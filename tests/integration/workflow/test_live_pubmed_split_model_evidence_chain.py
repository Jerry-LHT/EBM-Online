"""Opt-in PubMed-to-GRADE evidence-chain run with split LLM models."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_meta_analysis import (
    RunMetaAnalysis,
)
from ebm_backend.online_pipeline.application.use_cases.run_article_qualification import (
    RunArticleQualification,
)
from ebm_backend.online_pipeline.application.use_cases.run_study_screening import (
    RunStudyScreening,
)
from ebm_backend.online_pipeline.application.use_cases.run_online_ebm_workflow import (
    RunOnlineEBMWorkflow,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.llm import load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.factory import (
    build_production_analysis_methods_selector,
    build_production_overall_estimates_calculator,
    build_production_study_evidence_agent,
    build_production_subgroup_analyzer,
    build_production_synthesis_planner,
)
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.factory import (
    build_production_article_qualifier,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.factory import (
    build_production_staged_study_screening,
)
from ebm_backend.online_pipeline.infrastructure.persistence import (
    FileWorkflowRunStore,
    get_runtime_root,
)
from ebm_backend.online_pipeline.interfaces.api.dependencies import (
    get_grade_use_case_for_api,
    get_q2pico_use_case_for_api,
    get_risk_of_bias_use_case_for_api,
    get_search_retrieval_use_case_for_api,
    get_study_pio_use_case_for_api,
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_PUBMED_WORKFLOW") != "1",
    reason="Set RUN_LIVE_PUBMED_WORKFLOW=1 to run the PubMed evidence chain.",
)

QUESTION_TEXT = (
    "In adults with knee osteoarthritis, does exercise, compared "
    "with attention control, placebo, no treatment, usual care, or limited "
    "education, reduce knee pain immediately after the intervention?"
)
MAX_PUBMED_CANDIDATES = 500
MAX_PMC_ARTICLES = 100


def test_pubmed_rcts_run_through_meta_and_grade_with_split_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir = Path(
        os.getenv("PUBMED_WORKFLOW_ARTIFACT_DIR")
        or tmp_path / "pubmed_workflow_artifacts"
    )
    runtime_dir = artifact_dir / "runtime"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EBM_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv(
        "META_STUDY_EVIDENCE_DEBUG_DIR",
        str(artifact_dir / "meta_source_workspace_debug"),
    )

    default_config = load_llm_config()
    if default_config.model != "gpt-5.4-mini":
        raise ValueError(
            "This split-model live test requires llm.local.json to use "
            "gpt-5.4-mini for non-Meta modules."
        )
    meta_config = replace(
        default_config,
        model=os.getenv("META_LIVE_MODEL") or "gpt-5.4",
        timeout_seconds=max(default_config.timeout_seconds, 360.0),
    )

    meta_analysis = RunMetaAnalysis(
        synthesis_planner=build_production_synthesis_planner(config=meta_config),
        study_evidence_agent=build_production_study_evidence_agent(
            config=meta_config
        ),
        analysis_methods_selector=build_production_analysis_methods_selector(),
        subgroup_analyzer=build_production_subgroup_analyzer(),
        overall_estimates_calculator=build_production_overall_estimates_calculator(),
    )
    screening_methods = build_production_staged_study_screening(
        config=default_config
    )
    workflow = RunOnlineEBMWorkflow(
        q2pico=get_q2pico_use_case_for_api(),
        search_retrieval=get_search_retrieval_use_case_for_api(
            source_names=["pubmed"]
        ),
        article_qualification=RunArticleQualification(
            qualifier=build_production_article_qualifier(
                config=default_config,
                cache_root=runtime_dir / "cache" / "article_qualification_content_v1",
            )
        ),
        study_screening=RunStudyScreening(
            criteria_planner=screening_methods.criteria_planner,
            coarse_screener=screening_methods.coarse_screener,
            synthesis_ready_screener=screening_methods.synthesis_ready_screener,
        ),
        study_pio=get_study_pio_use_case_for_api(),
        risk_of_bias=get_risk_of_bias_use_case_for_api(),
        meta_analysis=meta_analysis,
        grade=get_grade_use_case_for_api(),
        run_store=FileWorkflowRunStore(get_runtime_root() / "workflow_runs"),
    )
    result = workflow.execute(
        review_id="live-pubmed-cd004376-knee-pain-v1",
        question_text=QUESTION_TEXT,
        constraints=WorkflowConstraints(study_design="RCT"),
        retrieval_config=ModuleRunConfig(
            max_candidates_per_source=MAX_PUBMED_CANDIDATES,
            max_results_per_source=MAX_PMC_ARTICLES,
            constraints=WorkflowConstraints(study_design="RCT"),
        ),
        expand_outcomes=True,
    )

    serialized = to_jsonable(result)
    (artifact_dir / "result.json").write_text(
        json.dumps(serialized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "run_summary.json").write_text(
        json.dumps(_run_summary(serialized), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    assert result.search_retrieval is not None
    assert 0 < result.search_retrieval.returned_count <= MAX_PMC_ARTICLES
    assert result.study_screening is not None
    assert len(result.study_screening.decisions) <= MAX_PMC_ARTICLES
    assert result.study_selection is not None
    assert result.study_selection.not_selected_study_ids == []
    assert result.status == "succeeded"
    assert len(result.study_pio) == len(result.study_selection.selected_study_ids)
    assert len(result.risk_of_bias) == len(result.study_selection.selected_study_ids)
    assert result.meta_analysis is not None
    assert result.meta_analysis.analysis_settings
    assert result.meta_analysis.meta_analysis_data_rows
    assert result.grade is not None


def _run_summary(serialized: dict[str, object]) -> dict[str, object]:
    search = serialized.get("search_retrieval") or {}
    screening = serialized.get("study_screening") or {}
    selection = serialized.get("study_selection") or {}
    meta = serialized.get("meta_analysis") or {}
    grade = serialized.get("grade") or {}
    source_results = search.get("source_results") or []
    return {
        "review_id": serialized.get("review_id"),
        "question_text": serialized.get("question_text"),
        "status": serialized.get("status"),
        "stage_statuses": [
            {
                "stage_name": row.get("stage_name"),
                "status": row.get("status"),
                "error_code": row.get("error_code"),
                "error_message": row.get("error_message"),
            }
            for row in serialized.get("stages") or []
        ],
        "retrieval": {
            "returned_count": search.get("returned_count"),
            "source_results": [
                {
                    "source_name": row.get("source_name"),
                    "total_hits": row.get("total_hits"),
                    "returned_count": row.get("returned_count"),
                    "search_query": row.get("search_query"),
                    "warning_count": row.get("warning_count"),
                }
                for row in source_results
            ],
        },
        "screening": {
            "included_count": len(screening.get("included_studies") or []),
            "excluded_count": len(screening.get("excluded_articles") or []),
            "included_studies": screening.get("included_studies") or [],
        },
        "downstream_selection": {
            "eligible_count": len(selection.get("eligible_study_ids") or []),
            "selected_count": len(selection.get("selected_study_ids") or []),
            "not_selected_count": len(
                selection.get("not_selected_study_ids") or []
            ),
            "selected_study_ids": selection.get("selected_study_ids") or [],
            "not_selected_study_ids": (
                selection.get("not_selected_study_ids") or []
            ),
            "truncated": selection.get("truncated"),
        },
        "study_pio_count": len(serialized.get("study_pio") or []),
        "risk_of_bias_count": len(serialized.get("risk_of_bias") or []),
        "meta_analysis": {
            "target_count": len(
                (meta.get("synthesis_plan") or {}).get("targets") or []
            ),
            "candidate_row_count": len(meta.get("study_result_rows") or []),
            "resolution_count": len(
                meta.get("candidate_resolution_records") or []
            ),
            "data_row_count": len(meta.get("meta_analysis_data_rows") or []),
            "analysis_setting_count": len(meta.get("analysis_settings") or []),
            "overall_estimate_count": len(meta.get("overall_estimates") or []),
        },
        "grade_sof_row_count": len(grade.get("sof_rows") or []),
    }
