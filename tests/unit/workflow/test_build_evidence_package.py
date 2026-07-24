from __future__ import annotations

from ebm_backend.online_pipeline.application.use_cases.build_evidence_package import (
    BuildEvidencePackage,
)
from ebm_backend.online_pipeline.domain.common import (
    DataType,
    EstimationStatus,
    GradeDomainName,
)
from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleQualificationResult,
)
from ebm_backend.online_pipeline.domain.grade import (
    DomainJudgements,
    EffectEstimateRef,
    GRADEDomainJudgement,
    GradeResult,
    SoFRowGRADEAssessment,
)
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSetting,
    AnalysisSubgroup,
    AnalysisTimepoint,
    CandidateResolutionRecord,
    ContinuousResultData,
    MetaAnalysisDataRow,
    MetaAnalysisResultPackage,
    MetaAnalysisSynthesisPlan,
    OverallEstimate,
    StudyResultComparison,
    StudyResultOutcome,
    SynthesisTarget,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.risk_of_bias import (
    RiskOfBiasAssessment,
    RoB1DomainJudgement,
    RoB1OverallJudgement,
)
from ebm_backend.online_pipeline.domain.screening import (
    ScreeningCriteria,
    StudyScreeningResult,
)
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.domain.study_characteristics import (
    StudyComparatorCharacteristics,
    StudyInterventionCharacteristics,
    StudyOutcomeCharacteristics,
    StudyPIOCharacteristics,
    StudyPopulationCharacteristics,
)
from ebm_backend.online_pipeline.domain.workflow import (
    OnlineEBMWorkflowResult,
    WorkflowSearchRetrievalSummary,
    WorkflowSearchSourceSummary,
    WorkflowArticlePrecheckResult,
    WorkflowStudySelection,
)


TARGET_ID = "target-1"
STUDY_ID = "study-1"


def _target() -> SynthesisTarget:
    return SynthesisTarget(
        target_id=TARGET_ID,
        setting_family_id="family-1",
        population_scope="adults",
        comparison=AnalysisComparison(experimental="treatment", comparator="control"),
        outcome=AnalysisOutcome(label="pain", measure="scale"),
        timepoint=AnalysisTimepoint(label="12 weeks"),
        subgroup=AnalysisSubgroup(),
        data_type=DataType.CONTINUOUS,
        effect_measure_plan="Mean Difference",
    )


def _setting() -> AnalysisSetting:
    target = _target()
    return AnalysisSetting(
        setting_id=target.target_id,
        setting_family_id=target.setting_family_id,
        population_scope=target.population_scope,
        comparison=target.comparison,
        outcome=target.outcome,
        timepoint=target.timepoint,
        subgroup=target.subgroup,
        data_type=target.data_type,
        eligible_study_ids=[STUDY_ID],
    )


def _judgement(domain: GradeDomainName) -> GRADEDomainJudgement:
    return GRADEDomainJudgement(
        domain=domain,
        downgraded="no",
        severity="not_serious",
        levels=0,
        level_evaluable=True,
        rationale="No serious concern.",
    )


