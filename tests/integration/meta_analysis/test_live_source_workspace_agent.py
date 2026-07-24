"""Opt-in smoke cases for the experimental source-workspace evidence agent."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from ebm_backend.online_pipeline.infrastructure.llm import load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.source_workspace_agent.method import (
    Method,
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_SOURCE_WORKSPACE") != "1",
    reason="Set RUN_LIVE_SOURCE_WORKSPACE=1 to call the source-workspace evidence agent.",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTICLE_PATH = (
    REPO_ROOT / "tests/fixtures/meta_analysis/live_e2e_hospital_stay/desai_2018.json"
)
# These are source-only article files from the filtered development snapshot.
# The live test reads article XML only; it never imports benchmark code or gold.
CONTINUOUS_SOURCE_CASES = (
    (
        REPO_ROOT
        / "benchmark/online_pipeline/meta_analysis/subtask2_study_results/datasets/"
        "cochrane_meta_v2-key-filter/shared/articles/pmc__PMC6323346.json",
        "12 weeks",
        {
            "experimental": (68.3, 8.9, 20),
            "control": (51.6, 1.2, 20),
        },
    ),
    (
        REPO_ROOT
        / "benchmark/online_pipeline/meta_analysis/subtask2_study_results/datasets/"
        "cochrane_meta_v2-key-filter/shared/articles/pmc__PMC7367519.json",
        "13 weeks",
        {
            "experimental": (48.7, 17.5, 24),
            # The Quality-of-life T1 control cell carries footnote f (n=22),
            # which is more local than the generic T1 header n=24.
            "control": (46.9, 13.6, 22),
        },
    ),
)
GIV_ARTICLE_PATH = (
    REPO_ROOT
    / "benchmark/online_pipeline/meta_analysis/subtask2_study_results/datasets/"
    "cochrane_meta_v2-key-filter/shared/articles/pmc__PMC4811029.json"
)
LIVE_MAX_TABLE_WORKERS = 2
TARGET = {
    "target_id": "live::postoperative-atrial-fibrillation",
    "setting_family_id": "live::postoperative-atrial-fibrillation",
    "population_scope": "Adults undergoing cardiac surgery",
    "comparison": {
        "experimental": "perioperative levosimendan",
        "comparator": "standard cardiac care",
    },
    "outcome": {
        "label": "postoperative atrial fibrillation",
        "measure": "participants with postoperative atrial fibrillation",
    },
    "timepoint": {
        "label": "postoperative period during index hospitalization",
        "strategy": "exact",
    },
    "subgroup": {"factor": None, "level": None},
    "data_type": "Dichotomous",
    "result_selection_policy": {
        "analysis_population_priority": ["all randomized participants"],
        "statistic_type_priority": ["events and analyzed total"],
        "tie_policy": "unresolved",
    },
    "effect_measure_plan": "Risk Ratio",
    "analysis_model_plan": "common_effect",
}


def test_live_source_workspace_extracts_one_real_rct_article(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = json.loads(ARTICLE_PATH.read_text(encoding="utf-8"))
    config = load_llm_config()
    assert config is not None
    live_model = os.getenv("META_SOURCE_WORKSPACE_LIVE_MODEL")
    if live_model:
        config = replace(config, model=live_model)
    artifact_dir = Path(
        os.getenv("META_SOURCE_WORKSPACE_ARTIFACT_DIR")
        or tmp_path / "source-workspace-debug"
    )
    monkeypatch.setenv("META_STUDY_EVIDENCE_DEBUG_DIR", str(artifact_dir))
    result = Method(config=config, max_table_workers=LIVE_MAX_TABLE_WORKERS).run(
        review_id="live-source-workspace-desai-v1",
        study_id=article["study_id"],
        article=article,
        plan_hash="live-source-workspace-plan-v1",
        targets=[TARGET],
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {
        "coverage": result["coverage"],
        "resolution_status": result["resolution_records"][0]["status"],
        "data_rows": len(result["data_rows"]),
        "result_data": result["data_rows"][0]["result_data"]
        if result["data_rows"]
        else None,
    }
    print(json.dumps(summary, ensure_ascii=False))
    assert result["coverage"]["status"] in {
        "complete",
        "incomplete_source_coverage",
    }
    assert result["resolution_records"]
    assert result["data_rows"]
    field_selection = result["data_rows"][0]["derivation"]["input_values"][
        "field_selection"
    ]
    assert set(field_selection) == {
        "experimental_events",
        "experimental_total",
        "control_events",
        "control_total",
    }
    assert all(
        row["basis"] in {"direct", "supported_inference", "assumption"}
        for selections in field_selection.values()
        for row in selections
    )


@pytest.mark.parametrize(
    "article_path,timepoint,expected",
    CONTINUOUS_SOURCE_CASES,
    ids=["janyacharoen-2018", "li-2020"],
)
def test_live_source_workspace_extracts_real_continuous_rct_article(
    article_path: Path,
    timepoint: str,
    expected: dict[str, tuple[float, float, int]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = json.loads(article_path.read_text(encoding="utf-8"))
    config = load_llm_config()
    assert config is not None
    live_model = os.getenv("META_SOURCE_WORKSPACE_LIVE_MODEL")
    if live_model:
        config = replace(config, model=live_model)
    artifact_dir = Path(
        os.getenv("META_SOURCE_WORKSPACE_ARTIFACT_DIR")
        or tmp_path
        / f"source-workspace-continuous-{article['study_id'].lower().replace(' ', '-')}"
    )
    monkeypatch.setenv("META_STUDY_EVIDENCE_DEBUG_DIR", str(artifact_dir))
    target = {
        "target_id": f"live::continuous::{article['study_id']}",
        "setting_family_id": "live::continuous::koos-quality-of-life",
        "population_scope": "adults with knee osteoarthritis",
        "comparison": {
            "experimental": "exercise or physiotherapist-supported physical activity programme",
            "comparator": "inactive, delayed, or usual-care control",
        },
        "outcome": {
            "label": "KOOS knee-related quality of life",
            "measure": "KOOS quality-of-life subscale, 0 to 100",
        },
        "timepoint": {"label": timepoint, "strategy": "exact"},
        "subgroup": {"factor": None, "level": None},
        "data_type": "Continuous",
        "result_selection_policy": {
            "analysis_population_priority": [
                "participants assessed at the requested timepoint",
                "all randomized participants",
            ],
            "continuous_result_frame_priority": ["post_intervention"],
            "statistic_type_priority": ["arm mean, standard deviation, analyzed N"],
            "tie_policy": "unresolved",
        },
        "effect_measure_plan": "Mean Difference",
        "analysis_model_plan": "common_effect",
    }
    result = Method(config=config, max_table_workers=LIVE_MAX_TABLE_WORKERS).run(
        review_id="live-source-workspace-continuous-koos-v1",
        study_id=article["study_id"],
        article=article,
        plan_hash=f"live-source-workspace-continuous-{timepoint}",
        targets=[target],
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    assert result["coverage"]["status"] == "complete"
    assert result["resolution_records"][0]["status"] == "resolved"
    assert len(result["data_rows"]) == 1
    data = result["data_rows"][0]["result_data"]
    assert (
        data["experimental_mean"],
        data["experimental_sd"],
        data["experimental_total"],
    ) == pytest.approx(expected["experimental"])
    assert (
        data["control_mean"],
        data["control_sd"],
        data["control_total"],
    ) == pytest.approx(expected["control"])


def test_live_source_workspace_extracts_reported_direct_effect_for_giv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = json.loads(GIV_ARTICLE_PATH.read_text(encoding="utf-8"))
    config = load_llm_config()
    assert config is not None
    live_model = os.getenv("META_SOURCE_WORKSPACE_LIVE_MODEL")
    if live_model:
        config = replace(config, model=live_model)
    artifact_dir = Path(
        os.getenv("META_SOURCE_WORKSPACE_ARTIFACT_DIR")
        or tmp_path / "source-workspace-giv-yonkers-2015"
    )
    monkeypatch.setenv("META_STUDY_EVIDENCE_DEBUG_DIR", str(artifact_dir))
    target = {
        "target_id": "live::giv::yonkers-2015::pmts",
        "setting_family_id": "live::giv::pmdd-symptom-severity",
        "population_scope": "women aged 18 to 48 years with premenstrual dysphoric disorder",
        "comparison": {
            "experimental": "symptom-onset sertraline treatment",
            "comparator": "matching placebo",
        },
        "outcome": {
            "label": "premenstrual symptom severity",
            "measure": "Premenstrual Tension Scale (PMTS) total score, range 0 to 36",
        },
        "timepoint": {
            "label": "end point after six menstrual cycles",
            "strategy": "exact",
        },
        "subgroup": {"factor": None, "level": None},
        "data_type": "Continuous",
        "result_selection_policy": {
            "analysis_population_priority": [
                "participants included in the repeated-measures efficacy analysis",
                "all randomized participants",
            ],
            "continuous_result_frame_priority": ["change_score"],
            "statistic_type_priority": [
                "direct between-group mean difference with reported uncertainty",
                "arm mean, standard deviation, analyzed N",
            ],
            "tie_policy": "unresolved",
        },
        "effect_measure_plan": "Mean Difference",
        "analysis_model_plan": "common_effect",
    }
    result = Method(
        config=config,
        max_table_workers=LIVE_MAX_TABLE_WORKERS,
    ).run(
        review_id="live-source-workspace-giv-pmdd-v1",
        study_id=article["study_id"],
        article=article,
        plan_hash="live-source-workspace-giv-pmdd-plan-v1",
        targets=[target],
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    assert result["coverage"]["status"] in {
        "complete",
        "incomplete_source_coverage",
    }
    assert result["resolution_records"][0]["status"] == "resolved"
    assert len(result["data_rows"]) == 1
    row = result["data_rows"][0]
    item = row["result_items"][0]
    data = row["result_data"]
    derivation = row["derivation"]
    uncertainty = derivation["input_values"]["uncertainty"]

    assert item["study_result_setting"]["analysis_input_representation"] == (
        "generic_inverse_variance"
    )
    assert data["effect_measure"] == "Mean Difference"
    assert data["analysis_scale"] == "natural"
    assert derivation["input_values"]["reported_effect"] == pytest.approx(1.88)
    assert abs(data["effect_value"]) == pytest.approx(1.88)
    assert (
        data["effect_value"]
        * row["continuous_effect_alignment"]["effect_multiplier"]
    ) == pytest.approx(1.88)
    assert data["standard_error"] == pytest.approx(0.9540991639)
    assert derivation["method"] == "generic_inverse_variance"
    assert derivation["input_values"]["adjudicated_comparison_direction"] in {
        "experimental_minus_control",
        "control_minus_experimental",
    }
    assert derivation["input_values"]["comparison_direction_multiplier"] in {-1, 1}
    assert derivation["input_values"]["direction_adjudication"]["basis"] in {
        "source_reported",
        "cross_source_inference",
    }
    assert uncertainty["method"] == "ci_to_se"
    assert uncertainty["ci_lower"] == pytest.approx(0.01)
    assert uncertainty["ci_upper"] == pytest.approx(3.75)
    assert any(
        str(span.get("source_id") or "").lower() == "t2"
        for span in row["source_spans"]
    )
