"""Runtime policy for GRADE inconsistency methods."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal


InconsistencyMode = Literal["benchmark", "production", "audit"]


@dataclass(frozen=True)
class InconsistencyMethodConfig:
    """Controls leakage-sensitive optional capabilities.

    Benchmark mode is deliberately conservative and is the default used by the
    benchmark loaders. Production mode can enable local LLM heterogeneity
    profiling, but final judgement remains based on local workflow evidence.
    """

    mode: InconsistencyMode = "benchmark"
    allow_llm_profile: bool = False

    @classmethod
    def from_env(cls) -> "InconsistencyMethodConfig":
        mode = _mode_value(os.getenv("GRADE_INCONSISTENCY_MODE") or "benchmark")
        return cls(
            mode=mode,
            allow_llm_profile=_bool_env("GRADE_INCONSISTENCY_ALLOW_LLM", default=mode == "production"),
        )

    def effective_allow_llm_profile(self) -> bool:
        return self.mode in {"production", "audit"} and self.allow_llm_profile

    def audit_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "allow_llm_profile": self.allow_llm_profile,
        }


def _mode_value(value: str) -> InconsistencyMode:
    normalized = value.strip().lower()
    if normalized in {"benchmark", "production", "audit"}:
        return normalized  # type: ignore[return-value]
    return "benchmark"


def _bool_env(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
