"""Album art extraction and a thread-safe store for the current cover."""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Optional, Tuple

_FOLDER_ART_NAMES = (
    "cover.png", "cover.jpg", "folder.png", "folder.jpg",
    "front.png", "front.jpg", "album.png", "album.jpg",
    "albumart.png", "albumart.jpg", "AlbumArtSmall.jpg",
)


def detect_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    return "image/png"


def extract_embedded_cover(path: Path) -> Optional[Tuple[bytes, str]]:
    """Return (image bytes, mime) extracted from the audio file tags."""
    try:
        from mutagen import File
    except ImportError:
        return None
    try:
        audio = File(path)
        if audio is None:
            return None
        # FLAC / Ogg / Opus
        pictures = getattr(audio, "pictures", None)
        if pictures:
            pic = pictures[0]
            data = getattr(pic, "data", None)
            if data:
                mime = getattr(pic, "mime", None) or detect_mime(bytes(data))
                return bytes(data), mime
        tags = getattr(audio, "tags", None)
        if tags is None:
            return None
        # ID3 APIC (MP3 / AIFF / WAV)
        try:
            from mutagen.id3 import APIC
            for frame in tags.values():
                if isinstance(frame, APIC) and frame.data:
                    return bytes(frame.data), frame.mime or detect_mime(bytes(frame.data))
        except Exception:
            pass
        # MP4 covr
        try:
            covr = tags.get("covr")
            if covr:
                cover = covr[0]
                data = bytes(cover)
                if getattr(cover, "imageformat", None) is not None:
                    try:
                        from mutagen.mp4 import MP4Cover
                        fmt = {
                            MP4Cover.FORMAT_JPEG: "image/jpeg",
                            MP4Cover.FORMAT_PNG: "image/png",
                        }.get(cover.imageformat, "image/png")
                    except Exception:
                        fmt = detect_mime(data)
                else:
                    fmt = detect_mime(data)
                return data, fmt
        except Exception:
            pass
    except Exception:
        return None
    return None


def find_folder_cover(path: Path) -> Optional[Tuple[bytes, str]]:
    try:
        parent = path.parent
    except (OSError, ValueError):
        return None
    for name in _FOLDER_ART_NAMES:
        cand = parent / name
        try:
            if cand.is_file():
                data = cand.read_bytes()
                if data:
                    return data, detect_mime(data)
        except OSError:
            continue
    return None


def normalize_to_png(data: bytes) -> Tuple[bytes, str]:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue(), "image/png"
    except Exception:
        return data, detect_mime(data)


def placeholder_cover_png() -> bytes:
    """Small generated placeholder so the OBS layout stays stable without art."""
    try:
        from PIL import Image, ImageDraw
        size = 600
        img = Image.new("RGBA", (size, size), (24, 26, 34, 255))
        draw = ImageDraw.Draw(img)
        margin = 36
        draw.rounded_rectangle(
            [margin, margin, size - margin, size - margin],
            radius=44,
            outline=(60, 64, 82, 255),
            width=8,
        )
        cx, cy = size // 2, size // 2
        draw.ellipse([cx - 130, cy - 130, cx + 130, cy + 130], fill=(45, 49, 66, 255))
        draw.text((cx - 40, cy - 70), "\u266a", fill=(120, 128, 160, 255))
        draw.text((cx + 10, cy - 10), "\u266a", fill=(120, 128, 160, 255))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return (
            b"\x89PNG\r\n\x1a\n" +
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89" +
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )


class CoverStore:
    """Holds the latest cover bytes; read by the HTTP server and the GUI."""

    def __init__(self) -> None:
        self._data: bytes = placeholder_cover_png()
        self._mime: str = "image/png"
        self._ts: int = 0
        self._lock = threading.Lock()

    def update(self, data: Optional[bytes], mime: str = "image/png") -> None:
        with self._lock:
            if data:
                self._data = data
                self._mime = mime
                self._ts += 1
            else:
                self._data = placeholder_cover_png()
                self._mime = "image/png"
                self._ts += 1

    def get(self) -> Tuple[bytes, str, int]:
        with self._lock:
            return self._data, self._mime, self._ts

    @property
    def timestamp(self) -> int:
        return self._ts


def get_cover_for_file(path: str) -> Optional[Tuple[bytes, str]]:
    if not path or path.startswith(("http://", "https://", "rtmp://")):
        return None
    p = Path(path)
    found = extract_embedded_cover(p)
    if not found:
        found = find_folder_cover(p)
    return found
