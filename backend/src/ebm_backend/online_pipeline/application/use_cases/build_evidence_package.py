"""Build the compact downstream product from a full workflow audit result."""

from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.domain.common import EstimationStatus
from ebm_backend.online_pipeline.domain.evidence_package import (
    EvidenceCompleteness,
    EvidenceEstimate,
    EvidenceGradeAssessment,
    EvidenceGradeJudgement,
    EvidencePackage,
    EvidencePackageStatus,
    EvidenceProtocol,
    EvidenceRiskOfBias,
    EvidenceRoBDomain,
    EvidenceRoBOverall,
    EvidenceSearchSource,
    EvidenceSearchSummary,
    EvidenceStudy,
    EvidenceStudyArm,
    EvidenceStudyEffect,
    EvidenceStudyOutcome,
    EvidenceStudyPIO,
    EvidenceStudyPopulation,
    EvidenceSubgroupDifference,
    EvidenceTarget,
    EvidenceUnit,
)
from ebm_backend.online_pipeline.domain.grade import SoFRowGRADEAssessment
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSetting,
    MetaAnalysisDataRow,
    OverallEstimate,
    SubgroupEstimate,
    SynthesisTarget,
)
from ebm_backend.online_pipeline.domain.workflow import OnlineEBMWorkflowResult


SCHEMA_VERSION = "evidence-package.v1"
FOUR_DOMAIN_GRADE_SCOPE = "four_domain_partial_grade"


@dataclass(frozen=True)
class BuildEvidencePackage:
    """Project an auditable workflow result into its stable downstream view."""

    def execute(self, *, result: OnlineEBMWorkflowResult) -> EvidencePackage:
        screening = result.study_screening
        included_study_ids = _downstream_study_ids(result=result)
        studies, missing_study_codes = _build_studies(
            result=result,
            included_study_ids=included_study_ids,
        )
        evidence_units = _build_evidence_units(
            result=result,
            included_study_ids=included_study_ids,
        )
        status = _build_package_status(
            result=result,
            included_study_ids=included_study_ids,
            evidence_units=evidence_units,
            missing_study_codes=missing_study_codes,
        )
        criteria = screening.screening_criteria if screening else None
        return EvidencePackage(
            schema_version=SCHEMA_VERSION,
            run_id=result.run_id,
            review_id=result.review_id,
            status=status,
            protocol=EvidenceProtocol(
                question_text=result.question_text,
                question_pico=result.question_pico,
                inclusion_criteria=(
                    list(criteria.inclusion_criteria) if criteria else []
                ),
                exclusion_criteria=(
                    list(criteria.exclusion_criteria) if criteria else []
                ),
            ),
            search_summary=_build_search_summary(result=result),
            studies=studies,
            evidence_units=evidence_units,
        )


