"""Thin ctypes wrapper around AIMP's built-in Remote Control API.

AIMP exposes a remote access window (class ``AIMP2_RemoteInfo``) since long
before plugins were needed.  We use:

  * WM_AIMP_PROPERTY / WM_AIMP_COMMAND messages for state, position, duration;
  * a named shared-memory mapping ``AIMP2_RemoteInfo`` for track tags;
  * WM_COPYDATA for the album art (AIMP sends PNG bytes).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import queue
import struct
import threading
from typing import Dict, Optional

AIMP_CLASS = "AIMP2_RemoteInfo"
AIMP_MAP_SIZE = 2048

WM_USER = 0x0400
WM_AIMP_COMMAND = WM_USER + 0x75
WM_AIMP_NOTIFY = WM_USER + 0x76
WM_AIMP_PROPERTY = WM_USER + 0x77
WM_COPYDATA = 0x004A
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_AIMP_COPYDATA_ALBUMART_ID = 0x41495043

PROPVALUE_GET = 0
PROPVALUE_SET = 1

PROP_VERSION = 0x10
PROP_PLAYER_POSITION = 0x20
PROP_PLAYER_DURATION = 0x30
PROP_PLAYER_STATE = 0x40
PROP_VOLUME = 0x50
PROP_MUTE = 0x60
PROP_TRACK_REPEAT = 0x70
PROP_TRACK_SHUFFLE = 0x80

CMD_BASE = 10
CMD_REGISTER_NOTIFY = CMD_BASE + 1
CMD_UNREGISTER_NOTIFY = CMD_BASE + 2
CMD_PLAY = CMD_BASE + 3
CMD_PLAYPAUSE = CMD_BASE + 4
CMD_PAUSE = CMD_BASE + 5
CMD_STOP = CMD_BASE + 6
CMD_NEXT = CMD_BASE + 7
CMD_PREV = CMD_BASE + 8
CMD_QUIT = CMD_BASE + 11
CMD_GET_ALBUMART = CMD_BASE + 19

NOTIFY_TRACK_INFO = 1
NOTIFY_TRACK_START = 2
NOTIFY_PROPERTY = 3

FILE_MAP_READ = 0x0004

_TRACK_STRUCT = "<IIIIIqIIIIIIIII6I"
_TRACK_FIELDS = (
    "Deprecated1", "Active", "BitRate", "Channels", "Duration", "FileSize",
    "FileMark", "SampleRate", "TrackNumber", "AlbumLength", "ArtistLength",
    "DateLength", "FileNameLength", "GenreLength", "TitleLength",
)

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def _setup_user32() -> None:
    _user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
    _user32.FindWindowW.restype = wt.HWND
    _user32.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
    _user32.SendMessageW.restype = ctypes.c_ssize_t
    _user32.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
    _user32.PostMessageW.restype = wt.BOOL
    _user32.IsWindow.argtypes = [wt.HWND]
    _user32.IsWindow.restype = wt.BOOL
    _user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
    _user32.DefWindowProcW.restype = ctypes.c_ssize_t
    _user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    _user32.CreateWindowExW.argtypes = [
        wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
    ]
    _user32.CreateWindowExW.restype = wt.HWND
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, ctypes.c_uint, ctypes.c_uint]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
    _user32.DestroyWindow.argtypes = [wt.HWND]
    _user32.DestroyWindow.restype = wt.BOOL
    _user32.PostQuitMessage.argtypes = [ctypes.c_int]
    _kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wt.HINSTANCE
    _kernel32.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    _kernel32.OpenFileMappingW.restype = wt.HANDLE
    _kernel32.MapViewOfFile.argtypes = [
        wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t,
    ]
    _kernel32.MapViewOfFile.restype = ctypes.c_void_p
    _kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.argtypes = [wt.HANDLE]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT),
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


class COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [
        ("dwData", ctypes.c_ssize_t),
        ("cbData", wt.DWORD),
        ("lpData", ctypes.c_void_p),
    ]


_setup_user32()


class AimpError(RuntimeError):
    pass


def find_aimp_window() -> int:
    hwnd = _user32.FindWindowW(AIMP_CLASS, None)
    if not hwnd:
        hwnd = _user32.FindWindowW(AIMP_CLASS, AIMP_CLASS)
    return int(hwnd or 0)


class AimpClient:
    """Communicates with the running AIMP instance."""

    def __init__(self) -> None:
        self._hwnd = 0
        self.detect()

    @property
    def hwnd(self) -> int:
        return self._hwnd

    @property
    def connected(self) -> bool:
        return self._hwnd != 0

    def detect(self) -> bool:
        self._hwnd = find_aimp_window()
        return self.connected

    def refresh_handle(self) -> bool:
        """Re-validate the AIMP window handle so a restarted AIMP is picked up."""
        if self._hwnd:
            if _user32.IsWindow(self._hwnd):
                buf = ctypes.create_unicode_buffer(64)
                _user32.GetClassNameW(self._hwnd, buf, 64)
                if buf.value == AIMP_CLASS:
                    return True
        self._hwnd = find_aimp_window()
        return self.connected

    def send_message(self, msg: int, wparam: int, lparam: int = 0) -> int:
        if not self._hwnd:
            raise AimpError("AIMP is not running")
        return int(_user32.SendMessageW(self._hwnd, msg, wparam, lparam))

    def get_property(self, prop: int) -> int:
        return self.send_message(WM_AIMP_PROPERTY, prop | PROPVALUE_GET, 0)

    def set_property(self, prop: int, value: int) -> bool:
        return self.send_message(WM_AIMP_PROPERTY, prop | PROPVALUE_SET, value) != 0

    def send_command(self, cmd: int, param: int = 0) -> int:
        return self.send_message(WM_AIMP_COMMAND, cmd, param)

    def register_notify(self, hwnd: int) -> bool:
        return self.send_command(CMD_REGISTER_NOTIFY, hwnd) != 0

    def unregister_notify(self, hwnd: int) -> bool:
        try:
            self.send_command(CMD_UNREGISTER_NOTIFY, hwnd)
            return True
        except AimpError:
            return False

    def request_album_art(self, receiver_hwnd: int) -> bool:
        return self.send_command(CMD_GET_ALBUMART, receiver_hwnd) != 0

    # ---- player properties -------------------------------------------------

    def get_version(self) -> Optional[tuple]:
        v = self.get_property(PROP_VERSION)
        if not v:
            return None
        return (v >> 16) / 100, v & 0xFFFF

    def get_player_state(self) -> int:
        return self.get_property(PROP_PLAYER_STATE)

    def get_position(self) -> int:
        return self.get_property(PROP_PLAYER_POSITION)

    def get_duration(self) -> int:
        return self.get_property(PROP_PLAYER_DURATION)

    def get_volume(self) -> int:
        return self.get_property(PROP_VOLUME)

    def is_muted(self) -> bool:
        return bool(self.get_property(PROP_MUTE))

    def is_shuffled(self) -> bool:
        return bool(self.get_property(PROP_TRACK_SHUFFLE))

    def is_repeated(self) -> bool:
        return bool(self.get_property(PROP_TRACK_REPEAT))

    # ---- track tags --------------------------------------------------------

    def get_track_info(self) -> Optional[Dict[str, object]]:
        """Read the current track from AIMP's shared memory mapping."""
        if not self._hwnd:
            raise AimpError("AIMP is not running")
        hmap = _kernel32.OpenFileMappingW(FILE_MAP_READ, False, AIMP_CLASS)
        if not hmap:
            return None
        try:
            view = _kernel32.MapViewOfFile(hmap, FILE_MAP_READ, 0, 0, AIMP_MAP_SIZE)
            if not view:
                return None
            try:
                data = ctypes.string_at(view, AIMP_MAP_SIZE)
            finally:
                _kernel32.UnmapViewOfFile(view)
        finally:
            _kernel32.CloseHandle(hmap)

        try:
            values = struct.unpack_from(_TRACK_STRUCT, data, 0)
        except struct.error:
            return None
        meta = dict(zip(_TRACK_FIELDS, values[: len(_TRACK_FIELDS)]))
        if not meta.get("Active"):
            return None

        offset = struct.calcsize(_TRACK_STRUCT)
        pos = offset
        text: Dict[str, str] = {}
        for key in ("Album", "Artist", "Date", "FileName", "Genre", "Title"):
            length = int(meta[key + "Length"])
            raw = data[pos:pos + length * 2]
            text[key] = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
            pos += length * 2

        return {
            "bit_rate": int(meta["BitRate"]),
            "channels": int(meta["Channels"]),
            "duration": int(meta["Duration"]),
            "file_size": int(meta["FileSize"]),
            "file_mark": int(meta["FileMark"]),
            "sample_rate": int(meta["SampleRate"]),
            "track_number": int(meta["TrackNumber"]),
            "album": text["Album"],
            "artist": text["Artist"],
            "year": text["Date"],
            "filename": text["FileName"],
            "genre": text["Genre"],
            "title": text["Title"],
        }


