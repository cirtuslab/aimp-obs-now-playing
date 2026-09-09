from aimp_obs.overlay import OverlayConfig


def test_update_from_dict_casts_types():
    cfg = OverlayConfig()
    cfg.update_from_dict({
        "theme": "neon",
        "width": "480",
        "hide_lyrics": "true",
        "margin": 12.0,
        "lyric_font": "微软雅黑",
        "not_a_field": "ignored",
        "_private": "ignored",
    })
    assert cfg.theme == "neon"
    assert cfg.width == 480 and isinstance(cfg.width, int)
    assert cfg.hide_lyrics is True
    assert cfg.margin == 12 and isinstance(cfg.margin, int)
    assert cfg.lyric_font == "微软雅黑"
    assert not hasattr(cfg, "not_a_field")


def test_update_from_dict_rejects_bad_values():
    cfg = OverlayConfig(theme="modern", width=460)
    cfg.update_from_dict({
        "width": "not-a-number",
        "theme": None,
        "hide_title": "off",
    })
    assert cfg.width == 460
    assert cfg.theme == ""
    assert cfg.hide_title is False


def test_update_from_dict_truncates_long_strings():
    cfg = OverlayConfig()
    cfg.update_from_dict({"lyric_font": "x" * 1000})
    assert len(cfg.lyric_font) == 256
