from __future__ import annotations

from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIStatusError, NotFoundError

from app.ai_provider import (
    OpenAICompatibleProvider,
    ProviderError,
    _extract_response_stream_text,
    _extract_response_stream_thinking,
    _extract_stream_text,
    _extract_stream_thinking,
    _resolve_endpoint,
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
    assert _extract_response_stream_text(
        {"type": "response.output_text.delta", "delta": "answer"}
    ) == "answer"
    assert _extract_response_stream_text(
        {
            "type": "response.completed",
            "response": {
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "answer"}]}
                ]
            },
        }
    ) == "answer"
    assert _extract_response_stream_thinking(
        {"type": "response.reasoning_summary_text.delta", "delta": "reason"}
    ) == "reason"


@pytest.mark.parametrize(
    ("entered", "root", "mode"),
    [
        ("https://api.example.com/v1", "https://api.example.com/v1", None),
        (
            "https://api.example.com/v1/chat/completions",
            "https://api.example.com/v1",
            "chat_completions",
        ),
        (
            "https://api.example.com/chat/completions",
            "https://api.example.com",
            "chat_completions",
        ),
        (
            "https://api.example.com/v1/responses",
            "https://api.example.com/v1",
            "responses",
        ),
    ],
)
def test_full_generation_endpoints_are_resolved_without_duplicate_paths(
    entered: str, root: str, mode: str | None
) -> None:
    assert _resolve_endpoint(entered) == (root, mode)


def test_total_request_timeout_has_a_clear_user_message() -> None:
    error = httpx.ReadTimeout(
        "timed out",
        request=httpx.Request("POST", "http://local/v1/chat/completions"),
    )
    assert "模型请求超时" in friendly_provider_error(error)


def test_extra_body_and_reasoning_effort_are_forwarded_only_when_enabled() -> None:
    fake_stream = [{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}]

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
        "api_mode": "chat_completions",
    }
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        image = Path(folder) / "x.png"
        image.write_bytes(b"image")
        with patch("app.ai_provider.OpenAI", FakeClient):
            provider = OpenAICompatibleProvider(model)
            list(provider.stream_screenshot({"extra_body_enabled": False, "prompt_template": "p"}, [image]))
            assert "extra_body" not in provider.client.chat.completions.kwargs
            assert provider.client.chat.completions.kwargs["reasoning_effort"] == "high"
            assert provider.client.chat.completions.kwargs["max_completion_tokens"] == 12
            assert "max_tokens" not in provider.client.chat.completions.kwargs
            list(provider.stream_screenshot({"extra_body_enabled": True, "extra_body": {"thinking": True}, "prompt_template": "p"}, [image]))
            assert provider.client.chat.completions.kwargs["extra_body"] == {"thinking": True}

            automatic = OpenAICompatibleProvider({**model, "reasoning_effort": ""})
            list(automatic.stream_screenshot({"extra_body_enabled": False, "prompt_template": "p"}, [image]))
            assert "reasoning_effort" not in automatic.client.chat.completions.kwargs


def test_auto_mode_prefers_responses_only_for_active_reasoning() -> None:
    base = {
        "base_url": "http://local/v1",
        "api_key": "key",
        "model": "reasoning-compatible",
        "api_mode": "auto",
    }
    with patch("app.ai_provider.OpenAI", lambda **_kwargs: None):
        assert OpenAICompatibleProvider({**base, "reasoning_effort": "high"})._candidate_modes() == [
            "responses",
            "chat_completions",
        ]
        assert OpenAICompatibleProvider({**base, "reasoning_effort": "none"})._candidate_modes() == [
            "chat_completions",
            "responses",
        ]


def test_stream_rejects_empty_output_instead_of_marking_task_complete() -> None:
    class Completions:
        def create(self, **_kwargs):
            return [{"choices": [{"delta": {}, "finish_reason": "stop"}]}]

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.chat = type("Chat", (), {"completions": Completions()})()

        def close(self) -> None:
            pass

    with patch("app.ai_provider.OpenAI", FakeClient):
        provider = OpenAICompatibleProvider(
            {
                "base_url": "http://local/v1",
                "api_key": "key",
                "model": "empty-compatible",
                "api_mode": "chat_completions",
            }
        )
        with pytest.raises(ProviderError, match="可见回答"):
            list(
                provider.stream_screenshot(
                    {"prompt_template": "prompt", "extra_body_enabled": False},
                    [],
                )
            )


