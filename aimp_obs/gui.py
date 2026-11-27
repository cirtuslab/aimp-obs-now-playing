"""AIMP Prism Deck — pywebview (Edge WebView2) GPU-accelerated control panel.

Replaces the legacy Tkinter main window with a frameless, Windows-11 rounded,
holographic vinyl audio deck while keeping 100% compatibility with ``main.py``,
``OverlayServer``, ``SettingsStore``, ``TrayIcon`` and the on-demand ``FloatingOverlay``.
"""

from __future__ import annotations

import base64
import os
import socket
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .aimp_api import (
    CMD_NEXT,
    CMD_PLAYPAUSE,
    CMD_PREV,
    CMD_STOP,
    PROP_PLAYER_POSITION,
    AimpClient,
    AlbumArtReceiver,
)
from .cover import CoverStore
from .demo import demo_cover_bytes, demo_snapshot
from .floating_host import FloatingOverlayHost
from .overlay import THEMES, OverlayConfig
from .paths import icon_path
from .settings import SettingsStore
from .state import StateHub
from .theme import (
    DARK_PALETTE,
    apply_win11_frameless_style,
    copy_to_clipboard_win32,
    enumerate_system_fonts,
    extract_cover_palette,
)
from .tray import TrayIcon
from .webui import load_webui_html

# Backwards-compatible alias kept for callers/tests referencing COLORS
COLORS = DARK_PALETTE


class StudioBridge:
    """JavaScript-to-Python API object exposed via ``window.pywebview.api``."""

    def __init__(self, app: "App") -> None:
        self._app = app

    # ------------------------------------------------------------- Bootstrap & Poll

    def get_bootstrap(self) -> Dict[str, Any]:
        return self._app.build_bootstrap()

    def poll_state(self, client_cover_ts: int = -1) -> Dict[str, Any]:
        return self._app.build_poll_payload(client_cover_ts)

    def poll_floating(self, client_cover_ts: int = -1) -> Dict[str, Any]:
        payload = self._app.build_poll_payload(client_cover_ts)
        payload["ui_theme"] = self._app._ui_mode
        payload["floating_lyric_font_anim"] = bool(
            getattr(self._app.settings, "floating_lyric_font_anim", True)
        )
        return payload

    def floating_toggle_lock(self) -> Dict[str, Any]:
        return {"ok": True, "locked": self._app.toggle_floating_lock()}

    def floating_set_scale(self, scale: float) -> Dict[str, Any]:
        return {"ok": True, "scale": self._app.set_floating_scale(float(scale))}

    def floating_set_opacity(self, opacity: float) -> Dict[str, Any]:
        return {"ok": True, "opacity": self._app.set_floating_opacity(float(opacity))}

    def floating_set_font_anim(self, enabled: bool) -> Dict[str, Any]:
        self._app.set_floating_font_anim(bool(enabled))
        return {"ok": True, "enabled": bool(enabled)}

    def floating_show_menu(self) -> Dict[str, Any]:
        return {"ok": self._app.show_floating_menu()}

    def floating_close(self) -> Dict[str, Any]:
        self._app.close_floating()
        return {"ok": True}

    # ------------------------------------------------------------- Player Control

    def player_cmd(self, action: str) -> Dict[str, Any]:
        ok = self._app.send_player_cmd(action)
        return {"ok": ok}

    def seek(self, ratio: float) -> Dict[str, Any]:
        ok = self._app.seek_ratio(float(ratio))
        return {"ok": ok}

    # ------------------------------------------------------------- UI & Overlay

    def set_ui_theme(self, mode: str) -> Dict[str, Any]:
        applied = self._app.set_ui_theme(mode)
        return {"ok": True, "ui_theme": applied}

    def update_overlay(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "overlay": self._app.update_overlay(patch)}

    def reset_overlay(self) -> Dict[str, Any]:
        return {"ok": True, "overlay": self._app.reset_overlay()}

    def toggle_demo(self) -> Dict[str, Any]:
        return {"ok": True, "demo": self._app.toggle_demo()}

    def toggle_floating(self) -> Dict[str, Any]:
        return {"ok": True, "floating": self._app.toggle_floating()}

    # ------------------------------------------------------------- Server & Export

    def toggle_server(self, port: int) -> Dict[str, Any]:
        return self._app.toggle_server(port)

    def save_runtime(self, port: int, refresh_ms: int, export_dir: str) -> Dict[str, Any]:
        return self._app.save_runtime(port, refresh_ms, export_dir)

    def choose_export_dir(self) -> Dict[str, Any]:
        return self._app.choose_export_dir()

    def open_export_dir(self) -> Dict[str, Any]:
        return {"ok": self._app.open_export_dir()}

    def open_url(self, kind: str = "overlay") -> Dict[str, Any]:
        return {"ok": self._app.open_url(kind)}

    def copy_text(self, text: str) -> Dict[str, Any]:
        return {"ok": copy_to_clipboard_win32(str(text or ""))}

    # ------------------------------------------------------------- Mobile Devices

    def get_mobile_state(self) -> Dict[str, Any]:
        return self._app.mobile_state()

    def toggle_mobile(self, enabled: bool) -> Dict[str, Any]:
        return self._app.toggle_mobile(bool(enabled))

    def device_action(self, action: str, device_id: str) -> Dict[str, Any]:
        return self._app.device_action(action, device_id)

    # ------------------------------------------------------------- Window / Tray

    def window_minimize(self) -> Dict[str, Any]:
        self._app.minimize_to_tray()
        return {"ok": True}

    def window_close(self) -> Dict[str, Any]:
        self._app.request_close()
        return {"ok": True}


