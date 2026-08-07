"""Desktop floating overlay window with the same info as the OBS browser source."""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import io
import threading
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional

from PIL import Image, ImageDraw, ImageOps

from .aimp_api import CMD_NEXT, CMD_PLAYPAUSE, CMD_PREV, CMD_STOP
from .cover import CoverStore
from .overlay import THEMES, OverlayConfig
from .paths import icon_path
from .state import StateHub, format_time

BASE_W, BASE_H = 560, 360
TRANSPARENT = "#010203"
SCALE_MIN, SCALE_MAX = 0.4, 2.5

HOTKEY_ID = 0x4150
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_L = 0x4C

TK_THEMES = {
    "modern": {"panel": "#10131b", "border": "#2a2f3d", "accent": "#ff9f19", "text": "#f2f3f7", "dim": "#9aa2b3", "bar_bg": "#2b3140"},
    "glass": {"panel": "#1d2634", "border": "#4a5a78", "accent": "#5cc8ff", "text": "#ffffff", "dim": "#b9c4d4", "bar_bg": "#33405a"},
    "minimal": {"panel": "#0c0e14", "border": "#232833", "accent": "#ffffff", "text": "#ffffff", "dim": "#a0a6b4", "bar_bg": "#2a2f3a"},
    "neon": {"panel": "#12081f", "border": "#ff2da0", "accent": "#ff2da0", "text": "#f6f2ff", "dim": "#9a8fb0", "bar_bg": "#3a2450"},
    "spotify": {"panel": "#121212", "border": "#232323", "accent": "#1ed760", "text": "#ffffff", "dim": "#b3b3b3", "bar_bg": "#333333"},
    "light": {"panel": "#fafbff", "border": "#d8dce8", "accent": "#2563eb", "text": "#111827", "dim": "#6b7280", "bar_bg": "#e2e6ef"},
    "bar": {"panel": "#10131b", "border": "#2a2f3d", "accent": "#ff9f19", "text": "#f2f3f7", "dim": "#9aa2b3", "bar_bg": "#2b3140"},
    "center": {"panel": "#1d2634", "border": "#4a5a78", "accent": "#5cc8ff", "text": "#ffffff", "dim": "#b9c4d4", "bar_bg": "#33405a"},
}


def _hex_to_rgb(color: str) -> tuple:
    color = color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _lerp_color(c1: str, c2: str, t: float) -> str:
    a = _hex_to_rgb(c1)
    b = _hex_to_rgb(c2)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


