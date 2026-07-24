from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace
from typing import Any

import httpx
from openai import BadRequestError, RateLimitError
import pytest

from ebm_backend.online_pipeline.infrastructure.llm import client as client_module
from ebm_backend.online_pipeline.infrastructure.llm.client import (
    LLMAPIError,
    MAX_CONCURRENT_LLM_CALLS,
    OPENAI_MAX_RETRIES,
    call_llm_json,
    parse_json_object,
    response_text,
)


CHAT_RESPONSE = {"choices": [{"message": {"content": '{"ok": true}'}}]}
RESPONSES_RESPONSE = {
    "status": "completed",
    "output": [
        {
            "type": "message",
            "content": [{"type": "output_text", "text": '{"ok": true}'}],
        }
    ],
}


class _Endpoint:
    def __init__(self, default_response: dict[str, Any]) -> None:
        self.default_response = default_response
        self.calls: list[dict[str, Any]] = []
        self.effects: list[Any] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        effect = self.effects.pop(0) if self.effects else self.default_response
        if isinstance(effect, BaseException):
            raise effect
        return effect


class _FakeClient:
    def __init__(self) -> None:
        self.responses_endpoint = _Endpoint(RESPONSES_RESPONSE)
        self.chat_endpoint = _Endpoint(CHAT_RESPONSE)
        self.responses = SimpleNamespace(create=self.responses_endpoint.create)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.chat_endpoint.create)
        )


@pytest.fixture
def fake_client(monkeypatch) -> _FakeClient:
    client = _FakeClient()
    monkeypatch.setattr(client_module, "_openai_client", lambda config: client)
    return client


def _config(api_mode: str) -> dict[str, Any]:
    return {
        "api_key": "test-key",
        "base_url": "https://example.test/v1",
        "model": "test-model",
        "api_mode": api_mode,
    }


def _status_error(
    *,
    status_code: int,
    message: str,
    request_id: str = "req-test",
    retry_after: str | None = None,
) -> BadRequestError | RateLimitError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    headers = {"x-request-id": request_id}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    response = httpx.Response(status_code, request=request, headers=headers)
    body = {"message": message, "type": "invalid_request_error"}
    if status_code == 429:
        return RateLimitError(message, response=response, body=body)
    return BadRequestError(message, response=response, body=body)


@pytest.mark.parametrize(
    ("status_code", "message", "expected"),
    [
        (None, "Request timed out.", "provider_timeout"),
        (500, "dial tcp upstream: connect: connection refused", "provider_upstream_connection_error"),
        (500, "internal server error", "provider_server_error"),
        (429, "too many requests", "provider_rate_limited"),
        (401, "invalid token", "provider_authentication_error"),
        (400, "invalid request", "provider_request_rejected"),
    ],
)
def test_provider_failures_have_stable_diagnostic_codes(
    status_code: int | None,
    message: str,
    expected: str,
) -> None:
    assert client_module._provider_failure_code(
        status_code=status_code,
        provider_message=message,
    ) == expected


def test_responses_is_default_and_omits_unspecified_temperature(fake_client) -> None:
    result = call_llm_json(
        config={
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
        },
        system="system",
        prompt="original prompt",
    )

    assert result == {"ok": True}
    payload = fake_client.responses_endpoint.calls[0]
    assert payload["instructions"].endswith(
        "Return a valid JSON (json) object."
    )
    assert payload["input"] == (
        "original prompt\n\nReturn a valid JSON (json) object."
    )
    assert payload["store"] is False
    assert payload["text"] == {"format": {"type": "json_object"}}
    assert "temperature" not in payload
    assert not fake_client.chat_endpoint.calls


def test_json_call_reports_normalized_provider_usage(fake_client) -> None:
    fake_client.responses_endpoint.default_response = {
        **RESPONSES_RESPONSE,
        "id": "resp-123",
        "model": "provider-model",
        "usage": {
            "input_tokens": 120,
            "output_tokens": 34,
            "total_tokens": 154,
            "input_tokens_details": {"cached_tokens": 20},
            "output_tokens_details": {"reasoning_tokens": 12},
        },
    }
    metadata: dict[str, Any] = {}

    result = call_llm_json(
        config=_config("responses"),
        system="system",
        prompt="prompt",
        metadata_sink=metadata.update,
    )

    assert result == {"ok": True}
    assert metadata["response_id"] == "resp-123"
    assert metadata["model"] == "provider-model"
    assert metadata["usage"] == {
        "input_tokens": 120,
        "output_tokens": 34,
        "total_tokens": 154,
        "cached_input_tokens": 20,
        "reasoning_tokens": 12,
    }


