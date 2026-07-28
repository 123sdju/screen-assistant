from __future__ import annotations

import time
import tempfile
from pathlib import Path

import pytest

from app.config import ConfigStore
from app.pairing import PairingError, PairingManager


def test_pair_code_is_one_time_and_tokens_are_independent() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        store = ConfigStore(Path(folder) / "config.json")
        pairing = PairingManager(store)
        code, _ = pairing.issue_code()
        first = pairing.pair(code, "phone-1", "Phone 1")
        assert pairing.authenticate(first["token"])["device_id"] == "phone-1"
        with pytest.raises(PairingError):
            pairing.pair(code, "phone-2", "Phone 2")
        code, _ = pairing.issue_code()
        second = pairing.pair(code, "phone-2", "Phone 2")
        assert first["token"] != second["token"]
        assert pairing.revoke("phone-1")
        assert pairing.authenticate(first["token"]) is None
        assert pairing.authenticate(second["token"]) is not None


def test_expired_pair_code_is_rejected(monkeypatch) -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        store = ConfigStore(Path(folder) / "config.json")
        pairing = PairingManager(store, ttl_seconds=1)
        code, _ = pairing.issue_code()
        monkeypatch.setattr(time, "time", lambda: 9_999_999_999.0)
        with pytest.raises(PairingError):
            pairing.pair(code, "phone", "Phone")