def test_chat_stream_falls_back_to_legacy_token_limit_when_provider_rejects_modern_field() -> None:
    bad_response = httpx.Response(
        400,
        json={"error": {"message": "unsupported parameter max_completion_tokens"}},
        request=httpx.Request("POST", "http://local/v1/chat/completions"),
    )

    class Completions:
        def __init__(self) -> None:
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise APIStatusError(
                    "unsupported parameter max_completion_tokens",
                    response=bad_response,
                    body=None,
                )
            return [{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}]

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.completions = Completions()
            self.chat = type("Chat", (), {"completions": self.completions})()

        def close(self) -> None:
            pass

    with patch("app.ai_provider.OpenAI", FakeClient):
        provider = OpenAICompatibleProvider(
            {
                "base_url": "http://local/v1",
                "api_key": "key",
                "model": "legacy-compatible",
                "max_tokens": 2048,
                "api_mode": "chat_completions",
            }
        )
        chunks = list(
            provider.stream_screenshot(
                {"prompt_template": "prompt", "extra_body_enabled": False},
                [],
            )
        )

    assert chunks == [("ok", "")]
    assert provider.client.completions.calls[0]["max_completion_tokens"] == 2048
    assert provider.client.completions.calls[1]["max_tokens"] == 2048


def test_responses_summary_falls_back_when_provider_does_not_support_it() -> None:
    bad_response = httpx.Response(
        400,
        json={"error": {"message": "reasoning summary is unsupported"}},
        request=httpx.Request("POST", "http://local/v1/responses"),
    )

    class Responses:
        def __init__(self) -> None:
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise APIStatusError(
                    "reasoning summary is unsupported",
                    response=bad_response,
                    body=None,
                )
            return [{"type": "response.output_text.delta", "delta": "ok"}]

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.responses = Responses()

        def close(self) -> None:
            pass

    with patch("app.ai_provider.OpenAI", FakeClient):
        provider = OpenAICompatibleProvider(
            {
                "base_url": "http://local/v1/responses",
                "api_key": "key",
                "model": "reasoning-compatible",
                "reasoning_effort": "medium",
            }
        )
        chunks = list(
            provider.stream_screenshot(
                {"prompt_template": "prompt", "extra_body_enabled": False},
                [],
            )
        )

    assert chunks == [("ok", "")]
    assert provider.client.responses.calls[0]["reasoning"] == {
        "effort": "medium",
        "summary": "auto",
    }
    assert provider.client.responses.calls[1]["reasoning"] == {"effort": "medium"}


def test_stream_rejects_incomplete_responses_instead_of_marking_them_complete() -> None:
    class Responses:
        def create(self, **_kwargs):
            return [
                {
                    "type": "response.incomplete",
                    "response": {
                        "status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"},
                    },
                }
            ]

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.responses = Responses()

        def close(self) -> None:
            pass

    with patch("app.ai_provider.OpenAI", FakeClient):
        provider = OpenAICompatibleProvider(
            {
                "base_url": "http://local/v1/responses",
                "api_key": "key",
                "model": "reasoning-compatible",
                "reasoning_effort": "high",
            }
        )
        with pytest.raises(ProviderError, match="响应未完成"):
            list(
                provider.stream_screenshot(
                    {"prompt_template": "prompt", "extra_body_enabled": False},
                    [],
                )
            )


def test_stream_rejects_chat_length_finish_reason() -> None:
    class Completions:
        def create(self, **_kwargs):
            return [{"choices": [{"delta": {}, "finish_reason": "length"}]}]

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.chat = type("Chat", (), {"completions": Completions()})()

        def close(self) -> None:
            pass

    with patch("app.ai_provider.OpenAI", FakeClient):
        provider = OpenAICompatibleProvider(
            {
                "base_url": "http://local/v1",
                "api_key": "key",
                "model": "chat-compatible",
                "api_mode": "chat_completions",
            }
        )
        with pytest.raises(ProviderError, match="token 上限"):
            list(
                provider.stream_screenshot(
                    {"prompt_template": "prompt", "extra_body_enabled": False},
                    [],
                )
            )