def _build_search_summary(
    *, result: OnlineEBMWorkflowResult
) -> EvidenceSearchSummary:
    search = result.search_retrieval
    screening = result.study_screening
    sources = []
    if search is not None:
        sources = [
            EvidenceSearchSource(
                source_name=row.source_name,
                total_hits=row.total_hits,
                retrieved_count=row.returned_count,
                citation_count=row.retrieved_record_count,
                full_text_available_count=row.full_text_available_count,
                remaining_full_text_count=row.remaining_full_text_count,
                truncated=row.truncated,
                warning_codes=_unique([warning.code for warning in row.warnings]),
            )
            for row in search.source_results
        ]
    included_count = len(screening.included_studies) if screening else 0
    excluded_count = len(screening.excluded_articles) if screening else 0
    decision_count = len(screening.decisions) if screening else 0
    screened_count = decision_count or included_count + excluded_count
    precheck = result.article_precheck
    qualification = result.article_qualification
    return EvidenceSearchSummary(
        retrieved_count=search.returned_count if search else 0,
        screened_count=screened_count,
        included_count=included_count,
        excluded_count=excluded_count,
        downstream_selected_count=(
            len(result.study_selection.selected_study_ids)
            if result.study_selection is not None
            else included_count
        ),
        downstream_not_selected_count=(
            len(result.study_selection.not_selected_study_ids)
            if result.study_selection is not None
            else 0
        ),
        citation_count=search.retrieved_record_count if search else 0,
        full_text_available_count=search.full_text_available_count if search else 0,
        remaining_full_text_count=search.remaining_full_text_count if search else 0,
        precheck_passed_count=len(precheck.passed_studies) if precheck else 0,
        precheck_excluded_count=len(precheck.excluded_studies) if precheck else 0,
        article_type_passed_count=(
            len(qualification.passed_studies) if qualification else 0
        ),
        article_type_uncertain_count=(
            len(qualification.uncertain_studies) if qualification else 0
        ),
        article_type_excluded_count=(
            len(qualification.excluded_studies) if qualification else 0
        ),
        article_type_technical_failure_count=(
            len(qualification.technical_failure_studies) if qualification else 0
        ),
        meta_ready_count=len(screening.meta_ready_studies) if screening else 0,
        meta_investigation_count=(
            len(screening.meta_investigation_studies) if screening else 0
        ),
        meta_unavailable_no_readable_table_count=(
            len(screening.meta_unavailable_no_readable_table_studies)
            if screening
            else 0
        ),
        meta_selected_count=(
            len(result.study_selection.meta_analysis_study_ids)
            if result.study_selection is not None
            else 0
        ),
        sources=sources,
    )


def _downstream_study_ids(*, result: OnlineEBMWorkflowResult) -> list[str]:
    if result.study_selection is not None:
        return list(result.study_selection.selected_study_ids)
    if result.study_screening is not None:
        return list(result.study_screening.included_studies)
    return []


def _build_studies(
    *,
    result: OnlineEBMWorkflowResult,
    included_study_ids: list[str],
) -> tuple[list[EvidenceStudy], list[str]]:
    pio_by_study = {row.study_id: row for row in result.study_pio}
    rob_by_study = {row.study_id: row for row in result.risk_of_bias}
    missing_codes: list[str] = []
    studies: list[EvidenceStudy] = []
    for study_id in included_study_ids:
        pio = pio_by_study.get(study_id)
        rob = rob_by_study.get(study_id)
        if pio is None:
            missing_codes.append("study_pio_missing")
        if rob is None:
            missing_codes.append("study_risk_of_bias_missing")
        compact_pio = None
        if pio is not None:
            compact_pio = EvidenceStudyPIO(
                population=EvidenceStudyPopulation(
                    description=pio.population.description,
                    eligibility_notes=pio.population.eligibility_notes,
                ),
                interventions=[
                    EvidenceStudyArm(label=row.label, description=row.description)
                    for row in pio.interventions
                ],
                comparators=[
                    EvidenceStudyArm(label=row.label, description=row.description)
                    for row in pio.comparators
                ],
                outcomes=[
                    EvidenceStudyOutcome(
                        outcome_label=row.outcome_label,
                        measurement=row.measurement,
                        timepoints=list(row.timepoints),
                    )
                    for row in pio.outcomes
                ],
            )
        compact_rob = None
        if rob is not None:
            compact_rob = EvidenceRiskOfBias(
                domains=[
                    EvidenceRoBDomain(
                        domain=row.domain,
                        judgement=row.judgement,
                        rationale=row.rationale,
                    )
                    for row in rob.domains
                ],
                overall=EvidenceRoBOverall(
                    judgement=rob.overall.judgement,
                    rationale=rob.overall.rationale,
                    driving_domains=list(rob.overall.driving_domains),
                ),
            )
        studies.append(
            EvidenceStudy(
                study_id=study_id,
                study_pio=compact_pio,
                risk_of_bias=compact_rob,
            )
        )
    return studies, _unique(missing_codes)


