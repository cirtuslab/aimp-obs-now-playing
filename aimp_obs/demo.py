"""Demo (mock) data so the GUI / floating window can preview without AIMP."""

from __future__ import annotations

import io
import time

from PIL import Image, ImageDraw, ImageFont

DEMO_COVER_TS = 999
DEMO_DURATION_MS = 225_000
DEMO_LINES = [
    ("♪ 示例歌词第一行", "♪ 示例歌词第一句翻译"),
    ("♪ 示例歌词第二行", "♪ 示例歌词第二句翻译"),
    ("♪ 示例歌词第三行", "♪ 示例歌词第三句翻译"),
    ("♪ 示例歌词第四行", "♪ 示例歌词第四句翻译"),
    ("♪ 示例歌词第五行", "♪ 示例歌词第五句翻译"),
]

# Enhanced LRC word timings (relative to each demo line start).
DEMO_WORDS = [
    [{"t": 0, "s": "♪ 示"}, {"t": 1000, "s": "例"}, {"t": 2000, "s": "歌"}, {"t": 3000, "s": "词"}, {"t": 4000, "s": "第一"}, {"t": 5200, "s": "行"}],
    [{"t": 0, "s": "♪ 示例"}, {"t": 1400, "s": "歌词"}, {"t": 2800, "s": "第二行"}],
    [{"t": 0, "s": "♪ 示例"}, {"t": 1400, "s": "歌词"}, {"t": 2800, "s": "第三行"}],
    [{"t": 0, "s": "♪ 示例"}, {"t": 1400, "s": "歌词"}, {"t": 2800, "s": "第四行"}],
    [{"t": 0, "s": "♪ 示例"}, {"t": 1400, "s": "歌词"}, {"t": 2800, "s": "第五行"}],
]

_cover_cache: bytes | None = None


def demo_cover_bytes() -> bytes:
    global _cover_cache
    if _cover_cache is not None:
        return _cover_cache
    img = Image.new("RGB", (512, 512), (30, 34, 46))
    d = ImageDraw.Draw(img)
    for y in range(512):
        d.line([(0, y), (512, y)], fill=(24 + y // 8, 30 + y // 10, 44 + y // 9))
    d.ellipse([96, 96, 416, 416], fill=(255, 159, 25))
    d.ellipse([150, 150, 362, 362], fill=(30, 34, 46))
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 150)
    except Exception:
        font = ImageFont.load_default()
    d.text((180, 180), "\u266a", font=font, fill=(255, 159, 25))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    _cover_cache = buf.getvalue()
    return _cover_cache


def _fmt(ms: int) -> str:
    total = int(ms) // 1000
    m, s = divmod(total, 60)
    return f"{m}:{s:02d}"


def demo_snapshot() -> dict:
    now = time.time()
    position_ms = int((now * 1000) % DEMO_DURATION_MS)
    idx = int(now // 8) % len(DEMO_LINES)
    cur = DEMO_LINES[idx]
    nxt = DEMO_LINES[(idx + 1) % len(DEMO_LINES)]
    line_base_ms = idx * 8000
    cur_words = [{"t": line_base_ms + w["t"], "s": w["s"]} for w in DEMO_WORDS[idx]]
    return {
        "connected": True,
        "state": "playing",
        "state_text": "播放中",
        "title": "示例歌曲 Example Song",
        "artist": "示例歌手",
        "album": "示例专辑",
        "genre": "Pop",
        "year": "2026",
        "filename": "D:\\Demo\\example.mp3",
        "position_ms": position_ms,
        "duration_ms": DEMO_DURATION_MS,
        "position": _fmt(position_ms),
        "duration": _fmt(DEMO_DURATION_MS),
        "progress": position_ms / DEMO_DURATION_MS,
        "volume": 60,
        "muted": False,
        "shuffle": False,
        "repeat": False,
        "track_key": "demo",
        "lyrics_synced": True,
        "lyrics_words": cur_words,
        "lyrics_current": "\n".join(cur),
        "lyrics_next": "\n".join(nxt),
        "lyrics_full": ["\n".join(line) for line in DEMO_LINES],
        "cover_ts": DEMO_COVER_TS,
        "aimp_version": "演示数据",
        "updated_at": now,
    }
