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


def test_enhanced_lrc_words():
    text = (
        "[00:20.570]<00:20.570>初<00:20.930>め<00:21.080>て<00:21.200>の<00:21.370>ル<00:21.430>ー<00:21.620>ブ<00:21.770>ル<00:21.940>は<00:22.470>\n"
        "[00:20.570]第一次去卢浮宫时\n"
        "[00:22.760]<00:22.760>な<00:22.970>ん<00:23.130>て\n"
    )
    lrc = parse_lrc(text)
    assert lrc.synced is True
    # tags are stripped from the display text
    assert lrc.lines[0].text == "初めてのルーブルは"
    words = lrc.lines[0].words
    assert len(words) == 9
    assert words[0].start_ms == 20570 and words[0].text == "初"
    assert words[1].start_ms == 20930 and words[1].text == "め"
    assert words[-1].start_ms == 21940 and words[-1].text == "は"
    # translation line carries no word data
    assert lrc.lines[1].words == []
    assert lrc.lines[1].text == "第一次去卢浮宫时"
    # words_at returns the active line's words
    cur = lrc.words_at(21500)
    assert cur[0] == {"t": 20570, "s": "初"}
    assert cur[4] == {"t": 21370, "s": "ル"}
    # before the first line -> no words
    assert lrc.words_at(0) == []


def test_enhanced_lrc_single_word_not_treated_as_enhanced():
    lrc = parse_lrc("[00:00.000]<00:00.000> 作词 : 宇多田ヒカル<00:01.000>\n")
    assert lrc.lines[0].words == []
    assert lrc.lines[0].text == "作词 : 宇多田ヒカル"


def test_enhanced_lrc_offset_applies_to_words():
    text = "[00:10.000]<00:10.000>词<00:10.500>组<00:11.000>测<00:11.500>试\n"
    lrc = parse_lrc(text)
    assert [w.start_ms for w in lrc.lines[0].words] == [10000, 10500, 11000, 11500]


def test_ncm_http_url_uses_plugin_lyric_file(tmp_path, monkeypatch):
    from aimp_obs.lyrics import LyricsProvider

    monkeypatch.setenv("TEMP", str(tmp_path))
    lrc_dir = tmp_path / "aimp_ncm" / "lyrics"
    lrc_dir.mkdir(parents=True)
    (lrc_dir / "22719261.lrc").write_text(
        "[00:10.000]第一次去卢浮宫时\n[00:22.760]なんて\n", encoding="utf-8"
    )
    provider = LyricsProvider()
    lyrics = provider.get("http://127.0.0.1:47777/781962518/22719261.mp3", "卢浮宫", "某人")
    assert lyrics is not None and lyrics.synced is True
    assert [ln.text for ln in lyrics.lines] == ["第一次去卢浮宫时", "なんて"]


def test_ncm_url_without_plugin_file_falls_back(tmp_path, monkeypatch):
    from aimp_obs.lyrics import LyricsProvider

    monkeypatch.setenv("TEMP", str(tmp_path))
    assert LyricsProvider().get("http://127.0.0.1:47777/1/999.mp3", "x", "y") is None

