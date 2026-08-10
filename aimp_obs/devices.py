"""Device approval store for LAN / mobile access.

Mobile access is OFF by default. A device registers with a random id; the GUI
must approve it before the device can read state or send playback commands.
Approved devices receive a token which is required for non-loopback access.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional


class DeviceManager:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else None
        self.enabled: bool = False
        self._lock = threading.Lock()
        self._devices: Dict[str, dict] = {}
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._devices = data
            except (OSError, ValueError):
                self._devices = {}

    # ------------------------------------------------------------- persist
    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._devices, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    # ------------------------------------------------------------- public
    def register(self, device_id: str, name: str = "") -> dict:
        """Register (or return status of) a device. New devices start pending."""
        device_id = (device_id or "").strip()[:64]
        if not device_id:
            return {"ok": False, "error": "invalid id"}
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is not None:
                return {
                    "ok": True,
                    "approved": dev.get("status") == "approved",
                    "pending": dev.get("status") == "pending",
                    "rejected": dev.get("status") == "rejected",
                    "token": dev.get("token", "") if dev.get("status") == "approved" else "",
                }
            dev = {
                "id": device_id,
                "name": (name or "移动设备").strip()[:40] or "移动设备",
                "token": secrets.token_urlsafe(24),
                "status": "pending",
                "created_at": time.time(),
                "approved_at": None,
            }
            self._devices[device_id] = dev
            self._save()
            return {"ok": True, "approved": False, "pending": True, "rejected": False, "token": ""}

    def status(self, device_id: str) -> dict:
        with self._lock:
            dev = self._devices.get((device_id or "").strip())
            if dev is None:
                return {"known": False}
            return {
                "known": True,
                "approved": dev.get("status") == "approved",
                "pending": dev.get("status") == "pending",
                "rejected": dev.get("status") == "rejected",
                "token": dev.get("token", "") if dev.get("status") == "approved" else "",
            }

    def approve(self, device_id: str) -> bool:
        with self._lock:
            dev = self._devices.get((device_id or "").strip())
            if dev is None:
                return False
            dev["status"] = "approved"
            dev["approved_at"] = time.time()
            self._save()
            return True

    def reject(self, device_id: str) -> bool:
        with self._lock:
            dev = self._devices.get((device_id or "").strip())
            if dev is None:
                return False
            dev["status"] = "rejected"
            self._save()
            return True

    def remove(self, device_id: str) -> bool:
        with self._lock:
            key = (device_id or "").strip()
            if key not in self._devices:
                return False
            del self._devices[key]
            self._save()
            return True

    def pending(self) -> List[dict]:
        with self._lock:
            return [dict(d) for d in self._devices.values() if d.get("status") == "pending"]

    def approved(self) -> List[dict]:
        with self._lock:
            return [dict(d) for d in self._devices.values() if d.get("status") == "approved"]

    def all(self) -> List[dict]:
        with self._lock:
            return [dict(d) for d in self._devices.values()]

    def check_token(self, token: str) -> Optional[str]:
        """Return the device id if the token belongs to an approved device."""
        if not token:
            return None
        with self._lock:
            for dev in self._devices.values():
                if dev.get("status") == "approved" and secrets.compare_digest(str(dev.get("token", "")), token):
                    return dev.get("id")
        return None
