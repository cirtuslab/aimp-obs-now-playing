"""LRC / embedded-lyrics loading and live line lookup."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META_RE = re.compile(r"^\[([a-zA-Z]+):(.*)\]$")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class LyricLine:
    time_ms: int
    text: str


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


def parse_lrc(text: str) -> Lyrics:
    synced = False
    metadata: Dict[str, str] = {}
    lines: List[LyricLine] = []
    unsynced: List[str] = []

    for raw_line in text.splitlines():
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
            for tag in tags:
                time_ms = _time_from_tag(tag.group(1), tag.group(2), tag.group(3) or "")
                if time_ms is None:
                    continue
                lines.append(LyricLine(time_ms, body))
        else:
            unsynced.append(line)

    offset = 0
    try:
        offset = int(metadata.get("offset", "0"))
    except ValueError:
        offset = 0
    if offset:
        for ln in lines:
            ln.time_ms += offset
    lines.sort(key=lambda ln: ln.time_ms)
    return Lyrics(synced=synced, lines=lines, unsynced_lines=unsynced, metadata=metadata, raw=text)


def _sanitize_filename(name: str) -> str:
    return _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")


class LyricsProvider:
    """Finds lyrics for the currently playing file (sidecar .lrc/.txt or tags)."""

    def __init__(self) -> None:
        self._cache: Dict[tuple, Lyrics] = {}

    def get(self, filename: str, title: str, artist: str) -> Optional[Lyrics]:
        if not filename or filename.startswith(("http://", "https://", "rtmp://")):
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
                    self._cache[key] = parse_lrc(decode_bytes(cand.read_bytes()))
                return self._cache[key]
            except OSError:
                continue
        return self._load_embedded(path)

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