class App:
    """pywebview-powered AIMP Prism Deck GUI with Win32 tray & floating overlay host."""

    def __init__(
        self,
        client: AimpClient,
        receiver: AlbumArtReceiver,
        state_hub: StateHub,
        cover_store: CoverStore,
        server,
        export_dir: Path,
        refresh_ms: int = 300,
        settings: Optional[SettingsStore] = None,
    ) -> None:
        self.client = client
        self.receiver = receiver
        self.state_hub = state_hub
        self.cover_store = cover_store
        self.server = server
        self.export_dir = Path(export_dir)
        self.refresh_ms = max(100, int(refresh_ms))
        self.settings = settings or SettingsStore()

        if getattr(self.server, "config", None) is None:
            self.server.config = OverlayConfig()

        self._ui_mode = "light" if getattr(self.settings, "ui_theme", "dark") == "light" else "dark"
        self._window = None
        self._tray: Optional[TrayIcon] = None
        self._in_tray = False
        self._closing = False
        self._lock = threading.Lock()

        self._demo_active = False
        self._real_cover: Optional[bytes] = None
        self._last_snap: Optional[Dict[str, Any]] = None
        self._cached_cover_ts: int = -1
        self._cached_cover_data_url: str = ""
        self._cached_palette: Dict[str, str] = {
            "primary": "#FF9F19", "secondary": "#38BDF8", "glow": "#A855F7",
        }
        self._fonts_cache: Optional[list] = None

        self.bridge = StudioBridge(self)
        self._floating_host = FloatingOverlayHost(self.bridge, app=self)

    # ------------------------------------------------------------ Mainloop

    def mainloop(self, debug: bool = False) -> None:
        """Create the frameless WebView2 window and enter pywebview's event loop."""
        import webview

        bg_hex = "#eef2f9" if self._ui_mode == "light" else "#07090f"
        self._window = webview.create_window(
            title="AIMP Now Playing → OBS",
            html=load_webui_html(),
            js_api=self.bridge,
            width=820,
            height=520,
            min_size=(740, 470),
            resizable=True,
            frameless=True,
            easy_drag=False,
            shadow=True,
            background_color=bg_hex,
        )
        self._window.events.shown += self._on_shown
        self._window.events.minimized += self._on_minimized
        self._window.events.closing += self._on_closing

        ico = icon_path()
        icon_arg = str(ico) if ico.exists() else None
        try:
            webview.start(
                gui="edgechromium",
                debug=debug,
                private_mode=True,
                icon=icon_arg,
            )
        finally:
            self._cleanup()

    def _window_hwnd(self) -> int:
        win = self._window
        if win is None:
            return 0
        native = getattr(win, "native", None)
        if native is None:
            return 0
        try:
            handle = getattr(native, "Handle", None)
            if handle is not None:
                return int(handle.ToInt64())
        except Exception:
            # Handle may not be created yet or already disposed.
            return 0
        return 0

    def _on_shown(self) -> None:
        hwnd = self._window_hwnd()
        if hwnd:
            apply_win11_frameless_style(hwnd, dark=(self._ui_mode == "dark"))

    def _on_minimized(self) -> None:
        if not self._closing and not self._in_tray:
            self.minimize_to_tray()

    def _on_closing(self) -> None:
        self._closing = True
        self._cleanup()

    def _cleanup(self) -> None:
        self._closing = True
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                # Tray thread may already have exited during shutdown.
                pass
            self._tray = None
        try:
            self._floating_host.close()
        except Exception:
            # Floating overlay host may already be stopped.
            pass
        try:
            self._save_settings()
        except Exception:
            # Ignore disk errors while shutting down.
            pass

    # ------------------------------------------------------------ Tray Logic

    def _ensure_tray(self) -> TrayIcon:
        if self._tray is None:
            self._tray = TrayIcon(
                "AIMP Now Playing → OBS",
                icon_path(),
                on_show=self.restore_from_tray,
                on_quit=self.request_close,
            )
        return self._tray

    def minimize_to_tray(self) -> None:
        if self._closing or self._in_tray:
            return
        if not self._ensure_tray().show("已最小化到托盘，双击图标恢复窗口"):
            # Fallback to standard minimize when Windows shell tray is unavailable.
            win = self._window
            if win is not None:
                try:
                    win.minimize()
                except Exception:
                    # Ignore window state race during fallback minimize.
                    pass
            return
        self._in_tray = True
        win = self._window
        if win is not None:
            try:
                win.evaluate_js("window.__PRISM_SET_PAUSED__ && window.__PRISM_SET_PAUSED__(true)")
            except Exception:
                # WebView may be busy or hidden already.
                pass
            try:
                win.hide()
            except Exception:
                # Ignore WinForms state race during hide.
                pass
        if self._floating_host.is_open:
            self._floating_host.ensure_visible()

    def restore_from_tray(self) -> None:
        if self._tray is not None:
            self._tray.hide()
        self._in_tray = False
        win = self._window
        if win is not None:
            try:
                win.show()
                win.restore()
            except Exception:
                # Window might be closing while tray click arrived.
                return
            hwnd = self._window_hwnd()
            if hwnd:
                apply_win11_frameless_style(hwnd, dark=(self._ui_mode == "dark"))
            try:
                win.evaluate_js("window.__PRISM_SET_PAUSED__ && window.__PRISM_SET_PAUSED__(false)")
            except Exception:
                # Ignore JS bridge error during restore.
                pass

    def request_close(self) -> None:
        self._closing = True
        win = self._window
        if win is not None:
            try:
                win.destroy()
            except Exception:
                # Window may already be destroyed.
                pass

    # ------------------------------------------------------------ Data & State

    def _cover_bundle(self, force_ts: int = -1) -> Tuple[int, str, Dict[str, str]]:
        raw, mime, ts = self.cover_store.get()
        if ts != self._cached_cover_ts or not self._cached_cover_data_url:
            web_bytes, web_mime = self.cover_store.web_image()
            b64 = base64.b64encode(web_bytes).decode("ascii")
            self._cached_cover_ts = ts
            self._cached_cover_data_url = f"data:{web_mime};base64,{b64}"
            self._cached_palette = extract_cover_palette(raw or web_bytes)
        if force_ts == self._cached_cover_ts:
            return self._cached_cover_ts, "", self._cached_palette
        return self._cached_cover_ts, self._cached_cover_data_url, self._cached_palette

    def _current_snapshot(self) -> Dict[str, Any]:
        demo = bool(getattr(self.server.config, "demo", False))
        with self._lock:
            if demo != self._demo_active:
                self._demo_active = demo
                if demo:
                    self._real_cover = self.cover_store.get()[0]
                    self.cover_store.update(demo_cover_bytes())
                elif self._real_cover is not None:
                    self.cover_store.update(self._real_cover)
        snap = demo_snapshot() if demo else self.state_hub.snapshot()
        self._last_snap = snap
        return snap

    def _server_info(self) -> Dict[str, Any]:
        running = bool(getattr(self.server, "running", False))
        port = int(getattr(self.server, "port", 8765))
        url = self.server.url if running else f"http://127.0.0.1:{port}/"
        return {"running": running, "port": port, "url": url}

    def build_bootstrap(self) -> Dict[str, Any]:
        if self._fonts_cache is None:
            self._fonts_cache = enumerate_system_fonts()
        snap = self._current_snapshot()
        ts, data_url, palette = self._cover_bundle(force_ts=-1)
        devs = getattr(self.server, "devices", None)
        pending_count = len(devs.pending()) if (devs and devs.enabled) else 0
        return {
            "ui_theme": self._ui_mode,
            "themes": THEMES,
            "fonts": self._fonts_cache,
            "overlay": self.server.config.to_dict(),
            "server": self._server_info(),
            "refresh_ms": self.refresh_ms,
            "export_dir": str(self.export_dir),
            "floating": self._floating_host.is_open,
            "snapshot": snap,
            "cover_ts": ts,
            "cover_data_url": data_url,
            "palette": palette,
            "pending_count": pending_count,
        }

    def build_poll_payload(self, client_cover_ts: int = -1) -> Dict[str, Any]:
        snap = self._current_snapshot()
        ts, data_url, palette = self._cover_bundle(force_ts=client_cover_ts)
        devs = getattr(self.server, "devices", None)
        pending_count = len(devs.pending()) if (devs and devs.enabled) else 0
        payload: Dict[str, Any] = {
            "snapshot": snap,
            "cover_ts": ts,
            "floating": self._floating_host.is_open,
            "server": self._server_info(),
            "overlay": self.server.config.to_dict(),
            "pending_count": pending_count,
        }
        if data_url:
            payload["cover_data_url"] = data_url
            payload["palette"] = palette
        return payload

    # ------------------------------------------------------------ Commands

    def send_player_cmd(self, action: str) -> bool:
        mapping = {
            "prev": CMD_PREV,
            "playpause": CMD_PLAYPAUSE,
            "next": CMD_NEXT,
            "stop": CMD_STOP,
        }
        cmd = mapping.get(str(action or "").lower())
        if cmd is None:
            return False
        try:
            if not self.client.connected:
                self.client.detect()
            self.client.send_command(cmd)
            return True
        except Exception:
            return False

    def seek_ratio(self, ratio: float) -> bool:
        snap = self._last_snap or self._current_snapshot()
        duration = int(snap.get("duration_ms") or 0)
        if duration <= 0:
            return False
        clamped = max(0.0, min(1.0, float(ratio)))
        target_ms = int(duration * clamped)
        if self._demo_active:
            return True
        try:
            if self.client.connected:
                self.client.set_property(PROP_PLAYER_POSITION, target_ms)
                return True
        except Exception:
            return False
        return False

    def set_ui_theme(self, mode: str) -> str:
        self._ui_mode = "light" if str(mode).lower() == "light" else "dark"
        self.settings.ui_theme = self._ui_mode
        self._save_settings()
        hwnd = self._window_hwnd()
        if hwnd:
            apply_win11_frameless_style(hwnd, dark=(self._ui_mode == "dark"))
        return self._ui_mode

    def update_overlay(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(patch, dict):
            self.server.config.update_from_dict(patch)
            self._save_settings()
        return self.server.config.to_dict()

    def reset_overlay(self) -> Dict[str, Any]:
        self.server.config.update_from_dict(OverlayConfig().to_dict())
        self._save_settings()
        return self.server.config.to_dict()

    def toggle_demo(self) -> bool:
        new_val = not bool(getattr(self.server.config, "demo", False))
        self.server.config.demo = new_val
        self._save_settings()
        return new_val

    def toggle_floating(self) -> bool:
        return self._floating_host.toggle()

    def toggle_floating_lock(self) -> bool:
        return self._floating_host.toggle_lock()

    def set_floating_scale(self, scale: float) -> float:
        return self._floating_host.set_scale(scale)

    def set_floating_opacity(self, opacity: float) -> float:
        return self._floating_host.set_opacity(opacity)

    def set_floating_font_anim(self, enabled: bool) -> None:
        self.settings.floating_lyric_font_anim = bool(enabled)
        self._save_settings()

    def show_floating_menu(self) -> bool:
        return self._floating_host.show_context_menu()

    def close_floating(self) -> None:
        self._floating_host.close()

    # ------------------------------------------------------------ Server & Files

    def _save_settings(self) -> None:
        self.settings.port = int(getattr(self.server, "port", self.settings.port))
        self.settings.refresh_ms = self.refresh_ms
        self.settings.export_dir = str(self.export_dir)
        self.settings.ui_theme = self._ui_mode
        self.settings.overlay = self.server.config
        self.settings.save()

    def save_runtime(self, port: int, refresh_ms: int, export_dir: str) -> Dict[str, Any]:
        try:
            p = int(port)
            if 1 <= p <= 65535:
                self.settings.port = p
        except (TypeError, ValueError):
            pass
        try:
            self.refresh_ms = max(100, int(refresh_ms))
        except (TypeError, ValueError):
            pass
        cleaned = (export_dir or "").strip()
        if cleaned:
            new_dir = Path(cleaned)
            if new_dir != self.export_dir:
                self.export_dir = new_dir
                if self.state_hub.exporter:
                    self.state_hub.exporter = type(self.state_hub.exporter)(self.export_dir)
        self._save_settings()
        return {"ok": True, "refresh_ms": self.refresh_ms, "export_dir": str(self.export_dir)}

    def toggle_server(self, port: int) -> Dict[str, Any]:
        if self.server.running:
            self.server.stop()
            return {"ok": True, "server": self._server_info()}
        try:
            p = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "error": "端口无效，请输入 1-65535 之间的数字"}
        if not 1 <= p <= 65535:
            return {"ok": False, "error": "端口必须在 1-65535 之间"}
        self.server.port = p
        if self.server.start():
            self._save_settings()
            return {"ok": True, "server": self._server_info()}
        return {"ok": False, "error": "端口被占用，请更换其他端口"}

    def choose_export_dir(self) -> Dict[str, Any]:
        win = self._window
        if win is None:
            return {"ok": False, "path": ""}
        try:
            import webview

            res = win.create_file_dialog(
                webview.FileDialog.FOLDER,
                directory=str(self.export_dir),
            )
            chosen = ""
            if isinstance(res, (list, tuple)) and res:
                chosen = str(res[0])
            elif isinstance(res, str):
                chosen = res
            if chosen:
                self.export_dir = Path(chosen)
                if self.state_hub.exporter:
                    self.state_hub.exporter = type(self.state_hub.exporter)(self.export_dir)
                self._save_settings()
                return {"ok": True, "path": chosen}
        except Exception:
            return {"ok": False, "path": ""}
        return {"ok": False, "path": ""}

    def open_export_dir(self) -> bool:
        try:
            self.export_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.export_dir))
            return True
        except Exception:
            return False

    def open_url(self, kind: str = "overlay") -> bool:
        base = self._server_info()["url"].rstrip("/")
        target = f"{base}/preview" if kind == "preview" else f"{base}/"
        try:
            os.startfile(target)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ Mobile Companion

    @staticmethod
    def _lan_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
            finally:
                s.close()
        except Exception:
            return "127.0.0.1"

    def mobile_state(self) -> Dict[str, Any]:
        devs = self.server.devices
        enabled = bool(devs and devs.enabled)
        url = f"http://{self._lan_ip()}:{self.server.port}/m"
        return {
            "enabled": enabled,
            "url": url,
            "pending": devs.pending() if enabled else [],
            "approved": devs.approved() if enabled else [],
        }

    def toggle_mobile(self, enabled: bool) -> Dict[str, Any]:
        devs = self.server.devices
        on = bool(enabled)
        devs.enabled = on
        self.settings.mobile_enabled = on
        self._save_settings()
        loopback = ("127.0.0.1", "localhost", "::1")
        if on and self.server.host in loopback:
            self.server.host = "0.0.0.0"
            self.server.stop()
            if not self.server.start():
                self.server.host = "127.0.0.1"
                self.server.start()
        elif not on and self.server.host not in loopback:
            self.server.host = "127.0.0.1"
            self.server.stop()
            self.server.start()
        return self.mobile_state()

    def device_action(self, action: str, device_id: str) -> Dict[str, Any]:
        devs = self.server.devices
        ok = False
        if action == "approve":
            ok = devs.approve(device_id)
        elif action == "reject":
            ok = devs.reject(device_id)
        elif action == "remove":
            ok = devs.remove(device_id)
        state = self.mobile_state()
        state["ok"] = ok
        return state