def _build_evidence_units(
    *,
    result: OnlineEBMWorkflowResult,
    included_study_ids: list[str],
) -> list[EvidenceUnit]:
    meta = result.meta_analysis
    if meta is None:
        return []
    settings = {row.setting_id: row for row in meta.analysis_settings}
    plan_targets = list(meta.synthesis_plan.targets) if meta.synthesis_plan else []
    ordered_targets: list[SynthesisTarget | AnalysisSetting] = (
        plan_targets or list(meta.analysis_settings)
    )
    grade_rows = {
        row.setting_id: row
        for row in (result.grade.sof_rows if result.grade is not None else [])
    }
    units: list[EvidenceUnit] = []
    for target_source in ordered_targets:
        target_id = (
            target_source.target_id
            if isinstance(target_source, SynthesisTarget)
            else target_source.setting_id
        )
        setting = settings.get(target_id)
        target = _compact_target(target_source=target_source, setting=setting)
        records = [
            row for row in meta.candidate_resolution_records if row.target_id == target_id
        ]
        rows = [
            row for row in meta.meta_analysis_data_rows if row.setting_id == target_id
        ]
        overall = next(
            (row for row in meta.overall_estimates if row.setting_id == target_id),
            None,
        )
        subgroup_estimates = [
            row for row in meta.subgroup_estimates if row.setting_id == target_id
        ]
        primary_estimate = _primary_estimate(
            target=target,
            overall=overall,
            subgroup_estimates=subgroup_estimates,
        )
        completeness = _build_completeness(
            expected_study_ids=included_study_ids,
            records=records,
            rows=rows,
            primary_estimate=primary_estimate,
        )
        units.append(
            EvidenceUnit(
                evidence_unit_id=target_id,
                target=target,
                completeness=completeness,
                study_effects=[_compact_study_effect(row) for row in rows],
                overall_estimate=(
                    _compact_estimate(overall, estimate_type="overall")
                    if overall is not None
                    else None
                ),
                subgroup_estimates=[
                    _compact_estimate(row, estimate_type="subgroup")
                    for row in subgroup_estimates
                ],
                subgroup_difference_tests=[
                    EvidenceSubgroupDifference(
                        test_id=row.test_id,
                        subgroup_factor=row.subgroup_factor,
                        test_status=row.test_status,
                        compared_subgroup_estimate_ids=list(
                            row.compared_subgroup_estimate_ids
                        ),
                        chi2=row.chi2,
                        df=row.df,
                        p_value=row.p_value,
                        i2_between_subgroups=row.i2_between_subgroups,
                    )
                    for row in meta.subgroup_difference_tests
                    if row.setting_family_id == target.setting_family_id
                ],
                grade=_compact_grade(grade_rows.get(target_id)),
            )
        )
    return units


def _compact_target(
    *,
    target_source: SynthesisTarget | AnalysisSetting,
    setting: AnalysisSetting | None,
) -> EvidenceTarget:
    source = setting or target_source
    return EvidenceTarget(
        target_id=(
            target_source.target_id
            if isinstance(target_source, SynthesisTarget)
            else target_source.setting_id
        ),
        setting_family_id=source.setting_family_id,
        population_scope=source.population_scope,
        comparison=source.comparison,
        outcome=source.outcome,
        timepoint=source.timepoint,
        subgroup=source.subgroup,
        data_type=source.data_type,
        planned_effect_measure=(
            target_source.effect_measure_plan
            if isinstance(target_source, SynthesisTarget)
            else None
        ),
    )


def _primary_estimate(
    *,
    target: EvidenceTarget,
    overall: OverallEstimate | None,
    subgroup_estimates: list[SubgroupEstimate],
) -> OverallEstimate | SubgroupEstimate | None:
    if target.subgroup.is_overall:
        return overall
    return subgroup_estimates[0] if subgroup_estimates else None


