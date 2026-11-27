"""Tests for the pywebview Prism Deck backend bridge, palette extractor, and WebUI loader."""

import io
import types
from pathlib import Path

from PIL import Image

from aimp_obs.cover import CoverStore
from aimp_obs.devices import DeviceManager
from aimp_obs.gui import App
from aimp_obs.overlay import OverlayConfig
from aimp_obs.settings import SettingsStore
from aimp_obs.theme import enumerate_system_fonts, extract_cover_palette
from aimp_obs.webui import load_floating_html, load_webui_html


class _FakeClient:
    def __init__(self):
        self.connected = True
        self.cmds = []
        self.props = []

    def detect(self):
        return True

    def send_command(self, cmd):
        self.cmds.append(cmd)

    def set_property(self, prop, val):
        self.props.append((prop, val))


class _FakeStateHub:
    def __init__(self):
        self.exporter = None

    def snapshot(self):
        return {
            "connected": True,
            "state": "playing",
            "title": "Prism Test",
            "artist": "Test Artist",
            "album": "Test Album",
            "position_ms": 42000,
            "duration_ms": 180000,
            "position": "0:42",
            "duration": "3:00",
            "progress": 0.2333,
            "lyrics_synced": True,
            "lyrics_words": [],
            "lyrics_current": "Test lyric line",
            "lyrics_next": "Next line",
            "lyrics_full": [],
            "cover_ts": 1,
        }


class _FakeServer:
    def __init__(self, devices):
        self.host = "127.0.0.1"
        self.port = 8765
        self.running = True
        self.config = OverlayConfig()
        self.devices = devices

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/"

    def start(self):
        self.running = True
        return True

    def stop(self):
        self.running = False


def test_load_webui_html_inlines_css_and_js():
    html = load_webui_html()
    assert "/*__PRISM_CSS__*/" not in html
    assert "/*__PRISM_JS__*/" not in html
    assert "AIMP PRISM" in html
    assert "spectrumCanvas" in html
    assert "makeQrSvg" in html


def test_load_floating_html_is_transparent_and_self_contained():
    html = load_floating_html()
    assert "floating_show_menu" in html
    assert "poll_floating" in html
    assert "__FLOAT_LOCK_STATE__" in html
    assert "__FLOAT_SET_SCALE__" in html


def test_extract_cover_palette_produces_three_hex_colors():
    img = Image.new("RGB", (64, 64), (10, 14, 24))
    for x in range(10, 32):
        for y in range(10, 54):
            img.putpixel((x, y), (255, 80, 30))
    for x in range(34, 58):
        for y in range(10, 54):
            img.putpixel((x, y), (40, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    pal = extract_cover_palette(buf.getvalue())
    assert set(pal.keys()) == {"primary", "secondary", "glow"}
    for val in pal.values():
        assert val.startswith("#") and len(val) == 7


def test_enumerate_system_fonts_returns_nonempty_list():
    fonts = enumerate_system_fonts()
    assert isinstance(fonts, list)
    assert len(fonts) > 0
    assert all(isinstance(f, str) and not f.startswith("@") for f in fonts)


def test_studio_bridge_bootstrap_controls_and_settings(tmp_path: Path):
    settings = SettingsStore(tmp_path / "settings.json")
    devices = DeviceManager(tmp_path / "devices.json")
    server = _FakeServer(devices)
    client = _FakeClient()
    cover_store = CoverStore()
    app = App(
        client=client,
        receiver=types.SimpleNamespace(hwnd=0),
        state_hub=_FakeStateHub(),
        cover_store=cover_store,
        server=server,
        export_dir=tmp_path / "export",
        refresh_ms=250,
        settings=settings,
    )

    boot = app.bridge.get_bootstrap()
    assert boot["ui_theme"] == "dark"
    assert boot["cover_data_url"].startswith("data:image/")
    assert "modern" in boot["themes"]
    assert boot["snapshot"]["title"] == "Prism Test"

    # Second poll with same cover_ts skips resending cover base64
    poll_same = app.bridge.poll_state(boot["cover_ts"])
    assert "cover_data_url" not in poll_same

    # Player command & seek
    assert app.bridge.player_cmd("playpause")["ok"] is True
    assert len(client.cmds) == 1
    assert app.bridge.seek(0.5)["ok"] is True
    assert client.props[-1][1] == 90000

    # Theme & overlay persistence
    res_theme = app.bridge.set_ui_theme("light")
    assert res_theme["ui_theme"] == "light"
    assert settings.ui_theme == "light"

    res_ov = app.bridge.update_overlay({"theme": "neon", "pos": "top-right", "hide_lyrics": True})
    assert res_ov["overlay"]["theme"] == "neon"
    assert res_ov["overlay"]["pos"] == "top-right"
    assert res_ov["overlay"]["hide_lyrics"] is True

    # Reset restores defaults
    res_rst = app.bridge.reset_overlay()
    assert res_rst["overlay"]["theme"] == "modern"
    assert res_rst["overlay"]["pos"] == "bottom-left"

    # Demo toggle switches cover
    assert app.bridge.toggle_demo()["demo"] is True
    poll_demo = app.bridge.poll_state(boot["cover_ts"])
    assert poll_demo["snapshot"]["connected"] is True
    assert "cover_data_url" in poll_demo

    # Mobile toggle & device approval
    m = app.bridge.toggle_mobile(True)
    assert m["enabled"] is True
    reg = devices.register("dev-123", "iPhone", "sec-1")
    assert reg["pending"] is True
    m2 = app.bridge.device_action("approve", "dev-123")
    assert len(m2["approved"]) == 1
    assert len(m2["pending"]) == 0
