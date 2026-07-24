"""OpenAI-compatible JSON client shared by online-pipeline methods."""

from __future__ import annotations

from functools import lru_cache
import json
import re
from threading import BoundedSemaphore
from typing import Any, Callable, Mapping

from openai import APIError, APIStatusError, OpenAI

from ebm_backend.online_pipeline.infrastructure.llm.config import LLMConfig


MAX_CONCURRENT_LLM_CALLS = 32
OPENAI_MAX_RETRIES = 2
_LLM_CALL_SLOTS = BoundedSemaphore(MAX_CONCURRENT_LLM_CALLS)
_JSON_INSTRUCTION = "Return a valid JSON (json) object."


class LLMAPIError(RuntimeError):
    """Stable provider-error contract exposed to online-pipeline callers."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        request_id: str | None,
        retry_after_seconds: float | None,
        retryable: bool,
        provider_message: str,
        failure_code: str = "provider_error",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.retry_after_seconds = retry_after_seconds
        self.retryable = retryable
        self.provider_message = provider_message
        self.failure_code = failure_code

        # Temporary compatibility for method-local retry helpers that used
        # urllib.error.HTTPError attributes before the SDK migration.
        self.code = status_code
        self.headers: Mapping[str, str] = {}


def call_llm_json(
    *,
    config: LLMConfig | dict[str, Any],
    system: str,
    prompt: str,
    model: str | None = None,
    timeout_seconds: float | None = None,
    temperature: float | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_output_tokens: int | None = None,
    reasoning_effort: str | None = None,
    json_schema: dict[str, Any] | None = None,
    json_schema_name: str = "structured_response",
    metadata_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Generate and parse one JSON object through Responses or Chat."""

    normalized = _normalize_config(config)
    api_mode = _normalize_api_mode(normalized.get("api_mode"))
    json_marker_retry_enabled = _config_bool(
        normalized.get("json_marker_retry_enabled", True),
        name="json_marker_retry_enabled",
    )
    selected_model = model or str(normalized["model"])
    timeout = _optional_float(timeout_seconds)
    if timeout is None:
        timeout = _optional_float(normalized.get("timeout_seconds")) or 180.0
    selected_temperature = _optional_float(temperature)
    if temperature is None:
        selected_temperature = _optional_float(normalized.get("temperature"))

    client = _openai_client(normalized)
    with _LLM_CALL_SLOTS:
        if api_mode == "responses":
            content = _call_responses_text(
                client=client,
                system=system,
                prompt=prompt,
                model=selected_model,
                timeout_seconds=timeout,
                temperature=selected_temperature,
                tools=tools,
                max_output_tokens=max_output_tokens,
                reasoning_effort=reasoning_effort,
                json_schema=json_schema,
                json_schema_name=json_schema_name,
                json_marker_retry_enabled=json_marker_retry_enabled,
                metadata_sink=metadata_sink,
            )
        else:
            if tools:
                raise ValueError(
                    "LLM tools are supported only with api_mode='responses'; "
                    "chat mode does not implement tool orchestration"
                )
            content = _call_chat_text(
                client=client,
                system=system,
                prompt=prompt,
                model=selected_model,
                timeout_seconds=timeout,
                temperature=selected_temperature,
                max_output_tokens=max_output_tokens,
                reasoning_effort=reasoning_effort,
                json_schema=json_schema,
                json_schema_name=json_schema_name,
                json_marker_retry_enabled=json_marker_retry_enabled,
                metadata_sink=metadata_sink,
            )
    return parse_json_object(content)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse an object, retaining a bounded compatibility fallback for fences."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("LLM response contained no text")
    candidate = _extract_json_object_text(text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = json.loads(_extract_first_balanced_json_object(text))
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object")
    return parsed


def response_text(response: Any) -> str:
    """Extract assistant text while preserving refusal/incomplete diagnostics."""

    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        model_dump = getattr(response, "model_dump", None)
        if callable(model_dump):
            return response_text(model_dump())
    if isinstance(response, dict):
        status = str(response.get("status") or "").strip().lower()
        if status == "incomplete":
            incomplete = (
                response.get("incomplete_details")
                if isinstance(response.get("incomplete_details"), dict)
                else {}
            )
            raise ValueError(
                "LLM response was incomplete"
                f"; reason={incomplete.get('reason')!r}"
            )
        response_error = response.get("error")
        if isinstance(response_error, dict) and response_error:
            raise ValueError(
                "LLM response reported an error"
                f"; code={response_error.get('code')!r}"
                f"; message={_bounded_text(response_error.get('message'))!r}"
            )
        output_text = response.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        chunks: list[str] = []
        for item in response.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content_item in item.get("content") or []:
                if not isinstance(content_item, dict):
                    continue
                refusal = content_item.get("refusal")
                if isinstance(refusal, str) and refusal.strip():
                    raise ValueError(
                        f"LLM refused the request; refusal={_bounded_text(refusal)!r}"
                    )
                if isinstance(content_item.get("text"), str):
                    chunks.append(content_item["text"])
        if chunks:
            return "\n".join(chunks)

        choices = response.get("choices") or []
        if choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            refusal = message.get("refusal")
            if isinstance(refusal, str) and refusal.strip():
                raise ValueError(
                    f"LLM refused the request; refusal={_bounded_text(refusal)!r}"
                )
            finish_reason = choice.get("finish_reason")
            if finish_reason in {"length", "content_filter"}:
                raise _chat_incomplete_error(response=response, finish_reason=finish_reason)
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                content_chunks = [
                    str(part.get("text"))
                    for part in content
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                ]
                if content_chunks:
                    return "\n".join(content_chunks)
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        raise _chat_incomplete_error(
            response=response,
            finish_reason=choice.get("finish_reason"),
        )

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content
    raise ValueError("LLM response contained no complete text")


def response_metadata(
    response: Any,
    *,
    api_mode: str,
    model: str,
) -> dict[str, Any]:
    """Extract provider usage without changing the parsed-JSON return contract."""

    payload = _response_mapping(response)
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    input_details = (
        usage.get("input_tokens_details")
        if isinstance(usage.get("input_tokens_details"), dict)
        else usage.get("prompt_tokens_details")
        if isinstance(usage.get("prompt_tokens_details"), dict)
        else {}
    )
    output_details = (
        usage.get("output_tokens_details")
        if isinstance(usage.get("output_tokens_details"), dict)
        else usage.get("completion_tokens_details")
        if isinstance(usage.get("completion_tokens_details"), dict)
        else {}
    )
    request_id = _first_text(
        getattr(response, "_request_id", None),
        getattr(response, "request_id", None),
        payload.get("request_id"),
    )
    return {
        "api_mode": api_mode,
        "model": str(payload.get("model") or model),
        "response_id": _first_text(payload.get("id")),
        "request_id": request_id,
        "status": _first_text(payload.get("status")),
        "usage": {
            "input_tokens": _first_int(
                usage.get("input_tokens"), usage.get("prompt_tokens")
            ),
            "output_tokens": _first_int(
                usage.get("output_tokens"), usage.get("completion_tokens")
            ),
            "total_tokens": _first_int(usage.get("total_tokens")),
            "cached_input_tokens": _first_int(
                input_details.get("cached_tokens"),
                input_details.get("cached_input_tokens"),
            ),
            "reasoning_tokens": _first_int(
                output_details.get("reasoning_tokens")
            ),
        },
    }


def _emit_response_metadata(
    sink: Callable[[dict[str, Any]], None] | None,
    metadata: dict[str, Any],
) -> None:
    if sink is None:
        return
    try:
        sink(metadata)
    except Exception:
        # Observability must not turn a valid provider response into a failed call.
        return


def _response_mapping(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        value = model_dump()
        return value if isinstance(value, dict) else {}
    return {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_config(config: LLMConfig | dict[str, Any]) -> dict[str, Any]:
    if isinstance(config, LLMConfig):
        return config.to_dict()
    return dict(config)


def _normalize_api_mode(value: Any) -> str:
    normalized = str(value or "responses").strip().lower()
    if normalized in {"response", "auto"}:
        return "responses"
    if normalized not in {"responses", "chat"}:
        raise ValueError(
            "LLM api_mode must be one of: responses, chat, auto "
            "('response' is accepted as an alias for 'responses')"
        )
    return normalized


def _config_bool(value: Any, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"{name} must be boolean")


@lru_cache(maxsize=16)
def _cached_openai_client(
    *,
    api_key: str,
    base_url: str,
    max_retries: int = OPENAI_MAX_RETRIES,
) -> OpenAI:
    """Reuse the official SDK client and its HTTP connection pool."""

    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=max_retries,
    )


def _openai_client(config: dict[str, Any]) -> OpenAI:
    max_retries = int(config.get("sdk_max_retries", OPENAI_MAX_RETRIES))
    if max_retries < 0:
        raise ValueError("sdk_max_retries must be zero or greater")
    return _cached_openai_client(
        api_key=str(config["api_key"]),
        base_url=str(config.get("base_url") or "https://api.openai.com/v1").rstrip("/"),
        max_retries=max_retries,
    )


def _call_responses_text(
    *,
    client: Any,
    system: str,
    prompt: str,
    model: str,
    timeout_seconds: float,
    temperature: float | None,
    tools: list[dict[str, Any]] | None,
    max_output_tokens: int | None,
    reasoning_effort: str | None,
    json_schema: dict[str, Any] | None,
    json_schema_name: str,
    json_marker_retry_enabled: bool,
    metadata_sink: Callable[[dict[str, Any]], None] | None,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "instructions": _with_json_instruction(system),
        "input": _with_json_instruction(prompt),
        "store": False,
        "text": _responses_text_format(
            json_schema=json_schema,
            json_schema_name=json_schema_name,
        ),
        "timeout": timeout_seconds,
    }
    # Responses model families and OpenAI-compatible gateways do not expose a
    # uniform temperature capability.  Omitting it lets the selected model use
    # its supported default and avoids a retry changing routes and failing with
    # an unsupported-parameter response.
    if tools:
        payload["tools"] = tools
    if max_output_tokens is not None:
        payload["max_output_tokens"] = int(max_output_tokens)
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}

    response = _create_with_json_marker_retry(
        create=client.responses.create,
        payload=payload,
        enabled=json_marker_retry_enabled,
    )
    _emit_response_metadata(
        metadata_sink,
        response_metadata(response, api_mode="responses", model=model),
    )
    return response_text(response)


def _call_chat_text(
    *,
    client: Any,
    system: str,
    prompt: str,
    model: str,
    timeout_seconds: float,
    temperature: float | None,
    max_output_tokens: int | None,
    reasoning_effort: str | None,
    json_schema: dict[str, Any] | None,
    json_schema_name: str,
    json_marker_retry_enabled: bool,
    metadata_sink: Callable[[dict[str, Any]], None] | None,
) -> str:
    # This Chat-only compatibility marker must be in the first user message.
    # One deployed gateway ignores later user messages while validating JSON
    # mode and intermittently rejects otherwise valid requests.
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _with_json_instruction(system)},
            {"role": "user", "content": _with_json_instruction(prompt)},
        ],
        "response_format": _chat_response_format(
            json_schema=json_schema,
            json_schema_name=json_schema_name,
        ),
        "store": False,
        "timeout": timeout_seconds,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_output_tokens is not None:
        payload["max_completion_tokens"] = int(max_output_tokens)
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    response = _create_with_json_marker_retry(
        create=client.chat.completions.create,
        payload=payload,
        enabled=json_marker_retry_enabled,
    )
    _emit_response_metadata(
        metadata_sink,
        response_metadata(response, api_mode="chat", model=model),
    )
    return response_text(response)


