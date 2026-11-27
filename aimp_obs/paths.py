"""Path helpers that work both from source and from a PyInstaller onefile exe."""

from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def icon_path() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller onefile: bundled data lives in _MEIPASS
        bundle = Path(getattr(sys, "_MEIPASS", app_root()))
        return bundle / "assets" / "icon.ico"
    return app_root() / "assets" / "icon.ico"


def webui_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", app_root()))
        return bundle / "aimp_obs" / "webui"
    return Path(__file__).resolve().parent / "webui"
