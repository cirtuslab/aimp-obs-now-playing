from aimp_obs.settings import SettingsStore


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.port = 8899
    store.refresh_ms = 500
    store.floating_lyric_font_anim = False
    store.overlay.theme = "neon"
    store.overlay.lyric_font = "微软雅黑"
    store.save()

    loaded = SettingsStore(path)
    assert loaded.port == 8899
    assert loaded.refresh_ms == 500
    assert loaded.floating_lyric_font_anim is False
    assert loaded.overlay.theme == "neon"
    assert loaded.overlay.lyric_font == "微软雅黑"
