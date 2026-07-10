"""Meta-analysis module-level method coordinator."""

from __future__ import annotations

import re
from typing import Any

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import DataType, EstimationStatus
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSetting,
    AnalysisSubgroup,
    AnalysisTimepoint,
    CandidateStudyResult,
    ContinuousResultData,
    DichotomousResultData,
    HeterogeneitySummary,
    MetaAnalysisResultPackage,
    OverallEstimate,
    PredictionInterval,
    StudyResultDerivation,
    StudyResultSetting,
    StudyResultComparison,
    StudyResultOutcome,
    StudyResultRow,
    SubgroupDifferenceTest,
    SubgroupEstimate,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.base import MetaAnalysisMethod
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.loader import get_meta_analysis_subtask_method


class Method(MetaAnalysisMethod):
    """Coordinate independently implemented meta-analysis subtasks."""

    def __init__(self, *, subtask_method_name: str = "method_test") -> None:
        self.subtask_method_name = subtask_method_name
        self.study_results_method = get_meta_analysis_subtask_method("study_results", subtask_method_name)
        self.analysis_methods_method = get_meta_analysis_subtask_method("analysis_methods", subtask_method_name)
        self.subgroup_analysis_method = get_meta_analysis_subtask_method("subgroup_analysis", subtask_method_name)
        self.overall_estimates_method = get_meta_analysis_subtask_method("overall_estimates", subtask_method_name)

    def run(
        self,
        *,
        review_id: str,
        question_text: str,
        question_pico: QuestionPICO,
        included_studies: list[str],
        articles: list[CleanedArticle],
        study_characteristics: list[StudyPIOCharacteristics],
    ) -> MetaAnalysisResultPackage:
        instance = _workflow_instance(
            review_id=review_id,
            question_pico=question_pico,
            included_studies=included_studies,
        )
        article_payloads = [_article_payload(article) for article in articles]
        instance = {
            **instance,
            "study_result_targets": _study_result_targets(
                instance=instance,
                article_payloads=article_payloads,
            ),
        }
        study_result_rows = self.study_results_method.run(instance=instance, articles=article_payloads)
        estimable_rows = flatten_estimable_candidate_rows(study_result_rows)
        analysis_methods = self.analysis_methods_method.run(instance={**instance, "study_result_rows": estimable_rows})
        instance = {**instance, "study_result_rows": estimable_rows, "analysis_methods": analysis_methods}
        subgroup_payload = self.subgroup_analysis_method.run(instances=[instance])
        subgroup_results = subgroup_payload.get(str(instance["instance_id"]), {"subgroup_estimates": [], "subgroup_difference_tests": []})
        overall_estimates = self.overall_estimates_method.run(instance=instance)
        setting = _analysis_setting_from_dict(instance["analysis_setting"])
        return MetaAnalysisResultPackage(
            review_id=review_id,
            analysis_settings=[setting],
            study_result_rows=[_study_result_row_from_dict(row) for row in estimable_rows],
            subgroup_estimates=[_subgroup_estimate_from_dict(row) for row in subgroup_results.get("subgroup_estimates") or []],
            subgroup_difference_tests=[
                _subgroup_difference_test_from_dict(row)
                for row in subgroup_results.get("subgroup_difference_tests") or []
            ],
            overall_estimates=[_overall_estimate_from_dict(row) for row in overall_estimates],
        )


