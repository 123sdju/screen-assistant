from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Iterator

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, OpenAI

from app.config import (
    normalize_base_url,
    normalize_reasoning_effort,
    parse_extra_body,
    validate_reasoning_extra_body,
)


class ProviderError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(self, model_config: dict[str, Any]) -> None:
        base_url = normalize_base_url(model_config.get("base_url"))
        api_key = str(model_config.get("api_key") or "").strip()
        model = str(model_config.get("model") or "").strip()
        if not base_url:
            raise ProviderError("请填写 Base URL")
        if not api_key:
            raise ProviderError("请填写 API Key")
        if not model:
            raise ProviderError("请填写模型名")
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = int(model_config.get("timeout_seconds") or 120)
        self.max_tokens = int(model_config.get("max_tokens") or 2048)
        self.reasoning_effort = normalize_reasoning_effort(model_config.get("reasoning_effort"))
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=self.timeout_seconds,
            max_retries=1,
        )

    def test_connection(self) -> str:
        """Probe /models while tolerating compatible APIs with bad Content-Type."""
        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code in {401, 403}:
                raise ProviderError("API Key 无效或没有访问权限")
            if response.status_code == 404:
                return self._test_chat_completion("供应商未提供 /models")
            if response.status_code == 429:
                raise ProviderError("供应商限流或额度不足")
            if response.status_code >= 400:
                raise ProviderError(f"供应商返回 HTTP {response.status_code}: {_safe_error_text(response)}")
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                return self._test_chat_completion("/models 未返回 JSON")
            try:
                available = _extract_model_ids(payload)
            except ProviderError:
                return self._test_chat_completion("/models 格式不兼容")
            if self.model in available:
                if self.reasoning_effort:
                    return self._test_chat_completion(
                        f"已找到模型 {self.model}，并验证思考强度 {self.reasoning_effort}"
                    )
                return f"连接成功，已找到模型 {self.model}"
            return self._test_chat_completion(f"模型目录未包含 {self.model}")
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(friendly_provider_error(exc)) from exc

    def _test_chat_completion(self, reason: str) -> str:
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
        }
        if self.reasoning_effort:
            request_body["reasoning_effort"] = self.reasoning_effort
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )
        if response.status_code in {401, 403}:
            raise ProviderError("API Key 无效、已过期，或没有该模型的访问权限")
        if response.status_code == 404:
            raise ProviderError("聊天接口或模型不存在，请检查 Base URL 和模型名")
        if response.status_code == 429:
            raise ProviderError("供应商限流或额度不足")
        if response.status_code >= 400:
            if response.status_code == 400 and self.reasoning_effort:
                raise ProviderError(
                    f"供应商或模型不支持思考强度 {self.reasoning_effort}: "
                    f"{_safe_error_text(response)}"
                )
            raise ProviderError(f"模型测试返回 HTTP {response.status_code}: {_safe_error_text(response)}")
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError("聊天接口返回的不是有效 JSON，请检查 Base URL 是否为 API 根路径") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list):
            raise ProviderError("聊天接口响应格式错误：缺少 choices 数组")
        return f"连接成功，模型 {self.model} 可调用（{reason}，已改用最小聊天请求验证）"

    def stream_screenshot(
        self,
        profile: dict[str, Any],
        image_paths: list[Path],
    ) -> Iterator[tuple[str, str]]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": _messages(profile, image_paths),
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        validate_reasoning_extra_body(
            {"reasoning_effort": self.reasoning_effort},
            profile,
        )
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        extra_body = parse_extra_body(profile)
        if extra_body is not None:
            kwargs["extra_body"] = extra_body
        try:
            stream = self.client.chat.completions.create(**kwargs)
            for chunk in stream:
                payload = chunk.model_dump(mode="json") if hasattr(chunk, "model_dump") else chunk
                yield _extract_stream_text(payload), _extract_stream_thinking(payload)
        except Exception as exc:
            raise ProviderError(friendly_provider_error(exc)) from exc

    def close(self) -> None:
        self.client.close()


def friendly_provider_error(exc: Exception) -> str:
    if isinstance(exc, AuthenticationError):
        return "API Key 无效或没有访问权限"
    if isinstance(exc, APITimeoutError):
        return "模型请求超时，请检查网络或增大超时时间"
    if isinstance(exc, APIConnectionError):
        return "无法连接 Base URL，请检查地址、网络和代理设置"
    if isinstance(exc, httpx.TimeoutException):
        return "模型请求超时，请检查网络或增大超时时间"
    if isinstance(exc, httpx.RequestError):
        return "无法连接 Base URL，请检查地址、网络和代理设置"
    if isinstance(exc, APIStatusError):
        if exc.status_code == 404:
            return "接口或模型不存在，请检查 Base URL 和模型名"
        if exc.status_code == 429:
            return "供应商限流或额度不足"
        return f"供应商返回 HTTP {exc.status_code}: {exc.message}"
    return str(exc) or type(exc).__name__


def _extract_model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        raise ProviderError("/models 返回格式错误：顶层必须是 JSON Object")
    raw_models = payload.get("data", payload.get("models"))
    if not isinstance(raw_models, list):
        raise ProviderError("/models 返回格式错误：缺少 data/models 数组")
    result: list[str] = []
    for item in raw_models:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            identifier = item.get("id", item.get("name"))
            if identifier is not None:
                result.append(str(identifier))
    return result


def _safe_error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if payload.get("message"):
                return str(payload["message"])
            if payload.get("detail"):
                return str(payload["detail"])
    except (json.JSONDecodeError, ValueError):
        pass
    text = response.text.strip()
    return text[:300] if text else "无错误详情"


def _messages(profile: dict[str, Any], image_paths: list[Path]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system_prompt = str(profile.get("system_prompt") or "").strip()
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": str(profile.get("prompt_template") or "").strip()
            or "请分析这些截图并给出清晰、可执行的回答。",
        }
    ]
    for path in image_paths:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content_type = _content_type(path)
        content.append({"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{encoded}"}})
    messages.append({"role": "user", "content": content})
    return messages


def _extract_stream_text(data: Any) -> str:
    return _extract_delta(data, ("content",))


def _extract_stream_thinking(data: Any) -> str:
    return _extract_delta(data, ("reasoning_content", "reasoning", "thinking", "thinking_content"))


def _extract_delta(data: Any, fields: tuple[str, ...]) -> str:
    try:
        delta = data["choices"][0]["delta"]
    except (KeyError, IndexError, TypeError):
        return ""
    parts: list[str] = []
    for field in fields:
        value = delta.get(field) if isinstance(delta, dict) else None
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
    return "".join(parts)


def _content_type(path: Path) -> str:
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".bmp": "image/bmp"}.get(
        path.suffix.lower(), "image/png"
    )