def test_responses_json_call_maps_schema_tools_and_budgets_and_omits_temperature(
    fake_client,
) -> None:
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    result = call_llm_json(
        config=_config("responses"),
        system="system",
        prompt="prompt",
        temperature=0,
        tools=[{"type": "web_search"}],
        max_output_tokens=8192,
        reasoning_effort="low",
        json_schema=schema,
        json_schema_name="result",
    )

    assert result == {"ok": True}
    payload = fake_client.responses_endpoint.calls[0]
    assert "temperature" not in payload
    assert payload["tools"] == [{"type": "web_search"}]
    assert payload["max_output_tokens"] == 8192
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["text"] == {
        "format": {
            "type": "json_schema",
            "name": "result",
            "schema": schema,
            "strict": True,
        }
    }


def test_chat_json_call_marks_first_user_message_and_maps_parameters(fake_client) -> None:
    result = call_llm_json(
        config=_config("chat"),
        system="system",
        prompt="original prompt",
        temperature=0,
        max_output_tokens=8192,
        reasoning_effort="low",
    )

    assert result == {"ok": True}
    payload = fake_client.chat_endpoint.calls[0]
    assert payload["messages"] == [
        {
            "role": "system",
            "content": "system\n\nReturn a valid JSON (json) object.",
        },
        {
            "role": "user",
            "content": "original prompt\n\nReturn a valid JSON (json) object.",
        },
    ]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["temperature"] == 0
    assert payload["max_completion_tokens"] == 8192
    assert payload["reasoning_effort"] == "low"
    assert payload["store"] is False


def test_chat_json_call_passes_strict_json_schema(fake_client) -> None:
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    result = call_llm_json(
        config=_config("chat"),
        system="system",
        prompt="prompt",
        json_schema=schema,
        json_schema_name="result",
    )

    assert result == {"ok": True}
    assert fake_client.chat_endpoint.calls[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "result",
            "schema": schema,
            "strict": True,
        },
    }


@pytest.mark.parametrize("api_mode", ["auto", "response"])
def test_legacy_aliases_resolve_once_to_responses(fake_client, api_mode) -> None:
    assert call_llm_json(
        config=_config(api_mode),
        system="system",
        prompt="prompt",
    ) == {"ok": True}

    assert len(fake_client.responses_endpoint.calls) == 1
    assert not fake_client.chat_endpoint.calls


def test_chat_mode_rejects_responses_tools(fake_client) -> None:
    with pytest.raises(ValueError, match="only with api_mode='responses'"):
        call_llm_json(
            config=_config("chat"),
            system="system",
            prompt="prompt",
            tools=[{"type": "web_search"}],
        )

    assert not fake_client.chat_endpoint.calls


def test_official_sdk_client_is_cached_and_owns_technical_retries(monkeypatch) -> None:
    constructed: list[dict[str, Any]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            constructed.append(kwargs)

    client_module._cached_openai_client.cache_clear()
    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAI)
    try:
        first = client_module._openai_client(_config("responses"))
        second = client_module._openai_client(_config("chat"))
    finally:
        client_module._cached_openai_client.cache_clear()

    assert first is second
    assert constructed == [
        {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "max_retries": OPENAI_MAX_RETRIES,
        }
    ]


def test_llm_calls_have_one_process_wide_concurrency_limit(monkeypatch) -> None:
    lock = Lock()
    release = Event()
    active = 0
    peak = 0

    def fake_chat_call(**kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == MAX_CONCURRENT_LLM_CALLS:
                release.set()
        assert release.wait(timeout=1)
        with lock:
            active -= 1
        return '{"ok": true}'

    monkeypatch.setattr(client_module, "_openai_client", lambda config: object())
    monkeypatch.setattr(client_module, "_call_chat_text", fake_chat_call)
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_LLM_CALLS * 2) as executor:
        results = list(
            executor.map(
                lambda _: call_llm_json(
                    config=_config("chat"),
                    system="system",
                    prompt="prompt",
                ),
                range(MAX_CONCURRENT_LLM_CALLS * 2),
            )
        )

    assert all(result == {"ok": True} for result in results)
    assert peak == MAX_CONCURRENT_LLM_CALLS == 32


