"""Strict Agent Runtime configuration loaded from ignored local JSON."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .contracts import AgentProvider
from .errors import AgentConfigurationError


DEFAULT_AGENT_CONFIG_PATH = "llm.local.json"
_ALLOWED_FIELDS = frozenset({"provider", "api_key", "model", "base_url"})


@dataclass(frozen=True, slots=True)
class AgentRuntimeConfig:
    provider: AgentProvider
    api_key: str
    model: str
    base_url: str
    source_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise AgentConfigurationError("api_key must not be blank")
        normalized_model = self.model.strip()
        prefix = f"{self.provider.value}/"
        if not normalized_model.startswith(prefix) or normalized_model == prefix:
            raise AgentConfigurationError(
                f"model must use the {prefix}<model-id> form"
            )
        object.__setattr__(self, "model", normalized_model)
        object.__setattr__(self, "base_url", _normalize_base_url(self.base_url))

    @property
    def cli_model(self) -> str:
        return self.model.split("/", maxsplit=1)[1]

    def __repr__(self) -> str:
        return (
            "AgentRuntimeConfig("
            f"provider={self.provider!r}, api_key='***', "
            f"model={self.model!r}, base_url={self.base_url!r}, "
            f"source_path={self.source_path!r})"
        )


def load_agent_runtime_config(
    path: str | Path | None = None,
) -> AgentRuntimeConfig:
    raw_path = (
        path
        or os.getenv("LLM_CONFIG_PATH")
        or DEFAULT_AGENT_CONFIG_PATH
    )
    resolved = Path(raw_path).expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AgentConfigurationError(
            f"Missing Agent Runtime config: {resolved}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise AgentConfigurationError(
            f"Agent Runtime config is not valid JSON: {resolved}"
        ) from exc
    if not isinstance(payload, dict):
        raise AgentConfigurationError(
            f"Agent Runtime config must be a JSON object: {resolved}"
        )
    return runtime_config_from_mapping(payload, source_path=resolved)


def runtime_config_from_mapping(
    payload: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> AgentRuntimeConfig:
    unknown = sorted(set(payload) - _ALLOWED_FIELDS)
    if unknown:
        raise AgentConfigurationError(
            "llm.local.json supports only provider, api_key, model, and "
            "base_url; "
            f"remove: {', '.join(unknown)}"
        )
    provider_text = str(payload.get("provider") or "").strip().lower()
    api_key = str(payload.get("api_key") or "").strip()
    model = str(payload.get("model") or "").strip()
    base_url = str(payload.get("base_url") or "").strip()
    try:
        provider = AgentProvider(provider_text)
    except ValueError as exc:
        supported = ", ".join(item.value for item in AgentProvider)
        raise AgentConfigurationError(
            f"provider must be one of: {supported}"
        ) from exc
    return AgentRuntimeConfig(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
        source_path=source_path,
    )


def _normalize_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentConfigurationError(
            "base_url must be an absolute HTTP or HTTPS URL"
        )
    if parsed.username or parsed.password:
        raise AgentConfigurationError("base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise AgentConfigurationError(
            "base_url must not contain a query string or fragment"
        )
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            "",
            "",
        )
    )
