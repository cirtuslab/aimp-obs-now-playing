"""Modern dark control panel for the AIMP -> OBS tool (CustomTkinter)."""

from __future__ import annotations

import ctypes
import os
import socket
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, font as tkfont, messagebox
from typing import Optional

import customtkinter as ctk
from PIL import Image

from .aimp_api import CMD_NEXT, CMD_PLAYPAUSE, CMD_PREV, CMD_STOP, AimpClient, AlbumArtReceiver
from .cover import CoverStore
from .demo import demo_cover_bytes, demo_snapshot
from .overlay import THEMES, OverlayConfig
from .paths import icon_path
from .settings import SettingsStore
from .state import StateHub, format_time
from .tray import TrayIcon

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("gold")

COLORS = {
    "bg": "#0e1016",
    "card": "#171b24",
    "card2": "#1e2330",
    "border": "#2b3140",
    "text": "#eef1f8",
    "dim": "#8d95a8",
    "accent": "#ff9f19",
    "accent_hover": "#ffb44d",
    "green": "#3ddc84",
    "yellow": "#ffd166",
    "red": "#ff6b6b",
    "button": "#252b3a",
    "button_hover": "#303850",
}


class _DeviceRow:
    """Reusable row for the mobile device lists.

    The device list is polled every 2s; rebuilding CTk widgets each time costs hundreds of
    milliseconds and blanks the list, so rows are created once and updated in place.
    """

    def __init__(self, master, font) -> None:
        self.frame = ctk.CTkFrame(master, fg_color=COLORS["card2"], corner_radius=8)
        self.label = ctk.CTkLabel(
            self.frame, text="", font=font, text_color=COLORS["text"], anchor="w",
        )
        self.label.pack(side="left", padx=10, pady=6)
        self._font = font
        self._buttons: list = []
        self._packed = False
        self._sig = None

    def _button(self, index: int):
        while len(self._buttons) <= index:
            btn = ctk.CTkButton(
                self.frame, text="", width=56, height=26, font=self._font,
                fg_color=COLORS["button"], text_color=COLORS["text"],
            )
            btn.pack(side="right", padx=(0, 6), pady=4)
            self._buttons.append(btn)
        return self._buttons[index]

    def update(self, text: str, actions) -> None:
        """``actions``: sequence of (label, command, fg_color, text_color), right to left."""
        sig = (text, tuple((a[0], a[2], a[3]) for a in actions))
        if sig != self._sig:
            self._sig = sig
            self.label.configure(text=text)
            for i, (label, command, fg, tc) in enumerate(actions):
                self._button(i).configure(
                    text=label, command=command, fg_color=fg, text_color=tc,
                )
        for btn in self._buttons[len(actions):]:
            if btn.winfo_manager():
                btn.pack_forget()

    def show(self, visible: bool) -> None:
        if visible == self._packed:
            return
        self._packed = visible
        if visible:
            self.frame.pack(fill="x", padx=4, pady=3)
        else:
            self.frame.pack_forget()


