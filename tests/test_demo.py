from aimp_obs.demo import demo_cover_bytes, demo_snapshot


def test_demo_snapshot_fields():
    snap = demo_snapshot()
    assert snap["title"] == "示例歌曲 Example Song"
    assert snap["artist"] == "示例歌手"
    assert snap["lyrics_synced"] is True
    assert 0 <= snap["progress"] <= 1


def test_demo_cover_is_png():
    assert demo_cover_bytes().startswith(b"\x89PNG")
