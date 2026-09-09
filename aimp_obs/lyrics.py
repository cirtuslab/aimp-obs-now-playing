"""LRC / embedded-lyrics loading and live line lookup."""

from __future__ import annotations

import bisect
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# AIMP-NCM (https://github.com/cirtuslab/AIMP-NCM) streaming item URIs as
# written into the synced playlist / reported by AIMP's shared memory:
#   http://127.0.0.1:<port>/x/<token>/<playlist_id>/<song_id>.mp3   (>= v1.6, token auth)
#   http://127.0.0.1:<port>/<playlist_id>/<song_id>                 (v1.5, extensionless)
#   http://127.0.0.1:<port>/<playlist_id>/<song_id>.mp3             (legacy)
# The token segment is only for proxy auth; the song id (needed for the
# lyric lookup) is the last numeric segment.
# Lyrics for these items live in %TEMP%\aimp_ncm\lyric\<song_id>.lrc
# (AIMP-NCM v1.5+ cache, shared by AIMPLyricsSaver since its archive
# directory was aligned to the singular form); the old plural "lyrics"
# directory is kept for backwards compatibility.
_NCM_HTTP_RE = re.compile(
    r"^https?://[^/]+/(?:x/[^/]+/)?(\d+)/(\d+?)(?:\.mp3)?$"
)
_NCM_LRC_DIRS = ("lyric", "lyrics")

_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_WORD_TIME_RE = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")
_META_RE = re.compile(r"^\[([a-zA-Z]+):(.*)\]$")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class LyricWord:
    """A single word in an Enhanced LRC line (absolute start time + text)."""

    start_ms: int
    text: str


@dataclass
class LyricLine:
    time_ms: int
    text: str
    words: List[LyricWord] = field(default_factory=list)


@dataclass
class Lyrics:
    synced: bool
    lines: List[LyricLine] = field(default_factory=list)
    unsynced_lines: List[str] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    raw: str = ""

    @property
    def has_text(self) -> bool:
        return bool(self.lines or self.unsynced_lines)

    def group_at(self, pos_ms: int) -> tuple[str, str]:
        """Return (current group text, next group text) for the given position."""
        if not self.synced or not self.lines:
            return "", ""
        times = [ln.time_ms for ln in self.lines]
        idx = bisect.bisect_right(times, pos_ms) - 1
        if idx < 0:
            current = ""
            nxt = self.lines[0].text
            return current, nxt
        group_time = times[idx]
        start = idx
        while start > 0 and times[start - 1] == group_time:
            start -= 1
        end = idx + 1
        while end < len(self.lines) and times[end] == group_time:
            end += 1
        current = "\n".join(ln.text for ln in self.lines[start:end])
        if end < len(self.lines):
            next_time = times[end]
            nxt_end = end + 1
            while nxt_end < len(self.lines) and times[nxt_end] == next_time:
                nxt_end += 1
            nxt = "\n".join(ln.text for ln in self.lines[end:nxt_end])
        else:
            nxt = ""
        return current, nxt

    def words_at(self, pos_ms: int) -> List[Dict[str, object]]:
        """Return Enhanced-LRC words of the line active at pos_ms."""
        if not self.synced or not self.lines:
            return []
        times = [ln.time_ms for ln in self.lines]
        idx = bisect.bisect_right(times, pos_ms) - 1
        if idx < 0:
            return []
        group_time = times[idx]
        start = idx
        while start > 0 and times[start - 1] == group_time:
            start -= 1
        words = self.lines[start].words
        return [{"t": w.start_ms, "s": w.text} for w in words]

    def full_text(self) -> str:
        if self.synced:
            return "\n".join(ln.text for ln in self.lines)
        return "\n".join(self.unsynced_lines)


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "gb18030", "big5", "shift_jis", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _time_from_tag(minutes: str, seconds: str, fraction: str) -> Optional[int]:
    try:
        return (
            int(minutes) * 60_000
            + int(seconds) * 1000
            + int(fraction.ljust(3, "0")[:3] if fraction else "0")
        )
    except ValueError:
        return None


def _parse_enhanced_words(body: str, line_start_ms: Optional[int]) -> List[LyricWord]:
    """Parse Enhanced LRC word tags `<mm:ss.xx>` inside a line body."""
    if not body or "<" not in body:
        return []
    words: List[LyricWord] = []
    prev_start = line_start_ms
    pos = 0
    for m in _WORD_TIME_RE.finditer(body):
        seg = body[pos:m.start()]
        if seg and prev_start is not None:
            words.append(LyricWord(prev_start, seg))
        prev_start = _time_from_tag(m.group(1), m.group(2), m.group(3) or "")
        pos = m.end()
    tail = body[pos:]
    if tail and prev_start is not None:
        words.append(LyricWord(prev_start, tail))
    if len(words) < 2:
        return []
    return words


