"""LLM provider configuration loaded from local JSON."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_LLM_CONFIG_PATH = "llm.local.json"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_API_MODE = "responses"
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_TEMPERATURE: float | None = None
DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
DEFAULT_SCREENING_INPUT_TOKEN_BUDGET = 48_000


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    api_mode: str = DEFAULT_API_MODE
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    temperature: float | None = DEFAULT_TEMPERATURE
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS
    screening_input_token_budget: int = DEFAULT_SCREENING_INPUT_TOKEN_BUDGET
    source_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "api_mode": self.api_mode,
            "timeout_seconds": self.timeout_seconds,
            "temperature": self.temperature,
            "context_window_tokens": self.context_window_tokens,
            "screening_input_token_budget": self.screening_input_token_budget,
        }


def load_llm_config(
    path: str | Path | None = None,
    *,
    required: bool = True,
) -> LLMConfig | None:
    """Load the local JSON LLM config."""

    resolved = _resolve_config_path(path)
    if resolved.exists():
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"LLM config must be a JSON object: {resolved}")
        return _config_from_payload(payload, source_path=resolved)

    if required:
        raise FileNotFoundError(
            f"Missing LLM config: {resolved}. Copy llm.local.example.json to llm.local.json."
        )
    return None


def _resolve_config_path(path: str | Path | None) -> Path:
    raw_path = path or os.getenv("LLM_CONFIG_PATH") or DEFAULT_LLM_CONFIG_PATH
    resolved = Path(raw_path)
    if resolved.is_absolute():
        return resolved
    return Path.cwd() / resolved


def _config_from_payload(
    payload: dict[str, Any],
    *,
    source_path: Path,
) -> LLMConfig:
    api_key = _text(payload.get("api_key"))
    base_url = _text(payload.get("base_url")) or DEFAULT_BASE_URL
    model = _text(payload.get("model") or payload.get("model_id"))
    api_mode = _normalize_api_mode(_text(payload.get("api_mode") or payload.get("mode")) or DEFAULT_API_MODE)
    timeout_seconds = _float_value(
        payload.get("timeout_seconds") or payload.get("timeout"),
        DEFAULT_TIMEOUT_SECONDS,
    )
    temperature = _optional_float_value(
        payload.get("temperature"),
    )
    context_window_tokens = _positive_int_value(
        payload.get("context_window_tokens"),
        DEFAULT_CONTEXT_WINDOW_TOKENS,
        name="context_window_tokens",
    )
    screening_input_token_budget = _positive_int_value(
        payload.get("screening_input_token_budget"),
        DEFAULT_SCREENING_INPUT_TOKEN_BUDGET,
        name="screening_input_token_budget",
    )
    if screening_input_token_budget >= context_window_tokens:
        raise ValueError(
            "screening_input_token_budget must be smaller than context_window_tokens"
        )
    missing = [name for name, value in {"api_key": api_key, "model": model}.items() if not value]
    if missing:
        raise ValueError(f"Missing required LLM config fields in {source_path}: {missing}")
    return LLMConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model,
        api_mode=api_mode,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        context_window_tokens=context_window_tokens,
        screening_input_token_budget=screening_input_token_budget,
        source_path=source_path,
    )

def _normalize_api_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"response", "auto"}:
        normalized = "responses"
    if normalized not in {"chat", "responses"}:
        raise ValueError(
            "LLM api_mode must be one of: chat, responses, auto "
            "('auto' resolves to 'responses')"
        )
    return normalized


def _float_value(value: Any, default: float) -> float:
    if value is None or str(value).strip() == "":
        return default
    return float(value)


def _optional_float_value(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def _positive_int_value(value: Any, default: int, *, name: str) -> int:
    if value is None or str(value).strip() == "":
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
