from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Iterator

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, OpenAI

from app.config import (
    normalize_base_url,
    normalize_api_mode,
    normalize_reasoning_effort,
    normalize_url_mode,
    parse_extra_body,
    validate_reasoning_extra_body,
)


class ProviderError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(self, model_config: dict[str, Any]) -> None:
        self.url_mode = normalize_url_mode(model_config.get("url_mode"))
        raw_url = str(model_config.get("base_url") or "").strip()
        entered_url = raw_url if self.url_mode == "full_endpoint" else normalize_base_url(raw_url)
        api_key = str(model_config.get("api_key") or "").strip()
        model = str(model_config.get("model") or "").strip()
        if not entered_url:
            raise ProviderError("请填写 Base URL")
        if not api_key:
            raise ProviderError("请填写 API Key")
        if not model:
            raise ProviderError("请填写模型名")
        self.model = model
        resolved_root, detected_mode = _resolve_endpoint(entered_url)
        if self.url_mode == "api_root":
            self.base_url = entered_url.rstrip("/")
            detected_mode = None
        else:
            self.base_url = resolved_root
        self.full_endpoint_url = entered_url if self.url_mode == "full_endpoint" else ""
        configured_mode = normalize_api_mode(model_config.get("api_mode"))
        self.api_mode = detected_mode if configured_mode == "auto" and detected_mode else configured_mode
        if self.full_endpoint_url and self.api_mode == "auto":
            raise ProviderError("完整端点 URL 使用自定义路径时，请明确选择 Chat Completions 或 Responses")
        self.api_key = api_key
        self.timeout_seconds = int(model_config.get("timeout_seconds") or 120)
        self.max_tokens = int(model_config.get("max_tokens") or 2048)
        self.reasoning_effort = normalize_reasoning_effort(model_config.get("reasoning_effort"))
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=api_key,
            timeout=self.timeout_seconds,
            max_retries=1,
        )

    def test_connection(self) -> str:
        """Validate the selected generation endpoint with a minimal request."""
        try:
            modes = self._candidate_modes()
            for index, mode in enumerate(modes):
                try:
                    return self._test_completion(mode)
                except _EndpointUnavailable:
                    if index + 1 == len(modes):
                        raise ProviderError("生成接口不存在，请检查 Base URL 和接口格式")
            raise ProviderError("没有可用的生成接口")
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(friendly_provider_error(exc)) from exc

    def _test_completion(self, mode: str) -> str:
        if mode == "responses":
            endpoint = "responses"
            request_body: dict[str, Any] = {
                "model": self.model,
                "input": "Reply with OK.",
                "stream": False,
                "max_output_tokens": min(self.max_tokens, 32),
            }
            if self.reasoning_effort:
                request_body["reasoning"] = {"effort": self.reasoning_effort}
        else:
            endpoint = "chat/completions"
            request_body = {
                "model": self.model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "stream": False,
                "max_tokens": min(self.max_tokens, 32),
            }
            if self.reasoning_effort:
                request_body["reasoning_effort"] = self.reasoning_effort
        response = httpx.post(
            self._endpoint_url(mode),
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
        if response.status_code in {404, 405, 501} or (
            response.status_code == 400 and _suggests_responses_endpoint(_safe_error_text(response))
        ):
            raise _EndpointUnavailable()
        if response.status_code == 429:
            raise ProviderError("供应商限流或额度不足")
        if response.status_code >= 400:
            if response.status_code == 400 and self.reasoning_effort:
                raise ProviderError(
                    f"供应商或模型不支持思考强度 {self.reasoning_effort}: "
                    f"{_safe_error_text(response)}"
                )
            raise ProviderError(f"{_mode_label(mode)} 测试返回 HTTP {response.status_code}: {_safe_error_text(response)}")
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(f"{_mode_label(mode)} 返回的不是有效 JSON") from exc
        if not _valid_test_payload(payload, mode):
            expected = "output/output_text" if mode == "responses" else "choices"
            raise ProviderError(f"{_mode_label(mode)} 响应格式错误：缺少 {expected}")
        return f"连接成功，模型 {self.model} 可通过 {_mode_label(mode)} 调用"

    def stream_screenshot(
        self,
        profile: dict[str, Any],
        image_paths: list[Path],
    ) -> Iterator[tuple[str, str]]:
        validate_reasoning_extra_body(
            {"reasoning_effort": self.reasoning_effort},
            profile,
        )
        extra_body = parse_extra_body(profile)
        modes = self._candidate_modes()
        for index, mode in enumerate(modes):
            emitted = False
            try:
                for text, thinking in self._stream_mode(mode, profile, image_paths, extra_body):
                    if text or thinking:
                        emitted = True
                        yield text, thinking
                return
            except Exception as exc:
                if not emitted and index + 1 < len(modes) and _is_endpoint_unavailable(exc):
                    continue
                raise ProviderError(friendly_provider_error(exc)) from exc

    def _candidate_modes(self) -> list[str]:
        if self.api_mode == "auto":
            return ["chat_completions", "responses"]
        return [self.api_mode]

    def _endpoint_url(self, mode: str) -> str:
        if self.full_endpoint_url:
            return self.full_endpoint_url
        endpoint = "responses" if mode == "responses" else "chat/completions"
        return f"{self.base_url}/{endpoint}"

    def _stream_mode(
        self,
        mode: str,
        profile: dict[str, Any],
        image_paths: list[Path],
        extra_body: dict[str, Any] | None,
    ) -> Iterator[tuple[str, str]]:
        if self.full_endpoint_url:
            yield from self._stream_full_endpoint(
                mode,
                profile,
                image_paths,
                extra_body,
            )
            return
        if mode == "responses":
            kwargs: dict[str, Any] = {
                "model": self.model,
                "input": _responses_input(profile, image_paths),
                "max_output_tokens": self.max_tokens,
                "stream": True,
            }
            system_prompt = str(profile.get("system_prompt") or "").strip()
            if system_prompt:
                kwargs["instructions"] = system_prompt
            if self.reasoning_effort:
                kwargs["reasoning"] = {"effort": self.reasoning_effort}
            if extra_body is not None:
                kwargs["extra_body"] = extra_body
            stream = self.client.responses.create(**kwargs)
            for event in stream:
                payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else event
                yield _extract_response_stream_text(payload), _extract_response_stream_thinking(payload)
            return

        kwargs = {
            "model": self.model,
            "messages": _messages(profile, image_paths),
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if extra_body is not None:
            kwargs["extra_body"] = extra_body
        stream = self.client.chat.completions.create(**kwargs)
        for chunk in stream:
            payload = chunk.model_dump(mode="json") if hasattr(chunk, "model_dump") else chunk
            yield _extract_stream_text(payload), _extract_stream_thinking(payload)

    def _stream_full_endpoint(
        self,
        mode: str,
        profile: dict[str, Any],
        image_paths: list[Path],
        extra_body: dict[str, Any] | None,
    ) -> Iterator[tuple[str, str]]:
        if mode == "responses":
            body: dict[str, Any] = {
                "model": self.model,
                "input": _responses_input(profile, image_paths),
                "max_output_tokens": self.max_tokens,
                "stream": True,
            }
            system_prompt = str(profile.get("system_prompt") or "").strip()
            if system_prompt:
                body["instructions"] = system_prompt
            if self.reasoning_effort:
                body["reasoning"] = {"effort": self.reasoning_effort}
        else:
            body = {
                "model": self.model,
                "messages": _messages(profile, image_paths),
                "max_tokens": self.max_tokens,
                "stream": True,
            }
            if self.reasoning_effort:
                body["reasoning_effort"] = self.reasoning_effort
        if extra_body is not None:
            body.update(extra_body)
        with httpx.stream(
            "POST",
            self.full_endpoint_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "text/event-stream, application/json",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as response:
            if response.status_code >= 400:
                response.read()
                raise ProviderError(
                    f"{_mode_label(mode)} 返回 HTTP {response.status_code}: "
                    f"{_safe_error_text(response)}"
                )
            for payload in _iter_stream_payloads(response.iter_lines()):
                if mode == "responses":
                    yield (
                        _extract_response_stream_text(payload),
                        _extract_response_stream_thinking(payload),
                    )
                else:
                    yield _extract_stream_text(payload), _extract_stream_thinking(payload)

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


def _responses_input(profile: dict[str, Any], image_paths: list[Path]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": str(profile.get("prompt_template") or "").strip()
            or "请分析这些截图并给出清晰、可执行的回答。",
        }
    ]
    for path in image_paths:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{_content_type(path)};base64,{encoded}",
            }
        )
    return [{"role": "user", "content": content}]


