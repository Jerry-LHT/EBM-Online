"""Source profiling for targeted extraction."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.config import LLMConfig
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.context import (
    ExtractionContext,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.skills.common import (
    call_skill,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.tools.source_catalog import (
    source_payload,
)


SYSTEM = (
    "You are an evidence-based medicine data extraction assistant. "
    "Read the provided source faithfully and return only source-grounded JSON."
)


def profile_source(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    source: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "workflow_setting": {
            "setting_id": context.setting_id,
            "comparison": context.analysis_setting.get("comparison") or {},
            "outcome": context.analysis_setting.get("outcome") or {},
            "timepoint": context.analysis_setting.get("timepoint") or {},
            "subgroup": context.analysis_setting.get("subgroup") or {},
            "target_semantics": _target_semantics(context.analysis_setting),
            "data_type": context.data_type,
            "required_fields": context.required_fields,
            "extraction_hint": context.extraction_hint,
        },
        "source": source_payload(source),
    }
    return call_skill(
        config=config,
        template="profile_source.txt",
        payload=payload,
        system=SYSTEM,
        fallback={
            "status": "unavailable",
            "brief_summary": "",
            "source_profile": {},
            "warnings": [],
        },
    )


def _target_semantics(setting: dict[str, Any]) -> str:
    parts: list[str] = []
    comparison = setting.get("comparison") if isinstance(setting.get("comparison"), dict) else {}
    outcome = setting.get("outcome") if isinstance(setting.get("outcome"), dict) else {}
    timepoint = setting.get("timepoint") if isinstance(setting.get("timepoint"), dict) else {}
    subgroup = setting.get("subgroup") if isinstance(setting.get("subgroup"), dict) else {}
    for value in (
        comparison.get("text"),
        outcome.get("label"),
        outcome.get("measure"),
        timepoint.get("label"),
        subgroup.get("level"),
        setting.get("data_type"),
    ):
        text = " ".join(str(value).split()) if value else ""
        if text:
            parts.append(text)
    return " | ".join(parts)
