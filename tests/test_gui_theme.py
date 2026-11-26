"""Tests for the dual-theme design tokens, easing math, and vector icon renderer."""

from PIL import Image

from aimp_obs.theme import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    WS_EX_APPWINDOW,
    WS_EX_TOOLWINDOW,
    blend_hex,
    compute_no_taskbar_exstyle,
    dominant_accent_from_image,
    ease_in_out_cubic,
    ease_out_cubic,
    get_palette,
    hex_to_rgb,
    render_icon_image,
    rgb_to_hex,
)


def test_dark_and_light_palettes_share_exact_keys():
    assert set(DARK_PALETTE.keys()) == set(LIGHT_PALETTE.keys())
    assert get_palette("dark") is DARK_PALETTE
    assert get_palette("light") is LIGHT_PALETTE
    assert get_palette("LIGHT") is LIGHT_PALETTE
    assert get_palette("unknown") is DARK_PALETTE


def test_color_conversion_and_blending():
    assert hex_to_rgb("#ff9a1f") == (255, 154, 31)
    assert hex_to_rgb("#fff") == (255, 255, 255)
    assert rgb_to_hex(255, 154, 31) == "#FF9A1F"
    assert blend_hex("#000000", "#FFFFFF", 0.0) == "#000000"
    assert blend_hex("#000000", "#FFFFFF", 1.0) == "#FFFFFF"
    assert blend_hex("#000000", "#FFFFFF", 0.5) == "#808080"


def test_easing_boundaries_and_monotonicity():
    for fn in (ease_out_cubic, ease_in_out_cubic):
        assert fn(-0.5) == 0.0
        assert fn(0.0) == 0.0
        assert fn(1.0) == 1.0
        assert fn(1.5) == 1.0
        vals = [fn(i / 10.0) for i in range(11)]
        assert vals == sorted(vals)


def test_dominant_accent_extracts_saturated_hue():
    img = Image.new("RGB", (64, 64), (20, 22, 30))
    for x in range(16, 48):
        for y in range(16, 48):
            img.putpixel((x, y), (255, 120, 20))
    r, g, b = dominant_accent_from_image(img)
    assert r > 200 and g > 80 and b < 60


def test_vector_icons_render_rgba_at_requested_size():
    names = (
        "play", "pause", "stop", "prev", "next", "music", "palette",
        "broadcast", "phone", "float", "sparkles", "copy", "external",
        "folder", "sun", "moon", "reset", "power", "brand", "dot",
    )
    for name in names:
        img = render_icon_image(name, "#FF9A1F", size=18)
        assert img.mode == "RGBA"
        assert img.size == (18, 18)
        # Ensure something non-transparent was actually drawn
        assert img.getbbox() is not None


def test_no_taskbar_exstyle_sets_toolwindow_and_clears_appwindow():
    # Typical top-level window with WS_EX_APPWINDOW + WS_EX_TOPMOST (0x8)
    raw = WS_EX_APPWINDOW | 0x00080008
    out = compute_no_taskbar_exstyle(raw)
    assert out & WS_EX_TOOLWINDOW
    assert not (out & WS_EX_APPWINDOW)
    assert out & 0x00080008  # preserves topmost & layered bits