class App(ctk.CTk):
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
        super().__init__()
        self.client = client
        self.receiver = receiver
        self.state_hub = state_hub
        self.cover_store = cover_store
        self.server = server
        self.export_dir = Path(export_dir)
        self.refresh_ms = refresh_ms
        self.settings = settings or SettingsStore()

        self._closing = False
        self._settings_ready = False
        self._settings_window = None
        self._mobile_window = None
        self._pending_rows: list = []
        self._approved_rows: list = []
        self.lbl_no_pending = None
        self.lbl_no_approved = None
        self._mobile_url_text = ""
        self._floating = None
        self._cover_ts = -1
        self._cover_image: Optional[ctk.CTkImage] = None
        self._last_snap: Optional[dict] = None
        self._last_ui: dict = {}
        self._last_progress = -1
        self._last_time_text = ""
        self._demo_active = False
        self._real_cover: Optional[bytes] = None
        self._anchor_pos = 0
        self._anchor_wall = 0.0
        self._anchor_playing = False
        self._tray = None
        self._in_tray = False
        self._tray_show_event = threading.Event()
        self._tray_quit_event = threading.Event()

        self.title("AIMP Now Playing → OBS")
        self.geometry("780x600")
        self.minsize(720, 460)
        self.configure(fg_color=COLORS["bg"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._font = ctk.CTkFont(family="Segoe UI", size=13)
        self._font_small = ctk.CTkFont(family="Segoe UI", size=12)
        self._font_badge = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        self._font_title = ctk.CTkFont(family="Segoe UI", size=22, weight="bold")
        self._font_artist = ctk.CTkFont(family="Segoe UI", size=14, weight="bold")
        self._font_meta = ctk.CTkFont(family="Segoe UI", size=12)
        self._font_lyric = ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        self._font_lyric_next = ctk.CTkFont(family="Segoe UI", size=13)
        self._font_section = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")

        self._build_ui()
        self._settings_ready = True
        self._set_window_icon(self)
        self.after(50, self._tick)
        self.after(200, self._poll)

    def _set_window_icon(self, win) -> None:
        icon = icon_path()
        if icon.exists():
            try:
                win.iconbitmap(str(icon))
            except Exception:
                pass

    # ------------------------------------------------------------- layout

    def _build_ui(self) -> None:
        pad = {"padx": 22, "pady": (16, 6)}
        root = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        root.pack(fill="both", expand=True)
        self._scroll = root

        # Header
        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", **pad)
        ctk.CTkLabel(
            header, text="AIMP Now Playing", font=self._font_title,
            text_color=COLORS["text"], anchor="w",
        ).pack(side="left")
        self.lbl_badge = ctk.CTkLabel(
            header, text="● 未连接", font=self._font_badge,
            text_color=COLORS["red"],
        )
        self.lbl_badge.pack(side="right")

        # Now playing card
        card = ctk.CTkFrame(
            root, fg_color=COLORS["card"], corner_radius=20,
            border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", padx=22, pady=(6, 10))
        card.grid_columnconfigure(1, weight=1)

        self.lbl_cover = ctk.CTkLabel(card, text="", width=128, height=128)
        self.lbl_cover.grid(row=0, column=0, rowspan=4, padx=(18, 18), pady=18)

        self.lbl_title = ctk.CTkLabel(
            card, text="—", font=self._font_title, text_color=COLORS["text"],
            anchor="w", wraplength=500,
        )
        self.lbl_title.grid(row=0, column=1, sticky="ew", pady=(16, 0))

        self.lbl_artist = ctk.CTkLabel(
            card, text="—", font=self._font_artist, text_color=COLORS["accent"],
            anchor="w", wraplength=500,
        )
        self.lbl_artist.grid(row=1, column=1, sticky="ew", pady=(2, 0))

        self.lbl_meta = ctk.CTkLabel(
            card, text="", font=self._font_meta, text_color=COLORS["dim"],
            anchor="w", wraplength=500,
        )
        self.lbl_meta.grid(row=2, column=1, sticky="ew", pady=(2, 0))

        self.lbl_aimp = ctk.CTkLabel(
            card, text="", font=self._font_small, text_color=COLORS["dim"],
            anchor="w",
        )
        self.lbl_aimp.grid(row=3, column=1, sticky="ew", pady=(2, 14))

        # Progress
        prog = ctk.CTkFrame(root, fg_color="transparent")
        prog.pack(fill="x", padx=22, pady=(0, 4))
        self.progress = ctk.CTkProgressBar(
            prog, height=8, corner_radius=4,
            fg_color=COLORS["button"], progress_color=COLORS["accent"],
        )
        self.progress.pack(fill="x")
        self.progress.set(0)
        times = ctk.CTkFrame(root, fg_color="transparent")
        times.pack(fill="x", padx=22, pady=(4, 8))
        self.lbl_time = ctk.CTkLabel(
            times, text="0:00 / 0:00", font=self._font_small,
            text_color=COLORS["dim"], anchor="w",
        )
        self.lbl_time.pack(side="left")
        self.lbl_server_state = ctk.CTkLabel(
            times, text="服务未启动", font=self._font_small,
            text_color=COLORS["dim"], anchor="e",
        )
        self.lbl_server_state.pack(side="right")

        # Lyrics card
        lyr = ctk.CTkFrame(
            root, fg_color=COLORS["card"], corner_radius=20,
            border_width=1, border_color=COLORS["border"],
        )
        lyr.pack(fill="x", padx=22, pady=(2, 10))
        ctk.CTkLabel(
            lyr, text="歌词", font=self._font_section,
            text_color=COLORS["dim"], anchor="w",
        ).pack(anchor="w", padx=18, pady=(14, 2))
        self.lbl_lyric = ctk.CTkLabel(
            lyr, text="暂无歌词", font=self._font_lyric,
            text_color=COLORS["text"], anchor="w", justify="left",
            wraplength=690,
        )
        self.lbl_lyric.pack(anchor="w", padx=18, pady=(2, 2))
        self.lbl_lyric_next = ctk.CTkLabel(
            lyr, text="", font=self._font_lyric_next,
            text_color=COLORS["dim"], anchor="w", justify="left",
            wraplength=690,
        )
        self.lbl_lyric_next.pack(anchor="w", padx=18, pady=(2, 14))

        # Controls
        ctrl = ctk.CTkFrame(root, fg_color="transparent")
        ctrl.pack(fill="x", padx=22, pady=(0, 10))
        btn_cfg = dict(width=74, height=42, corner_radius=14)
        self.btn_prev = ctk.CTkButton(
            ctrl, text="⏮ 上一首", command=lambda: self._cmd(CMD_PREV),
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"],
            text_color=COLORS["text"], font=self._font, **btn_cfg,
        )
        self.btn_prev.pack(side="left", padx=(0, 8))
        self.btn_play = ctk.CTkButton(
            ctrl, text="⏸ 播放/暂停", command=lambda: self._cmd(CMD_PLAYPAUSE),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color="#14100a", font=self._font_bold(), **btn_cfg,
        )
        self.btn_play.pack(side="left", padx=(0, 8))
        self.btn_stop = ctk.CTkButton(
            ctrl, text="⏹ 停止", command=lambda: self._cmd(CMD_STOP),
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"],
            text_color=COLORS["text"], font=self._font, **btn_cfg,
        )
        self.btn_stop.pack(side="left", padx=(0, 8))
        self.btn_next = ctk.CTkButton(
            ctrl, text="⏭ 下一首", command=lambda: self._cmd(CMD_NEXT),
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"],
            text_color=COLORS["text"], font=self._font, **btn_cfg,
        )
        self.btn_next.pack(side="left")

        # Settings entry button (style + OBS moved to a secondary window)
        settings_row = ctk.CTkFrame(root, fg_color="transparent")
        settings_row.pack(fill="x", padx=22, pady=(0, 12))
        self.btn_settings = ctk.CTkButton(
            settings_row, text="⚙ 覆盖页样式 / OBS 设置", height=46, corner_radius=14,
            command=self._open_settings_window, font=self._font_bold(),
            fg_color=COLORS["card2"], hover_color=COLORS["button_hover"],
            border_width=1, border_color=COLORS["accent"], text_color=COLORS["text"],
        )
        self.btn_settings.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_floating = ctk.CTkButton(
            settings_row, text="🖥 桌面悬浮窗", height=46, corner_radius=14,
            command=self._toggle_floating, font=self._font_bold(),
            fg_color=COLORS["card2"], hover_color=COLORS["button_hover"],
            border_width=1, border_color=COLORS["accent"], text_color=COLORS["text"],
        )
        self.btn_floating.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.btn_service = ctk.CTkButton(
            settings_row, text="▶ 启动服务", height=46, corner_radius=14,
            command=self._toggle_server, font=self._font_bold(),
            fg_color=COLORS["card2"], hover_color=COLORS["button_hover"],
            border_width=1, border_color=COLORS["accent"], text_color=COLORS["text"],
        )
        self.btn_service.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.btn_mobile = ctk.CTkButton(
            settings_row, text="📱 手机连接", height=46, corner_radius=14,
            command=self._open_mobile_window, font=self._font_bold(),
            fg_color=COLORS["card2"], hover_color=COLORS["button_hover"],
            border_width=1, border_color=COLORS["accent"], text_color=COLORS["text"],
        )
        self.btn_mobile.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.lbl_hint_main = ctk.CTkLabel(
            root, text="样式、OBS 设置和桌面悬浮窗可点击上方按钮打开。",
            font=self._font_small, text_color=COLORS["dim"], anchor="w",
        )
        self.lbl_hint_main.pack(fill="x", padx=22, pady=(0, 14))

    # ------------------------------------------------- settings window

    def _build_style_panel(self, parent) -> None:
        if getattr(self.server, "config", None) is None:
            self.server.config = OverlayConfig()
        ctk.CTkLabel(
            parent, text="覆盖页样式（OBS 浏览器源约 1-2 秒自动同步）",
            font=self._font_section, text_color=COLORS["dim"], anchor="w",
        ).pack(anchor="w", padx=6, pady=(2, 6))

        # theme row
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkLabel(r, text="主题", width=58, anchor="w", font=self._font_small, text_color=COLORS["dim"]).pack(side="left")
        self._theme_labels = [meta["label"] for meta in THEMES.values()]
        self._theme_keys = {meta["label"]: key for key, meta in THEMES.items()}
        self._theme_combo = ctk.CTkComboBox(
            r, values=self._theme_labels, command=self._on_theme,
            width=210, height=32, corner_radius=10,
            fg_color=COLORS["card2"], border_color=COLORS["border"],
            button_color=COLORS["accent"], button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["card2"], dropdown_hover_color=COLORS["button_hover"],
            text_color=COLORS["text"], font=self._font_small,
        )
        self._theme_combo.pack(side="left", padx=(6, 10))
        ctk.CTkButton(
            r, text="重置样式", width=90, height=32, corner_radius=10,
            command=self._reset_style, font=self._font_small,
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"], text_color=COLORS["text"],
        ).pack(side="left")

        # position row
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkLabel(r, text="位置", width=58, anchor="w", font=self._font_small, text_color=COLORS["dim"]).pack(side="left")
        grid = ctk.CTkFrame(r, fg_color="transparent")
        grid.pack(side="left", padx=(6, 0))
        self._pos_buttons = {}
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
                btn = ctk.CTkButton(
                    grid, text=pos_labels[key], width=48, height=30, corner_radius=8,
                    command=lambda k=key: self._set_pos(k),
                    font=self._font_small, fg_color=COLORS["button"],
                    hover_color=COLORS["button_hover"], text_color=COLORS["text"],
                )
                btn.grid(row=ri, column=ci, padx=2, pady=2)
                self._pos_buttons[key] = btn

        # cover side + background + panel row
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkLabel(r, text="封面", width=58, anchor="w", font=self._font_small, text_color=COLORS["dim"]).pack(side="left")
        self._cover_buttons = {}
        for key, text in (("left", "左"), ("right", "右"), ("top", "上")):
            btn = ctk.CTkButton(
                r, text=text, width=46, height=30, corner_radius=8,
                command=lambda k=key: self._set_coverside(k),
                font=self._font_small, fg_color=COLORS["button"],
                hover_color=COLORS["button_hover"], text_color=COLORS["text"],
            )
            btn.pack(side="left", padx=(0, 4))
            self._cover_buttons[key] = btn
        self._btn_bg = ctk.CTkButton(
            r, text="背景: 透明", width=112, height=30, corner_radius=8,
            command=lambda: self._set_bg(""), font=self._font_small,
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"], text_color=COLORS["text"],
        )
        self._btn_bg.pack(side="left", padx=(14, 4))
        ctk.CTkButton(
            r, text="背景自定义…", width=100, height=30, corner_radius=8,
            command=self._pick_bg, font=self._font_small,
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"], text_color=COLORS["text"],
        ).pack(side="left", padx=(0, 14))
        self._btn_panel = ctk.CTkButton(
            r, text="面板: 默认", width=112, height=30, corner_radius=8,
            command=lambda: self._set_panel(""), font=self._font_small,
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"], text_color=COLORS["text"],
        )
        self._btn_panel.pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            r, text="面板自定义…", width=100, height=30, corner_radius=8,
            command=self._pick_panel, font=self._font_small,
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"], text_color=COLORS["text"],
        ).pack(side="left")

        # accent row
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkLabel(r, text="强调色", width=58, anchor="w", font=self._font_small, text_color=COLORS["dim"]).pack(side="left")
        self._accent_buttons = {}
        for color in ("#ff9f19", "#1ed760", "#5cc8ff", "#ff2da0", "#2563eb", "#ffffff"):
            btn = ctk.CTkButton(
                r, text="", width=30, height=30, corner_radius=8,
                command=lambda c=color: self._set_accent(c),
                fg_color=color, hover_color=color,
            )
            btn.pack(side="left", padx=(0, 5))
            self._accent_buttons[color] = btn
        ctk.CTkButton(
            r, text="自定义…", width=90, height=30, corner_radius=8,
            command=self._pick_accent, font=self._font_small,
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"], text_color=COLORS["text"],
        ).pack(side="left")

        # lyric font row
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkLabel(r, text="歌词字体", width=58, anchor="w", font=self._font_small, text_color=COLORS["dim"]).pack(side="left")
        self._font_families = ["默认"] + sorted(
            set(f for f in tkfont.families() if not f.startswith("@"))
        )
        self._lyric_font_name = ctk.CTkLabel(
            r, text="默认", width=170, anchor="w",
            font=self._font_small, text_color=COLORS["text"],
        )
        self._lyric_font_name.pack(side="left", padx=(6, 10))
        ctk.CTkButton(
            r, text="选择字体…", width=110, height=32, corner_radius=10,
            command=self._pick_lyric_font, font=self._font_small,
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"],
            text_color=COLORS["text"],
        ).pack(side="left", padx=(0, 14))
        self._lyric_preview = ctk.CTkLabel(
            r, text="示例歌词 AaBb 中文", font=self._font_lyric,
            text_color=COLORS["dim"],
        )
        self._lyric_preview.pack(side="left")

        # size entries row
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=6, pady=(0, 6))
        self._var_width = ctk.StringVar()
        self._var_fontsize = ctk.StringVar()
        self._var_margin = ctk.StringVar()
        self._var_radius = ctk.StringVar()
        self._var_coverradius = ctk.StringVar()
        entry_specs = [
            ("宽度", self._var_width, 70),
            ("字号", self._var_fontsize, 60),
            ("边距", self._var_margin, 60),
            ("圆角", self._var_radius, 60),
            ("封面圆角", self._var_coverradius, 70),
        ]
        first = True
        for label, var, width in entry_specs:
            if not first:
                ctk.CTkLabel(r, text="", width=10).pack(side="left")
            first = False
            ctk.CTkLabel(r, text=label, font=self._font_small, text_color=COLORS["dim"]).pack(side="left")
            entry = ctk.CTkEntry(
                r, textvariable=var, width=width, height=30, corner_radius=8,
                fg_color=COLORS["card2"], border_color=COLORS["border"],
                text_color=COLORS["text"], font=self._font_small,
            )
            entry.pack(side="left", padx=(4, 0))
            entry.bind("<Return>", self._style_apply)
            entry.bind("<FocusOut>", self._style_apply)

        # switches row
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=6, pady=(2, 10))
        self._switches = {}
        for cfg_key, label in (
            ("hide_cover", "隐藏封面"), ("hide_title", "隐藏标题"), ("hide_state", "隐藏状态"),
            ("hide_progress", "隐藏进度"), ("hide_lyrics", "隐藏歌词"),
            ("hide_when_stopped", "停止时隐藏"), ("demo", "演示模式"),
        ):
            sw = ctk.CTkSwitch(
                r, text=label, font=self._font_small,
                progress_color=COLORS["accent"],
                command=lambda k=cfg_key: self._on_switch(k),
            )
            sw.pack(side="left", padx=(0, 14))
            self._switches[cfg_key] = sw

        self._style_refresh()

    def _build_obs_panel(self, parent) -> None:
        ctk.CTkLabel(
            parent, text="OBS 浏览器源", font=self._font_section,
            text_color=COLORS["dim"], anchor="w",
        ).pack(anchor="w", padx=6, pady=(12, 6))

        card = ctk.CTkFrame(
            parent, fg_color=COLORS["card"], corner_radius=20,
            border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", padx=6, pady=(0, 8))
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=18, pady=(14, 8))
        ctk.CTkLabel(row1, text="端口", font=self._font_small, text_color=COLORS["dim"]).pack(side="left")
        self.var_port = ctk.StringVar(value=str(getattr(self.server, "port", 8765)))
        self._entry_port = ctk.CTkEntry(
            row1, textvariable=self.var_port, width=72, height=32,
            corner_radius=10, fg_color=COLORS["card2"], border_color=COLORS["border"],
            text_color=COLORS["text"], font=self._font_small,
        )
        self._entry_port.pack(side="left", padx=(6, 16))
        self._entry_port.bind("<Return>", self._save_runtime_settings)
        self._entry_port.bind("<FocusOut>", self._save_runtime_settings)
        ctk.CTkLabel(row1, text="刷新 ms", font=self._font_small, text_color=COLORS["dim"]).pack(side="left")
        self.var_refresh = ctk.StringVar(value=str(self.refresh_ms))
        self._entry_refresh = ctk.CTkEntry(
            row1, textvariable=self.var_refresh, width=72, height=32,
            corner_radius=10, fg_color=COLORS["card2"], border_color=COLORS["border"],
            text_color=COLORS["text"], font=self._font_small,
        )
        self._entry_refresh.pack(side="left", padx=(6, 16))
        self._entry_refresh.bind("<Return>", self._save_runtime_settings)
        self._entry_refresh.bind("<FocusOut>", self._save_runtime_settings)
        self.btn_server = ctk.CTkButton(
            row1, text="启动服务", width=96, height=32, corner_radius=10,
            command=self._toggle_server, font=self._font_small,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color="#14100a",
        )
        self.btn_server.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row1, text="复制 OBS 地址", width=112, height=32, corner_radius=10,
            command=self._copy_url, font=self._font_small,
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"], text_color=COLORS["text"],
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row1, text="浏览器预览", width=100, height=32, corner_radius=10,
            command=self._open_browser, font=self._font_small,
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"], text_color=COLORS["text"],
        ).pack(side="left")

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkLabel(row2, text="导出目录", font=self._font_small, text_color=COLORS["dim"]).pack(side="left")
        self.var_export = ctk.StringVar(value=str(self.export_dir))
        self._entry_export = ctk.CTkEntry(
            row2, textvariable=self.var_export, height=32, corner_radius=10,
            fg_color=COLORS["card2"], border_color=COLORS["border"],
            text_color=COLORS["text"], font=self._font_small,
        )
        self._entry_export.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self._entry_export.bind("<Return>", self._save_runtime_settings)
        self._entry_export.bind("<FocusOut>", self._save_runtime_settings)
        ctk.CTkButton(
            row2, text="选择…", width=76, height=32, corner_radius=10,
            command=self._choose_export, font=self._font_small,
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"], text_color=COLORS["text"],
        ).pack(side="left")

        self.lbl_hint = ctk.CTkLabel(
            parent, text="OBS 中添加“浏览器”源，URL 填 http://127.0.0.1:8765/ 即可",
            font=self._font_small, text_color=COLORS["dim"], anchor="w",
        )
        self.lbl_hint.pack(fill="x", padx=6, pady=(0, 14))


    # --------------------------------------------------------- mobile
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

    def _open_mobile_window(self) -> None:
        if self._mobile_window is not None and self._mobile_window.winfo_exists():
            self._mobile_window.focus()
            return
        win = ctk.CTkToplevel(self)
        win.title("手机连接")
        self._set_window_icon(win)
        win.geometry("440x400")
        win.minsize(400, 340)
        self._mobile_window = win
        devs = self.server.devices
        ip = self._lan_ip()

        ctk.CTkLabel(
            win, text="📱 手机连接", font=self._font_title, text_color=COLORS["text"],
        ).pack(anchor="w", padx=18, pady=(16, 2))
        ctk.CTkLabel(
            win, text="同一 Wi-Fi 下用 Safari 打开下方地址；首次连接需电脑同意。",
            font=self._font_small, text_color=COLORS["dim"], anchor="w", wraplength=420,
        ).pack(anchor="w", padx=18)

        self._mobile_switch = ctk.CTkSwitch(
            win, text="启用手机连接", command=self._toggle_mobile,
            font=self._font, progress_color=COLORS["accent"],
        )
        self._mobile_switch.pack(anchor="w", padx=18, pady=(12, 2))
        if devs.enabled:
            self._mobile_switch.select()
        else:
            self._mobile_switch.deselect()

        url = f"http://{ip}:{self.server.port}/m"
        urlrow = ctk.CTkFrame(win, fg_color=COLORS["card2"], corner_radius=10)
        urlrow.pack(fill="x", padx=18, pady=(6, 2))
        self.lbl_mobile_url = ctk.CTkLabel(
            urlrow, text=url, font=self._font_small,
            text_color=COLORS["accent"], anchor="w",
        )
        self.lbl_mobile_url.pack(side="left", padx=12, pady=8)

        ctk.CTkLabel(
            win, text="待审核设备", font=self._font_section, text_color=COLORS["dim"], anchor="w",
        ).pack(anchor="w", padx=18, pady=(12, 2))
        self.mobile_pending = ctk.CTkScrollableFrame(win, fg_color="transparent", height=64)
        self.mobile_pending.pack(fill="x", padx=12, pady=(0, 4))
        self.lbl_no_pending = ctk.CTkLabel(
            self.mobile_pending, text="暂无待审核设备",
            font=self._font_small, text_color=COLORS["dim"],
        )

        ctk.CTkLabel(
            win, text="已授权设备", font=self._font_section, text_color=COLORS["dim"], anchor="w",
        ).pack(anchor="w", padx=18, pady=(8, 2))
        self.mobile_approved = ctk.CTkScrollableFrame(win, fg_color="transparent", height=64)
        self.mobile_approved.pack(fill="x", padx=12, pady=(0, 4))
        self.lbl_no_approved = ctk.CTkLabel(
            self.mobile_approved, text="暂无已授权设备",
            font=self._font_small, text_color=COLORS["dim"],
        )
        self._pending_rows = []
        self._approved_rows = []

        self.lbl_mobile_hint = ctk.CTkLabel(
            win, text="", font=self._font_small, text_color=COLORS["dim"],
            anchor="w", wraplength=420,
        )
        self.lbl_mobile_hint.pack(anchor="w", padx=18, pady=(6, 10))

        win.protocol("WM_DELETE_WINDOW", self._close_mobile_window)
        # Auto-fit height so both the pending and approved lists are visible.
        win.update_idletasks()
        win.geometry(f"460x{win.winfo_reqheight() + 12}")
        self._refresh_mobile_view()
        win.after(2000, self._mobile_poll)

    def _close_mobile_window(self) -> None:
        if self._mobile_window is not None:
            self._mobile_window.destroy()
            self._mobile_window = None
        self._pending_rows = []
        self._approved_rows = []
        self.lbl_no_pending = None
        self.lbl_no_approved = None

    def _toggle_mobile(self) -> None:
        devs = self.server.devices
        on = bool(self._mobile_switch.get())
        devs.enabled = on
        self.settings.mobile_enabled = on
        self.settings.save()
        loopback = ("127.0.0.1", "localhost", "::1")
        if on and self.server.host in loopback:
            # Rebind to 0.0.0.0 so phones on the LAN can reach /m.
            self.server.host = "0.0.0.0"
            self.server.stop()
            ok = self.server.start()
            if not ok:
                self.server.host = "127.0.0.1"
                self.server.start()
        elif not on and self.server.host not in loopback:
            # Restore loopback-only binding when mobile access is turned off.
            self.server.host = "127.0.0.1"
            self.server.stop()
            self.server.start()
        self._refresh_mobile_view()

    def _mobile_poll(self) -> None:
        if self._mobile_window is None or not self._mobile_window.winfo_exists():
            return
        self._refresh_mobile_view()
        self._mobile_window.after(2000, self._mobile_poll)

    @staticmethod
    def _sync_specs(rows: list, specs: list, make_row) -> None:
        """Grow/reuse ``rows`` to match ``specs`` and hide the leftovers."""
        for i, (text, actions) in enumerate(specs):
            if i >= len(rows):
                rows.append(make_row())
            rows[i].update(text, actions)
            rows[i].show(True)
        for row in rows[len(specs):]:
            row.show(False)

    def _refresh_mobile_view(self) -> None:
        if self._mobile_window is None or not self._mobile_window.winfo_exists():
            return
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
        hint = "" if devs.enabled else "手机连接已关闭。开启后，首次访问需在电脑端同意。"
        if self.lbl_mobile_hint.cget("text") != hint:
            self.lbl_mobile_hint.configure(text=hint)

        pending_specs = [
            (
                f"{dev.get('name', '?')}  ({dev.get('id', '')})",
                [
                    ("同意", lambda d=dev: self._device_action("approve", d["id"]),
                     COLORS["accent"], "#14100a"),
                    ("拒绝", lambda d=dev: self._device_action("reject", d["id"]),
                     COLORS["button"], COLORS["text"]),
                ],
            )
            for dev in pending
        ]
        approved_specs = [
            (
                f"{dev.get('name', '?')}  ({dev.get('id', '')})",
                [
                    ("移除", lambda d=dev: self._device_action("remove", d["id"]),
                     COLORS["button"], COLORS["text"]),
                ],
            )
            for dev in approved
        ]
        self._sync_specs(
            self._pending_rows, pending_specs,
            lambda: _DeviceRow(self.mobile_pending, self._font_small),
        )
        self._sync_specs(
            self._approved_rows, approved_specs,
            lambda: _DeviceRow(self.mobile_approved, self._font_small),
        )
        self._sync_placeholder(self.lbl_no_pending, not pending_specs)
        self._sync_placeholder(self.lbl_no_approved, not approved_specs)

    @staticmethod
    def _sync_placeholder(label, visible: bool) -> None:
        if label is None:
            return
        packed = bool(label.winfo_manager())
        if visible and not packed:
            label.pack(anchor="w", padx=6, pady=4)
        elif not visible and packed:
            label.pack_forget()

    def _device_action(self, action: str, device_id: str) -> None:
        devs = self.server.devices
        if action == "approve":
            devs.approve(device_id)
        elif action == "reject":
            devs.reject(device_id)
        elif action == "remove":
            devs.remove(device_id)
        self._refresh_mobile_view()

    def _open_settings_window(self) -> None:
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.focus()
            return
        win = ctk.CTkToplevel(self)
        win.title("覆盖页样式 & OBS 设置")
        self._set_window_icon(win)
        win.geometry("840x760")
        win.minsize(780, 560)
        win.configure(fg_color=COLORS["bg"])
        win.transient(self)
        win.lift()
        win.focus_force()
        win.after(80, win.lift)
        scroll = ctk.CTkScrollableFrame(win, fg_color=COLORS["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True)
        self._build_style_panel(scroll)
        self._build_obs_panel(scroll)
        self._settings_window = win
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_settings_window(win))

    def _close_settings_window(self, win=None) -> None:
        if win is None:
            win = self._settings_window
        if win is not None and win.winfo_exists():
            win.destroy()
        self._settings_window = None

    def _toggle_floating(self) -> None:
        if self._floating is not None and getattr(self._floating, "closed", False) is False:
            self._floating.close()
            self._floating = None
            self.btn_floating.configure(text="🖥 桌面悬浮窗")
            return
        from .floating import FloatingOverlay
        self._floating = FloatingOverlay(
            self, self.state_hub, self.cover_store, self.server.config,
            self.refresh_ms, self.settings, self.client,
        )
        self.btn_floating.configure(text="关闭悬浮窗")

    def _font_bold(self) -> ctk.CTkFont:
        if getattr(self, "_font_bold_obj", None) is None:
            self._font_bold_obj = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        return self._font_bold_obj

    # --------------------------------------------------- overlay style

    def _on_theme(self, choice: str) -> None:
        key = self._theme_keys.get(choice)
        if key:
            self.server.config.theme = key
            self._style_refresh()

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

    def _pick_lyric_font(self) -> None:
        if getattr(self, "_font_dialog", None) is not None and self._font_dialog.winfo_exists():
            self._font_dialog.focus()
            return
        dlg = ctk.CTkToplevel(self)
        self._font_dialog = dlg
        dlg.title("选择歌词字体")
        dlg.geometry("440x560")
        dlg.minsize(400, 480)
        self._set_window_icon(dlg)
        dlg.configure(fg_color=COLORS["bg"])
        dlg.transient(self)
        dlg.grab_set()

        search = ctk.CTkEntry(
            dlg, placeholder_text="输入关键字搜索字体…", height=36, corner_radius=10,
            fg_color=COLORS["card2"], border_color=COLORS["border"],
            text_color=COLORS["text"], font=self._font_small,
        )
        search.pack(fill="x", padx=16, pady=(14, 8))

        list_frame = ctk.CTkFrame(
            dlg, fg_color=COLORS["card"], corner_radius=12,
            border_width=1, border_color=COLORS["border"],
        )
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        listbox = tk.Listbox(
            list_frame, bg=COLORS["card2"], fg=COLORS["text"],
            selectbackground=COLORS["accent"], selectforeground="#101014",
            relief="flat", highlightthickness=0,
            font=("Segoe UI", 12), activestyle="none",
        )
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        scrollbar.pack(side="right", fill="y", pady=4)

        preview = ctk.CTkLabel(
            dlg, text="示例歌词 AaBb 中文", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=16),
            text_color=COLORS["text"],
        )
        preview.pack(fill="x", padx=16, pady=(0, 8))

        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(
            btns, text="默认字体", width=100, height=34, corner_radius=10,
            command=lambda: self._finish_font_pick(dlg, "默认"),
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"],
            text_color=COLORS["text"], font=self._font_small,
        ).pack(side="left")
        ctk.CTkButton(
            btns, text="确定", width=90, height=34, corner_radius=10,
            command=lambda: self._font_pick_ok(dlg, listbox),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color="#14100a", font=self._font_small,
        ).pack(side="right")
        ctk.CTkButton(
            btns, text="取消", width=80, height=34, corner_radius=10,
            command=lambda: self._close_font_dialog(dlg),
            fg_color=COLORS["button"], hover_color=COLORS["button_hover"],
            text_color=COLORS["text"], font=self._font_small,
        ).pack(side="right", padx=(0, 8))

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

        def on_key(_event) -> None:
            refresh(search.get())

        def on_select(_event) -> None:
            sel = listbox.curselection()
            if sel:
                name = listbox.get(sel[0])
                try:
                    preview.configure(font=ctk.CTkFont(family=name, size=16))
                except Exception:
                    pass

        def finish(_event=None) -> None:
            self._font_pick_ok(dlg, listbox)

        search.bind("<KeyRelease>", on_key)
        listbox.bind("<<ListboxSelect>>", on_select)
        listbox.bind("<Double-Button-1>", finish)
        dlg.bind("<Return>", finish)
        dlg.bind("<Escape>", lambda e: self._close_font_dialog(dlg))
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
        if getattr(self, "_font_dialog", None) is dlg:
            self._font_dialog = None
        try:
            dlg.destroy()
        except Exception:
            pass

    def _on_switch(self, key: str) -> None:
        setattr(self.server.config, key, self._switches[key].get() == 1)
        self._style_refresh()

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
        self.lbl_hint.configure(text="已恢复默认样式，OBS 浏览器源约 1-2 秒后更新。")

    def _save_overlay(self) -> None:
        if not getattr(self, "_settings_ready", False):
            return
        try:
            self.settings.overlay = self.server.config
            self.settings.save()
        except Exception:
            pass

    def _save_runtime_settings(self, _event=None) -> None:
        if not hasattr(self, "var_port"):
            self.settings.port = self.server.port
            try:
                self.settings.save()
            except Exception:
                pass
            return
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

    def _style_refresh(self) -> None:
        cfg = self.server.config
        label = next(
            (lab for lab, key in self._theme_keys.items() if key == cfg.theme),
            self._theme_labels[0],
        )
        self._theme_combo.set(label)
        for key, btn in self._pos_buttons.items():
            active = key == cfg.pos
            btn.configure(
                fg_color=COLORS["accent"] if active else COLORS["button"],
                hover_color=COLORS["accent_hover"] if active else COLORS["button_hover"],
            )
        for key, btn in self._cover_buttons.items():
            active = key == cfg.coverside
            btn.configure(
                fg_color=COLORS["accent"] if active else COLORS["button"],
                hover_color=COLORS["accent_hover"] if active else COLORS["button_hover"],
            )
        for color, btn in self._accent_buttons.items():
            active = color.lower() == (cfg.accent or "").lower()
            btn.configure(
                border_width=2 if active else 0,
                border_color="#ffffff" if active else COLORS["button"],
            )
        self._btn_bg.configure(text=f"背景: {cfg.bg if cfg.bg else '透明'}")
        self._btn_panel.configure(text=f"面板: {cfg.panel if cfg.panel else '默认'}")
        font_name = cfg.lyric_font if cfg.lyric_font in self._font_families else "默认"
        self._lyric_font_name.configure(text=font_name)
        try:
            self._lyric_preview.configure(
                font=ctk.CTkFont(
                    family="Segoe UI" if font_name == "默认" else font_name,
                    size=14,
                )
            )
        except Exception:
            pass
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

    # ----------------------------------------------------------- actions

    def _cmd(self, cmd: int) -> None:
        try:
            if not self.client.connected:
                self.client.detect()
            self.client.send_command(cmd)
        except Exception:
            pass

    def _toggle_server(self) -> None:
        if self.server.running:
            self.server.stop()
            if hasattr(self, "btn_server"):
                self.btn_server.configure(text="启动服务")
            if hasattr(self, "btn_service"):
                self.btn_service.configure(text="▶ 启动服务")
            if hasattr(self, "lbl_hint"):
                self.lbl_hint.configure(text="服务已停止。")
            return
        if hasattr(self, "var_port"):
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
            if hasattr(self, "var_port"):
                self.var_port.set(str(self.server.port))
            if hasattr(self, "btn_server"):
                self.btn_server.configure(text="停止服务")
            if hasattr(self, "btn_service"):
                self.btn_service.configure(text="⏹ 停止服务")
            if hasattr(self, "lbl_hint"):
                self.lbl_hint.configure(text=f"OBS 浏览器源地址: {self.server.url}")
            self._save_runtime_settings()
        else:
            messagebox.showerror("启动失败", "端口被占用，请换一个端口。")

    def _copy_url(self) -> None:
        url = self.server.url if self.server.running else f"http://127.0.0.1:{self.var_port.get()}/"
        self.clipboard_clear()
        self.clipboard_append(url)
        self.lbl_hint.configure(text=f"已复制: {url}")

    def _open_browser(self) -> None:
        url = self.server.url if self.server.running else f"http://127.0.0.1:{self.var_port.get()}/"
        os.startfile(url)

    def _choose_export(self) -> None:
        chosen = filedialog.askdirectory(initialdir=str(self.export_dir))
        if chosen:
            self.export_dir = Path(chosen)
            self.var_export.set(chosen)
            if self.state_hub.exporter:
                self.state_hub.exporter = type(self.state_hub.exporter)(self.export_dir)
            self._save_runtime_settings()

    # -------------------------------------------------------------- poll

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
        snap = self._last_snap
        if snap and snap.get("state") == "playing" and snap.get("duration_ms"):
            est = self._anchor_pos + (time.time() - self._anchor_wall) * 1000
            duration = snap["duration_ms"]
            if est <= duration:
                self.progress.set(est / duration)
                text = f"{format_time(int(est))} / {snap.get('duration', '0:00')}"
                if text != self._last_time_text:
                    self._last_time_text = text
                    self.lbl_time.configure(text=text)
        self.after(100, self._tick)

    def _update_ui(self, s: dict) -> None:
        state = s.get("state")
        self._anchor_pos = int(s.get("position_ms", 0))
        self._anchor_wall = time.time()
        self._anchor_playing = state == "playing"

        def set_label(key: str, widget, text: str, **kw) -> None:
            if self._last_ui.get(key) != text:
                self._last_ui[key] = text
                widget.configure(text=text, **kw)

        set_label("title", self.lbl_title, s.get("title") or "—")
        artist_album = " · ".join(x for x in (s.get("artist"), s.get("album")) if x)
        set_label("artist", self.lbl_artist, artist_album or "未知艺术家")
        genre_year = " · ".join(x for x in (s.get("genre"), s.get("year")) if x)
        set_label("meta", self.lbl_meta, genre_year or "暂无专辑信息")
        set_label("aimp", self.lbl_aimp, s.get("aimp_version") or "")

        if s.get("connected"):
            if state == "playing":
                set_label("badge", self.lbl_badge, "● 播放中", text_color=COLORS["green"])
            elif state == "paused":
                set_label("badge", self.lbl_badge, "● 已暂停", text_color=COLORS["yellow"])
            else:
                set_label("badge", self.lbl_badge, "● 未在播放", text_color=COLORS["dim"])
        else:
            set_label("badge", self.lbl_badge, "● 未连接", text_color=COLORS["red"])

        progress = int((s.get("progress") or 0.0) * 1000)
        if progress != self._last_progress:
            self._last_progress = progress
            self.progress.set(progress / 1000)
        set_label("time", self.lbl_time, f"{s.get('position')} / {s.get('duration')}")

        cover_ts = s.get("cover_ts", 0)
        if cover_ts != self._cover_ts:
            image = self._rounded_cover(128, 22, blocking=False)
            if image is not None:  # artwork still decoding -> retry on the next poll
                self._cover_ts = cover_ts
                self._cover_image = image
                self.lbl_cover.configure(image=image)

        cur = s.get("lyrics_current") or ""
        nxt = s.get("lyrics_next") or ""
        full = s.get("lyrics_full") or []
        if s.get("lyrics_synced"):
            set_label("lyric_cur", self.lbl_lyric, cur or "（纯音乐 / 本句无歌词）")
            set_label("lyric_next", self.lbl_lyric_next, nxt)
        elif full:
            set_label("lyric_cur", self.lbl_lyric, "\n".join(full[-4:]))
            set_label("lyric_next", self.lbl_lyric_next, "")
        else:
            set_label("lyric_cur", self.lbl_lyric, "暂无歌词")
            set_label("lyric_next", self.lbl_lyric_next, "")

        if self.server.running:
            set_label("server_state", self.lbl_server_state, self.server.url)
            if hasattr(self, "btn_service"):
                self.btn_service.configure(text="⏹ 停止服务")
        else:
            set_label("server_state", self.lbl_server_state, "服务未启动")
            if hasattr(self, "btn_service"):
                self.btn_service.configure(text="▶ 启动服务")

    def _rounded_cover(self, size: int, radius: int, blocking: bool = True):
        """Rounded cover thumbnail; the store caches decode/resize per cover revision."""
        img = self.cover_store.rounded_image(size, radius, blocking)
        if img is None:
            if not blocking:
                return None
            img = Image.new("RGBA", (size, size), (36, 42, 56, 255))
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))

    # ---------------------------------------------------------- minimize to tray

    def _is_minimized(self) -> bool:
        """True while the window is minimised.

        A title-bar (or taskbar) minimise does not surface as Tk's ``<Unmap>`` on Windows, so ask
        Win32 as well as Tk.
        """
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
            return  # no notification area (shell gone): keep the normal minimised window
        self._in_tray = True
        self.withdraw()  # also removes the taskbar button

    def _restore_from_tray(self) -> None:
        if self._tray is not None:
            self._tray.hide()
        self._in_tray = False
        self.deiconify()
        self.state("normal")
        self.lift()
        try:
            self.focus_force()
        except tk.TclError:
            pass

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
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        self._close_settings_window()
        if self._floating is not None:
            self._floating.close()
            self._floating = None
        self._save_runtime_settings()
        self.destroy()
