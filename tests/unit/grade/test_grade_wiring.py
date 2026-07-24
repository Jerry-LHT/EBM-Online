from __future__ import annotations

from threading import Barrier, Lock, get_ident
from types import SimpleNamespace

from ebm_backend.online_pipeline.application.use_cases.run_grade import (
    RunGrade,
    _grade_risk_of_bias_input,
)
from ebm_backend.online_pipeline.domain.common import DataType, EstimationStatus
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSetting,
    AnalysisSubgroup,
    AnalysisTimepoint,
    ContinuousResultData,
    DichotomousResultData,
    MetaAnalysisDataRow,
    MetaAnalysisResultPackage,
    OverallEstimate,
    StudyResultComparison,
    StudyResultOutcome,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.risk_of_bias import (
    RiskOfBiasAssessment,
    RoB1DomainJudgement,
)
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria
from ebm_backend.online_pipeline.domain.study_characteristics import (
    StudyComparatorCharacteristics,
    StudyInterventionCharacteristics,
    StudyOutcomeCharacteristics,
    StudyPIOCharacteristics,
    StudyPopulationCharacteristics,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.factory import (
    build_production_grade_imprecision_assessor,
    build_production_grade_inconsistency_assessor,
    build_production_grade_indirectness_assessor,
    build_production_grade_risk_of_bias_assessor,
)


class _ConcurrentAssessor:
    def __init__(self, *, domain: str, barrier: Barrier, thread_ids: set[int], lock: Lock) -> None:
        self.domain = domain
        self.barrier = barrier
        self.thread_ids = thread_ids
        self.lock = lock

    def run(self, **kwargs):
        with self.lock:
            self.thread_ids.add(get_ident())
        self.barrier.wait(timeout=2)
        return {
            "domain": self.domain,
            "downgraded": "no",
            "severity": "none",
            "levels": 0,
            "level_evaluable": True,
            "rationale": self.domain,
        }


def test_use_case_runs_four_domains_concurrently_and_assembles_in_fixed_fields() -> None:
    barrier = Barrier(4)
    thread_ids: set[int] = set()
    lock = Lock()
    assessors = {
        domain: _ConcurrentAssessor(domain=domain, barrier=barrier, thread_ids=thread_ids, lock=lock)
        for domain in ("risk_of_bias", "inconsistency", "indirectness", "imprecision")
    }
    use_case = RunGrade(
        risk_of_bias_assessor=assessors["risk_of_bias"],
        inconsistency_assessor=assessors["inconsistency"],
        indirectness_assessor=assessors["indirectness"],
        imprecision_assessor=assessors["imprecision"],
    )
    setting = AnalysisSetting(
        setting_id="setting-1",
        setting_family_id="family-1",
        population_scope="adults with the condition",
        comparison=AnalysisComparison(experimental="treatment", comparator="control"),
        outcome=AnalysisOutcome(label="outcome"),
        timepoint=AnalysisTimepoint(),
        subgroup=AnalysisSubgroup(),
        data_type=DataType.DICHOTOMOUS,
    )
    estimate = OverallEstimate(
        overall_estimate_id="estimate-1",
        setting_id="setting-1",
        setting_family_id="family-1",
        method_id="method-1",
        included_study_ids=[],
        study_count=0,
        participant_count=0,
        data_type=DataType.DICHOTOMOUS,
        effect_measure="Risk Ratio",
        analysis_model="random_effect",
        statistical_method="MH",
        ci_level="95%",
        estimation_status=EstimationStatus.COMPUTED,
    )

    result = use_case.execute(
        review_id="review-1",
        question_text="question",
        question_pico=QuestionPICO(),
        screening_criteria=ScreeningCriteria(),
        study_characteristics=[],
        risk_of_bias=[],
        meta_analysis_result=MetaAnalysisResultPackage(
            review_id="review-1",
            analysis_settings=[setting],
            overall_estimates=[estimate],
        ),
    )

    assert len(thread_ids) == 4
    judgements = result.sof_rows[0].domain_judgements
    assert not hasattr(result.sof_rows[0], "candidate_id")
    assert result.sof_rows[0].population_scope == "adults with the condition"
    assert judgements.risk_of_bias.rationale == "risk_of_bias"
    assert judgements.inconsistency.rationale == "inconsistency"
    assert judgements.indirectness.rationale == "indirectness"
    assert judgements.imprecision.rationale == "imprecision"
    assert all(
        judgement.severity == "not_serious"
        and judgement.assessment_status == "assessed"
        for judgement in (
            judgements.risk_of_bias,
            judgements.inconsistency,
            judgements.indirectness,
            judgements.imprecision,
        )
    )


def test_explicit_factories_build_current_grade_domain_adapters() -> None:
    assert callable(build_production_grade_risk_of_bias_assessor().run)
    assert callable(build_production_grade_inconsistency_assessor().run)
    assert callable(build_production_grade_indirectness_assessor().run)
    assert callable(build_production_grade_imprecision_assessor().run)


class _CaptureAssessor:
    def __init__(self) -> None:
        self.kwargs = None

    def run(self, **kwargs):
        self.kwargs = kwargs
        return {
            "downgraded": "no",
            "severity": "none",
            "levels": 0,
            "level_evaluable": True,
            "rationale": "captured",
        }


def test_grade_indirectness_receives_row_scoped_study_pico_projection() -> None:
    assessors = [_CaptureAssessor() for _ in range(4)]
    use_case = RunGrade(
        risk_of_bias_assessor=assessors[0],
        inconsistency_assessor=assessors[1],
        indirectness_assessor=assessors[2],
        imprecision_assessor=assessors[3],
    )
    setting = AnalysisSetting(
        setting_id="setting-1",
        setting_family_id="family-1",
        population_scope="Adults with hypertension",
        comparison=AnalysisComparison(experimental="Exercise", comparator="Usual care"),
        outcome=AnalysisOutcome(label="Blood pressure", measure="Systolic BP"),
        timepoint=AnalysisTimepoint(label="12 weeks"),
        subgroup=AnalysisSubgroup(),
        data_type=DataType.CONTINUOUS,
    )
    estimate = OverallEstimate(
        overall_estimate_id="estimate-1",
        setting_id="setting-1",
        setting_family_id="family-1",
        method_id="method-1",
        included_study_ids=["study-1", "study-missing-rob"],
        study_count=2,
        participant_count=120,
        data_type=DataType.CONTINUOUS,
        effect_measure="Mean Difference",
        analysis_model="random_effect",
        statistical_method="inverse_variance",
        ci_level="95%",
        estimation_status=EstimationStatus.COMPUTED,
        included_data_row_ids=["row-1"],
    )
    row = MetaAnalysisDataRow(
        data_row_id="row-1",
        setting_id="setting-1",
        setting_family_id="family-1",
        study_id="study-1",
        data_type=DataType.CONTINUOUS,
        comparison=StudyResultComparison(
            experimental_arm="Exercise",
            control_arm="Usual care",
        ),
        outcome=StudyResultOutcome(label="Blood pressure", timepoint="12 weeks"),
        subgroup=AnalysisSubgroup(),
        result_data=ContinuousResultData(
            experimental_mean=120,
            experimental_sd=10,
            experimental_total=30,
            control_mean=125,
            control_sd=10,
            control_total=30,
        ),
        source_candidate_ids=["candidate-1"],
        resolution_id="resolution-1",
        estimate_id="estimate-1",
        estimate_scope="overall",
        analysis_status="included",
        participant_count=60,
        effect_measure="Mean Difference",
        analysis_model="random_effect",
        statistical_method="inverse_variance",
        analysis_effect=-5.0,
        analysis_scale="identity",
        effect_value=-5.0,
        ci_lower=-10.0,
        ci_upper=0.0,
        variance=6.5,
        standard_error=2.55,
        weight=1.0,
        weight_fraction=1.0,
    )
    characteristics = StudyPIOCharacteristics(
        study_id="study-1",
        population=StudyPopulationCharacteristics(
            description="120 adults with hypertension"
        ),
        interventions=[
            StudyInterventionCharacteristics(
                label="Exercise",
                description="Supervised exercise three times weekly",
            )
        ],
        comparators=[
            StudyComparatorCharacteristics(
                label="Usual care",
                description="Routine primary care",
            )
        ],
        outcomes=[
            StudyOutcomeCharacteristics(
                outcome_label="Blood pressure",
                measurement="Automated seated systolic blood pressure",
                timepoints=["12 weeks"],
            )
        ],
    )

    use_case.execute(
        review_id="review-1",
        question_text="Does exercise lower blood pressure?",
        question_pico=QuestionPICO(
            P=["Adults with hypertension"],
            I=["Exercise"],
            C=["Usual care"],
            O=["Blood pressure"],
        ),
        screening_criteria=ScreeningCriteria(),
        study_characteristics=[characteristics],
        risk_of_bias=[
            RiskOfBiasAssessment(
                study_id="study-1",
                domains=[
                    RoB1DomainJudgement(
                        domain="random_sequence_generation",
                        judgement="low_risk",
                        rationale="Computer-generated random sequence.",
                    )
                ],
                assessed_domains=["random_sequence_generation"],
                unassessed_domains=[
                    "allocation_concealment",
                    "blinding_participants_personnel",
                    "blinding_outcome_assessment",
                    "incomplete_outcome_data",
                    "selective_reporting",
                    "other_bias",
                ],
            )
        ],
        meta_analysis_result=MetaAnalysisResultPackage(
            review_id="review-1",
            analysis_settings=[setting],
            meta_analysis_data_rows=[row],
            overall_estimates=[estimate],
        ),
    )

    assert set(assessors[2].kwargs) == {"grade_input"}
    indirectness_input = assessors[2].kwargs["grade_input"]
    assert indirectness_input.review_intervention == ["Exercise"]
    assert indirectness_input.setting.comparison.experimental == "Exercise"
    assert indirectness_input.coverage.expected_data_row_ids == ["row-1"]
    assert indirectness_input.coverage.available_data_row_ids == ["row-1"]
    assert indirectness_input.direct_comparison_status == "pairwise_direct"
    projection = indirectness_input.study_evidence[0]
    assert projection.mapping_status.intervention == "matched"
    assert projection.mapping_status.comparator == "matched"
    assert projection.mapping_status.outcome == "matched"
    assert projection.mapping_status.timepoint == "matched"
    assert projection.intervention.description == (
        "Supervised exercise three times weekly"
    )
    assert projection.effect_value == -5.0
    assert projection.weight_fraction == 1.0
    assert set(assessors[0].kwargs) == {"grade_input"}
    grade_input = assessors[0].kwargs["grade_input"]
    assert grade_input.contribution_basis == "study_count"
    assert [
        (study.study_id, study.rob_available, study.contribution_weight)
        for study in grade_input.contributing_studies
    ] == [
        ("study-1", True, None),
        ("study-missing-rob", False, None),
    ]
    assert grade_input.coverage.missing_rob_study_ids == ["study-missing-rob"]


def test_grade_risk_of_bias_uses_complete_meta_analysis_weights() -> None:
    setting = AnalysisSetting(
        setting_id="setting-weighted",
        setting_family_id="family-weighted",
        population_scope="adults",
        comparison=AnalysisComparison(experimental="treatment", comparator="control"),
        outcome=AnalysisOutcome(label="outcome"),
        timepoint=AnalysisTimepoint(),
        subgroup=AnalysisSubgroup(),
        data_type=DataType.DICHOTOMOUS,
    )
    estimate = OverallEstimate(
        overall_estimate_id="estimate-weighted",
        setting_id="setting-weighted",
        setting_family_id="family-weighted",
        method_id="method-weighted",
        included_study_ids=["study-1", "study-2"],
        included_data_row_ids=["row-1", "row-2"],
        study_count=2,
        participant_count=200,
        data_type=DataType.DICHOTOMOUS,
        effect_measure="Risk Ratio",
        analysis_model="fixed_effect",
        statistical_method="Mantel-Haenszel",
        ci_level="95%",
        estimation_status=EstimationStatus.COMPUTED,
    )
    rows = [
        _weighted_data_row("row-1", "study-1", 0.25),
        _weighted_data_row("row-2", "study-2", 0.75),
    ]

    grade_input = _grade_risk_of_bias_input(
        setting=setting,
        estimate=estimate,
        data_rows=rows,
        risk_of_bias=[],
    )

    assert grade_input.contribution_basis == "meta_analysis_weight"
    assert grade_input.coverage.weight_status == "complete"
    assert [item.contribution_weight for item in grade_input.contributing_studies] == [
        0.25,
        0.75,
    ]


def test_run_grade_connects_meta_analysis_data_row_weights_to_risk_of_bias() -> None:
    assessors = [_CaptureAssessor() for _ in range(4)]
    use_case = RunGrade(
        risk_of_bias_assessor=assessors[0],
        inconsistency_assessor=assessors[1],
        indirectness_assessor=assessors[2],
        imprecision_assessor=assessors[3],
    )
    setting = AnalysisSetting(
        setting_id="setting-weighted",
        setting_family_id="family-weighted",
        population_scope="adults",
        comparison=AnalysisComparison(experimental="treatment", comparator="control"),
        outcome=AnalysisOutcome(label="outcome"),
        timepoint=AnalysisTimepoint(),
        subgroup=AnalysisSubgroup(),
        data_type=DataType.DICHOTOMOUS,
    )
    estimate = OverallEstimate(
        overall_estimate_id="estimate-weighted",
        setting_id="setting-weighted",
        setting_family_id="family-weighted",
        method_id="method-weighted",
        included_study_ids=["study-1", "study-2"],
        included_data_row_ids=["row-1", "row-2"],
        study_count=2,
        participant_count=200,
        data_type=DataType.DICHOTOMOUS,
        effect_measure="Risk Ratio",
        analysis_model="fixed_effect",
        statistical_method="Mantel-Haenszel",
        ci_level="95%",
        estimation_status=EstimationStatus.COMPUTED,
    )

    use_case.execute(
        review_id="review-weighted",
        question_text="question",
        question_pico=QuestionPICO(),
        screening_criteria=ScreeningCriteria(),
        study_characteristics=[],
        risk_of_bias=[],
        meta_analysis_result=MetaAnalysisResultPackage(
            review_id="review-weighted",
            analysis_settings=[setting],
            meta_analysis_data_rows=[
                _weighted_data_row("row-1", "study-1", 0.25),
                _weighted_data_row("row-2", "study-2", 0.75),
                _weighted_data_row(
                    "other-row",
                    "other-study",
                    1.0,
                    estimate_id="other-estimate",
                ),
            ],
            overall_estimates=[estimate],
        ),
    )

    grade_input = assessors[0].kwargs["grade_input"]
    assert grade_input.contribution_basis == "meta_analysis_weight"
    assert grade_input.coverage.weight_status == "complete"
    assert [
        (item.study_id, item.contribution_weight)
        for item in grade_input.contributing_studies
    ] == [("study-1", 0.25), ("study-2", 0.75)]
    inconsistency_input = assessors[1].kwargs["grade_input"]
    assert inconsistency_input.estimate.estimate_id == "estimate-weighted"
    assert inconsistency_input.coverage.expected_data_row_ids == ["row-1", "row-2"]
    assert [
        (item.data_row_id, item.effect_value, item.weight_fraction)
        for item in inconsistency_input.study_effects
    ] == [
        ("row-1", 0.5, 0.25),
        ("row-2", 0.5, 0.75),
    ]
    assert "other-row" not in {
        item.data_row_id for item in inconsistency_input.study_effects
    }
    imprecision_input = assessors[3].kwargs["grade_input"]
    assert imprecision_input.estimate.estimate_id == "estimate-weighted"
    assert imprecision_input.coverage.expected_data_row_ids == ["row-1", "row-2"]
    assert [
        item.data_row_id for item in imprecision_input.contributing_data_rows
    ] == ["row-1", "row-2"]
    assert not hasattr(imprecision_input, "study_characteristics")
    assert not hasattr(imprecision_input, "risk_of_bias")


def test_grade_risk_of_bias_clears_partial_weights_before_study_count_fallback() -> None:
    setting = AnalysisSetting(
        setting_id="setting-partial",
        setting_family_id="family-partial",
        population_scope="adults",
        comparison=AnalysisComparison(experimental="treatment", comparator="control"),
        outcome=AnalysisOutcome(label="outcome"),
        timepoint=AnalysisTimepoint(),
        subgroup=AnalysisSubgroup(),
        data_type=DataType.DICHOTOMOUS,
    )
    estimate = OverallEstimate(
        overall_estimate_id="estimate-partial",
        setting_id="setting-partial",
        setting_family_id="family-partial",
        method_id="method-partial",
        included_study_ids=["study-1", "study-2"],
        included_data_row_ids=["row-1", "row-2"],
        study_count=2,
        participant_count=200,
        data_type=DataType.DICHOTOMOUS,
        effect_measure="Risk Ratio",
        analysis_model="fixed_effect",
        statistical_method="Mantel-Haenszel",
        ci_level="95%",
        estimation_status=EstimationStatus.COMPUTED,
    )

    grade_input = _grade_risk_of_bias_input(
        setting=setting,
        estimate=estimate,
        data_rows=[
            _weighted_data_row(
                "row-1",
                "study-1",
                1.0,
                setting_id="setting-partial",
                setting_family_id="family-partial",
                estimate_id="estimate-partial",
            )
        ],
        risk_of_bias=[],
    )

    assert grade_input.contribution_basis == "study_count"
    assert grade_input.coverage.weight_status == "unavailable"
    assert [
        item.contribution_weight for item in grade_input.contributing_studies
    ] == [None, None]


def _weighted_data_row(
    data_row_id: str,
    study_id: str,
    weight_fraction: float,
    *,
    setting_id: str = "setting-weighted",
    setting_family_id: str = "family-weighted",
    estimate_id: str = "estimate-weighted",
) -> MetaAnalysisDataRow:
    return MetaAnalysisDataRow(
        data_row_id=data_row_id,
        setting_id=setting_id,
        setting_family_id=setting_family_id,
        study_id=study_id,
        data_type=DataType.DICHOTOMOUS,
        comparison=StudyResultComparison(
            experimental_arm="treatment",
            control_arm="control",
        ),
        outcome=StudyResultOutcome(label="outcome"),
        subgroup=AnalysisSubgroup(),
        result_data=DichotomousResultData(
            experimental_events=10,
            experimental_total=50,
            control_events=20,
            control_total=50,
        ),
        source_candidate_ids=[f"candidate-{study_id}"],
        resolution_id=f"resolution-{study_id}",
        method_id="method-weighted",
        estimate_id=estimate_id,
        estimate_scope="overall",
        analysis_status="included",
        participant_count=100,
        effect_measure="Risk Ratio",
        analysis_model="fixed_effect",
        statistical_method="Mantel-Haenszel",
        analysis_effect=-0.693147,
        analysis_scale="log",
        effect_value=0.5,
        ci_lower=0.25,
        ci_upper=1.0,
        variance=0.1,
        standard_error=0.316228,
        weight=weight_fraction * 10,
        weight_fraction=weight_fraction,
    )
