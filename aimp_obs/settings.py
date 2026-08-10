"""Persistent user settings (overlay style, port, refresh, export dir)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .overlay import OverlayConfig


def default_settings_path() -> Path:
    override = os.environ.get("AIMP_SETTINGS_PATH")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "AIMP-OBS-NowPlaying" / "settings.json"


class SettingsStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else default_settings_path()
        self.port: int = 8765
        self.refresh_ms: int = 300
        self.export_dir: str = ""
        self.floating_lyric_font_anim: bool = True
        self.mobile_enabled: bool = False
        self.overlay = OverlayConfig()
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        try:
            self.port = int(data.get("port", self.port))
        except (TypeError, ValueError):
            pass
        try:
            self.refresh_ms = max(100, int(data.get("refresh_ms", self.refresh_ms)))
        except (TypeError, ValueError):
            pass
        export_dir = data.get("export_dir")
        if isinstance(export_dir, str) and export_dir.strip():
            self.export_dir = export_dir.strip()
        if isinstance(data.get("floating_lyric_font_anim"), bool):
            self.floating_lyric_font_anim = data["floating_lyric_font_anim"]
        if isinstance(data.get("mobile_enabled"), bool):
            self.mobile_enabled = data["mobile_enabled"]
        overlay_data = data.get("overlay")
        if isinstance(overlay_data, dict):
            self.overlay.update_from_dict(overlay_data)

    def save(self) -> None:
        data: Dict[str, Any] = {
            "port": self.port,
            "refresh_ms": self.refresh_ms,
            "export_dir": self.export_dir,
            "floating_lyric_font_anim": self.floating_lyric_font_anim,
            "mobile_enabled": self.mobile_enabled,
            "overlay": self.overlay.to_dict(),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass
