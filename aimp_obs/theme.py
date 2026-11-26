"""Theme tokens, color math, native titlebar sync, and crisp vector icons.

Zero extra dependencies: icons are anti-aliased 2x-supersampled Pillow drawings,
giving clean geometric glyphs across Windows versions without emoji fallback boxes.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import math
import time
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Dual-mode color palettes ("Obsidian Studio" & "Porcelain Studio")
# ---------------------------------------------------------------------------

DARK_PALETTE: Dict[str, str] = {
    "mode": "dark",
    "bg": "#0B0D12",
    "sidebar": "#10131A",
    "card": "#161A23",
    "card_alt": "#1C212D",
    "card_hover": "#232938",
    "border": "#242B3A",
    "border_strong": "#333D52",
    "text": "#F2F4F8",
    "text_secondary": "#A5B0C4",
    "text_muted": "#6C768C",
    "accent": "#FF9A1F",
    "accent_hover": "#FFB24C",
    "accent_soft": "#2A1F10",
    "accent_fg": "#181005",
    "success": "#2ED47A",
    "success_soft": "#10281C",
    "warning": "#F5B73B",
    "warning_soft": "#2A210F",
    "danger": "#F25F5C",
    "danger_soft": "#2D1416",
    "button": "#202634",
    "button_hover": "#2B3346",
    "track_bg": "#242B3A",
    "toast_bg": "#1F2534",
    "toast_border": "#364158",
    "preview_canvas": "#090B10",
    "preview_grid": "#181D28",
}

LIGHT_PALETTE: Dict[str, str] = {
    "mode": "light",
    "bg": "#F3F5F9",
    "sidebar": "#FFFFFF",
    "card": "#FFFFFF",
    "card_alt": "#F1F4F9",
    "card_hover": "#E7ECF4",
    "border": "#E1E6F0",
    "border_strong": "#C8D1E0",
    "text": "#121723",
    "text_secondary": "#4B566B",
    "text_muted": "#818C9F",
    "accent": "#E67700",
    "accent_hover": "#CC6900",
    "accent_soft": "#FFF2E2",
    "accent_fg": "#FFFFFF",
    "success": "#16A34A",
    "success_soft": "#E6F8ED",
    "warning": "#D97706",
    "warning_soft": "#FEF3DB",
    "danger": "#DC2626",
    "danger_soft": "#FDECEC",
    "button": "#EEF1F7",
    "button_hover": "#E2E7F0",
    "track_bg": "#DCE3EE",
    "toast_bg": "#171C28",
    "toast_border": "#2C3548",
    "preview_canvas": "#E7ECF4",
    "preview_grid": "#D5DCE8",
}

PALETTES: Dict[str, Dict[str, str]] = {
    "dark": DARK_PALETTE,
    "light": LIGHT_PALETTE,
}

# Preview styles for the 8 OBS themes (used by the live mini-preview canvas)
OVERLAY_THEME_META: Dict[str, Dict[str, str]] = {
    "modern":  {"panel": "#141822", "border": "#2E3546", "text": "#F2F3F7", "dim": "#9CA3B5", "accent": "#FF9F19", "accent2": "#FFD08A"},
    "glass":   {"panel": "#1C2438", "border": "#48608A", "text": "#FFFFFF", "dim": "#C8D4EE", "accent": "#5CE1E6", "accent2": "#A78BFA"},
    "minimal": {"panel": "",        "border": "",        "text": "#FFFFFF", "dim": "#CBD5E1", "accent": "#94A3B8", "accent2": "#CBD5E1"},
    "neon":    {"panel": "#140924", "border": "#FF2DA0", "text": "#FBF7FF", "dim": "#D5B8F0", "accent": "#FF2DA0", "accent2": "#00F5D4"},
    "spotify": {"panel": "#121212", "border": "#282828", "text": "#FFFFFF", "dim": "#B3B3B3", "accent": "#1ED760", "accent2": "#1ED760"},
    "light":   {"panel": "#FFFFFF", "border": "#DCE3EE", "text": "#111827", "dim": "#64748B", "accent": "#2563EB", "accent2": "#60A5FA"},
    "bar":     {"panel": "#12151E", "border": "#2A3142", "text": "#F4F6FA", "dim": "#9BA4B8", "accent": "#FF9F19", "accent2": "#FFD08A"},
    "center":  {"panel": "#131722", "border": "#2D3448", "text": "#F4F6FA", "dim": "#9BA4B8", "accent": "#FF9F19", "accent2": "#FFD08A"},
}


def get_palette(mode: str) -> Dict[str, str]:
    return LIGHT_PALETTE if str(mode).lower() == "light" else DARK_PALETTE


# ---------------------------------------------------------------------------
# Easing & Color Interpolation Math
# ---------------------------------------------------------------------------

def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if value < lo else (hi if value > hi else value)


def ease_out_cubic(t: float) -> float:
    t = clamp(t)
    inv = 1.0 - t
    return 1.0 - inv * inv * inv


def ease_out_quart(t: float) -> float:
    t = clamp(t)
    inv = 1.0 - t
    return 1.0 - inv * inv * inv * inv


def ease_in_out_cubic(t: float) -> float:
    t = clamp(t)
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - pow(-2.0 * t + 2.0, 3) / 2.0


def hex_to_rgb(color: str) -> Tuple[int, int, int]:
    c = (color or "#000000").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return (0, 0, 0)
    try:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, int(r))):02X}{max(0, min(255, int(g))):02X}{max(0, min(255, int(b))):02X}"


def blend_hex(c1: str, c2: str, t: float) -> str:
    """Linearly interpolate between two #RRGGBB hex colors."""
    t = clamp(t)
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    return rgb_to_hex(
        round(r1 + (r2 - r1) * t),
        round(g1 + (g2 - g1) * t),
        round(b1 + (b2 - b1) * t),
    )


