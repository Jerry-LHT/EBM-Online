"""Small LLM JSON-call helper for online-pipeline methods and benchmarks."""

from __future__ import annotations

import json
import re
import ssl
import urllib.request
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.config import LLMConfig


def call_llm_json(
    *,
    config: LLMConfig | dict[str, Any],
    system: str,
    prompt: str,
    model: str | None = None,
    timeout_seconds: float | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Call the configured LLM and parse a JSON object response."""

    normalized = _normalize_config(config)
    api_mode = str(normalized.get("api_mode") or "responses").strip().lower()
    selected_model = model or str(normalized["model"])
    timeout = float(timeout_seconds if timeout_seconds is not None else normalized.get("timeout_seconds") or 180)
    temp = float(temperature if temperature is not None else normalized.get("temperature") or 0)
    if api_mode == "responses":
        content = _call_responses_text(
            config=normalized,
            system=system,
            prompt=prompt,
            model=selected_model,
            timeout_seconds=timeout,
            temperature=temp,
        )
    elif api_mode == "chat":
        content = _call_chat_text(
            config=normalized,
            system=system,
            prompt=prompt,
            model=selected_model,
            timeout_seconds=timeout,
            temperature=temp,
        )
    else:
        raise ValueError("LLM api_mode must be one of: responses, chat")
    return parse_json_object(content)


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = _extract_json_object_text(text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = json.loads(_extract_first_balanced_json_object(text))
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object")
    return parsed


def response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        output_text = response.get("output_text")
        if isinstance(output_text, str):
            return output_text
        chunks: list[str] = []
        for item in response.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content_item in item.get("content") or []:
                if isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                    chunks.append(content_item["text"])
        if chunks:
            return "\n".join(chunks)
        choices = response.get("choices") or []
        if choices:
            message = (choices[0] or {}).get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content
    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
    return str(response)


def _normalize_config(config: LLMConfig | dict[str, Any]) -> dict[str, Any]:
    if isinstance(config, LLMConfig):
        return config.to_dict()
    return dict(config)


def _call_responses_text(
    *,
    config: dict[str, Any],
    system: str,
    prompt: str,
    model: str,
    timeout_seconds: float,
    temperature: float,
) -> str:
    payload = {
        "model": model,
        "instructions": system,
        "input": prompt,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        str(config["base_url"]).rstrip("/") + "/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds, context=_ssl_context()) as raw_response:
        data = json.loads(raw_response.read().decode("utf-8"))
    return response_text(data)


def _call_chat_text(
    *,
    config: dict[str, Any],
    system: str,
    prompt: str,
    model: str,
    timeout_seconds: float,
    temperature: float,
) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("The openai package is required for chat-mode LLM calls") from exc
    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"], timeout=timeout_seconds)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
    except Exception:
        response = client.chat.completions.create(model=model, messages=messages, temperature=temperature)
    return response_text(response)


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


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())
