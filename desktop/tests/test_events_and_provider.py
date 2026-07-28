from __future__ import annotations

from pathlib import Path
import tempfile
from unittest.mock import patch

import httpx
import pytest

from app.ai_provider import (
    OpenAICompatibleProvider,
    ProviderError,
    _extract_stream_text,
    _extract_stream_thinking,
    friendly_provider_error,
)
from app.events import EventHub, encode_sse


def test_event_hub_broadcasts_and_encodes_sequence() -> None:
    hub = EventHub()
    assert hub.subscriber_count == 0
    with hub.subscribe() as first, hub.subscribe() as second:
        assert hub.subscriber_count == 2
        event = hub.publish("result_delta", delta="answer")
        assert first.get_nowait() == event
        assert second.get_nowait() == event
    assert hub.subscriber_count == 0
    assert "event: result_delta" in encode_sse(event)
    assert '"delta": "answer"' in encode_sse(event)


def test_stream_extracts_text_and_reasoning() -> None:
    payload = {"choices": [{"delta": {"content": "done", "reasoning_content": "step"}}]}
    assert _extract_stream_text(payload) == "done"
    assert _extract_stream_thinking(payload) == "step"


def test_total_request_timeout_has_a_clear_user_message() -> None:
    error = httpx.ReadTimeout(
        "timed out",
        request=httpx.Request("POST", "http://local/v1/chat/completions"),
    )
    assert "模型请求超时" in friendly_provider_error(error)


def test_extra_body_and_reasoning_effort_are_forwarded_only_when_enabled() -> None:
    fake_stream = []

    class Completions:
        def __init__(self) -> None:
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return fake_stream

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.chat = type("Chat", (), {"completions": Completions()})()

        def close(self) -> None:
            pass

    model = {
        "base_url": "http://local/v1",
        "api_key": "key",
        "model": "vision",
        "max_tokens": 12,
        "reasoning_effort": "high",
    }
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        image = Path(folder) / "x.png"
        image.write_bytes(b"image")
        with patch("app.ai_provider.OpenAI", FakeClient):
            provider = OpenAICompatibleProvider(model)
            list(provider.stream_screenshot({"extra_body_enabled": False, "prompt_template": "p"}, [image]))
            assert "extra_body" not in provider.client.chat.completions.kwargs
            assert provider.client.chat.completions.kwargs["reasoning_effort"] == "high"
            list(provider.stream_screenshot({"extra_body_enabled": True, "extra_body": {"thinking": True}, "prompt_template": "p"}, [image]))
            assert provider.client.chat.completions.kwargs["extra_body"] == {"thinking": True}

            automatic = OpenAICompatibleProvider({**model, "reasoning_effort": ""})
            list(automatic.stream_screenshot({"extra_body_enabled": False, "prompt_template": "p"}, [image]))
            assert "reasoning_effort" not in automatic.client.chat.completions.kwargs


def test_connection_accepts_json_served_as_text_plain() -> None:
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    model = {
        "base_url": "http://local/v1",
        "api_key": "key",
        "model": "vision",
        "timeout_seconds": 3,
    }
    response = httpx.Response(
        200,
        content=b'{"object":"list","data":[{"id":"vision"}]}',
        headers={"content-type": "text/plain"},
        request=httpx.Request("GET", "http://local/v1/models"),
    )
    with patch("app.ai_provider.OpenAI", FakeClient), patch("app.ai_provider.httpx.get", return_value=response):
        provider = OpenAICompatibleProvider(model)
        assert provider.test_connection() == "连接成功，已找到模型 vision"


def test_connection_falls_back_to_minimal_chat_when_models_is_not_json() -> None:
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    model = {
        "base_url": "http://local",
        "api_key": "key",
        "model": "vision",
    }
    models_response = httpx.Response(
        200,
        content=b"<html>landing page</html>",
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", "http://local/v1/models"),
    )
    chat_response = httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
        request=httpx.Request("POST", "http://local/v1/chat/completions"),
    )
    with (
        patch("app.ai_provider.OpenAI", FakeClient),
        patch("app.ai_provider.httpx.get", return_value=models_response),
        patch("app.ai_provider.httpx.post", return_value=chat_response) as post,
    ):
        provider = OpenAICompatibleProvider(model)
        message = provider.test_connection()
        assert "连接成功" in message
        assert post.call_args.args[0] == "http://local/v1/chat/completions"


def test_connection_validates_reasoning_effort_and_reports_rejection() -> None:
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    model = {
        "base_url": "http://local/v1",
        "api_key": "key",
        "model": "vision",
        "reasoning_effort": "xhigh",
    }
    models_response = httpx.Response(
        200,
        json={"data": [{"id": "vision"}]},
        request=httpx.Request("GET", "http://local/v1/models"),
    )
    chat_response = httpx.Response(
        400,
        json={"error": {"message": "unsupported value"}},
        request=httpx.Request("POST", "http://local/v1/chat/completions"),
    )
    with (
        patch("app.ai_provider.OpenAI", FakeClient),
        patch("app.ai_provider.httpx.get", return_value=models_response),
        patch("app.ai_provider.httpx.post", return_value=chat_response) as post,
    ):
        provider = OpenAICompatibleProvider(model)
        with pytest.raises(ProviderError, match="不支持思考强度 xhigh"):
            provider.test_connection()
        assert post.call_args.kwargs["json"]["reasoning_effort"] == "xhigh"


def test_connection_reports_authentication_error() -> None:
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    model = {
        "base_url": "http://local/v1",
        "api_key": "bad-key",
        "model": "vision",
    }
    response = httpx.Response(
        401,
        json={"error": {"message": "invalid key"}},
        request=httpx.Request("GET", "http://local/v1/models"),
    )
    with patch("app.ai_provider.OpenAI", FakeClient), patch("app.ai_provider.httpx.get", return_value=response):
        provider = OpenAICompatibleProvider(model)
        with pytest.raises(ProviderError, match="API Key"):
            provider.test_connection()
