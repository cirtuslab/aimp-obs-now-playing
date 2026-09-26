"""Notification-area (system tray) icon, built on ``Shell_NotifyIconW`` through ctypes.

The main window uses it to minimise into the tray instead of the taskbar. Keeping it dependency
free matters for the single-file exe, so the icon lives in a message-only window owned by a
worker thread (same pattern as the album-art receiver and the floating window's hotkey pump).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from pathlib import Path
from typing import Callable, Optional

WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_COMMAND = 0x0111
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0x0, 0x1, 0x2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO = 0x1
NIIF_NOSOUND = 0x10

MF_STRING = 0x0
TPM_RIGHTBUTTON = 0x2
TPM_RETURNCMD = 0x100

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
LR_DEFAULTSIZE = 0x40
IDI_APPLICATION = 32512

CMD_SHOW = 1
CMD_QUIT = 2

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
_user32.CreateWindowExW.restype = wt.HWND
_user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, ctypes.c_uint, ctypes.c_uint]
_user32.GetMessageW.restype = ctypes.c_int
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
_user32.DestroyWindow.argtypes = [wt.HWND]
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_user32.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
_user32.PostMessageW.restype = wt.BOOL
_user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
_user32.LoadImageW.restype = wt.HANDLE
_user32.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
_user32.LoadIconW.restype = wt.HICON
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
_user32.CreatePopupMenu.restype = wt.HMENU
_user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
_user32.TrackPopupMenu.argtypes = [
    wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID,
]
_user32.TrackPopupMenu.restype = ctypes.c_uint
_user32.DestroyMenu.argtypes = [wt.HMENU]
_user32.SetForegroundWindow.argtypes = [wt.HWND]
_user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
_user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
_user32.RegisterWindowMessageW.restype = wt.UINT
_user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.PostThreadMessageW.restype = wt.BOOL
_shell32 = ctypes.windll.shell32
_kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wt.HINSTANCE
_kernel32.GetCurrentThreadId.restype = wt.DWORD

# Reuse the window-class definitions from the AIMP client: ctypes keeps one shared
# ``windll.user32`` per process, so two modules must not register the same function with
# different (structurally identical) Structure types.
from .aimp_api import WNDCLASSEXW, WNDPROC  # noqa: E402  (shared Win32 plumbing)


class NOTIFYICONDATAW(ctypes.Structure):
    """NOTIFYICONDATA v2 (Windows 2000+ layout, still accepted by the shell)."""

    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
    ]


_shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
_shell32.Shell_NotifyIconW.restype = wt.BOOL


class TrayIcon:
    """Tray icon with a small menu ("显示主窗口" / "退出").

    ``on_show`` and ``on_quit`` are invoked on the tray thread: they must be thread safe and
    must not touch Tk (signal the UI thread instead).
    """

    def __init__(
        self,
        tooltip: str,
        icon_path: Optional[Path] = None,
        on_show: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ) -> None:
        self.tooltip = tooltip
        self.icon_path = Path(icon_path) if icon_path else None
        self.on_show = on_show
        self.on_quit = on_quit

        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._hwnd: int = 0
        self._hicon: int = 0
        self._visible = False
        self._lock = threading.Lock()
        self._wndproc_ref = WNDPROC(self._wndproc)  # keep alive for the window class
        self._taskbar_created = 0

    # ------------------------------------------------------------------ public
    def start(self) -> bool:
        """Spin up the message window. Safe to call repeatedly."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="TrayIcon",
            )
            self._thread.start()
        return self._ready.wait(3.0) and bool(self._hwnd)

    def show(self, hint: str = "") -> bool:
        """Add the icon (or refresh it); ``hint`` shows a one-off (silent) balloon message."""
        if not self.start():
            return False
        data = self._notify_data(hint)
        added = self._visible
        cmd = NIM_MODIFY if added else NIM_ADD
        ok = bool(_shell32.Shell_NotifyIconW(cmd, ctypes.byref(data)))
        if ok:
            self._visible = True
        return ok

    def hide(self) -> bool:
        """Remove the icon from the notification area."""
        if not self._hwnd or not self._visible:
            return True
        data = self._notify_data()
        ok = bool(_shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data)))
        self._visible = False
        return ok

    def stop(self) -> None:
        self.hide()
        thread = self._thread
        if thread and thread.is_alive() and self._hwnd:
            tid = thread.native_id
            if tid:
                _user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        self._thread = None

    @property
    def hwnd(self) -> int:
        return self._hwnd

    @property
    def visible(self) -> bool:
        return self._visible

    # ----------------------------------------------------------------- internal
    def _notify_data(self, hint: str = "") -> NOTIFYICONDATAW:
        data = NOTIFYICONDATAW()
        # NOTIFYICONDATA v2 size (no trailing padding) so the shell parses our layout.
        data.cbSize = NOTIFYICONDATAW.dwInfoFlags.offset + ctypes.sizeof(wt.DWORD)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self._hicon
        data.szTip = self.tooltip[:127]
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        if hint:
            data.uFlags |= NIF_INFO
            data.szInfo = hint[:255]
            data.szInfoTitle = self.tooltip[:63]
            # NIIF_NOSOUND: the default information chime is jarring for a "minimised" hint.
            data.dwInfoFlags = NIIF_INFO | NIIF_NOSOUND
        return data

    def _run(self) -> None:
        instance = _kernel32.GetModuleHandleW(None)
        class_name = f"AIMPNowPlayingTray{id(self):x}"
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = instance
        wc.lpszClassName = class_name
        if not _user32.RegisterClassExW(ctypes.byref(wc)):
            self._ready.set()
            return

        self._taskbar_created = _user32.RegisterWindowMessageW("TaskbarCreated")
        hwnd = _user32.CreateWindowExW(
            0, class_name, "AIMPNowPlayingTray", 0, 0, 0, 0, 0, None, None, instance, None,
        )
        self._hwnd = int(hwnd or 0)
        if self._hwnd:
            self._hicon = _user32.LoadImageW(
                None, str(self.icon_path) if self.icon_path else None, IMAGE_ICON, 0, 0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            ) or _user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
        self._ready.set()
        if not self._hwnd:
            return

        msg = wt.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        _user32.DestroyWindow(hwnd)
        _user32.UnregisterClassW(class_name, instance)
        self._hwnd = 0

    def _wndproc(self, hwnd, msg, wparam, lparam) -> int:
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self._fire(self.on_show)
            elif event == WM_RBUTTONUP:
                self._popup_menu(hwnd)
            return 0
        if msg == WM_COMMAND:
            self._command(wparam & 0xFFFF)
            return 0
        if msg == WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        if msg and msg == self._taskbar_created and self._visible:
            # Explorer restarted: the shell forgot our icon, put it back.
            _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._notify_data()))
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _command(self, cmd: int) -> None:
        if cmd == CMD_SHOW:
            self._fire(self.on_show)
        elif cmd == CMD_QUIT:
            self._fire(self.on_quit)

    def _popup_menu(self, hwnd) -> None:
        menu = _user32.CreatePopupMenu()
        if not menu:
            return
        try:
            _user32.AppendMenuW(menu, MF_STRING, CMD_SHOW, "显示主窗口")
            _user32.AppendMenuW(menu, MF_STRING, CMD_QUIT, "退出")
            point = wt.POINT()
            _user32.GetCursorPos(ctypes.byref(point))
            _user32.SetForegroundWindow(hwnd)  # so the menu closes when clicking elsewhere
            cmd = _user32.TrackPopupMenu(
                menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, point.x, point.y, 0, hwnd, None,
            )
            _user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        finally:
            _user32.DestroyMenu(menu)
        if cmd:
            self._command(cmd)

    @staticmethod
    def _fire(callback: Optional[Callable[[], None]]) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception:
            pass
