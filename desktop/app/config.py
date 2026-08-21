from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any


def executable_dir() -> Path:
    override = os.getenv("SCREEN_ASSISTANT_HOME")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


APP_DIR = executable_dir()
CONFIG_PATH = Path(os.getenv("SCREEN_ASSISTANT_CONFIG", str(APP_DIR / "config.json")))

DEFAULT_SHORTCUTS = {
    "capture_fullscreen": "F1",
    "capture_multi": "F2",
    "capture_region": "F3",
    "submit_buffer": "F4",
    "capture_and_submit": "F5",
    "clear_buffer": "F6",
    "next_profile": "F7",
    "replay_result": "F8",
    "scroll_apps_up": "F9",
    "scroll_apps_down": "F10",
    "increase_app_font": "F11",
    "decrease_app_font": "F12",
}

REASONING_EFFORTS = {"", "none", "minimal", "low", "medium", "high", "xhigh", "max"}
API_MODES = {"auto", "chat_completions", "responses"}
URL_MODES = {"auto", "api_root", "full_endpoint"}
DEFAULT_MAX_TOKENS = 8192


def normalize_base_url(value: Any) -> str:
    """Normalize an OpenAI-compatible API root.

    Most compatible services expose endpoints below ``/v1``. When users paste
    only a scheme and host, use that conventional root while preserving any
    explicit provider-specific path.
    """
    cleaned = str(value or "").strip().rstrip("/")
    if not cleaned:
        return ""
    try:
        from urllib.parse import urlsplit, urlunsplit

        parsed = urlsplit(cleaned)
        if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.path in {"", "/"}:
            return urlunsplit((parsed.scheme, parsed.netloc, "/v1", parsed.query, parsed.fragment))
    except ValueError:
        pass
    return cleaned