class FloatingOverlay:
    def __init__(
        self,
        master,
        state_hub: StateHub,
        cover_store: CoverStore,
        config: OverlayConfig,
        refresh_ms: int = 250,
        settings=None,
        client=None,
    ) -> None:
        self.master = master
        self.state_hub = state_hub
        self.cover_store = cover_store
        self.config = config
        self.settings = settings
        self.client = client
        self.refresh_ms = max(100, refresh_ms)
        self.scale = 1.0
        self._base_h = 300
        self._applied_base_h = 300
        self._display_h = 300
        self._panel_anim_h = 300
        self._resize_anim_job = None
        self._last_cur = ""
        self._last_nxt = ""
        self.opacity = 0.9
        self.locked = False
        self.closed = False
        self._drag_offset: Optional[tuple] = None
        self._cover_ts = -1
        self._cover_loaded_scale = None
        self._photo: Optional[tk.PhotoImage] = None
        self._theme_sig: Optional[tuple] = None
        self._last_snap: Optional[dict] = None
        self._anim_running = False
        self._anim_jobs: list = []
        self._font_measure_cache: dict = {}
        self._lock_hint_job = None
        self._lock_hint_text = ""
        self._hotkey_event = threading.Event()
        self._stop_hotkey = threading.Event()
        self._hotkey_thread: Optional[threading.Thread] = None

        self.win = tk.Toplevel(master)
        self.win.title("桌面悬浮窗")
        icon = icon_path()
        if icon.exists():
            try:
                self.win.iconbitmap(str(icon))
            except Exception:
                pass
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.win.attributes("-alpha", self.opacity)
        self.win.configure(bg=TRANSPARENT)
        self.canvas = tk.Canvas(self.win, bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self._build_menu()
        self._bind_events()
        self._set_geometry()
        self._start_hotkey()
        self._draw()
        self.win.after(100, self._tick)

    # ------------------------------------------------------------ helpers

    def _colors(self) -> dict:
        base = dict(TK_THEMES.get(self.config.theme, TK_THEMES["modern"]))
        if self.config.panel:
            base["panel"] = self.config.panel
        if self.config.accent:
            base["accent"] = self.config.accent
            base["accent2"] = self.config.accent2 or self.config.accent
        else:
            base["accent2"] = base["accent"]
        if self.config.text:
            base["text"] = self.config.text
        if self.config.dim:
            base["dim"] = self.config.dim
        return base

    def _theme_signature(self) -> tuple:
        c = self._colors()
        return (
            self.config.theme, self.config.lyric_font,
            c["panel"], c["border"], c["accent"], c["text"], c["dim"],
        )

    def _font(self, size: int, bold: bool = False) -> tuple:
        family = self.config.lyric_font or "Segoe UI"
        return (family, max(6, round(size * self.scale)), "bold" if bold else "normal")

    def _set_geometry(self) -> None:
        self._display_h = self._base_h
        self._panel_anim_h = self._base_h
        w, h = round(BASE_W * self.scale), round(self._base_h * self.scale)
        x = max(0, self.win.winfo_screenwidth() - w - 40)
        y = 40
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self._applied_base_h = self._base_h

    def _set_scale(self, value: float) -> None:
        if self._resize_anim_job is not None:
            try:
                self.win.after_cancel(self._resize_anim_job)
            except Exception:
                pass
            self._resize_anim_job = None
        old_w, old_h = self.win.winfo_width(), self.win.winfo_height()
        cx = self.win.winfo_x() + old_w // 2
        cy = self.win.winfo_y() + old_h // 2
        self.scale = max(SCALE_MIN, min(SCALE_MAX, value))
        self._display_h = self._base_h
        self._panel_anim_h = self._base_h
        w, h = round(BASE_W * self.scale), round(self._base_h * self.scale)
        self.win.geometry(f"{w}x{h}+{cx - w // 2}+{cy - h // 2}")
        self._draw()
        self._applied_base_h = self._base_h

    # -------------------------------------------------------------- events

    def _bind_events(self) -> None:
        self.canvas.bind("<Button-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)
        self.canvas.bind("<Button-3>", self._show_menu)
        self.canvas.bind("<Control-MouseWheel>", self._on_wheel)
        self.win.bind("<Control-Key-l>", lambda e: self.toggle_lock())
        self.win.bind("<Control-Key-L>", lambda e: self.toggle_lock())

    def _build_menu(self) -> None:
        self.menu = tk.Menu(self.win, tearoff=0)
        self.menu.add_command(label="⏯ 播放/暂停", command=lambda: self._player_cmd(CMD_PLAYPAUSE))
        self.menu.add_command(label="⏮ 上一首", command=lambda: self._player_cmd(CMD_PREV))
        self.menu.add_command(label="⏭ 下一首", command=lambda: self._player_cmd(CMD_NEXT))
        self.menu.add_command(label="⏹ 停止", command=lambda: self._player_cmd(CMD_STOP))
        self.menu.add_separator()

        appearance = tk.Menu(self.menu, tearoff=0)
        theme_menu = tk.Menu(appearance, tearoff=0)
        for key, meta in THEMES.items():
            theme_menu.add_command(
                label=meta["label"], command=lambda k=key: self._set_theme(k),
            )
        appearance.add_cascade(label="主题", menu=theme_menu)
        opacity_menu = tk.Menu(appearance, tearoff=0)
        for label, value in (
            ("100%", 1.0), ("90%", 0.9), ("80%", 0.8),
            ("70%", 0.7), ("60%", 0.6), ("50%", 0.5),
        ):
            opacity_menu.add_command(
                label=label, command=lambda v=value: self._set_opacity(v),
            )
        appearance.add_cascade(label="透明度", menu=opacity_menu)
        scale_menu = tk.Menu(appearance, tearoff=0)
        scale_menu.add_command(label="放大", command=lambda: self._set_scale(self.scale * 1.15))
        scale_menu.add_command(label="缩小", command=lambda: self._set_scale(self.scale / 1.15))
        scale_menu.add_command(label="重置 100%", command=lambda: self._set_scale(1.0))
        appearance.add_cascade(label="缩放", menu=scale_menu)
        self._font_anim_var = tk.BooleanVar(
            value=bool(getattr(self.settings, "floating_lyric_font_anim", True)),
        )
        appearance.add_checkbutton(
            label="歌词字号动画", variable=self._font_anim_var,
            command=self._toggle_font_anim,
        )
        self.menu.add_cascade(label="外观", menu=appearance)

        interaction = tk.Menu(self.menu, tearoff=0)
        interaction.add_command(label="锁定/解锁拖动 (Ctrl+Shift+L)", command=self.toggle_lock)
        self.menu.add_cascade(label="交互", menu=interaction)
        self.menu.add_separator()
        self.menu.add_command(label="关闭悬浮窗", command=self.close)

    def _player_cmd(self, cmd: int) -> None:
        if self.client is not None:
            try:
                self.client.send_command(cmd)
            except Exception:
                pass

    def _toggle_font_anim(self) -> None:
        if self.settings is not None:
            self.settings.floating_lyric_font_anim = bool(self._font_anim_var.get())
            try:
                self.settings.save()
            except Exception:
                pass

    def _set_opacity(self, value: float) -> None:
        self.opacity = max(0.3, min(1.0, value))
        try:
            self.win.attributes("-alpha", self.opacity)
        except tk.TclError:
            pass

    def _show_menu(self, event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _on_wheel(self, event) -> None:
        if self.locked:
            return
        if event.delta > 0:
            self._set_scale(self.scale * 1.1)
        else:
            self._set_scale(self.scale / 1.1)

    def _on_drag_start(self, event) -> None:
        if self.locked:
            return
        self._drag_offset = (event.x_root - self.win.winfo_x(), event.y_root - self.win.winfo_y())

    def _on_drag_move(self, event) -> None:
        if self.locked or self._drag_offset is None:
            return
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self.win.geometry(f"+{x}+{y}")

    def toggle_lock(self) -> None:
        self.locked = not self.locked
        self._show_lock_hint()

    def _set_theme(self, key: str) -> None:
        self.config.theme = key
        if self.settings is not None:
            try:
                self.settings.save()
            except Exception:
                pass
        self._draw()

    # ------------------------------------------------------------- hotkey

    def _start_hotkey(self) -> None:
        self._hotkey_thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self._hotkey_thread.start()

    def _hotkey_loop(self) -> None:
        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        user32.RegisterHotKey.restype = wt.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, ctypes.c_uint, ctypes.c_uint]
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
        user32.PostThreadMessageW.argtypes = [wt.DWORD, ctypes.c_uint, wt.WPARAM, wt.LPARAM]

        tid = ctypes.windll.kernel32.GetCurrentThreadId()
        user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_L)
        msg = wt.MSG()
        try:
            while not self._stop_hotkey.is_set():
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r <= 0:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self._hotkey_event.set()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    # ---------------------------------------------------------------- draw

    def _rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        return self.canvas.create_polygon(self._rounded_points(x1, y1, x2, y2, r), smooth=True, **kwargs)

    @staticmethod
    def _rounded_points(x1, y1, x2, y2, r):
        r = max(1, r)
        return [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]

    def _draw(self) -> None:
        self._anim_running = False
        self.canvas.delete("all")
        s = self.scale
        colors = self._colors()
        w, h = round(BASE_W * s), round(self._display_h * s)
        self._panel_anim_h = self._display_h
        m = 12 * s
        self._panel_item = self._rounded_rect(
            m, m, w - m, h - m, 30 * s,
            fill=colors["panel"], outline=colors["border"],
            width=max(1, round(1.2 * s)), tags="panel",
        )

        # cover (reload at current scale so it always follows the window size)
        cover_size = round(96 * s)
        cover_x, cover_y = round(26 * s), round(26 * s)
        self._cover_pos = (cover_x, cover_y, cover_size)
        self._load_cover()
        self._update_cover_item()

        # title / artist (dim, like the browser source)
        tx = round(136 * s)
        max_text_w = w - tx - round(60 * s)
        self._title_item = self.canvas.create_text(
            tx, round(52 * s), anchor="nw", fill=colors["text"], font=self._font(16, True),
        )
        self._artist_item = self.canvas.create_text(
            tx, round(80 * s), anchor="nw", fill=colors["dim"], font=self._font(11),
        )
        self._max_text_w = max_text_w

        # progress (bar background + fill, like the browser source)
        bar_x1 = round(26 * s)
        bar_x2 = w - round(26 * s)
        bar_y = round(134 * s)
        bar_h = max(3, round(5 * s))
        self._rounded_rect(
            bar_x1, bar_y, bar_x2, bar_y + bar_h, bar_h / 2,
            fill=colors["bar_bg"], outline="",
        )
        self._bar_x1, self._bar_x2, self._bar_y, self._bar_h = bar_x1, bar_x2, bar_y, bar_h
        self._bar_fill_item = self._rounded_rect(
            bar_x1, bar_y, bar_x1, bar_y + bar_h, bar_h / 2,
            fill=colors["accent"], outline="", tags="barfill",
        )
        time_y = bar_y + bar_h + round(6 * s)
        self._time_left_item = self.canvas.create_text(
            bar_x1, time_y, anchor="nw", text="0:00",
            fill=colors["dim"], font=self._font(9), tags="time",
        )
        self._time_right_item = self.canvas.create_text(
            bar_x2, time_y, anchor="e", text="0:00",
            fill=colors["dim"], font=self._font(9), tags="time",
        )

        # lyric slots (explicit font objects so the selected lyric font applies)
        family = self.config.lyric_font or "Segoe UI"
        self._lyric_font_obj = tkfont.Font(
            root=self.win, family=family, size=max(6, round(14 * s)), weight="bold",
        )
        self._lyric_next_font_obj = tkfont.Font(
            root=self.win, family=family, size=max(6, round(11 * s)),
        )
        self._lyric_max_w = w - 2 * round(26 * s) - round(50 * s)
        lx = round(26 * s)
        self._lyric_cur_item = self.canvas.create_text(
            lx, 0, anchor="nw", fill=colors["text"], font=self._lyric_font_obj,
        )
        self._lyric_next_item = self.canvas.create_text(
            lx, 0, anchor="nw", fill=colors["dim"], font=self._lyric_next_font_obj,
        )
        self._lyric_x = lx
        self._layout_lyrics(self._last_cur, self._last_nxt)
        self.canvas.coords(self._lyric_cur_item, lx, self._lyric_cur_y)
        self.canvas.coords(self._lyric_next_item, lx, self._lyric_next_y)

        # lock indicator
        self._lock_item = self.canvas.create_text(
            w - round(30 * s), h - round(26 * s), anchor="e",
            text="", fill=colors["accent"], font=("Segoe UI Emoji", max(8, round(11 * s))),
        )
        if self._lock_hint_text:
            self.canvas.itemconfig(self._lock_item, text=self._lock_hint_text)
        self._theme_sig = self._theme_signature()

    def _update_cover_item(self) -> None:
        self.canvas.delete("cover")
        if self._photo is None:
            return
        x, y, size = self._cover_pos
        self.canvas.create_image(x, y, anchor="nw", image=self._photo, tags="cover")
        self.canvas.create_rectangle(x, y, x + size, y + size, outline="", tags="cover")

    def _load_cover(self) -> None:
        data, _mime, ts = self.cover_store.get()
        size = max(8, round(96 * self.scale))
        if self._cover_ts == ts and getattr(self, "_cover_loaded_scale", None) == self.scale:
            return
        self._cover_ts = ts
        self._cover_loaded_scale = self.scale
        try:
            img = Image.open(io.BytesIO(data)).convert("RGBA")
            img = ImageOps.fit(img, (size, size), Image.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, size - 1, size - 1], radius=max(2, round(10 * self.scale)), fill=255,
            )
            img.putalpha(mask)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            self._photo = tk.PhotoImage(data=base64.b64encode(buf.getvalue()).decode("ascii"))
        except Exception:
            self._photo = None

    def _fit(self, text: str, font, max_w: int) -> str:
        if not text:
            return ""
        if isinstance(font, tuple):
            if font not in self._font_measure_cache:
                self._font_measure_cache[font] = tkfont.Font(font=font)
            f = self._font_measure_cache[font]
        else:
            f = font
        if f.measure(text) <= max_w:
            return text
        while text and f.measure(text + "…") > max_w:
            text = text[:-1]
        return text + "…"

    def _fit_multiline(self, text: str, font, max_w: int) -> str:
        return "\n".join(self._fit(line, font, max_w) for line in text.split("\n")[:2])

    def _layout_lyrics(self, cur_text: str, nxt_text: str = "") -> None:
        s = self.scale
        cur_lines = max(1, cur_text.count("\n") + 1)
        nxt_lines = max(1, nxt_text.count("\n") + 1)
        cur_h = self._lyric_font_obj.metrics("linespace")
        nxt_h = self._lyric_next_font_obj.metrics("linespace")
        gap = round(8 * s)
        block_h = cur_lines * cur_h
        nxt_block_h = nxt_lines * nxt_h
        cur_y = round(172 * s)
        next_y = cur_y + block_h + gap
        bottom = next_y + nxt_block_h + round(28 * s)
        self._lyric_cur_block_h = block_h
        self._lyric_next_block_h = nxt_block_h
        self._lyric_cur_y = cur_y
        self._lyric_next_y = next_y
        self._base_h = max(280, round(bottom / s))

    def _resize_window_geometry(self) -> None:
        w = round(BASE_W * self.scale)
        h = round(self._display_h * self.scale)
        cx = self.win.winfo_x() + self.win.winfo_width() // 2
        cy = self.win.winfo_y() + self.win.winfo_height() // 2
        self.win.geometry(f"{w}x{h}+{cx - w // 2}+{cy - h // 2}")

    def _update_panel_height(self) -> None:
        s = self.scale
        colors = self._colors()
        w, h = round(BASE_W * s), round(self._panel_anim_h * s)
        m = 12 * s
        if hasattr(self, "_panel_item"):
            self.canvas.coords(
                self._panel_item,
                *self._rounded_points(m, m, w - m, h - m, 30 * s),
            )
            self.canvas.itemconfig(
                self._panel_item,
                fill=colors["panel"], outline=colors["border"],
                width=max(1, round(1.2 * s)),
            )
        if hasattr(self, "_lock_item"):
            self.canvas.coords(self._lock_item, w - round(30 * s), h - round(26 * s))

    def _apply_size(self) -> None:
        if self._resize_anim_job is not None:
            return
        target = self._base_h
        start = self._panel_anim_h
        if target == start:
            self._applied_base_h = target
            return
        self._display_h = target
        self._resize_window_geometry()
        self._applied_base_h = target
        steps = 6
        duration = 180

        def frame(i: int) -> None:
            t = i / steps
            ease = t * t * (3 - 2 * t)
            self._panel_anim_h = max(280, round(start + (target - start) * ease))
            self._update_panel_height()
            if i < steps:
                self._resize_anim_job = self.win.after(
                    round(duration / steps), lambda: frame(i + 1)
                )
            else:
                self._panel_anim_h = target
                self._update_panel_height()
                self._resize_anim_job = None
                self._applied_base_h = target

        frame(0)

    def _update_dynamic(self, snap: dict) -> None:
        colors = self._colors()
        s = self.scale

        title = snap.get("title") or "未在播放"
        artist_album = " · ".join(x for x in (snap.get("artist"), snap.get("album")) if x)
        self.canvas.itemconfig(self._title_item, text=self._fit(title, self._font(16, True), self._max_text_w))
        self.canvas.itemconfig(self._artist_item, text=self._fit(artist_album or "未知艺术家", self._font(11), self._max_text_w))

        # progress
        progress = max(0.0, min(1.0, snap.get("progress") or 0.0))
        x2 = self._bar_x1 + (self._bar_x2 - self._bar_x1) * progress
        if progress <= 0.005:
            x2 = self._bar_x1
        self.canvas.coords(
            self._bar_fill_item,
            *self._rounded_points(
                self._bar_x1, self._bar_y, x2,
                self._bar_y + self._bar_h, self._bar_h / 2,
            ),
        )

        # time (left + right, like the browser source)
        time_y = self._bar_y + self._bar_h + round(6 * s)
        self.canvas.itemconfig(self._time_left_item, text=snap.get("position") or "0:00")
        self.canvas.coords(self._time_left_item, self._bar_x1, time_y)
        self.canvas.itemconfig(self._time_right_item, text=snap.get("duration") or "0:00")
        self.canvas.coords(self._time_right_item, self._bar_x2, time_y)


        # lyrics
        cur = snap.get("lyrics_current") or ""
        nxt = snap.get("lyrics_next") or ""
        if not snap.get("lyrics_synced"):
            full = snap.get("lyrics_full") or []
            cur = full[-2] if len(full) >= 2 else (full[-1] if full else "")
            nxt = full[-1] if len(full) >= 2 else ""
        self._update_lyrics(cur, nxt, colors)

    def _update_lyrics(self, cur: str, nxt: str, colors: dict) -> None:
        cur = self._fit_multiline(cur, self._lyric_font_obj, self._lyric_max_w)
        nxt = self._fit_multiline(nxt, self._lyric_next_font_obj, self._lyric_max_w)
        self._last_cur = cur
        self._last_nxt = nxt
        if self._anim_running:
            return
        old_cur = self.canvas.itemcget(self._lyric_cur_item, "text")
        if old_cur and old_cur != cur:
            self._animate_lyrics(cur, nxt)
            return
        self._layout_lyrics(cur, nxt)
        if self._base_h != self._applied_base_h:
            self._apply_size()
        if self._panel_anim_h < self._base_h:
            return
        self.canvas.itemconfig(self._lyric_cur_item, text=cur, fill=colors["text"])
        self.canvas.itemconfig(self._lyric_next_item, text=nxt, fill=colors["dim"])
        self.canvas.coords(self._lyric_cur_item, self._lyric_x, self._lyric_cur_y)
        self.canvas.coords(self._lyric_next_item, self._lyric_x, self._lyric_next_y)

    def _animate_lyrics(self, new_cur: str, new_nxt: str) -> None:
        colors = self._colors()
        panel = colors["panel"]
        text_c = colors["text"]
        dim_c = colors["dim"]
        old_cur = self.canvas.itemcget(self._lyric_cur_item, "text")
        old_nxt = self.canvas.itemcget(self._lyric_next_item, "text")
        self._anim_running = True
        up = self._lyric_next_y - self._lyric_cur_y
        slide = round(12 * self.scale)
        frames = 10
        delay = 24
        font_anim = bool(getattr(self.settings, "floating_lyric_font_anim", True))
        cur_font_size = max(6, round(14 * self.scale))
        next_font_size = max(6, round(11 * self.scale))
        last_font_size = next_font_size
        anim_font = None
        if font_anim:
            anim_font = tkfont.Font(
                root=self.win, family=self.config.lyric_font or "Segoe UI",
                size=next_font_size, weight="bold",
            )
        temp = self.canvas.create_text(
            self._lyric_x, self._lyric_next_y, anchor="nw",
            text=new_nxt, fill=panel, font=self._lyric_next_font_obj, tags="lyric_temp",
        )

        def frame(i: int) -> None:
            nonlocal last_font_size
            if self.closed or not self._anim_running:
                return
            t = i / frames
            cur_y = self._lyric_cur_y - up * t
            nxt_y = self._lyric_next_y - up * t
            temp_y = self._lyric_next_y + slide * (1 - t)
            self.canvas.coords(self._lyric_cur_item, self._lyric_x, cur_y)
            self.canvas.itemconfig(self._lyric_cur_item, text=old_cur, fill=_lerp_color(text_c, panel, t))
            self.canvas.coords(self._lyric_next_item, self._lyric_x, nxt_y)
            self.canvas.itemconfig(self._lyric_next_item, text=old_nxt, fill=_lerp_color(dim_c, text_c, t))
            if font_anim and anim_font is not None:
                font_size = round(next_font_size + (cur_font_size - next_font_size) * t)
                if font_size != last_font_size:
                    last_font_size = font_size
                    anim_font.configure(size=font_size)
                    self.canvas.itemconfig(self._lyric_next_item, font=anim_font)
            self.canvas.coords(temp, self._lyric_x, temp_y)
            self.canvas.itemconfig(temp, fill=_lerp_color(panel, dim_c, t))
            if i == frames:
                self.canvas.delete(temp)
                self._layout_lyrics(new_cur, new_nxt)
                if self._base_h != self._applied_base_h:
                    self._apply_size()
                    self._layout_lyrics(new_cur, new_nxt)
                if self._panel_anim_h >= self._base_h:
                    self.canvas.coords(self._lyric_cur_item, self._lyric_x, self._lyric_cur_y)
                    self.canvas.itemconfig(self._lyric_cur_item, text=new_cur, fill=text_c)
                    self.canvas.itemconfig(self._lyric_cur_item, font=self._lyric_font_obj)
                    self.canvas.coords(self._lyric_next_item, self._lyric_x, self._lyric_next_y)
                    self.canvas.itemconfig(self._lyric_next_item, text=new_nxt, fill=dim_c)
                    self.canvas.itemconfig(self._lyric_next_item, font=self._lyric_next_font_obj)
                self._anim_running = False
                return
            self.win.after(delay, lambda: frame(i + 1))

        self.win.after(delay, lambda: frame(1))

    def _show_lock_hint(self) -> None:
        if not hasattr(self, "_lock_item"):
            return
        if self._lock_hint_job is not None:
            try:
                self.win.after_cancel(self._lock_hint_job)
            except Exception:
                pass
        self._lock_hint_text = "🔒" if self.locked else "🔓"
        self.canvas.itemconfig(self._lock_item, text=self._lock_hint_text, fill=self._colors()["accent"])
        self._lock_hint_job = self.win.after(1800, self._hide_lock_hint)

    def _hide_lock_hint(self) -> None:
        self._lock_hint_job = None
        self._lock_hint_text = ""
        if hasattr(self, "_lock_item"):
            self.canvas.itemconfig(self._lock_item, text="")

    def _sync_config(self) -> None:
        sig = self._theme_signature()
        if sig != self._theme_sig:
            self._theme_sig = sig
            self._draw()

    def _tick(self) -> None:
        if self.closed:
            return
        if self._hotkey_event.is_set():
            self._hotkey_event.clear()
            self.toggle_lock()
        self._sync_config()
        snap = self.state_hub.snapshot()
        if snap.get("cover_ts", 0) != self._cover_ts:
            self._draw()
        self._update_dynamic(snap)
        self.win.after(self.refresh_ms, self._tick)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._anim_running = False
        if self._resize_anim_job is not None:
            try:
                self.win.after_cancel(self._resize_anim_job)
            except Exception:
                pass
            self._resize_anim_job = None
        if self._lock_hint_job is not None:
            try:
                self.win.after_cancel(self._lock_hint_job)
            except Exception:
                pass
            self._lock_hint_job = None
        self._stop_hotkey.set()
        if self._hotkey_thread is not None and self._hotkey_thread.is_alive():
            try:
                tid = self._hotkey_thread.native_id
                if tid:
                    ctypes.windll.user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            except Exception:
                pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
