"""Method adapter for targeted extraction."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm import load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.base import StudyResultsMethod
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.orchestrator import (
    extract_study_result_rows,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.progress import (
    ProgressLogger,
)


DEFAULT_CONFIG_PATH = "llm.local.json"


class Method(StudyResultsMethod):
    """Target-driven study-result extraction aligned to workflow settings."""

    def __init__(self, *, llm_config: str | Path | None = None, phase: str = "full") -> None:
        self.llm_config_path = Path(llm_config or os.environ.get("SUBTASK2_LLM_CONFIG", DEFAULT_CONFIG_PATH))
        self.phase = phase

    def run(self, *, instance: dict[str, Any], articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        config = load_llm_config(self.llm_config_path, required=False)
        if config is None:
            return []
        return extract_study_result_rows(
            instance=instance,
            articles=articles,
            config=config,
            phase=self.phase,
            progress=ProgressLogger(),
        )


def build_method() -> Method:
    return Method()
