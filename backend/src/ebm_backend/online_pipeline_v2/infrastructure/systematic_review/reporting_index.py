"""Build a compact, deterministic reading index for final Review reporting."""

from __future__ import annotations

from collections import Counter
import json
from typing import Any, Mapping

from ebm_backend.online_pipeline_v2.infrastructure.persistence.filesystem import (
    digest_tag,
)


def build_reporting_index(
    files: Mapping[str, bytes], *, review_path: str
) -> dict[str, Any]:
    """Summarize navigation facts without replacing the source artifacts."""

    index: dict[str, Any] = {
        "schema_version": "systematic-review-reporting-index.v2",
        "review_path": review_path,
        "source_files": [
            {
                "path": name,
                "sha256": digest_tag(content),
                "size_bytes": len(content),
                "reading_role": _reading_role(name),
            }
            for name, content in sorted(files.items())
        ],
        "stages": {},
        "display_candidates": [],
    }
    search = _object(files, "review-context/search.json")
    selection = _object(files, "review-context/selection.json")
    index["stages"]["search"] = _search_summary(search)
    index["stages"]["selection"] = _selection_summary(selection)
    index["display_candidates"].append(
        _candidate(
            "selection-flow",
            "selection_flow",
            "review-context/reporting-index.json",
            (),
        )
    )
    if review_path == "evidence_review":
        study_data = _object(files, "study-data/study-data-collection.json")
        risk = _object(files, "study-data/risk-of-bias.json")
        synthesis = _object(files, "analysis-data/synthesis.json")
        sof = _object(files, "certainty/summary-of-findings.json")
        index["stages"].update(
            {
                "study_data": _study_data_summary(study_data),
                "risk_of_bias": _risk_summary(risk),
                "synthesis": _synthesis_summary(synthesis),
                "certainty": _sof_summary(sof),
            }
        )
        index["display_candidates"].extend(
            (
                _candidate(
                    "study-characteristics",
                    "study_characteristics",
                    "study-data/study-data-collection.json",
                    _ids(study_data.get("studies"), "study_id"),
                ),
                _candidate(
                    "risk-of-bias",
                    "risk_of_bias",
                    "study-data/risk-of-bias.json",
                    _ids(risk.get("assessments"), "assessment_id"),
                ),
                _candidate(
                    "individual-results",
                    "individual_results",
                    "analysis-data/synthesis.json",
                    _ids(synthesis.get("analyses"), "analysis_id"),
                ),
                _candidate(
                    "synthesis-results",
                    "synthesis_results",
                    "analysis-data/synthesis.json",
                    _ids(synthesis.get("analyses"), "analysis_id"),
                ),
                _candidate(
                    "summary-of-findings",
                    "summary_of_findings",
                    "certainty/summary-of-findings.json",
                    _ids(sof.get("tables"), "table_id"),
                ),
            )
        )
    return index


def _search_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    runs = _records(value.get("search_runs"))
    manifest_summary = _mapping(_mapping(value.get("manifest")).get("summary"))
    return {
        "record_count": int(manifest_summary.get("record_count", len(_records(value.get("records"))))),
        "source_count": int(manifest_summary.get("source_count", len(runs))),
        "sources": [
            {
                "search_run_id": run.get("search_run_id"),
                "source_name": run.get("source_name"),
                "platform": run.get("platform"),
                "status": run.get("status"),
                "executed_at": run.get("executed_at"),
                "result_count": run.get("result_count"),
                "retrieved_count": run.get("retrieved_count"),
                "status_reason": run.get("status_reason"),
            }
            for run in runs
        ],
        "limitations": list(value.get("limitations") or ()),
    }


def _selection_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    screenings = _records(value.get("record_screening"))
    evidence = _records(value.get("report_evidence"))
    decisions = _records(value.get("study_decisions"))
    reports = {
        str(item.get("report_id")): item
        for item in _records(value.get("reports"))
        if item.get("report_id")
    }
    links = _records(value.get("study_report_links"))
    classifications = Counter(str(item.get("classification")) for item in decisions)
    return {
        "source_record_count": len(screenings),
        "duplicate_record_count": sum(
            item.get("duplicate_of_record_id") is not None for item in screenings
        ),
        "records_advanced_count": sum(
            bool(item.get("advances_to_report_assessment")) for item in screenings
        ),
        "reports_sought_count": len(_records(value.get("reports"))),
        "reports_not_retrieved_count": sum(
            not bool(item.get("accessed")) for item in evidence
        ),
        "reports_assessed_count": sum(bool(item.get("accessed")) for item in evidence),
        "study_count": len(_records(value.get("studies"))),
        "classifications": dict(sorted(classifications.items())),
        "unresolved_conflict_count": len(_records(value.get("conflicts"))),
        "studies": [
            {
                "study_id": study.get("study_id"),
                "display_name": study.get("display_name"),
                "classification": next(
                    (
                        item.get("classification")
                        for item in decisions
                        if item.get("study_id") == study.get("study_id")
                    ),
                    None,
                ),
            }
            for study in _records(value.get("studies"))
        ],
        "study_references": [
            _study_reference_group(study, decisions, links, reports)
            for study in _records(value.get("studies"))
        ],
        "limitations": list(value.get("limitations") or ()),
    }


