"""Album art extraction and a thread-safe store for the current cover."""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

_FOLDER_ART_NAMES = (
    "cover.png", "cover.jpg", "folder.png", "folder.jpg",
    "front.png", "front.jpg", "album.png", "album.jpg",
    "albumart.png", "albumart.jpg", "AlbumArtSmall.jpg",
)

# Downscale target kept for repeated re-renders (window zoom, GUI thumbnail).
_MASTER_PX = 512
# Size/quality of the copy served to the browser source and the mobile page.
_WEB_PX = 512
_WEB_QUALITY = 88


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
        from tinytag import TinyTag
    except ImportError:
        return None
    try:
        tag = TinyTag.get(path, tags=True, duration=False, image=True)
        img = tag.images.any if tag is not None else None
        if img is not None and img.data:
            mime = img.mime_type or detect_mime(img.data)
            return bytes(img.data), mime
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
    mime = detect_mime(data)
    if not data or mime == "image/png":
        # Already canonical: re-encoding a 2000px cover costs hundreds of milliseconds.
        return data, mime
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
        return data, mime


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
        # Rendering a 1400px cover down to a 96px thumbnail costs tens of milliseconds, so it is
        # done once per revision/size instead of on every repaint: the Tk thread must stay free
        # for animations.
        self._render_lock = threading.RLock()
        self._master_ts: int = -1
        self._master = None
        self._warming: int = -1
        self._rounded: Dict[tuple, object] = {}
        self._masks: Dict[tuple, object] = {}
        self._web_ts: int = -1
        self._web: Optional[Tuple[bytes, str]] = None

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
            self.warm(self._ts, self._data)

    def get(self) -> Tuple[bytes, str, int]:
        with self._lock:
            return self._data, self._mime, self._ts

    @property
    def timestamp(self) -> int:
        return self._ts

    # ------------------------------------------------------------- render cache
    def _master_image(self, ts: int, data: bytes):
        """Decoded RGBA cover, pre-shrunk once per revision so later resizes stay cheap."""
        with self._render_lock:
            if self._master_ts == ts:
                return self._master
            master = None
            try:
                from PIL import Image

                img = Image.open(io.BytesIO(data))
                img.load()
                img = img.convert("RGBA")
                # One box-filter pass instead of a LANCZOS resize: much cheaper, and the
                # remaining step down to the requested size still happens with LANCZOS.
                factor = max(1, round(min(img.size) / _MASTER_PX))
                if factor > 1:
                    img = img.reduce(factor)
                master = img
            except Exception:
                master = None
            if self._ts != ts:  # a newer cover arrived while decoding; keep the freshest
                return self._master
            self._master_ts = ts
            self._master = master
            self._rounded.clear()
            if self._warming == ts:
                self._warming = -1
            return master

    def warm(self, ts: Optional[int] = None, data: Optional[bytes] = None) -> None:
        """Decode the current cover on a worker thread so the UI thread only has to scale it."""
        if ts is None or data is None:
            data, _mime, ts = self.get()
        if self._master_ts == ts or ts <= 0:
            return
        self._warming = ts  # set before the thread starts: the UI must not race it
        threading.Thread(
            target=self._master_image, args=(ts, data), daemon=True, name="CoverDecode",
        ).start()

    def web_image(self) -> Tuple[bytes, str]:
        """Downscaled JPEG for the browser source and the phone page (cached per revision).

        The raw artwork can be several megabytes while the pages never show it larger than a few
        hundred pixels; sending the full image costs transfer and client-side decode time.
        """
        data, mime, ts = self.get()
        with self._render_lock:
            if self._web_ts == ts and self._web is not None:
                return self._web
            out: Tuple[bytes, str] = (data, mime)
            try:
                from PIL import Image

                img = self._master_image(ts, data)
                if img is not None:
                    if max(img.size) > _WEB_PX:
                        img = img.copy()
                        img.thumbnail((_WEB_PX, _WEB_PX), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, "JPEG", quality=_WEB_QUALITY, optimize=True)
                    out = (buf.getvalue(), "image/jpeg")
            except Exception:
                out = (data, mime)
            self._web_ts = ts
            self._web = out
            return out

    def rounded_image(self, size: int, radius: int, blocking: bool = True):
        """RGBA image of the current cover, ``size``x``size`` with rounded corners.

        ``None`` when the artwork cannot be decoded; callers fall back to a plain fill. With
        ``blocking=False`` it also returns ``None`` while a background decode is still running,
        so the UI thread can keep showing the previous artwork instead of waiting.
        """
        data, _mime, ts = self.get()
        key = (ts, size, radius)
        if not blocking and self._master_ts != ts and self._warming == ts:
            return None  # a decode for this revision is already running; do not race it
        if not self._render_lock.acquire(blocking=blocking):
            return None
        try:
            if key in self._rounded:
                return self._rounded[key]
            img = None
            try:
                from PIL import Image, ImageDraw, ImageOps

                master = self._master_image(ts, data)
                if master is not None:
                    img = ImageOps.fit(master, (size, size), Image.LANCZOS)
                    mask = self._masks.get((size, radius))
                    if mask is None:
                        mask = Image.new("L", (size, size), 0)
                        ImageDraw.Draw(mask).rounded_rectangle(
                            [0, 0, size - 1, size - 1],
                            radius=max(1, int(radius)), fill=255,
                        )
                        self._masks[(size, radius)] = mask
                    img.putalpha(mask)
            except Exception:
                img = None
            self._rounded[key] = img
            return img
        finally:
            self._render_lock.release()


def get_cover_for_file(path: str) -> Optional[Tuple[bytes, str]]:
    if not path or path.startswith(("http://", "https://", "rtmp://")):
        return None
    p = Path(path)
    found = extract_embedded_cover(p)
    if not found:
        found = find_folder_cover(p)
    return found
