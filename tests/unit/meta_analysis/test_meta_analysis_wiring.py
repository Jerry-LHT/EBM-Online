from __future__ import annotations

from ebm_backend.online_pipeline.application.use_cases.run_meta_analysis import (
    MetaAnalysisProgressEvent,
    RunMetaAnalysis,
    _article_payload,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleTable,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.factory import (
    build_production_analysis_methods_selector,
    build_production_overall_estimates_calculator,
    build_production_study_evidence_agent,
    build_production_subgroup_analyzer,
    build_production_synthesis_planner,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.errors import (
    MetaAnalysisInvocationError,
)


class _SynthesisPlanner:
    def __init__(self) -> None:
        self.context = None

    def run(self, *, context):
        self.context = context
        return {
            "plan_id": "meta-plan::review-1::v3",
            "review_id": "review-1",
            "version": "3",
            "status": "frozen",
            "plan_hash": "hash-1",
            "screening_criteria_snapshot": context["screening_criteria"],
            "rationale": "Prespecified outcome target.",
            "unsupported_targets": [],
            "targets": [
                {
                    "target_id": "setting::review-1::pain",
                    "setting_family_id": "family::pain",
                    "population_scope": "adults",
                    "comparison": {"experimental": "treatment", "comparator": "control"},
                    "outcome": {"label": "pain", "measure": "pain present"},
                    "timepoint": {
                        "label": "7 days",
                        "strategy": "exact",
                        "target_value": 7,
                        "window_start": 7,
                        "window_end": 7,
                        "unit": "days",
                        "anchor": "randomization",
                        "basis": "screening_criteria",
                        "rationale": "Prespecified seven-day follow-up.",
                    },
                    "subgroup": {"factor": None, "level": None},
                    "data_type": "Dichotomous",
                    "result_selection_policy": {
                        "acceptable_outcome_measures": ["pain present"],
                        "outcome_measure_priority": ["pain present"],
                        "analysis_population_priority": ["intention-to-treat"],
                        "statistic_type_priority": ["events and total"],
                        "source_priority": ["primary results table"],
                        "tie_policy": "unresolved",
                        "decision_basis": {
                            "outcome_measure": "Prespecified outcome.",
                            "timepoint": "Prespecified follow-up.",
                            "analysis_population": "Assignment effect.",
                            "statistic_type": "Arm-level estimate.",
                            "source": "Primary source.",
                        },
                    },
                    "effect_measure_plan": "Risk Ratio",
                    "analysis_model_plan": "common_effect",
                }
            ],
        }


def test_meta_analysis_article_payload_preserves_formal_raw_xml() -> None:
    article = CleanedArticle(
        study_id="study-1",
        metadata=ArticleMetadata(title="Trial"),
        xml_content=ArticleXmlContent(),
        tables=[
            ArticleTable(
                table_id="table-1",
                caption="Outcome",
                rows=[],
                raw_xml="<table-wrap id=\"table-1\"><table/></table-wrap>",
            )
        ],
    )

    payload = _article_payload(article)

    assert payload["tables"][0]["raw_xml"] == article.tables[0].raw_xml


class _StudyEvidence:
    def run(self, *, review_id, targets, study_id, article, plan_hash):
        assert review_id == "review-1"
        assert study_id == "study-1"
        assert article["study_id"] == "study-1"
        assert plan_hash == "hash-1"
        target_id = targets[0]["target_id"]
        row = {
            "row_id": "study-result::study-1",
            "setting_id": target_id,
            "study_id": "study-1",
            "extraction_status": "extracted",
            "data_type": "Dichotomous",
            "comparison": {"experimental_arm": "treatment", "control_arm": "control"},
            "outcome": {"label": "pain", "timepoint": "7 days"},
            "subgroup": {"factor": None, "level": None},
            "result_items": [
                {
                    "candidate_id": "candidate-1",
                    "match_status": "matched",
                    "study_result_setting": {
                        "outcome_label": "pain",
                        "outcome_measure": "pain present",
                        "timepoint": "7 days",
                        "population_or_subgroup": "adults",
                        "analysis_population": "intention-to-treat",
                        "experimental_arm_label": "treatment",
                        "control_arm_label": "control",
                    },
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 2,
                        "experimental_total": 20,
                        "control_events": 5,
                        "control_total": 20,
                    },
                    "analysis_disposition": "ready_for_estimate",
                    "source_spans": [{"source_id": "table-1", "text": "2/20 and 5/20"}],
                }
            ],
        }
        candidate = row["result_items"][0]
        resolution_id = f"resolution::{target_id}::{study_id}"
        return {
            "study_id": study_id,
            "study_result_rows": [row],
            "resolution_records": [{
                "resolution_id": resolution_id,
                "target_id": target_id,
                "study_id": study_id,
                "status": "resolved",
                "operation": "selected",
                "contributing_candidate_ids": [candidate["candidate_id"]],
                "unresolved_candidate_ids": [],
                "applied_rule_ids": ["semantic_compatibility"],
                "excluded_candidate_ids": [],
                "reason": "Unique compatible candidate.",
                "dependency_group_id": f"dependency::{study_id}",
                "source_spans": candidate["source_spans"],
            }],
            "data_rows": [{
                **row,
                "data_row_id": f"resolved::{study_id}",
                "result_data": candidate["result_data"],
                "source_candidate_ids": [candidate["candidate_id"]],
                "resolution_id": resolution_id,
                "result_items": [
                    {
                        **candidate,
                        "source_candidate_ids": [candidate["candidate_id"]],
                        "include_in_estimate": True,
                        "analysis_disposition": "selected_for_analysis",
                        "resolution_reason": resolution_id,
                        "resolution_operation": "selected",
                    }
                ],
            }],
            "coverage": {"study_id": study_id, "status": "complete"},
        }


class _AnalysisMethods:
    def run(self, *, instance):
        assert len(instance["meta_analysis_data_rows"]) == 1
        return [
            {
                "method_id": "method-1",
                "setting_id": instance["analysis_setting"]["setting_id"],
                "data_type": "Dichotomous",
                "effect_measure": "Risk Ratio",
                "analysis_model": "fixed_effect",
                "statistical_method": "Mantel-Haenszel",
                "method_status": "ready",
                "status": "supported",
                "analysis_included_study_ids": ["study-1"],
            }
        ]


class _SubgroupAnalysis:
    def run(self, *, instances):
        return {
            instance["instance_id"]: {
                "subgroup_estimates": [],
                "subgroup_difference_tests": [],
            }
            for instance in instances
        }


class _OverallEstimates:
    def run(self, **kwargs):
        return {"overall_estimates": [], "meta_analysis_data_rows": []}


class _NeverCalled:
    def run(self, **kwargs):
        raise AssertionError("Unsupported targets must not enter downstream stages")


def test_use_case_freezes_plan_then_resolves_candidates_before_analysis() -> None:
    planner = _SynthesisPlanner()
    use_case = RunMetaAnalysis(
        synthesis_planner=planner,
        study_evidence_agent=_StudyEvidence(),
        analysis_methods_selector=_AnalysisMethods(),
        subgroup_analyzer=_SubgroupAnalysis(),
        overall_estimates_calculator=_OverallEstimates(),
    )

    result = use_case.execute(
        review_id="review-1",
        question_text="question",
        question_pico=QuestionPICO(P=["adults"], I=["treatment"], C=["control"], O=["pain"]),
        screening_criteria=ScreeningCriteria(inclusion_criteria=["Randomized trials"]),
        included_studies=["study-1"],
        articles=[
            CleanedArticle(
                study_id="study-1",
                metadata=ArticleMetadata(title="Trial"),
                xml_content=ArticleXmlContent(),
            )
        ],
    )

    assert set(planner.context) == {
        "review_id",
        "question_text",
        "question_pico",
        "screening_criteria",
    }
    assert result.synthesis_plan is not None
    assert result.synthesis_plan.status == "frozen"
    assert result.candidate_resolution_records[0].status == "resolved"
    assert result.candidate_resolution_records[0].contributing_candidate_ids == [
        "candidate-1"
    ]
    assert result.synthesis_analysis_datasets[0].data_row_ids == [
        "resolved::study-1"
    ]
    assert result.meta_analysis_data_rows[0].study_id == "study-1"
    assert result.analysis_settings[0].eligible_study_ids == ["study-1"]
    assert result.analysis_settings[0].population_scope == "adults"
    assert not hasattr(result.analysis_settings[0], "candidate_id")
    assert result.study_result_rows[0].result_items[0].candidate_id == "candidate-1"
    assert (
        result.study_result_rows[0]
        .result_items[0]
        .study_result_setting.analysis_population
        == "intention-to-treat"
    )
    assert result.analysis_methods[0].method_id == "method-1"
    assert result.analysis_methods[0].interval_method == "Wald"


def test_progress_observer_can_checkpoint_and_reuse_study_evidence() -> None:
    events: list[MetaAnalysisProgressEvent] = []
    use_case = RunMetaAnalysis(
        synthesis_planner=_SynthesisPlanner(),
        study_evidence_agent=_StudyEvidence(),
        analysis_methods_selector=_AnalysisMethods(),
        subgroup_analyzer=_SubgroupAnalysis(),
        overall_estimates_calculator=_OverallEstimates(),
    )
    kwargs = {
        "review_id": "review-1",
        "question_text": "question",
        "question_pico": QuestionPICO(P=["adults"], I=["treatment"], C=["control"], O=["pain"]),
        "screening_criteria": ScreeningCriteria(inclusion_criteria=["Randomized trials"]),
        "included_studies": ["study-1"],
        "articles": [
            CleanedArticle(
                study_id="study-1",
                metadata=ArticleMetadata(title="Trial"),
                xml_content=ArticleXmlContent(),
            )
        ],
    }

    first = use_case.execute(**kwargs, progress_observer=events.append)
    study_event = next(
        event
        for event in events
        if event.stage == "study_evidence" and event.status == "completed"
    )
    assert study_event.payload is not None
    assert {event.stage for event in events} >= {
        "study_evidence",
        "candidate_resolution",
        "analysis_inputs",
        "analysis_method_selection",
        "subgroup_analysis",
        "overall_estimation",
        "final_package",
    }

    resumed_events: list[MetaAnalysisProgressEvent] = []
    resumed = RunMetaAnalysis(
        synthesis_planner=_NeverCalled(),
        study_evidence_agent=_NeverCalled(),
        analysis_methods_selector=_AnalysisMethods(),
        subgroup_analyzer=_SubgroupAnalysis(),
        overall_estimates_calculator=_OverallEstimates(),
    ).execute(
        **kwargs,
        synthesis_plan=first.synthesis_plan,
        precomputed_study_evidence={"study-1": study_event.payload},
        progress_observer=resumed_events.append,
    )

    assert resumed.study_result_rows == first.study_result_rows
    assert any(
        event.stage == "study_evidence" and event.status == "reused"
        for event in resumed_events
    )


def test_article_technical_failure_is_partial_coverage_not_missing_evidence() -> None:
    class PartiallyFailingEvidence(_StudyEvidence):
        def run(self, **kwargs):
            if kwargs["study_id"] == "study-2":
                raise MetaAnalysisInvocationError(
                    stage="table_result_extraction",
                    attempts=2,
                    retry_exhausted=True,
                    context_id="review-1::study-2::table-1",
                    failure_code="provider_timeout",
                    status_code=None,
                    request_id="request-2",
                    failure_detail="Request timed out.",
                    attempt_history=[
                        {
                            "attempt": 1,
                            "status": "provider_error",
                            "failure_code": "provider_timeout",
                        },
                        {
                            "attempt": 2,
                            "status": "provider_error",
                            "failure_code": "provider_timeout",
                        },
                    ],
                )
            return super().run(**kwargs)

    use_case = RunMetaAnalysis(
        synthesis_planner=_SynthesisPlanner(),
        study_evidence_agent=PartiallyFailingEvidence(),
        analysis_methods_selector=_AnalysisMethods(),
        subgroup_analyzer=_SubgroupAnalysis(),
        overall_estimates_calculator=_OverallEstimates(),
    )
    articles = [
        CleanedArticle(
            study_id=study_id,
            metadata=ArticleMetadata(title=f"Trial {study_id}"),
            xml_content=ArticleXmlContent(),
        )
        for study_id in ("study-1", "study-2")
    ]

    result = use_case.execute(
        review_id="review-1",
        question_text="question",
        question_pico=QuestionPICO(P=["adults"], I=["treatment"], C=["control"], O=["pain"]),
        screening_criteria=ScreeningCriteria(inclusion_criteria=["Randomized trials"]),
        included_studies=["study-1", "study-2"],
        articles=articles,
    )

    records = {row.study_id: row for row in result.candidate_resolution_records}
    assert records["study-1"].status == "resolved"
    assert records["study-2"].status == "technical_failure"
    assert records["study-2"].failure_code == "provider_timeout"
    assert records["study-2"].failure_detail == "Request timed out."
    assert records["study-2"].failure_metadata == {
        "stage": "table_result_extraction",
        "attempts": 2,
        "retry_exhausted": True,
        "request_id": "request-2",
        "attempt_history": [
            {
                "attempt": 1,
                "status": "provider_error",
                "failure_code": "provider_timeout",
            },
            {
                "attempt": 2,
                "status": "provider_error",
                "failure_code": "provider_timeout",
            },
        ],
    }
    assert result.analysis_methods[0].analysis_included_study_ids == ["study-1"]
    dataset = result.synthesis_analysis_datasets[0]
    assert dataset.resolution_summary["incomplete_coverage_study_count"] == 1
    assert dataset.provenance["coverage_by_study"]["study-2"] == "technical_failure"
    assert dataset.provenance["technical_failures_by_study"]["study-2"] == {
        "failure_code": "provider_timeout",
        "failure_detail": "Request timed out.",
        "stage": "table_result_extraction",
        "attempts": 2,
        "retry_exhausted": True,
        "request_id": "request-2",
        "attempt_history": [
            {
                "attempt": 1,
                "status": "provider_error",
                "failure_code": "provider_timeout",
            },
            {
                "attempt": 2,
                "status": "provider_error",
                "failure_code": "provider_timeout",
            },
        ],
    }


def test_explicit_factories_build_current_capabilities() -> None:
    assert callable(build_production_synthesis_planner().run)
    assert callable(build_production_study_evidence_agent().run)
    assert callable(build_production_analysis_methods_selector().run)
    assert callable(build_production_subgroup_analyzer().run)
    assert callable(build_production_overall_estimates_calculator().run)


def test_llm_factories_reuse_injected_workflow_config_snapshot() -> None:
    config = {
        "api_key": "test-key",
        "base_url": "https://example.test/v1",
        "model": "test-model",
        "api_mode": "chat",
    }

    planner = build_production_synthesis_planner(config=config)
    evidence_agent = build_production_study_evidence_agent(config=config)

    assert planner.config is config
    assert evidence_agent.config is config


def test_unsupported_plan_stops_before_article_result_extraction() -> None:
    class UnsupportedPlanner:
        def run(self, *, context):
            return {
                "plan_id": "meta-plan::review-1::v3",
                "review_id": "review-1",
                "version": "3",
                "status": "not_plannable",
                "plan_hash": "hash-unsupported",
                "targets": [],
                "unsupported_targets": [
                    {
                        "outcome_label": "overall survival",
                        "data_type": "Time-to-event",
                        "reason": "Requires a hazard-ratio data model.",
                        "reason_code": "unsupported_data_type",
                    }
                ],
                "screening_criteria_snapshot": context["screening_criteria"],
                "rationale": "No supported target.",
            }

    use_case = RunMetaAnalysis(
        synthesis_planner=UnsupportedPlanner(),
        study_evidence_agent=_NeverCalled(),
        analysis_methods_selector=_NeverCalled(),
        subgroup_analyzer=_NeverCalled(),
        overall_estimates_calculator=_NeverCalled(),
    )

    result = use_case.execute(
        review_id="review-1",
        question_text="Does treatment improve overall survival?",
        question_pico=QuestionPICO(
            P=["adults"],
            I=["treatment"],
            C=["control"],
            O=["overall survival"],
        ),
        screening_criteria=ScreeningCriteria(),
        included_studies=["study-1"],
        articles=[
            CleanedArticle(
                study_id="study-1",
                metadata=ArticleMetadata(title="Trial"),
                xml_content=ArticleXmlContent(),
            )
        ],
    )

    assert result.synthesis_plan is not None
    assert result.synthesis_plan.status == "not_plannable"
    assert result.synthesis_plan.unsupported_targets[0].data_type == "Time-to-event"
    assert result.study_result_rows == []
