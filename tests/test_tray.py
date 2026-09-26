"""Tray icon bookkeeping: the balloon hint must be silent and properly filled in."""

from aimp_obs.tray import NIF_ICON, NIF_INFO, NIF_TIP, NIIF_INFO, NIIF_NOSOUND, TrayIcon


def test_balloon_hint_is_silent():
    tray = TrayIcon("AIMP Now Playing → OBS")
    data = tray._notify_data("已最小化到托盘，双击图标恢复窗口")

    assert data.uFlags & NIF_INFO
    assert data.dwInfoFlags == NIIF_INFO | NIIF_NOSOUND  # no chime
    assert data.szInfo == "已最小化到托盘，双击图标恢复窗口"
    assert data.szInfoTitle == "AIMP Now Playing → OBS"


def test_tooltip_and_icon_always_set():
    tray = TrayIcon("AIMP Now Playing → OBS")
    data = tray._notify_data()

    assert not (data.uFlags & NIF_INFO)  # no balloon without a hint
    assert data.uFlags & NIF_ICON and data.uFlags & NIF_TIP
    assert data.szTip == "AIMP Now Playing → OBS"


def test_long_text_is_truncated_to_field_sizes():
    tray = TrayIcon("T" * 200)
    data = tray._notify_data("x" * 400)

    assert len(data.szTip) <= 127
    assert len(data.szInfo) <= 255
    assert len(data.szInfoTitle) <= 63
