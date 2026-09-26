"""CoverStore render cache: revision handling, non-blocking contract, corner rounding."""

import io
import threading
import time

from PIL import Image, ImageDraw

from aimp_obs.cover import CoverStore, normalize_to_png


def _png(size=64, color=(200, 30, 40)):
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, "PNG")
    return buf.getvalue()


def test_rounded_image_is_cached_per_revision():
    store = CoverStore()
    store.update(_png(color=(10, 20, 30)))
    store._master_image(*_current(store))  # build the master synchronously

    first = store.rounded_image(96, 10)
    assert first is not None and first.size == (96, 96)
    assert store.rounded_image(96, 10) is first  # same revision/size -> cached object

    other_size = store.rounded_image(48, 10)
    assert other_size is not first and other_size.size == (48, 48)


def test_new_cover_invalidates_cached_render():
    store = CoverStore()
    store.update(_png(color=(10, 20, 30)))
    store._master_image(*_current(store))
    first = store.rounded_image(96, 10)

    store.update(_png(color=(240, 220, 10)))
    store._master_image(*_current(store))
    second = store.rounded_image(96, 10)

    assert second is not first
    assert second.getpixel((48, 48)) != first.getpixel((48, 48))


def test_rounded_corners_are_transparent():
    store = CoverStore()
    store.update(_png())
    store._master_image(*_current(store))
    img = store.rounded_image(96, 20)

    assert img.mode == "RGBA"
    assert img.getpixel((48, 48))[3] == 255  # centre opaque
    assert img.getpixel((0, 0))[3] == 0  # corner rounded away


def test_non_blocking_render_returns_none_while_decoding():
    """The UI must never wait for a cover decode in flight."""
    store = CoverStore()
    store.update(_png(size=512))
    started = threading.Event()
    release = threading.Event()

    def holder():
        with store._render_lock:
            started.set()
            release.wait(5)

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert started.wait(2)

    assert store.rounded_image(96, 10, blocking=False) is None
    release.set()
    thread.join(5)
    # once the decoder is free the render goes through
    assert store.rounded_image(96, 10) is not None


def test_warm_decodes_master_off_thread():
    store = CoverStore()
    store.update(_png(size=1024))
    for _ in range(100):
        if store._master_ts == store.timestamp:
            break
        time.sleep(0.02)
    assert store._master_ts == store.timestamp
    assert max(store._master.size) <= 512


def _noise_png(size: int) -> bytes:
    img = Image.effect_noise((size, size), 100).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_web_image_is_downscaled_and_cached():
    """The browser source must not be handed a multi-megabyte cover."""
    store = CoverStore()
    store.update(_noise_png(1500))
    first = store.web_image()
    data, mime = first
    assert mime == "image/jpeg"
    assert data.startswith(b"\xff\xd8\xff")
    assert len(data) < 200_000  # source is several MB
    assert store.web_image() is first  # cached for the same revision

    store.update(_noise_png(1500))
    assert store.web_image()[0] != data


def test_web_image_falls_back_to_raw_bytes():
    store = CoverStore()
    store.update(b"definitely not an image")
    data, mime = store.web_image()
    assert data == b"definitely not an image"
    assert mime == "image/png"


def test_normalize_keeps_png_bytes_untouched():
    png = _png(64)
    assert normalize_to_png(png) == (png, "image/png")
    assert normalize_to_png(b"") == (b"", "image/png")


def test_normalize_converts_other_formats():
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(buf, "JPEG")
    data, mime = normalize_to_png(buf.getvalue())
    assert mime == "image/png"
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


def _current(store):
    data, _mime, ts = store.get()
    return ts, data
