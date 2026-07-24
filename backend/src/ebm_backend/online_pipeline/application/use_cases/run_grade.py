"""Application orchestration for four-domain GRADE assessment."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

from ebm_backend.online_pipeline.domain.common import EstimationStatus, GradeDomainName
from ebm_backend.online_pipeline.domain.grade import (
    DomainJudgements,
    EffectEstimateRef,
    GRADEDomainJudgement,
    GRADEImprecisionCoverage,
    GRADEImprecisionDataRow,
    GRADEImprecisionEstimate,
    GRADEImprecisionInput,
    GRADEImprecisionSetting,
    GRADEIndirectnessCoverage,
    GRADEIndirectnessEstimate,
    GRADEIndirectnessInput,
    GRADEIndirectnessMappingStatus,
    GRADEIndirectnessSetting,
    GRADEIndirectnessStudyEvidence,
    GRADEInconsistencyCoverage,
    GRADEInconsistencyEstimate,
    GRADEInconsistencyInput,
    GRADEInconsistencySetting,
    GRADEInconsistencyStudyEffect,
    GRADERiskOfBiasCoverage,
    GRADERiskOfBiasDomainEvidence,
    GRADERiskOfBiasDomainSummary,
    GRADERiskOfBiasInput,
    GRADERiskOfBiasSetting,
    GRADERiskOfBiasStudyEvidence,
    GRADERiskOfBiasSummary,
    GradeResult,
    SoFRowGRADEAssessment,
)
from ebm_backend.online_pipeline.domain.meta_analysis import MetaAnalysisResultPackage
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.risk_of_bias import (
    ROB1_DOMAINS,
    RiskOfBiasAssessment,
)
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.application.ports import (
    GRADEImprecisionPort,
    GRADEInconsistencyPort,
    GRADEIndirectnessPort,
    GRADERiskOfBiasPort,
)


GRADE_DOMAIN_ORDER = ("risk_of_bias", "inconsistency", "indirectness", "imprecision")
GRADE_MAX_WORKERS = 4


class RunGrade:
    """Coordinate four independently implemented GRADE domain capabilities."""

    def __init__(
        self,
        *,
        risk_of_bias_assessor: GRADERiskOfBiasPort,
        inconsistency_assessor: GRADEInconsistencyPort,
        indirectness_assessor: GRADEIndirectnessPort,
        imprecision_assessor: GRADEImprecisionPort,
    ) -> None:
        self.domain_assessors = {
            "risk_of_bias": risk_of_bias_assessor,
            "inconsistency": inconsistency_assessor,
            "indirectness": indirectness_assessor,
            "imprecision": imprecision_assessor,
        }

    def execute(
        self,
        *,
        review_id: str,
        question_text: str,
        question_pico: QuestionPICO,
        screening_criteria: ScreeningCriteria,
        study_characteristics: list[StudyPIOCharacteristics],
        risk_of_bias: list[RiskOfBiasAssessment],
        meta_analysis_result: MetaAnalysisResultPackage,
    ) -> GradeResult:
        rows = []
        with ThreadPoolExecutor(max_workers=GRADE_MAX_WORKERS) as executor:
            for setting in meta_analysis_result.analysis_settings:
                estimate_type, estimate = _matched_estimate(setting=setting, meta_analysis_result=meta_analysis_result)
                if estimate is None:
                    continue
                included_study_ids = list(estimate.included_study_ids)
                included_study_id_set = set(included_study_ids)
                filtered_study_characteristics = [
                    item for item in study_characteristics if item.study_id in included_study_id_set
                ]
                filtered_risk_of_bias = [item for item in risk_of_bias if item.study_id in included_study_id_set]
                missing_study_characteristics_ids = [
                    study_id
                    for study_id in included_study_ids
                    if study_id not in {item.study_id for item in filtered_study_characteristics}
                ]
                missing_risk_of_bias_ids = [
                    study_id
                    for study_id in included_study_ids
                    if study_id not in {item.study_id for item in filtered_risk_of_bias}
                ]
                evidence_body = _workflow_evidence_body(
                    setting=setting,
                    estimate=estimate,
                    estimate_type=estimate_type,
                    meta_analysis_result=meta_analysis_result,
                    question_pico=question_pico,
                    screening_criteria=screening_criteria,
                    study_characteristics=filtered_study_characteristics,
                    risk_of_bias=filtered_risk_of_bias,
                    missing_study_characteristics_ids=missing_study_characteristics_ids,
                    missing_risk_of_bias_ids=missing_risk_of_bias_ids,
                )
                grade_risk_of_bias_input = _grade_risk_of_bias_input(
                    setting=setting,
                    estimate=estimate,
                    data_rows=[
                        row
                        for row in meta_analysis_result.meta_analysis_data_rows
                        if row.estimate_id == _estimate_id(
                            estimate=estimate, estimate_type=estimate_type
                        )
                    ],
                    risk_of_bias=filtered_risk_of_bias,
                )
                grade_inconsistency_input = _grade_inconsistency_input(
                    setting=setting,
                    estimate=estimate,
                    estimate_type=estimate_type,
                    meta_analysis_result=meta_analysis_result,
                    study_characteristics=filtered_study_characteristics,
                )
                grade_indirectness_input = _grade_indirectness_input(
                    setting=setting,
                    estimate=estimate,
                    estimate_type=estimate_type,
                    meta_analysis_result=meta_analysis_result,
                    question_pico=question_pico,
                    screening_criteria=screening_criteria,
                    study_characteristics=filtered_study_characteristics,
                )
                grade_imprecision_input = _grade_imprecision_input(
                    setting=setting,
                    estimate=estimate,
                    estimate_type=estimate_type,
                    meta_analysis_result=meta_analysis_result,
                )
                row_context = {
                    "instance_id": f"workflow-grade::{review_id}::{setting.setting_id}",
                    "review_id": review_id,
                    "sof_row_id": f"sof-row::{setting.setting_id}",
                    "question_text": question_text,
                    "question_pico": to_jsonable(question_pico),
                    "screening_criteria": to_jsonable(screening_criteria),
                    "evidence_body": evidence_body,
                    "alignment": {},
                }
                judgements = dict(
                    zip(
                        GRADE_DOMAIN_ORDER,
                        executor.map(
                            lambda domain: _run_grade_domain(
                                domain=domain,
                                assessor=self.domain_assessors[domain],
                                grade_risk_of_bias_input=grade_risk_of_bias_input,
                                grade_inconsistency_input=grade_inconsistency_input,
                                grade_indirectness_input=grade_indirectness_input,
                                grade_imprecision_input=grade_imprecision_input,
                            ),
                            GRADE_DOMAIN_ORDER,
                        ),
                    )
                )
                rows.append(
                    SoFRowGRADEAssessment(
                        sof_row_id=str(row_context["sof_row_id"]),
                        row_label=setting.outcome.label,
                        setting_id=setting.setting_id,
                        setting_family_id=setting.setting_family_id,
                        population_scope=setting.population_scope,
                        comparison=setting.comparison,
                        outcome=setting.outcome,
                        timepoint=setting.timepoint,
                        subgroup=setting.subgroup,
                        effect_estimate_ref=EffectEstimateRef(
                            estimate_type=estimate_type,
                            estimate_id=_estimate_id(
                                estimate=estimate,
                                estimate_type=estimate_type,
                            ),
                            estimation_status=str(estimate.estimation_status),
                        ),
                        included_study_ids=list(estimate.included_study_ids),
                        domain_judgements=DomainJudgements(
                            risk_of_bias=_dataclass_judgement(
                                judgements["risk_of_bias"],
                                GradeDomainName.RISK_OF_BIAS,
                            ),
                            inconsistency=_dataclass_judgement(
                                judgements["inconsistency"],
                                GradeDomainName.INCONSISTENCY,
                            ),
                            indirectness=_dataclass_judgement(
                                judgements["indirectness"],
                                GradeDomainName.INDIRECTNESS,
                            ),
                            imprecision=_dataclass_judgement(
                                judgements["imprecision"],
                                GradeDomainName.IMPRECISION,
                            ),
                        ),
                    )
                )
        return GradeResult(review_id=review_id, question_text=question_text, sof_rows=rows)


def _matched_estimate(*, setting, meta_analysis_result) -> tuple[str, Any | None]:
    if setting.subgroup.is_overall:
        for estimate in meta_analysis_result.overall_estimates:
            if estimate.setting_id == setting.setting_id:
                return "overall", estimate
        return "overall", None
    for estimate in meta_analysis_result.subgroup_estimates:
        if estimate.setting_id == setting.setting_id:
            return "subgroup", estimate
    return "subgroup", None


def _workflow_evidence_body(
    *,
    setting,
    estimate,
    estimate_type: str,
    meta_analysis_result,
    question_pico: QuestionPICO,
    screening_criteria: ScreeningCriteria,
    study_characteristics: list[StudyPIOCharacteristics],
    risk_of_bias: list[RiskOfBiasAssessment],
    missing_study_characteristics_ids: list[str],
    missing_risk_of_bias_ids: list[str],
) -> dict[str, Any]:
    included = set(estimate.included_study_ids)
    study_rows = [
        row
        for row in meta_analysis_result.meta_analysis_data_rows
        if row.setting_id == setting.setting_id and row.study_id in included
    ]
    serialized_study_rows = [to_jsonable(row) for row in study_rows]
    review_scope_pico = {
        "population": list(question_pico.P),
        "intervention": list(question_pico.I),
        "comparator": list(question_pico.C),
        "outcome": list(question_pico.O),
    }
    synthesis_target_pico = _synthesis_target_pico(setting)
    study_pico_projections = _study_pico_projections(
        study_characteristics=study_characteristics,
        study_rows=study_rows,
    )
    return {
        "setting_id": setting.setting_id,
        "setting_family_id": setting.setting_family_id,
        "analysis_setting": to_jsonable(setting),
        "target_pico": to_jsonable(question_pico),
        "review_scope_pico": review_scope_pico,
        "synthesis_target_pico": synthesis_target_pico,
        "screening_criteria": to_jsonable(screening_criteria),
        "effect_estimate_ref": {
            "estimate_type": estimate_type,
            "estimate_id": _estimate_id(estimate=estimate, estimate_type=estimate_type),
            "estimation_status": str(estimate.estimation_status),
        },
        "effect_estimate": to_jsonable(estimate),
        "included_study_ids": list(estimate.included_study_ids),
        "study_characteristics": [to_jsonable(item) for item in study_characteristics],
        "study_characteristics_missing_study_ids": list(missing_study_characteristics_ids),
        "risk_of_bias_assessments": [to_jsonable(item) for item in risk_of_bias],
        "risk_of_bias_missing_study_ids": list(missing_risk_of_bias_ids),
        "meta_analysis_data_rows": serialized_study_rows,
        "evidence_found": {
            "included_study_ids": list(estimate.included_study_ids),
            "study_characteristics_missing_study_ids": list(
                missing_study_characteristics_ids
            ),
            "study_pico_projections": study_pico_projections,
            "meta_analysis_data_rows": serialized_study_rows,
        },
        "subgroup_estimates": [to_jsonable(row) for row in meta_analysis_result.subgroup_estimates if row.setting_family_id == setting.setting_family_id],
        "subgroup_difference_tests": [
            to_jsonable(row)
            for row in meta_analysis_result.subgroup_difference_tests
            if row.setting_family_id == setting.setting_family_id
        ],
    }


def _run_grade_domain(
    *,
    domain: str,
    assessor: Any,
    grade_risk_of_bias_input: GRADERiskOfBiasInput,
    grade_inconsistency_input: GRADEInconsistencyInput,
    grade_indirectness_input: GRADEIndirectnessInput,
    grade_imprecision_input: GRADEImprecisionInput,
) -> dict[str, Any]:
    if domain == "risk_of_bias":
        return assessor.run(grade_input=grade_risk_of_bias_input)
    if domain == "inconsistency":
        return assessor.run(grade_input=grade_inconsistency_input)
    if domain == "indirectness":
        return assessor.run(grade_input=grade_indirectness_input)
    return assessor.run(grade_input=grade_imprecision_input)


def _grade_imprecision_input(
    *,
    setting: Any,
    estimate: Any,
    estimate_type: str,
    meta_analysis_result: MetaAnalysisResultPackage,
) -> GRADEImprecisionInput:
    estimate_id = _estimate_id(estimate=estimate, estimate_type=estimate_type)
    if not estimate_id:
        raise ValueError("Matched GRADE estimate must have an estimate ID")
    expected_ids = list(getattr(estimate, "included_data_row_ids", None) or [])
    rows_by_id: dict[str, Any] = {}
    for row in meta_analysis_result.meta_analysis_data_rows:
        if row.data_row_id not in expected_ids or row.estimate_id != estimate_id:
            continue
        if row.data_row_id in rows_by_id:
            raise ValueError(
                "GRADE imprecision matched estimate contains duplicate DataRow ID: "
                f"{row.data_row_id}"
            )
        rows_by_id[row.data_row_id] = row

    contributing_rows: list[GRADEImprecisionDataRow] = []
    missing_ids: list[str] = []
    for data_row_id in expected_ids:
        row = rows_by_id.get(data_row_id)
        if row is None or row.analysis_status != "included":
            missing_ids.append(data_row_id)
            continue
        if row.data_type != setting.data_type:
            missing_ids.append(data_row_id)
            continue
        contributing_rows.append(
            GRADEImprecisionDataRow(
                data_row_id=row.data_row_id,
                study_id=row.study_id,
                data_type=row.data_type,
                result_data=row.result_data,
            )
        )

    estimation_status = getattr(
        estimate.estimation_status,
        "value",
        estimate.estimation_status,
    )
    available_ids = [item.data_row_id for item in contributing_rows]
    return GRADEImprecisionInput(
        setting=GRADEImprecisionSetting(
            setting_id=setting.setting_id,
            setting_family_id=setting.setting_family_id,
            population=setting.population_scope,
            comparison=setting.comparison,
            outcome=setting.outcome,
            timepoint=setting.timepoint,
            subgroup=setting.subgroup,
            data_type=setting.data_type,
            effect_measure=estimate.effect_measure,
        ),
        estimate=GRADEImprecisionEstimate(
            estimate_type=estimate_type,
            estimate_id=estimate_id,
            estimation_status=str(estimation_status),
            included_study_ids=list(estimate.included_study_ids),
            included_data_row_ids=expected_ids,
            participant_count=int(estimate.participant_count),
            data_type=estimate.data_type,
            effect_measure=estimate.effect_measure,
            ci_level=str(estimate.ci_level),
            pooled_effect=_float_or_none(estimate.effect_value),
            ci_lower=_float_or_none(estimate.ci_lower),
            ci_upper=_float_or_none(estimate.ci_upper),
            effect_direction_convention=getattr(
                estimate,
                "effect_direction_convention",
                None,
            ),
        ),
        contributing_data_rows=contributing_rows,
        coverage=GRADEImprecisionCoverage(
            expected_data_row_ids=expected_ids,
            available_data_row_ids=available_ids,
            missing_data_row_ids=missing_ids,
        ),
    )


def _grade_inconsistency_input(
    *,
    setting: Any,
    estimate: Any,
    estimate_type: str,
    meta_analysis_result: MetaAnalysisResultPackage,
    study_characteristics: list[StudyPIOCharacteristics],
) -> GRADEInconsistencyInput:
    estimate_id = _estimate_id(estimate=estimate, estimate_type=estimate_type)
    if not estimate_id:
        raise ValueError("Matched GRADE estimate must have an estimate ID")
    expected_ids = list(getattr(estimate, "included_data_row_ids", None) or [])
    rows_by_id: dict[str, Any] = {}
    for row in meta_analysis_result.meta_analysis_data_rows:
        if row.data_row_id not in expected_ids or row.estimate_id != estimate_id:
            continue
        if row.data_row_id in rows_by_id:
            raise ValueError(
                "GRADE inconsistency matched estimate contains duplicate DataRow ID: "
                f"{row.data_row_id}"
            )
        rows_by_id[row.data_row_id] = row

    effects: list[GRADEInconsistencyStudyEffect] = []
    missing_ids: list[str] = []
    missing_ci_ids: list[str] = []
    missing_weight_ids: list[str] = []
    for data_row_id in expected_ids:
        row = rows_by_id.get(data_row_id)
        if (
            row is None
            or row.analysis_status != "included"
            or row.effect_value is None
        ):
            missing_ids.append(data_row_id)
            continue
        if row.ci_lower is None or row.ci_upper is None:
            missing_ci_ids.append(data_row_id)
        if row.weight_fraction is None:
            missing_weight_ids.append(data_row_id)
        effects.append(
            GRADEInconsistencyStudyEffect(
                data_row_id=row.data_row_id,
                study_id=row.study_id,
                effect_value=float(row.effect_value),
                ci_lower=_float_or_none(row.ci_lower),
                ci_upper=_float_or_none(row.ci_upper),
                weight_fraction=_float_or_none(row.weight_fraction),
                analysis_scale=row.analysis_scale,
                effect_measure=str(row.effect_measure or estimate.effect_measure),
                comparison=row.comparison,
                outcome=row.outcome,
                subgroup=row.subgroup,
            )
        )

    available_ids = [item.data_row_id for item in effects]
    estimation_status = getattr(
        estimate.estimation_status,
        "value",
        estimate.estimation_status,
    )
    return GRADEInconsistencyInput(
        setting=GRADEInconsistencySetting(
            setting_id=setting.setting_id,
            setting_family_id=setting.setting_family_id,
            population=setting.population_scope,
            comparison=setting.comparison,
            outcome=setting.outcome,
            timepoint=setting.timepoint,
            subgroup=setting.subgroup,
            data_type=setting.data_type,
            effect_measure=estimate.effect_measure,
        ),
        estimate=GRADEInconsistencyEstimate(
            estimate_type=estimate_type,
            estimate_id=estimate_id,
            estimation_status=str(estimation_status),
            included_study_ids=list(estimate.included_study_ids),
            included_data_row_ids=expected_ids,
            study_count=int(estimate.study_count),
            participant_count=int(estimate.participant_count),
            effect_measure=estimate.effect_measure,
            analysis_model=estimate.analysis_model,
            pooled_effect=_float_or_none(estimate.effect_value),
            ci_lower=_float_or_none(estimate.ci_lower),
            ci_upper=_float_or_none(estimate.ci_upper),
            heterogeneity=estimate.heterogeneity,
            prediction_interval=getattr(estimate, "prediction_interval", None),
        ),
        study_effects=effects,
        subgroup_estimates=[
            item
            for item in meta_analysis_result.subgroup_estimates
            if item.setting_family_id == setting.setting_family_id
        ],
        subgroup_difference_tests=[
            item
            for item in meta_analysis_result.subgroup_difference_tests
            if item.setting_family_id == setting.setting_family_id
        ],
        study_characteristics=list(study_characteristics),
        coverage=GRADEInconsistencyCoverage(
            expected_data_row_ids=expected_ids,
            available_data_row_ids=available_ids,
            missing_data_row_ids=missing_ids,
            missing_ci_data_row_ids=missing_ci_ids,
            missing_weight_data_row_ids=missing_weight_ids,
        ),
    )


def _grade_indirectness_input(
    *,
    setting: Any,
    estimate: Any,
    estimate_type: str,
    meta_analysis_result: MetaAnalysisResultPackage,
    question_pico: QuestionPICO,
    screening_criteria: ScreeningCriteria,
    study_characteristics: list[StudyPIOCharacteristics],
) -> GRADEIndirectnessInput:
    estimate_id = _estimate_id(estimate=estimate, estimate_type=estimate_type)
    if not estimate_id:
        raise ValueError("Matched GRADE estimate must have an estimate ID")
    expected_ids = list(getattr(estimate, "included_data_row_ids", None) or [])
    rows_by_id: dict[str, Any] = {}
    for row in meta_analysis_result.meta_analysis_data_rows:
        if row.data_row_id not in expected_ids or row.estimate_id != estimate_id:
            continue
        if row.data_row_id in rows_by_id:
            raise ValueError(
                "GRADE indirectness matched estimate contains duplicate DataRow ID: "
                f"{row.data_row_id}"
            )
        rows_by_id[row.data_row_id] = row

    characteristics_by_study: dict[str, StudyPIOCharacteristics] = {}
    for characteristics in study_characteristics:
        if characteristics.study_id in characteristics_by_study:
            raise ValueError(
                "GRADE indirectness Study PIO must have unique study_id values"
            )
        characteristics_by_study[characteristics.study_id] = characteristics

    study_evidence: list[GRADEIndirectnessStudyEvidence] = []
    missing_ids: list[str] = []
    missing_pio_ids: list[str] = []
    ambiguous_mapping_ids: list[str] = []
    missing_weight_ids: list[str] = []
    for data_row_id in expected_ids:
        row = rows_by_id.get(data_row_id)
        if row is None or row.analysis_status != "included":
            missing_ids.append(data_row_id)
            continue
        characteristics = characteristics_by_study.get(row.study_id)
        if characteristics is None:
            missing_pio_ids.append(data_row_id)
            intervention = comparator = study_outcome = None
            intervention_status = comparator_status = outcome_status = (
                "study_pio_missing"
            )
            timepoint_status = "study_pio_missing"
            candidate_interventions = []
            candidate_comparators = []
            candidate_outcomes = []
            population = None
        else:
            population = characteristics.population
            intervention, intervention_status = _indirectness_unique_label_match(
                characteristics.interventions,
                target=row.comparison.experimental_arm,
                label_name="label",
            )
            comparator, comparator_status = _indirectness_unique_label_match(
                characteristics.comparators,
                target=row.comparison.control_arm,
                label_name="label",
            )
            study_outcome, outcome_status = _indirectness_unique_label_match(
                characteristics.outcomes,
                target=row.outcome.label,
                label_name="outcome_label",
            )
            timepoint_status = _indirectness_timepoint_mapping_status(
                target=row.outcome.timepoint,
                outcome=study_outcome,
                outcome_status=outcome_status,
            )
            candidate_interventions = (
                [] if intervention else list(characteristics.interventions)
            )
            candidate_comparators = (
                [] if comparator else list(characteristics.comparators)
            )
            candidate_outcomes = (
                [] if study_outcome else list(characteristics.outcomes)
            )
        mapping_status = GRADEIndirectnessMappingStatus(
            intervention=intervention_status,
            comparator=comparator_status,
            outcome=outcome_status,
            timepoint=timepoint_status,
        )
        if "ambiguous" in {
            intervention_status,
            comparator_status,
            outcome_status,
            timepoint_status,
        }:
            ambiguous_mapping_ids.append(data_row_id)
        if row.weight_fraction is None:
            missing_weight_ids.append(data_row_id)
        study_evidence.append(
            GRADEIndirectnessStudyEvidence(
                data_row_id=row.data_row_id,
                study_id=row.study_id,
                comparison=row.comparison,
                outcome=row.outcome,
                subgroup=row.subgroup,
                population=population,
                intervention=intervention,
                comparator=comparator,
                study_outcome=study_outcome,
                mapping_status=mapping_status,
                candidate_interventions=candidate_interventions,
                candidate_comparators=candidate_comparators,
                candidate_outcomes=candidate_outcomes,
                effect_value=_float_or_none(row.effect_value),
                ci_lower=_float_or_none(row.ci_lower),
                ci_upper=_float_or_none(row.ci_upper),
                weight_fraction=_float_or_none(row.weight_fraction),
                control_baseline_risk=_control_baseline_risk(row),
            )
        )

    estimation_status = getattr(
        estimate.estimation_status,
        "value",
        estimate.estimation_status,
    )
    available_ids = [item.data_row_id for item in study_evidence]
    return GRADEIndirectnessInput(
        setting=GRADEIndirectnessSetting(
            setting_id=setting.setting_id,
            setting_family_id=setting.setting_family_id,
            population=setting.population_scope,
            comparison=setting.comparison,
            outcome=setting.outcome,
            timepoint=setting.timepoint,
            subgroup=setting.subgroup,
            data_type=setting.data_type,
            effect_measure=estimate.effect_measure,
        ),
        estimate=GRADEIndirectnessEstimate(
            estimate_type=estimate_type,
            estimate_id=estimate_id,
            estimation_status=str(estimation_status),
            included_study_ids=list(estimate.included_study_ids),
            included_data_row_ids=expected_ids,
            study_count=int(estimate.study_count),
            participant_count=int(estimate.participant_count),
            effect_measure=estimate.effect_measure,
            analysis_model=estimate.analysis_model,
            pooled_effect=_float_or_none(estimate.effect_value),
            ci_lower=_float_or_none(estimate.ci_lower),
            ci_upper=_float_or_none(estimate.ci_upper),
        ),
        review_population=list(question_pico.P),
        review_intervention=list(question_pico.I),
        review_comparator=list(question_pico.C),
        review_outcome=list(question_pico.O),
        screening_criteria=screening_criteria,
        study_evidence=study_evidence,
        direct_comparison_status=(
            "pairwise_direct" if available_ids else "unclear"
        ),
        subgroup_estimates=[
            item
            for item in meta_analysis_result.subgroup_estimates
            if item.setting_family_id == setting.setting_family_id
        ],
        subgroup_difference_tests=[
            item
            for item in meta_analysis_result.subgroup_difference_tests
            if item.setting_family_id == setting.setting_family_id
        ],
        coverage=GRADEIndirectnessCoverage(
            expected_data_row_ids=expected_ids,
            available_data_row_ids=available_ids,
            missing_data_row_ids=missing_ids,
            missing_study_pio_data_row_ids=missing_pio_ids,
            ambiguous_mapping_data_row_ids=ambiguous_mapping_ids,
            missing_weight_data_row_ids=missing_weight_ids,
        ),
    )


def _grade_risk_of_bias_input(
    *,
    setting: Any,
    estimate: Any,
    data_rows: list[Any],
    risk_of_bias: list[RiskOfBiasAssessment],
) -> GRADERiskOfBiasInput:
    included_study_ids = list(estimate.included_study_ids)
    included_data_row_ids = list(
        getattr(estimate, "included_data_row_ids", None) or []
    )
    included_data_row_id_set = set(included_data_row_ids)
    expected_estimate_id = getattr(estimate, "overall_estimate_id", None) or getattr(
        estimate,
        "subgroup_estimate_id",
        None,
    )
    matched_rows = [
        row
        for row in data_rows
        if getattr(row, "data_row_id", None) in included_data_row_id_set
        and getattr(row, "estimate_id", None) == expected_estimate_id
    ]
    weight_by_study: dict[str, float] = {}
    rows_have_weights = bool(included_data_row_ids)
    for row in matched_rows:
        if row.analysis_status != "included" or row.weight_fraction is None:
            rows_have_weights = False
            continue
        weight_by_study[row.study_id] = (
            weight_by_study.get(row.study_id, 0.0) + row.weight_fraction
        )
    estimation_status = getattr(
        estimate.estimation_status,
        "value",
        estimate.estimation_status,
    )
    weights_complete = (
        estimation_status == EstimationStatus.COMPUTED.value
        and rows_have_weights
        and len(matched_rows) == len(included_data_row_ids)
        and {row.data_row_id for row in matched_rows}
        == included_data_row_id_set
        and set(weight_by_study) == set(included_study_ids)
        and abs(sum(weight_by_study.values()) - 1.0) <= 0.01
    )
    applied_weight_by_study = weight_by_study if weights_complete else {}
    by_study: dict[str, RiskOfBiasAssessment] = {}
    for assessment in risk_of_bias:
        if assessment.study_id in by_study:
            raise ValueError(
                "GRADE risk_of_bias assessments must have unique study_id values"
            )
        by_study[assessment.study_id] = assessment

    studies = [
        _grade_risk_of_bias_study(by_study[study_id])
        if study_id in by_study and by_study[study_id].domains
        else _missing_grade_risk_of_bias_study(study_id)
        for study_id in included_study_ids
    ]
    studies = [
        replace(
            study,
            contribution_weight=applied_weight_by_study.get(study.study_id),
        )
        for study in studies
    ]
    assessed_study_ids = [
        item.study_id for item in studies if item.rob_available
    ]
    missing = [item.study_id for item in studies if not item.rob_available]
    coverage = GRADERiskOfBiasCoverage(
        expected_study_ids=list(included_study_ids),
        assessed_study_ids=assessed_study_ids,
        missing_rob_study_ids=missing,
        weight_status="complete" if weights_complete else "unavailable",
    )
    return GRADERiskOfBiasInput(
        setting=GRADERiskOfBiasSetting(
            setting_id=setting.setting_id,
            population=str(setting.population_scope),
            comparison=setting.comparison,
            outcome=setting.outcome,
            timepoint=setting.timepoint,
            subgroup=setting.subgroup,
        ),
        contribution_basis="meta_analysis_weight" if weights_complete else "study_count",
        contributing_studies=studies,
        coverage=coverage,
        summary=_summarize_grade_risk_of_bias(studies),
    )


def _grade_risk_of_bias_study(
    assessment: RiskOfBiasAssessment,
) -> GRADERiskOfBiasStudyEvidence:
    domain_ids = [item.domain for item in assessment.domains]
    assessed_domains = list(assessment.assessed_domains or domain_ids)
    unassessed_domains = list(
        assessment.unassessed_domains
        or [domain for domain in ROB1_DOMAINS if domain not in assessed_domains]
    )
    assessed_set = set(assessed_domains)
    core_five = set(ROB1_DOMAINS[:5])
    if assessed_set == set(ROB1_DOMAINS):
        profile = "rob1_full_7"
    elif assessed_set == core_five:
        profile = "rob1_core_5"
    else:
        profile = "rob1_custom"
    return GRADERiskOfBiasStudyEvidence(
        study_id=assessment.study_id,
        contribution_weight=None,
        rob_available=True,
        assessment_scope="article_level",
        assessment_profile=profile,
        assessed_domains=assessed_domains,
        unassessed_domains=unassessed_domains,
        domains=[
            GRADERiskOfBiasDomainEvidence(
                domain=item.domain,
                judgement=item.judgement,
                rationale=item.rationale,
            )
            for item in assessment.domains
        ],
    )


def _missing_grade_risk_of_bias_study(
    study_id: str,
) -> GRADERiskOfBiasStudyEvidence:
    return GRADERiskOfBiasStudyEvidence(
        study_id=study_id,
        contribution_weight=None,
        rob_available=False,
        assessment_scope="article_level",
        assessment_profile="rob1_custom",
        assessed_domains=[],
        unassessed_domains=list(ROB1_DOMAINS),
        domains=[],
    )


def _summarize_grade_risk_of_bias(
    studies: list[GRADERiskOfBiasStudyEvidence],
) -> GRADERiskOfBiasSummary:
    profile_counts: dict[str, int] = {}
    for study in studies:
        if not study.rob_available:
            continue
        profile_counts[study.assessment_profile] = (
            profile_counts.get(study.assessment_profile, 0) + 1
        )

    domain_summaries: list[GRADERiskOfBiasDomainSummary] = []
    for domain_id in ROB1_DOMAINS:
        entries = [
            (study, domain)
            for study in studies
            for domain in study.domains
            if domain.domain == domain_id
        ]
        if not entries:
            continue
        by_judgement = {
            judgement: [
                study
                for study, domain in entries
                if domain.judgement == judgement
            ]
            for judgement in ("low_risk", "unclear_risk", "high_risk")
        }
        use_weights = all(
            study.contribution_weight is not None for study, _ in entries
        )
        domain_summaries.append(
            GRADERiskOfBiasDomainSummary(
                domain=domain_id,
                assessed_study_count=len(entries),
                low_risk_count=len(by_judgement["low_risk"]),
                unclear_risk_count=len(by_judgement["unclear_risk"]),
                high_risk_count=len(by_judgement["high_risk"]),
                low_risk_weight=_judgement_weight(
                    by_judgement["low_risk"], use_weights=use_weights
                ),
                unclear_risk_weight=_judgement_weight(
                    by_judgement["unclear_risk"], use_weights=use_weights
                ),
                high_risk_weight=_judgement_weight(
                    by_judgement["high_risk"], use_weights=use_weights
                ),
                high_risk_study_ids=[
                    item.study_id for item in by_judgement["high_risk"]
                ],
                unclear_risk_study_ids=[
                    item.study_id for item in by_judgement["unclear_risk"]
                ],
            )
        )
    return GRADERiskOfBiasSummary(
        profile_counts=profile_counts,
        domain_summaries=domain_summaries,
    )


def _judgement_weight(
    studies: list[GRADERiskOfBiasStudyEvidence],
    *,
    use_weights: bool,
) -> float | None:
    if not use_weights:
        return None
    return round(
        sum(item.contribution_weight or 0.0 for item in studies),
        6,
    )


def _dataclass_judgement(payload: dict[str, Any], domain: GradeDomainName) -> GRADEDomainJudgement:
    raw_severity = str(payload.get("severity") or "unclear")
    # Accept archived adapters that still emit ``none`` while exposing the
    # canonical GRADE term at the application boundary.
    severity = "not_serious" if raw_severity == "none" else raw_severity
    raw_status = str(payload.get("assessment_status") or "").strip()
    if raw_status in {"completed", "assessed"}:
        assessment_status = "assessed"
    elif raw_status in {
        "single_study_not_estimable",
        "insufficient_evidence",
    }:
        assessment_status = raw_status
    elif raw_status in {"not_evaluable", "unclear"} or severity == "unclear":
        assessment_status = "insufficient_evidence"
    elif (payload.get("decision_features") or {}).get("reason_group") == "single_study":
        assessment_status = "single_study_not_estimable"
    else:
        assessment_status = "assessed"
    return GRADEDomainJudgement(
        domain=domain,
        downgraded=str(payload.get("downgraded") or "unclear"),
        severity=severity,
        levels=payload.get("levels", "unclear"),
        level_evaluable=bool(payload.get("level_evaluable")),
        rationale=str(payload.get("rationale") or ""),
        assessment_status=assessment_status,
        source_spans=[],
    )


def _estimate_id(*, estimate, estimate_type: str) -> str | None:
    return getattr(estimate, "overall_estimate_id", None) if estimate_type == "overall" else getattr(estimate, "subgroup_estimate_id", None)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _synthesis_target_pico(setting: Any) -> dict[str, Any]:
    timepoint = setting.timepoint
    timepoint_value = timepoint.label
    if not timepoint_value and timepoint.target_value is not None:
        unit = f" {timepoint.unit}" if timepoint.unit else ""
        timepoint_value = f"{timepoint.target_value:g}{unit}"
    subgroup = setting.subgroup
    subgroup_value = ""
    if subgroup.factor or subgroup.level:
        subgroup_value = ": ".join(
            value for value in (subgroup.factor, subgroup.level) if value
        )
    return {
        "population": {
            "value": setting.population_scope,
            "source": "analysis_setting.population_scope",
        },
        "intervention": {
            "value": setting.comparison.experimental,
            "source": "analysis_setting.comparison.experimental",
        },
        "comparator": {
            "value": setting.comparison.comparator,
            "source": "analysis_setting.comparison.comparator",
        },
        "outcome": {
            "value": setting.outcome.label,
            "measure": setting.outcome.measure,
            "source": "analysis_setting.outcome",
        },
        "timepoint": {
            "value": timepoint_value or "",
            "source": "analysis_setting.timepoint",
        },
        "subgroup": {
            "value": subgroup_value,
            "source": "analysis_setting.subgroup",
        },
        "setting": {
            "value": str(setting.source_context.get("setting") or ""),
            "source": "analysis_setting.source_context.setting",
        },
    }


def _study_pico_projections(
    *,
    study_characteristics: list[StudyPIOCharacteristics],
    study_rows: list[Any],
) -> list[dict[str, Any]]:
    rows_by_study: dict[str, list[Any]] = {}
    for row in study_rows:
        rows_by_study.setdefault(row.study_id, []).append(row)

    projections: list[dict[str, Any]] = []
    for characteristics in study_characteristics:
        rows = rows_by_study.get(characteristics.study_id) or [None]
        for row in rows:
            projections.append(
                _study_pico_projection(characteristics=characteristics, row=row)
            )
    return projections


def _study_pico_projection(
    *,
    characteristics: StudyPIOCharacteristics,
    row: Any | None,
) -> dict[str, Any]:
    if row is None:
        return {
            "study_id": characteristics.study_id,
            "contribution_to_current_estimate": None,
            "study_pico_for_indirectness": {
                "population": to_jsonable(characteristics.population),
                "intervention": None,
                "comparator": None,
                "outcome": None,
            },
            "mapping_status": {
                "intervention": "missing_result_row",
                "comparator": "missing_result_row",
                "outcome": "missing_result_row",
                "timepoint": "missing_result_row",
            },
            "candidate_interventions": [
                to_jsonable(item) for item in characteristics.interventions
            ],
            "candidate_comparators": [
                to_jsonable(item) for item in characteristics.comparators
            ],
            "candidate_outcomes": [
                to_jsonable(item) for item in characteristics.outcomes
            ],
        }

    intervention, intervention_status = _unique_label_match(
        characteristics.interventions,
        target=row.comparison.experimental_arm,
        label_name="label",
    )
    comparator, comparator_status = _unique_label_match(
        characteristics.comparators,
        target=row.comparison.control_arm,
        label_name="label",
    )
    outcome, outcome_status = _unique_label_match(
        characteristics.outcomes,
        target=row.outcome.label,
        label_name="outcome_label",
    )
    timepoint_status = _timepoint_mapping_status(
        target=row.outcome.timepoint,
        outcome=outcome,
    )
    return {
        "study_id": characteristics.study_id,
        "contribution_to_current_estimate": {
            "experimental_arm": row.comparison.experimental_arm,
            "comparator_arm": row.comparison.control_arm,
            "outcome": row.outcome.label,
            "timepoint": row.outcome.timepoint,
        },
        "study_pico_for_indirectness": {
            "population": to_jsonable(characteristics.population),
            "intervention": to_jsonable(intervention) if intervention else None,
            "comparator": to_jsonable(comparator) if comparator else None,
            "outcome": to_jsonable(outcome) if outcome else None,
        },
        "mapping_status": {
            "intervention": intervention_status,
            "comparator": comparator_status,
            "outcome": outcome_status,
            "timepoint": timepoint_status,
        },
        "candidate_interventions": (
            []
            if intervention
            else [to_jsonable(item) for item in characteristics.interventions]
        ),
        "candidate_comparators": (
            []
            if comparator
            else [to_jsonable(item) for item in characteristics.comparators]
        ),
        "candidate_outcomes": (
            []
            if outcome
            else [to_jsonable(item) for item in characteristics.outcomes]
        ),
    }


def _unique_label_match(
    items: list[Any],
    *,
    target: str | None,
    label_name: str,
) -> tuple[Any | None, str]:
    normalized_target = _normalized_label(target)
    if not normalized_target:
        return None, "target_missing"
    matches = [
        item
        for item in items
        if _normalized_label(getattr(item, label_name, None)) == normalized_target
    ]
    if len(matches) == 1:
        return matches[0], "matched"
    return None, "unresolved"


def _timepoint_mapping_status(*, target: str | None, outcome: Any | None) -> str:
    normalized_target = _normalized_label(target)
    if not normalized_target:
        return "target_missing"
    if outcome is None:
        return "unresolved"
    if any(
        _normalized_label(value) == normalized_target for value in outcome.timepoints
    ):
        return "matched"
    return "unresolved"


def _normalized_label(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _indirectness_unique_label_match(
    items: list[Any],
    *,
    target: str | None,
    label_name: str,
) -> tuple[Any | None, str]:
    normalized_target = _normalized_label(target)
    if not normalized_target:
        return None, "target_missing"
    matches = [
        item
        for item in items
        if _normalized_label(getattr(item, label_name, None)) == normalized_target
    ]
    if len(matches) == 1:
        return matches[0], "matched"
    if len(matches) > 1:
        return None, "ambiguous"
    return None, "not_found"


def _indirectness_timepoint_mapping_status(
    *,
    target: str | None,
    outcome: Any | None,
    outcome_status: str,
) -> str:
    normalized_target = _normalized_label(target)
    if not normalized_target:
        return "target_missing"
    if outcome_status == "ambiguous":
        return "ambiguous"
    if outcome is None:
        return "not_found"
    if any(
        _normalized_label(value) == normalized_target for value in outcome.timepoints
    ):
        return "matched"
    return "not_found"


def _control_baseline_risk(row: Any) -> float | None:
    result_data = getattr(row, "result_data", None)
    control_events = getattr(result_data, "control_events", None)
    control_total = getattr(result_data, "control_total", None)
    if not isinstance(control_events, int) or not isinstance(control_total, int):
        return None
    if control_total <= 0 or not 0 <= control_events <= control_total:
        return None
    return control_events / control_total
