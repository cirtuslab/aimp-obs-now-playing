"""The lyric size animation must hand out one font per size, never reconfigure an attached one.

Re-configuring a font that is already used by an item makes Tk invalidate its whole font package;
every text widget in the process then repaints, which made the main window and the context menus
flicker for the whole lyric transition (measured: 101 repaints / ~500k px per 10 transitions,
versus 0 with per-size font objects).
"""

import types

from aimp_obs import floating
from aimp_obs.floating import FloatingOverlay


class _StubFont:
    created: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _StubFont.created.append(self)


def _bare_overlay() -> FloatingOverlay:
    overlay = FloatingOverlay.__new__(FloatingOverlay)
    overlay._anim_fonts = {}
    overlay.config = types.SimpleNamespace(lyric_font="Segoe UI")
    overlay.win = object()
    return overlay


def test_anim_font_is_created_once_per_size(monkeypatch):
    _StubFont.created = []
    monkeypatch.setattr(floating.tkfont, "Font", _StubFont)
    overlay = _bare_overlay()

    small = overlay._anim_font(11)
    assert overlay._anim_font(11) is small  # cached, not re-created
    large = overlay._anim_font(14)
    assert large is not small
    assert type(small) is _StubFont  # created, never re-configured
    assert len(_StubFont.created) == 2
    assert _StubFont.created[0].kwargs["size"] == 11
    assert _StubFont.created[1].kwargs["size"] == 14


def test_anim_font_cache_stays_bounded(monkeypatch):
    _StubFont.created = []
    monkeypatch.setattr(floating.tkfont, "Font", _StubFont)
    overlay = _bare_overlay()

    for size in range(6, 120):
        overlay._anim_font(size)
    assert len(overlay._anim_fonts) <= 65