def test_connection_validates_the_real_generation_endpoint() -> None:
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
        content=b'{"choices":[{"message":{"content":"OK"}}]}',
        headers={"content-type": "text/plain"},
        request=httpx.Request("POST", "http://local/v1/chat/completions"),
    )
    with patch("app.ai_provider.OpenAI", FakeClient), patch("app.ai_provider.httpx.post", return_value=response):
        provider = OpenAICompatibleProvider(model)
        assert "Chat Completions" in provider.test_connection()


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
        "api_mode": "chat_completions",
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
    with patch("app.ai_provider.OpenAI", FakeClient), patch("app.ai_provider.httpx.post", return_value=response):
        provider = OpenAICompatibleProvider(model)
        with pytest.raises(ProviderError, match="API Key"):
            provider.test_connection()


def test_responses_endpoint_uses_multimodal_shape_and_stream_events() -> None:
    class Responses:
        def __init__(self) -> None:
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return [
                {"type": "response.reasoning_summary_text.delta", "delta": "step"},
                {"type": "response.output_text.delta", "delta": "done"},
            ]

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.responses = Responses()

        def close(self) -> None:
            pass

    model = {
        "base_url": "http://local/v1/responses",
        "api_key": "key",
        "model": "vision",
        "reasoning_effort": "high",
    }
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        image = Path(folder) / "x.png"
        image.write_bytes(b"image")
        with patch("app.ai_provider.OpenAI", FakeClient):
            provider = OpenAICompatibleProvider(model)
            chunks = list(
                provider.stream_screenshot(
                    {
                        "system_prompt": "system",
                        "prompt_template": "prompt",
                        "extra_body_enabled": True,
                        "extra_body": {"custom": True},
                    },
                    [image],
                )
            )
        assert chunks == [("", "step"), ("done", "")]
        kwargs = provider.client.responses.kwargs
        assert kwargs["reasoning"] == {"effort": "high", "summary": "auto"}
        assert kwargs["instructions"] == "system"
        assert kwargs["extra_body"] == {"custom": True}
        assert kwargs["input"][0]["content"][0] == {"type": "input_text", "text": "prompt"}
        assert kwargs["input"][0]["content"][1]["type"] == "input_image"


def test_responses_connection_test_uses_responses_url_and_payload() -> None:
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    response = httpx.Response(
        200,
        json={
            "id": "resp_1",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "OK"}],
                }
            ],
        },
        request=httpx.Request("POST", "http://local/v1/responses"),
    )
    model = {
        "base_url": "http://local/v1/responses",
        "api_key": "key",
        "model": "vision",
        "reasoning_effort": "low",
    }
    with (
        patch("app.ai_provider.OpenAI", FakeClient),
        patch("app.ai_provider.httpx.post", return_value=response) as post,
    ):
        provider = OpenAICompatibleProvider(model)
        assert "Responses" in provider.test_connection()
        assert post.call_args.args[0] == "http://local/v1/responses"
        assert post.call_args.kwargs["json"]["reasoning"] == {
            "effort": "low",
            "summary": "auto",
        }


def test_connection_rejects_completed_responses_without_visible_output() -> None:
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    response = httpx.Response(
        200,
        json={"id": "resp_1", "status": "completed", "output": []},
        request=httpx.Request("POST", "http://local/v1/responses"),
    )
    model = {
        "base_url": "http://local/v1/responses",
        "api_key": "key",
        "model": "vision",
    }
    with patch("app.ai_provider.OpenAI", FakeClient), patch(
        "app.ai_provider.httpx.post", return_value=response
    ):
        provider = OpenAICompatibleProvider(model)
        with pytest.raises(ProviderError, match="没有可见输出"):
            provider.test_connection()