def _build_completeness(
    *,
    expected_study_ids: list[str],
    records: list,
    rows: list[MetaAnalysisDataRow],
    primary_estimate: OverallEstimate | SubgroupEstimate | None,
) -> EvidenceCompleteness:
    record_by_study = {row.study_id: row for row in records}
    expected = _unique(
        [*expected_study_ids, *[row.study_id for row in records]]
    )
    technical = [
        study_id
        for study_id in expected
        if study_id in record_by_study
        and record_by_study[study_id].status == "technical_failure"
    ]
    unavailable = [
        study_id
        for study_id in expected
        if study_id in record_by_study
        and record_by_study[study_id].status == "data_unavailable"
    ]
    unresolved = [
        study_id
        for study_id in expected
        if study_id not in record_by_study
        or record_by_study[study_id].status
        not in {"resolved", "data_unavailable", "technical_failure"}
    ]
    contributing = (
        list(primary_estimate.included_study_ids)
        if primary_estimate is not None
        else [row.study_id for row in rows if row.analysis_status == "included"]
    )
    reason_codes: list[str] = []
    if technical:
        reason_codes.append("study_result_technical_failure")
    if unresolved:
        reason_codes.append("study_result_unresolved")
    estimation_status = _status_value(
        primary_estimate.estimation_status if primary_estimate is not None else None
    )
    if not expected:
        status = "no_eligible_studies"
        reason_codes.append("no_eligible_studies")
    elif technical or unresolved or estimation_status == "failed":
        status = "partial"
        if estimation_status == "failed":
            reason_codes.append("estimate_failed")
    elif estimation_status == "computed":
        status = "complete"
    else:
        status = "insufficient_for_synthesis"
        reason_codes.append("insufficient_data_for_estimate")
    return EvidenceCompleteness(
        status=status,
        expected_study_ids=expected,
        contributing_study_ids=_unique(contributing),
        data_unavailable_study_ids=unavailable,
        unresolved_study_ids=unresolved,
        technical_failure_study_ids=technical,
        reason_codes=_unique(reason_codes),
    )


def _compact_study_effect(row: MetaAnalysisDataRow) -> EvidenceStudyEffect:
    return EvidenceStudyEffect(
        study_id=row.study_id,
        analysis_status=row.analysis_status,
        comparison=AnalysisComparison(
            experimental=row.comparison.experimental_arm,
            comparator=row.comparison.control_arm,
        ),
        outcome=AnalysisOutcome(
            label=row.outcome.label,
            measure=None,
        ),
        result_data=row.result_data,
        participant_count=row.participant_count,
        effect_measure=row.effect_measure,
        effect_value=row.effect_value,
        ci_lower=row.ci_lower,
        ci_upper=row.ci_upper,
        weight_fraction=row.weight_fraction,
        analysis_scale=row.analysis_scale,
        exclusion_reason=row.analysis_exclusion_reason,
    )


def _compact_estimate(
    row: OverallEstimate | SubgroupEstimate,
    *,
    estimate_type: str,
) -> EvidenceEstimate:
    estimate_id = (
        row.overall_estimate_id
        if isinstance(row, OverallEstimate)
        else row.subgroup_estimate_id
    )
    return EvidenceEstimate(
        estimate_id=estimate_id,
        estimate_type=estimate_type,
        estimation_status=_status_value(row.estimation_status),
        included_study_ids=list(row.included_study_ids),
        study_count=row.study_count,
        participant_count=row.participant_count,
        data_type=row.data_type,
        effect_measure=row.effect_measure,
        analysis_model=row.analysis_model,
        statistical_method=row.statistical_method,
        ci_level=row.ci_level,
        effect_value=row.effect_value,
        ci_lower=row.ci_lower,
        ci_upper=row.ci_upper,
        prediction_interval=(
            row.prediction_interval if isinstance(row, OverallEstimate) else None
        ),
        heterogeneity=row.heterogeneity,
        effect_test=row.effect_test if isinstance(row, OverallEstimate) else None,
        effect_direction_convention=row.effect_direction_convention,
        subgroup=row.subgroup if isinstance(row, SubgroupEstimate) else None,
    )


