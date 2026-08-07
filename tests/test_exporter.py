import time

from aimp_obs.state import Exporter


def _snapshot(position_ms=1000, cover_ts=1):
    return {
        "track_key": "track-a",
        "state": "playing",
        "state_text": "播放中",
        "title": "测试歌曲",
        "artist": "测试歌手",
        "album": "",
        "position_ms": position_ms,
        "position": "0:01",
        "duration": "3:00",
        "cover_ts": cover_ts,
    }


def test_cover_only_rewritten_when_cover_changes(tmp_path):
    exporter = Exporter(tmp_path)
    exporter.write(_snapshot(1000), b"cover-1", "lyrics")
    first = (tmp_path / "cover.png").read_bytes()

    time.sleep(0.01)
    exporter.write(_snapshot(2000), b"cover-1", "lyrics")
    assert (tmp_path / "cover.png").read_bytes() == first

    exporter.write(_snapshot(3000, cover_ts=2), b"cover-2", "lyrics")
    assert (tmp_path / "cover.png").read_bytes() == b"cover-2"


def test_lyrics_only_rewritten_when_changed(tmp_path):
    exporter = Exporter(tmp_path)
    exporter.write(_snapshot(), b"cover", "lyrics-A")
    first = (tmp_path / "lyrics.lrc").read_text(encoding="utf-8")
    exporter.write(_snapshot(2000), b"cover", "lyrics-A")
    assert (tmp_path / "lyrics.lrc").read_text(encoding="utf-8") == first
    exporter.write(_snapshot(3000), b"cover", "lyrics-B")
    assert (tmp_path / "lyrics.lrc").read_text(encoding="utf-8") == "lyrics-B"