class AlbumArtReceiver:
    """Hidden message-only window which receives album art via WM_COPYDATA."""

    _CLASS_NAME = "AimpNowPlaying_ArtReceiver"

    def __init__(self) -> None:
        self._hwnd: int = 0
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._class_registered = False
        self._art: Optional[bytes] = None
        self._art_lock = threading.Lock()
        self._dirty = threading.Event()
        self._wndproc_cb = WNDPROC(self._wndproc)

    @property
    def hwnd(self) -> int:
        return self._hwnd

    @property
    def dirty(self) -> threading.Event:
        return self._dirty

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="AIMPArtReceiver", daemon=True)
        self._thread.start()
        self._ready.wait(3)
        if not self._hwnd:
            raise AimpError("Failed to create album art receiver window")

    def stop(self) -> None:
        if self._hwnd:
            _user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            self._hwnd = 0

    def take_dirty(self) -> bool:
        return self._dirty.is_set()

    def clear_dirty(self) -> None:
        self._dirty.clear()

    def get_art(self) -> Optional[bytes]:
        with self._art_lock:
            return self._art

    def set_art(self, data: bytes) -> None:
        with self._art_lock:
            self._art = data

    def _run(self) -> None:
        hinst = _kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_cb
        wc.hInstance = hinst
        wc.lpszClassName = self._CLASS_NAME
        if not self._class_registered:
            _user32.RegisterClassExW(ctypes.byref(wc))
            self._class_registered = True
        h = _user32.CreateWindowExW(
            0, self._CLASS_NAME, self._CLASS_NAME, 0, 0, 0, 0, 0,
            None, None, hinst, None,
        )
        self._hwnd = int(h or 0)
        self._ready.set()
        msg = wt.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, h: int, msg: int, wp: int, lp: int) -> int:
        if msg == WM_COPYDATA:
            cds = ctypes.cast(lp, ctypes.POINTER(COPYDATASTRUCT)).contents
            if cds.dwData == WM_AIMP_COPYDATA_ALBUMART_ID:
                data = ctypes.string_at(cds.lpData, int(cds.cbData))
                if data:
                    self.set_art(data)
                    self._dirty.set()
                return 1
        elif msg == WM_CLOSE:
            _user32.DestroyWindow(h)
            return 0
        elif msg == WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return int(_user32.DefWindowProcW(h, msg, wp, lp))
