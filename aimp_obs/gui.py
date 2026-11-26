"""Compact jewel-like dual-theme animated control panel for AIMP Now Playing -> OBS.

Features a compact 680x440 top-pill studio layout, 60fps single-canvas directional
crossfade+slide tab transitions (zero widget pop-in), expanding circular radial ripple
Dark/Light theme switching, breathing cover aura, 7-bar peak-hold equalizer, glowing
shimmer seek bar, smooth scrolling lyrics, and zero extra dependencies.
"""

from __future__ import annotations

import ctypes
import os
import socket
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, font as tkfont, messagebox
from typing import Dict, Optional, Tuple

import customtkinter as ctk
from PIL import Image

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
from .overlay import THEMES, OverlayConfig
from .paths import icon_path
from .settings import SettingsStore
from .state import StateHub, format_time
from .theme import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    OVERLAY_THEME_META,
    IconCache,
    animate_window_alpha,
    apply_native_titlebar_theme,
    atomic_widget_swap,
    capture_region_surface,
    get_palette,
)
from .tray import TrayIcon
from .widgets import (
    AnimatedProgressBar,
    CoverStage,
    EqualizerWidget,
    LyricsStage,
    OverlayPreviewCanvas,
    SegmentedTabBar,
    StatusPulseDot,
    ThemeToggleSwitch,
    ToastBanner,
    TransitionCurtain,
)

# Backwards-compatible alias
COLORS = DARK_PALETTE


def T(key: str) -> Tuple[str, str]:
    """Return a CustomTkinter (light, dark) color pair for a semantic token."""
    return (LIGHT_PALETTE[key], DARK_PALETTE[key])


class _DeviceRow:
    """Reusable row for the mobile device lists (updates in place without flicker)."""

    def __init__(self, master, font) -> None:
        self.frame = ctk.CTkFrame(
            master, fg_color=T("card_alt"), corner_radius=10,
            border_width=1, border_color=T("border"),
        )
        self.label = ctk.CTkLabel(
            self.frame, text="", font=font, text_color=T("text"), anchor="w",
        )
        self.label.pack(side="left", padx=10, pady=6, fill="x", expand=True)
        self._font = font
        self._buttons: list = []
        self._packed = False
        self._sig = None

    def _button(self, index: int):
        while len(self._buttons) <= index:
            btn = ctk.CTkButton(
                self.frame, text="", width=52, height=26, corner_radius=8,
                font=self._font, fg_color=T("button"), hover_color=T("button_hover"),
                text_color=T("text"),
            )
            btn.pack(side="right", padx=(0, 6), pady=5)
            self._buttons.append(btn)
        return self._buttons[index]

    def update(self, text: str, actions) -> None:
        """``actions``: sequence of (label, command, fg_color, hover_color, text_color)."""
        sig = (text, tuple((a[0], a[2], a[4]) for a in actions))
        if sig != self._sig:
            self._sig = sig
            self.label.configure(text=text)
            for i, (label, command, fg, hv, tc) in enumerate(actions):
                self._button(i).configure(
                    text=label, command=command, fg_color=fg, hover_color=hv, text_color=tc,
                )
        for btn in self._buttons[len(actions):]:
            if btn.winfo_manager():
                btn.pack_forget()

    def show(self, visible: bool) -> None:
        if visible == self._packed:
            return
        self._packed = visible
        if visible:
            self.frame.pack(fill="x", padx=2, pady=3)
        else:
            self.frame.pack_forget()