def dominant_accent_from_image(img: Image.Image) -> Tuple[int, int, int]:
    """Extract a vivid ambient glow color from an album cover image."""
    try:
        small = img.convert("RGB").resize((24, 24), Image.BILINEAR)
        get_px = getattr(small, "get_flattened_data", small.getdata)
        pixels = list(get_px())
        best = None
        best_score = -1.0
        avg_r = avg_g = avg_b = 0
        for r, g, b in pixels:
            avg_r += r
            avg_g += g
            avg_b += b
            mx = max(r, g, b)
            mn = min(r, g, b)
            sat = (mx - mn) / (mx + 1.0)
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            # Prefer saturated mid-bright colors for a classy ambient halo
            score = sat * (1.0 - abs(lum - 0.55)) * (mx / 255.0)
            if score > best_score:
                best_score = score
                best = (r, g, b)
        if best and best_score > 0.12:
            return best
        n = max(1, len(pixels))
        return (avg_r // n, avg_g // n, avg_b // n)
    except Exception:
        return (255, 154, 31)


# ---------------------------------------------------------------------------
# Native Windows 10/11 Titlebar Dark/Light Sync (DWM)
# ---------------------------------------------------------------------------

def apply_native_titlebar_theme(window, dark: bool) -> None:
    """Sync Windows 10/11 DWM titlebar dark mode with the app theme."""
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        val = ctypes.c_int(1 if dark else 0)
        dwmapi = ctypes.windll.dwmapi
        # Windows 11 / Win10 20H1+ uses attribute 20; older Win10 uses 19.
        res = dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
        if res != 0:
            dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Win32 Taskbar Visibility & Smooth Window Opacity Animator
# ---------------------------------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
GA_ROOT = 2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
WM_SETREDRAW = 0x000B
RDW_INVALIDATE = 0x0001
RDW_ERASE = 0x0004
RDW_ALLCHILDREN = 0x0080
RDW_UPDATENOW = 0x0100


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


def capture_widget_image(widget, client_only: bool = False) -> Optional[Image.Image]:
    """Capture a top-level Tk window's Win32 HWND into an offscreen PIL RGB Image."""
    try:
        hwnd_val = _get_win_hwnd(widget) if not client_only else int(widget.winfo_id())
        if not hwnd_val:
            return None
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hwnd = ctypes.c_void_p(hwnd_val)

        rect = wt.RECT()
        if client_only:
            if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return None
        else:
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < 10 or h < 10:
            return None

        hwnd_dc = user32.GetDC(hwnd) if client_only else user32.GetWindowDC(hwnd)
        if not hwnd_dc:
            return None
        mfc_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
        old = gdi32.SelectObject(mfc_dc, bmp)
        try:
            # PW_RENDERFULLCONTENT = 2; PW_CLIENTONLY = 1
            flags = 3 if client_only else 2
            ok = user32.PrintWindow(hwnd, mfc_dc, flags)
            if not ok:
                ok = user32.PrintWindow(hwnd, mfc_dc, 1 if client_only else 0)
            if not ok:
                return None

            bmi = _BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            bmi.biWidth = w
            bmi.biHeight = -h
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0  # BI_RGB
            buf = ctypes.create_string_buffer(w * h * 4)
            lines = gdi32.GetDIBits(mfc_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
            if not lines:
                return None
            return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
        finally:
            gdi32.SelectObject(mfc_dc, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mfc_dc)
            user32.ReleaseDC(hwnd, hwnd_dc)
    except Exception:
        return None


def capture_region_image(top_window, widget) -> Optional[Image.Image]:
    """Capture ``top_window`` via DWM PrintWindow and crop exact physical bounds of ``widget``."""
    try:
        user32 = ctypes.windll.user32
        top_hwnd = _get_win_hwnd(top_window)
        sub_hwnd = int(widget.winfo_id())
        if not top_hwnd or not sub_hwnd:
            return None
        top_rect = wt.RECT()
        sub_rect = wt.RECT()
        if not user32.GetWindowRect(ctypes.c_void_p(top_hwnd), ctypes.byref(top_rect)):
            return None
        if not user32.GetWindowRect(ctypes.c_void_p(sub_hwnd), ctypes.byref(sub_rect)):
            return None
        full = capture_widget_image(top_window, client_only=False)
        if full is None:
            return None
        x1 = max(0, sub_rect.left - top_rect.left)
        y1 = max(0, sub_rect.top - top_rect.top)
        x2 = min(full.width, sub_rect.right - top_rect.left)
        y2 = min(full.height, sub_rect.bottom - top_rect.top)
        if x2 - x1 < 10 or y2 - y1 < 10:
            return None
        return full.crop((x1, y1, x2, y2))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Ultra-Fast Native Win32 GDI Surface & AlphaBlend Compositor (<1ms/frame!)
# ---------------------------------------------------------------------------

SRCCOPY = 0x00CC0020
PS_SOLID = 0
NULL_BRUSH = 5


class _GdiApi:
    """Isolated WinDLL handles with strict 64-bit-safe signatures (no ctypes conflict)."""

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=False)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=False)
        self.msimg32 = ctypes.WinDLL("msimg32", use_last_error=False)
        self.winmm = ctypes.WinDLL("winmm", use_last_error=False)

        vp = ctypes.c_void_p
        ci = ctypes.c_int

        self.user32.GetWindowRect.argtypes = [vp, ctypes.POINTER(wt.RECT)]
        self.user32.GetWindowRect.restype = wt.BOOL
        self.user32.GetWindowDC.argtypes = [vp]
        self.user32.GetWindowDC.restype = vp
        self.user32.GetDC.argtypes = [vp]
        self.user32.GetDC.restype = vp
        self.user32.ReleaseDC.argtypes = [vp, vp]
        self.user32.ReleaseDC.restype = ci
        self.user32.PrintWindow.argtypes = [vp, vp, ctypes.c_uint]
        self.user32.PrintWindow.restype = wt.BOOL
        self.user32.FillRect.argtypes = [vp, ctypes.POINTER(wt.RECT), vp]
        self.user32.FillRect.restype = ci

        self.gdi32.CreateCompatibleDC.argtypes = [vp]
        self.gdi32.CreateCompatibleDC.restype = vp
        self.gdi32.CreateCompatibleBitmap.argtypes = [vp, ci, ci]
        self.gdi32.CreateCompatibleBitmap.restype = vp
        self.gdi32.SelectObject.argtypes = [vp, vp]
        self.gdi32.SelectObject.restype = vp
        self.gdi32.DeleteObject.argtypes = [vp]
        self.gdi32.DeleteObject.restype = wt.BOOL
        self.gdi32.DeleteDC.argtypes = [vp]
        self.gdi32.DeleteDC.restype = wt.BOOL
        self.gdi32.BitBlt.argtypes = [vp, ci, ci, ci, ci, vp, ci, ci, wt.DWORD]
        self.gdi32.BitBlt.restype = wt.BOOL
        self.gdi32.CreateSolidBrush.argtypes = [wt.DWORD]
        self.gdi32.CreateSolidBrush.restype = vp
        self.gdi32.CreatePen.argtypes = [ci, ci, wt.DWORD]
        self.gdi32.CreatePen.restype = vp
        self.gdi32.GetStockObject.argtypes = [ci]
        self.gdi32.GetStockObject.restype = vp
        self.gdi32.CreateEllipticRgn.argtypes = [ci, ci, ci, ci]
        self.gdi32.CreateEllipticRgn.restype = vp
        self.gdi32.SelectClipRgn.argtypes = [vp, vp]
        self.gdi32.SelectClipRgn.restype = ci
        self.gdi32.Ellipse.argtypes = [vp, ci, ci, ci, ci]
        self.gdi32.Ellipse.restype = wt.BOOL

        self.msimg32.AlphaBlend.argtypes = [
            vp, ci, ci, ci, ci, vp, ci, ci, ci, ci, ctypes.c_uint32,
        ]
        self.msimg32.AlphaBlend.restype = wt.BOOL

        self.winmm.timeBeginPeriod.argtypes = [ctypes.c_uint]
        self.winmm.timeBeginPeriod.restype = ctypes.c_uint
        self.winmm.timeEndPeriod.argtypes = [ctypes.c_uint]
        self.winmm.timeEndPeriod.restype = ctypes.c_uint


