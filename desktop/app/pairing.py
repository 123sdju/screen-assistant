from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from typing import Any

from app.config import ConfigStore


class PairingError(RuntimeError):
    pass


class PairingManager:
    def __init__(self, config: ConfigStore, ttl_seconds: int = 120) -> None:
        self.config = config
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._code = ""
        self._expires_at = 0.0

    def issue_code(self) -> tuple[str, int]:
        with self._lock:
            self._code = f"{secrets.randbelow(1_000_000):06d}"
            self._expires_at = time.time() + self.ttl_seconds
            return self._code, int(self._expires_at)

    def pair(self, code: str, device_id: str, device_name: str) -> dict[str, str]:
        now = time.time()
        with self._lock:
            if not self._code or now >= self._expires_at or not hmac.compare_digest(str(code), self._code):
                raise PairingError("配对码无效或已过期")
            self._code = ""
            self._expires_at = 0.0
        token = secrets.token_urlsafe(32)
        token_hash = self.hash_token(token)
        devices = [item for item in self.config.data.get("paired_devices", []) if item.get("device_id") != device_id]
        devices.append(
            {
                "device_id": device_id,
                "device_name": device_name or "Android App",
                "token_hash": token_hash,
                "paired_at": int(now),
            }
        )
        self.config.data["paired_devices"] = devices
        self.config.save()
        return {"token": token, "device_id": device_id, "desktop_id": self.config.data["device_id"]}

    def authenticate(self, token: str) -> dict[str, Any] | None:
        candidate = self.hash_token(token)
        for device in self.config.data.get("paired_devices", []):
            if hmac.compare_digest(str(device.get("token_hash") or ""), candidate):
                return device
        return None

    def revoke(self, device_id: str) -> bool:
        devices = self.config.data.get("paired_devices", [])
        remaining = [item for item in devices if item.get("device_id") != device_id]
        if len(remaining) == len(devices):
            return False
        self.config.data["paired_devices"] = remaining
        self.config.save()
        return True

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
