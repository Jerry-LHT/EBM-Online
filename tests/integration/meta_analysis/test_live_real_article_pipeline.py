"""Opt-in Meta-analysis workflow audit with copied real cleaned articles."""

from __future__ import annotations

from dataclasses import replace
import json
import math
import os
from pathlib import Path

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_meta_analysis import (
    RunMetaAnalysis,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleSource,
    ArticleTable,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.factory import (
    build_production_analysis_methods_selector,
    build_production_overall_estimates_calculator,
    build_production_study_evidence_agent,
    build_production_subgroup_analyzer,
    build_production_synthesis_planner,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, load_llm_config


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_META_E2E") != "1",
    reason="Set RUN_LIVE_META_E2E=1 to run the real-article Meta-analysis audit.",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTICLE_ROOT = REPO_ROOT / "tests/fixtures/meta_analysis/live_e2e_hospital_stay"
CASE_ARTICLES = (
    ARTICLE_ROOT / "desai_2018.json",
    ARTICLE_ROOT / "ersoy_2013.json",
)
EXPECTED_DICHOTOMOUS_ARM_VALUES = {
    "Desai 2018": frozenset({(14, 30), (23, 30)}),
}
EXPECTED_UNRESOLVED_DICHOTOMOUS_STUDIES = {"Ersoy 2013"}
CONTINUOUS_ARTICLE_ROOT = (
    REPO_ROOT / "tests/fixtures/meta_analysis/live_e2e_koos_quality_of_life"
)
CONTINUOUS_CASE_ARTICLES = (
    CONTINUOUS_ARTICLE_ROOT / "janyacharoen_2018.json",
    CONTINUOUS_ARTICLE_ROOT / "li_2020.json",
)
EXPECTED_CONTINUOUS_ARM_VALUES = {
    "Janyacharoen 2018": {
        "experimental": (68.3, 8.9, 20),
        "control": (51.6, 1.2, 20),
    },
    "Li 2020": {
        "experimental": (48.7, 17.5, 24),
        # The cell-level footnote is the article's best-supported analyzed N.
        "control": (46.9, 13.6, 22),
    },
}


def test_two_dichotomous_articles_run_to_pooled_overall_estimate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run planning, extraction, resolution, method selection, and pooling.

    The first article is the real Desai RCT fixture.  The second is a small
    controlled XML article with the same review question and an explicit
    arm-level event table.  It exercises the complete production path without
    importing benchmark code or using benchmark annotations as runtime input.
    """

    artifact_dir = Path(
        os.getenv("META_BINARY_E2E_ARTIFACT_DIR")
        or tmp_path / "binary-artifacts"
    )
    _configure_live_runtime(artifact_dir=artifact_dir, monkeypatch=monkeypatch)

    articles = [
        _cleaned_article(ARTICLE_ROOT / "desai_2018.json"),
        _controlled_binary_article(),
    ]
    llm_config = _live_config()
    result = _production_use_case(
        llm_config=llm_config,
        max_article_workers=2,
    ).execute(
        review_id="postoperative-atrial-fibrillation-dichotomous-e2e-v1",
        question_text=(
            "In adults undergoing cardiac surgery, does perioperative levosimendan "
            "versus standard cardiac care reduce postoperative atrial fibrillation "
            "after surgery?"
        ),
        question_pico=QuestionPICO(
            P=["adults undergoing cardiac surgery"],
            I=["perioperative levosimendan"],
            C=["standard cardiac care"],
            O=["postoperative atrial fibrillation after surgery"],
        ),
        screening_criteria=ScreeningCriteria(
            inclusion_criteria=[
                "Individually randomized parallel-group trials in adults undergoing cardiac surgery.",
                "Compare perioperative levosimendan with standard cardiac care.",
                "Report postoperative atrial fibrillation as arm-level event counts and participant totals at the postoperative assessment defined by each eligible trial.",
            ],
            exclusion_criteria=[
                "Exclude reports without arm-level event counts and participant totals for postoperative atrial fibrillation.",
                "Exclude non-randomized, crossover, and cluster-randomized studies.",
                "Exclude outcomes other than postoperative atrial fibrillation.",
            ],
        ),
        included_studies=[article.study_id for article in articles],
        articles=articles,
    )

    serialized = to_jsonable(result)
    (artifact_dir / "result.json").write_text(
        json.dumps(serialized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "case_id": "postoperative_atrial_fibrillation_two_study_binary",
                "fixture_files": [
                    "tests/fixtures/meta_analysis/live_e2e_hospital_stay/desai_2018.json",
                    "controlled_article_created_in_test",
                ],
                "source_contract": {
                    "data_type": "Dichotomous",
                    "effect_measure": "Risk Ratio",
                    "analysis_model": "selected_by_synthesis_planner",
                    "benchmark_gold_used_for_assertions": False,
                },
                "api_mode": llm_config.api_mode,
                "model": llm_config.model,
                "result_artifact": "result.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert result.synthesis_plan is not None
    assert result.synthesis_plan.status == "frozen"
    targets = [
        target
        for target in result.synthesis_plan.targets
        if target.data_type.value == "Dichotomous"
        and target.effect_measure_plan == "Risk Ratio"
        and "atrial fibrillation" in target.outcome.label.casefold()
    ]
    assert len(targets) == 1
    target = targets[0]

    records = [
        record
        for record in result.candidate_resolution_records
        if record.target_id == target.target_id
    ]
    assert {record.study_id for record in records} == {
        article.study_id for article in articles
    }
    assert all(record.status == "resolved" for record in records)

    datasets = [
        dataset
        for dataset in result.synthesis_analysis_datasets
        if dataset.target_id == target.target_id
    ]
    assert len(datasets) == 1
    setting_id = datasets[0].analysis_setting.setting_id
    selected = [
        row for row in result.meta_analysis_data_rows if row.setting_id == setting_id
    ]
    assert {row.study_id for row in selected} == {
        article.study_id for article in articles
    }
    assert all(row.analysis_status == "included" for row in selected)
    assert all(row.result_data is not None for row in selected)

    method = next(
        method
        for method in result.analysis_methods
        if method.setting_id == target.target_id
    )
    assert method.effect_measure == "Risk Ratio"
    assert method.method_status == "ready"
    assert method.statistical_policy_id == "cochrane_revman_v1"

    estimates = [
        estimate
        for estimate in result.overall_estimates
        if estimate.setting_id == target.target_id
    ]
    assert len(estimates) == 1
    estimate = estimates[0]
    assert estimate.estimation_status.value == "computed"
    assert estimate.study_count == 2
    assert estimate.participant_count == 140
    assert set(estimate.included_study_ids) == {
        article.study_id for article in articles
    }
    assert estimate.effect_direction_convention == "experimental_relative_to_control"
    assert 0 < float(estimate.effect_value) < 1
    assert float(estimate.ci_lower) <= float(estimate.effect_value)
    assert float(estimate.effect_value) <= float(estimate.ci_upper)

    analyzed_rows = [
        row
        for row in selected
        if row.estimate_id == estimate.overall_estimate_id
    ]
    assert len(analyzed_rows) == 2
    assert all(row.weight is not None and row.weight > 0 for row in analyzed_rows)
    assert math.isclose(
        sum(float(row.weight_fraction) for row in analyzed_rows),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    )

    (artifact_dir / "summary.json").write_text(
        json.dumps(
            {
                "study_ids": sorted(estimate.included_study_ids),
                "study_count": estimate.study_count,
                "participant_count": estimate.participant_count,
                "effect_measure": estimate.effect_measure,
                "effect_value": estimate.effect_value,
                "ci_lower": estimate.ci_lower,
                "ci_upper": estimate.ci_upper,
                "weight_fractions": {
                    row.study_id: row.weight_fraction for row in analyzed_rows
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_real_article_runs_from_synthesis_plan_to_overall_estimate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise every production Meta adapter without injected candidate rows."""

    artifact_dir = Path(os.getenv("META_E2E_ARTIFACT_DIR") or tmp_path / "artifacts")
    _configure_live_runtime(artifact_dir=artifact_dir, monkeypatch=monkeypatch)

    articles = [_cleaned_article(path) for path in CASE_ARTICLES]
    llm_config = _live_config()
    use_case = _production_use_case(llm_config=llm_config)

    result = use_case.execute(
        review_id="additional-inotropes-real-e2e-v7",
        question_text=(
            "In adults undergoing cardiac surgery, does perioperative levosimendan "
            "versus standard cardiac care change the number of participants requiring "
            "postoperative noradrenaline or another additional inotropic drug during "
            "the first 30 days after surgery?"
        ),
        question_pico=QuestionPICO(
            P=["adults undergoing cardiac surgery"],
            I=["perioperative levosimendan"],
            C=["standard cardiac care"],
            O=[
                "participants requiring postoperative noradrenaline or another additional inotropic drug within 30 days after surgery"
            ],
        ),
        screening_criteria=ScreeningCriteria(
            inclusion_criteria=[
                "Individually randomized parallel-group trials in adults undergoing cardiac surgery.",
                "Compare perioperative levosimendan with standard cardiac care.",
                "Report participants requiring postoperative noradrenaline or another additional inotropic drug as event counts and arm totals.",
                "Use cumulative events from surgery day 0 through postoperative day 30; if several assessments are reported, use the latest assessment within that window.",
            ],
            exclusion_criteria=[
                "Exclude reports that do not distinguish levosimendan from standard cardiac care.",
                "Exclude reports without arm-level event counts or participant totals for this outcome.",
                "Exclude inotropic-drug use first reported more than 30 days after surgery.",
            ],
        ),
        included_studies=[article.study_id for article in articles],
        articles=articles,
    )

    serialized = to_jsonable(result)
    (artifact_dir / "result.json").write_text(
        json.dumps(serialized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "case_id": "additional_inotropes_dichotomous_mixed_denominator_evidence",
                "fixture_files": [
                    str(path.relative_to(REPO_ROOT)) for path in CASE_ARTICLES
                ],
                "api_mode": llm_config.api_mode,
                "model": llm_config.model,
                "result_artifact": "result.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert result.synthesis_plan is not None
    assert result.synthesis_plan.version == "5"
    assert result.synthesis_plan.status == "frozen"
    matching_targets = [
        target
        for target in result.synthesis_plan.targets
        if target.data_type.value == "Dichotomous"
        and target.effect_measure_plan == "Risk Ratio"
        and "inotropic" in target.outcome.label.casefold()
    ]
    assert len(matching_targets) == 1
    target = matching_targets[0]
    raw_rows = [
        row for row in result.study_result_rows if row.setting_id == target.target_id
    ]
    assert {row.study_id for row in raw_rows} == {
        *EXPECTED_DICHOTOMOUS_ARM_VALUES,
        *EXPECTED_UNRESOLVED_DICHOTOMOUS_STUDIES,
    }
    assert all(row.result_items for row in raw_rows)

    records = [
        record
        for record in result.candidate_resolution_records
        if record.target_id == target.target_id
    ]
    assert {record.study_id for record in records} == {
        *EXPECTED_DICHOTOMOUS_ARM_VALUES,
        *EXPECTED_UNRESOLVED_DICHOTOMOUS_STUDIES,
    }
    assert {
        record.study_id for record in records if record.status == "resolved"
    } == set(EXPECTED_DICHOTOMOUS_ARM_VALUES)
    assert {
        record.study_id for record in records if record.status == "unresolved"
    } == EXPECTED_UNRESOLVED_DICHOTOMOUS_STUDIES

    datasets = [
        dataset
        for dataset in result.synthesis_analysis_datasets
        if dataset.target_id == target.target_id
    ]
    assert len(datasets) == 1
    selected = [
        row
        for row in result.meta_analysis_data_rows
        if row.setting_id == datasets[0].analysis_setting.setting_id
    ]
    assert {row.study_id for row in selected} == set(EXPECTED_DICHOTOMOUS_ARM_VALUES)
    assert {
        row.study_id: _unordered_dichotomous_arm_values(row.result_data)
        for row in selected
    } == EXPECTED_DICHOTOMOUS_ARM_VALUES

    methods = [
        method
        for method in result.analysis_methods
        if method.setting_id == target.target_id
    ]
    assert len(methods) == 1
    assert methods[0].effect_measure == "Risk Ratio"
    assert methods[0].method_status == "ready"
    assert methods[0].statistical_policy_id == "cochrane_revman_v1"
    assert result.subgroup_estimates == []
    assert result.subgroup_difference_tests == []

    estimates = [
        estimate
        for estimate in result.overall_estimates
        if estimate.setting_id == target.target_id
    ]
    assert len(estimates) == 1
    assert estimates[0].estimation_status.value == "computed"
    assert estimates[0].study_count == 1
    assert estimates[0].participant_count == 60
    assert set(estimates[0].included_study_ids) == set(EXPECTED_DICHOTOMOUS_ARM_VALUES)
    assert estimates[0].effect_direction_convention == "experimental_relative_to_control"
    assert math.isfinite(float(estimates[0].effect_value))
    assert math.isfinite(float(estimates[0].ci_lower))
    assert math.isfinite(float(estimates[0].ci_upper))
    assert float(estimates[0].ci_lower) <= float(estimates[0].effect_value)
    assert float(estimates[0].effect_value) <= float(estimates[0].ci_upper)
    analyzed_rows = [
        row
        for row in result.meta_analysis_data_rows
        if row.estimate_id == estimates[0].overall_estimate_id
        and row.analysis_status == "included"
    ]
    assert len(analyzed_rows) == 1
    assert all(row.weight is not None and row.weight > 0 for row in analyzed_rows)
    assert math.isclose(
        sum(float(row.weight_fraction) for row in analyzed_rows),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    )


def test_real_continuous_articles_run_to_weighted_overall_estimate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover a same-scale continuous result with source-correct follow-up Ns."""

    artifact_dir = Path(
        os.getenv("META_CONTINUOUS_E2E_ARTIFACT_DIR")
        or tmp_path / "continuous-artifacts"
    )
    _configure_live_runtime(artifact_dir=artifact_dir, monkeypatch=monkeypatch)

    articles = [_cleaned_article(path) for path in CONTINUOUS_CASE_ARTICLES]
    llm_config = _live_config()
    result = _production_use_case(llm_config=llm_config).execute(
        review_id="koos-quality-of-life-real-e2e-v1",
        question_text=(
            "In adults with knee osteoarthritis, does a structured exercise or "
            "physiotherapist-supported physical activity programme, compared with "
            "an inactive or delayed-programme control, improve knee-related quality "
            "of life on the KOOS 0-to-100 scale at the end of 12 to 13 weeks?"
        ),
        question_pico=QuestionPICO(
            P=["adults with knee osteoarthritis"],
            I=["structured exercise or physiotherapist-supported physical activity programme"],
            C=["inactive control or delayed-programme control"],
            O=["KOOS knee-related quality of life at 12 to 13 weeks"],
        ),
        screening_criteria=ScreeningCriteria(
            inclusion_criteria=[
                "Individually randomized parallel-group trials in adults with knee osteoarthritis.",
                "Compare a structured exercise or physiotherapist-supported physical activity programme with an inactive or delayed-programme control.",
                "Use the KOOS knee-related quality-of-life subscale scored from 0 to 100, where higher scores are better.",
                "Use post-intervention arm means, standard deviations, and the number assessed at the available end-of-intervention assessment from 12 through 13 weeks after treatment start.",
            ],
            exclusion_criteria=[
                "Exclude change-from-baseline, adjusted-effect-only, or baseline values when compatible post-intervention arm summaries are available.",
                "Exclude results from a different KOOS subscale or outside the 12-to-13-week window.",
                "Exclude cluster-randomized and crossover trials.",
            ],
        ),
        included_studies=[article.study_id for article in articles],
        articles=articles,
    )

    serialized = to_jsonable(result)
    (artifact_dir / "result.json").write_text(
        json.dumps(serialized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "case_id": "koos_quality_of_life_continuous_two_study",
                "fixture_files": [
                    str(path.relative_to(REPO_ROOT))
                    for path in CONTINUOUS_CASE_ARTICLES
                ],
                "source_contract": {
                    "data_type": "Continuous",
                    "effect_measure": "Mean Difference",
                    "result_frame": "post_intervention",
                    "scale": "KOOS knee-related quality of life, 0-100, higher is better",
                    "time_window_weeks": [12, 13],
                    "expected_arm_values": EXPECTED_CONTINUOUS_ARM_VALUES,
                    "benchmark_gold_used_for_assertions": False,
                },
                "api_mode": llm_config.api_mode,
                "model": llm_config.model,
                "result_artifact": "result.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert result.synthesis_plan is not None
    assert result.synthesis_plan.version == "5"
    assert result.synthesis_plan.status == "frozen"
    matching_targets = [
        target
        for target in result.synthesis_plan.targets
        if target.data_type.value == "Continuous"
        and target.effect_measure_plan == "Mean Difference"
        and "quality of life" in target.outcome.label.casefold()
    ]
    assert len(matching_targets) == 1
    target = matching_targets[0]

    raw_rows = [
        row for row in result.study_result_rows if row.setting_id == target.target_id
    ]
    assert {row.study_id for row in raw_rows} == set(EXPECTED_CONTINUOUS_ARM_VALUES)
    assert all(row.result_items for row in raw_rows)

    records = [
        record
        for record in result.candidate_resolution_records
        if record.target_id == target.target_id
    ]
    assert {record.study_id for record in records} == set(EXPECTED_CONTINUOUS_ARM_VALUES)
    assert all(record.status == "resolved" for record in records)

    datasets = [
        dataset
        for dataset in result.synthesis_analysis_datasets
        if dataset.target_id == target.target_id
    ]
    assert len(datasets) == 1
    selected = [
        row
        for row in result.meta_analysis_data_rows
        if row.setting_id == datasets[0].analysis_setting.setting_id
    ]
    assert {row.study_id for row in selected} == set(EXPECTED_CONTINUOUS_ARM_VALUES)
    for row in selected:
        payload = to_jsonable(row.result_data)
        expected = EXPECTED_CONTINUOUS_ARM_VALUES[row.study_id]
        assert (
            payload["experimental_mean"],
            payload["experimental_sd"],
            payload["experimental_total"],
        ) == pytest.approx(expected["experimental"])
        assert (
            payload["control_mean"],
            payload["control_sd"],
            payload["control_total"],
        ) == pytest.approx(expected["control"])
        assert row.continuous_effect_alignment is not None
        assert row.continuous_effect_alignment.result_frame == "post_intervention"
        assert row.continuous_effect_alignment.effect_multiplier == 1
        assert row.continuous_effect_alignment.status == "ready"

    methods = [
        method for method in result.analysis_methods if method.setting_id == target.target_id
    ]
    assert len(methods) == 1
    assert methods[0].effect_measure == "Mean Difference"
    assert methods[0].method_status == "ready"
    assert methods[0].statistical_policy_id == "cochrane_revman_v1"

    estimates = [
        estimate
        for estimate in result.overall_estimates
        if estimate.setting_id == target.target_id
    ]
    assert len(estimates) == 1
    estimate = estimates[0]
    assert estimate.estimation_status.value == "computed"
    assert estimate.study_count == 2
    assert estimate.participant_count == 88
    assert set(estimate.included_study_ids) == set(EXPECTED_CONTINUOUS_ARM_VALUES)
    assert estimate.effect_direction_convention == "original_measure_direction"
    assert float(estimate.effect_value) > 0
    assert float(estimate.ci_lower) <= float(estimate.effect_value)
    assert float(estimate.effect_value) <= float(estimate.ci_upper)

    analyzed_rows = [
        row
        for row in result.meta_analysis_data_rows
        if row.estimate_id == estimate.overall_estimate_id
        and row.analysis_status == "included"
    ]
    assert len(analyzed_rows) == 2
    assert all(row.weight is not None and row.weight > 0 for row in analyzed_rows)
    assert math.isclose(
        sum(float(row.weight_fraction) for row in analyzed_rows),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert float(estimate.effect_value) == pytest.approx(
        sum(
            float(row.effect_value) * float(row.weight_fraction)
            for row in analyzed_rows
        )
    )
    assert result.subgroup_estimates == []
    assert result.subgroup_difference_tests == []


def _unordered_dichotomous_arm_values(
    result_data: object,
) -> frozenset[tuple[int, int]]:
    payload = to_jsonable(result_data)
    return frozenset(
        {
            (
                payload["experimental_events"],
                payload["experimental_total"],
            ),
            (
                payload["control_events"],
                payload["control_total"],
            ),
        }
    )


def _configure_live_runtime(
    *,
    artifact_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(
        "META_STUDY_EVIDENCE_DEBUG_DIR",
        str(artifact_dir / "study_evidence_debug"),
    )


def _live_config() -> LLMConfig:
    llm_config = load_llm_config()
    api_mode_override = os.getenv("META_E2E_API_MODE")
    if api_mode_override:
        llm_config = replace(llm_config, api_mode=api_mode_override)
    if llm_config.api_mode != "chat":
        raise AssertionError("This live E2E must run through the production Chat API")
    return llm_config


def _production_use_case(
    *,
    llm_config: LLMConfig,
    max_article_workers: int = 1,
) -> RunMetaAnalysis:
    return RunMetaAnalysis(
        synthesis_planner=build_production_synthesis_planner(config=llm_config),
        study_evidence_agent=build_production_study_evidence_agent(config=llm_config),
        analysis_methods_selector=build_production_analysis_methods_selector(),
        subgroup_analyzer=build_production_subgroup_analyzer(),
        overall_estimates_calculator=build_production_overall_estimates_calculator(),
        max_article_workers=max_article_workers,
    )


def _controlled_binary_article() -> CleanedArticle:
    return CleanedArticle(
        study_id="Controlled Cardiac Surgery RCT 2024",
        metadata=ArticleMetadata(
            title=(
                "Perioperative levosimendan for prevention of postoperative atrial "
                "fibrillation: a randomized controlled trial"
            ),
            source_type="controlled-live-integration-fixture",
            publication_year="2024",
        ),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id="methods",
                    title="Methods",
                    text=(
                        "Eighty adults undergoing elective cardiac surgery were "
                        "randomized in a 1:1 parallel design to perioperative "
                        "levosimendan (Group L) or standard cardiac care (Group C). "
                        "Postoperative atrial fibrillation was assessed throughout "
                        "the index hospitalization."
                    ),
                ),
                ArticleSection(
                    section_id="results",
                    title="Results",
                    text=(
                        "All randomized participants were included in the reported "
                        "postoperative outcome table."
                    ),
                ),
            ]
        ),
        tables=[
            ArticleTable(
                table_id="table-2",
                caption="Postoperative outcomes during the index hospitalization",
                rows=[
                    {
                        "_raw_xml": (
                            '<table-wrap id="T2"><label>Table 2</label>'
                            '<caption><p>Postoperative outcomes during the index '
                            'hospitalization</p></caption><table><thead><tr>'
                            '<th>Outcome</th><th>Group L: levosimendan</th>'
                            '<th>Group C: standard care</th><th>P value</th>'
                            '</tr></thead><tbody><tr><td>Postoperative atrial '
                            'fibrillation, events / participants assessed (%)</td>'
                            '<td>4 events / 40 participants assessed (10.0%)</td>'
                            '<td>12 events / 40 participants assessed (30.0%)</td>'
                            '<td>0.03</td></tr></tbody></table><table-wrap-foot>'
                            '<fn><p>For this outcome, the denominator is the number '
                            'of participants assessed for postoperative atrial '
                            'fibrillation in that arm.</p></fn></table-wrap-foot>'
                            '</table-wrap>'
                        ),
                        "_section_path": "Results",
                    }
                ],
            )
        ],
        source=ArticleSource(
            database="controlled-live-integration-fixture",
            retrieval_rank=2,
            raw_record_id="controlled-cardiac-rct-2024",
        ),
    )


def _cleaned_article(path: Path) -> CleanedArticle:
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") or {}
    source = payload.get("source") or {}
    xml = payload.get("xml_content") or {}
    tables = []
    for index, table in enumerate(payload.get("tables") or [], start=1):
        rows = [dict(row) for row in table.get("rows") or [] if isinstance(row, dict)]
        raw_xml = table.get("raw_xml")
        if raw_xml and not any(row.get("_raw_xml") for row in rows):
            rows.append({"_raw_xml": str(raw_xml)})
        tables.append(
            ArticleTable(
                table_id=str(table.get("table_id") or f"t{index}"),
                caption=str(table.get("caption") or ""),
                rows=rows,
            )
        )
    return CleanedArticle(
        study_id=str(payload["study_id"]),
        metadata=ArticleMetadata(
            title=str(metadata.get("title") or ""),
            pmid=_optional_text(metadata.get("pmid")),
            pmc_id=_optional_text(metadata.get("pmc_id")),
            source_type=_optional_text(metadata.get("source_type")),
            publication_year=_optional_text(metadata.get("publication_year")),
            mesh_terms=[str(item) for item in metadata.get("mesh_terms") or []],
            doi=_optional_text(metadata.get("doi")),
        ),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id=str(section.get("section_id") or f"section-{index}"),
                    title=str(section.get("title") or ""),
                    text=str(section.get("text") or ""),
                )
                for index, section in enumerate(xml.get("sections") or [], start=1)
                if isinstance(section, dict)
            ]
        ),
        tables=tables,
        source=ArticleSource(
            database=str(source.get("database") or "copied-live-fixture"),
            retrieval_rank=source.get("retrieval_rank"),
            retrieval_score=source.get("retrieval_score"),
            raw_source_url=_optional_text(source.get("raw_source_url")),
            raw_record_id=_optional_text(source.get("raw_record_id")),
        ),
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