class App(ctk.CTk):
    """Compact jewel-like AIMP Now Playing -> OBS Studio Control Panel."""

    _NAV_ITEMS = (
        ("now_playing", "播放"),
        ("overlay", "样式"),
        ("obs", "OBS"),
        ("mobile", "手机"),
    )

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
        self.settings = settings or SettingsStore()
        self._ui_mode = "light" if getattr(self.settings, "ui_theme", "dark") == "light" else "dark"
        self._palette = get_palette(self._ui_mode)

        ctk.set_appearance_mode(self._ui_mode)
        ctk.set_default_color_theme("blue")

        super().__init__()
        self.client = client
        self.receiver = receiver
        self.state_hub = state_hub
        self.cover_store = cover_store
        self.server = server
        self.export_dir = Path(export_dir)
        self.refresh_ms = refresh_ms

        if getattr(self.server, "config", None) is None:
            self.server.config = OverlayConfig()

        self._closing = False
        self._settings_ready = False
        self._floating = None
        self._font_dialog = None
        self._cover_ts = -1
        self._last_snap: Optional[dict] = None
        self._last_ui: dict = {}
        self._last_progress = -1
        self._last_time_cur = ""
        self._last_time_dur = ""
        self._demo_active = False
        self._real_cover: Optional[bytes] = None
        self._anchor_pos = 0
        self._anchor_wall = 0.0
        self._anchor_playing = False
        self._is_playing_icon = False
        self._tray = None
        self._in_tray = False
        self._tray_show_event = threading.Event()
        self._tray_quit_event = threading.Event()
        self._active_tab = "now_playing"
        self._mobile_url_text = ""
        self._pending_rows: list = []
        self._approved_rows: list = []
        self._icons = IconCache()

        self.title("AIMP Now Playing → OBS")
        self.geometry("680x448")
        self.minsize(640, 420)
        self.configure(fg_color=T("bg"))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            pass

        # Compact crisp typography
        self._f_brand = ctk.CTkFont(family="Segoe UI", size=14, weight="bold")
        self._f_title = ctk.CTkFont(family="Segoe UI", size=18, weight="bold")
        self._f_artist = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        self._f_section = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        self._f_body = ctk.CTkFont(family="Segoe UI", size=12)
        self._f_body_bold = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        self._f_small = ctk.CTkFont(family="Segoe UI", size=11)
        self._f_small_bold = ctk.CTkFont(family="Segoe UI", size=11, weight="bold")
        self._f_caption = ctk.CTkFont(family="Segoe UI", size=10)
        self._f_mono = ctk.CTkFont(family="Consolas", size=11)

        self._build_ui()
        self._settings_ready = True
        self._set_window_icon(self)
        self.after(15, self._animate_startup)
        self.after(60, self._tick)
        self.after(150, self._poll)
        self.after(1800, self._mobile_poll)

    def _animate_startup(self) -> None:
        if self._closing:
            return
        apply_native_titlebar_theme(self, self._ui_mode == "dark")
        animate_window_alpha(self, 0.0, 1.0, duration_ms=210, steps=11)

    def _set_window_icon(self, win) -> None:
        icon = icon_path()
        if icon.exists():
            try:
                win.iconbitmap(str(icon))
            except Exception:
                pass

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        # Root container sits inside self so _root_curtain can capture & ripple over it seamlessly
        self._root_container = ctk.CTkFrame(self, fg_color=T("bg"), corner_radius=0)
        self._root_container.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self._root_container.grid_rowconfigure(0, weight=0)
        self._root_container.grid_rowconfigure(1, weight=0)
        self._root_container.grid_rowconfigure(2, weight=1)
        self._root_container.grid_columnconfigure(0, weight=1)

        self._build_header(self._root_container)

        # Hairline divider under top bar
        ctk.CTkFrame(self._root_container, height=1, fg_color=T("border"), corner_radius=0).grid(
            row=1, column=0, sticky="ew",
        )

        # Stacked workspace container (all 4 pages permanently pre-mounted)
        self._workspace = ctk.CTkFrame(self._root_container, fg_color=T("bg"), corner_radius=0)
        self._workspace.grid(row=2, column=0, sticky="nsew")

        self._pages: Dict[str, ctk.CTkBaseClass] = {}
        self._pages["now_playing"] = self._build_now_playing_page(self._workspace)
        self._pages["overlay"] = self._build_overlay_page(self._workspace)
        self._pages["obs"] = self._build_obs_page(self._workspace)
        self._pages["mobile"] = self._build_mobile_page(self._workspace)

        for page in self._pages.values():
            page.place(x=0, y=0, relwidth=1.0, relheight=1.0)

        # Single-canvas floating DWM transition curtain (zero widget pop-in!)
        self._curtain = TransitionCurtain(self, bg=self._palette["bg"])
        self._toast = ToastBanner(self._workspace, self._palette)

        self._switch_tab("now_playing", instant=True)
        self._style_refresh()
        self._refresh_mobile_view()
        self._sync_quick_dock()

    # ------------------------------------------------------------ Top Header

    def _build_header(self, parent) -> None:
        hdr = ctk.CTkFrame(parent, height=52, fg_color=T("sidebar"), corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)
        hdr.grid_columnconfigure(2, weight=1)
        self._header = hdr

        # Left: Brand + Live Pulse Status
        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=(14, 6), pady=9)
        brand_ico = self._icons.get("brand", DARK_PALETTE["accent"], LIGHT_PALETTE["accent"], 22)
        ctk.CTkLabel(left, text="", image=brand_ico, width=22).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(left, text="AIMP", font=self._f_brand, text_color=T("text")).pack(side="left", padx=(0, 8))

        pill = ctk.CTkFrame(
            left, fg_color=T("card_alt"), corner_radius=10,
            border_width=1, border_color=T("border"),
        )
        pill.pack(side="left")
        self._status_dot = StatusPulseDot(pill, self._palette, bg_key="card_alt")
        self._status_dot.pack(side="left", padx=(7, 4), pady=4)
        self.lbl_badge = ctk.CTkLabel(
            pill, text="未连接", font=self._f_caption, text_color=T("danger"),
        )
        self.lbl_badge.pack(side="left", padx=(0, 8), pady=3)

        # Center: Gliding Segmented Pill Tab Bar
        self._tab_bar = SegmentedTabBar(
            hdr, self._NAV_ITEMS, self._palette,
            on_select=self._switch_tab, width=240, height=32, bg_key="sidebar",
        )
        self._tab_bar.grid(row=0, column=1, pady=10)

        # Right: Compact Quick Dock (Float, Demo, Moon/Sun Theme Switch)
        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=(6, 14), pady=9)

        self._theme_switch = ThemeToggleSwitch(
            right,
            is_light=(self._ui_mode == "light"),
            palette=self._palette,
            on_toggle=self._on_theme_toggle,
            bg_key="sidebar",
        )
        self._theme_switch.pack(side="right", padx=(6, 0))

        self._ico_demo_idle = self._icons.get("sparkles", DARK_PALETTE["text_secondary"], LIGHT_PALETTE["text_secondary"], 14)
        self._ico_demo_on = self._icons.get("sparkles", DARK_PALETTE["accent"], LIGHT_PALETTE["accent"], 14)
        self.btn_demo_quick = ctk.CTkButton(
            right, text="演示", image=self._ico_demo_idle, compound="left",
            width=58, height=28, corner_radius=9, font=self._f_caption,
            fg_color=T("card_alt"), hover_color=T("card_hover"),
            border_width=1, border_color=T("border"), text_color=T("text_secondary"),
            command=self._toggle_demo_quick,
        )
        self.btn_demo_quick.pack(side="right", padx=(4, 0))

        self._ico_float_idle = self._icons.get("float", DARK_PALETTE["text_secondary"], LIGHT_PALETTE["text_secondary"], 14)
        self._ico_float_on = self._icons.get("float", DARK_PALETTE["accent"], LIGHT_PALETTE["accent"], 14)
        self.btn_floating = ctk.CTkButton(
            right, text="悬浮窗", image=self._ico_float_idle, compound="left",
            width=68, height=28, corner_radius=9, font=self._f_caption,
            fg_color=T("card_alt"), hover_color=T("card_hover"),
            border_width=1, border_color=T("border"), text_color=T("text_secondary"),
            command=self._toggle_floating,
        )
        self.btn_floating.pack(side="right", padx=(0, 2))

    # ------------------------------------------------- Tab Switch (60fps!)

    @staticmethod
    def _page_host(page):
        return getattr(page, "_parent_frame", page)

    def _switch_tab(self, key: str, instant: bool = False) -> None:
        if key not in self._pages:
            return
        if not instant and key == self._active_tab:
            return

        keys = [item[0] for item in self._NAV_ITEMS]
        old_idx = keys.index(self._active_tab) if self._active_tab in keys else 0
        new_idx = keys.index(key) if key in keys else 0
        direction = 1 if new_idx >= old_idx else -1
        self._active_tab = key
        self._tab_bar.set_active(key, instant=instant)

        target_host = self._page_host(self._pages[key])

        if instant:
            target_host.lift()
            if self._toast._visible:
                self._toast._frame.lift()
            return

        # Pre-update target page data before capturing its offscreen bitmap
        if key == "overlay":
            self._overlay_preview.update_preview(self.server.config, self._last_snap)
        elif key == "mobile":
            self._refresh_mobile_view()

        # Freeze workspace behind native Win32 GDI overlay while target paints offscreen,
        # then run hardware-fast 60+ FPS AlphaBlend slide+crossfade (<1ms/frame)!
        surf_old = capture_region_surface(self, self._workspace)
        if surf_old is not None and self._curtain.show_static(surf_old, self._workspace, bg=self._palette["bg"]):
            target_host.lift()
            if self._toast._visible:
                self._toast._frame.lift()
            self.update()
            surf_new = capture_region_surface(self, self._workspace)
            if surf_new is not None:
                def _after_slide() -> None:
                    if self._toast._visible:
                        self._toast._frame.lift()

                self._curtain.play_slide_crossfade(
                    surf_old, surf_new, direction, self._palette["bg"],
                    duration_ms=230, on_done=_after_slide,
                )
                return
            self._curtain.hide()
        elif surf_old is not None:
            surf_old.release()

        # Graceful fallback if offscreen capture is unavailable
        def _fallback_lift() -> None:
            target_host.lift()
            if self._toast._visible:
                self._toast._frame.lift()

        atomic_widget_swap(self._workspace, _fallback_lift)

    # ------------------------------------------------- Page 1: Now Playing

    def _build_now_playing_page(self, parent) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color=T("bg"), corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        # Hero Player Card
        hero = ctk.CTkFrame(
            page, fg_color=T("card"), corner_radius=18,
            border_width=1, border_color=T("border"),
        )
        hero.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        hero.grid_columnconfigure(1, weight=1)

        # Left: Breathing ambient CoverStage
        self._cover_stage = CoverStage(hero, self._palette, cover_size=118, pad=20, radius=18)
        self._cover_stage.grid(row=0, column=0, padx=(8, 4), pady=8)

        # Right: Visualizer + Metadata + Shimmer Progress + Transport
        info = ctk.CTkFrame(hero, fg_color="transparent")
        info.grid(row=0, column=1, sticky="nsew", padx=(4, 16), pady=12)
        info.grid_columnconfigure(0, weight=1)

        # Top row: 7-bar Equalizer + Meta + Quick Copy / Service pills
        top_row = ctk.CTkFrame(info, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._equalizer = EqualizerWidget(top_row, self._palette, width=46, height=16)
        self._equalizer.pack(side="left", padx=(0, 8))
        self.lbl_meta = ctk.CTkLabel(
            top_row, text="AIMP Remote API", font=self._f_caption,
            text_color=T("text_muted"), anchor="w",
        )
        self.lbl_meta.pack(side="left")

        ico_copy = self._icons.get("copy", DARK_PALETTE["text"], LIGHT_PALETTE["text"], 12)
        ctk.CTkButton(
            top_row, text=" OBS", image=ico_copy, compound="left",
            width=54, height=24, corner_radius=7, font=self._f_caption,
            fg_color=T("card_alt"), hover_color=T("card_hover"),
            border_width=1, border_color=T("border"), text_color=T("text"),
            command=self._copy_url,
        ).pack(side="right", padx=(6, 0))

        self._ico_power_on = self._icons.get("power", DARK_PALETTE["success"], LIGHT_PALETTE["success"], 12)
        self._ico_power_off = self._icons.get("power", DARK_PALETTE["text_muted"], LIGHT_PALETTE["text_muted"], 12)
        self.btn_service_pill = ctk.CTkButton(
            top_row, text=" :8765", image=self._ico_power_on, compound="left",
            width=66, height=24, corner_radius=7, font=self._f_caption,
            fg_color=T("success_soft"), hover_color=T("card_hover"),
            border_width=1, border_color=T("border"), text_color=T("success"),
            command=self._toggle_server,
        )
        self.btn_service_pill.pack(side="right")

        # Title & Artist
        self.lbl_title = ctk.CTkLabel(
            info, text="未在播放", font=self._f_title, text_color=T("text"),
            anchor="w", justify="left", wraplength=430,
        )
        self.lbl_title.grid(row=1, column=0, sticky="ew")

        self.lbl_artist = ctk.CTkLabel(
            info, text="请启动 AIMP，或点击右上角「演示」预览",
            font=self._f_artist, text_color=T("accent"),
            anchor="w", justify="left", wraplength=430,
        )
        self.lbl_artist.grid(row=2, column=0, sticky="ew", pady=(1, 8))

        # Glowing Shimmer Seekable Progress Bar
        self._progress_bar = AnimatedProgressBar(
            info, self._palette, on_seek=self._on_seek, bg_key="card",
        )
        self._progress_bar.grid(row=3, column=0, sticky="ew")

        # Bottom bar: Time + Centered/Left Transport Controls + AIMP version
        ctrl_row = ctk.CTkFrame(info, fg_color="transparent")
        ctrl_row.grid(row=4, column=0, sticky="ew", pady=(4, 0))

        self._ico_prev = self._icons.get("prev", DARK_PALETTE["text"], LIGHT_PALETTE["text"], 14)
        self._ico_next = self._icons.get("next", DARK_PALETTE["text"], LIGHT_PALETTE["text"], 14)
        self._ico_stop = self._icons.get("stop", DARK_PALETTE["text_secondary"], LIGHT_PALETTE["text_secondary"], 12)
        self._ico_play = self._icons.get("play", DARK_PALETTE["accent_fg"], LIGHT_PALETTE["accent_fg"], 15)
        self._ico_pause = self._icons.get("pause", DARK_PALETTE["accent_fg"], LIGHT_PALETTE["accent_fg"], 15)

        self.btn_prev = ctk.CTkButton(
            ctrl_row, text="", image=self._ico_prev, width=34, height=34, corner_radius=17,
            fg_color=T("button"), hover_color=T("button_hover"),
            command=lambda: self._cmd(CMD_PREV),
        )
        self.btn_prev.pack(side="left", padx=(0, 7))

        self.btn_play = ctk.CTkButton(
            ctrl_row, text="", image=self._ico_play, width=44, height=36, corner_radius=18,
            fg_color=T("accent"), hover_color=T("accent_hover"),
            command=lambda: self._cmd(CMD_PLAYPAUSE),
        )
        self.btn_play.pack(side="left", padx=(0, 7))

        self.btn_next = ctk.CTkButton(
            ctrl_row, text="", image=self._ico_next, width=34, height=34, corner_radius=17,
            fg_color=T("button"), hover_color=T("button_hover"),
            command=lambda: self._cmd(CMD_NEXT),
        )
        self.btn_next.pack(side="left", padx=(0, 7))

        self.btn_stop = ctk.CTkButton(
            ctrl_row, text="", image=self._ico_stop, width=30, height=30, corner_radius=15,
            fg_color="transparent", hover_color=T("button"),
            border_width=1, border_color=T("border"),
            command=lambda: self._cmd(CMD_STOP),
        )
        self.btn_stop.pack(side="left")

        self.lbl_time_dur = ctk.CTkLabel(
            ctrl_row, text="0:00", font=self._f_mono, text_color=T("text_muted"),
        )
        self.lbl_time_dur.pack(side="right")
        ctk.CTkLabel(ctrl_row, text=" / ", font=self._f_mono, text_color=T("text_muted")).pack(side="right")
        self.lbl_time_cur = ctk.CTkLabel(
            ctrl_row, text="0:00", font=self._f_mono, text_color=T("text_secondary"),
        )
        self.lbl_time_cur.pack(side="right")

        # Compact Lyrics Theater Card
        lyr_card = ctk.CTkFrame(
            page, fg_color=T("card"), corner_radius=18,
            border_width=1, border_color=T("border"),
        )
        lyr_card.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 14))
        lyr_card.grid_columnconfigure(0, weight=1)
        lyr_card.grid_rowconfigure(1, weight=1)

        lyr_hdr = ctk.CTkFrame(lyr_card, fg_color="transparent")
        lyr_hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 2))
        ctk.CTkLabel(lyr_hdr, text="实时歌词", font=self._f_section, text_color=T("text_secondary")).pack(side="left")
        self.lbl_lyric_badge = ctk.CTkLabel(
            lyr_hdr, text="等待歌词", font=self._f_caption,
            text_color=T("text_muted"), fg_color=T("card_alt"), corner_radius=6,
            padx=7, pady=1,
        )
        self.lbl_lyric_badge.pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            lyr_hdr, text="样式设置 →", height=22, width=76, corner_radius=6,
            font=self._f_caption, fg_color="transparent", hover_color=T("card_alt"),
            text_color=T("accent"), command=lambda: self._switch_tab("overlay"),
        ).pack(side="right")

        self._lyrics_stage = LyricsStage(lyr_card, self._palette, height=96)
        self._lyrics_stage.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))

        return page

    # ----------------------------------------------- Page 2: Overlay Studio

    def _build_overlay_page(self, parent) -> ctk.CTkScrollableFrame:
        page = ctk.CTkScrollableFrame(parent, fg_color=T("bg"), corner_radius=0)

        # Compact top bar
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(10, 8))
        ctk.CTkLabel(top, text="覆盖页样式", font=self._f_brand, text_color=T("text")).pack(side="left")
        ctk.CTkLabel(top, text="· 实时同步至 OBS", font=self._f_caption, text_color=T("text_muted")).pack(side="left", padx=(6, 0))

        ico_rst = self._icons.get("reset", DARK_PALETTE["text"], LIGHT_PALETTE["text"], 12)
        ctk.CTkButton(
            top, text=" 重置", image=ico_rst, compound="left",
            height=28, width=68, corner_radius=8, font=self._f_caption,
            fg_color=T("card"), hover_color=T("card_hover"),
            border_width=1, border_color=T("border"), text_color=T("text"),
            command=self._reset_style,
        ).pack(side="right", padx=(6, 0))

        ico_ext = self._icons.get("external", DARK_PALETTE["accent_fg"], LIGHT_PALETTE["accent_fg"], 12)
        ctk.CTkButton(
            top, text=" 浏览器预览", image=ico_ext, compound="left",
            height=28, width=92, corner_radius=8, font=self._f_caption,
            fg_color=T("accent"), hover_color=T("accent_hover"),
            text_color=T("accent_fg"), command=self._open_browser,
        ).pack(side="right")

        # Live 16:9 Mini Preview Card
        prev_card = ctk.CTkFrame(
            page, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        prev_card.pack(fill="x", padx=14, pady=(0, 10))
        self._overlay_preview = OverlayPreviewCanvas(prev_card, self._palette, height=138)
        self._overlay_preview.pack(fill="x", padx=8, pady=8)

        # Compact 4x2 Theme Grid
        theme_card = ctk.CTkFrame(
            page, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        theme_card.pack(fill="x", padx=14, pady=(0, 10))
        tgrid = ctk.CTkFrame(theme_card, fg_color="transparent")
        tgrid.pack(fill="x", padx=10, pady=10)
        for col in range(4):
            tgrid.grid_columnconfigure(col, weight=1, uniform="tc")

        self._theme_cards: Dict[str, ctk.CTkButton] = {}
        for idx, (key, meta) in enumerate(THEMES.items()):
            r, c = divmod(idx, 4)
            swatch_hex = OVERLAY_THEME_META.get(key, {}).get("accent", "#FF9F19")
            swatch_ico = self._icons.solid("dot", swatch_hex, 10)
            btn = ctk.CTkButton(
                tgrid, text=f" {meta['label']}", image=swatch_ico, compound="left",
                anchor="w", height=32, corner_radius=9, font=self._f_caption,
                fg_color=T("card_alt"), hover_color=T("card_hover"),
                border_width=1, border_color=T("border"), text_color=T("text"),
                command=lambda k=key: self._select_overlay_theme(k),
            )
            btn.grid(row=r, column=c, sticky="ew", padx=3, pady=3)
            self._theme_cards[key] = btn

        # Two-column: Position+Cover | Colors+Font
        mid = ctk.CTkFrame(page, fg_color="transparent")
        mid.pack(fill="x", padx=14, pady=(0, 10))
        mid.grid_columnconfigure(0, weight=4, uniform="mc")
        mid.grid_columnconfigure(1, weight=6, uniform="mc")

        pos_card = ctk.CTkFrame(
            mid, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        pos_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ctk.CTkLabel(pos_card, text="位置与封面", font=self._f_small_bold, text_color=T("text")).pack(anchor="w", padx=12, pady=(10, 6))

        pgrid = ctk.CTkFrame(pos_card, fg_color=T("card_alt"), corner_radius=10)
        pgrid.pack(padx=12, pady=(0, 8))
        self._pos_buttons: Dict[str, ctk.CTkButton] = {}
        pos_rows = [
            ["top-left", "top-center", "top-right"],
            ["left", "center", "right"],
            ["bottom-left", "bottom-center", "bottom-right"],
        ]
        pos_labels = {
            "top-left": "左上", "top-center": "上", "top-right": "右上",
            "left": "左", "center": "中", "right": "右",
            "bottom-left": "左下", "bottom-center": "下", "bottom-right": "右下",
        }
        for ri, row in enumerate(pos_rows):
            for ci, key in enumerate(row):
                b = ctk.CTkButton(
                    pgrid, text=pos_labels[key], width=44, height=26, corner_radius=7,
                    font=self._f_caption, fg_color=T("button"), hover_color=T("button_hover"),
                    text_color=T("text"), command=lambda k=key: self._set_pos(k),
                )
                b.grid(row=ri, column=ci, padx=2, pady=2)
                self._pos_buttons[key] = b

        crow = ctk.CTkFrame(pos_card, fg_color="transparent")
        crow.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(crow, text="封面", font=self._f_caption, text_color=T("text_secondary")).pack(side="left", padx=(0, 6))
        self._cover_buttons: Dict[str, ctk.CTkButton] = {}
        for key, label in (("left", "左"), ("right", "右"), ("top", "上")):
            b = ctk.CTkButton(
                crow, text=label, width=38, height=24, corner_radius=7,
                font=self._f_caption, fg_color=T("button"), hover_color=T("button_hover"),
                text_color=T("text"), command=lambda k=key: self._set_coverside(k),
            )
            b.pack(side="left", padx=2)
            self._cover_buttons[key] = b

        col_card = ctk.CTkFrame(
            mid, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        col_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ctk.CTkLabel(col_card, text="配色与字体", font=self._f_small_bold, text_color=T("text")).pack(anchor="w", padx=12, pady=(10, 6))

        arow = ctk.CTkFrame(col_card, fg_color="transparent")
        arow.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(arow, text="强调", width=36, anchor="w", font=self._f_caption, text_color=T("text_secondary")).pack(side="left")
        self._accent_buttons: Dict[str, ctk.CTkButton] = {}
        for color in ("#ff9f19", "#1ed760", "#5cc8ff", "#ff2da0", "#2563eb", "#ffffff"):
            b = ctk.CTkButton(
                arow, text="", width=22, height=22, corner_radius=11,
                fg_color=color, hover_color=color,
                border_width=1, border_color=T("border_strong"),
                command=lambda c=color: self._set_accent(c),
            )
            b.pack(side="left", padx=(0, 5))
            self._accent_buttons[color] = b
        ctk.CTkButton(
            arow, text="取色…", width=50, height=24, corner_radius=7,
            font=self._f_caption, fg_color=T("button"), hover_color=T("button_hover"),
            text_color=T("text"), command=self._pick_accent,
        ).pack(side="left", padx=(2, 0))

        brow = ctk.CTkFrame(col_card, fg_color="transparent")
        brow.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(brow, text="背景", width=36, anchor="w", font=self._f_caption, text_color=T("text_secondary")).pack(side="left")
        self._btn_bg = ctk.CTkButton(
            brow, text="透明", width=64, height=24, corner_radius=7,
            font=self._f_caption, fg_color=T("button"), hover_color=T("button_hover"),
            text_color=T("text"), command=lambda: self._set_bg(""),
        )
        self._btn_bg.pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            brow, text="自定义…", width=58, height=24, corner_radius=7,
            font=self._f_caption, fg_color=T("button"), hover_color=T("button_hover"),
            text_color=T("text"), command=self._pick_bg,
        ).pack(side="left", padx=(0, 10))

        prow = ctk.CTkFrame(col_card, fg_color="transparent")
        prow.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(prow, text="面板", width=36, anchor="w", font=self._f_caption, text_color=T("text_secondary")).pack(side="left")
        self._btn_panel = ctk.CTkButton(
            prow, text="默认", width=64, height=24, corner_radius=7,
            font=self._f_caption, fg_color=T("button"), hover_color=T("button_hover"),
            text_color=T("text"), command=lambda: self._set_panel(""),
        )
        self._btn_panel.pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            prow, text="自定义…", width=58, height=24, corner_radius=7,
            font=self._f_caption, fg_color=T("button"), hover_color=T("button_hover"),
            text_color=T("text"), command=self._pick_panel,
        ).pack(side="left")

        frow = ctk.CTkFrame(col_card, fg_color="transparent")
        frow.pack(fill="x", padx=12, pady=(2, 10))
        ctk.CTkLabel(frow, text="字体", width=36, anchor="w", font=self._f_caption, text_color=T("text_secondary")).pack(side="left")
        self._font_families = ["默认"] + sorted(
            set(f for f in tkfont.families() if not f.startswith("@"))
        )
        self._lyric_font_name = ctk.CTkLabel(
            frow, text="默认", anchor="w", font=self._f_small_bold, text_color=T("text"),
        )
        self._lyric_font_name.pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            frow, text="选择字体…", width=72, height=24, corner_radius=7,
            font=self._f_caption, fg_color=T("button"), hover_color=T("button_hover"),
            text_color=T("text"), command=self._pick_lyric_font,
        ).pack(side="right")

        # Dimensions & Switches Card
        dim_card = ctk.CTkFrame(
            page, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        dim_card.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkLabel(dim_card, text="尺寸与显隐", font=self._f_small_bold, text_color=T("text")).pack(anchor="w", padx=12, pady=(10, 6))

        drow = ctk.CTkFrame(dim_card, fg_color="transparent")
        drow.pack(fill="x", padx=12, pady=(0, 10))
        self._var_width = ctk.StringVar()
        self._var_fontsize = ctk.StringVar()
        self._var_margin = ctk.StringVar()
        self._var_radius = ctk.StringVar()
        self._var_coverradius = ctk.StringVar()
        for i, (lab, var) in enumerate((
            ("宽度", self._var_width), ("字号", self._var_fontsize),
            ("边距", self._var_margin), ("圆角", self._var_radius), ("封面圆角", self._var_coverradius),
        )):
            drow.grid_columnconfigure(i, weight=1)
            cell = ctk.CTkFrame(drow, fg_color="transparent")
            cell.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 5, 0))
            ctk.CTkLabel(cell, text=lab, font=self._f_caption, text_color=T("text_muted"), anchor="w").pack(anchor="w")
            ent = ctk.CTkEntry(
                cell, textvariable=var, height=28, corner_radius=7,
                placeholder_text="默认",
                fg_color=T("card_alt"), border_color=T("border"),
                text_color=T("text"), font=self._f_caption,
            )
            ent.pack(fill="x", pady=(2, 0))
            ent.bind("<Return>", self._style_apply)
            ent.bind("<FocusOut>", self._style_apply)

        sgrid = ctk.CTkFrame(dim_card, fg_color="transparent")
        sgrid.pack(fill="x", padx=12, pady=(0, 10))
        for c in range(4):
            sgrid.grid_columnconfigure(c, weight=1)
        self._switches: Dict[str, ctk.CTkSwitch] = {}
        for idx, (cfg_key, label) in enumerate((
            ("hide_cover", "隐藏封面"), ("hide_title", "隐藏标题"),
            ("hide_state", "隐藏状态"), ("hide_progress", "隐藏进度"),
            ("hide_lyrics", "隐藏歌词"), ("hide_when_stopped", "停止隐藏"),
            ("demo", "演示模式"),
        )):
            r, c = divmod(idx, 4)
            sw = ctk.CTkSwitch(
                sgrid, text=label, font=self._f_caption, switch_width=32, switch_height=16,
                text_color=T("text"), fg_color=("#CBD5E1", "#2B3346"),
                progress_color=T("accent"),
                button_color=("#FFFFFF", "#F2F4F8"),
                button_hover_color=("#F8FAFC", "#FFFFFF"),
                command=lambda k=cfg_key: self._on_switch(k),
            )
            sw.grid(row=r, column=c, sticky="w", pady=4, padx=(0, 4))
            self._switches[cfg_key] = sw

        return page

    # ------------------------------------------------- Page 3: OBS & Export

    def _build_obs_page(self, parent) -> ctk.CTkScrollableFrame:
        page = ctk.CTkScrollableFrame(parent, fg_color=T("bg"), corner_radius=0)

        # Card 1: OBS Browser Source
        url_card = ctk.CTkFrame(
            page, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        url_card.pack(fill="x", padx=14, pady=(12, 10))
        ctk.CTkLabel(url_card, text="OBS 浏览器源地址", font=self._f_small_bold, text_color=T("text")).pack(anchor="w", padx=14, pady=(12, 6))

        url_box = ctk.CTkFrame(
            url_card, fg_color=T("card_alt"), corner_radius=10,
            border_width=1, border_color=T("border"),
        )
        url_box.pack(fill="x", padx=14, pady=(0, 8))
        self.lbl_obs_url = ctk.CTkLabel(
            url_box, text=self.server.url, font=self._f_mono,
            text_color=T("accent"), anchor="w",
        )
        self.lbl_obs_url.pack(side="left", padx=10, pady=7, fill="x", expand=True)

        ico_copy = self._icons.get("copy", DARK_PALETTE["accent_fg"], LIGHT_PALETTE["accent_fg"], 12)
        ctk.CTkButton(
            url_box, text=" 复制", image=ico_copy, compound="left",
            width=66, height=26, corner_radius=7, font=self._f_caption,
            fg_color=T("accent"), hover_color=T("accent_hover"), text_color=T("accent_fg"),
            command=self._copy_url,
        ).pack(side="right", padx=(4, 6), pady=4)

        acts = ctk.CTkFrame(url_card, fg_color="transparent")
        acts.pack(fill="x", padx=14, pady=(0, 12))
        ico_ext = self._icons.get("external", DARK_PALETTE["text"], LIGHT_PALETTE["text"], 12)
        ctk.CTkButton(
            acts, text=" 打开覆盖页", image=ico_ext, compound="left",
            height=28, corner_radius=8, font=self._f_caption,
            fg_color=T("button"), hover_color=T("button_hover"), text_color=T("text"),
            command=self._open_browser,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            acts, text=" 主题画廊 (/preview)", image=ico_ext, compound="left",
            height=28, corner_radius=8, font=self._f_caption,
            fg_color=T("button"), hover_color=T("button_hover"), text_color=T("text"),
            command=self._open_preview_gallery,
        ).pack(side="left")
        ctk.CTkLabel(
            acts, text="建议 OBS 尺寸 460×240", font=self._f_caption, text_color=T("text_muted"),
        ).pack(side="right")

        # Card 2: Service Params
        srv_card = ctk.CTkFrame(
            page, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        srv_card.pack(fill="x", padx=14, pady=(0, 10))
        srow = ctk.CTkFrame(srv_card, fg_color="transparent")
        srow.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(srow, text="端口", font=self._f_small, text_color=T("text_secondary")).pack(side="left")
        self.var_port = ctk.StringVar(value=str(getattr(self.server, "port", 8765)))
        self._entry_port = ctk.CTkEntry(
            srow, textvariable=self.var_port, width=72, height=30, corner_radius=8,
            fg_color=T("card_alt"), border_color=T("border"),
            text_color=T("text"), font=self._f_mono,
        )
        self._entry_port.pack(side="left", padx=(6, 16))
        self._entry_port.bind("<Return>", self._save_runtime_settings)
        self._entry_port.bind("<FocusOut>", self._save_runtime_settings)

        ctk.CTkLabel(srow, text="刷新 (ms)", font=self._f_small, text_color=T("text_secondary")).pack(side="left")
        self.var_refresh = ctk.StringVar(value=str(self.refresh_ms))
        self._entry_refresh = ctk.CTkEntry(
            srow, textvariable=self.var_refresh, width=72, height=30, corner_radius=8,
            fg_color=T("card_alt"), border_color=T("border"),
            text_color=T("text"), font=self._f_mono,
        )
        self._entry_refresh.pack(side="left", padx=(6, 16))
        self._entry_refresh.bind("<Return>", self._save_runtime_settings)
        self._entry_refresh.bind("<FocusOut>", self._save_runtime_settings)

        self.btn_server = ctk.CTkButton(
            srow, text="停止服务" if self.server.running else "启动服务",
            width=88, height=30, corner_radius=8, font=self._f_small_bold,
            fg_color=T("accent"), hover_color=T("accent_hover"), text_color=T("accent_fg"),
            command=self._toggle_server,
        )
        self.btn_server.pack(side="right")

        # Card 3: Export Dir
        exp_card = ctk.CTkFrame(
            page, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        exp_card.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkLabel(exp_card, text="纯文件导出目录", font=self._f_small_bold, text_color=T("text")).pack(anchor="w", padx=14, pady=(12, 6))

        erow = ctk.CTkFrame(exp_card, fg_color="transparent")
        erow.pack(fill="x", padx=14, pady=(0, 8))
        self.var_export = ctk.StringVar(value=str(self.export_dir))
        self._entry_export = ctk.CTkEntry(
            erow, textvariable=self.var_export, height=30, corner_radius=8,
            fg_color=T("card_alt"), border_color=T("border"),
            text_color=T("text"), font=self._f_small,
        )
        self._entry_export.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._entry_export.bind("<Return>", self._save_runtime_settings)
        self._entry_export.bind("<FocusOut>", self._save_runtime_settings)

        ctk.CTkButton(
            erow, text="选择…", width=62, height=30, corner_radius=8,
            font=self._f_caption, fg_color=T("button"), hover_color=T("button_hover"),
            text_color=T("text"), command=self._choose_export,
        ).pack(side="left", padx=(0, 5))

        ico_fld = self._icons.get("folder", DARK_PALETTE["text"], LIGHT_PALETTE["text"], 12)
        ctk.CTkButton(
            erow, text=" 打开", image=ico_fld, compound="left",
            width=62, height=30, corner_radius=8, font=self._f_caption,
            fg_color=T("button"), hover_color=T("button_hover"), text_color=T("text"),
            command=self._open_export_dir,
        ).pack(side="left")

        chips = ctk.CTkFrame(exp_card, fg_color="transparent")
        chips.pack(fill="x", padx=14, pady=(0, 12))
        for fname in ("nowplaying.json", "nowplaying.txt", "cover.png", "lyrics.lrc"):
            ctk.CTkLabel(
                chips, text=fname, font=self._f_mono,
                text_color=T("text_secondary"), fg_color=T("card_alt"),
                corner_radius=6, padx=8, pady=2,
            ).pack(side="left", padx=(0, 5))

        return page

    # --------------------------------------------------- Page 4: Mobile

    def _build_mobile_page(self, parent) -> ctk.CTkScrollableFrame:
        page = ctk.CTkScrollableFrame(parent, fg_color=T("bg"), corner_radius=0)

        mcard = ctk.CTkFrame(
            page, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        mcard.pack(fill="x", padx=14, pady=(12, 10))

        mrow = ctk.CTkFrame(mcard, fg_color="transparent")
        mrow.pack(fill="x", padx=14, pady=(12, 8))
        self._mobile_switch = ctk.CTkSwitch(
            mrow, text="启用局域网手机连接", command=self._toggle_mobile,
            font=self._f_small_bold, text_color=T("text"),
            fg_color=("#CBD5E1", "#2B3346"), progress_color=T("accent"),
            button_color=("#FFFFFF", "#F2F4F8"),
            button_hover_color=("#F8FAFC", "#FFFFFF"),
        )
        self._mobile_switch.pack(side="left")
        if self.server.devices.enabled:
            self._mobile_switch.select()
        else:
            self._mobile_switch.deselect()

        url_box = ctk.CTkFrame(
            mcard, fg_color=T("card_alt"), corner_radius=10,
            border_width=1, border_color=T("border"),
        )
        url_box.pack(fill="x", padx=14, pady=(0, 8))
        self.lbl_mobile_url = ctk.CTkLabel(
            url_box, text=f"http://{self._lan_ip()}:{self.server.port}/m",
            font=self._f_mono, text_color=T("accent"), anchor="w",
        )
        self.lbl_mobile_url.pack(side="left", padx=10, pady=7, fill="x", expand=True)
        ico_copy = self._icons.get("copy", DARK_PALETTE["text"], LIGHT_PALETTE["text"], 12)
        ctk.CTkButton(
            url_box, text=" 复制", image=ico_copy, compound="left",
            width=66, height=26, corner_radius=7, font=self._f_caption,
            fg_color=T("button"), hover_color=T("button_hover"), text_color=T("text"),
            command=self._copy_mobile_url,
        ).pack(side="right", padx=(4, 6), pady=4)

        self.lbl_mobile_hint = ctk.CTkLabel(
            mcard, text="", font=self._f_caption, text_color=T("text_muted"), anchor="w",
        )
        self.lbl_mobile_hint.pack(anchor="w", padx=14, pady=(0, 12))

        # Two-column device lists
        drow = ctk.CTkFrame(page, fg_color="transparent")
        drow.pack(fill="x", padx=14, pady=(0, 14))
        drow.grid_columnconfigure(0, weight=1, uniform="devc")
        drow.grid_columnconfigure(1, weight=1, uniform="devc")

        pcard = ctk.CTkFrame(
            drow, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        pcard.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ctk.CTkLabel(pcard, text="待审核设备", font=self._f_small_bold, text_color=T("text")).pack(anchor="w", padx=12, pady=(10, 4))
        self.mobile_pending = ctk.CTkFrame(pcard, fg_color="transparent")
        self.mobile_pending.pack(fill="x", padx=10, pady=(0, 10))
        self.lbl_no_pending = ctk.CTkLabel(
            self.mobile_pending, text="暂无待审核设备",
            font=self._f_caption, text_color=T("text_muted"), anchor="w",
        )

        acard = ctk.CTkFrame(
            drow, fg_color=T("card"), corner_radius=14,
            border_width=1, border_color=T("border"),
        )
        acard.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ctk.CTkLabel(acard, text="已授权设备", font=self._f_small_bold, text_color=T("text")).pack(anchor="w", padx=12, pady=(10, 4))
        self.mobile_approved = ctk.CTkFrame(acard, fg_color="transparent")
        self.mobile_approved.pack(fill="x", padx=10, pady=(0, 10))
        self.lbl_no_approved = ctk.CTkLabel(
            self.mobile_approved, text="暂无已授权设备",
            font=self._f_caption, text_color=T("text_muted"), anchor="w",
        )

        return page

    # ---------------------------------------- Circular Radial Ripple Theme!

    def _on_theme_toggle(self, is_light: bool) -> None:
        mode = "light" if is_light else "dark"

        # Compute exact origin coordinates of the Moon/Sun switch relative to root container
        try:
            ox = (self._theme_switch.winfo_rootx() - self._root_container.winfo_rootx()) + self._theme_switch.winfo_width() // 2
            oy = (self._theme_switch.winfo_rooty() - self._root_container.winfo_rooty()) + self._theme_switch.winfo_height() // 2
        except Exception:
            ox, oy = self.winfo_width() - 36, 26

        surf_old = capture_region_surface(self, self._root_container)
        if surf_old is not None and self._curtain.show_static(surf_old, self._root_container, bg=self._palette["bg"]):
            self._apply_ui_theme(mode, announce=False)
            self.update()
            surf_new = capture_region_surface(self, self._root_container)
            if surf_new is not None:
                def _done() -> None:
                    self._toast.show(
                        "已切换到亮色模式" if mode == "light" else "已切换到深色模式",
                        "accent",
                    )

                self._curtain.play_radial_ripple(
                    surf_old, surf_new, (ox, oy), self._palette["accent"],
                    duration_ms=340, on_done=_done,
                )
                return
            self._curtain.hide()
        elif surf_old is not None:
            surf_old.release()

        self._apply_ui_theme(mode, announce=True)

    def _apply_ui_theme(self, mode: str, announce: bool = False) -> None:
        mode = "light" if str(mode).lower() == "light" else "dark"
        self._ui_mode = mode
        self._palette = get_palette(mode)

        def _recolor() -> None:
            ctk.set_appearance_mode(mode)
            apply_native_titlebar_theme(self, mode == "dark")
            self._theme_switch.apply_theme(self._palette)
            self._tab_bar.apply_theme(self._palette)
            self._status_dot.apply_theme(self._palette)
            self._cover_stage.apply_theme(self._palette)
            self._equalizer.apply_theme(self._palette, bg_key="card")
            self._progress_bar.apply_theme(self._palette)
            self._lyrics_stage.apply_theme(self._palette)
            self._overlay_preview.apply_theme(self._palette)
            self._toast.apply_theme(self._palette)

        if self._curtain.active:
            _recolor()
        else:
            atomic_widget_swap(self, _recolor)

        self.settings.ui_theme = mode
        if self._settings_ready:
            try:
                self.settings.save()
            except Exception:
                pass

        if announce:
            self._toast.show("已切换到亮色模式" if mode == "light" else "已切换到深色模式", "accent")

    # ------------------------------------------------------ Backwards Compat

    def _open_settings_window(self) -> None:
        self._switch_tab("overlay")

    def _open_mobile_window(self) -> None:
        self._switch_tab("mobile")

    # -------------------------------------------------------- Overlay Style

    def _select_overlay_theme(self, key: str) -> None:
        self.server.config.theme = key
        self._style_refresh()
        self._toast.show(f"已切换主题：{THEMES[key]['label']}", "accent")

    def _set_pos(self, key: str) -> None:
        self.server.config.pos = key
        self._style_refresh()

    def _set_coverside(self, key: str) -> None:
        self.server.config.coverside = key
        self._style_refresh()

    def _set_accent(self, color: str) -> None:
        self.server.config.accent = color
        self.server.config.accent2 = color
        self._style_refresh()

    def _set_bg(self, color: str = "") -> None:
        self.server.config.bg = color
        self._style_refresh()

    def _set_panel(self, color: str = "") -> None:
        self.server.config.panel = color
        self._style_refresh()

    def _on_lyric_font(self, choice: str) -> None:
        self.server.config.lyric_font = "" if choice == "默认" else choice
        self._style_refresh()

    def _on_switch(self, key: str) -> None:
        setattr(self.server.config, key, self._switches[key].get() == 1)
        self._style_refresh()
        self._sync_quick_dock()

    def _toggle_demo_quick(self) -> None:
        new_val = not bool(getattr(self.server.config, "demo", False))
        self.server.config.demo = new_val
        self._style_refresh()
        self._sync_quick_dock()
        self._toast.show("已开启演示模式" if new_val else "已关闭演示模式", "accent")

    def _sync_quick_dock(self) -> None:
        float_on = self._floating is not None and getattr(self._floating, "closed", False) is False
        self.btn_floating.configure(
            text="悬浮中" if float_on else "悬浮窗",
            image=self._ico_float_on if float_on else self._ico_float_idle,
            fg_color=T("accent_soft") if float_on else T("card_alt"),
            border_color=T("accent") if float_on else T("border"),
            text_color=T("accent") if float_on else T("text_secondary"),
        )
        demo_on = bool(getattr(self.server.config, "demo", False))
        self.btn_demo_quick.configure(
            text="演示中" if demo_on else "演示",
            image=self._ico_demo_on if demo_on else self._ico_demo_idle,
            fg_color=T("accent_soft") if demo_on else T("card_alt"),
            border_color=T("accent") if demo_on else T("border"),
            text_color=T("accent") if demo_on else T("text_secondary"),
        )

    def _style_apply(self, _event=None) -> None:
        cfg = self.server.config

        def num(var: ctk.StringVar, default: int = 0) -> int:
            try:
                return max(0, int(var.get()))
            except Exception:
                return default

        cfg.width = num(self._var_width)
        cfg.fontsize = num(self._var_fontsize)
        cfg.margin = num(self._var_margin, 20)
        cfg.radius = num(self._var_radius)
        cfg.coverradius = num(self._var_coverradius)
        self._style_refresh()

    def _reset_style(self) -> None:
        self.server.config.update_from_dict(OverlayConfig().to_dict())
        self._style_refresh()
        self._sync_quick_dock()
        self._toast.show("已恢复默认覆盖页样式", "success")

    def _save_overlay(self) -> None:
        if not self._settings_ready:
            return
        try:
            self.settings.overlay = self.server.config
            self.settings.save()
        except Exception:
            pass

    def _style_refresh(self) -> None:
        cfg = self.server.config
        for key, btn in self._theme_cards.items():
            active = (key == cfg.theme)
            btn.configure(
                fg_color=T("accent_soft") if active else T("card_alt"),
                border_color=T("accent") if active else T("border"),
                text_color=T("accent") if active else T("text"),
            )
        for key, btn in self._pos_buttons.items():
            active = (key == cfg.pos)
            btn.configure(
                fg_color=T("accent") if active else T("button"),
                hover_color=T("accent_hover") if active else T("button_hover"),
                text_color=T("accent_fg") if active else T("text"),
            )
        for key, btn in self._cover_buttons.items():
            active = (key == cfg.coverside)
            btn.configure(
                fg_color=T("accent") if active else T("button"),
                hover_color=T("accent_hover") if active else T("button_hover"),
                text_color=T("accent_fg") if active else T("text"),
            )
        for color, btn in self._accent_buttons.items():
            active = color.lower() == (cfg.accent or "").lower()
            btn.configure(
                border_width=2 if active else 1,
                border_color=T("text") if active else T("border_strong"),
            )
        self._btn_bg.configure(text=cfg.bg if cfg.bg else "透明")
        self._btn_panel.configure(text=cfg.panel if cfg.panel else "默认")

        font_name = cfg.lyric_font if cfg.lyric_font in self._font_families else "默认"
        self._lyric_font_name.configure(text=font_name[:18])

        for key, sw in self._switches.items():
            if getattr(cfg, key):
                sw.select()
            else:
                sw.deselect()

        self._var_width.set(str(cfg.width or ""))
        self._var_fontsize.set(str(cfg.fontsize or ""))
        self._var_margin.set(str(cfg.margin or ""))
        self._var_radius.set(str(cfg.radius or ""))
        self._var_coverradius.set(str(cfg.coverradius or ""))
        self._overlay_preview.update_preview(cfg, self._last_snap)
        self._save_overlay()

    def _pick_bg(self) -> None:
        color = colorchooser.askcolor(
            color=self.server.config.bg or "#101010", parent=self, title="选择浏览器源背景色",
        )
        if color and color[1]:
            self._set_bg(color[1])

    def _pick_panel(self) -> None:
        color = colorchooser.askcolor(
            color=self.server.config.panel or "#171b24", parent=self, title="选择面板背景色",
        )
        if color and color[1]:
            self._set_panel(color[1])

    def _pick_accent(self) -> None:
        color = colorchooser.askcolor(
            color=self.server.config.accent or "#ff9f19", parent=self, title="选择强调色",
        )
        if color and color[1]:
            self._set_accent(color[1])

    # ------------------------------------------------------- Font Picker

    def _pick_lyric_font(self) -> None:
        if self._font_dialog is not None and self._font_dialog.winfo_exists():
            self._font_dialog.focus()
            return
        dlg = ctk.CTkToplevel(self)
        self._font_dialog = dlg
        dlg.title("选择歌词字体")
        dlg.geometry("380x460")
        dlg.minsize(340, 400)
        self._set_window_icon(dlg)
        dlg.configure(fg_color=T("bg"))
        dlg.transient(self)
        dlg.grab_set()
        try:
            dlg.attributes("-alpha", 0.0)
        except Exception:
            pass
        dlg.after(15, lambda: (
            apply_native_titlebar_theme(dlg, self._ui_mode == "dark"),
            animate_window_alpha(dlg, 0.0, 1.0, duration_ms=160, steps=8),
        ))

        search = ctk.CTkEntry(
            dlg, placeholder_text="搜索本机字体…", height=32, corner_radius=9,
            fg_color=T("card"), border_color=T("border"),
            text_color=T("text"), font=self._f_small,
        )
        search.pack(fill="x", padx=14, pady=(14, 8))

        list_frame = ctk.CTkFrame(
            dlg, fg_color=T("card"), corner_radius=12,
            border_width=1, border_color=T("border"),
        )
        list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        pal = self._palette
        listbox = tk.Listbox(
            list_frame, bg=pal["card"], fg=pal["text"],
            selectbackground=pal["accent"], selectforeground=pal["accent_fg"],
            relief="flat", highlightthickness=0,
            font=("Segoe UI", 10), activestyle="none",
        )
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        scrollbar.pack(side="right", fill="y", pady=6, padx=(0, 4))

        preview = ctk.CTkLabel(
            dlg, text="示例歌词 AaBb 中文预览", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=T("text"), fg_color=T("card"), corner_radius=9,
            padx=10, pady=6,
        )
        preview.pack(fill="x", padx=14, pady=(0, 8))

        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkButton(
            btns, text="默认", width=72, height=30, corner_radius=8,
            command=lambda: self._finish_font_pick(dlg, "默认"),
            fg_color=T("button"), hover_color=T("button_hover"),
            text_color=T("text"), font=self._f_small_bold,
        ).pack(side="left")
        ctk.CTkButton(
            btns, text="确定", width=76, height=30, corner_radius=8,
            command=lambda: self._font_pick_ok(dlg, listbox),
            fg_color=T("accent"), hover_color=T("accent_hover"),
            text_color=T("accent_fg"), font=self._f_small_bold,
        ).pack(side="right")
        ctk.CTkButton(
            btns, text="取消", width=68, height=30, corner_radius=8,
            command=lambda: self._close_font_dialog(dlg),
            fg_color=T("button"), hover_color=T("button_hover"),
            text_color=T("text"), font=self._f_small_bold,
        ).pack(side="right", padx=(0, 6))

        fonts = [f for f in self._font_families if f != "默认"]

        def refresh(keyword: str = "") -> None:
            listbox.delete(0, tk.END)
            kw = keyword.strip().lower()
            for f in fonts:
                if kw in f.lower():
                    listbox.insert(tk.END, f)
            current = self.server.config.lyric_font
            if current:
                for i in range(listbox.size()):
                    if listbox.get(i) == current:
                        listbox.selection_clear(0, tk.END)
                        listbox.selection_set(i)
                        listbox.see(i)
                        break

        def on_select(_event) -> None:
            sel = listbox.curselection()
            if sel:
                name = listbox.get(sel[0])
                try:
                    preview.configure(font=ctk.CTkFont(family=name, size=14))
                except Exception:
                    pass

        search.bind("<KeyRelease>", lambda _e: refresh(search.get()))
        listbox.bind("<<ListboxSelect>>", on_select)
        listbox.bind("<Double-Button-1>", lambda _e: self._font_pick_ok(dlg, listbox))
        dlg.bind("<Return>", lambda _e: self._font_pick_ok(dlg, listbox))
        dlg.bind("<Escape>", lambda _e: self._close_font_dialog(dlg))
        dlg.protocol("WM_DELETE_WINDOW", lambda: self._close_font_dialog(dlg))
        refresh()
        if self.server.config.lyric_font:
            search.insert(0, self.server.config.lyric_font)
        search.focus_set()

    def _font_pick_ok(self, dlg, listbox) -> None:
        sel = listbox.curselection()
        if sel:
            self._finish_font_pick(dlg, listbox.get(sel[0]))
        else:
            self._close_font_dialog(dlg)

    def _finish_font_pick(self, dlg, choice: str) -> None:
        self._on_lyric_font(choice)
        self._close_font_dialog(dlg)

    def _close_font_dialog(self, dlg) -> None:
        if self._font_dialog is dlg:
            self._font_dialog = None
        try:
            dlg.destroy()
        except Exception:
            pass

    # ------------------------------------------------------ Mobile Companion

    def _lan_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
            finally:
                s.close()
        except Exception:
            return "127.0.0.1"

    def _toggle_mobile(self) -> None:
        devs = self.server.devices
        on = bool(self._mobile_switch.get())
        devs.enabled = on
        self.settings.mobile_enabled = on
        self.settings.save()
        loopback = ("127.0.0.1", "localhost", "::1")
        if on and self.server.host in loopback:
            self.server.host = "0.0.0.0"
            self.server.stop()
            ok = self.server.start()
            if not ok:
                self.server.host = "127.0.0.1"
                self.server.start()
        elif not on and self.server.host not in loopback:
            self.server.host = "127.0.0.1"
            self.server.stop()
            self.server.start()
        self._refresh_mobile_view()
        self._toast.show("已开启手机连接" if on else "已关闭手机连接", "success" if on else "accent")

    def _mobile_poll(self) -> None:
        if self._closing:
            return
        if self.server.devices.enabled or self._active_tab == "mobile":
            self._refresh_mobile_view()
        self.after(2000, self._mobile_poll)

    @staticmethod
    def _sync_specs(rows: list, specs: list, make_row) -> None:
        for i, (text, actions) in enumerate(specs):
            if i >= len(rows):
                rows.append(make_row())
            rows[i].update(text, actions)
            rows[i].show(True)
        for row in rows[len(specs):]:
            row.show(False)

    @staticmethod
    def _sync_placeholder(label, visible: bool) -> None:
        if label is None:
            return
        packed = bool(label.winfo_manager())
        if visible and not packed:
            label.pack(anchor="w", padx=4, pady=4)
        elif not visible and packed:
            label.pack_forget()

    def _refresh_mobile_view(self) -> None:
        devs = self.server.devices
        if bool(self._mobile_switch.get()) != devs.enabled:
            if devs.enabled:
                self._mobile_switch.select()
            else:
                self._mobile_switch.deselect()
        url = f"http://{self._lan_ip()}:{self.server.port}/m"
        if url != self._mobile_url_text:
            self._mobile_url_text = url
            self.lbl_mobile_url.configure(text=url)

        pending = devs.pending() if devs.enabled else []
        approved = devs.approved() if devs.enabled else []
        self._tab_bar.set_badge("mobile", len(pending))

        hint = (
            "Safari「分享 → 添加到主屏幕」即可全屏使用。"
            if devs.enabled
            else "手机连接已关闭。开启后首次访问需在此点击「同意」。"
        )
        if self.lbl_mobile_hint.cget("text") != hint:
            self.lbl_mobile_hint.configure(text=hint)

        pending_specs = [
            (
                f"{dev.get('name', '?')} ({dev.get('id', '')[:8]})",
                [
                    ("同意", lambda d=dev: self._device_action("approve", d["id"]),
                     T("accent"), T("accent_hover"), T("accent_fg")),
                    ("拒绝", lambda d=dev: self._device_action("reject", d["id"]),
                     T("button"), T("button_hover"), T("text")),
                ],
            )
            for dev in pending
        ]
        approved_specs = [
            (
                f"{dev.get('name', '?')} ({dev.get('id', '')[:8]})",
                [
                    ("移除", lambda d=dev: self._device_action("remove", d["id"]),
                     T("danger_soft"), T("button_hover"), T("danger")),
                ],
            )
            for dev in approved
        ]
        self._sync_specs(
            self._pending_rows, pending_specs,
            lambda: _DeviceRow(self.mobile_pending, self._f_caption),
        )
        self._sync_specs(
            self._approved_rows, approved_specs,
            lambda: _DeviceRow(self.mobile_approved, self._f_caption),
        )
        self._sync_placeholder(self.lbl_no_pending, not pending_specs)
        self._sync_placeholder(self.lbl_no_approved, not approved_specs)

    def _device_action(self, action: str, device_id: str) -> None:
        devs = self.server.devices
        if action == "approve":
            devs.approve(device_id)
            self._toast.show("已授权该设备", "success")
        elif action == "reject":
            devs.reject(device_id)
            self._toast.show("已拒绝设备请求", "warning")
        elif action == "remove":
            devs.remove(device_id)
            self._toast.show("已移除设备授权", "accent")
        self._refresh_mobile_view()

    # ------------------------------------------------------- Runtime Actions

    def _toggle_floating(self) -> None:
        if self._floating is not None and getattr(self._floating, "closed", False) is False:
            self._floating.close(animated=True)
            self._floating = None
            self._sync_quick_dock()
            self._toast.show("已关闭桌面悬浮窗", "accent")
            return
        from .floating import FloatingOverlay

        self._floating = FloatingOverlay(
            self, self.state_hub, self.cover_store, self.server.config,
            self.refresh_ms, self.settings, self.client,
        )
        self._sync_quick_dock()
        self._toast.show("已打开桌面悬浮窗 (Ctrl+Shift+L 锁定)", "success")

    def _cmd(self, cmd: int) -> None:
        try:
            if not self.client.connected:
                self.client.detect()
            self.client.send_command(cmd)
        except Exception:
            pass

    def _on_seek(self, ratio: float) -> None:
        snap = self._last_snap
        if not snap or not snap.get("duration_ms"):
            return
        target_ms = int(snap["duration_ms"] * ratio)
        self._anchor_pos = target_ms
        self._anchor_wall = time.time()
        self.lbl_time_cur.configure(text=format_time(target_ms))
        if self._demo_active:
            return
        try:
            if self.client.connected:
                self.client.set_property(PROP_PLAYER_POSITION, target_ms)
        except Exception:
            pass

    def _save_runtime_settings(self, _event=None) -> None:
        try:
            self.settings.port = int(self.var_port.get())
        except ValueError:
            pass
        try:
            self.settings.refresh_ms = max(100, int(self.var_refresh.get()))
        except ValueError:
            pass
        try:
            new_dir = Path(self.var_export.get().strip() or str(self.export_dir))
            if new_dir != self.export_dir:
                self.export_dir = new_dir
                if self.state_hub.exporter:
                    self.state_hub.exporter = type(self.state_hub.exporter)(self.export_dir)
        except Exception:
            pass
        self.settings.export_dir = str(self.export_dir)
        try:
            self.settings.save()
        except Exception:
            pass

    def _toggle_server(self) -> None:
        if self.server.running:
            self.server.stop()
            self._sync_server_ui()
            self._toast.show("HTTP 服务已停止", "warning")
            return
        try:
            port = int(self.var_port.get())
        except ValueError:
            messagebox.showerror("端口无效", "请输入 1-65535 之间的端口号。")
            return
        if not 1 <= port <= 65535:
            messagebox.showerror("端口无效", "端口必须在 1-65535 之间。")
            return
        self.server.port = port
        if self.server.start():
            self.var_port.set(str(self.server.port))
            self._save_runtime_settings()
            self._sync_server_ui()
            self._toast.show(f"服务已启动：{self.server.url}", "success")
        else:
            messagebox.showerror("启动失败", "端口被占用，请换一个端口。")

    def _sync_server_ui(self) -> None:
        running = self.server.running
        url = self.server.url if running else f"http://127.0.0.1:{self.var_port.get()}/"
        if self._last_ui.get("server_running") == (running, url):
            return
        self._last_ui["server_running"] = (running, url)
        self.lbl_obs_url.configure(text=url)
        self.btn_server.configure(text="停止服务" if running else "启动服务")
        if running:
            self.btn_service_pill.configure(
                text=f" :{self.server.port}",
                image=self._ico_power_on,
                fg_color=T("success_soft"),
                text_color=T("success"),
            )
        else:
            self.btn_service_pill.configure(
                text=" 已停止",
                image=self._ico_power_off,
                fg_color=T("card_alt"),
                text_color=T("text_muted"),
            )

    def _copy_url(self) -> None:
        url = self.server.url if self.server.running else f"http://127.0.0.1:{self.var_port.get()}/"
        self.clipboard_clear()
        self.clipboard_append(url)
        self._toast.show(f"已复制：{url}", "success")

    def _copy_mobile_url(self) -> None:
        url = f"http://{self._lan_ip()}:{self.server.port}/m"
        self.clipboard_clear()
        self.clipboard_append(url)
        self._toast.show(f"已复制：{url}", "success")

    def _open_browser(self) -> None:
        url = self.server.url if self.server.running else f"http://127.0.0.1:{self.var_port.get()}/"
        os.startfile(url)

    def _open_preview_gallery(self) -> None:
        base = self.server.url if self.server.running else f"http://127.0.0.1:{self.var_port.get()}/"
        os.startfile(base.rstrip("/") + "/preview")

    def _choose_export(self) -> None:
        chosen = filedialog.askdirectory(initialdir=str(self.export_dir))
        if chosen:
            self.export_dir = Path(chosen)
            self.var_export.set(chosen)
            if self.state_hub.exporter:
                self.state_hub.exporter = type(self.state_hub.exporter)(self.export_dir)
            self._save_runtime_settings()
            self._toast.show("已更新导出目录", "success")

    def _open_export_dir(self) -> None:
        try:
            self.export_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.export_dir))
        except Exception:
            pass

    # -------------------------------------------------------------- Poll Loop

    def _poll(self) -> None:
        if self._closing:
            return
        demo = bool(getattr(self.server.config, "demo", False))
        if demo != self._demo_active:
            self._demo_active = demo
            if demo:
                self._real_cover = self.cover_store.get()[0]
                self.cover_store.update(demo_cover_bytes())
            elif self._real_cover is not None:
                self.cover_store.update(self._real_cover)
        snap = demo_snapshot() if demo else self.state_hub.refresh()
        self._last_snap = snap
        self._update_ui(snap)
        try:
            ms = max(100, int(self.var_refresh.get()))
        except (ValueError, AttributeError):
            ms = self.refresh_ms
        self.after(ms, self._poll)

    def _tick(self) -> None:
        if self._closing:
            return
        if self._tray_show_event.is_set():
            self._tray_show_event.clear()
            self._restore_from_tray()
        if self._tray_quit_event.is_set():
            self._tray_quit_event.clear()
            self._on_close()
            return
        if self._is_minimized():
            self._minimize_to_tray()
        if self._floating is not None and getattr(self._floating, "closed", False):
            self._floating = None
            self._sync_quick_dock()

        snap = self._last_snap
        if snap and snap.get("state") == "playing" and snap.get("duration_ms"):
            est = self._anchor_pos + (time.time() - self._anchor_wall) * 1000
            duration = snap["duration_ms"]
            if 0 <= est <= duration:
                self._progress_bar.set_progress(est / duration)
                cur_txt = format_time(int(est))
                if cur_txt != self._last_time_cur:
                    self._last_time_cur = cur_txt
                    self.lbl_time_cur.configure(text=cur_txt)
        self.after(90, self._tick)

    def _update_ui(self, s: dict) -> None:
        state = s.get("state")
        self._anchor_pos = int(s.get("position_ms", 0))
        self._anchor_wall = time.time()
        self._anchor_playing = (state == "playing")

        def set_label(key: str, widget, text: str, **kw) -> None:
            sig = (text, kw.get("text_color"))
            if self._last_ui.get(key) != sig:
                self._last_ui[key] = sig
                widget.configure(text=text, **kw)

        title = s.get("title") or "未在播放"
        set_label("title", self.lbl_title, title)
        artist_album = " · ".join(x for x in (s.get("artist"), s.get("album")) if x)
        if not s.get("connected") and not self._demo_active:
            artist_text = "请启动 AIMP，或点击右上角「演示」体验"
        else:
            artist_text = artist_album or "未知艺术家"
        set_label("artist", self.lbl_artist, artist_text)

        genre_year = " · ".join(x for x in (s.get("genre"), s.get("year")) if x)
        set_label("meta", self.lbl_meta, genre_year or ("演示模式" if self._demo_active else "AIMP"))

        if s.get("connected"):
            if state == "playing":
                set_label("badge", self.lbl_badge, "播放中", text_color=T("success"))
                self._status_dot.set_status("success", True)
            elif state == "paused":
                set_label("badge", self.lbl_badge, "已暂停", text_color=T("warning"))
                self._status_dot.set_status("warning", False)
            else:
                set_label("badge", self.lbl_badge, "已就绪", text_color=T("text_secondary"))
                self._status_dot.set_status("text_muted", False)
        else:
            set_label("badge", self.lbl_badge, "未连接", text_color=T("danger"))
            self._status_dot.set_status("danger", False)

        is_playing = (state == "playing")
        self._equalizer.set_playing(is_playing)
        self._cover_stage.set_playing(is_playing)
        self._progress_bar.set_playing(is_playing)
        if is_playing != self._is_playing_icon:
            self._is_playing_icon = is_playing
            self.btn_play.configure(image=self._ico_pause if is_playing else self._ico_play)

        progress = int((s.get("progress") or 0.0) * 1000)
        if progress != self._last_progress:
            self._last_progress = progress
            self._progress_bar.set_progress(progress / 1000.0)
        cur_txt = s.get("position") or "0:00"
        dur_txt = s.get("duration") or "0:00"
        if cur_txt != self._last_time_cur:
            self._last_time_cur = cur_txt
            self.lbl_time_cur.configure(text=cur_txt)
        if dur_txt != self._last_time_dur:
            self._last_time_dur = dur_txt
            self.lbl_time_dur.configure(text=dur_txt)

        cover_ts = s.get("cover_ts", 0)
        if cover_ts != self._cover_ts:
            pil_img = self.cover_store.rounded_image(118, 18, blocking=False)
            if pil_img is not None:
                animate = (self._cover_ts != -1)
                self._cover_ts = cover_ts
                self._cover_stage.set_cover(pil_img, animate=animate)

        cur = s.get("lyrics_current") or ""
        nxt = s.get("lyrics_next") or ""
        full = s.get("lyrics_full") or []
        if s.get("lyrics_synced"):
            self._lyrics_stage.set_lyrics(cur or "（纯音乐 / 间奏中）", nxt, True)
            set_label("lyr_badge", self.lbl_lyric_badge, "LRC 同步", text_color=T("accent"))
        elif full:
            self._lyrics_stage.set_lyrics("\n".join(full[-2:]), "", False)
            set_label("lyr_badge", self.lbl_lyric_badge, "纯文本", text_color=T("text_secondary"))
        else:
            self._lyrics_stage.set_lyrics("暂无歌词", "支持同名 .lrc 与音频内嵌歌词", False)
            set_label("lyr_badge", self.lbl_lyric_badge, "无歌词", text_color=T("text_muted"))

        if self._active_tab == "overlay" and not self._curtain.active:
            self._overlay_preview.update_preview(self.server.config, s)

        self._sync_server_ui()

    # ------------------------------------------------------ Minimize to Tray

    def _is_minimized(self) -> bool:
        try:
            if self.state() == "iconic":
                return True
        except tk.TclError:
            return False
        try:
            return bool(ctypes.windll.user32.IsIconic(self.winfo_id()))
        except Exception:
            return False

    def _minimize_to_tray(self) -> None:
        if self._closing or self._in_tray or not self._is_minimized():
            return
        if not self._ensure_tray().show("已最小化到托盘，双击图标恢复窗口"):
            return
        self._in_tray = True
        self.withdraw()
        if self._floating is not None and not getattr(self._floating, "closed", False):
            self.after(25, self._floating.ensure_visible_no_taskbar)

    def _restore_from_tray(self) -> None:
        if self._tray is not None:
            self._tray.hide()
        self._in_tray = False
        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            pass
        self.deiconify()
        self.state("normal")
        self.lift()
        try:
            self.focus_force()
        except tk.TclError:
            pass
        animate_window_alpha(self, 0.0, 1.0, duration_ms=180, steps=10)

    def _ensure_tray(self) -> TrayIcon:
        if self._tray is None:
            self._tray = TrayIcon(
                "AIMP Now Playing → OBS",
                icon_path(),
                on_show=self._tray_show_event.set,
                on_quit=self._tray_quit_event.set,
            )
        return self._tray

    def _on_close(self) -> None:
        self._closing = True
        self._curtain.destroy()
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        if self._font_dialog is not None and self._font_dialog.winfo_exists():
            try:
                self._font_dialog.destroy()
            except Exception:
                pass
            self._font_dialog = None
        if self._floating is not None:
            self._floating.close()
            self._floating = None
        self._save_runtime_settings()
        self.destroy()
