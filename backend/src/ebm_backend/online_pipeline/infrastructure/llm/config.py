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
DEFAULT_TEMPERATURE = 0.0


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    api_mode: str = DEFAULT_API_MODE
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    temperature: float = DEFAULT_TEMPERATURE
    source_path: Path | None = None

    def to_dict(self) -> dict[str, str]:
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "api_mode": self.api_mode,
            "timeout_seconds": str(self.timeout_seconds),
            "temperature": str(self.temperature),
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
    temperature = _float_value(
        payload.get("temperature"),
        DEFAULT_TEMPERATURE,
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
        source_path=source_path,
    )

def _normalize_api_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "response":
        normalized = "responses"
    if normalized not in {"chat", "responses", "auto"}:
        raise ValueError("LLM api_mode must be one of: chat, responses, auto")
    return normalized


def _float_value(value: Any, default: float) -> float:
    if value is None or str(value).strip() == "":
        return default
    return float(value)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