def _create_with_json_marker_retry(
    *, create: Any, payload: dict[str, Any], enabled: bool
) -> Any:
    """Retry once only for the deployed gateway's false JSON-marker 400."""

    try:
        return create(**payload)
    except APIStatusError as error:
        if not _is_missing_json_marker_error(error):
            raise _llm_api_error(error) from error
        if not enabled:
            wrapped = _llm_api_error(error)
            # This exact gateway error is known to be transient.  When the
            # compatibility retry is disabled, let the owning method spend its
            # one explicit retry instead of hiding another provider call here.
            wrapped.retryable = True
            raise wrapped from error
        try:
            return create(**payload)
        except APIError as retry_error:
            raise _llm_api_error(retry_error) from retry_error
    except APIError as error:
        raise _llm_api_error(error) from error


def _responses_text_format(
    *,
    json_schema: dict[str, Any] | None,
    json_schema_name: str,
) -> dict[str, Any]:
    if json_schema is None:
        return {"format": {"type": "json_object"}}
    return {
        "format": {
            "type": "json_schema",
            "name": json_schema_name,
            "schema": json_schema,
            "strict": True,
        }
    }


def _chat_response_format(
    *,
    json_schema: dict[str, Any] | None,
    json_schema_name: str,
) -> dict[str, Any]:
    if json_schema is None:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": json_schema_name,
            "schema": json_schema,
            "strict": True,
        },
    }