def _study_reference_group(
    study: Mapping[str, Any],
    decisions: list[Mapping[str, Any]],
    links: list[Mapping[str, Any]],
    reports: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    study_id = study.get("study_id")
    decision = next(
        (item for item in decisions if item.get("study_id") == study_id), {}
    )
    study_links = [item for item in links if item.get("study_id") == study_id]
    return {
        "study_id": study_id,
        "display_name": study.get("display_name"),
        "classification": decision.get("classification"),
        "decision_reason": decision.get("reason"),
        "primary_exclusion_criterion": decision.get("primary_exclusion_criterion"),
        "follow_up_actions": list(decision.get("follow_up_actions") or ()),
        "reports": [
            {
                "report_id": report.get("report_id"),
                "is_primary": bool(link.get("is_primary")),
                "report_role": link.get("rationale"),
                "title": report.get("title"),
                "citation": report.get("citation"),
                "external_identifiers": list(
                    report.get("external_identifiers") or ()
                ),
                "locators": list(report.get("locators") or ()),
            }
            for link in study_links
            if (report := reports.get(str(link.get("report_id")))) is not None
        ],
    }


def _study_data_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    studies = _records(value.get("studies"))
    return {
        "status": value.get("status"),
        "study_count": len(studies),
        "studies": [
            {
                "study_id": item.get("study_id"),
                "display_name": item.get("display_name"),
                "completion": item.get("completion"),
                "result_ids": [
                    result.get("result_id")
                    for result in _records(item.get("results"))
                    if result.get("result_id")
                ],
            }
            for item in studies
        ],
        "issues": list(value.get("issues") or ()),
    }


def _risk_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    assessments = _records(value.get("assessments"))
    return {
        "assessment_count": len(assessments),
        "unassessed_result_count": len(_records(value.get("unassessed_results"))),
        "assessments": [
            {
                "assessment_id": item.get("assessment_id"),
                "study_id": item.get("study_id"),
                "target_id": item.get("target_id"),
                "overall": item.get("overall"),
            }
            for item in assessments
        ],
        "limitations": list(value.get("limitations") or ()),
        "issues": list(value.get("issues") or ()),
    }


def _synthesis_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    analyses = _records(value.get("analyses"))
    return {
        "status": value.get("status"),
        "analysis_count": len(analyses),
        "no_evidence_count": sum(item.get("no_evidence") is not None for item in analyses),
        "no_pooling_count": sum(item.get("no_pooling") is not None for item in analyses),
        "analyses": [
            {
                "analysis_id": item.get("analysis_id"),
                "definition": item.get("definition"),
                "has_estimate": bool(item.get("overall_estimates_and_settings")),
                "no_evidence": item.get("no_evidence"),
                "no_pooling": item.get("no_pooling"),
            }
            for item in analyses
        ],
        "issues": list(value.get("issues") or ()),
    }


def _sof_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    tables = _records(value.get("tables"))
    return {
        "table_count": len(tables),
        "tables": [
            {
                "table_id": item.get("table_id"),
                "population": item.get("population"),
                "intervention": item.get("intervention"),
                "comparison": item.get("comparison"),
                "outcomes": [
                    {
                        "evidence_body_id": row.get("evidence_body_id"),
                        "outcome": row.get("outcome"),
                        "time_frame": row.get("time_frame"),
                        "study_count": row.get("study_count"),
                        "participant_count": row.get("participant_count"),
                        "certainty": row.get("certainty"),
                    }
                    for row in _records(item.get("rows"))
                ],
            }
            for item in tables
        ],
    }


def _candidate(
    display_id: str, kind: str, source_path: str, object_ids: tuple[str, ...]
) -> dict[str, Any]:
    return {
        "display_id": display_id,
        "kind": kind,
        "source_path": source_path,
        "object_ids": list(object_ids),
    }


def _reading_role(path: str) -> str:
    if path.endswith("reporting-index.json"):
        return "read_first"
    if path in {"review-context/search.json", "review-context/selection.json"}:
        return "raw_audit_open_if_needed"
    if path.endswith(".csv") or path.endswith(".jsonl"):
        return "projection_open_if_needed"
    return "semantic_source"


def _object(files: Mapping[str, bytes], name: str) -> dict[str, Any]:
    content = files.get(name)
    if content is None:
        return {}
    value = json.loads(content)
    return value if isinstance(value, dict) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _ids(value: Any, field: str) -> tuple[str, ...]:
    return tuple(
        str(item[field]) for item in _records(value) if item.get(field) is not None
    )
