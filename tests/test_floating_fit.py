"""Text fitting must keep the previous (linear) trimming result while being much cheaper."""

from aimp_obs.floating import trim_to_width


def _measure(text: str) -> int:
    """Deterministic stand-in for a proportional font."""
    return sum(7 if ch in "ilj.,! " else 13 for ch in text)


def _reference(text: str, max_w: int) -> str:
    if _measure(text) <= max_w:
        return text
    while text and _measure(text + "…") > max_w:
        text = text[:-1]
    return text + "…"


def test_matches_reference_for_many_widths():
    samples = [
        "Messages from the Stars (Extended Club Mix)",
        "A very long title " * 6,
        "短标题",
        "中文歌词第一句与第二句混排的歌词行",
        "iiiiiii",
        "WWWWWWWWWWWWWWWWWW",
        "",
    ]
    for text in samples:
        for max_w in (0, 5, 40, 61, 120, 240, 367, 800, 5000):
            assert trim_to_width(text, max_w, _measure) == _reference(text, max_w), (text, max_w)


def test_text_that_fits_is_returned_unchanged():
    assert trim_to_width("short", 500, _measure) == "short"


def test_ellipsis_is_binary_searched():
    calls = []

    def counting_measure(text: str) -> int:
        calls.append(text)
        return _measure(text)

    out = trim_to_width("A very long title " * 6, 200, counting_measure)
    assert out.endswith("…")
    assert len(calls) <= 12  # log2(len) probes per step, not one per dropped character
