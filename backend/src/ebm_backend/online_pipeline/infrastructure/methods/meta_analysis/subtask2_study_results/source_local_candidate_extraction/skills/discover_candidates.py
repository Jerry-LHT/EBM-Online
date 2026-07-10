"""Source reader for targeted extraction candidate discovery."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.config import LLMConfig
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.context import (
    ExtractionContext,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.debug_artifacts import (
    debug_dir_for,
    write_named_debug_artifact,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.prompt_loader import (
    render_prompt,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.skills.common import (
    call_skill,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.tools.source_catalog import (
    source_payload,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.tools.json_tools import (
    prompt_json,
)


SYSTEM = (
    "You are an evidence-based medicine data extraction assistant. "
    "Read the provided source faithfully and return only source-grounded JSON."
)


def _target_semantics(setting: dict[str, Any]) -> str:
    parts: list[str] = []
    outcome = setting.get("outcome") or {}
    comparison = setting.get("comparison") or {}
    timepoint = setting.get("timepoint") or {}
    subgroup = setting.get("subgroup") or {}

    outcome_label = outcome.get("measure") or outcome.get("domain") or outcome.get("name")
    comparison_label = comparison.get("label") or comparison.get("arm_1_label") or comparison.get("arm_2_label")
    timepoint_label = timepoint.get("label") or timepoint.get("value")
    subgroup_label = subgroup.get("label") or subgroup.get("value")

    if outcome_label:
        parts.append(f"outcome: {outcome_label}")
    if comparison_label:
        parts.append(f"comparison: {comparison_label}")
    if timepoint_label:
        parts.append(f"timepoint: {timepoint_label}")
    if subgroup_label:
        parts.append(f"subgroup: {subgroup_label}")
    data_type = setting.get("data_type")
    if data_type:
        parts.append(f"data_type: {data_type}")
    return "; ".join(parts)


def discover_candidates_from_source(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    source: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "review_analysis_setting": {
            "setting_id": context.setting_id,
            "comparison": context.analysis_setting.get("comparison") or {},
            "outcome": context.analysis_setting.get("outcome") or {},
            "timepoint": context.analysis_setting.get("timepoint") or {},
            "subgroup": context.analysis_setting.get("subgroup") or {},
            "data_type": context.data_type,
            "required_result_fields": context.required_fields,
            "extraction_hint": context.extraction_hint,
        },
        "source": source_payload(source),
    }
    prompt = render_prompt("discover_candidates.txt", input_json=prompt_json(payload))
    result = call_skill(
        config=config,
        template="discover_candidates.txt",
        payload=payload,
        system=SYSTEM,
        fallback={
            "status": "unavailable",
            "brief_summary": "",
            "candidates": [],
            "warnings": [],
        },
    )
    debug_path = debug_dir_for(f"{context.instance_id}::{context.target.get('extraction_task_id') or context.study_id}")
    source_id = str(source.get("source_id") or "source")
    safe_source_id = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in source_id)
    write_named_debug_artifact(
        path=debug_path,
        filename=f"discover_candidates__{safe_source_id}.json",
        payload={
            "source_id": source_id,
            "payload": payload,
            "prompt": prompt,
            "parsed_output": result,
        },
    )
    return result