def test_sdk_response_objects_are_supported() -> None:
    class SDKResponse:
        def model_dump(self) -> dict[str, Any]:
            return RESPONSES_RESPONSE

    assert response_text(SDKResponse()) == '{"ok": true}'


def test_empty_provider_envelope_is_not_stringified_as_model_json() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "no complete text; finish_reason='length'; completion_tokens=4608; "
            "reasoning_tokens=4608"
        ),
    ):
        response_text(
            {
                "choices": [
                    {"message": {"content": None}, "finish_reason": "length"}
                ],
                "usage": {
                    "completion_tokens": 4608,
                    "completion_tokens_details": {"reasoning_tokens": 4608},
                },
            }
        )
    with pytest.raises(ValueError, match="contained no text"):
        parse_json_object("")


def test_provider_incomplete_error_and_refusal_are_preserved() -> None:
    with pytest.raises(ValueError, match="incomplete; reason='max_output_tokens'"):
        response_text(
            {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [],
            }
        )
    with pytest.raises(ValueError, match="refused.*policy refusal"):
        response_text(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "refusal": "policy refusal",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        )


def test_chat_retries_only_exact_missing_json_marker_400_once(fake_client) -> None:
    marker_error = _status_error(
        status_code=400,
        message=(
            "Response input messages must contain the word 'json' in some form "
            "to use 'response.format' of type 'json_object'."
        ),
    )
    fake_client.chat_endpoint.effects = [marker_error, CHAT_RESPONSE]

    result = call_llm_json(
        config=_config("chat"),
        system="system",
        prompt="prompt",
    )

    assert result == {"ok": True}
    assert len(fake_client.chat_endpoint.calls) == 2
    assert fake_client.chat_endpoint.calls[0] == fake_client.chat_endpoint.calls[1]


def test_responses_retries_only_exact_missing_json_marker_400_once(fake_client) -> None:
    marker_error = _status_error(
        status_code=400,
        message=(
            "Response input messages must contain the word 'json' in some form "
            "to use 'response.format' of type 'json_object'."
        ),
    )
    fake_client.responses_endpoint.effects = [marker_error, RESPONSES_RESPONSE]

    result = call_llm_json(
        config=_config("responses"),
        system="system",
        prompt="prompt",
    )

    assert result == {"ok": True}
    assert len(fake_client.responses_endpoint.calls) == 2
    assert (
        fake_client.responses_endpoint.calls[0]
        == fake_client.responses_endpoint.calls[1]
    )


def test_json_marker_retry_can_be_delegated_to_the_owning_method(fake_client) -> None:
    marker_error = _status_error(
        status_code=400,
        message=(
            "Response input messages must contain the word 'json' in some form "
            "to use 'response.format' of type 'json_object'."
        ),
    )
    fake_client.responses_endpoint.effects = [marker_error, RESPONSES_RESPONSE]

    with pytest.raises(LLMAPIError) as raised:
        call_llm_json(
            config={
                **_config("responses"),
                "json_marker_retry_enabled": False,
            },
            system="system",
            prompt="prompt",
        )

    assert len(fake_client.responses_endpoint.calls) == 1
    assert raised.value.status_code == 400
    assert raised.value.retryable is True


def test_ordinary_bad_request_is_not_retried(fake_client) -> None:
    fake_client.chat_endpoint.effects = [
        _status_error(status_code=400, message="unsupported response schema")
    ]

    with pytest.raises(LLMAPIError) as raised:
        call_llm_json(
            config=_config("chat"),
            system="system",
            prompt="prompt",
        )

    assert len(fake_client.chat_endpoint.calls) == 1
    assert raised.value.status_code == 400
    assert raised.value.request_id == "req-test"
    assert raised.value.retryable is False
    assert "unsupported response schema" in raised.value.provider_message


def test_final_rate_limit_error_preserves_typed_diagnostics(fake_client) -> None:
    fake_client.chat_endpoint.effects = [
        _status_error(
            status_code=429,
            message="rate limit reached",
            retry_after="7",
        )
    ]

    with pytest.raises(LLMAPIError) as raised:
        call_llm_json(
            config=_config("chat"),
            system="system",
            prompt="prompt",
        )

    assert len(fake_client.chat_endpoint.calls) == 1
    assert raised.value.status_code == raised.value.code == 429
    assert raised.value.request_id == "req-test"
    assert raised.value.retry_after_seconds == 7
    assert raised.value.retryable is True
    assert "rate limit reached" in str(raised.value)
