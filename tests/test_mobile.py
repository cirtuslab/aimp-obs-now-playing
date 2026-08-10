from aimp_obs.mobile import render_mobile


def test_mobile_page_has_core_elements():
    html = render_mobile()
    assert "lyricCur" in html
    assert "barFill" in html
    assert "/api/state" in html
    assert 'name="viewport"' in html
    assert "orientation: landscape" in html


def test_mobile_page_has_no_write_controls():
    # read-only: no POST, no config form
    html = render_mobile()
    assert "api/config" not in html
    assert 'method="post"' not in html.lower()
