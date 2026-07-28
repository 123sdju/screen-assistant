from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.config import (
    ConfigStore,
    normalize_base_url,
    normalize_reasoning_effort,
    normalize_remote_settings,
    parse_extra_body,
    public_remote_settings,
    validate_reasoning_extra_body,
)


def test_config_is_portable_and_preserves_plaintext_key() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        path = Path(folder) / "config.json"
        store = ConfigStore(path)
        store.data["models"][0]["api_key"] = "test-key-local"
        store.save()
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["models"][0]["api_key"] == "test-key-local"


def test_replay_options_are_loaded_and_clamped() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        path = Path(folder) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "replay": {
                        "fast_mode": True,
                        "chars_per_second": 999,
                        "jitter_percent": -5,
                    }
                }
            ),
            encoding="utf-8",
        )
        assert ConfigStore(path).data["replay"] == {
            "fast_mode": True,
            "chars_per_second": 30,
            "jitter_percent": 0,
        }


def test_extra_body_is_omitted_when_disabled() -> None:
    assert parse_extra_body({"extra_body_enabled": False, "extra_body": {"x": 1}}) is None


def test_extra_body_accepts_object_and_rejects_array() -> None:
    assert parse_extra_body({"extra_body_enabled": True, "extra_body": '{"enable_thinking": true}'}) == {
        "enable_thinking": True
    }
    with pytest.raises(ValueError):
        parse_extra_body({"extra_body_enabled": True, "extra_body": []})


def test_reasoning_effort_migrates_and_validates_supported_values() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        path = Path(folder) / "config.json"
        path.write_text(
            json.dumps({"models": [{"id": "m", "reasoning_effort": "unknown"}]}),
            encoding="utf-8",
        )
        assert ConfigStore(path).data["models"][0]["reasoning_effort"] == ""
    for effort in ("", "none", "minimal", "low", "medium", "high", "xhigh", "max"):
        assert normalize_reasoning_effort(effort) == effort
    with pytest.raises(ValueError, match="思考强度"):
        normalize_reasoning_effort("extreme")


def test_reasoning_effort_rejects_duplicate_extra_body_field() -> None:
    with pytest.raises(ValueError, match="重复"):
        validate_reasoning_extra_body(
            {"reasoning_effort": "high"},
            {
                "extra_body_enabled": True,
                "extra_body": {"reasoning_effort": "low"},
            },
        )
    validate_reasoning_extra_body(
        {"reasoning_effort": ""},
        {
            "extra_body_enabled": True,
            "extra_body": {"reasoning_effort": "low"},
        },
    )


def test_base_url_adds_v1_only_when_no_path_was_supplied() -> None:
    assert normalize_base_url("https://api.example.com") == "https://api.example.com/v1"
    assert normalize_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    assert normalize_base_url("https://api.example.com/openai") == "https://api.example.com/openai"


def test_remote_settings_never_return_api_key_and_keep_or_replace_it() -> None:
    current = {
        "models": [
            {
                "id": "model-1",
                "name": "Old",
                "base_url": "https://old/v1",
                "api_key": "sk-secret",
                "model": "old-model",
                "timeout_seconds": 120,
                "max_tokens": 2048,
                "reasoning_effort": "high",
            }
        ],
        "profiles": [
            {
                "id": "profile-1",
                "name": "Default",
                "model_id": "model-1",
                "system_prompt": "",
                "prompt_template": "p",
                "language": "auto",
                "extra_body_enabled": False,
                "extra_body": {},
            }
        ],
        "active_profile_id": "profile-1",
    }
    public = public_remote_settings(current)
    assert "sk-secret" not in json.dumps(public)
    assert public["models"][0]["api_key_configured"] is True
    assert public["models"][0]["reasoning_effort"] == "high"

    public["models"][0]["name"] = "Kept"
    kept = normalize_remote_settings(current, public)
    assert kept["models"][0]["api_key"] == "sk-secret"

    public["models"][0]["api_key_action"] = "replace"
    public["models"][0]["api_key"] = "sk-new"
    replaced = normalize_remote_settings(current, public)
    assert replaced["models"][0]["api_key"] == "sk-new"