def _extract_stream_text(data: Any) -> str:
    delta = _extract_delta(data, ("content",))
    if delta:
        return delta
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    return content if isinstance(content, str) else ""


def _extract_stream_thinking(data: Any) -> str:
    return _extract_delta(data, ("reasoning_content", "reasoning", "thinking", "thinking_content"))


def _extract_response_stream_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    event_type = str(data.get("type") or "")
    if event_type in {"response.output_text.delta", "response.text.delta"}:
        return _string_delta(data.get("delta"))
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    output = data.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict) or not isinstance(item.get("content"), list):
                continue
            for content in item["content"]:
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        if parts:
            return "".join(parts)
    return _extract_stream_text(data)


def _extract_response_stream_thinking(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    event_type = str(data.get("type") or "")
    if event_type in {
        "response.reasoning_summary_text.delta",
        "response.reasoning_text.delta",
        "response.reasoning.delta",
    }:
        return _string_delta(data.get("delta"))
    return _extract_stream_thinking(data)


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


class _EndpointUnavailable(RuntimeError):
    pass


def _resolve_endpoint(url: str) -> tuple[str, str | None]:
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    lower = path.lower()
    detected: str | None = None
    if lower.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
        detected = "chat_completions"
    elif lower.endswith("/responses"):
        path = path[: -len("/responses")]
        detected = "responses"
    root = urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)).rstrip("/")
    return root, detected


def _mode_label(mode: str) -> str:
    return "Responses" if mode == "responses" else "Chat Completions"


def _valid_test_payload(payload: Any, mode: str) -> bool:
    if not isinstance(payload, dict):
        return False
    if mode == "responses":
        return isinstance(payload.get("output"), list) or isinstance(payload.get("output_text"), str)
    return isinstance(payload.get("choices"), list)


def _string_delta(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"]
    return ""


def _iter_stream_payloads(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith(":"):
            continue
        data = line[5:].strip() if line.startswith("data:") else line
        if data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(payload, dict):
            yield payload


def _is_endpoint_unavailable(exc: Exception) -> bool:
    if not isinstance(exc, APIStatusError):
        return False
    if exc.status_code in {404, 405, 501}:
        return True
    return exc.status_code == 400 and _suggests_responses_endpoint(str(exc.message))


def _suggests_responses_endpoint(message: str) -> bool:
    lowered = message.lower()
    return "responses" in lowered and any(
        marker in lowered for marker in ("endpoint", "use ", "unsupported", "not supported")
    )