def _complete_result() -> OnlineEBMWorkflowResult:
    target = _target()
    estimate = OverallEstimate(
        overall_estimate_id="estimate-1",
        setting_id=TARGET_ID,
        setting_family_id="family-1",
        method_id="method-1",
        included_study_ids=[STUDY_ID],
        included_data_row_ids=["row-1"],
        study_count=1,
        participant_count=100,
        data_type=DataType.CONTINUOUS,
        effect_measure="Mean Difference",
        analysis_model="fixed_effect",
        statistical_method="Inverse Variance",
        ci_level="95%",
        estimation_status=EstimationStatus.COMPUTED,
        effect_value=-2.0,
        ci_lower=-3.0,
        ci_upper=-1.0,
    )
    data_row = MetaAnalysisDataRow(
        data_row_id="row-1",
        setting_id=TARGET_ID,
        setting_family_id="family-1",
        study_id=STUDY_ID,
        data_type=DataType.CONTINUOUS,
        comparison=StudyResultComparison(
            experimental_arm="treatment",
            control_arm="control",
        ),
        outcome=StudyResultOutcome(label="pain", timepoint="12 weeks"),
        subgroup=AnalysisSubgroup(),
        result_data=ContinuousResultData(
            experimental_mean=3.0,
            experimental_sd=1.0,
            experimental_total=50,
            control_mean=5.0,
            control_sd=1.0,
            control_total=50,
        ),
        source_candidate_ids=["candidate-1"],
        resolution_id="resolution-1",
        method_id="method-1",
        estimate_id="estimate-1",
        estimate_scope="overall",
        analysis_status="included",
        participant_count=100,
        effect_measure="Mean Difference",
        analysis_model="fixed_effect",
        statistical_method="Inverse Variance",
        analysis_effect=-2.0,
        analysis_scale="mean_difference",
        effect_value=-2.0,
        ci_lower=-3.0,
        ci_upper=-1.0,
        variance=0.25,
        standard_error=0.5,
        weight=4.0,
        weight_fraction=1.0,
    )
    domains = DomainJudgements(
        risk_of_bias=_judgement(GradeDomainName.RISK_OF_BIAS),
        inconsistency=_judgement(GradeDomainName.INCONSISTENCY),
        indirectness=_judgement(GradeDomainName.INDIRECTNESS),
        imprecision=_judgement(GradeDomainName.IMPRECISION),
    )
    return OnlineEBMWorkflowResult(
        review_id="review-1",
        question_text="Does treatment improve pain?",
        status="succeeded",
        run_id="run-1",
        question_pico=QuestionPICO(
            P=["adults"], I=["treatment"], C=["control"], O=["pain"]
        ),
        search_retrieval=WorkflowSearchRetrievalSummary(
            returned_count=1,
            retrieved_study_ids=[STUDY_ID],
            source_results=[
                WorkflowSearchSourceSummary(
                    source_name="pubmed",
                    search_query="raw query must not leak",
                    query_used="provider query must not leak",
                    total_hits=4,
                    returned_count=1,
                )
            ],
        ),
        study_screening=StudyScreeningResult(
            screening_criteria=ScreeningCriteria(
                inclusion_criteria=["Adults"],
                exclusion_criteria=["Not randomized"],
            ),
            included_studies=[STUDY_ID],
            included_articles=[STUDY_ID],
        ),
        study_pio=[
            StudyPIOCharacteristics(
                study_id=STUDY_ID,
                population=StudyPopulationCharacteristics(description="100 adults"),
                interventions=[
                    StudyInterventionCharacteristics(
                        label="treatment", description="daily treatment"
                    )
                ],
                comparators=[
                    StudyComparatorCharacteristics(
                        label="control", description="usual care"
                    )
                ],
                outcomes=[
                    StudyOutcomeCharacteristics(
                        outcome_label="pain",
                        measurement="scale",
                        timepoints=["12 weeks"],
                    )
                ],
            )
        ],
        risk_of_bias=[
            RiskOfBiasAssessment(
                study_id=STUDY_ID,
                domains=[
                    RoB1DomainJudgement(
                        domain="random_sequence_generation",
                        judgement="low_risk",
                        rationale="Adequate randomization.",
                    )
                ],
                overall=RoB1OverallJudgement(
                    judgement="low_risk",
                    rationale="No important concern.",
                ),
            )
        ],
        meta_analysis=MetaAnalysisResultPackage(
            review_id="review-1",
            synthesis_plan=MetaAnalysisSynthesisPlan(
                plan_id="plan-1",
                review_id="review-1",
                version="1",
                status="frozen",
                plan_hash="hash",
                targets=[target],
            ),
            candidate_resolution_records=[
                CandidateResolutionRecord(
                    resolution_id="resolution-1",
                    target_id=TARGET_ID,
                    study_id=STUDY_ID,
                    status="resolved",
                )
            ],
            analysis_settings=[_setting()],
            meta_analysis_data_rows=[data_row],
            overall_estimates=[estimate],
        ),
        grade=GradeResult(
            review_id="review-1",
            question_text="Does treatment improve pain?",
            sof_rows=[
                SoFRowGRADEAssessment(
                    sof_row_id="sof-1",
                    row_label="pain",
                    setting_id=TARGET_ID,
                    setting_family_id="family-1",
                    population_scope="adults",
                    comparison=target.comparison,
                    outcome=target.outcome,
                    timepoint=target.timepoint,
                    subgroup=target.subgroup,
                    effect_estimate_ref=EffectEstimateRef(
                        estimate_type="overall",
                        estimate_id="estimate-1",
                        estimation_status="computed",
                    ),
                    included_study_ids=[STUDY_ID],
                    domain_judgements=domains,
                )
            ],
        ),
        grade_status="succeeded",
    )


def test_builds_compact_complete_downstream_product() -> None:
    package = BuildEvidencePackage().execute(result=_complete_result())
    payload = to_jsonable(package)

    assert package.status.execution_status == "succeeded"
    assert package.status.evidence_status == "complete"
    assert package.status.ready_for_downstream is True
    assert package.search_summary.retrieved_count == 1
    assert package.studies[0].study_pio is not None
    assert package.evidence_units[0].completeness.contributing_study_ids == [
        STUDY_ID
    ]
    assert package.evidence_units[0].overall_estimate is not None
    assert package.evidence_units[0].overall_estimate.effect_value == -2.0
    assert package.evidence_units[0].grade.scope == "four_domain_partial_grade"
    assert package.evidence_units[0].grade.overall_certainty is None
    assert len(package.evidence_units[0].grade.domain_judgements) == 4
    serialized = str(payload)
    assert "raw query must not leak" not in serialized
    assert "provider query must not leak" not in serialized
    assert "source_spans" not in serialized
    assert "candidate_resolution_records" not in serialized
    assert "stages" not in payload