_GDI: Optional[_GdiApi] = None


def gdi_api() -> _GdiApi:
    global _GDI
    if _GDI is None:
        _GDI = _GdiApi()
    return _GDI


def hex_to_colorref(color: str) -> int:
    """Convert #RRGGBB to Win32 COLORREF (0x00BBGGRR)."""
    r, g, b = hex_to_rgb(color)
    return (b << 16) | (g << 8) | r


class GdiSurface:
    """Owned Win32 memory DC + HBITMAP surface for sub-millisecond GDI compositing."""

    def __init__(self, hdc, hbmp, old_bmp, width: int, height: int) -> None:
        self.hdc = hdc
        self.hbmp = hbmp
        self._old_bmp = old_bmp
        self.width = width
        self.height = height

    @classmethod
    def create(cls, ref_hdc, width: int, height: int) -> Optional["GdiSurface"]:
        api = gdi_api()
        hdc = api.gdi32.CreateCompatibleDC(ref_hdc)
        if not hdc:
            return None
        hbmp = api.gdi32.CreateCompatibleBitmap(ref_hdc, width, height)
        if not hbmp:
            api.gdi32.DeleteDC(hdc)
            return None
        old = api.gdi32.SelectObject(hdc, hbmp)
        return cls(hdc, hbmp, old, width, height)

    def fill_hex(self, color: str) -> None:
        api = gdi_api()
        brush = api.gdi32.CreateSolidBrush(hex_to_colorref(color))
        if brush:
            rc = wt.RECT(0, 0, self.width, self.height)
            api.user32.FillRect(self.hdc, ctypes.byref(rc), brush)
            api.gdi32.DeleteObject(brush)

    def release(self) -> None:
        if not self.hdc:
            return
        api = gdi_api()
        if self._old_bmp:
            api.gdi32.SelectObject(self.hdc, self._old_bmp)
            self._old_bmp = None
        if self.hbmp:
            api.gdi32.DeleteObject(self.hbmp)
            self.hbmp = None
        api.gdi32.DeleteDC(self.hdc)
        self.hdc = None