def parse_lrc(source: str) -> Lyrics:
    synced = False
    metadata: Dict[str, str] = {}
    lines: List[LyricLine] = []
    unsynced: List[str] = []

    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        meta = _META_RE.match(line)
        if meta and line.startswith("["):
            key, value = meta.group(1).lower(), meta.group(2).strip()
            if key in ("ti", "ar", "al", "by", "offset", "re", "ve"):
                metadata[key] = value
                continue

        tags = list(_TIME_RE.finditer(line))
        if tags:
            synced = True
            body = line[tags[-1].end():].strip()
            if not body:
                continue
            first_ms = _time_from_tag(tags[0].group(1), tags[0].group(2), tags[0].group(3) or "")
            words = _parse_enhanced_words(body, first_ms)
            body_text = _WORD_TIME_RE.sub("", body)
            stripped = body_text.strip()
            if stripped != body_text:
                lead = len(body_text) - len(body_text.lstrip())
                trail = len(body_text) - len(body_text.rstrip())
                body_text = stripped
                if words:
                    if lead:
                        w0 = words[0]
                        words[0] = LyricWord(w0.start_ms, w0.text[lead:] if len(w0.text) >= lead else w0.text)
                    if trail:
                        wl = words[-1]
                        words[-1] = LyricWord(wl.start_ms, wl.text[:len(wl.text) - trail] if len(wl.text) >= trail else wl.text)
            for tag in tags:
                time_ms = _time_from_tag(tag.group(1), tag.group(2), tag.group(3) or "")
                if time_ms is None:
                    continue
                lines.append(LyricLine(time_ms, body_text, words=words))
        else:
            unsynced.append(line)

    offset = 0
    try:
        offset = int(metadata.get("offset", "0"))
    except ValueError:
        offset = 0
    if offset:
        seen_word_lists: set = set()
        for ln in lines:
            ln.time_ms += offset
            # Multi-timestamp lines share one words list; apply offset only once.
            if ln.words and id(ln.words) not in seen_word_lists:
                seen_word_lists.add(id(ln.words))
                for w in ln.words:
                    w.start_ms += offset
    lines.sort(key=lambda ln: ln.time_ms)
    return Lyrics(synced=synced, lines=lines, unsynced_lines=unsynced, metadata=metadata, raw=source)


def _sanitize_filename(name: str) -> str:
    return _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")


class LyricsProvider:
    """Finds lyrics for the currently playing file (sidecar .lrc/.txt or tags)."""

    _MAX_CACHE = 64

    def __init__(self) -> None:
        self._cache: Dict[tuple, Lyrics] = {}

    def _cache_put(self, key: tuple, lyrics: Lyrics) -> None:
        if key in self._cache:
            self._cache[key] = lyrics
            return
        if len(self._cache) >= self._MAX_CACHE:
            # Drop the oldest inserted entry to keep memory bounded.
            try:
                oldest = next(iter(self._cache))
            except StopIteration:
                return
            del self._cache[oldest]
        self._cache[key] = lyrics

    def get(self, filename: str, title: str, artist: str) -> Optional[Lyrics]:
        if not filename:
            return None
        # AIMP-NCM streaming items: lyrics are fetched and saved by the
        # AIMPLyricsSaver plugin to %TEMP%\aimp_ncm\lyrics\<song_id>.lrc.
        ncm = self._get_ncm_lyrics(filename)
        if ncm is not None:
            return ncm
        if filename.startswith(("http://", "https://", "rtmp://")):
            return None
        path = Path(filename)
        candidates = self._candidates(path, title, artist)
        for cand in candidates:
            try:
                if not cand.is_file():
                    continue
                stat = cand.stat()
                key = (str(cand), stat.st_mtime_ns, stat.st_size)
                if key not in self._cache:
                    self._cache_put(key, parse_lrc(decode_bytes(cand.read_bytes())))
                return self._cache[key]
            except OSError:
                continue
        return self._load_embedded(path)

    @staticmethod
    def _get_ncm_lyrics(filename: str) -> Optional[Lyrics]:
        m = _NCM_HTTP_RE.match(filename)
        if not m:
            return None
        song_id = m.group(2)
        temp = Path(os.environ.get("TEMP", "")) / "aimp_ncm"
        for sub in _NCM_LRC_DIRS:
            lrc_path = temp / sub / f"{song_id}.lrc"
            try:
                if not lrc_path.is_file():
                    continue
                return parse_lrc(decode_bytes(lrc_path.read_bytes()))
            except OSError:
                continue
        return None

    @staticmethod
    def _candidates(path: Path, title: str, artist: str) -> List[Path]:
        out: List[Path] = []
        try:
            parent = path.parent
            stem = path.stem
        except (OSError, ValueError):
            return out
        for ext in (".lrc", ".txt"):
            out.append(parent / f"{stem}{ext}")
        safe_title = _sanitize_filename(title)
        safe_artist = _sanitize_filename(artist)
        if safe_artist and safe_title:
            for ext in (".lrc", ".txt"):
                out.append(parent / f"{safe_artist} - {safe_title}{ext}")
        if safe_title:
            for ext in (".lrc", ".txt"):
                out.append(parent / f"{safe_title}{ext}")
        return out

    @staticmethod
    def _load_embedded(path: Path) -> Optional[Lyrics]:
        try:
            from tinytag import TinyTag
        except ImportError:
            return None
        try:
            tag = TinyTag.get(path, tags=True, duration=False)
            values = tag.other.get("lyrics") if hasattr(tag, "other") else None
            if not values:
                return None
            text = "\n".join(str(v) for v in values)
            return parse_lrc(text)
        except Exception:
            return None