def _with_json_instruction(text: str) -> str:
    return text.rstrip() + f"\n\n{_JSON_INSTRUCTION}"


def _is_missing_json_marker_error(error: APIStatusError) -> bool:
    if getattr(error, "status_code", None) != 400:
        return False
    message = _provider_error_message(error).lower()
    return (
        "must contain" in message
        and "json" in message
        and ("json_object" in message or "response_format" in message or ".format" in message)
    )


def _llm_api_error(error: APIError) -> LLMAPIError:
    status_code = getattr(error, "status_code", None)
    request_id = getattr(error, "request_id", None)
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after_seconds = _retry_after_seconds(headers.get("Retry-After"))
    retryable = status_code is None or status_code in {408, 409, 429} or status_code >= 500
    provider_message = _provider_error_message(error)
    failure_code = _provider_failure_code(
        status_code=status_code,
        provider_message=provider_message,
    )
    status = f" status={status_code}" if status_code is not None else ""
    request = f" request_id={request_id}" if request_id else ""
    wrapped = LLMAPIError(
        f"LLM provider request failed;{status}{request}; {provider_message}",
        status_code=status_code,
        request_id=request_id,
        retry_after_seconds=retry_after_seconds,
        retryable=retryable,
        provider_message=provider_message,
        failure_code=failure_code,
    )
    wrapped.headers = headers
    return wrapped