def capture_region_surface(top_window, widget) -> Optional[GdiSurface]:
    """Capture ``widget`` directly into a Win32 GdiSurface (~2-3ms, zero PIL overhead)."""
    try:
        api = gdi_api()
        top_hwnd = _get_win_hwnd(top_window)
        sub_hwnd = int(widget.winfo_id())
        if not top_hwnd or not sub_hwnd:
            return None
        top_rect = wt.RECT()
        sub_rect = wt.RECT()
        if not api.user32.GetWindowRect(top_hwnd, ctypes.byref(top_rect)):
            return None
        if not api.user32.GetWindowRect(sub_hwnd, ctypes.byref(sub_rect)):
            return None

        fw = top_rect.right - top_rect.left
        fh = top_rect.bottom - top_rect.top
        x1 = max(0, sub_rect.left - top_rect.left)
        y1 = max(0, sub_rect.top - top_rect.top)
        sw = min(fw - x1, sub_rect.right - sub_rect.left)
        sh = min(fh - y1, sub_rect.bottom - sub_rect.top)
        if fw < 10 or fh < 10 or sw < 10 or sh < 10:
            return None

        win_dc = api.user32.GetWindowDC(top_hwnd)
        if not win_dc:
            return None
        full = None
        cropped = None
        try:
            full = GdiSurface.create(win_dc, fw, fh)
            if full is None:
                return None
            ok = api.user32.PrintWindow(top_hwnd, full.hdc, 2)
            if not ok:
                ok = api.user32.PrintWindow(top_hwnd, full.hdc, 0)
            if not ok:
                return None
            cropped = GdiSurface.create(win_dc, sw, sh)
            if cropped is None:
                return None
            api.gdi32.BitBlt(cropped.hdc, 0, 0, sw, sh, full.hdc, x1, y1, SRCCOPY)
            result = cropped
            cropped = None
            return result
        finally:
            if full is not None:
                full.release()
            if cropped is not None:
                cropped.release()
            api.user32.ReleaseDC(top_hwnd, win_dc)
    except Exception:
        return None


