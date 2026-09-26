"""State collection, JSON snapshots and export-file generation."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from .aimp_api import AimpClient, AimpError, AlbumArtReceiver
from .cover import CoverStore, get_cover_for_file, normalize_to_png
from .lyrics import LyricsProvider


def format_time(ms: int) -> str:
    if ms is None or ms < 0:
        return "0:00"
    total = int(ms) // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class Exporter:
    """Writes plain files that OBS text/image sources can also consume."""

    def __init__(self, export_dir: Path) -> None:
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self._last_sig: Optional[tuple] = None
        self._last_cover_ts: Optional[int] = None
        self._last_lyrics_raw: Optional[str] = None

    def write(self, snapshot: Dict, cover_bytes: bytes, lyrics_raw: str) -> None:
        sig = (
            snapshot.get("track_key"),
            snapshot.get("state"),
            int(snapshot.get("position_ms", 0) // 1000),
            snapshot.get("cover_ts", 0),
            len(lyrics_raw or ""),
        )
        if sig == self._last_sig:
            return
        self._last_sig = sig

        try:
            (self.export_dir / "nowplaying.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            title = snapshot.get("title") or "未播放"
            artist = snapshot.get("artist") or ""
            album = snapshot.get("album") or ""
            line2 = " - ".join(x for x in (artist, album) if x)
            text = (
                f"{title}\n"
                f"{line2}\n"
                f"{snapshot.get('position', '0:00')} / {snapshot.get('duration', '0:00')}\n"
                f"状态: {snapshot.get('state_text', '')}\n"
            )
            (self.export_dir / "nowplaying.txt").write_text(text, encoding="utf-8")
            cover_ts = snapshot.get("cover_ts")
            if cover_ts != self._last_cover_ts:
                self._last_cover_ts = cover_ts
                (self.export_dir / "cover.png").write_bytes(cover_bytes)
            if lyrics_raw != self._last_lyrics_raw:
                self._last_lyrics_raw = lyrics_raw
                if lyrics_raw:
                    (self.export_dir / "lyrics.lrc").write_text(lyrics_raw, encoding="utf-8")
        except OSError:
            pass


class StateHub:
    """Collects the current AIMP state and keeps it safe to read from any thread."""

    def __init__(
        self,
        client: AimpClient,
        receiver: AlbumArtReceiver,
        cover_store: CoverStore,
        lyrics_provider: Optional[LyricsProvider] = None,
        export_dir: Optional[Path] = None,
    ) -> None:
        self.client = client
        self.receiver = receiver
        self.cover_store = cover_store
        self.lyrics_provider = lyrics_provider or LyricsProvider()
        self.exporter = Exporter(export_dir) if export_dir else None
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._snapshot: Dict = self._disconnected_snapshot()
        self._last_track_key: Optional[str] = None
        self._want_aimp_art = False
        self._last_aimp_art: Optional[bytes] = None
        self._last_aimp_hwnd: Optional[int] = None

    def snapshot(self) -> Dict:
        with self._lock:
            return dict(self._snapshot)

    def refresh(self) -> Dict:
        """Refresh the AIMP snapshot.

        Both the poller thread and the GUI thread call this; only one refresh runs at a time, the
        other caller gets the most recent snapshot instead of duplicating the (expensive) AIMP,
        cover and lyrics work.
        """
        if not self._refresh_lock.acquire(blocking=False):
            return self.snapshot()
        try:
            return self._refresh()
        finally:
            self._refresh_lock.release()

    def _refresh(self) -> Dict:
        self.client.refresh_handle()
        if not self.client.connected:
            snap = self._disconnected_snapshot()
            with self._lock:
                self._snapshot = snap
            self._export(snap)
            return snap

        if self.client.hwnd != self._last_aimp_hwnd:
            self._last_aimp_hwnd = self.client.hwnd
            if self.receiver.hwnd:
                try:
                    self.client.register_notify(self.receiver.hwnd)
                except AimpError:
                    pass

        try:
            track = self.client.get_track_info()
            state = self.client.get_player_state()
            position = self.client.get_position()
            duration = self.client.get_duration()
            volume = self.client.get_volume()
            muted = self.client.is_muted()
            shuffled = self.client.is_shuffled()
            repeated = self.client.is_repeated()
            version = self.client.get_version()
        except AimpError:
            snap = self._disconnected_snapshot()
            with self._lock:
                self._snapshot = snap
            self._export(snap)
            return snap

        if track is None:
            track_key = "stopped"
            title = artist = album = genre = year = filename = ""
            duration = 0
        else:
            title = str(track.get("title") or "")
            artist = str(track.get("artist") or "")
            album = str(track.get("album") or "")
            genre = str(track.get("genre") or "")
            year = str(track.get("year") or "")
            filename = str(track.get("filename") or "")
            duration = int(track.get("duration") or 0)
            track_key = f"{filename}\x00{title}\x00{artist}\x00{duration}"

        if track_key != self._last_track_key:
            self._last_track_key = track_key
            self._want_aimp_art = True
            if filename and not filename.startswith(("http://", "https://")):
                found = get_cover_for_file(filename)
                if found:
                    data, mime = normalize_to_png(found[0])
                    self.cover_store.update(data, mime)
            if self.receiver.hwnd:
                try:
                    self.client.request_album_art(self.receiver.hwnd)
                except AimpError:
                    pass

        if self._want_aimp_art:
            art = self.receiver.get_art()
            if art and art != self._last_aimp_art:
                self._last_aimp_art = art
                png, _ = normalize_to_png(art)
                self.cover_store.update(png)
                self._want_aimp_art = False

        lyrics = self.lyrics_provider.get(filename, title, artist) if filename else None
        lyrics_current = lyrics_next = ""
        lyrics_full: list = []
        lyrics_words: list = []
        lyrics_synced = False
        lyrics_raw = ""
        if lyrics and lyrics.has_text:
            lyrics_synced = lyrics.synced
            lyrics_raw = lyrics.raw
            if lyrics.synced:
                lyrics_current, lyrics_next = lyrics.group_at(position)
                lyrics_words = lyrics.words_at(position)
                lyrics_full = [ln.text for ln in lyrics.lines]
            else:
                lyrics_full = lyrics.unsynced_lines

        state_name = {0: "stopped", 1: "paused", 2: "playing"}.get(state, "stopped")
        state_text = {"stopped": "未在播放", "paused": "已暂停", "playing": "播放中"}[state_name]
        progress = (position / duration) if duration > 0 else 0.0
        version_text = f"{version[0]:.2f} (build {version[1]})" if version else ""

        snap = {
            "connected": True,
            "state": state_name,
            "state_text": state_text,
            "title": title,
            "artist": artist,
            "album": album,
            "genre": genre,
            "year": year,
            "filename": filename,
            "position_ms": int(position),
            "duration_ms": int(duration),
            "position": format_time(position),
            "duration": format_time(duration),
            "progress": round(max(0.0, min(1.0, progress)), 4),
            "volume": int(volume),
            "muted": bool(muted),
            "shuffle": bool(shuffled),
            "repeat": bool(repeated),
            "track_key": track_key,
            "lyrics_synced": lyrics_synced,
            "lyrics_words": lyrics_words,
            "lyrics_current": lyrics_current,
            "lyrics_next": lyrics_next,
            "lyrics_full": lyrics_full,
            "lyrics_raw": lyrics_raw,
            "cover_ts": self.cover_store.timestamp,
            "aimp_version": version_text,
            "updated_at": time.time(),
        }
        with self._lock:
            self._snapshot = snap
        self._export(snap)
        return snap

    def _export(self, snap: Dict) -> None:
        if not self.exporter:
            return
        cover, _mime, _ts = self.cover_store.get()
        self.exporter.write(snap, cover, snap.get("lyrics_raw", ""))

    @staticmethod
    def _disconnected_snapshot() -> Dict:
        return {
            "connected": False,
            "state": "stopped",
            "state_text": "未检测到 AIMP",
            "title": "",
            "artist": "",
            "album": "",
            "genre": "",
            "year": "",
            "filename": "",
            "position_ms": 0,
            "duration_ms": 0,
            "position": "0:00",
            "duration": "0:00",
            "progress": 0.0,
            "volume": 0,
            "muted": False,
            "shuffle": False,
            "repeat": False,
            "track_key": "",
            "lyrics_synced": False,
            "lyrics_words": [],
            "lyrics_current": "",
            "lyrics_next": "",
            "lyrics_full": [],
            "cover_ts": 0,
            "aimp_version": "",
            "updated_at": time.time(),
        }
