"""Zero-Tkinter WebView2 floating desktop overlay controller.

Runs as a second frameless, always-on-top pywebview window that:
- Never loads tcl86t.dll / Tkinter (completely eliminating cross-thread Tcl_Panic crashes).
- Hides itself from the Windows taskbar via Win32 ``WS_EX_TOOLWINDOW`` (without calling
  WinForms ``ShowInTaskbar = False``, which would recreate the HWND and abort WebView2).
- Uses Windows 11 native DWM rounded corners (``DWMWCP_ROUND``) and ``WS_EX_LAYERED``
  (``LWA_ALPHA``) for crisp edges and true desktop translucency.
- Hosts a native Win32 popup context menu (``TrackPopupMenu``) on its message thread so
  the menu floats freely outside the overlay bounds and is never clipped at small sizes.
- Supports ``Ctrl+Shift+L`` global hotkey to lock/unlock dragging.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import threading
from typing import Callable, Optional

from .aimp_api import WNDCLASSEXW, WNDPROC
from .overlay import THEMES
from .theme import (
    DWMWA_WINDOW_CORNER_PREFERENCE,
    DWMWCP_ROUND,
    WS_EX_TOOLWINDOW,
    compute_no_taskbar_exstyle,
)
from .webui import load_floating_html

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1

MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_L = 0x4C
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_NULL = 0x0000
WM_APP = 0x8000
WM_SHOW_MENU = WM_APP + 12
_HOTKEY_ID = 0xA10F

MF_STRING = 0x0000
MF_POPUP = 0x0010
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

# Native Win32 popup menu command IDs
_CMD_PLAYPAUSE = 101
_CMD_PREV = 102
_CMD_NEXT = 103
_CMD_STOP = 104
_CMD_THEME_BASE = 200
_CMD_OPACITY_BASE = 300
_CMD_SCALE_UP = 401
_CMD_SCALE_DOWN = 402
_CMD_SCALE_RESET = 403
_CMD_FONT_ANIM = 501
_CMD_LOCK = 601
_CMD_CLOSE = 701

_OPACITY_PRESETS = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5)

BASE_W, BASE_H = 560, 300
SCALE_MIN, SCALE_MAX = 0.55, 2.2


def _get_exstyle(hwnd: int) -> int:
    u32 = ctypes.WinDLL("user32")
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        u32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
        u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        return int(u32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
    u32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    u32.GetWindowLongW.restype = ctypes.c_long
    return int(u32.GetWindowLongW(hwnd, GWL_EXSTYLE))


def _set_exstyle(hwnd: int, value: int) -> None:
    u32 = ctypes.WinDLL("user32")
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        u32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, value)
    else:
        u32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
        u32.SetWindowLongW.restype = ctypes.c_long
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE, value)
    u32.SetWindowPos.argtypes = [
        wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wt.UINT,
    ]
    u32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def _primary_screen_width() -> int:
    if sys.platform != "win32":
        return 1920
    try:
        u32 = ctypes.WinDLL("user32")
        u32.GetSystemMetrics.argtypes = [ctypes.c_int]
        u32.GetSystemMetrics.restype = ctypes.c_int
        return int(u32.GetSystemMetrics(0)) or 1920
    except Exception:
        return 1920


def _dpi_scale() -> float:
    """Return the system DPI scale factor (e.g. 1.0, 1.25, 1.5, 2.0)."""
    if sys.platform != "win32":
        return 1.0
    try:
        u32 = ctypes.WinDLL("user32")
        u32.GetDpiForSystem.restype = wt.UINT
        dpi = int(u32.GetDpiForSystem())
        if dpi >= 96:
            return dpi / 96.0
    except Exception:
        # Fallback for older Windows builds without GetDpiForSystem.
        pass
    return 1.0


class FloatingOverlayHost:
    """Thread-safe controller for the pywebview desktop floating window."""

    def __init__(
        self,
        bridge,
        app=None,
        on_state_change: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self._bridge = bridge
        self._app = app
        self._on_state_change = on_state_change
        self._lock = threading.Lock()
        self._window = None
        self._locked = False
        self._scale = 1.0
        self._opacity = 0.90
        self._hotkey_thread: Optional[threading.Thread] = None
        self._hotkey_tid: int = 0

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._window is not None

    @property
    def is_locked(self) -> bool:
        with self._lock:
            return self._locked

    def open(self) -> bool:
        with self._lock:
            if self._window is not None:
                return True
        try:
            import webview

            w = round(BASE_W * self._scale)
            h = round(BASE_H * self._scale)
            dpi = _dpi_scale()
            logical_screen_w = round(_primary_screen_width() / dpi)
            x = max(20, logical_screen_w - w - 40)
            y = 40
            win = webview.create_window(
                title="桌面悬浮窗",
                html=load_floating_html(),
                js_api=self._bridge,
                width=w,
                height=h,
                x=x,
                y=y,
                resizable=False,
                frameless=True,
                transparent=False,
                on_top=True,
                shadow=True,
                background_color="#10131b",
                easy_drag=False,
            )
            win.events.loaded += lambda: self._on_loaded(win)
            win.events.closed += self._on_window_closed
            with self._lock:
                self._window = win
                self._locked = False
            self._start_hotkey_pump()
            self._notify(True)
            return True
        except Exception:
            return False

    def close(self) -> None:
        with self._lock:
            win = self._window
            self._window = None
            self._locked = False
        self._stop_hotkey_pump()
        if win is not None:
            try:
                win.destroy()
            except Exception:
                # Window may already be closing or destroyed.
                pass
        self._notify(False)

    def toggle(self) -> bool:
        if self.is_open:
            self.close()
            return False
        return self.open()

    def toggle_lock(self) -> bool:
        with self._lock:
            win = self._window
            if win is None:
                return False
            self._locked = not self._locked
            locked = self._locked
        try:
            flag = "true" if locked else "false"
            win.evaluate_js(f"window.__FLOAT_LOCK_STATE__ && window.__FLOAT_LOCK_STATE__({flag})")
        except Exception:
            # Floating webview may be mid-close during toggle.
            pass
        return locked

    def set_scale(self, scale: float) -> float:
        clamped = max(SCALE_MIN, min(SCALE_MAX, float(scale)))
        with self._lock:
            self._scale = clamped
            win = self._window
        if win is not None:
            try:
                win.resize(round(BASE_W * clamped), round(BASE_H * clamped))
            except Exception:
                # Ignore resize errors if floating window is closing.
                pass
            try:
                win.evaluate_js(f"window.__FLOAT_SET_SCALE__ && window.__FLOAT_SET_SCALE__({clamped:.4f})")
            except Exception:
                # Ignore JS bridge error while window is initializing/closing.
                pass
        return clamped

    def set_opacity(self, opacity: float) -> float:
        clamped = max(0.30, min(1.0, float(opacity)))
        with self._lock:
            self._opacity = clamped
            win = self._window
        if win is not None:
            self._apply_opacity(self._hwnd_of(win), clamped)
        return clamped

    def show_context_menu(self) -> bool:
        """Trigger a native Win32 desktop popup menu on the message thread (never clipped)."""
        if sys.platform != "win32":
            return False
        tid = self._hotkey_tid
        if not tid:
            return False
        try:
            u32 = ctypes.WinDLL("user32")
            u32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
            u32.PostThreadMessageW.restype = wt.BOOL
            return bool(u32.PostThreadMessageW(tid, WM_SHOW_MENU, 0, 0))
        except Exception:
            return False

    def ensure_visible(self) -> None:
        with self._lock:
            win = self._window
        if win is not None:
            self._apply_exstyle(win)

    # ---------------------------------------------------------------- internal

    def _on_loaded(self, win) -> None:
        self._configure_native_window(win)
        with self._lock:
            sc = self._scale
        try:
            win.evaluate_js(f"window.__FLOAT_SET_SCALE__ && window.__FLOAT_SET_SCALE__({sc:.4f})")
        except Exception:
            # Ignore if closed right after load.
            pass

    def _hwnd_of(self, win) -> int:
        native = getattr(win, "native", None)
        if native is None:
            return 0
        try:
            handle = getattr(native, "Handle", None)
            return int(handle.ToInt64()) if handle is not None else 0
        except Exception:
            return 0

    @staticmethod
    def _apply_opacity(hwnd: int, opacity: float) -> None:
        if sys.platform != "win32" or not hwnd:
            return
        try:
            u32 = ctypes.WinDLL("user32")
            u32.SetLayeredWindowAttributes.argtypes = [
                wt.HWND, wt.COLORREF, wt.BYTE, wt.DWORD,
            ]
            u32.SetLayeredWindowAttributes.restype = wt.BOOL
            alpha = max(60, min(255, round(opacity * 255)))
            u32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)
        except Exception:
            # Ignore if window handle became invalid.
            pass

    @staticmethod
    def _apply_round_corners(hwnd: int) -> None:
        if sys.platform != "win32" or not hwnd:
            return
        try:
            dwmapi = ctypes.WinDLL("dwmapi")
            dwmapi.DwmSetWindowAttribute.argtypes = [
                wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD,
            ]
            dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
            corner = ctypes.c_int(DWMWCP_ROUND)
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(corner), ctypes.sizeof(corner),
            )
        except Exception:
            # Older Windows 10 builds do not support DWM corner preference.
            pass

    def _configure_native_window(self, win) -> None:
        if sys.platform != "win32" or win is None:
            return
        hwnd = self._hwnd_of(win)
        if not hwnd:
            return
        try:
            u32 = ctypes.WinDLL("user32")
            u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
            u32.ShowWindow.restype = wt.BOOL
            u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
            u32.GetWindowRect.restype = wt.BOOL
            u32.SetWindowPos.argtypes = [
                wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wt.UINT,
            ]
            ex = compute_no_taskbar_exstyle(_get_exstyle(hwnd)) | WS_EX_TOOLWINDOW | WS_EX_LAYERED
            u32.ShowWindow(hwnd, SW_HIDE)
            _set_exstyle(hwnd, ex)
            self._apply_round_corners(hwnd)
            with self._lock:
                opacity = self._opacity
            self._apply_opacity(hwnd, opacity)
            rc = wt.RECT()
            if u32.GetWindowRect(hwnd, ctypes.byref(rc)):
                win_w = max(1, rc.right - rc.left)
                phys_w = _primary_screen_width()
                if rc.right > phys_w or rc.left < 0:
                    target_x = max(16, phys_w - win_w - 40)
                    u32.SetWindowPos(
                        hwnd, HWND_TOPMOST, target_x, 40, 0, 0,
                        SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
                    )
            u32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        except Exception:
            # Ignore Win32 errors if window handle became invalid.
            pass

    def _apply_exstyle(self, win) -> None:
        if sys.platform != "win32":
            return
        hwnd = self._hwnd_of(win)
        if not hwnd:
            return
        try:
            ex = compute_no_taskbar_exstyle(_get_exstyle(hwnd)) | WS_EX_TOOLWINDOW | WS_EX_LAYERED
            _set_exstyle(hwnd, ex)
            with self._lock:
                opacity = self._opacity
            self._apply_opacity(hwnd, opacity)
        except Exception:
            # Ignore Win32 errors if window handle became invalid.
            pass

    def _on_window_closed(self) -> None:
        with self._lock:
            self._window = None
            self._locked = False
        self._stop_hotkey_pump()
        self._notify(False)

    def _notify(self, state: bool) -> None:
        cb = self._on_state_change
        if cb is not None:
            try:
                cb(state)
            except Exception:
                # Ignore UI callback errors on teardown.
                pass

    # ------------------------------------------ Global Hotkey & Native Popup Menu

    def _start_hotkey_pump(self) -> None:
        if sys.platform != "win32":
            return
        with self._lock:
            if self._hotkey_thread is not None and self._hotkey_thread.is_alive():
                return
            self._hotkey_thread = threading.Thread(
                target=self._hotkey_loop,
                daemon=True,
                name="FloatHotkeyMenuPump",
            )
            self._hotkey_thread.start()

    def _stop_hotkey_pump(self) -> None:
        if sys.platform != "win32":
            return
        tid = self._hotkey_tid
        self._hotkey_tid = 0
        if tid:
            try:
                u32 = ctypes.WinDLL("user32")
                u32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
                u32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            except Exception:
                # Thread may have already exited.
                pass

    def _hotkey_loop(self) -> None:
        u32 = ctypes.WinDLL("user32")
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentThreadId.restype = wt.DWORD
        k32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        k32.GetModuleHandleW.restype = wt.HINSTANCE
        u32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
        u32.RegisterHotKey.restype = wt.BOOL
        u32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
        u32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
        u32.GetMessageW.restype = ctypes.c_int
        u32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
        u32.DefWindowProcW.restype = ctypes.c_ssize_t
        u32.CreateWindowExW.argtypes = [
            wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
        ]
        u32.CreateWindowExW.restype = wt.HWND
        u32.DestroyWindow.argtypes = [wt.HWND]
        u32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]

        # Hidden owner window on this thread so TrackPopupMenu dismisses properly on outside click.
        instance = k32.GetModuleHandleW(None)
        cls_name = f"AIMPFloatMenuOwner{id(self):x}"
        wndproc_ref = WNDPROC(lambda h, m, w, l: u32.DefWindowProcW(h, m, w, l))
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = wndproc_ref
        wc.hInstance = instance
        wc.lpszClassName = cls_name
        menu_hwnd = 0
        registered_cls = bool(ctypes.windll.user32.RegisterClassExW(ctypes.byref(wc)))
        if registered_cls:
            menu_hwnd = int(
                u32.CreateWindowExW(
                    0, cls_name, "AIMPFloatMenu", 0, 0, 0, 0, 0, None, None, instance, None,
                ) or 0
            )

        self._hotkey_tid = int(k32.GetCurrentThreadId())
        hk_ok = bool(
            u32.RegisterHotKey(None, _HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_L)
        )
        try:
            msg = wt.MSG()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    self.toggle_lock()
                elif msg.message == WM_SHOW_MENU and menu_hwnd:
                    self._popup_native_menu(u32, menu_hwnd)
        finally:
            if hk_ok:
                u32.UnregisterHotKey(None, _HOTKEY_ID)
            if menu_hwnd:
                u32.DestroyWindow(menu_hwnd)
            if registered_cls:
                u32.UnregisterClassW(cls_name, instance)
            self._hotkey_tid = 0

    def _popup_native_menu(self, u32, owner_hwnd: int) -> None:
        u32.CreatePopupMenu.restype = wt.HMENU
        u32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
        u32.DestroyMenu.argtypes = [wt.HMENU]
        u32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
        u32.SetForegroundWindow.argtypes = [wt.HWND]
        u32.TrackPopupMenu.argtypes = [
            wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, wt.HWND, wt.LPVOID,
        ]
        u32.TrackPopupMenu.restype = ctypes.c_uint
        u32.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]

        theme_keys = list(THEMES.keys())
        cur_theme = getattr(getattr(self._app, "server", None), "config", None)
        cur_theme_key = getattr(cur_theme, "theme", "modern")
        font_anim = bool(getattr(getattr(self._app, "settings", None), "floating_lyric_font_anim", True))
        with self._lock:
            cur_opacity = self._opacity
            cur_locked = self._locked

        menu = u32.CreatePopupMenu()
        theme_sub = u32.CreatePopupMenu()
        opacity_sub = u32.CreatePopupMenu()
        scale_sub = u32.CreatePopupMenu()
        if not menu:
            return
        try:
            u32.AppendMenuW(menu, MF_STRING, _CMD_PLAYPAUSE, "⏯ 播放 / 暂停")
            u32.AppendMenuW(menu, MF_STRING, _CMD_PREV, "⏮ 上一首")
            u32.AppendMenuW(menu, MF_STRING, _CMD_NEXT, "⏭ 下一首")
            u32.AppendMenuW(menu, MF_STRING, _CMD_STOP, "⏹ 停止")
            u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)

            for idx, key in enumerate(theme_keys):
                flags = MF_STRING | (MF_CHECKED if key == cur_theme_key else 0)
                u32.AppendMenuW(theme_sub, flags, _CMD_THEME_BASE + idx, THEMES[key]["label"])
            u32.AppendMenuW(menu, MF_POPUP, int(theme_sub), "主题")

            for idx, val in enumerate(_OPACITY_PRESETS):
                flags = MF_STRING | (MF_CHECKED if abs(cur_opacity - val) < 0.04 else 0)
                u32.AppendMenuW(opacity_sub, flags, _CMD_OPACITY_BASE + idx, f"{round(val * 100)}%")
            u32.AppendMenuW(menu, MF_POPUP, int(opacity_sub), "透明度")

            u32.AppendMenuW(scale_sub, MF_STRING, _CMD_SCALE_UP, "放大 (+15%)")
            u32.AppendMenuW(scale_sub, MF_STRING, _CMD_SCALE_DOWN, "缩小 (-15%)")
            u32.AppendMenuW(scale_sub, MF_STRING, _CMD_SCALE_RESET, "重置 100%")
            u32.AppendMenuW(menu, MF_POPUP, int(scale_sub), "缩放")

            u32.AppendMenuW(
                menu, MF_STRING | (MF_CHECKED if font_anim else 0),
                _CMD_FONT_ANIM, "歌词字号动画",
            )
            u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            u32.AppendMenuW(
                menu, MF_STRING | (MF_CHECKED if cur_locked else 0),
                _CMD_LOCK, "锁定拖动 (Ctrl+Shift+L)",
            )
            u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            u32.AppendMenuW(menu, MF_STRING, _CMD_CLOSE, "关闭悬浮窗")

            pt = wt.POINT()
            u32.GetCursorPos(ctypes.byref(pt))
            u32.SetForegroundWindow(owner_hwnd)
            cmd = int(
                u32.TrackPopupMenu(
                    menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, owner_hwnd, None,
                )
            )
            u32.PostMessageW(owner_hwnd, WM_NULL, 0, 0)
        finally:
            # Destroying the root menu also destroys its attached submenus.
            u32.DestroyMenu(menu)

        self._handle_menu_cmd(cmd, theme_keys, font_anim)

    def _handle_menu_cmd(self, cmd: int, theme_keys: list, cur_font_anim: bool) -> None:
        if not cmd:
            return
        app = self._app
        if cmd == _CMD_PLAYPAUSE and app:
            app.send_player_cmd("playpause")
        elif cmd == _CMD_PREV and app:
            app.send_player_cmd("prev")
        elif cmd == _CMD_NEXT and app:
            app.send_player_cmd("next")
        elif cmd == _CMD_STOP and app:
            app.send_player_cmd("stop")
        elif _CMD_THEME_BASE <= cmd < _CMD_THEME_BASE + len(theme_keys) and app:
            app.update_overlay({"theme": theme_keys[cmd - _CMD_THEME_BASE]})
        elif _CMD_OPACITY_BASE <= cmd < _CMD_OPACITY_BASE + len(_OPACITY_PRESETS):
            self.set_opacity(_OPACITY_PRESETS[cmd - _CMD_OPACITY_BASE])
        elif cmd == _CMD_SCALE_UP:
            self.set_scale(self._scale * 1.15)
        elif cmd == _CMD_SCALE_DOWN:
            self.set_scale(self._scale / 1.15)
        elif cmd == _CMD_SCALE_RESET:
            self.set_scale(1.0)
        elif cmd == _CMD_FONT_ANIM and app:
            app.set_floating_font_anim(not cur_font_anim)
        elif cmd == _CMD_LOCK:
            self.toggle_lock()
        elif cmd == _CMD_CLOSE:
            self.close()