def atomic_widget_swap(container, swap_fn) -> None:
    """Batch a multi-widget Z-order / layout switch into one atomic Win32 paint."""
    user32 = None
    hwnd_int = 0
    try:
        hwnd_int = int(container.winfo_id())
        user32 = ctypes.windll.user32
        # Pass plain int (aimp_api.py configures SendMessageW.argtypes with wt.HWND).
        user32.SendMessageW(hwnd_int, WM_SETREDRAW, 0, 0)
    except Exception:
        user32 = None
        hwnd_int = 0

    try:
        swap_fn()
        try:
            container.update_idletasks()
        except Exception:
            pass
    finally:
        if user32 is not None and hwnd_int:
            try:
                user32.SendMessageW(hwnd_int, WM_SETREDRAW, 1, 0)
                user32.RedrawWindow(
                    ctypes.c_void_p(hwnd_int), None, None,
                    RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW,
                )
            except Exception:
                pass


def compute_no_taskbar_exstyle(exstyle: int) -> int:
    """Return Win32 extended window style flags that keep a window off the taskbar."""
    return (int(exstyle) | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW


def _get_win_hwnd(window) -> int:
    """Resolve the true top-level Win32 HWND for a Tk window."""
    wid = int(window.winfo_id())
    try:
        user32 = ctypes.windll.user32
        root = user32.GetAncestor(wid, GA_ROOT)
        if root:
            return int(root)
        parent = user32.GetParent(wid)
        if parent:
            return int(parent)
    except Exception:
        pass
    return wid


def hide_window_from_taskbar(window) -> bool:
    """Apply WS_EX_TOOLWINDOW and clear WS_EX_APPWINDOW so the window never occupies the taskbar."""
    try:
        user32 = ctypes.windll.user32
        hwnd = _get_win_hwnd(window)
        if not hwnd:
            return False

        # Use 64-bit-safe GetWindowLongPtrW / SetWindowLongPtrW when available.
        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
        get_long.restype = ctypes.c_ssize_t
        set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        set_long.restype = ctypes.c_ssize_t

        old_style = int(get_long(hwnd, GWL_EXSTYLE))
        new_style = compute_no_taskbar_exstyle(old_style)
        if new_style != old_style:
            set_long(hwnd, GWL_EXSTYLE, new_style)
            user32.SetWindowPos(
                ctypes.c_void_p(hwnd),
                None,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
        return True
    except Exception:
        return False


def animate_window_alpha(
    window,
    start: float,
    end: float,
    duration_ms: int = 180,
    steps: int = 10,
    on_done=None,
) -> None:
    """Smoothly animate a Tk window's ``-alpha`` using wall-clock easing."""
    prev_job = getattr(window, "_alpha_anim_job", None)
    if prev_job is not None:
        try:
            window.after_cancel(prev_job)
        except Exception:
            pass
        setattr(window, "_alpha_anim_job", None)

    duration_s = max(0.02, duration_ms / 1000.0)
    delay = max(12, min(16, int(duration_ms // max(1, steps))))
    start = clamp(start)
    end = clamp(end)

    def _apply(val: float) -> bool:
        try:
            if not window.winfo_exists():
                return False
            window.attributes("-alpha", val)
            return True
        except Exception:
            return False

    if not _apply(start):
        return

    t0 = time.perf_counter()

    def _frame() -> None:
        setattr(window, "_alpha_anim_job", None)
        frac = clamp((time.perf_counter() - t0) / duration_s)
        val = start + (end - start) * ease_out_cubic(frac)
        if not _apply(val):
            return
        if frac < 1.0:
            job = window.after(delay, _frame)
            setattr(window, "_alpha_anim_job", job)
        elif on_done is not None:
            try:
                on_done()
            except Exception:
                pass

    job = window.after(delay, _frame)
    setattr(window, "_alpha_anim_job", job)


# ---------------------------------------------------------------------------
# Anti-aliased 2x Supersampled Vector Icons (Pillow)
# ---------------------------------------------------------------------------

def render_icon_image(name: str, color: str, size: int = 18) -> Image.Image:
    """Draw a clean geometric icon at 3x resolution and downsample with LANCZOS."""
    scale = 3
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgb = hex_to_rgb(color) + (255,)
    sw = max(2, round(1.8 * scale))
    m = round(3.0 * scale)  # margin
    cx = cy = s / 2.0

    if name == "play":
        d.polygon(
            [(s * 0.30, s * 0.18), (s * 0.82, cy), (s * 0.30, s * 0.82)],
            fill=rgb,
        )
    elif name == "pause":
        w = s * 0.18
        gap = s * 0.14
        r = max(2, round(1.5 * scale))
        d.rounded_rectangle([cx - gap / 2 - w, s * 0.20, cx - gap / 2, s * 0.80], radius=r, fill=rgb)
        d.rounded_rectangle([cx + gap / 2, s * 0.20, cx + gap / 2 + w, s * 0.80], radius=r, fill=rgb)
    elif name == "stop":
        r = max(2, round(1.5 * scale))
        d.rounded_rectangle([s * 0.25, s * 0.25, s * 0.75, s * 0.75], radius=r, fill=rgb)
    elif name == "prev":
        r = max(2, round(1.2 * scale))
        d.rounded_rectangle([s * 0.18, s * 0.22, s * 0.30, s * 0.78], radius=r, fill=rgb)
        d.polygon([(s * 0.80, s * 0.22), (s * 0.34, cy), (s * 0.80, s * 0.78)], fill=rgb)
    elif name == "next":
        r = max(2, round(1.2 * scale))
        d.polygon([(s * 0.20, s * 0.22), (s * 0.66, cy), (s * 0.20, s * 0.78)], fill=rgb)
        d.rounded_rectangle([s * 0.70, s * 0.22, s * 0.82, s * 0.78], radius=r, fill=rgb)
    elif name == "music":
        # Double eighth note
        d.line([(s * 0.38, s * 0.24), (s * 0.76, s * 0.17)], fill=rgb, width=max(2, round(2.2 * scale)))
        d.line([(s * 0.38, s * 0.24), (s * 0.38, s * 0.72)], fill=rgb, width=sw)
        d.line([(s * 0.76, s * 0.17), (s * 0.76, s * 0.64)], fill=rgb, width=sw)
        d.ellipse([s * 0.20, s * 0.62, s * 0.42, s * 0.82], fill=rgb)
        d.ellipse([s * 0.58, s * 0.54, s * 0.80, s * 0.74], fill=rgb)
    elif name == "palette":
        # Stylized layered cards / style icon
        r = max(3, round(2.2 * scale))
        d.rounded_rectangle([s * 0.14, s * 0.22, s * 0.72, s * 0.72], radius=r, outline=rgb, width=sw)
        d.rounded_rectangle([s * 0.30, s * 0.36, s * 0.86, s * 0.82], radius=r, outline=rgb, width=sw)
        d.ellipse([s * 0.44, s * 0.52, s * 0.60, s * 0.68], fill=rgb)
    elif name == "broadcast":
        # Signal / OBS broadcast icon
        d.ellipse([cx - s * 0.10, cy - s * 0.10, cx + s * 0.10, cy + s * 0.10], fill=rgb)
        for rad in (s * 0.25, s * 0.40):
            bbox = [cx - rad, cy - rad, cx + rad, cy + rad]
            d.arc(bbox, start=-45, end=45, fill=rgb, width=sw)
            d.arc(bbox, start=135, end=225, fill=rgb, width=sw)
    elif name == "phone":
        r = max(3, round(2.5 * scale))
        d.rounded_rectangle([s * 0.26, s * 0.12, s * 0.74, s * 0.88], radius=r, outline=rgb, width=sw)
        d.line([(s * 0.42, s * 0.77), (s * 0.58, s * 0.77)], fill=rgb, width=sw)
    elif name == "float":
        # Picture-in-picture / floating window icon
        r = max(3, round(2.0 * scale))
        d.rounded_rectangle([s * 0.14, s * 0.18, s * 0.86, s * 0.78], radius=r, outline=rgb, width=sw)
        d.rounded_rectangle([s * 0.48, s * 0.44, s * 0.78, s * 0.70], radius=max(2, round(1.4 * scale)), fill=rgb)
    elif name == "sparkles":
        # 4-point star (Demo mode)
        pts = [
            (cx, s * 0.12),
            (cx + s * 0.10, cy - s * 0.10),
            (s * 0.88, cy),
            (cx + s * 0.10, cy + s * 0.10),
            (cx, s * 0.88),
            (cx - s * 0.10, cy + s * 0.10),
            (s * 0.12, cy),
            (cx - s * 0.10, cy - s * 0.10),
        ]
        d.polygon(pts, fill=rgb)
    elif name == "copy":
        r = max(2, round(1.8 * scale))
        d.rounded_rectangle([s * 0.34, s * 0.30, s * 0.82, s * 0.84], radius=r, outline=rgb, width=sw)
        d.arc([s * 0.18, s * 0.16, s * 0.36, s * 0.34], 180, 270, fill=rgb, width=sw)
        d.line([(s * 0.27, s * 0.16), (s * 0.66, s * 0.16)], fill=rgb, width=sw)
        d.line([(s * 0.18, s * 0.25), (s * 0.18, s * 0.68)], fill=rgb, width=sw)
    elif name == "external":
        r = max(2, round(1.6 * scale))
        d.line([(s * 0.54, s * 0.20), (s * 0.82, s * 0.20), (s * 0.82, s * 0.48)], fill=rgb, width=sw)
        d.line([(s * 0.44, s * 0.56), (s * 0.80, s * 0.20)], fill=rgb, width=sw)
        d.line([(s * 0.42, s * 0.26), (s * 0.20, s * 0.26), (s * 0.20, s * 0.80), (s * 0.74, s * 0.80), (s * 0.74, s * 0.58)], fill=rgb, width=sw)
    elif name == "folder":
        r = max(2, round(1.8 * scale))
        d.polygon([
            (s * 0.14, s * 0.26), (s * 0.42, s * 0.26),
            (s * 0.50, s * 0.35), (s * 0.86, s * 0.35),
            (s * 0.86, s * 0.78), (s * 0.14, s * 0.78),
        ], outline=rgb, width=sw)
    elif name == "sun":
        d.ellipse([cx - s * 0.18, cy - s * 0.18, cx + s * 0.18, cy + s * 0.18], fill=rgb)
        for deg in range(0, 360, 45):
            ang = math.radians(deg)
            x1 = cx + math.cos(ang) * s * 0.27
            y1 = cy + math.sin(ang) * s * 0.27
            x2 = cx + math.cos(ang) * s * 0.40
            y2 = cy + math.sin(ang) * s * 0.40
            d.line([(x1, y1), (x2, y2)], fill=rgb, width=sw)
    elif name == "moon":
        d.ellipse([s * 0.18, s * 0.18, s * 0.82, s * 0.82], fill=rgb)
        d.ellipse([s * 0.36, s * 0.12, s * 0.92, s * 0.68], fill=(0, 0, 0, 0))
    elif name == "reset":
        d.arc([m, m, s - m, s - m], start=40, end=325, fill=rgb, width=sw)
        d.polygon([(s * 0.76, s * 0.16), (s * 0.88, s * 0.38), (s * 0.62, s * 0.36)], fill=rgb)
    elif name == "power":
        d.arc([s * 0.20, s * 0.22, s * 0.80, s * 0.82], start=-52, end=232, fill=rgb, width=sw)
        d.line([(cx, s * 0.14), (cx, s * 0.46)], fill=rgb, width=sw)
    elif name == "brand":
        # Sleek circular vinyl/wave emblem
        d.ellipse([s * 0.10, s * 0.10, s * 0.90, s * 0.90], outline=rgb, width=max(3, round(2.6 * scale)))
        d.polygon([(s * 0.42, s * 0.31), (s * 0.70, cy), (s * 0.42, s * 0.69)], fill=rgb)
    else:
        d.ellipse([m, m, s - m, s - m], fill=rgb)

    return img.resize((size, size), Image.LANCZOS)


class IconCache:
    """Caches CTkImage instances keyed by (name, dark_color, light_color, size)."""

    def __init__(self) -> None:
        self._cache: Dict[tuple, object] = {}

    def get(self, name: str, color_dark: str, color_light: str, size: int = 18):
        import customtkinter as ctk

        key = (name, color_dark, color_light, size)
        img = self._cache.get(key)
        if img is None:
            dark_im = render_icon_image(name, color_dark, size)
            light_im = render_icon_image(name, color_light, size)
            img = ctk.CTkImage(light_image=light_im, dark_image=dark_im, size=(size, size))
            self._cache[key] = img
        return img

    def solid(self, name: str, color: str, size: int = 18):
        return self.get(name, color, color, size)
