"""Application orchestration for the Meta-analysis workflow."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import math
import re
from typing import Any, Callable

from ebm_backend.online_pipeline.application.ports import (
    AnalysisMethodsPort,
    OverallEstimatesPort,
    StudyEvidencePort,
    SubgroupAnalysisPort,
    SynthesisPlanningPort,
)
from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import DataType, EstimationStatus
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisMethodDecision,
    AnalysisOutcome,
    AnalysisSetting,
    AnalysisSettingExtractionTarget,
    AnalysisSettingStudyCandidate,
    AnalysisSubgroup,
    AnalysisTimepoint,
    CandidateResolutionRecord,
    CandidateStudyResult,
    ContinuousEffectAlignment,
    ContinuousResultData,
    DichotomousResultData,
    GenericInverseVarianceResultData,
    EffectTest,
    HeterogeneitySummary,
    MetaAnalysisResultPackage,
    MetaAnalysisSynthesisPlan,
    OverallEstimate,
    PredictionInterval,
    ResultSelectionPolicy,
    MetaAnalysisDataRow,
    StudyResultComparison,
    StudyResultDerivation,
    StudyResultOutcome,
    StudyResultRow,
    StudyResultSetting,
    SubgroupDifferenceTest,
    SubgroupEstimate,
    SynthesisAnalysisDataset,
    SynthesisTarget,
    UnsupportedSynthesisTarget,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria
from ebm_backend.online_pipeline.domain.serialization import to_jsonable


MAX_ARTICLE_WORKERS = 16


@dataclass(frozen=True)
class MetaAnalysisProgressEvent:
    """Inspectable progress emitted only when an observer is supplied."""

    stage: str
    status: str
    unit_id: str | None = None
    payload: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None


MetaAnalysisProgressObserver = Callable[[MetaAnalysisProgressEvent], None]


class RunMetaAnalysis:
    """Run the frozen plan, candidate extraction, resolution, and synthesis stages."""

    def __init__(
        self,
        *,
        synthesis_planner: SynthesisPlanningPort,
        study_evidence_agent: StudyEvidencePort,
        analysis_methods_selector: AnalysisMethodsPort,
        subgroup_analyzer: SubgroupAnalysisPort,
        overall_estimates_calculator: OverallEstimatesPort,
        max_article_workers: int = 16,
    ) -> None:
        self.synthesis_planner = synthesis_planner
        self.study_evidence_agent = study_evidence_agent
        self.analysis_methods_selector = analysis_methods_selector
        self.subgroup_analyzer = subgroup_analyzer
        self.overall_estimates_calculator = overall_estimates_calculator
        self.max_article_workers = min(MAX_ARTICLE_WORKERS, max(1, max_article_workers))

    def execute(
        self,
        *,
        review_id: str,
        question_text: str,
        question_pico: QuestionPICO,
        screening_criteria: ScreeningCriteria,
        included_studies: list[str],
        articles: list[CleanedArticle],
        synthesis_plan: MetaAnalysisSynthesisPlan | None = None,
        precomputed_study_evidence: dict[str, dict[str, Any]] | None = None,
        progress_observer: MetaAnalysisProgressObserver | None = None,
    ) -> MetaAnalysisResultPackage:
        article_payloads = _validated_article_payloads(
            included_studies=included_studies,
            articles=articles,
        )
        resolved_plan = synthesis_plan or self.plan(
            review_id=review_id,
            question_text=question_text,
            question_pico=question_pico,
            screening_criteria=screening_criteria,
        )
        if resolved_plan.review_id and resolved_plan.review_id != review_id:
            raise ValueError("synthesis_plan review_id does not match the Meta-analysis run")
        plan_payload = to_jsonable(resolved_plan)
        if not isinstance(plan_payload, dict):
            raise TypeError("synthesis_plan must serialize to an object")
        synthesis_plan = resolved_plan
        target_payloads = [
            row for row in plan_payload.get("targets") or [] if isinstance(row, dict)
        ]
        if not target_payloads:
            result = MetaAnalysisResultPackage(
                review_id=review_id,
                synthesis_plan=synthesis_plan,
            )
            _emit_progress(
                progress_observer,
                stage="final_package",
                status="completed",
                payload=to_jsonable(result),
            )
            return result

        evidence = self._analyze_articles(
            review_id=review_id,
            included_studies=included_studies,
            targets=target_payloads,
            article_payloads=article_payloads,
            plan_hash=str(plan_payload.get("plan_hash") or ""),
            precomputed_study_evidence=precomputed_study_evidence,
            progress_observer=progress_observer,
        )
        _emit_progress(
            progress_observer,
            stage="study_evidence_collection",
            status="completed",
            payload={
                "study_ids": [str(item.get("study_id") or "") for item in evidence],
                "coverage": [item["coverage"] for item in evidence],
            },
        )
        raw_rows = [row for item in evidence for row in item["study_result_rows"]]
        resolutions = [
            {
                "target_id": str(record.get("target_id") or ""),
                "study_id": str(record.get("study_id") or ""),
                "record": record,
                "data_row": next(
                    (
                        row
                        for row in item["data_rows"]
                        if str(row.get("resolution_id") or "")
                        == str(record.get("resolution_id") or "")
                    ),
                    None,
                ),
            }
            for item in evidence
            for record in item["resolution_records"]
        ]
        _emit_progress(
            progress_observer,
            stage="candidate_resolution",
            status="completed",
            payload={
                "study_result_rows": raw_rows,
                "resolution_records": [item["record"] for item in resolutions],
                "resolved_data_rows": [
                    item["data_row"] for item in resolutions if item["data_row"] is not None
                ],
            },
        )
        instances, datasets, settings = self._build_analysis_inputs(
            plan=plan_payload,
            targets=target_payloads,
            included_studies=included_studies,
            article_payloads=article_payloads,
            resolutions=resolutions,
            coverage=[item["coverage"] for item in evidence],
        )
        _emit_progress(
            progress_observer,
            stage="analysis_inputs",
            status="completed",
            payload={
                "instances": instances,
                "synthesis_analysis_datasets": to_jsonable(datasets),
                "analysis_settings": settings,
            },
        )
        for instance in instances:
            instance["analysis_methods"] = self.analysis_methods_selector.run(
                instance=instance
            )
            _emit_progress(
                progress_observer,
                stage="analysis_method_selection",
                status="completed",
                unit_id=str(instance.get("instance_id") or ""),
                payload={
                    "instance_id": str(instance.get("instance_id") or ""),
                    "analysis_methods": instance["analysis_methods"],
                },
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_stage = {
                executor.submit(
                    self.subgroup_analyzer.run,
                    instances=instances,
                ): "subgroup_analysis",
                executor.submit(
                    self._calculate_overall_estimates,
                    instances,
                ): "overall_estimation",
            }
            downstream_payloads: dict[str, dict[str, Any]] = {}
            for future in as_completed(future_to_stage):
                stage = future_to_stage[future]
                try:
                    payload = future.result()
                except Exception as exc:
                    _emit_progress(
                        progress_observer,
                        stage=stage,
                        status="failed",
                        error=exc,
                    )
                    raise
                downstream_payloads[stage] = payload
                _emit_progress(
                    progress_observer,
                    stage=stage,
                    status="completed",
                    payload=payload,
                )
        subgroup_payload = downstream_payloads["subgroup_analysis"]
        overall_payload = downstream_payloads["overall_estimation"]

        methods = [
            row
            for instance in instances
            for row in instance.get("analysis_methods") or []
            if isinstance(row, dict)
        ]
        subgroup_estimates: list[dict[str, Any]] = []
        subgroup_data_rows: list[dict[str, Any]] = []
        subgroup_tests: dict[str, dict[str, Any]] = {}
        for instance in instances:
            result = subgroup_payload.get(
                str(instance["instance_id"]),
                {"subgroup_estimates": [], "subgroup_difference_tests": []},
            )
            subgroup_estimates.extend(
                row
                for row in result.get("subgroup_estimates") or []
                if isinstance(row, dict)
            )
            subgroup_data_rows.extend(
                row
                for row in result.get("meta_analysis_data_rows") or []
                if isinstance(row, dict)
            )
            for row in result.get("subgroup_difference_tests") or []:
                if not isinstance(row, dict):
                    continue
                test_id = str(
                    row.get("test_id") or row.get("subgroup_difference_test_id") or ""
                )
                if test_id:
                    subgroup_tests[test_id] = row

        overall_estimates = [
            row
            for result in overall_payload.values()
            for row in result.get("overall_estimates") or []
            if isinstance(row, dict)
        ]
        overall_estimates = _annotate_partial_estimates(
            rows=overall_estimates,
            coverage=[item["coverage"] for item in evidence],
        )
        overall_data_rows = [
            row
            for result in overall_payload.values()
            for row in result.get("meta_analysis_data_rows") or []
            if isinstance(row, dict)
        ]
        data_rows = _finalize_data_rows(
            rows=[
                row
                for instance in instances
                for row in instance.get("meta_analysis_data_rows") or []
                if isinstance(row, dict)
            ],
            enriched_rows=[*subgroup_data_rows, *overall_data_rows],
            methods=methods,
        )
        result = MetaAnalysisResultPackage(
            review_id=review_id,
            synthesis_plan=synthesis_plan,
            candidate_resolution_records=[
                _resolution_record_from_dict(item["record"]) for item in resolutions
            ],
            synthesis_analysis_datasets=datasets,
            analysis_settings=[_analysis_setting_from_dict(row) for row in settings],
            study_result_rows=[_study_result_row_from_dict(row) for row in raw_rows],
            meta_analysis_data_rows=[_data_row_from_dict(row) for row in data_rows],
            analysis_methods=[_analysis_method_from_dict(row) for row in methods],
            subgroup_estimates=[
                _subgroup_estimate_from_dict(row) for row in subgroup_estimates
            ],
            subgroup_difference_tests=[
                _subgroup_difference_test_from_dict(row)
                for row in subgroup_tests.values()
            ],
            overall_estimates=[
                _overall_estimate_from_dict(row) for row in overall_estimates
            ],
        )
        _emit_progress(
            progress_observer,
            stage="final_package",
            status="completed",
            payload=to_jsonable(result),
        )
        return result

    def plan(
        self,
        *,
        review_id: str,
        question_text: str,
        question_pico: QuestionPICO,
        screening_criteria: ScreeningCriteria,
    ) -> MetaAnalysisSynthesisPlan:
        """Create the unchanged result-blind plan for reuse by later stages."""
        plan_payload = self.synthesis_planner.run(
            context={
                "review_id": review_id,
                "question_text": question_text,
                "question_pico": to_jsonable(question_pico),
                "screening_criteria": to_jsonable(screening_criteria),
            }
        )
        if not isinstance(plan_payload, dict):
            raise TypeError("synthesis planner must return an object")
        return _synthesis_plan_from_dict(plan_payload)

    def _analyze_articles(
        self,
        *,
        review_id: str,
        included_studies: list[str],
        targets: list[dict[str, Any]],
        article_payloads: list[dict[str, Any]],
        plan_hash: str,
        precomputed_study_evidence: dict[str, dict[str, Any]] | None = None,
        progress_observer: MetaAnalysisProgressObserver | None = None,
    ) -> list[dict[str, Any]]:
        article_by_study = {
            str(article.get("study_id") or ""): article
            for article in article_payloads
        }

        target_ids = [str(target.get("target_id") or "") for target in targets]
        precomputed = dict(precomputed_study_evidence or {})
        unexpected = sorted(set(precomputed) - set(included_studies))
        if unexpected:
            raise ValueError(
                "Precomputed study evidence contains non-included study IDs: "
                + ", ".join(unexpected)
            )
        results_by_study: dict[str, dict[str, Any]] = {}
        for study_id, value in precomputed.items():
            validated = _validated_study_evidence_result(
                value,
                study_id=study_id,
                target_ids=target_ids,
            )
            results_by_study[study_id] = validated
            _emit_progress(
                progress_observer,
                stage="study_evidence",
                status="reused",
                unit_id=study_id,
                payload=validated,
            )

        def analyze(study_id: str) -> dict[str, Any]:
            try:
                result = self.study_evidence_agent.run(
                    review_id=review_id,
                    targets=targets,
                    study_id=study_id,
                    article=article_by_study[study_id],
                    plan_hash=plan_hash,
                )
                return _validated_study_evidence_result(
                    result,
                    study_id=study_id,
                    target_ids=target_ids,
                )
            except RuntimeError as exc:
                if not _is_article_evidence_technical_error(exc):
                    raise
                return _technical_failure_evidence(
                    study_id=study_id,
                    targets=targets,
                    error=exc,
                )

        pending_studies = [
            study_id for study_id in included_studies if study_id not in results_by_study
        ]
        if not pending_studies:
            return [results_by_study[study_id] for study_id in included_studies]
        workers = min(self.max_article_workers, len(pending_studies))
        if workers <= 1:
            for study_id in pending_studies:
                try:
                    result = analyze(study_id)
                except Exception as exc:
                    _emit_progress(
                        progress_observer,
                        stage="study_evidence",
                        status="failed",
                        unit_id=study_id,
                        error=exc,
                    )
                    raise
                results_by_study[study_id] = result
                _emit_progress(
                    progress_observer,
                    stage="study_evidence",
                    status="completed",
                    unit_id=study_id,
                    payload=result,
                )
            return [results_by_study[study_id] for study_id in included_studies]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_study = {
                executor.submit(analyze, study_id): study_id
                for study_id in pending_studies
            }
            for future in as_completed(future_to_study):
                study_id = future_to_study[future]
                try:
                    result = future.result()
                except Exception as exc:
                    _emit_progress(
                        progress_observer,
                        stage="study_evidence",
                        status="failed",
                        unit_id=study_id,
                        error=exc,
                    )
                    raise
                results_by_study[study_id] = result
                _emit_progress(
                    progress_observer,
                    stage="study_evidence",
                    status="completed",
                    unit_id=study_id,
                    payload=result,
                )
        return [results_by_study[study_id] for study_id in included_studies]

    def _build_analysis_inputs(
        self,
        *,
        plan: dict[str, Any],
        targets: list[dict[str, Any]],
        included_studies: list[str],
        article_payloads: list[dict[str, Any]],
        resolutions: list[dict[str, Any]],
        coverage: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[SynthesisAnalysisDataset], list[dict[str, Any]]]:
        instances: list[dict[str, Any]] = []
        datasets: list[SynthesisAnalysisDataset] = []
        settings: list[dict[str, Any]] = []
        for target in targets:
            target_id = str(target.get("target_id") or "")
            target_resolutions = [
                item for item in resolutions if item["target_id"] == target_id
            ]
            data_rows = [
                item["data_row"]
                for item in target_resolutions
                if item["data_row"] is not None
                and str(item["record"].get("status") or "") == "resolved"
            ]
            contributing = [str(row.get("study_id") or "") for row in data_rows]
            setting = _analysis_setting_payload(
                target=target,
                included_studies=included_studies,
                contributing_studies=contributing,
                article_payloads=article_payloads,
                plan=plan,
            )
            settings.append(setting)
            instance = {
                "instance_id": f"meta-analysis::{plan.get('review_id')}::{target_id}",
                "review_id": plan.get("review_id"),
                "included_studies": contributing,
                "analysis_setting": setting,
                "meta_analysis_data_rows": data_rows,
            }
            instances.append(instance)
            datasets.append(
                _synthesis_dataset(
                    plan=plan,
                    target=target,
                    setting=setting,
                    included_studies=included_studies,
                    resolutions=target_resolutions,
                    data_rows=data_rows,
                    coverage=coverage,
                )
            )
        return instances, datasets, settings

    def _calculate_overall_estimates(
        self,
        instances: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        return {
            str(instance.get("instance_id") or ""): self.overall_estimates_calculator.run(
                instance=instance
            )
            for instance in instances
        }


def _emit_progress(
    observer: MetaAnalysisProgressObserver | None,
    *,
    stage: str,
    status: str,
    unit_id: str | None = None,
    payload: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    if observer is None:
        return
    observer(
        MetaAnalysisProgressEvent(
            stage=stage,
            status=status,
            unit_id=unit_id,
            payload=payload,
            error_type=type(error).__name__ if error is not None else None,
            error_message=str(error) if error is not None else None,
        )
    )


def _validated_study_evidence_result(
    value: dict[str, Any],
    *,
    study_id: str,
    target_ids: list[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Study evidence agent must return an object")
    rows = [row for row in value.get("study_result_rows") or [] if isinstance(row, dict)]
    records = [row for row in value.get("resolution_records") or [] if isinstance(row, dict)]
    data_rows = [row for row in value.get("data_rows") or [] if isinstance(row, dict)]
    coverage = value.get("coverage") if isinstance(value.get("coverage"), dict) else {}
    row_targets = [str(row.get("setting_id") or "") for row in rows]
    record_targets = [str(row.get("target_id") or "") for row in records]
    if row_targets != target_ids or record_targets != target_ids:
        raise ValueError(
            "Study evidence agent must return one ordered row and resolution record per target"
        )
    if any(str(row.get("study_id") or "") != study_id for row in [*rows, *records, *data_rows]):
        raise ValueError("Study evidence agent returned a mismatched study_id")
    coverage = {
        **coverage,
        "study_id": study_id,
        "status": str(coverage.get("status") or "complete"),
    }
    return {
        "study_id": study_id,
        "study_result_rows": rows,
        "resolution_records": records,
        "data_rows": data_rows,
        "coverage": coverage,
    }


def _is_article_evidence_technical_error(error: RuntimeError) -> bool:
    return error.__class__.__name__ in {
        "MetaAnalysisInvocationError",
        "MetaAnalysisOutputError",
    } and hasattr(error, "stage")


def _technical_failure_evidence(
    *,
    study_id: str,
    targets: list[dict[str, Any]],
    error: RuntimeError,
) -> dict[str, Any]:
    stage = str(getattr(error, "stage", "study_evidence_agent"))
    attempts = int(getattr(error, "attempts", 0) or 0)
    failure_code = str(getattr(error, "failure_code", "technical_failure"))
    failure_detail = _bounded_failure_detail(
        getattr(error, "failure_detail", None)
        or getattr(error, "validation_error", None)
        or str(error)
    )
    failure_metadata = {
        "stage": stage,
        "attempts": attempts,
        "retry_exhausted": bool(getattr(error, "retry_exhausted", False)),
        "status_code": getattr(error, "status_code", None),
        "request_id": getattr(error, "request_id", None),
        "attempt_history": getattr(error, "attempt_history", None),
    }
    failure_metadata = {
        key: value for key, value in failure_metadata.items() if value is not None
    }
    failure_summary = (
        f"Article evidence failed with '{failure_code}' at stage '{stage}' "
        f"after {attempts} attempt(s)."
    )
    rows = []
    records = []
    for target in targets:
        target_id = str(target.get("target_id") or "")
        comparison = target.get("comparison") if isinstance(target.get("comparison"), dict) else {}
        outcome = target.get("outcome") if isinstance(target.get("outcome"), dict) else {}
        rows.append(
            {
                "row_id": f"study-result::{_slug(target_id)}::{_slug(study_id)}",
                "setting_id": target_id,
                "study_id": study_id,
                "extraction_status": "technical_failure",
                "data_type": target.get("data_type"),
                "comparison": {
                    "experimental_arm": str(comparison.get("experimental") or ""),
                    "control_arm": str(comparison.get("comparator") or ""),
                },
                "outcome": {
                    "label": str(outcome.get("label") or ""),
                    "timepoint": (target.get("timepoint") or {}).get("label"),
                },
                "subgroup": target.get("subgroup") or {"factor": None, "level": None},
                "missing_reason": "technical_failure",
                "result_items": [],
                "candidate_results": [],
                "study_result_note": failure_summary,
                "extraction_status_reason": failure_code,
                "notes": "",
            }
        )
        records.append(
            {
                "resolution_id": f"resolution::{target_id}::{_slug(study_id)}",
                "target_id": target_id,
                "study_id": study_id,
                "status": "technical_failure",
                "operation": None,
                "contributing_candidate_ids": [],
                "unresolved_candidate_ids": [],
                "applied_rule_ids": [],
                "excluded_candidate_ids": [],
                "reason": failure_summary,
                "dependency_group_id": f"dependency::{target_id}::{_slug(study_id)}",
                "source_spans": [],
                "candidate_dispositions": [],
                "derivation": None,
                "failure_code": failure_code,
                "failure_detail": failure_detail,
                "failure_metadata": failure_metadata,
            }
        )
    return {
        "study_id": study_id,
        "study_result_rows": rows,
        "resolution_records": records,
        "data_rows": [],
        "coverage": {
            "study_id": study_id,
            "status": "technical_failure",
            "failed_stage": stage,
            "attempts": attempts,
            "failure_code": failure_code,
            "failure_detail": failure_detail,
            "failure_metadata": failure_metadata,
            "expected_target_ids": [str(target.get("target_id") or "") for target in targets],
        },
    }


def _bounded_failure_detail(value: object, *, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _annotate_partial_estimates(
    *,
    rows: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    incomplete = [
        row
        for row in coverage
        if str(row.get("status") or "complete") != "complete"
    ]
    if not incomplete:
        return rows
    description = "; ".join(
        f"{row.get('study_id')}={row.get('status')}"
        for row in incomplete
    )
    note = f"Partial evidence coverage: {description}."
    return [
        {
            **row,
            "estimation_notes": " ".join(
                part
                for part in [str(row.get("estimation_notes") or "").strip(), note]
                if part
            ),
        }
        for row in rows
    ]


def _finalize_data_rows(
    *,
    rows: list[dict[str, Any]],
    enriched_rows: list[dict[str, Any]],
    methods: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return one final state for every resolved row in deterministic order."""

    enriched_by_id = {
        str(row.get("data_row_id") or row.get("row_id") or ""): row
        for row in enriched_rows
        if isinstance(row, dict)
    }
    method_by_setting = {
        str(row.get("setting_id") or ""): row
        for row in methods
        if isinstance(row, dict)
    }
    finalized: list[dict[str, Any]] = []
    for row in rows:
        row_id = str(row.get("data_row_id") or row.get("row_id") or "")
        if row_id in enriched_by_id:
            finalized.append(enriched_by_id[row_id])
            continue
        setting_id = str(row.get("setting_id") or "")
        setting_subgroup = row.get("subgroup") if isinstance(row.get("subgroup"), dict) else {}
        scope = "subgroup" if setting_subgroup.get("factor") or setting_subgroup.get("level") else "overall"
        estimate_prefix = "subgroup-estimate" if scope == "subgroup" else "overall-estimate"
        method = method_by_setting.get(setting_id) or {}
        finalized.append(
            {
                **row,
                "data_row_id": row_id,
                "method_id": method.get("method_id"),
                "estimate_id": f"{estimate_prefix}::{setting_id}",
                "estimate_scope": scope,
                "analysis_status": "not_analyzed",
                "analysis_exclusion_reason": "statistical_adapter_returned_no_data_row",
                "effect_measure": method.get("effect_measure"),
                "analysis_model": method.get("analysis_model"),
                "statistical_method": method.get("statistical_method"),
            }
        )
    ordered = sorted(finalized, key=lambda row: str(row.get("data_row_id") or ""))
    if any(str(row.get("analysis_status") or "pending") == "pending" for row in ordered):
        raise ValueError("Final Meta-analysis data rows must not remain pending")
    weights_by_estimate: dict[str, list[float]] = {}
    for row in ordered:
        if str(row.get("analysis_status") or "") != "included":
            continue
        estimate_id = str(row.get("estimate_id") or "")
        weight = _optional_float(row.get("weight_fraction"))
        if not estimate_id or weight is None:
            raise ValueError("Included Meta-analysis data rows require estimate_id and weight_fraction")
        weights_by_estimate.setdefault(estimate_id, []).append(weight)
    for estimate_id, weights in weights_by_estimate.items():
        if abs(sum(weights) - 1.0) > 1e-6:
            raise ValueError(
                f"Meta-analysis data-row weights for {estimate_id} must sum to 1"
            )
    return ordered


