"""Local HTTP server that feeds the OBS Browser Source."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from .cover import CoverStore
from .mobile import render_mobile
from .overlay import OverlayConfig, render_gallery, render_overlay


class _Handler(BaseHTTPRequestHandler):
    server_version = "AIMPNowPlaying/1.0"

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html", "/overlay"):
                self._send_text(render_overlay(), "text/html; charset=utf-8")
            elif path in ("/preview", "/themes"):
                self._send_text(render_gallery(), "text/html; charset=utf-8")
            elif path in ("/m", "/mobile"):
                self._send_text(render_mobile(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._send_text(
                    json.dumps(self.server.state_hub.snapshot(), ensure_ascii=False),
                    "application/json; charset=utf-8",
                )
            elif path == "/cover.png":
                data, mime, _ts = self.server.cover_store.get()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            elif path == "/lyrics.lrc":
                raw = self.server.state_hub.snapshot().get("lyrics_raw", "")
                self._send_text(raw or "", "text/plain; charset=utf-8")
            elif path == "/api/config":
                self._send_text(
                    json.dumps(self.server.config.to_dict(), ensure_ascii=False),
                    "application/json; charset=utf-8",
                )
            elif path == "/health":
                self._send_text(json.dumps({"ok": True}), "application/json")
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/api/config":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))
            self.server.config.update_from_dict(data)
            self._send_text(
                json.dumps(self.server.config.to_dict(), ensure_ascii=False),
                "application/json; charset=utf-8",
            )
        except Exception:
            self.send_error(400)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


class OverlayServer:
    def __init__(
        self,
        state_hub,
        cover_store: CoverStore,
        host: str = "127.0.0.1",
        port: int = 8765,
        config: Optional[OverlayConfig] = None,
    ) -> None:
        self.state_hub = state_hub
        self.cover_store = cover_store
        self.host = host
        self.port = port
        self.config = config or OverlayConfig()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host
        return f"http://{host}:{self.port}/"

    def start(self) -> bool:
        if self._httpd:
            return True
        httpd = None
        for attempt in range(20):
            try:
                httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
                break
            except OSError:
                self.port += 1
        if httpd is None:
            return False
        httpd.state_hub = self.state_hub
        httpd.cover_store = self.cover_store
        httpd.config = self.config
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, name="OverlayServer", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._thread = None


def find_free_port(start: int = 8765) -> int:
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start
