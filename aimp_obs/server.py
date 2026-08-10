"""Local HTTP server that feeds the OBS Browser Source and the mobile page."""

from __future__ import annotations

import json
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from .cover import CoverStore
from .devices import DeviceManager
from .mobile import mobile_icon_png, render_manifest, render_mobile
from .overlay import OverlayConfig, render_gallery, render_overlay

PROTECTED_GET = {"/api/state", "/cover.png", "/lyrics.lrc", "/api/config"}


class _Handler(BaseHTTPRequestHandler):
    server_version = "AIMPNowPlaying/1.0"

    # --------------------------------------------------------- helpers
    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "127.0.0.1"

    def _is_loopback(self) -> bool:
        return self._client_ip() in ("127.0.0.1", "::1", "localhost")

    def _query(self) -> dict:
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def _device_token(self) -> str:
        tok = self.headers.get("X-AIMP-Token", "")
        if not tok:
            q = self._query()
            tok = q.get("token", [""])[0]
        return (tok or "").strip()

    def _mobile_on(self) -> bool:
        devs = getattr(self.server, "devices", None)
        return bool(devs and devs.enabled)

    def _auth_ok(self) -> bool:
        """Loopback always allowed; LAN needs an approved device token."""
        if self._is_loopback():
            return True
        if not self._mobile_on():
            return False
        devs = self.server.devices
        return devs.check_token(self._device_token()) is not None

    def _send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _deny(self, message: str) -> None:
        self._send_json({"ok": False, "error": message}, 403)

    # --------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html", "/overlay"):
                self._send_text(render_overlay(), "text/html; charset=utf-8")
            elif path in ("/preview", "/themes"):
                self._send_text(render_gallery(), "text/html; charset=utf-8")
            elif path in ("/m", "/mobile"):
                if not self._mobile_on():
                    self._deny("手机连接未开启，请在电脑端 GUI 中启用")
                    return
                self._send_text(render_mobile(), "text/html; charset=utf-8")
            elif path == "/m/manifest.webmanifest":
                if not self._mobile_on():
                    self._deny("手机连接未开启")
                    return
                self._send_text(render_manifest(), "application/manifest+json; charset=utf-8")
            elif path == "/m/icon.png":
                if not self._mobile_on():
                    self._deny("手机连接未开启")
                    return
                data = mobile_icon_png()
                if not data:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            elif path == "/api/device/status":
                if not self._mobile_on():
                    self._deny("手机连接未开启")
                    return
                q = self._query()
                device_id = q.get("id", [""])[0]
                self._send_json(self.server.devices.status(device_id))
            elif path in PROTECTED_GET:
                if not self._auth_ok():
                    self._deny("设备未授权")
                    return
                if path == "/api/state":
                    self._send_text(
                        json.dumps(self.server.state_hub.snapshot(), ensure_ascii=False),
                        "application/json; charset=utf-8",
                    )
                elif path == "/cover.png":
                    data, mime, _ts = self.server.cover_store.get()
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                elif path == "/lyrics.lrc":
                    raw = self.server.state_hub.snapshot().get("lyrics_raw", "")
                    self._send_text(raw or "", "text/plain; charset=utf-8")
                elif path == "/api/config":
                    self._send_text(
                        json.dumps(self.server.config.to_dict(), ensure_ascii=False),
                        "application/json; charset=utf-8",
                    )
            elif path == "/health":
                self._send_text(json.dumps({"ok": True}), "application/json")
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # --------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/device/register":
                if not self._mobile_on():
                    self._deny("手机连接未开启")
                    return
                data = self._read_json()
                self._send_json(
                    self.server.devices.register(data.get("id", ""), data.get("name", ""))
                )
            elif path == "/api/control":
                if not self._mobile_on():
                    self._deny("手机连接未开启")
                    return
                devs = getattr(self.server, "devices", None)
                if not devs or devs.check_token(self._device_token()) is None:
                    self._deny("设备未授权")
                    return
                data = self._read_json()
                action = str(data.get("action", ""))
                cb = getattr(self.server, "control_cb", None)
                if not cb or cb(action) is False:
                    self._send_json({"ok": False, "error": "unsupported action"}, 400)
                else:
                    self._send_json({"ok": True, "action": action})
            elif path == "/api/config":
                # style writes are only allowed from this machine
                if not self._is_loopback():
                    self._deny("仅允许本机修改配置")
                    return
                data = self._read_json()
                self.server.config.update_from_dict(data)
                self._send_json(self.server.config.to_dict())
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


class OverlayServer:
    def __init__(
        self,
        state_hub,
        cover_store: CoverStore,
        host: str = "127.0.0.1",
        port: int = 8765,
        config: Optional[OverlayConfig] = None,
        devices: Optional[DeviceManager] = None,
        control_cb: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.state_hub = state_hub
        self.cover_store = cover_store
        self.host = host
        self.port = port
        self.config = config or OverlayConfig()
        self.devices = devices or DeviceManager()
        self.control_cb = control_cb
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host
        return f"http://{host}:{self.port}/"

    def start(self) -> bool:
        if self._httpd:
            return True
        httpd = None
        for attempt in range(20):
            try:
                httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
                break
            except OSError:
                self.port += 1
        if httpd is None:
            return False
        httpd.state_hub = self.state_hub
        httpd.cover_store = self.cover_store
        httpd.config = self.config
        httpd.devices = self.devices
        httpd.control_cb = self.control_cb
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, name="OverlayServer", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._thread = None


def find_free_port(start: int = 8765) -> int:
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start