def _analysis_setting_payload(
    *,
    target: dict[str, Any],
    included_studies: list[str],
    contributing_studies: list[str],
    article_payloads: list[dict[str, Any]],
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    target_id = str(target.get("target_id") or "")
    contributing_set = set(contributing_studies)
    source_context: dict[str, Any] = {
        "setting_definition": {
            "planned_effect_measure": target.get("effect_measure_plan"),
            "clinical_model_assumption": _model_assumption(target),
            "continuous_result_frame_priority": (
                (target.get("result_selection_policy") or {}).get(
                    "continuous_result_frame_priority"
                )
                if isinstance(target.get("result_selection_policy"), dict)
                else []
            ),
        }
    }
    if plan is not None:
        source_context["synthesis_plan"] = {
            "plan_id": plan.get("plan_id"),
            "plan_version": plan.get("version"),
            "plan_hash": plan.get("plan_hash"),
            "target_id": target_id,
        }
    return {
        "setting_id": target_id,
        "setting_family_id": str(target.get("setting_family_id") or target_id),
        "population_scope": str(target.get("population_scope") or ""),
        "comparison": target.get("comparison") or {},
        "outcome": target.get("outcome") or {},
        "timepoint": target.get("timepoint") or {"label": None},
        "subgroup": target.get("subgroup") or {"factor": None, "level": None},
        "data_type": target.get("data_type"),
        "eligible_study_ids": list(contributing_studies),
        "eligible_study_candidates": _study_candidates(
            setting_id=target_id,
            study_ids=contributing_studies,
            article_payloads=article_payloads,
        ),
        "excluded_study_ids": [
            study_id for study_id in included_studies if study_id not in contributing_set
        ],
        "source_context": source_context,
        "notes": str(target.get("notes") or ""),
    }


def _model_assumption(target: dict[str, Any]) -> str:
    value = str(target.get("analysis_model_plan") or "").casefold()
    if value in {"fixed", "fixed_effect", "common", "common_effect"}:
        return "common_effect"
    if value in {"random", "random_effects", "varying", "varying_effects"}:
        return "varying_effects"
    return "uncertain"


def _study_candidates(
    *,
    setting_id: str,
    study_ids: list[str],
    article_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    article_by_study = {str(row.get("study_id") or ""): row for row in article_payloads}
    return [
        {
            "study_id": study_id,
            "article_id": (article_by_study.get(study_id) or {}).get("article_id"),
            "extraction_task_id": f"target::{setting_id}::{_slug(study_id)}",
            "extraction_targets": [
                {
                    "target_id": f"target::{setting_id}::{_slug(study_id)}",
                    "extraction_hint": None,
                }
            ],
        }
        for study_id in study_ids
        if study_id in article_by_study
    ]


def _synthesis_dataset(
    *,
    plan: dict[str, Any],
    target: dict[str, Any],
    setting: dict[str, Any],
    included_studies: list[str],
    resolutions: list[dict[str, Any]],
    data_rows: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> SynthesisAnalysisDataset:
    selected = [_data_row_from_dict(row) for row in data_rows]
    excluded_candidate_ids = [
        candidate_id
        for item in resolutions
        for candidate_id in item["record"].get("excluded_candidate_ids") or []
    ]
    unresolved_candidate_ids = [
        str(candidate_id)
        for item in resolutions
        for candidate_id in item["record"].get("unresolved_candidate_ids") or []
    ]
    status_counts: dict[str, int] = {}
    for item in resolutions:
        status = str(item["record"].get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    selected_studies = {row.study_id for row in selected}
    coverage_by_study = {
        str(row.get("study_id") or ""): str(row.get("status") or "unknown")
        for row in coverage
    }
    failure_by_study = {
        str(row.get("study_id") or ""): {
            "failure_code": row.get("failure_code"),
            "failure_detail": row.get("failure_detail"),
            **(
                row.get("failure_metadata")
                if isinstance(row.get("failure_metadata"), dict)
                else {}
            ),
        }
        for row in coverage
        if row.get("failure_code")
    }
    incomplete_study_ids = [
        study_id
        for study_id in included_studies
        if coverage_by_study.get(study_id, "unknown") != "complete"
    ]
    target_id = str(target.get("target_id") or "")
    return SynthesisAnalysisDataset(
        dataset_id=f"analysis-dataset::{target_id}",
        plan_id=str(plan.get("plan_id") or ""),
        plan_version=str(plan.get("version") or ""),
        target_id=target_id,
        analysis_setting=_analysis_setting_from_dict(setting),
        data_row_ids=[row.data_row_id for row in selected],
        excluded_study_ids=[
            study_id for study_id in included_studies if study_id not in selected_studies
        ],
        excluded_candidate_ids=_unique(excluded_candidate_ids),
        unresolved_candidate_ids=_unique(unresolved_candidate_ids),
        resolution_summary={
            **status_counts,
            "expected_study_count": len(included_studies),
            "resolved_study_count": len(selected_studies),
            "incomplete_coverage_study_count": len(incomplete_study_ids),
        },
        provenance={
            "plan_hash": plan.get("plan_hash"),
            "resolution_ids": [item["record"].get("resolution_id") for item in resolutions],
            "coverage_by_study": coverage_by_study,
            "incomplete_coverage_study_ids": incomplete_study_ids,
            "technical_failures_by_study": failure_by_study,
        },
    )


def _data_row_from_dict(row: dict[str, Any]) -> MetaAnalysisDataRow:
    items = row.get("result_items") if isinstance(row.get("result_items"), list) else []
    candidate = items[0] if items and isinstance(items[0], dict) else {}
    data_type = _data_type(row.get("data_type"))
    data = row.get("result_data") if isinstance(row.get("result_data"), dict) else {}
    comparison = row.get("comparison") if isinstance(row.get("comparison"), dict) else {}
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    subgroup = row.get("subgroup") if isinstance(row.get("subgroup"), dict) else {}
    resolution_id = str(row.get("resolution_id") or candidate.get("resolution_reason") or "")
    return MetaAnalysisDataRow(
        data_row_id=str(row.get("data_row_id") or row.get("row_id") or ""),
        setting_id=str(row.get("setting_id") or ""),
        setting_family_id=str(row.get("setting_family_id") or row.get("setting_id") or ""),
        study_id=str(row.get("study_id") or ""),
        study_year=_optional_text(row.get("study_year")),
        data_type=data_type,
        comparison=StudyResultComparison(
            experimental_arm=str(comparison.get("experimental_arm") or ""),
            control_arm=str(comparison.get("control_arm") or ""),
        ),
        outcome=StudyResultOutcome(
            label=str(outcome.get("label") or ""),
            timepoint=_optional_text(outcome.get("timepoint")),
        ),
        subgroup=_analysis_subgroup(subgroup),
        result_data=_result_data(data, data_type=data_type),
        source_candidate_ids=_text_list(
            row.get("source_candidate_ids") or candidate.get("source_candidate_ids")
        ),
        resolution_id=resolution_id,
        method_id=_optional_text(row.get("method_id")),
        estimate_id=_optional_text(row.get("estimate_id")),
        estimate_scope=_optional_text(row.get("estimate_scope")),
        resolution_operation=str(candidate.get("resolution_operation") or "selected"),
        derivation=_derivation(
            row.get("derivation")
            if isinstance(row.get("derivation"), dict)
            else candidate.get("derivation")
            if isinstance(candidate.get("derivation"), dict)
            else None
        ),
        continuous_effect_alignment=_continuous_effect_alignment(
            row.get("continuous_effect_alignment")
            or candidate.get("continuous_effect_alignment")
        ),
        source_spans=_source_spans(candidate.get("source_spans") or row.get("source_spans")),
        analysis_status=str(row.get("analysis_status") or "pending"),
        analysis_exclusion_reason=_optional_text(row.get("analysis_exclusion_reason")),
        participant_count=int(row.get("participant_count") or 0),
        effect_measure=_optional_text(row.get("effect_measure")),
        analysis_model=_optional_text(row.get("analysis_model")),
        statistical_method=_optional_text(row.get("statistical_method")),
        analysis_effect=_optional_float(row.get("analysis_effect")),
        analysis_scale=_optional_text(row.get("analysis_scale")),
        effect_value=_optional_float(row.get("effect_value")),
        ci_lower=_optional_float(row.get("ci_lower")),
        ci_upper=_optional_float(row.get("ci_upper")),
        variance=_optional_float(row.get("variance")),
        standard_error=_optional_float(row.get("standard_error")),
        weight=_optional_float(row.get("weight")),
        weight_fraction=_optional_float(row.get("weight_fraction")),
        analysis_notes=_optional_text(row.get("analysis_notes")),
    )


def _validated_article_payloads(
    *,
    included_studies: list[str],
    articles: list[CleanedArticle],
) -> list[dict[str, Any]]:
    if len(set(included_studies)) != len(included_studies):
        raise ValueError("included_studies must not contain duplicate study IDs")
    articles_by_study: dict[str, CleanedArticle] = {}
    for article in articles:
        if article.study_id in articles_by_study:
            raise ValueError(f"Multiple articles were provided for study_id '{article.study_id}'")
        articles_by_study[article.study_id] = article
    missing = [study_id for study_id in included_studies if study_id not in articles_by_study]
    if missing:
        raise ValueError(f"Missing CleanedArticle for included study_id(s): {', '.join(missing)}")
    return [_article_payload(articles_by_study[study_id]) for study_id in included_studies]


def _article_payload(article: CleanedArticle) -> dict[str, Any]:
    payload = to_jsonable(article)
    payload["article_id"] = article.study_id
    payload["tables"] = [_table_payload(table) for table in article.tables]
    return payload


def _table_payload(table: Any) -> dict[str, Any]:
    raw_xml = str(getattr(table, "raw_xml", "") or "").strip() or None
    if raw_xml is None:
        # Compatibility for articles serialized before ArticleTable.raw_xml was
        # part of the domain contract.
        raw_xml = next(
            (
                str(row.get("_raw_xml"))
                for row in table.rows
                if isinstance(row, dict) and row.get("_raw_xml")
            ),
            None,
        )
    return {
        "table_id": table.table_id,
        "caption": table.caption,
        "raw_xml": raw_xml,
        "rows": to_jsonable(table.rows),
    }


def _synthesis_plan_from_dict(row: dict[str, Any]) -> MetaAnalysisSynthesisPlan:
    return MetaAnalysisSynthesisPlan(
        plan_id=str(row.get("plan_id") or ""),
        review_id=str(row.get("review_id") or ""),
        version=str(row.get("version") or ""),
        status=str(row.get("status") or ""),
        plan_hash=str(row.get("plan_hash") or ""),
        targets=[
            _synthesis_target_from_dict(item)
            for item in row.get("targets") or []
            if isinstance(item, dict)
        ],
        unsupported_targets=[
            UnsupportedSynthesisTarget(
                outcome_label=str(item.get("outcome_label") or ""),
                data_type=str(item.get("data_type") or ""),
                reason=str(item.get("reason") or ""),
                reason_code=str(item.get("reason_code") or "unsupported_data_type"),
            )
            for item in row.get("unsupported_targets") or []
            if isinstance(item, dict)
        ],
        screening_criteria_snapshot=(
            row.get("screening_criteria_snapshot")
            if isinstance(row.get("screening_criteria_snapshot"), dict)
            else {}
        ),
        rationale=str(row.get("rationale") or ""),
    )


def _synthesis_target_from_dict(row: dict[str, Any]) -> SynthesisTarget:
    comparison = row.get("comparison") if isinstance(row.get("comparison"), dict) else {}
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    timepoint = row.get("timepoint") if isinstance(row.get("timepoint"), dict) else {}
    subgroup = row.get("subgroup") if isinstance(row.get("subgroup"), dict) else {}
    selection = (
        row.get("result_selection_policy")
        if isinstance(row.get("result_selection_policy"), dict)
        else {}
    )
    return SynthesisTarget(
        target_id=str(row.get("target_id") or ""),
        setting_family_id=str(row.get("setting_family_id") or ""),
        population_scope=str(row.get("population_scope") or ""),
        comparison=AnalysisComparison(
            experimental=str(comparison.get("experimental") or ""),
            comparator=str(comparison.get("comparator") or ""),
        ),
        outcome=AnalysisOutcome(
            label=str(outcome.get("label") or ""),
            measure=_optional_text(outcome.get("measure")),
        ),
        timepoint=_analysis_timepoint(timepoint),
        subgroup=_analysis_subgroup(subgroup),
        data_type=_data_type(row.get("data_type")),
        result_selection_policy=ResultSelectionPolicy(
            acceptable_outcome_measures=_text_list(
                selection.get("acceptable_outcome_measures")
            ),
            outcome_measure_priority=_text_list(
                selection.get("outcome_measure_priority")
            ),
            analysis_population_priority=_text_list(
                selection.get("analysis_population_priority")
            ),
            continuous_result_frame_priority=_text_list(
                selection.get("continuous_result_frame_priority")
            ),
            statistic_type_priority=_text_list(
                selection.get("statistic_type_priority")
            ),
            source_priority=_text_list(selection.get("source_priority")),
            tie_policy=str(selection.get("tie_policy") or "unresolved"),
            decision_basis={
                str(key): str(value)
                for key, value in (
                    selection.get("decision_basis")
                    if isinstance(selection.get("decision_basis"), dict)
                    else {}
                ).items()
            },
        ),
        effect_measure_plan=_optional_text(row.get("effect_measure_plan")),
        analysis_model_plan=str(row.get("analysis_model_plan") or ""),
        notes=str(row.get("notes") or ""),
    )


def _resolution_record_from_dict(row: dict[str, Any]) -> CandidateResolutionRecord:
    return CandidateResolutionRecord(
        resolution_id=str(row.get("resolution_id") or ""),
        target_id=str(row.get("target_id") or ""),
        study_id=str(row.get("study_id") or ""),
        status=str(row.get("status") or ""),
        operation=_optional_text(row.get("operation")),
        contributing_candidate_ids=_text_list(
            row.get("contributing_candidate_ids")
        ),
        unresolved_candidate_ids=_text_list(row.get("unresolved_candidate_ids")),
        applied_rule_ids=_text_list(row.get("applied_rule_ids")),
        excluded_candidate_ids=_text_list(row.get("excluded_candidate_ids")),
        reason=str(row.get("reason") or ""),
        dependency_group_id=_optional_text(row.get("dependency_group_id")),
        source_spans=_source_spans(row.get("source_spans")),
        candidate_dispositions=[
            item
            for item in row.get("candidate_dispositions") or []
            if isinstance(item, dict)
        ],
        derivation=_derivation(
            row.get("derivation") if isinstance(row.get("derivation"), dict) else None
        ),
        failure_code=_optional_text(row.get("failure_code")),
        failure_detail=_optional_text(row.get("failure_detail")),
        failure_metadata=(
            dict(row.get("failure_metadata"))
            if isinstance(row.get("failure_metadata"), dict)
            else {}
        ),
    )


def _analysis_setting_from_dict(row: dict[str, Any]) -> AnalysisSetting:
    comparison = row.get("comparison") or {}
    outcome = row.get("outcome") or {}
    timepoint = row.get("timepoint") or {}
    subgroup = row.get("subgroup") or {}
    return AnalysisSetting(
        setting_id=str(row.get("setting_id") or ""),
        setting_family_id=str(row.get("setting_family_id") or ""),
        population_scope=str(row.get("population_scope") or ""),
        comparison=AnalysisComparison(
            experimental=str(comparison.get("experimental") or ""),
            comparator=str(comparison.get("comparator") or ""),
        ),
        outcome=AnalysisOutcome(
            label=str(outcome.get("label") or ""),
            measure=_optional_text(outcome.get("measure")),
        ),
        timepoint=_analysis_timepoint(timepoint),
        subgroup=_analysis_subgroup(subgroup),
        data_type=_data_type(row.get("data_type")),
        eligible_study_ids=_text_list(row.get("eligible_study_ids")),
        eligible_study_candidates=_analysis_setting_study_candidates(
            row.get("eligible_study_candidates")
        ),
        excluded_study_ids=_text_list(row.get("excluded_study_ids")),
        source_context=row.get("source_context") if isinstance(row.get("source_context"), dict) else {},
        notes=str(row.get("notes") or ""),
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
        missing_reason=_optional_text(row.get("missing_reason")),
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
        subgroup=_analysis_subgroup(subgroup),
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
                    reported_statistic_type=_optional_text(
                        setting.get("reported_statistic_type")
                    ),
                    analysis_input_representation=_optional_text(
                        setting.get("analysis_input_representation")
                    ),
                    reported_statistic_kinds=_text_list(
                        setting.get("reported_statistic_kinds")
                    ),
                    statistic_type_status=_optional_text(
                        setting.get("statistic_type_status")
                    ),
                    population_or_subgroup=_optional_text(setting.get("population_or_subgroup")),
                    analysis_population=_optional_text(setting.get("analysis_population")),
                    experimental_arm_label=_optional_text(setting.get("experimental_arm_label")),
                    control_arm_label=_optional_text(setting.get("control_arm_label")),
                    continuous_result_frame=_optional_text(
                        setting.get("continuous_result_frame")
                    ),
                    change_score_definition=_optional_text(
                        setting.get("change_score_definition")
                    ),
                    table_local_notes=_optional_text(setting.get("table_local_notes")),
                ),
                data_type=data_type,
                result_data=(
                    _optional_result_data(result_data, data_type=data_type)
                    if result_data is not None
                    else None
                ),
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


def _analysis_method_from_dict(row: dict[str, Any]) -> AnalysisMethodDecision:
    method_status = str(
        row.get("method_status")
        or ("ready" if row.get("status") == "supported" else "insufficient_data")
    )
    return AnalysisMethodDecision(
        method_id=str(row.get("method_id") or ""),
        setting_id=str(row.get("setting_id") or ""),
        data_type=_data_type(row.get("data_type")),
        effect_measure=str(row.get("effect_measure") or ""),
        analysis_model=str(row.get("analysis_model") or ""),
        statistical_method=str(row.get("statistical_method") or ""),
        ci_level=str(row.get("ci_level") or "95%"),
        status=str(row.get("status") or "supported"),
        method_status=method_status,
        analysis_included_study_ids=_text_list(row.get("analysis_included_study_ids")),
        analysis_excluded_studies=[item for item in row.get("analysis_excluded_studies") or [] if isinstance(item, dict)],
        heterogeneity_estimator=_optional_text(row.get("heterogeneity_estimator")),
        interval_method=str(
            row.get("interval_method")
            or ("Wald" if method_status in {"ready", "insufficient_data"} else "")
        ),
        prediction_interval_enabled=bool(row.get("prediction_interval_enabled")),
        statistical_policy_id=str(
            row.get("statistical_policy_id") or "cochrane_revman_v1"
        ),
        zero_cell_handling=row.get("zero_cell_handling") if isinstance(row.get("zero_cell_handling"), dict) else None,
        smd_method=_optional_text(row.get("smd_method")),
        rationale=str(row.get("rationale") or ""),
    )


def _overall_estimate_from_dict(row: dict[str, Any]) -> OverallEstimate:
    return OverallEstimate(
        overall_estimate_id=str(row.get("overall_estimate_id") or ""),
        setting_id=str(row.get("setting_id") or ""),
        setting_family_id=str(row.get("setting_family_id") or ""),
        method_id=str(row.get("method_id") or ""),
        included_study_ids=_text_list(row.get("included_study_ids")),
        included_data_row_ids=_text_list(row.get("included_data_row_ids")),
        study_count=int(row.get("study_count") or 0),
        participant_count=int(row.get("participant_count") or 0),
        data_type=_data_type(row.get("data_type")),
        effect_measure=str(row.get("effect_measure") or ""),
        analysis_model=str(row.get("analysis_model") or ""),
        statistical_method=str(row.get("statistical_method") or ""),
        ci_level=str(row.get("ci_level") or "95%"),
        estimation_status=_estimation_status(row.get("estimation_status")),
        interval_method=str(row.get("interval_method") or "Wald"),
        effect_value=row.get("effect_value"),
        ci_lower=row.get("ci_lower"),
        ci_upper=row.get("ci_upper"),
        prediction_interval=_prediction_interval(row.get("prediction_interval")),
        heterogeneity=_heterogeneity(row.get("heterogeneity")),
        effect_test=_effect_test(row.get("effect_test")),
        effect_direction_convention=_optional_text(
            row.get("effect_direction_convention")
        ),
        estimation_notes=_optional_text(row.get("estimation_notes")),
    )


def _subgroup_estimate_from_dict(row: dict[str, Any]) -> SubgroupEstimate:
    subgroup = row.get("subgroup") or {}
    return SubgroupEstimate(
        subgroup_estimate_id=str(row.get("subgroup_estimate_id") or ""),
        setting_id=str(row.get("setting_id") or ""),
        setting_family_id=str(row.get("setting_family_id") or ""),
        method_id=str(row.get("method_id") or ""),
        subgroup=_analysis_subgroup(subgroup),
        included_study_ids=_text_list(row.get("included_study_ids")),
        included_data_row_ids=_text_list(row.get("included_data_row_ids")),
        study_count=int(row.get("study_count") or 0),
        participant_count=int(row.get("participant_count") or 0),
        data_type=_data_type(row.get("data_type")),
        effect_measure=str(row.get("effect_measure") or ""),
        analysis_model=str(row.get("analysis_model") or ""),
        statistical_method=str(row.get("statistical_method") or ""),
        ci_level=str(row.get("ci_level") or "95%"),
        estimation_status=_estimation_status(row.get("estimation_status")),
        interval_method=str(row.get("interval_method") or "Wald"),
        effect_value=row.get("effect_value"),
        ci_lower=row.get("ci_lower"),
        ci_upper=row.get("ci_upper"),
        heterogeneity=_heterogeneity(row.get("heterogeneity")),
        effect_direction_convention=_optional_text(
            row.get("effect_direction_convention")
        ),
        estimation_notes=_optional_text(row.get("estimation_notes")),
    )


def _subgroup_difference_test_from_dict(row: dict[str, Any]) -> SubgroupDifferenceTest:
    comparison = row.get("comparison") if isinstance(row.get("comparison"), dict) else {}
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    timepoint = row.get("timepoint") if isinstance(row.get("timepoint"), dict) else {}
    return SubgroupDifferenceTest(
        test_id=str(row.get("subgroup_difference_test_id") or row.get("test_id") or ""),
        setting_family_id=str(row.get("setting_family_id") or ""),
        subgroup_factor=str(row.get("subgroup_factor") or ""),
        compared_subgroup_estimate_ids=_text_list(row.get("level_estimate_ids")),
        test_status=str(row.get("test_status") or "not_applicable"),
        chi2=row.get("chi2"),
        df=row.get("df"),
        p_value=row.get("p_value"),
        i2_between_subgroups=row.get("i2_between_subgroups"),
        comparison=(AnalysisComparison(experimental=str(comparison.get("experimental") or ""), comparator=str(comparison.get("comparator") or "")) if comparison else None),
        outcome=(AnalysisOutcome(label=str(outcome.get("label") or ""), measure=_optional_text(outcome.get("measure"))) if outcome else None),
        timepoint=_analysis_timepoint(timepoint) if timepoint else None,
        data_type=_data_type(row.get("data_type")) if row.get("data_type") else None,
        effect_measure=str(row.get("effect_measure") or ""),
        test_method=_optional_text(row.get("test_method")),
        subgroup_scope=_optional_text(row.get("subgroup_scope")),
        level_a=_optional_text(row.get("level_a")),
        level_b=_optional_text(row.get("level_b")),
        paired_study_ids=_text_list(row.get("paired_study_ids")),
        paired_study_count=int(row.get("paired_study_count") or 0),
        interaction_effect_value=row.get("interaction_effect_value"),
        interaction_ci_lower=row.get("interaction_ci_lower"),
        interaction_ci_upper=row.get("interaction_ci_upper"),
        interaction_scale=_optional_text(row.get("interaction_scale")),
        interaction_heterogeneity=_heterogeneity(
            row.get("interaction_heterogeneity")
        ),
        notes=_optional_text(row.get("test_notes")) or _optional_text(row.get("notes")),
    )


def _analysis_setting_study_candidates(value: Any) -> list[AnalysisSettingStudyCandidate]:
    if not isinstance(value, list):
        return []
    candidates = []
    for row in value:
        if not isinstance(row, dict):
            continue
        targets = [
            AnalysisSettingExtractionTarget(
                target_id=str(target.get("target_id") or ""),
                extraction_hint=_optional_text(target.get("extraction_hint")),
            )
            for target in row.get("extraction_targets") or []
            if isinstance(target, dict)
        ]
        candidates.append(
            AnalysisSettingStudyCandidate(
                study_id=str(row.get("study_id") or ""),
                article_id=_optional_text(row.get("article_id")),
                extraction_task_id=_optional_text(row.get("extraction_task_id")),
                extraction_targets=targets,
            )
        )
    return candidates


def _derivation(value: dict[str, Any] | None) -> StudyResultDerivation | None:
    if not value:
        return None
    return StudyResultDerivation(
        method=str(value.get("method") or "direct"),
        computed_fields=_text_list(value.get("computed_fields")),
        input_values=value.get("input_values") if isinstance(value.get("input_values"), dict) else {},
        formula=_optional_text(value.get("formula")),
        notes=_optional_text(value.get("notes")),
    )


def _continuous_effect_alignment(value: Any) -> ContinuousEffectAlignment | None:
    if not isinstance(value, dict):
        return None
    multiplier = value.get("effect_multiplier")
    return ContinuousEffectAlignment(
        result_frame=str(value.get("result_frame") or "unclear"),
        change_score_definition=str(
            value.get("change_score_definition") or "unclear"
        ),
        scale_direction=_optional_text(value.get("scale_direction")),
        effect_multiplier=(
            int(multiplier) if multiplier in {-1, 1, -1.0, 1.0} else None
        ),
        status=str(value.get("status") or "uncertain"),
        rationale=str(value.get("rationale") or ""),
    )


def _source_spans(value: Any) -> list[Any]:
    if isinstance(value, list):
        result = []
        for item in value:
            if not isinstance(item, dict):
                continue
            span = _source_span(item)
            if span is not None:
                result.append(span)
        return result
    if isinstance(value, dict):
        span = _source_span(value)
        return [span] if span is not None else []
    return []


def _source_span(value: dict[str, Any]):
    from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan

    source_id = _optional_text(value.get("source_id")) or _optional_text(value.get("article_id")) or _optional_text(value.get("candidate_id")) or ""
    text = (
        _optional_text(value.get("text"))
        or _optional_text(value.get("quote"))
        or _optional_text(value.get("evidence"))
        or ""
    )
    if not source_id and not text:
        return None
    return EvidenceSourceSpan(
        source_id=source_id,
        text=text,
        section=_optional_text(value.get("section")),
        page=_optional_text(value.get("page")),
        table_id=_optional_text(value.get("table_id")),
    )


def _result_data(data: dict[str, Any], *, data_type: DataType):
    if data_type == DataType.DICHOTOMOUS:
        return DichotomousResultData(
            experimental_events=_required_integer(data.get("experimental_events")),
            experimental_total=_required_integer(data.get("experimental_total")),
            control_events=_required_integer(data.get("control_events")),
            control_total=_required_integer(data.get("control_total")),
        )
    if _is_giv_result_data(data):
        participant_count = data.get("participant_count")
        return GenericInverseVarianceResultData(
            effect_value=_required_number(data.get("effect_value")),
            standard_error=_required_number(data.get("standard_error")),
            effect_measure=str(data.get("effect_measure") or ""),
            analysis_scale=str(data.get("analysis_scale") or "natural"),
            participant_count=(
                _required_integer(participant_count)
                if participant_count is not None
                else None
            ),
        )
    return ContinuousResultData(
        experimental_mean=_required_number(data.get("experimental_mean")),
        experimental_sd=_required_number(data.get("experimental_sd")),
        experimental_total=_required_integer(data.get("experimental_total")),
        control_mean=_required_number(data.get("control_mean")),
        control_sd=_required_number(data.get("control_sd")),
        control_total=_required_integer(data.get("control_total")),
    )


def _is_giv_result_data(data: dict[str, Any]) -> bool:
    return "effect_value" in data or "standard_error" in data


def _optional_result_data(data: dict[str, Any], *, data_type: DataType):
    try:
        return _result_data(data, data_type=data_type)
    except (TypeError, ValueError):
        return None


def _required_number(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("Boolean values are not valid numeric result data")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Result data must be finite")
    return number


def _required_integer(value: Any) -> int:
    number = _required_number(value)
    if not number.is_integer():
        raise ValueError("Counts and sample sizes must be integers")
    return int(number)


def _analysis_timepoint(value: dict[str, Any]) -> AnalysisTimepoint:
    return AnalysisTimepoint(
        label=_optional_text(value.get("label")),
        strategy=_optional_text(value.get("strategy")),
        target_value=_optional_float(value.get("target_value")),
        window_start=_optional_float(value.get("window_start")),
        window_end=_optional_float(value.get("window_end")),
        unit=_optional_text(value.get("unit")),
        anchor=_optional_text(value.get("anchor")),
        basis=_optional_text(value.get("basis")),
        rationale=str(value.get("rationale") or ""),
    )


def _analysis_subgroup(value: dict[str, Any]) -> AnalysisSubgroup:
    return AnalysisSubgroup(
        factor=_optional_text(value.get("factor")),
        level=_optional_text(value.get("level")),
        scope=_optional_text(value.get("scope")),
        membership_relation=_optional_text(value.get("membership_relation")),
    )


def _data_type(value: Any) -> DataType:
    raw = value.value if isinstance(value, DataType) else str(value)
    try:
        return DataType(raw)
    except ValueError as exc:
        raise ValueError(
            "Meta-analysis supports only Dichotomous or Continuous data_type; "
            f"received {raw!r}"
        ) from exc


def _estimation_status(value: Any) -> EstimationStatus:
    normalized = str(value or "").strip().lower()
    for status in EstimationStatus:
        if normalized == status.value:
            return status
    return EstimationStatus.INSUFFICIENT_DATA


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
        i2_method=_optional_text(value.get("i2_method")),
    )


def _effect_test(value: Any) -> EffectTest | None:
    if not isinstance(value, dict):
        return None
    statistic_name = str(value.get("statistic_name") or ("z" if value.get("z") is not None else "t"))
    statistic_value = value.get("statistic_value")
    if statistic_value is None:
        statistic_value = value.get("z") if value.get("z") is not None else value.get("t")
    p_value = value.get("p_value")
    if statistic_value is None or p_value is None:
        return None
    return EffectTest(
        statistic_name=statistic_name,
        statistic_value=statistic_value,
        p_value=p_value,
        df=value.get("df"),
    )


def _text_list(value: Any) -> list[str]:
    result: list[str] = []
    for item in value if isinstance(value, list) else []:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
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