def _workflow_instance(*, review_id: str, question_pico: QuestionPICO, included_studies: list[str]) -> dict[str, Any]:
    population = ", ".join(question_pico.P) or "review population"
    intervention = ", ".join(question_pico.I) or "intervention"
    comparator = ", ".join(question_pico.C) or "comparator"
    outcome = ", ".join(question_pico.O) or "outcome"
    setting_id = f"setting::{review_id}::default::overall"
    return {
        "instance_id": f"meta-analysis::{review_id}::default",
        "review_id": review_id,
        "included_studies": list(included_studies),
        "analysis_setting": {
            "setting_id": setting_id,
            "setting_family_id": f"setting-family::{review_id}::default",
            "candidate_id": f"candidate::{review_id}::default",
            "review_id": review_id,
            "analysis_group": "default",
            "analysis_number": "1",
            "analysis_name": outcome,
            "analysis_group_name": f"{intervention} versus {comparator}",
            "population_scope": {"label": population, "source": "question_pico"},
            "comparison": {
                "experimental": intervention,
                "comparator": comparator,
                "text": f"{intervention} versus {comparator}",
            },
            "outcome": {"label": outcome, "measure": None, "benefit_direction": None},
            "timepoint": {"label": None, "window": None},
            "subgroup": {"factor": None, "level": None, "source": "overall"},
            "data_type": "Dichotomous",
            "effect_measure": "Risk Ratio",
            "eligible_study_ids": list(included_studies),
            "source": {"method": "method_test"},
        },
    }


def _article_payload(article: CleanedArticle) -> dict[str, Any]:
    return {
        "study_id": article.study_id,
        "article_id": article.study_id,
        "metadata": to_jsonable(article.metadata),
        "tables": [_table_payload(table) for table in article.tables],
    }


def _table_payload(table) -> dict[str, Any]:
    rows = table.rows
    if rows and isinstance(rows[0], dict):
        rows = [[str(value) for value in row.values()] for row in rows]
    return {"table_id": table.table_id, "caption": table.caption, "rows": rows}


