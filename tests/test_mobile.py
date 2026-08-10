from aimp_obs.mobile import mobile_icon_png, render_manifest, render_mobile


def test_mobile_page_has_core_elements():
    html = render_mobile()
    assert "lyricCur" in html
    assert "barFill" in html
    assert "/api/state" in html
    assert 'name="viewport"' in html
    assert "orientation: landscape" in html


def test_mobile_page_has_device_auth():
    html = render_mobile()
    assert "authOverlay" in html
    assert "/api/device/register" in html
    assert "/api/device/status" in html


def test_mobile_page_has_playback_control():
    html = render_mobile()
    assert "/api/control" in html
    assert "ctrlPanel" in html


def test_mobile_page_has_no_html_form():
    # read-only display: no form-based writes; controls use fetch only
    html = render_mobile()
    assert "<form" not in html.lower()


def test_mobile_manifest_and_icon():
    import json
    manifest = json.loads(render_manifest())
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/m"
    png = mobile_icon_png()
    assert png.startswith(b"\x89PNG")
