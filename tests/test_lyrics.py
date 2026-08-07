from aimp_obs.lyrics import parse_lrc


def test_synced_lrc_with_offset_and_translation():
    text = (
        "[ti:测试]\n"
        "[offset:-500]\n"
        "[00:10.000]原文\n"
        "[00:10.000]译文\n"
        "[00:20.000]下一句\n"
    )
    lrc = parse_lrc(text)
    assert lrc.synced is True
    assert lrc.lines[0].time_ms == 9500
    cur, nxt = lrc.group_at(9600)
    assert cur == "原文\n译文"
    assert nxt == "下一句"


def test_unsynced_lrc():
    lrc = parse_lrc("第一行\n第二行\n")
    assert lrc.synced is False
    assert lrc.full_text() == "第一行\n第二行"


def test_multiple_timestamps_on_one_line():
    text = "[00:01.000][00:03.000]重复行\n"
    lrc = parse_lrc(text)
    assert [line.time_ms for line in lrc.lines] == [1000, 3000]