def default_config() -> dict[str, Any]:
    model_id = uuid.uuid4().hex
    profile_id = uuid.uuid4().hex
    return {
        "version": 1,
        "device_id": f"pc-{uuid.uuid4().hex[:12]}",
        "device_name": socket.gethostname(),
        "lan": {
            "host": "0.0.0.0",
            "port": 18765,
            "enabled": True,
            "advertise_address": "",
        },
        "ui": {"close_mode": "tray"},
        "replay": {
            "fast_mode": False,
            "chars_per_second": 12,
            "jitter_percent": 15,
        },
        "storage": {"history_dir": str(APP_DIR)},
        "models": [
            {
                "id": model_id,
                "name": "默认模型",
                "base_url": "",
                "api_key": "",
                "model": "",
                "timeout_seconds": 120,
                "max_tokens": DEFAULT_MAX_TOKENS,
                "reasoning_effort": "",
                "api_mode": "auto",
                "url_mode": "auto",
            }
        ],
        "profiles": [
            {
                "id": profile_id,
                "name": "默认配置",
                "model_id": model_id,
                "system_prompt": "",
                "prompt_template": "请分析这些截图并给出清晰、可执行的回答。",
                "language": "auto",
                "extra_body_enabled": False,
                "extra_body": {},
            }
        ],
        "active_profile_id": profile_id,
        "shortcuts": DEFAULT_SHORTCUTS.copy(),
        "paired_devices": [],
    }


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONFIG_PATH
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        defaults = default_config()
        if not self.path.exists():
            return defaults
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return defaults
        if not isinstance(raw, dict):
            return defaults
        merged = deepcopy(defaults)
        merged.update(raw)
        for section in ("lan", "ui", "storage", "shortcuts", "replay"):
            value = defaults[section].copy()
            if isinstance(raw.get(section), dict):
                value.update(raw[section])
            merged[section] = value
        merged["shortcuts"] = {
            action: str(merged["shortcuts"].get(action) or "").strip()
            for action in DEFAULT_SHORTCUTS
        }
        merged["models"] = _sanitize_models(raw.get("models"), defaults["models"])
        merged["profiles"] = _sanitize_profiles(raw.get("profiles"), merged["models"], defaults["profiles"])
        profile_ids = {item["id"] for item in merged["profiles"]}
        if merged.get("active_profile_id") not in profile_ids:
            merged["active_profile_id"] = merged["profiles"][0]["id"]
        if not isinstance(merged.get("paired_devices"), list):
            merged["paired_devices"] = []
        merged["lan"]["port"] = max(1024, min(int(merged["lan"].get("port") or 18765), 65535))
        if merged["ui"].get("close_mode") not in {"tray", "hidden"}:
            merged["ui"]["close_mode"] = "tray"
        merged["replay"]["fast_mode"] = bool(merged["replay"].get("fast_mode", False))
        merged["replay"]["chars_per_second"] = max(
            3, min(int(merged["replay"].get("chars_per_second") or 12), 30)
        )
        merged["replay"]["jitter_percent"] = max(
            0, min(int(merged["replay"].get("jitter_percent") or 15), 40)
        )
        return merged

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self.data, ensure_ascii=False, indent=2)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.path)

    def active_profile(self) -> dict[str, Any]:
        selected = str(self.data.get("active_profile_id") or "")
        return next((item for item in self.data["profiles"] if item["id"] == selected), self.data["profiles"][0])

    def model_for_profile(self, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        current = profile or self.active_profile()
        selected = str(current.get("model_id") or "")
        return next((item for item in self.data["models"] if item["id"] == selected), self.data["models"][0])

    def public_profiles(self) -> list[dict[str, str]]:
        return [{"id": item["id"], "name": item["name"]} for item in self.data["profiles"]]


def parse_extra_body(profile: dict[str, Any]) -> dict[str, Any] | None:
    if not bool(profile.get("extra_body_enabled")):
        return None
    value = profile.get("extra_body")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ValueError("extra_body 必须是有效的 JSON 对象") from exc
    if not isinstance(value, dict):
        raise ValueError("extra_body 必须是 JSON 对象")
    return value


def normalize_reasoning_effort(value: Any) -> str:
    effort = str(value or "").strip().lower()
    if effort not in REASONING_EFFORTS:
        raise ValueError("思考强度必须为自动、none、minimal、low、medium、high、xhigh 或 max")
    return effort


def normalize_api_mode(value: Any) -> str:
    mode = str(value or "auto").strip().lower()
    if mode not in API_MODES:
        raise ValueError("接口格式必须为自动、Chat Completions 或 Responses")
    return mode


def normalize_url_mode(value: Any) -> str:
    mode = str(value or "auto").strip().lower()
    if mode not in URL_MODES:
        raise ValueError("URL 模式必须为自动识别、API 根地址或完整端点 URL")
    return mode


def validate_reasoning_extra_body(
    model: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    effort = normalize_reasoning_effort(model.get("reasoning_effort"))
    extra_body = parse_extra_body(profile)
    if not effort or extra_body is None:
        return
    conflicts: list[str] = []
    if "reasoning_effort" in extra_body:
        conflicts.append("reasoning_effort")
    # Responses uses a nested `reasoning` object. Passing it through
    # extra_body would replace the standard object assembled from the model
    # setting, so it must be treated as the same duplicate configuration.
    if "reasoning" in extra_body:
        conflicts.append("reasoning")
    if conflicts:
        raise ValueError(
            f"思考强度与 extra_body 中的 {', '.join(conflicts)} 重复；"
            "请删除 extra_body 中的该字段，或把模型思考强度设为自动"
        )


def public_remote_settings(data: dict[str, Any]) -> dict[str, Any]:
    models = []
    for item in data.get("models", []):
        models.append(
            {
                "id": item["id"],
                "name": item["name"],
                "base_url": item["base_url"],
                "model": item["model"],
                "timeout_seconds": item["timeout_seconds"],
                "max_tokens": item["max_tokens"],
                "reasoning_effort": normalize_reasoning_effort(item.get("reasoning_effort")),
                "api_mode": normalize_api_mode(item.get("api_mode")),
                "url_mode": normalize_url_mode(item.get("url_mode")),
                "api_key_configured": bool(item.get("api_key")),
            }
        )
    return {
        "models": models,
        "profiles": deepcopy(data.get("profiles", [])),
        "active_profile_id": str(data.get("active_profile_id") or ""),
    }


def normalize_remote_settings(
    current: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    raw_models = payload.get("models")
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_models, list) or not raw_models:
        raise ValueError("至少保留一个模型连接")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError("至少保留一个配置组")

    existing_keys = {
        str(item.get("id")): str(item.get("api_key") or "")
        for item in current.get("models", [])
    }
    models: list[dict[str, Any]] = []
    model_ids: set[str] = set()
    for raw in raw_models:
        if not isinstance(raw, dict):
            raise ValueError("模型连接格式无效")
        model_id = str(raw.get("id") or uuid.uuid4().hex)
        if model_id in model_ids:
            raise ValueError("模型连接 ID 重复")
        model_ids.add(model_id)
        key_action = str(raw.get("api_key_action") or "keep")
        if key_action == "replace":
            api_key = str(raw.get("api_key") or "").strip()
        elif key_action == "clear":
            api_key = ""
        elif key_action == "keep":
            api_key = existing_keys.get(model_id, "")
        else:
            raise ValueError("API Key 操作无效")
        models.append(
            {
                "id": model_id,
                "name": str(raw.get("name") or "模型配置").strip() or "模型配置",
                "base_url": normalize_base_url(raw.get("base_url")),
                "api_key": api_key,
                "model": str(raw.get("model") or "").strip(),
                "timeout_seconds": max(5, min(int(raw.get("timeout_seconds") or 120), 600)),
                "max_tokens": max(1, min(int(raw.get("max_tokens") or DEFAULT_MAX_TOKENS), 131072)),
                "reasoning_effort": normalize_reasoning_effort(raw.get("reasoning_effort")),
                "api_mode": normalize_api_mode(raw.get("api_mode")),
                "url_mode": normalize_url_mode(raw.get("url_mode")),
            }
        )

    profiles: list[dict[str, Any]] = []
    profile_ids: set[str] = set()
    for raw in raw_profiles:
        if not isinstance(raw, dict):
            raise ValueError("配置组格式无效")
        profile_id = str(raw.get("id") or uuid.uuid4().hex)
        if profile_id in profile_ids:
            raise ValueError("配置组 ID 重复")
        profile_ids.add(profile_id)
        model_id = str(raw.get("model_id") or "")
        if model_id not in model_ids:
            raise ValueError("配置组引用的模型连接不存在")
        extra_body = raw.get("extra_body", {})
        if isinstance(extra_body, str):
            try:
                extra_body = json.loads(extra_body or "{}")
            except ValueError as exc:
                raise ValueError("extra_body 必须是有效的 JSON 对象") from exc
        if not isinstance(extra_body, dict):
            raise ValueError("extra_body 必须是 JSON 对象")
        profile = {
            "id": profile_id,
            "name": str(raw.get("name") or "配置").strip() or "配置",
            "model_id": model_id,
            "system_prompt": str(raw.get("system_prompt") or ""),
            "prompt_template": str(raw.get("prompt_template") or ""),
            "language": str(raw.get("language") or "auto"),
            "extra_body_enabled": bool(raw.get("extra_body_enabled", False)),
            "extra_body": extra_body,
        }
        parse_extra_body(profile)
        profiles.append(profile)

    models_by_id = {item["id"]: item for item in models}
    for profile in profiles:
        validate_reasoning_extra_body(models_by_id[profile["model_id"]], profile)

    active_profile_id = str(payload.get("active_profile_id") or current.get("active_profile_id") or "")
    if active_profile_id not in profile_ids:
        active_profile_id = profiles[0]["id"]
    return {
        "models": models,
        "profiles": profiles,
        "active_profile_id": active_profile_id,
    }


def _sanitize_models(raw: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return deepcopy(fallback)
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex),
                "name": str(item.get("name") or "模型配置"),
                "base_url": normalize_base_url(item.get("base_url")),
                "api_key": str(item.get("api_key") or ""),
                "model": str(item.get("model") or ""),
                "timeout_seconds": max(5, min(int(item.get("timeout_seconds") or 120), 600)),
                "max_tokens": max(1, min(int(item.get("max_tokens") or DEFAULT_MAX_TOKENS), 131072)),
                "reasoning_effort": _sanitize_reasoning_effort(item.get("reasoning_effort")),
                "api_mode": _sanitize_api_mode(item.get("api_mode")),
                "url_mode": _sanitize_url_mode(item.get("url_mode")),
            }
        )
    return result or deepcopy(fallback)


def _sanitize_reasoning_effort(value: Any) -> str:
    try:
        return normalize_reasoning_effort(value)
    except ValueError:
        return ""


def _sanitize_api_mode(value: Any) -> str:
    try:
        return normalize_api_mode(value)
    except ValueError:
        return "auto"


def _sanitize_url_mode(value: Any) -> str:
    try:
        return normalize_url_mode(value)
    except ValueError:
        return "auto"


def _sanitize_profiles(raw: Any, models: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return deepcopy(fallback)
    model_ids = {item["id"] for item in models}
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("model_id") or "")
        if model_id not in model_ids:
            model_id = models[0]["id"]
        extra_body = item.get("extra_body", {})
        if not isinstance(extra_body, (dict, str)):
            extra_body = {}
        result.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex),
                "name": str(item.get("name") or "配置"),
                "model_id": model_id,
                "system_prompt": str(item.get("system_prompt") or ""),
                "prompt_template": str(item.get("prompt_template") or ""),
                "language": str(item.get("language") or "auto"),
                "extra_body_enabled": bool(item.get("extra_body_enabled", False)),
                "extra_body": extra_body,
            }
        )
    return result or deepcopy(fallback)
