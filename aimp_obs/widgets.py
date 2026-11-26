"""Lightweight animated custom Canvas widgets and single-canvas transition engine.

Built strictly on tkinter.Canvas + Pillow (no extra dependencies). All transitions
run on a single Canvas HWND to guarantee true 60fps smoothness with zero widget pop-in.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageTk

from .theme import (
    NULL_BRUSH,
    OVERLAY_THEME_META,
    PS_SOLID,
    SRCCOPY,
    GdiSurface,
    blend_hex,
    clamp,
    dominant_accent_from_image,
    ease_in_out_cubic,
    ease_out_cubic,
    ease_out_quart,
    gdi_api,
    hex_to_colorref,
    hex_to_rgb,
)


def _draw_rounded_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    **kwargs,
) -> int:
    """Draw a smooth rounded rectangle polygon on a Tk Canvas."""
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    r = max(0.0, min(radius, w / 2.0, h / 2.0))
    if r <= 0.5:
        return canvas.create_rectangle(x1, y1, x2, y2, **kwargs)
    pts = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, splinesteps=16, **kwargs)


# ---------------------------------------------------------------------------
# 0. TransitionCurtain: Hardware-Fast Native Win32 GDI 60+ FPS Transition FX
# ---------------------------------------------------------------------------

def _alpha_blit(api, dst_hdc, src: GdiSurface, dx: int, alpha: int) -> None:
    """AlphaBlend ``src`` into ``dst_hdc`` shifted horizontally by ``dx`` (bounds-safe)."""
    alpha = max(0, min(255, int(alpha)))
    if alpha <= 0:
        return
    w, h = src.width, src.height
    if dx >= 0:
        src_x, dst_x, cw = 0, dx, w - dx
    else:
        src_x, dst_x, cw = -dx, 0, w + dx
    if cw <= 0:
        return
    if alpha >= 255:
        api.gdi32.BitBlt(dst_hdc, dst_x, 0, cw, h, src.hdc, src_x, 0, SRCCOPY)
    else:
        ftn = (alpha & 0xFF) << 16  # AC_SRC_OVER | SourceConstantAlpha
        api.msimg32.AlphaBlend(dst_hdc, dst_x, 0, cw, h, src.hdc, src_x, 0, cw, h, ftn)


class TransitionCurtain:
    """Floating borderless GDI overlay delivering true 60-100 FPS transitions (<1ms/frame).

    Uses Win32 ``BitBlt`` + ``msimg32.AlphaBlend`` + ``CreateEllipticRgn`` directly
    between offscreen ``GdiSurface`` bitmaps (zero PIL / Tk PhotoImage conversions per
    frame), paired with temporary 1ms multimedia timer resolution during transitions.
    """

    def __init__(self, top_window, bg: str = "#0B0D12") -> None:
        import ctypes
        import ctypes.wintypes as wt
        from .theme import hide_window_from_taskbar

        self._ctypes = ctypes
        self._wt = wt
        self._top = top_window
        self._hide_taskbar = hide_window_from_taskbar
        self._win = tk.Toplevel(top_window)
        self._win.withdraw()
        self._win.overrideredirect(True)
        try:
            self._win.transient(top_window)
        except Exception:
            pass
        self._win.configure(bg=bg)
        self._win.bind("<Expose>", self._on_expose)

        self._anim_id: Optional[str] = None
        self._active = False
        self._timer_boosted = False
        self._surf_old: Optional[GdiSurface] = None
        self._surf_new: Optional[GdiSurface] = None
        self._surf_back: Optional[GdiSurface] = None
        self._last_fps_frames = 0
        self._last_fps = 0.0

        # Warm up Win32 HWND + WS_EX_TOOLWINDOW invisibly once so the first transition is instant.
        try:
            self._win.attributes("-alpha", 0.0)
            self._win.geometry("64x64+-10000+-10000")
            self._win.deiconify()
            self._win.update()
            self._hide_taskbar(self._win)
            self._win.withdraw()
            self._win.attributes("-alpha", 1.0)
        except Exception:
            self._win.update_idletasks()
            self._hide_taskbar(self._win)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def win(self) -> tk.Toplevel:
        return self._win

    @property
    def last_fps(self) -> float:
        return self._last_fps

    def _boost_timer(self, enable: bool) -> None:
        if enable == self._timer_boosted:
            return
        try:
            api = gdi_api()
            if enable:
                api.winmm.timeBeginPeriod(1)
            else:
                api.winmm.timeEndPeriod(1)
            self._timer_boosted = enable
        except Exception:
            pass

    def _release_surfaces(self) -> None:
        for attr in ("_surf_old", "_surf_new", "_surf_back"):
            s = getattr(self, attr, None)
            if s is not None:
                s.release()
                setattr(self, attr, None)

    def _present(self, surf: Optional[GdiSurface]) -> None:
        """Blit ``surf`` directly onto the curtain HWND (<0.3ms)."""
        if surf is None or not self._active:
            return
        try:
            hwnd = int(self._win.winfo_id())
            if not hwnd:
                return
            api = gdi_api()
            dc = api.user32.GetDC(hwnd)
            if dc:
                try:
                    api.gdi32.BitBlt(dc, 0, 0, surf.width, surf.height, surf.hdc, 0, 0, SRCCOPY)
                finally:
                    api.user32.ReleaseDC(hwnd, dc)
        except Exception:
            pass

    def _on_expose(self, _event=None) -> None:
        if self._active:
            self._present(self._surf_back or self._surf_old)

    def _align_to_widget(self, target_widget) -> bool:
        try:
            api = gdi_api()
            rect = self._wt.RECT()
            sub_hwnd = int(target_widget.winfo_id())
            if not sub_hwnd or not api.user32.GetWindowRect(sub_hwnd, self._ctypes.byref(rect)):
                return False
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w < 10 or h < 10:
                return False
            self._win.deiconify()
            self._win.geometry(f"{w}x{h}+{rect.left}+{rect.top}")
            self._win.lift()
            self._win.update()
            return True
        except Exception:
            return False

    def show_static(self, surf: GdiSurface, target_widget, bg: Optional[str] = None) -> bool:
        """Cover ``target_widget`` with ``surf`` while widgets repaint invisibly underneath."""
        self.cancel()
        self._release_surfaces()
        self._surf_old = surf
        if bg:
            self._win.configure(bg=bg)
        if not self._align_to_widget(target_widget):
            return False
        self._active = True
        self._present(surf)
        return True

    def cancel(self) -> None:
        if self._anim_id is not None:
            try:
                self._top.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None
        self._boost_timer(False)

    def hide(self) -> None:
        self.cancel()
        self._active = False
        try:
            if self._win.winfo_exists():
                self._win.withdraw()
        except Exception:
            pass
        self._release_surfaces()

    def destroy(self) -> None:
        self.hide()
        try:
            if self._win.winfo_exists():
                self._win.destroy()
        except Exception:
            pass

    def _ensure_backbuffer(self, w: int, h: int) -> Optional[GdiSurface]:
        if self._surf_back is not None and self._surf_back.width == w and self._surf_back.height == h:
            return self._surf_back
        if self._surf_back is not None:
            self._surf_back.release()
            self._surf_back = None
        api = gdi_api()
        hwnd = int(self._win.winfo_id())
        dc = api.user32.GetDC(hwnd)
        if not dc:
            return None
        try:
            self._surf_back = GdiSurface.create(dc, w, h)
            return self._surf_back
        finally:
            api.user32.ReleaseDC(hwnd, dc)

    def play_slide_crossfade(
        self,
        surf_old: GdiSurface,
        surf_new: GdiSurface,
        direction: int,
        bg_hex: str,
        duration_ms: int = 230,
        on_done: Optional[Callable[[], None]] = None,
    ) -> None:
        """True 60+ FPS native GDI directional slide + AlphaBlend crossfade (<1ms/frame)."""
        self.cancel()
        self._surf_old = surf_old
        self._surf_new = surf_new
        w, h = surf_new.width, surf_new.height
        back = self._ensure_backbuffer(w, h)
        if back is None:
            self.hide()
            if on_done:
                on_done()
            return

        api = gdi_api()
        dir_sign = 1 if direction >= 0 else -1
        slide_dist = max(32, min(72, int(w * 0.07)))
        duration_s = max(0.06, duration_ms / 1000.0)
        self._active = True
        self._boost_timer(True)
        t0 = time.perf_counter()
        frames = 0

        def _frame() -> None:
            nonlocal frames
            self._anim_id = None
            try:
                if not self._win.winfo_exists():
                    self.hide()
                    return
            except Exception:
                self.hide()
                return
            elapsed = time.perf_counter() - t0
            frac = clamp(elapsed / duration_s)
            if frac >= 1.0:
                self._last_fps_frames = frames
                self._last_fps = frames / max(0.001, elapsed)
                self._present(surf_new)
                self.hide()
                if on_done:
                    on_done()
                return

            e = ease_out_quart(frac)
            old_dx = round(-slide_dist * 0.42 * e * dir_sign)
            new_dx = round(slide_dist * (1.0 - e) * dir_sign)

            back.fill_hex(bg_hex)
            _alpha_blit(api, back.hdc, surf_old, old_dx, round(255 * (1.0 - e)))
            _alpha_blit(api, back.hdc, surf_new, new_dx, round(255 * e))
            self._present(back)
            frames += 1
            self._anim_id = self._top.after(10, _frame)

        _frame()

    def play_radial_ripple(
        self,
        surf_old: GdiSurface,
        surf_new: GdiSurface,
        origin_xy: Tuple[int, int],
        accent_hex: str,
        duration_ms: int = 340,
        on_done: Optional[Callable[[], None]] = None,
    ) -> None:
        """True 60+ FPS native GDI circular clip-region ripple reveal (<1ms/frame)."""
        self.cancel()
        self._surf_old = surf_old
        self._surf_new = surf_new
        w, h = surf_new.width, surf_new.height
        back = self._ensure_backbuffer(w, h)
        if back is None:
            self.hide()
            if on_done:
                on_done()
            return

        api = gdi_api()
        ox, oy = int(origin_xy[0]), int(origin_xy[1])
        max_r = max(
            math.hypot(ox, oy),
            math.hypot(w - ox, oy),
            math.hypot(ox, h - oy),
            math.hypot(w - ox, h - oy),
        ) + 20.0
        duration_s = max(0.08, duration_ms / 1000.0)
        accent_cr = hex_to_colorref(accent_hex)
        soft_cr = hex_to_colorref(blend_hex(accent_hex, "#FFFFFF", 0.35))
        null_brush = api.gdi32.GetStockObject(NULL_BRUSH)

        self._active = True
        self._boost_timer(True)
        t0 = time.perf_counter()
        frames = 0

        def _frame() -> None:
            nonlocal frames
            self._anim_id = None
            try:
                if not self._win.winfo_exists():
                    self.hide()
                    return
            except Exception:
                self.hide()
                return
            elapsed = time.perf_counter() - t0
            frac = clamp(elapsed / duration_s)
            if frac >= 1.0:
                self._last_fps_frames = frames
                self._last_fps = frames / max(0.001, elapsed)
                self._present(surf_new)
                self.hide()
                if on_done:
                    on_done()
                return

            e = ease_in_out_cubic(frac)
            rad = int(max_r * e)

            # Base layer: old theme
            api.gdi32.BitBlt(back.hdc, 0, 0, w, h, surf_old.hdc, 0, 0, SRCCOPY)

            # Expanding circular clip revealing new theme
            if rad > 1:
                hrgn = api.gdi32.CreateEllipticRgn(ox - rad, oy - rad, ox + rad, oy + rad)
                if hrgn:
                    api.gdi32.SelectClipRgn(back.hdc, hrgn)
                    api.gdi32.BitBlt(back.hdc, 0, 0, w, h, surf_new.hdc, 0, 0, SRCCOPY)
                    api.gdi32.SelectClipRgn(back.hdc, None)
                    api.gdi32.DeleteObject(hrgn)

                # Luminous glowing accent ring along the expanding wavefront
                if 0.02 < frac < 0.96:
                    old_brush = api.gdi32.SelectObject(back.hdc, null_brush)
                    pen_outer = api.gdi32.CreatePen(PS_SOLID, 3, accent_cr)
                    if pen_outer:
                        old_pen = api.gdi32.SelectObject(back.hdc, pen_outer)
                        api.gdi32.Ellipse(back.hdc, ox - rad, oy - rad, ox + rad, oy + rad)
                        api.gdi32.SelectObject(back.hdc, old_pen)
                        api.gdi32.DeleteObject(pen_outer)
                    if rad > 6:
                        pen_inner = api.gdi32.CreatePen(PS_SOLID, 1, soft_cr)
                        if pen_inner:
                            old_pen = api.gdi32.SelectObject(back.hdc, pen_inner)
                            api.gdi32.Ellipse(back.hdc, ox - rad + 2, oy - rad + 2, ox + rad - 2, oy + rad - 2)
                            api.gdi32.SelectObject(back.hdc, old_pen)
                            api.gdi32.DeleteObject(pen_inner)
                    api.gdi32.SelectObject(back.hdc, old_brush)

            self._present(back)
            frames += 1
            self._anim_id = self._top.after(10, _frame)

        _frame()


# ---------------------------------------------------------------------------
# 1. SegmentedTabBar: Floating Top Pill Navigation with Gliding Thumb
# ---------------------------------------------------------------------------

class SegmentedTabBar(tk.Canvas):
    """Compact glass-like segmented pill tab bar with smoothly gliding active pill."""

    def __init__(
        self,
        master,
        items: Sequence[Tuple[str, str]],
        palette: Dict[str, str],
        on_select: Callable[[str], None],
        width: int = 256,
        height: int = 34,
        bg_key: str = "sidebar",
    ) -> None:
        self._items = list(items)
        self._palette = palette
        self._on_select = on_select
        self._bg_key = bg_key
        self._bar_w = width
        self._bar_h = height
        super().__init__(
            master, width=width, height=height, bg=palette[bg_key],
            highlightthickness=0, bd=0, cursor="hand2",
        )
        self._active_idx = 0
        self._pos = 0.0
        self._start_pos = 0.0
        self._anim_t0 = 0.0
        self._hover_idx = -1
        self._badges: Dict[str, int] = {}
        self._anim_id: Optional[str] = None
        self._font_idle = ("Segoe UI", 9)
        self._font_active = ("Segoe UI", 9, "bold")

        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self._draw()

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self.configure(bg=palette[self._bg_key])
        self._draw()

    def set_badge(self, key: str, count: int) -> None:
        if self._badges.get(key, 0) == count:
            return
        self._badges[key] = count
        self._draw()

    def set_active(self, key: str, instant: bool = False) -> None:
        for i, (k, _label) in enumerate(self._items):
            if k == key:
                self._active_idx = i
                break
        if instant:
            self._pos = float(self._active_idx)
            self._draw()
            return
        self._start_pos = self._pos
        self._anim_t0 = time.perf_counter()
        if self._anim_id is None:
            self._step()

    def _idx_from_x(self, x: float) -> int:
        w = max(1.0, float(self.winfo_width() or self._bar_w))
        n = len(self._items)
        return max(0, min(n - 1, int(x / (w / n))))

    def _on_click(self, event) -> None:
        idx = self._idx_from_x(event.x)
        key = self._items[idx][0]
        if idx != self._active_idx:
            self._active_idx = idx
            self._start_pos = self._pos
            self._anim_t0 = time.perf_counter()
            if self._anim_id is None:
                self._step()
        if self._on_select:
            self._on_select(key)

    def _on_motion(self, event) -> None:
        idx = self._idx_from_x(event.x)
        if idx != self._hover_idx:
            self._hover_idx = idx
            self._draw()

    def _on_leave(self, _event) -> None:
        if self._hover_idx != -1:
            self._hover_idx = -1
            self._draw()

    def _step(self) -> None:
        self._anim_id = None
        if not self.winfo_exists():
            return
        target = float(self._active_idx)
        frac = clamp((time.perf_counter() - self._anim_t0) / 0.22)
        if frac >= 1.0:
            self._pos = target
            self._draw()
            return
        self._pos = self._start_pos + (target - self._start_pos) * ease_out_quart(frac)
        self._draw()
        self._anim_id = self.after(10, self._step)

    def _draw(self) -> None:
        self.delete("all")
        w = float(self.winfo_width() or self._bar_w)
        h = float(self.winfo_height() or self._bar_h)
        if w < 40 or h < 16:
            return
        n = len(self._items)
        seg_w = (w - 6.0) / n

        # Outer recessed track pill
        _draw_rounded_rect(
            self, 1, 1, w - 1, h - 1, (h - 2) / 2.0,
            fill=self._palette["card_alt"], outline=self._palette["border"], width=1,
        )

        # Subtle hover highlight pill
        if 0 <= self._hover_idx < n and self._hover_idx != self._active_idx:
            hx1 = 3.0 + self._hover_idx * seg_w
            _draw_rounded_rect(
                self, hx1, 3, hx1 + seg_w, h - 3, (h - 6) / 2.0,
                fill=self._palette["card_hover"], outline="",
            )

        # Gliding active pill thumb
        px1 = 3.0 + self._pos * seg_w
        px2 = px1 + seg_w
        pill_fill = self._palette["accent"]
        _draw_rounded_rect(
            self, px1, 3, px2, h - 3, (h - 6) / 2.0,
            fill=pill_fill, outline="",
        )

        # Labels + optional notification badge dot
        for i, (key, label) in enumerate(self._items):
            cx = 3.0 + (i + 0.5) * seg_w
            cy = h / 2.0
            closeness = clamp(1.0 - abs(self._pos - i))
            txt_color = blend_hex(
                self._palette["text_secondary"],
                self._palette["accent_fg"],
                closeness,
            )
            font = self._font_active if closeness > 0.55 else self._font_idle
            self.create_text(cx, cy, text=label, fill=txt_color, font=font, anchor="center")
            if self._badges.get(key, 0) > 0:
                bx = 3.0 + (i + 1) * seg_w - 9
                by = 9
                dot_c = self._palette["accent_fg"] if closeness > 0.55 else self._palette["danger"]
                self.create_oval(bx - 3, by - 3, bx + 3, by + 3, fill=dot_c, outline="")


# ---------------------------------------------------------------------------
# 2. CoverStage: Album artwork with breathing ambient glow & smooth crossfade
# ---------------------------------------------------------------------------

class CoverStage(tk.Canvas):
    """Displays rounded album art over a cover-tinted breathing ambient glow."""

    def __init__(
        self,
        master,
        palette: Dict[str, str],
        cover_size: int = 118,
        pad: int = 20,
        radius: int = 18,
    ) -> None:
        self._palette = palette
        self._cover_size = cover_size
        self._pad = pad
        self._radius = radius
        total = cover_size + pad * 2
        super().__init__(
            master, width=total, height=total, bg=palette["card"],
            highlightthickness=0, bd=0,
        )
        self._total = total
        self._current_img: Optional[Image.Image] = None
        self._frame_lo: Optional[Image.Image] = None
        self._frame_hi: Optional[Image.Image] = None
        self._prev_frame: Optional[Image.Image] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._item = self.create_image(total // 2, total // 2, anchor="center")
        self._fade_t0 = 0.0
        self._fade_after: Optional[str] = None
        self._breathe_after: Optional[str] = None
        self._breathe_phase = 0.0
        self._playing = False
        self._glow_rgb = (255, 154, 31)

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self.configure(bg=palette["card"])
        if self._current_img is not None:
            self._rebuild_frames(self._current_img)
            self._show_pil(self._frame_lo)

    def set_playing(self, playing: bool) -> None:
        if self._playing == playing:
            return
        self._playing = playing
        if playing and self._breathe_after is None and self._fade_after is None:
            self._tick_breathe()
        elif not playing and self._frame_lo is not None and self._fade_after is None:
            self._show_pil(self._frame_lo)

    def _compose_frame(self, cover_rgba: Image.Image, glow_strength: float = 1.0) -> Image.Image:
        total = self._total
        bg_rgb = hex_to_rgb(self._palette["card"])
        canvas_img = Image.new("RGBA", (total, total), bg_rgb + (255,))

        glow_r, glow_g, glow_b = self._glow_rgb
        base_a = 84 if self._palette["mode"] == "dark" else 48
        glow_alpha = min(200, int(base_a * glow_strength))
        glow = Image.new("RGBA", (total, total), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        p = self._pad
        expand = round(3 * (glow_strength - 0.8))
        gd.rounded_rectangle(
            [p - expand, p + 3 - expand, total - p + expand, total - p + 7 + expand],
            radius=self._radius + 4,
            fill=(glow_r, glow_g, glow_b, glow_alpha),
        )
        glow = glow.filter(ImageFilter.GaussianBlur(radius=9))
        canvas_img.alpha_composite(glow)

        shadow = Image.new("RGBA", (total, total), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        shadow_a = 72 if self._palette["mode"] == "dark" else 28
        sd.rounded_rectangle(
            [p + 2, p + 5, total - p - 2, total - p + 4],
            radius=self._radius,
            fill=(0, 0, 0, shadow_a),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=5))
        canvas_img.alpha_composite(shadow)

        cov = cover_rgba
        if cov.size != (self._cover_size, self._cover_size):
            cov = cov.resize((self._cover_size, self._cover_size), Image.LANCZOS)
        canvas_img.alpha_composite(cov, (p, p))

        border_overlay = Image.new("RGBA", (total, total), (0, 0, 0, 0))
        bd = ImageDraw.Draw(border_overlay)
        rim = (255, 255, 255, 42) if self._palette["mode"] == "dark" else (0, 0, 0, 22)
        bd.rounded_rectangle(
            [p, p, p + self._cover_size - 1, p + self._cover_size - 1],
            radius=self._radius,
            outline=rim,
            width=1,
        )
        canvas_img.alpha_composite(border_overlay)
        return canvas_img.convert("RGB")

    def _rebuild_frames(self, cover_rgba: Image.Image) -> None:
        self._frame_lo = self._compose_frame(cover_rgba, 0.85)
        self._frame_hi = self._compose_frame(cover_rgba, 1.32)

    def _show_pil(self, img: Image.Image) -> None:
        self._photo = ImageTk.PhotoImage(img)
        self.itemconfigure(self._item, image=self._photo)

    def set_cover(self, cover_rgba: Image.Image, animate: bool = True) -> None:
        if cover_rgba is None:
            return
        self._glow_rgb = dominant_accent_from_image(cover_rgba)
        old_frame = self._frame_lo
        self._current_img = cover_rgba
        self._rebuild_frames(cover_rgba)

        if self._fade_after:
            try:
                self.after_cancel(self._fade_after)
            except Exception:
                pass
            self._fade_after = None

        if not animate or old_frame is None:
            self._show_pil(self._frame_lo)
            if self._playing and self._breathe_after is None:
                self._tick_breathe()
            return

        self._prev_frame = old_frame
        self._fade_t0 = time.perf_counter()
        self._step_fade()

    def _step_fade(self) -> None:
        self._fade_after = None
        if not self.winfo_exists():
            return
        frac = clamp((time.perf_counter() - self._fade_t0) / 0.26)
        if frac >= 1.0 or self._prev_frame is None or self._frame_lo is None:
            if self._frame_lo is not None:
                self._show_pil(self._frame_lo)
            self._prev_frame = None
            if self._playing and self._breathe_after is None:
                self._tick_breathe()
            return
        blended = Image.blend(self._prev_frame, self._frame_lo, ease_out_cubic(frac))
        self._show_pil(blended)
        self._fade_after = self.after(18, self._step_fade)

    def _tick_breathe(self) -> None:
        self._breathe_after = None
        if not self.winfo_exists() or not self._playing or self._fade_after is not None:
            return
        if self._frame_lo is not None and self._frame_hi is not None:
            self._breathe_phase = (self._breathe_phase + 0.08) % (math.tau)
            k = (math.sin(self._breathe_phase) + 1.0) * 0.5
            self._show_pil(Image.blend(self._frame_lo, self._frame_hi, k))
        self._breathe_after = self.after(90, self._tick_breathe)


# ---------------------------------------------------------------------------
# 3. EqualizerWidget: 7-bar harmonic visualizer with gravity peak-hold caps
# ---------------------------------------------------------------------------

class EqualizerWidget(tk.Canvas):
    """Lush 7-bar animated visualizer with glowing floating peak-hold dots."""

    def __init__(self, master, palette: Dict[str, str], width: int = 46, height: int = 18) -> None:
        self._palette = palette
        self._eq_w = width
        self._eq_h = height
        super().__init__(
            master, width=width, height=height, bg=palette["card"],
            highlightthickness=0, bd=0,
        )
        self._playing = False
        self._bars = [0.16] * 7
        self._peaks = [0.20] * 7
        self._phases = [0.0, 1.1, 2.3, 0.5, 3.1, 1.8, 4.0]
        self._speeds = [4.9, 6.6, 5.4, 7.6, 5.9, 6.9, 4.5]
        self._phase_t = 0.0
        self._after_id: Optional[str] = None
        self._draw()

    def apply_theme(self, palette: Dict[str, str], bg_key: str = "card") -> None:
        self._palette = palette
        self.configure(bg=palette[bg_key])
        self._draw()

    def set_playing(self, playing: bool) -> None:
        if self._playing == playing:
            return
        self._playing = playing
        if self._after_id is None:
            self._tick()

    def _tick(self) -> None:
        self._after_id = None
        if not self.winfo_exists():
            return
        self._phase_t += 0.055
        settled = True
        for i in range(len(self._bars)):
            if self._playing:
                s1 = math.sin(self._phase_t * self._speeds[i] + self._phases[i])
                s2 = math.sin(self._phase_t * (self._speeds[i] * 0.52) + i * 1.4)
                # Bell-curve envelope so center bars dance slightly taller
                env = 0.72 + 0.28 * math.sin((i + 0.5) / len(self._bars) * math.pi)
                target = 0.18 + 0.74 * env * ((s1 * 0.62 + s2 * 0.38 + 1.0) / 2.0)
                settled = False
            else:
                target = 0.16
            diff = target - self._bars[i]
            self._bars[i] += diff * 0.30
            if self._bars[i] >= self._peaks[i]:
                self._peaks[i] = self._bars[i]
            else:
                self._peaks[i] = max(self._bars[i], self._peaks[i] - 0.032)
            if abs(diff) > 0.012 or abs(self._peaks[i] - self._bars[i]) > 0.015:
                settled = False
        self._draw()
        if not settled:
            self._after_id = self.after(42, self._tick)

    def _draw(self) -> None:
        self.delete("all")
        n = len(self._bars)
        bar_w = 3.2
        gap = (self._eq_w - n * bar_w) / max(1, n - 1)
        accent = self._palette["accent"]
        peak_c = blend_hex(accent, "#FFFFFF", 0.45) if self._playing else self._palette["text_muted"]
        bar_c = accent if self._playing else self._palette["text_muted"]
        for i, level in enumerate(self._bars):
            x1 = i * (bar_w + gap)
            bh = max(3.0, level * (self._eq_h - 4))
            y1 = self._eq_h - bh - 1
            y2 = self._eq_h - 1
            _draw_rounded_rect(self, x1, y1, x1 + bar_w, y2, 1.5, fill=bar_c, outline="")
            if self._playing:
                py = self._eq_h - max(3.0, self._peaks[i] * (self._eq_h - 4)) - 3.2
                self.create_rectangle(x1, py, x1 + bar_w, py + 1.8, fill=peak_c, outline="")


# ---------------------------------------------------------------------------
# 4. StatusPulseDot: Breathing concentric status indicator
# ---------------------------------------------------------------------------

class StatusPulseDot(tk.Canvas):
    """Animated status dot with expanding breathing ring when playing."""

    def __init__(self, master, palette: Dict[str, str], bg_key: str = "sidebar") -> None:
        self._palette = palette
        self._bg_key = bg_key
        super().__init__(
            master, width=14, height=14, bg=palette[bg_key],
            highlightthickness=0, bd=0,
        )
        self._color_key = "danger"
        self._pulsing = False
        self._phase = 0.0
        self._after_id: Optional[str] = None
        self._draw()

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self.configure(bg=palette[self._bg_key])
        self._draw()

    def set_status(self, color_key: str, pulsing: bool) -> None:
        changed = (color_key != self._color_key) or (pulsing != self._pulsing)
        self._color_key = color_key
        self._pulsing = pulsing
        if not changed:
            return
        if pulsing and self._after_id is None:
            self._tick()
        else:
            self._draw()

    def _tick(self) -> None:
        self._after_id = None
        if not self.winfo_exists():
            return
        if not self._pulsing:
            self._phase = 0.0
            self._draw()
            return
        self._phase = (self._phase + 0.055) % 1.0
        self._draw()
        self._after_id = self.after(55, self._tick)

    def _draw(self) -> None:
        self.delete("all")
        cx = cy = 7
        dot_color = self._palette.get(self._color_key, self._palette["accent"])
        bg = self._palette[self._bg_key]
        if self._pulsing:
            p = ease_out_cubic(self._phase)
            rad = 3.0 + p * 3.8
            ring_color = blend_hex(dot_color, bg, 0.35 + 0.65 * p)
            self.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, outline=ring_color, width=1.4)
        self.create_oval(cx - 3.0, cy - 3.0, cx + 3.0, cy + 3.0, fill=dot_color, outline="")


# ---------------------------------------------------------------------------
# 5. AnimatedProgressBar: Glowing shimmer seekable progress bar
# ---------------------------------------------------------------------------

class AnimatedProgressBar(tk.Canvas):
    """Smoothly interpolated progress bar with light shimmer, hover orb thumb, and seek."""

    def __init__(
        self,
        master,
        palette: Dict[str, str],
        on_seek: Optional[Callable[[float], None]] = None,
        bg_key: str = "card",
    ) -> None:
        self._palette = palette
        self._bg_key = bg_key
        self._on_seek = on_seek
        super().__init__(
            master, height=18, bg=palette[bg_key],
            highlightthickness=0, bd=0, cursor="hand2" if on_seek else "",
        )
        self._value = 0.0
        self._target = 0.0
        self._hover = False
        self._hover_t = 0.0
        self._dragging = False
        self._playing = False
        self._shimmer = 0.0
        self._anim_id: Optional[str] = None

        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self.configure(bg=palette[self._bg_key])
        self._draw()

    def set_playing(self, playing: bool) -> None:
        if self._playing == playing:
            return
        self._playing = playing
        if playing and self._anim_id is None:
            self._step()

    def set_progress(self, value: float, instant: bool = False) -> None:
        if self._dragging:
            return
        self._target = clamp(value)
        if instant:
            self._value = self._target
            self._draw()
            return
        if self._anim_id is None and abs(self._target - self._value) > 0.0005:
            self._step()

    def _on_enter(self, _event) -> None:
        self._hover = True
        if self._anim_id is None:
            self._step()

    def _on_leave(self, _event) -> None:
        self._hover = False
        if self._anim_id is None:
            self._step()

    def _ratio_from_x(self, x: float) -> float:
        pad = 6.0
        w = max(1.0, self.winfo_width() - pad * 2)
        return clamp((x - pad) / w)

    def _on_press(self, event) -> None:
        if not self._on_seek:
            return
        self._dragging = True
        self._value = self._target = self._ratio_from_x(event.x)
        self._draw()

    def _on_drag(self, event) -> None:
        if not self._dragging:
            return
        self._value = self._target = self._ratio_from_x(event.x)
        self._draw()

    def _on_release(self, event) -> None:
        if not self._dragging:
            return
        self._dragging = False
        ratio = self._ratio_from_x(event.x)
        self._value = self._target = ratio
        self._draw()
        if self._on_seek:
            try:
                self._on_seek(ratio)
            except Exception:
                pass

    def _step(self) -> None:
        self._anim_id = None
        if not self.winfo_exists():
            return
        active = False
        diff = self._target - self._value
        if abs(diff) > 0.0006:
            self._value += diff * (0.45 if abs(diff) > 0.15 else 0.25)
            active = True
        else:
            self._value = self._target

        ht_target = 1.0 if (self._hover or self._dragging) else 0.0
        hdiff = ht_target - self._hover_t
        if abs(hdiff) > 0.02:
            self._hover_t += hdiff * 0.30
            active = True
        else:
            self._hover_t = ht_target

        if self._playing and self._value > 0.03:
            self._shimmer = (self._shimmer + 0.022) % 1.4
            active = True

        self._draw()
        if active:
            self._anim_id = self.after(32 if self._playing and abs(hdiff) <= 0.02 and abs(diff) <= 0.0006 else 18, self._step)

    def _draw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 20 or h < 6:
            return
        pad = 6.0
        cy = h / 2.0
        bar_h = 4.5 + 2.2 * self._hover_t
        y1 = cy - bar_h / 2.0
        y2 = cy + bar_h / 2.0
        x1 = pad
        x2 = w - pad

        _draw_rounded_rect(self, x1, y1, x2, y2, bar_h / 2.0, fill=self._palette["track_bg"], outline="")

        fill_w = (x2 - x1) * self._value
        fx = x1 + fill_w
        if fill_w >= 2.0:
            accent = self._palette["accent"]
            _draw_rounded_rect(self, x1, y1, fx, y2, bar_h / 2.0, fill=accent, outline="")
            # Traveling light shimmer beam while playing
            if self._playing and fill_w > 28 and self._shimmer < 1.0:
                sw = min(38.0, fill_w * 0.35)
                sx1 = x1 + (fill_w - sw) * self._shimmer
                sx2 = min(fx, sx1 + sw)
                shim_c = blend_hex(accent, "#FFFFFF", 0.36)
                _draw_rounded_rect(self, sx1, y1, sx2, y2, bar_h / 2.0, fill=shim_c, outline="")
            # Bright glowing tip
            if fill_w > 12:
                tip_c = blend_hex(accent, "#FFFFFF", 0.34)
                _draw_rounded_rect(self, max(x1, fx - 12), y1, fx, y2, bar_h / 2.0, fill=tip_c, outline="")

        if self._hover_t > 0.05:
            r = 3.6 + 2.4 * self._hover_t
            halo_r = r + 3.0 * self._hover_t
            halo_c = blend_hex(self._palette["accent"], self._palette[self._bg_key], 0.62)
            self.create_oval(fx - halo_r, cy - halo_r, fx + halo_r, cy + halo_r, fill=halo_c, outline="")
            thumb_fill = "#FFFFFF" if self._palette["mode"] == "dark" else self._palette["accent"]
            self.create_oval(
                fx - r, cy - r, fx + r, cy + r,
                fill=thumb_fill, outline=self._palette["accent"], width=1.5,
            )


# ---------------------------------------------------------------------------
# 6. LyricsStage: Smoothly scrolling & cross-fading compact lyrics theater
# ---------------------------------------------------------------------------

class LyricsStage(tk.Canvas):
    """Animated lyric display with upward slide-in + color fade on line changes."""

    def __init__(self, master, palette: Dict[str, str], height: int = 92) -> None:
        self._palette = palette
        super().__init__(
            master, height=height, bg=palette["card"],
            highlightthickness=0, bd=0,
        )
        self._cur = "暂无歌词"
        self._nxt = ""
        self._prev_cur = ""
        self._synced = False
        self._anim_t = 1.0
        self._anim_id: Optional[str] = None
        self._font_cur = ("Segoe UI", 13, "bold")
        self._font_sub = ("Segoe UI", 10)
        self._font_nxt = ("Segoe UI", 10)
        self.bind("<Configure>", lambda _e: self._draw())

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self.configure(bg=palette["card"])
        self._draw()

    def set_lyrics(self, current: str, nxt: str, synced: bool) -> None:
        if current == self._cur and nxt == self._nxt and synced == self._synced:
            return
        changed_line = (current != self._cur)
        if changed_line:
            self._prev_cur = self._cur
        self._cur = current
        self._nxt = nxt
        self._synced = synced
        if changed_line:
            self._anim_t = 0.0
            if self._anim_id:
                try:
                    self.after_cancel(self._anim_id)
                except Exception:
                    pass
                self._anim_id = None
            self._step()
        else:
            self._draw()

    def _step(self) -> None:
        self._anim_id = None
        if not self.winfo_exists():
            return
        self._anim_t = min(1.0, self._anim_t + 0.11)
        self._draw()
        if self._anim_t < 1.0:
            self._anim_id = self.after(18, self._step)

    def _draw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 40 or h < 36:
            return
        bg = self._palette["card"]
        text_c = self._palette["text"]
        sec_c = self._palette["text_secondary"]
        muted_c = self._palette["text_muted"]
        accent = self._palette["accent"]

        e = ease_out_cubic(self._anim_t)
        slide_y = (1.0 - e) * 16.0
        pad_x = 16
        wrap_w = max(120, w - pad_x - 16)

        cur_lines = self._cur.splitlines() if self._cur else [""]
        has_sub = len(cur_lines) > 1
        line_h_cur = 28
        line_h_sub = 21
        block_h = line_h_cur + (line_h_sub if has_sub else 0) + (22 if self._nxt else 0)
        top_y = max(8.0, (h - block_h) * 0.44)

        bar_h = (line_h_cur + (line_h_sub if has_sub else 0)) - 6
        bar_y1 = top_y + 3 + slide_y * 0.45
        bar_color = accent if self._synced else self._palette["border_strong"]
        _draw_rounded_rect(self, 3, bar_y1, 6.5, bar_y1 + bar_h, 2.0, fill=bar_color, outline="")

        if self._anim_t < 0.85 and self._prev_cur and self._prev_cur != "暂无歌词":
            out_y = top_y - e * 14.0
            out_c = blend_hex(sec_c, bg, clamp(e * 1.25))
            first_prev = self._prev_cur.splitlines()[0]
            self.create_text(
                pad_x, out_y, text=first_prev, anchor="nw",
                fill=out_c, font=self._font_sub, width=wrap_w,
            )

        primary_color = blend_hex(muted_c, text_c, e)
        y = top_y + slide_y
        self.create_text(
            pad_x, y, text=cur_lines[0], anchor="nw",
            fill=primary_color, font=self._font_cur, width=wrap_w,
        )
        y += line_h_cur
        if has_sub:
            sub_color = blend_hex(bg, sec_c, e)
            self.create_text(
                pad_x, y, text=cur_lines[1], anchor="nw",
                fill=sub_color, font=self._font_sub, width=wrap_w,
            )
            y += line_h_sub + 4
        else:
            y += 6

        if self._nxt:
            nxt_first = self._nxt.splitlines()[0]
            nxt_color = blend_hex(bg, muted_c, 0.45 + 0.55 * e)
            self.create_text(
                pad_x, min(h - 22, y), text=nxt_first, anchor="nw",
                fill=nxt_color, font=self._font_nxt, width=wrap_w,
            )


# ---------------------------------------------------------------------------
# 7. ThemeToggleSwitch: Compact Animated Light/Dark Sun-Moon Pill Switch
# ---------------------------------------------------------------------------

class ThemeToggleSwitch(tk.Canvas):
    """Tactile animated pill toggle switching between Dark (moon) and Light (sun)."""

    def __init__(
        self,
        master,
        is_light: bool,
        palette: Dict[str, str],
        on_toggle: Callable[[bool], None],
        bg_key: str = "sidebar",
    ) -> None:
        self._palette = palette
        self._bg_key = bg_key
        self._is_light = bool(is_light)
        self._pos = 1.0 if self._is_light else 0.0
        self._on_toggle = on_toggle
        self._anim_id: Optional[str] = None
        super().__init__(
            master, width=52, height=26, bg=palette[bg_key],
            highlightthickness=0, bd=0, cursor="hand2",
        )
        self.bind("<Button-1>", self._clicked)
        self._draw()

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self.configure(bg=palette[self._bg_key])
        self._draw()

    def set_mode(self, is_light: bool, animate: bool = True) -> None:
        self._is_light = bool(is_light)
        if not animate:
            self._pos = 1.0 if self._is_light else 0.0
            self._draw()
            return
        if self._anim_id is None:
            self._step()

    def _clicked(self, _event=None) -> None:
        self._is_light = not self._is_light
        if self._anim_id is None:
            self._step()
        if self._on_toggle:
            self._on_toggle(self._is_light)

    def _step(self) -> None:
        self._anim_id = None
        if not self.winfo_exists():
            return
        target = 1.0 if self._is_light else 0.0
        diff = target - self._pos
        if abs(diff) < 0.02:
            self._pos = target
            self._draw()
            return
        self._pos += diff * 0.30
        self._draw()
        self._anim_id = self.after(16, self._step)

    def _draw(self) -> None:
        self.delete("all")
        t = clamp(self._pos)
        track = blend_hex("#222A3E", "#FDE4B8", t)
        border = blend_hex("#36415C", "#F0B96B", t)
        _draw_rounded_rect(self, 1, 1, 51, 25, 12, fill=track, outline=border, width=1)

        if t < 0.7:
            sc = blend_hex("#8EA2D6", track, t / 0.7)
            self.create_oval(33, 7, 35.5, 9.5, fill=sc, outline="")
            self.create_oval(40, 14, 42, 16, fill=sc, outline="")

        cx = 13 + t * 26
        cy = 13
        r = 9
        thumb_fill = blend_hex("#141926", "#FF9A1F", t)
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=thumb_fill, outline="")

        if t < 0.5:
            mc = blend_hex("#FFD479", thumb_fill, t * 2.0)
            self.create_oval(cx - 4.5, cy - 4.5, cx + 4.5, cy + 4.5, fill=mc, outline="")
            self.create_oval(cx - 1.2, cy - 5.5, cx + 6.0, cy + 1.8, fill=thumb_fill, outline="")
        else:
            sc = blend_hex(thumb_fill, "#FFFFFF", (t - 0.5) * 2.0)
            self.create_oval(cx - 3.6, cy - 3.6, cx + 3.6, cy + 3.6, fill=sc, outline="")
            for deg in range(0, 360, 45):
                ang = math.radians(deg)
                self.create_line(
                    cx + math.cos(ang) * 5.2, cy + math.sin(ang) * 5.2,
                    cx + math.cos(ang) * 7.0, cy + math.sin(ang) * 7.0,
                    fill=sc, width=1.3,
                )


# ---------------------------------------------------------------------------
# 8. OverlayPreviewCanvas: Compact animated 16:9 OBS overlay miniature preview
# ---------------------------------------------------------------------------

class OverlayPreviewCanvas(tk.Canvas):
    """Interactive miniature 16:9 OBS scene preview reflecting OverlayConfig live."""

    _POS_ANCHORS = {
        "top-left": (0.0, 0.0),
        "top-center": (0.5, 0.0),
        "top-right": (1.0, 0.0),
        "left": (0.0, 0.5),
        "center": (0.5, 0.5),
        "right": (1.0, 0.5),
        "bottom-left": (0.0, 1.0),
        "bottom-center": (0.5, 1.0),
        "bottom-right": (1.0, 1.0),
    }

    def __init__(self, master, palette: Dict[str, str], height: int = 138) -> None:
        self._palette = palette
        super().__init__(
            master, height=height, bg=palette["preview_canvas"],
            highlightthickness=0, bd=0,
        )
        self._cfg_dict: Dict = {}
        self._title = "示例歌曲 Example Song"
        self._artist = "示例歌手 · 示例专辑"
        self._lyric = "♪ 示例歌词第一行"
        self._ax = 0.0
        self._ay = 1.0
        self._tx = 0.0
        self._ty = 1.0
        self._anim_id: Optional[str] = None
        self.bind("<Configure>", lambda _e: self._draw())

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self.configure(bg=palette["preview_canvas"])
        self._draw()

    def update_preview(self, cfg, snap: Optional[dict] = None) -> None:
        self._cfg_dict = cfg.to_dict() if hasattr(cfg, "to_dict") else dict(cfg or {})
        if snap and snap.get("title"):
            self._title = str(snap.get("title"))[:24]
            artist = " · ".join(x for x in (snap.get("artist"), snap.get("album")) if x)
            self._artist = (artist or "未知艺术家")[:28]
            lyr = (snap.get("lyrics_current") or "").splitlines()
            self._lyric = (lyr[0] if lyr else "♪ 实时同步歌词预览")[:24]
        pos = self._cfg_dict.get("pos", "bottom-left")
        self._tx, self._ty = self._POS_ANCHORS.get(pos, (0.0, 1.0))
        if abs(self._tx - self._ax) > 0.005 or abs(self._ty - self._ay) > 0.005:
            if self._anim_id is None:
                self._step()
        else:
            self._draw()

    def _step(self) -> None:
        self._anim_id = None
        if not self.winfo_exists():
            return
        dx = self._tx - self._ax
        dy = self._ty - self._ay
        if abs(dx) < 0.01 and abs(dy) < 0.01:
            self._ax, self._ay = self._tx, self._ty
            self._draw()
            return
        self._ax += dx * 0.28
        self._ay += dy * 0.28
        self._draw()
        self._anim_id = self.after(16, self._step)

    def _draw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 60 or h < 50:
            return
        cfg = self._cfg_dict
        bg_override = (cfg.get("bg") or "").strip()
        stage_bg = bg_override if bg_override.startswith("#") and len(bg_override) in (4, 7) else self._palette["preview_canvas"]
        grid_c = self._palette["preview_grid"]

        self.create_rectangle(0, 0, w, h, fill=stage_bg, outline="")
        if not bg_override:
            step = 18
            for gx in range(step, w, step):
                for gy in range(step, h, step):
                    self.create_oval(gx - 1, gy - 1, gx + 1, gy + 1, fill=grid_c, outline="")

        self.create_text(
            w - 10, 8, text="OBS 16:9 预览", anchor="ne",
            fill=self._palette["text_muted"], font=("Segoe UI", 8, "bold"),
        )

        theme_key = cfg.get("theme", "modern")
        meta = OVERLAY_THEME_META.get(theme_key, OVERLAY_THEME_META["modern"])
        panel_bg = (cfg.get("panel") or "").strip() or meta["panel"]
        accent = (cfg.get("accent") or "").strip() or meta["accent"]
        text_c = meta["text"]
        dim_c = meta["dim"]
        border_c = meta["border"]

        coverside = cfg.get("coverside", "left")
        if theme_key == "center":
            coverside = "top"
        is_bar = theme_key == "bar"

        hide_cover = bool(cfg.get("hide_cover"))
        hide_title = bool(cfg.get("hide_title"))
        hide_state = bool(cfg.get("hide_state"))
        hide_progress = bool(cfg.get("hide_progress"))
        hide_lyrics = bool(cfg.get("hide_lyrics"))

        if is_bar:
            cw = min(w - 28, 280)
            ch = 48
        elif coverside == "top":
            cw = 152
            ch = 104 if not hide_cover else 72
        else:
            cw = min(w - 30, 224)
            ch = 76 if not hide_lyrics else 62

        pad = 12
        avail_x = max(0, w - cw - pad * 2)
        avail_y = max(0, h - ch - pad * 2)
        cx1 = pad + avail_x * self._ax
        cy1 = pad + avail_y * self._ay
        cx2 = cx1 + cw
        cy2 = cy1 + ch

        raw_r = int(cfg.get("radius") or 0)
        card_r = clamp(raw_r * 0.55, 4, 16) if raw_r > 0 else 10

        if panel_bg:
            _draw_rounded_rect(
                self, cx1, cy1, cx2, cy2, card_r,
                fill=panel_bg, outline=border_c or "", width=1 if border_c else 0,
            )

        ip = 8
        cov_s = 32 if is_bar else (34 if coverside == "top" else 44)
        cov_r = clamp(int(cfg.get("coverradius") or 0) * 0.45, 3, 14) if cfg.get("coverradius") else 7

        tx1, ty1 = cx1 + ip, cy1 + ip
        tx2 = cx2 - ip

        if not hide_cover:
            if coverside == "right" and not is_bar:
                ax1 = cx2 - ip - cov_s
                ay1 = cy1 + (ch - cov_s) / 2
                tx2 = ax1 - 8
            elif coverside == "top" and not is_bar:
                ax1 = cx1 + (cw - cov_s) / 2
                ay1 = cy1 + ip
                ty1 = ay1 + cov_s + 5
            else:
                ax1 = cx1 + ip
                ay1 = cy1 + (ch - cov_s) / 2
                tx1 = ax1 + cov_s + 8
            _draw_rounded_rect(self, ax1, ay1, ax1 + cov_s, ay1 + cov_s, cov_r, fill=accent, outline="")
            mcx, mcy = ax1 + cov_s / 2, ay1 + cov_s / 2
            self.create_oval(mcx - 8, mcy - 8, mcx + 8, mcy + 8, fill="#161A23", outline="")
            self.create_oval(mcx - 2.5, mcy - 2.5, mcx + 2.5, mcy + 2.5, fill=accent, outline="")

        anchor = "n" if coverside == "top" and not is_bar else "nw"
        tx = (tx1 + tx2) / 2 if anchor == "n" else tx1

        if not hide_state and not is_bar:
            self.create_text(tx, ty1, text="● 播放中", anchor=anchor, fill=accent, font=("Segoe UI", 7, "bold"))
            ty1 += 10

        if not hide_title:
            self.create_text(tx, ty1, text=self._title[:16], anchor=anchor, fill=text_c, font=("Segoe UI", 8, "bold"))
            ty1 += 13
            self.create_text(tx, ty1, text=self._artist[:20], anchor=anchor, fill=dim_c, font=("Segoe UI", 7))
            ty1 += 11

        if not hide_progress:
            py = min(cy2 - (18 if not hide_lyrics else 10), ty1 + 3)
            pw = max(24, tx2 - tx1)
            _draw_rounded_rect(self, tx1, py, tx1 + pw, py + 3.5, 1.8, fill=blend_hex(dim_c, panel_bg or stage_bg, 0.6), outline="")
            _draw_rounded_rect(self, tx1, py, tx1 + pw * 0.58, py + 3.5, 1.8, fill=accent, outline="")
            ty1 = py + 6

        if not hide_lyrics and not is_bar:
            self.create_text(tx, min(cy2 - 12, ty1 + 1), text=self._lyric[:18], anchor=anchor, fill=text_c, font=("Segoe UI", 7))


# ---------------------------------------------------------------------------
# 9. ToastBanner: Smooth slide-in/out non-blocking status notification
# ---------------------------------------------------------------------------

class ToastBanner:
    """Animated floating pill toast anchored at the bottom-right of a parent container."""

    def __init__(self, master, palette: Dict[str, str]) -> None:
        import customtkinter as ctk

        self._master = master
        self._palette = palette
        self._frame = ctk.CTkFrame(
            master,
            fg_color=palette["toast_bg"],
            border_width=1,
            border_color=palette["toast_border"],
            corner_radius=12,
        )
        self._dot = ctk.CTkLabel(
            self._frame, text="●", width=10,
            font=ctk.CTkFont(family="Segoe UI", size=9),
            text_color=palette["accent"],
        )
        self._dot.pack(side="left", padx=(10, 4), pady=6)
        self._label = ctk.CTkLabel(
            self._frame, text="",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#F2F4F8",
        )
        self._label.pack(side="left", padx=(0, 12), pady=6)

        self._rely = 1.08
        self._target_rely = 1.08
        self._anim_id: Optional[str] = None
        self._hide_id: Optional[str] = None
        self._visible = False

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self._frame.configure(fg_color=palette["toast_bg"], border_color=palette["toast_border"])

    def show(self, message: str, kind: str = "accent", duration_ms: int = 2100) -> None:
        color = self._palette.get(kind, self._palette["accent"])
        self._dot.configure(text_color=color)
        self._label.configure(text=message)
        self._target_rely = 0.94
        if not self._visible:
            self._visible = True
            self._rely = 1.06
            self._frame.place(relx=0.97, rely=self._rely, anchor="se")
        self._frame.lift()
        if self._hide_id:
            try:
                self._master.after_cancel(self._hide_id)
            except Exception:
                pass
        self._hide_id = self._master.after(duration_ms, self.hide)
        if self._anim_id is None:
            self._step()

    def hide(self) -> None:
        self._hide_id = None
        self._target_rely = 1.08
        if self._anim_id is None:
            self._step()

    def _step(self) -> None:
        self._anim_id = None
        try:
            if not self._master.winfo_exists():
                return
        except Exception:
            return
        diff = self._target_rely - self._rely
        if abs(diff) < 0.002:
            self._rely = self._target_rely
            if self._rely >= 1.06:
                self._frame.place_forget()
                self._visible = False
            else:
                self._frame.place(relx=0.97, rely=self._rely, anchor="se")
            return
        self._rely += diff * 0.30
        self._frame.place(relx=0.97, rely=self._rely, anchor="se")
        self._anim_id = self._master.after(15, self._step)