def _study_result_targets(*, instance: dict[str, Any], article_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    setting = instance.get("analysis_setting") or {}
    setting_id = str(setting.get("setting_id") or instance.get("instance_id") or "setting")
    article_by_study = {str(article.get("study_id") or ""): article for article in article_payloads}
    targets = []
    for study_id in instance.get("included_studies") or []:
        study_id_text = str(study_id)
        article = article_by_study.get(study_id_text)
        if not article:
            continue
        targets.append(
            {
                "target_id": f"target::{setting_id}::{_slug(study_id_text)}",
                "setting_id": setting_id,
                "study_id": study_id_text,
                "article_id": article.get("article_id"),
            }
        )
    return targets


def _analysis_setting_from_dict(row: dict[str, Any]) -> AnalysisSetting:
    comparison = row.get("comparison") or {}
    outcome = row.get("outcome") or {}
    timepoint = row.get("timepoint") or {}
    subgroup = row.get("subgroup") or {}
    return AnalysisSetting(
        setting_id=str(row.get("setting_id") or ""),
        setting_family_id=str(row.get("setting_family_id") or ""),
        candidate_id=str(row.get("candidate_id") or ""),
        comparison=AnalysisComparison(
            experimental=str(comparison.get("experimental") or ""),
            comparator=str(comparison.get("comparator") or ""),
        ),
        outcome=AnalysisOutcome(label=str(outcome.get("label") or ""), measure=_optional_text(outcome.get("measure"))),
        timepoint=AnalysisTimepoint(label=_optional_text(timepoint.get("label"))),
        subgroup=AnalysisSubgroup(
            factor=_optional_text(subgroup.get("factor")),
            level=_optional_text(subgroup.get("level")),
        ),
        data_type=_data_type(row.get("data_type")),
        eligible_study_ids=[str(study_id) for study_id in row.get("eligible_study_ids") or []],
    )


def _study_result_row_from_dict(row: dict[str, Any]) -> StudyResultRow:
    comparison = row.get("comparison") or {}
    outcome = row.get("outcome") or {}
    subgroup = row.get("subgroup") or {}
    data_type = _data_type(row.get("data_type"))
    result_items_raw = row.get("result_items") if isinstance(row.get("result_items"), list) else None
    candidate_results_raw = row.get("candidate_results") if isinstance(row.get("candidate_results"), list) else None
    result_items = _candidate_results(result_items_raw or candidate_results_raw or [], default_data_type=data_type)
    candidate_results = _candidate_results(candidate_results_raw or result_items_raw or [], default_data_type=data_type)
    return StudyResultRow(
        row_id=str(row.get("row_id") or ""),
        extraction_task_id=_optional_text(row.get("extraction_task_id")),
        setting_id=str(row.get("setting_id") or ""),
        study_id=str(row.get("study_id") or ""),
        study_year=_optional_text(row.get("study_year")),
        extraction_status=str(row.get("extraction_status") or "extracted"),
        data_type=data_type,
        comparison=StudyResultComparison(
            experimental_arm=str(comparison.get("experimental_arm") or ""),
            control_arm=str(comparison.get("control_arm") or ""),
        ),
        outcome=StudyResultOutcome(
            label=str(outcome.get("label") or ""),
            timepoint=_optional_text(outcome.get("timepoint")),
        ),
        subgroup=AnalysisSubgroup(
            factor=_optional_text(subgroup.get("factor")),
            level=_optional_text(subgroup.get("level")),
        ),
        source_spans=_source_spans(row.get("source_spans") or row.get("source")),
        result_items=result_items,
        candidate_results=candidate_results,
        study_result_note=_optional_text(row.get("study_result_note")),
        extraction_status_reason=_optional_text(row.get("extraction_status_reason")),
        notes=str(row.get("notes") or ""),
    )


def _candidate_results(rows: list[Any], *, default_data_type: DataType) -> list[CandidateStudyResult]:
    candidates = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        data_type = _data_type(row.get("data_type") or default_data_type)
        result_data = row.get("result_data") if isinstance(row.get("result_data"), dict) else None
        setting = row.get("study_result_setting") if isinstance(row.get("study_result_setting"), dict) else {}
        derivation = row.get("derivation") if isinstance(row.get("derivation"), dict) else None
        candidates.append(
            CandidateStudyResult(
                candidate_id=str(row.get("candidate_id") or f"candidate::{index}"),
                match_status=str(row.get("match_status") or "candidate"),
                study_result_setting=StudyResultSetting(
                    row_label=_optional_text(setting.get("row_label")),
                    outcome_label=_optional_text(setting.get("outcome_label")),
                    outcome_measure=_optional_text(setting.get("outcome_measure")),
                    timepoint=_optional_text(setting.get("timepoint")),
                    statistic_type=_optional_text(setting.get("statistic_type")),
                    population_or_subgroup=_optional_text(setting.get("population_or_subgroup")),
                    experimental_arm_label=_optional_text(setting.get("experimental_arm_label")),
                    control_arm_label=_optional_text(setting.get("control_arm_label")),
                    table_local_notes=_optional_text(setting.get("table_local_notes")),
                ),
                data_type=data_type,
                result_data=_result_data(result_data, data_type=data_type) if result_data is not None else None,
                include_in_estimate=_optional_bool(row.get("include_in_estimate")),
                analysis_disposition=_optional_text(row.get("analysis_disposition")),
                resolution_reason=_optional_text(row.get("resolution_reason")),
                derivation=_derivation(derivation),
                source_spans=_source_spans(row.get("source_spans") or row.get("source")),
                confidence=_optional_text(row.get("confidence")),
                study_local_note=_optional_text(row.get("study_local_note")),
                study_local_result=row.get("study_local_result") if isinstance(row.get("study_local_result"), dict) else {},
                setting_alignment=row.get("setting_alignment") if isinstance(row.get("setting_alignment"), dict) else {},
                numeric_extraction=row.get("numeric_extraction") if isinstance(row.get("numeric_extraction"), dict) else {},
                note=_optional_text(row.get("note")) or _optional_text(row.get("reason")),
            )
        )
    return candidates


def flatten_estimable_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for row in rows:
        candidates = [
            candidate
            for candidate in ((row.get("result_items") if isinstance(row.get("result_items"), list) else None) or row.get("candidate_results") or [])
            if isinstance(candidate, dict)
        ]
        estimable = [
            candidate
            for candidate in candidates
            if (
                str(candidate.get("analysis_disposition") or "") == "ready_for_estimate"
                or (candidate.get("include_in_estimate") is True and not candidate.get("analysis_disposition"))
            )
            and isinstance(candidate.get("result_data"), dict)
        ]
        if not estimable:
            continue
        for index, candidate in enumerate(estimable):
            flattened.append(_row_from_candidate(row=row, candidate=candidate, index=index))
    return flattened


def _row_from_candidate(*, row: dict[str, Any], candidate: dict[str, Any], index: int) -> dict[str, Any]:
    setting = candidate.get("study_result_setting") if isinstance(candidate.get("study_result_setting"), dict) else {}
    comparison = row.get("comparison") if isinstance(row.get("comparison"), dict) else {}
    experimental = setting.get("experimental_arm_label") or comparison.get("experimental_arm")
    control = setting.get("control_arm_label") or comparison.get("control_arm")
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    row_id = f"{row.get('row_id') or 'row'}::candidate::{index}"
    return {
        **row,
        "row_id": row_id,
        "extraction_status": "extracted",
        "comparison": {
            **comparison,
            "experimental_arm": experimental,
            "control_arm": control,
        },
        "outcome": {
            **outcome,
            "label": setting.get("outcome_label") or outcome.get("label"),
            "timepoint": setting.get("timepoint") or outcome.get("timepoint"),
        },
        "source": candidate.get("source") or row.get("source") or {},
        "result_items": [candidate],
        "candidate_results": [candidate],
    }


def _derivation(value: dict[str, Any] | None) -> StudyResultDerivation | None:
    if not value:
        return None
    computed = value.get("computed_fields") if isinstance(value.get("computed_fields"), list) else []
    inputs = value.get("input_values") if isinstance(value.get("input_values"), dict) else {}
    return StudyResultDerivation(
        method=str(value.get("method") or "direct"),
        computed_fields=[str(item) for item in computed],
        input_values=inputs,
        formula=_optional_text(value.get("formula")),
        notes=_optional_text(value.get("notes")),
    )


def _source_spans(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [
            _source_span(item)
            for item in value
            if isinstance(item, dict)
        ]
    if isinstance(value, dict):
        span = _source_span(value)
        return [span] if span is not None else []
    return []


def _source_span(value: dict[str, Any]):
    from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan

    source_id = _optional_text(value.get("source_id")) or _optional_text(value.get("article_id")) or _optional_text(value.get("candidate_id")) or ""
    text = _optional_text(value.get("text")) or _optional_text(value.get("evidence")) or ""
    if not source_id and not text:
        return None
    return EvidenceSourceSpan(
        source_id=source_id,
        text=text,
        section=_optional_text(value.get("section")),
        page=_optional_text(value.get("page")),
        table_id=_optional_text(value.get("table_id")),
    )


def _overall_estimate_from_dict(row: dict[str, Any]) -> OverallEstimate:
    return OverallEstimate(
        overall_estimate_id=str(row.get("overall_estimate_id") or ""),
        setting_id=str(row.get("setting_id") or ""),
        setting_family_id=str(row.get("setting_family_id") or ""),
        method_id=str(row.get("method_id") or ""),
        candidate_id=str(row.get("candidate_id") or ""),
        included_study_ids=[str(study_id) for study_id in row.get("included_study_ids") or []],
        study_count=int(row.get("study_count") or 0),
        participant_count=int(row.get("participant_count") or 0),
        data_type=_data_type(row.get("data_type")),
        effect_measure=str(row.get("effect_measure") or ""),
        analysis_model=str(row.get("analysis_model") or ""),
        statistical_method=str(row.get("statistical_method") or ""),
        ci_level=str(row.get("ci_level") or "95%"),
        estimation_status=_estimation_status(row.get("estimation_status")),
        effect_value=row.get("effect_value"),
        ci_lower=row.get("ci_lower"),
        ci_upper=row.get("ci_upper"),
        prediction_interval=_prediction_interval(row.get("prediction_interval")),
        heterogeneity=_heterogeneity(row.get("heterogeneity")),
    )


def _subgroup_estimate_from_dict(row: dict[str, Any]) -> SubgroupEstimate:
    subgroup = row.get("subgroup") or {}
    return SubgroupEstimate(
        subgroup_estimate_id=str(row.get("subgroup_estimate_id") or ""),
        setting_id=str(row.get("setting_id") or ""),
        setting_family_id=str(row.get("setting_family_id") or ""),
        method_id=str(row.get("method_id") or ""),
        candidate_id=str(row.get("candidate_id") or ""),
        subgroup=AnalysisSubgroup(
            factor=_optional_text(subgroup.get("factor")),
            level=_optional_text(subgroup.get("level")),
        ),
        included_study_ids=[str(study_id) for study_id in row.get("included_study_ids") or []],
        study_count=int(row.get("study_count") or 0),
        participant_count=int(row.get("participant_count") or 0),
        data_type=_data_type(row.get("data_type")),
        effect_measure=str(row.get("effect_measure") or ""),
        analysis_model=str(row.get("analysis_model") or ""),
        statistical_method=str(row.get("statistical_method") or ""),
        ci_level=str(row.get("ci_level") or "95%"),
        estimation_status=_estimation_status(row.get("estimation_status")),
        effect_value=row.get("effect_value"),
        ci_lower=row.get("ci_lower"),
        ci_upper=row.get("ci_upper"),
        heterogeneity=_heterogeneity(row.get("heterogeneity")),
    )


def _subgroup_difference_test_from_dict(row: dict[str, Any]) -> SubgroupDifferenceTest:
    return SubgroupDifferenceTest(
        test_id=str(row.get("subgroup_difference_test_id") or row.get("test_id") or ""),
        setting_family_id=str(row.get("setting_family_id") or ""),
        subgroup_factor=str(row.get("subgroup_factor") or ""),
        compared_subgroup_estimate_ids=[str(item) for item in row.get("level_estimate_ids") or []],
        test_status=str(row.get("test_status") or "not_applicable"),
        chi2=row.get("chi2"),
        df=row.get("df"),
        p_value=row.get("p_value"),
        i2_between_subgroups=row.get("i2_between_subgroups"),
    )


def _result_data(data: dict[str, Any], *, data_type: DataType):
    if data_type == DataType.DICHOTOMOUS:
        return DichotomousResultData(
            experimental_events=int(data.get("experimental_events") or 0),
            experimental_total=int(data.get("experimental_total") or 0),
            control_events=int(data.get("control_events") or 0),
            control_total=int(data.get("control_total") or 0),
        )
    return ContinuousResultData(
        experimental_mean=float(data.get("experimental_mean") or 0.0),
        experimental_sd=float(data.get("experimental_sd") or 0.0),
        experimental_total=int(data.get("experimental_total") or 0),
        control_mean=float(data.get("control_mean") or 0.0),
        control_sd=float(data.get("control_sd") or 0.0),
        control_total=int(data.get("control_total") or 0),
    )


def _data_type(value: Any) -> DataType:
    return DataType.CONTINUOUS if str(value) == DataType.CONTINUOUS.value else DataType.DICHOTOMOUS


def _estimation_status(value: Any) -> EstimationStatus:
    return EstimationStatus.COMPUTED if value else EstimationStatus.INSUFFICIENT_DATA


def _prediction_interval(value: Any) -> PredictionInterval | None:
    if not isinstance(value, dict):
        return None
    return PredictionInterval(lower=value.get("lower"), upper=value.get("upper"))


def _heterogeneity(value: Any) -> HeterogeneitySummary | None:
    if not isinstance(value, dict):
        return None
    return HeterogeneitySummary(
        tau2=value.get("tau2"),
        chi2=value.get("chi2"),
        df=value.get("df"),
        p_value=value.get("p_value"),
        i2=value.get("i2"),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return cleaned or "study"


def build_method(method_name: str = "method_test") -> Method:
    return Method(subtask_method_name=method_name)