def _provider_failure_code(
    *,
    status_code: int | None,
    provider_message: str,
) -> str:
    message = provider_message.lower()
    if status_code == 408 or "timed out" in message or "timeout" in message:
        return "provider_timeout"
    if status_code == 429:
        return "provider_rate_limited"
    if status_code in {401, 403}:
        return "provider_authentication_error"
    if any(
        marker in message
        for marker in (
            "connection refused",
            "connect: connection",
            "dial tcp",
            "connection reset",
            "broken pipe",
            " eof",
        )
    ):
        return "provider_upstream_connection_error"
    if status_code is not None and status_code >= 500:
        return "provider_server_error"
    if status_code is not None and 400 <= status_code < 500:
        return "provider_request_rejected"
    return "provider_transport_error"


def _provider_error_message(error: APIError) -> str:
    body = getattr(error, "body", None)
    detail: Any = body
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        detail = body["error"]
    if isinstance(detail, dict):
        parts = [
            str(detail.get(name) or "").strip()
            for name in ("message", "type", "param", "code")
            if str(detail.get(name) or "").strip()
        ]
        if parts:
            return _bounded_text(" | ".join(parts))
    if detail not in (None, ""):
        return _bounded_text(detail)
    return _bounded_text(error)


def _retry_after_seconds(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def _chat_incomplete_error(*, response: dict[str, Any], finish_reason: Any) -> ValueError:
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    details = (
        usage.get("completion_tokens_details")
        if isinstance(usage.get("completion_tokens_details"), dict)
        else {}
    )
    return ValueError(
        "LLM response contained no complete text"
        f"; finish_reason={finish_reason!r}"
        f"; completion_tokens={usage.get('completion_tokens')!r}"
        f"; reasoning_tokens={details.get('reasoning_tokens')!r}"
    )


def _bounded_text(value: Any, *, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _extract_json_object_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if not match:
        return stripped
    return match.group(0)


def _extract_first_balanced_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    start = stripped.find("{")
    if start < 0:
        return stripped

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]
    return stripped[start:]