def _compact_grade(
    row: SoFRowGRADEAssessment | None,
) -> EvidenceGradeAssessment:
    if row is None:
        return EvidenceGradeAssessment(
            scope=FOUR_DOMAIN_GRADE_SCOPE,
            assessment_status="not_available",
            overall_certainty=None,
        )
    values = row.domain_judgements
    judgements = [
        values.risk_of_bias,
        values.inconsistency,
        values.indirectness,
        values.imprecision,
    ]
    return EvidenceGradeAssessment(
        scope=FOUR_DOMAIN_GRADE_SCOPE,
        assessment_status="available",
        overall_certainty=None,
        domain_judgements=[
            EvidenceGradeJudgement(
                domain=item.domain,
                downgraded=item.downgraded,
                severity=item.severity,
                levels=item.levels,
                level_evaluable=item.level_evaluable,
                rationale=item.rationale,
                assessment_status=item.assessment_status,
            )
            for item in judgements
        ],
    )


def _build_package_status(
    *,
    result: OnlineEBMWorkflowResult,
    included_study_ids: list[str],
    evidence_units: list[EvidenceUnit],
    missing_study_codes: list[str],
) -> EvidencePackageStatus:
    reason_codes = list(missing_study_codes)
    selection_truncated = bool(
        result.study_selection is not None and result.study_selection.truncated
    )
    if selection_truncated:
        reason_codes.append("eligible_studies_not_analyzed_due_to_limit")
    if result.persistence_status in {"partial", "failed"}:
        reason_codes.append("workflow_persistence_failed")
    failed_stages = [stage.stage_name for stage in result.stages if stage.status == "failed"]
    reason_codes.extend(f"{stage}_failed" for stage in failed_stages)

    execution_succeeded = result.status == "succeeded"
    if not execution_succeeded:
        has_evidence = any(
            [
                result.question_pico is not None,
                result.study_screening is not None,
                bool(result.study_pio),
                bool(result.risk_of_bias),
                result.meta_analysis is not None,
                result.grade is not None,
            ]
        )
        evidence_status = "partial" if has_evidence else "failed"
        reason_codes.append("workflow_execution_failed")
        ready = False
    elif result.study_screening is None:
        evidence_status = "partial"
        reason_codes.append("screening_result_missing")
        ready = False
    elif not included_study_ids:
        evidence_status = "no_eligible_studies"
        reason_codes.append("no_eligible_studies")
        ready = True
    elif result.meta_analysis is None:
        evidence_status = "partial"
        reason_codes.append("meta_analysis_missing")
        ready = False
    elif not evidence_units:
        evidence_status = "insufficient_for_synthesis"
        reason_codes.append("no_supported_synthesis_target")
        ready = not missing_study_codes
    elif any(unit.completeness.status == "partial" for unit in evidence_units):
        evidence_status = "partial"
        reason_codes.append("partial_evidence_coverage")
        ready = False
    elif any(
        unit.grade.assessment_status == "not_available"
        and unit.completeness.status == "complete"
        for unit in evidence_units
    ):
        evidence_status = "partial"
        reason_codes.append("grade_assessment_missing")
        ready = False
    elif all(
        unit.completeness.status == "insufficient_for_synthesis"
        for unit in evidence_units
    ):
        evidence_status = "insufficient_for_synthesis"
        reason_codes.append("insufficient_data_for_synthesis")
        ready = not missing_study_codes
    else:
        evidence_status = "complete"
        ready = not missing_study_codes

    if missing_study_codes:
        evidence_status = "partial"
        ready = False
    if selection_truncated:
        evidence_status = "partial"
        ready = False
    return EvidencePackageStatus(
        execution_status=result.status,
        evidence_status=evidence_status,
        ready_for_downstream=ready,
        reason_codes=_unique(reason_codes),
    )


def _status_value(value: EstimationStatus | str | None) -> str | None:
    if isinstance(value, EstimationStatus):
        return value.value
    return str(value) if value is not None else None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