def test_search_summary_exposes_compact_screening_funnel_counts() -> None:
    complete = _complete_result()
    assert complete.search_retrieval is not None
    assert complete.study_screening is not None
    result = OnlineEBMWorkflowResult(
        **{
            **complete.__dict__,
            "search_retrieval": WorkflowSearchRetrievalSummary(
                returned_count=3,
                retrieved_record_count=500,
                full_text_available_count=3,
                remaining_full_text_count=7,
                truncated=True,
            ),
            "article_precheck": WorkflowArticlePrecheckResult(
                passed_studies=["a", "b", "c"],
                excluded_studies=["d"],
            ),
            "article_qualification": ArticleQualificationResult(
                passed_studies=["a"],
                uncertain_studies=["b"],
                excluded_studies=["c"],
                technical_failure_studies=["e"],
            ),
            "study_screening": StudyScreeningResult(
                screening_criteria=complete.study_screening.screening_criteria,
                included_studies=["a", "b"],
                meta_ready_studies=["a"],
                meta_investigation_studies=["b"],
                meta_unavailable_no_readable_table_studies=["c"],
            ),
            "study_selection": WorkflowStudySelection(
                eligible_study_ids=["a", "b"],
                selected_study_ids=["a", "b"],
                meta_analysis_study_ids=["a", "b"],
            ),
        }
    )

    summary = BuildEvidencePackage().execute(result=result).search_summary

    assert summary.citation_count == 500
    assert summary.remaining_full_text_count == 7
    assert summary.precheck_excluded_count == 1
    assert summary.article_type_uncertain_count == 1
    assert summary.article_type_technical_failure_count == 1
    assert summary.meta_ready_count == 1
    assert summary.meta_investigation_count == 1
    assert summary.meta_unavailable_no_readable_table_count == 1
    assert summary.meta_selected_count == 2


def test_marks_eligible_studies_omitted_by_downstream_limit_as_partial() -> None:
    complete = _complete_result()
    assert complete.study_screening is not None
    screening = StudyScreeningResult(
        screening_criteria=complete.study_screening.screening_criteria,
        decisions=complete.study_screening.decisions,
        included_studies=[STUDY_ID, "study-2"],
        excluded_articles=complete.study_screening.excluded_articles,
    )
    truncated = OnlineEBMWorkflowResult(
        **{
            **complete.__dict__,
            "study_screening": screening,
            "study_selection": WorkflowStudySelection(
                eligible_study_ids=[STUDY_ID, "study-2"],
                selected_study_ids=[STUDY_ID],
                not_selected_study_ids=["study-2"],
                max_downstream_studies=1,
                truncated=True,
            ),
        }
    )

    package = BuildEvidencePackage().execute(result=truncated)

    assert package.search_summary.included_count == 2
    assert package.search_summary.downstream_selected_count == 1
    assert package.search_summary.downstream_not_selected_count == 1
    assert [study.study_id for study in package.studies] == [STUDY_ID]
    assert package.status.evidence_status == "partial"
    assert package.status.ready_for_downstream is False
    assert (
        "eligible_studies_not_analyzed_due_to_limit"
        in package.status.reason_codes
    )


def test_marks_technical_study_result_failure_as_partial_evidence() -> None:
    complete = _complete_result()
    assert complete.meta_analysis is not None
    partial_meta = MetaAnalysisResultPackage(
        review_id=complete.meta_analysis.review_id,
        synthesis_plan=complete.meta_analysis.synthesis_plan,
        analysis_settings=complete.meta_analysis.analysis_settings,
        candidate_resolution_records=[
            CandidateResolutionRecord(
                resolution_id="resolution-1",
                target_id=TARGET_ID,
                study_id=STUDY_ID,
                status="technical_failure",
            )
        ],
    )
    partial = OnlineEBMWorkflowResult(
        **{
            **complete.__dict__,
            "meta_analysis": partial_meta,
            "grade": GradeResult(
                review_id="review-1",
                question_text=complete.question_text,
            ),
        }
    )

    package = BuildEvidencePackage().execute(result=partial)

    assert package.status.execution_status == "succeeded"
    assert package.status.evidence_status == "partial"
    assert package.status.ready_for_downstream is False
    assert package.evidence_units[0].completeness.technical_failure_study_ids == [
        STUDY_ID
    ]
    assert "partial_evidence_coverage" in package.status.reason_codes


def test_no_eligible_studies_is_a_valid_downstream_result() -> None:
    result = OnlineEBMWorkflowResult(
        review_id="review-1",
        question_text="question",
        status="succeeded",
        run_id="run-1",
        question_pico=QuestionPICO(P=["adults"]),
        study_screening=StudyScreeningResult(
            screening_criteria=ScreeningCriteria(),
        ),
        meta_analysis=MetaAnalysisResultPackage(review_id="review-1"),
        grade=GradeResult(review_id="review-1", question_text="question"),
        grade_status="succeeded",
    )

    package = BuildEvidencePackage().execute(result=result)

    assert package.status.evidence_status == "no_eligible_studies"
    assert package.status.ready_for_downstream is True
    assert package.evidence_units == []