def test_connection_rejects_chat_output_truncated_by_token_limit() -> None:
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": "partial"},
                    "finish_reason": "length",
                }
            ]
        },
        request=httpx.Request("POST", "http://local/v1/chat/completions"),
    )
    model = {
        "base_url": "http://local/v1",
        "api_key": "key",
        "model": "vision",
        "api_mode": "chat_completions",
    }
    with patch("app.ai_provider.OpenAI", FakeClient), patch(
        "app.ai_provider.httpx.post", return_value=response
    ):
        provider = OpenAICompatibleProvider(model)
        with pytest.raises(ProviderError, match="token 上限"):
            provider.test_connection()


def test_auto_mode_falls_back_from_missing_chat_endpoint_to_responses() -> None:
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    missing_chat = httpx.Response(
        404,
        json={"error": {"message": "not found"}},
        request=httpx.Request("POST", "http://local/v1/chat/completions"),
    )
    responses_ok = httpx.Response(
        200,
        json={
            "id": "resp_1",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "OK"}],
                }
            ],
        },
        request=httpx.Request("POST", "http://local/v1/responses"),
    )
    model = {
        "base_url": "http://local/v1",
        "api_key": "key",
        "model": "vision",
        "api_mode": "auto",
    }
    with (
        patch("app.ai_provider.OpenAI", FakeClient),
        patch(
            "app.ai_provider.httpx.post",
            side_effect=[missing_chat, responses_ok],
        ) as post,
    ):
        provider = OpenAICompatibleProvider(model)
        assert "Responses" in provider.test_connection()
        assert [call.args[0] for call in post.call_args_list] == [
            "http://local/v1/chat/completions",
            "http://local/v1/responses",
        ]


def test_stream_auto_mode_falls_back_only_before_any_content_was_emitted() -> None:
    missing_response = httpx.Response(
        404,
        request=httpx.Request("POST", "http://local/v1/chat/completions"),
    )

    class Completions:
        def create(self, **_kwargs):
            raise NotFoundError("missing", response=missing_response, body=None)

    class Responses:
        def __init__(self) -> None:
            self.called = False

        def create(self, **_kwargs):
            self.called = True
            return [{"type": "response.output_text.delta", "delta": "fallback"}]

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.chat = type("Chat", (), {"completions": Completions()})()
            self.responses = Responses()

        def close(self) -> None:
            pass

    with patch("app.ai_provider.OpenAI", FakeClient):
        provider = OpenAICompatibleProvider(
            {
                "base_url": "http://local/v1",
                "api_key": "key",
                "model": "vision",
                "api_mode": "auto",
            }
        )
        chunks = list(
            provider.stream_screenshot(
                {"prompt_template": "prompt", "extra_body_enabled": False},
                [],
            )
        )
    assert chunks == [("fallback", "")]
    assert provider.client.responses.called is True


def test_full_endpoint_mode_posts_to_the_exact_custom_url() -> None:
    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    exact_url = "https://gateway.example.com/custom/generate?tenant=one"
    response = httpx.Response(
        200,
        content=(
            b'data: {"type":"response.output_text.delta","delta":"exact"}\n\n'
            b"data: [DONE]\n\n"
        ),
        request=httpx.Request("POST", exact_url),
    )
    context = MagicMock()
    context.__enter__.return_value = response
    context.__exit__.return_value = False
    with (
        patch("app.ai_provider.OpenAI", FakeClient),
        patch("app.ai_provider.httpx.stream", return_value=context) as stream,
    ):
        provider = OpenAICompatibleProvider(
            {
                "base_url": exact_url,
                "url_mode": "full_endpoint",
                "api_mode": "responses",
                "api_key": "key",
                "model": "vision",
            }
        )
        chunks = list(
            provider.stream_screenshot(
                {"prompt_template": "prompt", "extra_body_enabled": False},
                [],
            )
        )
    assert chunks == [("exact", "")]
    assert stream.call_args.args[:2] == ("POST", exact_url)


def test_custom_full_endpoint_requires_an_explicit_api_format() -> None:
    with pytest.raises(ProviderError, match="明确选择"):
        OpenAICompatibleProvider(
            {
                "base_url": "https://gateway.example.com/custom/generate",
                "url_mode": "full_endpoint",
                "api_mode": "auto",
                "api_key": "key",
                "model": "vision",
            }
        )
