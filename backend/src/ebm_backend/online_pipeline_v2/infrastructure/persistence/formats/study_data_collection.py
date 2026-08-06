"""Validation and deterministic projections for Study Data Collection v3."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any, Callable, Mapping

from pydantic import ValidationError

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.artifact_schemas import (
    RevManResultV1,
    STUDY_DATA_COLLECTION_DOCUMENT_V3,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.filesystem import jsonable
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.study_results import (
    project_results_csv,
    projection_summary,
)


class StudyDataCollectionError(ValueError):
    pass


DataCalculator = Callable[[dict[str, Any]], dict[str, Any]]

_NUMERIC_RELATIVE_TOLERANCE = Decimal("1e-12")
_NUMERIC_ABSOLUTE_TOLERANCE = Decimal("1e-12")


def parse_study_data_collection_document(
    content: bytes,
    *,
    expected_binding: Mapping[str, Any],
    require_completed: bool,
    calculate: DataCalculator,
) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StudyDataCollectionError(
            "Study Data Collection document must be UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise StudyDataCollectionError(
            "Study Data Collection document must be a JSON object"
        )
    return validate_study_data_collection_document(
        value,
        expected_binding=expected_binding,
        require_completed=require_completed,
        calculate=calculate,
    )


def validate_study_data_collection_document(
    document: Mapping[str, Any],
    *,
    expected_binding: Mapping[str, Any],
    calculate: DataCalculator,
    require_completed: bool = False,
) -> dict[str, Any]:
    try:
        STUDY_DATA_COLLECTION_DOCUMENT_V3.adapter.validate_python(document)
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(item) for item in first["loc"])
        raise StudyDataCollectionError(
            "Study Data Collection document is structurally invalid at "
            f"{location}: {first['msg']}"
        ) from exc
    value = deepcopy(dict(document))
    if value["binding"] != dict(expected_binding):
        raise StudyDataCollectionError("Study Data Collection binding does not match work")
    if require_completed and value["status"] != "completed":
        raise StudyDataCollectionError("Study Data Collection document is not completed")
    _unique(value["studies"], "study_id")
    global_observations: set[str] = set()
    global_results: set[str] = set()
    global_values: set[str] = set()
    for study in value["studies"]:
        _validate_study(
            study,
            completed=require_completed or value["status"] == "completed",
            calculate=calculate,
            global_observations=global_observations,
            global_results=global_results,
            global_values=global_values,
            validation_issues=value["issues"],
        )
    return value


def _validate_study(
    study: dict[str, Any],
    *,
    completed: bool,
    calculate: DataCalculator,
    global_observations: set[str],
    global_results: set[str],
    global_values: set[str],
    validation_issues: list[dict[str, Any]],
) -> None:
    coverage = _index(study["report_coverage"], "report_id")
    arms = _index(study.get("arms", []), "arm_id")
    outcomes = _index(study.get("outcomes", []), "outcome_id")
    targets = _index(study.get("targets", []), "target_id")
    observations = _index(study.get("source_observations", []), "observation_id")
    calculations = _index(study.get("calculations", []), "derivation_id")
    conflicts = _index(study.get("conflicts", []), "conflict_id")
    results = _index(study.get("results", []), "result_id")
    _unique(
        study["characteristics"].get("additional_characteristics", []),
        "item_id",
    )
    if global_observations.intersection(observations):
        raise StudyDataCollectionError("observation ids must be globally unique")
    if global_results.intersection(results):
        raise StudyDataCollectionError("result ids must be globally unique")
    global_observations.update(observations)
    global_results.update(results)
    for item in coverage.values():
        if item["status"] == "not_started" and item["attempts"]:
            raise StudyDataCollectionError(
                "not_started Report coverage cannot contain access attempts"
            )
        if item["status"] != "not_started" and not item["attempts"]:
            raise StudyDataCollectionError(
                "attempted Report coverage requires an access attempt"
            )
        if item["status"] in {"inspected", "unreported", "unusable"} and not any(
            attempt["accessed"] for attempt in item["attempts"]
        ):
            raise StudyDataCollectionError(
                f"{item['status']} Report coverage requires actually accessed content"
            )
        if item["status"] in {"unavailable", "unreported", "unusable"} and not item[
            "reason"
        ]:
            raise StudyDataCollectionError(
                f"{item['status']} Report coverage requires a reason"
            )
    if completed:
        if not study["completion"]["completed"]:
            raise StudyDataCollectionError(
                "completed document requires every Study to have inspectable completion"
            )
        if any(item["status"] == "not_started" for item in coverage.values()):
            raise StudyDataCollectionError(
                "completed document cannot contain not_started Reports"
            )
    for target in targets.values():
        if target["outcome_id"] not in outcomes:
            raise StudyDataCollectionError("Result target references unknown outcome")
        if not set(target["report_ids"]).issubset(coverage):
            raise StudyDataCollectionError("Result target references unknown Report")
    for observation in observations.values():
        if observation["report_id"] not in coverage:
            raise StudyDataCollectionError("source observation references unknown Report")
        if observation["target_id"] is not None and observation["target_id"] not in targets:
            raise StudyDataCollectionError("source observation references unknown target")

    computed: dict[str, dict[str, Any]] = {}
    for calculation_id, item in calculations.items():
        for name, origin in item["input_origins"].items():
            if origin["kind"] == "observed":
                observation_id = origin["observation_id"]
                if observation_id not in observations:
                    raise StudyDataCollectionError(
                        "calculation input references unknown observation"
                    )
                source = observations[observation_id]["reported_value"]["value"]
            else:
                prior_id = origin["calculation_id"]
                if prior_id not in computed:
                    raise StudyDataCollectionError(
                        "calculation input must reference an earlier calculation"
                    )
                source = computed[prior_id]["outputs"][origin["output_name"]]
            if _decimal(item["inputs"][name]) != _decimal(source):
                raise StudyDataCollectionError(
                    "calculation input does not match its declared source"
                )
        try:
            replay = calculate(
                {
                    "expression": item["expression"],
                    "inputs": item["inputs"],
                    "precision": item["precision"],
                }
            )
        except Exception as exc:
            _append_validation_warning(
                validation_issues,
                code="calculation_replay_unavailable",
                message=(
                    f"Calculation {calculation_id} could not be replayed by the "
                    f"deterministic calculator: {exc}"
                ),
            )
            computed[calculation_id] = item
            continue
        mismatches = [
            field
            for field in ("expression", "inputs", "precision", "input_digest")
            if _canonical(replay[field]) != _canonical(item[field])
        ]
        if not _outputs_close(item["outputs"], replay["outputs"]):
            mismatches.append("outputs")
        if _canonical(replay["output_digest"]) != _canonical(item["output_digest"]):
            mismatches.append("output_digest")
        if mismatches:
            _append_validation_warning(
                validation_issues,
                code="calculation_trace_normalized",
                message=(
                    f"Calculation {calculation_id} differed from deterministic "
                    f"calculator fields {sorted(set(mismatches))}; the calculator "
                    "output is authoritative."
                ),
            )
        for field in (
            "expression",
            "inputs",
            "precision",
            "outputs",
            "input_digest",
            "output_digest",
        ):
            item[field] = deepcopy(replay[field])
        computed[calculation_id] = replay
    used_calculations: set[str] = set()
    for result in results.values():
        if result["target_id"] not in targets:
            raise StudyDataCollectionError("Result references unknown target")
        if not set(result.get("source_observation_ids", [])).issubset(observations):
            raise StudyDataCollectionError("Result references unknown observation")
        if not set(result.get("calculation_ids", [])).issubset(calculations):
            raise StudyDataCollectionError("Result references unknown calculation")
        if not set(result.get("conflict_ids", [])).issubset(conflicts):
            raise StudyDataCollectionError("Result references unknown conflict")
        if not set(result["collection_assessment"].get("report_ids", [])).issubset(
            coverage
        ):
            raise StudyDataCollectionError(
                "Result collection assessment references unknown Report"
            )
        representations = _index(
            result.get("analysis_representations", []),
            "representation_id",
        )
        target = targets[result["target_id"]]
        for representation_id, representation in representations.items():
            _, sourced_values = _project_revman_result(
                representation["result"],
                arms=arms,
                outcome=target["revman_outcome_name"],
            )
            for value_id, cell in sourced_values.items():
                if value_id in global_values:
                    raise StudyDataCollectionError("value ids must be globally unique")
                global_values.add(value_id)
                actual = cell["value"]
                origin = cell["origin"]
                if origin["kind"] == "observed":
                    observation_id = origin["observation_id"]
                    if observation_id not in result.get("source_observation_ids", []):
                        raise StudyDataCollectionError(
                            "RevMan observed origin is not declared by Result"
                        )
                    expected = observations[observation_id]["reported_value"]["value"]
                else:
                    calculation_id = origin["calculation_id"]
                    if calculation_id not in result.get("calculation_ids", []):
                        raise StudyDataCollectionError(
                            "RevMan calculated origin is not declared by Result"
                        )
                    expected = computed[calculation_id]["outputs"][
                        origin["output_name"]
                    ]
                    used_calculations.add(calculation_id)
                if origin["kind"] == "calculated":
                    if not _numbers_close(actual, expected):
                        _append_validation_warning(
                            validation_issues,
                            code="calculated_value_normalized",
                            message=(
                                f"Calculated RevMan value {value_id} differed from "
                                "its deterministic calculation; the calculator "
                                "output is authoritative."
                            ),
                        )
                    cell["value"] = deepcopy(expected)
                elif _decimal(actual) != _decimal(expected):
                    raise StudyDataCollectionError(
                        "RevMan observed value does not match its declared origin"
                    )
            revman, _ = _project_revman_result(
                representation["result"],
                arms=arms,
                outcome=target["revman_outcome_name"],
            )
            try:
                RevManResultV1.model_validate(revman)
            except ValidationError as exc:
                first = exc.errors(include_url=False)[0]
                location = ".".join(str(item) for item in first["loc"])
                raise StudyDataCollectionError(
                    f"RevMan representation is invalid at {location}: "
                    f"{first['msg']}"
                ) from exc
    unused_calculations = sorted(set(calculations) - used_calculations)
    if completed and unused_calculations:
        _append_validation_warning(
            validation_issues,
            code="unused_calculation",
            message=(
                "Completed Study Data Collection contains calculations that are "
                f"not used by an analysis representation: {unused_calculations}."
            ),
        )


def results_projection_view(document: Mapping[str, Any]) -> dict[str, Any]:
    studies: list[dict[str, Any]] = []
    for study in document["studies"]:
        arm_index = _index(study.get("arms", []), "arm_id")
        target_index = _index(study.get("targets", []), "target_id")
        arms = []
        for arm in study.get("arms", []):
            label = arm["label"]
            if label["status"] != "reported" or not label.get("value"):
                continue
            description = arm["description"].get("value")
            arms.append(
                {
                    "arm_id": arm["arm_id"],
                    "label": label["value"],
                    "description": description,
                    "intervention": description,
                }
            )
        projected_results: list[dict[str, Any]] = []
        for collected in study.get("results", []):
            target = target_index[collected["target_id"]]
            for representation in collected.get("analysis_representations", []):
                revman, _ = _project_revman_result(
                    representation["result"],
                    arms=arm_index,
                    outcome=target["revman_outcome_name"],
                )
                projected_results.append(
                    {
                        "result_id": (
                            f"{collected['result_id']}:{representation['representation_id']}"
                        ),
                        "target_id": collected["target_id"],
                        "evidence_status": "reported",
                        "source_observation_ids": collected.get(
                            "source_observation_ids", []
                        ),
                        "normalization": {
                            "kind": "revman",
                            "result": revman,
                            "origins": [],
                        },
                        "derivation_ids": collected.get("calculation_ids", []),
                        "conflict_ids": collected.get("conflict_ids", []),
                        "notes": [
                            *collected.get("notes", []),
                            *representation.get("notes", []),
                        ],
                    }
                )
        studies.append(
            {
                "study_id": study["study_id"],
                "display_name": study["display_name"],
                "arms": arms,
                "results": projected_results,
            }
        )
    return {"binding": document["binding"], "studies": studies}


def project_study_data_collection(
    document: Mapping[str, Any],
) -> tuple[dict[str, bytes], dict[str, Any]]:
    view = results_projection_view(document)
    csvs = project_results_csv(view)
    legacy_summary = projection_summary(view)
    collected_result_count = sum(
        len(study.get("results", [])) for study in document["studies"]
    )
    analysis_representation_count = sum(
        len(result.get("analysis_representations", []))
        for study in document["studies"]
        for result in study.get("results", [])
    )
    summary = {
        "collected_result_count": collected_result_count,
        "analysis_representation_count": analysis_representation_count,
        "result_without_analysis_representation_count": sum(
            not result.get("analysis_representations", [])
            for study in document["studies"]
            for result in study.get("results", [])
        ),
        "projected_row_count": legacy_summary["projected_row_count"],
    }
    characteristics = b"".join(
        canonical_json_bytes(
            {
                "study_id": study["study_id"],
                "status": study["characteristics"]["status"],
                "report_ids": [item["report_id"] for item in study["report_coverage"]],
                "methods": study["characteristics"]["methods"],
                "population": study["characteristics"]["population"],
                "arms": study.get("arms", []),
                "outcomes": study.get("outcomes", []),
                "funding": study["characteristics"]["funding"],
                "conflicts_of_interest": study["characteristics"][
                    "conflicts_of_interest"
                ],
                "notes": study["characteristics"]["notes"],
                "additional_characteristics": study["characteristics"].get(
                    "additional_characteristics", []
                ),
            }
        )
        for study in document["studies"]
    )
    review_id = str(document["binding"]["review_id"])
    return (
        {
            f"{review_id}-study-characteristics.jsonl": characteristics,
            **csvs,
        },
        summary,
    )


def validate_completed_projections(
    document: Mapping[str, Any],
    *,
    authoritative: bytes,
    public_files: Mapping[str, bytes],
) -> dict[str, Any]:
    if authoritative != canonical_json_bytes(document):
        raise StudyDataCollectionError(
            "authoritative Study Data Collection JSON is not canonical"
        )
    expected, summary = project_study_data_collection(document)
    if dict(public_files) != expected:
        raise StudyDataCollectionError(
            "Study Data Collection projections do not match authoritative JSON"
        )
    if summary["analysis_representation_count"] and not summary["projected_row_count"]:
        raise StudyDataCollectionError(
            "normalized RevMan results must project at least one row"
        )
    return summary


def study_data_collection_counts(document: Mapping[str, Any]) -> dict[str, int]:
    _, summary = project_study_data_collection(document)
    return {
        "study_count": len(document["studies"]),
        "report_count": sum(len(item["report_coverage"]) for item in document["studies"]),
        "source_observation_count": sum(
            len(item.get("source_observations", [])) for item in document["studies"]
        ),
        "result_count": sum(
            len(item.get("results", [])) for item in document["studies"]
        ),
        "analysis_representation_count": summary["analysis_representation_count"],
        "result_without_analysis_representation_count": summary[
            "result_without_analysis_representation_count"
        ],
        "projected_row_count": summary["projected_row_count"],
        "study_arm_count": sum(
            len(item.get("arms", [])) for item in document["studies"]
        ),
        "characteristics_completed_count": sum(
            item["completion"]["characteristics"] == "completed"
            for item in document["studies"]
        ),
    }


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _project_revman_result(
    source: Mapping[str, Any],
    *,
    arms: Mapping[str, Mapping[str, Any]],
    outcome: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Project semantic arm/value identities into the RevMan exchange shape."""

    values: dict[str, dict[str, Any]] = {}

    def arm_label(arm_id: object) -> str:
        if not isinstance(arm_id, str) or arm_id not in arms:
            raise StudyDataCollectionError(
                "RevMan representation references an unknown Study arm id"
            )
        label = arms[arm_id]["label"]
        if label["status"] != "reported" or not label.get("value"):
            raise StudyDataCollectionError(
                "RevMan representation requires a reported Study arm label"
            )
        return str(label["value"])

    def visit(value: object) -> object:
        if isinstance(value, dict):
            if set(value) == {"value_id", "value", "origin"}:
                value_id = value["value_id"]
                if not isinstance(value_id, str) or not value_id:
                    raise StudyDataCollectionError("numeric value requires value_id")
                if value_id in values:
                    raise StudyDataCollectionError(
                        "value ids must be unique within a representation"
                    )
                values[value_id] = value
                return value["value"]
            projected: dict[str, Any] = {}
            for key, child in value.items():
                if key == "arm_id":
                    projected["arm"] = arm_label(child)
                elif key == "reference-arm-id":
                    projected["reference-arm"] = arm_label(child)
                elif key == "arm-1-id":
                    projected["arm-1"] = arm_label(child)
                elif key == "arm-2-id":
                    projected["arm-2"] = arm_label(child)
                else:
                    projected[key] = visit(child)
            return projected
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    projected = visit(dict(source))
    if not isinstance(projected, dict):
        raise StudyDataCollectionError("RevMan representation must be an object")
    return {"outcome": outcome, **projected}, values


def _index(items: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item[field]
        if key in result:
            raise StudyDataCollectionError(f"{field} values must be unique")
        result[key] = item
    return result


def _unique(items: list[dict[str, Any]], field: str) -> None:
    _index(items, field)


def _decimal(value: object) -> Decimal:
    if isinstance(value, dict) and set(value) >= {"kind", "value"}:
        if value["kind"] not in {"integer", "decimal"}:
            raise StudyDataCollectionError("calculation source must be numeric")
        value = value["value"]
    if isinstance(value, bool):
        raise StudyDataCollectionError("numeric value must not be boolean")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise StudyDataCollectionError("numeric value is invalid") from exc
    if not result.is_finite():
        raise StudyDataCollectionError("numeric value must be finite")
    return result


def _numbers_close(left: object, right: object) -> bool:
    left_decimal = _decimal(left)
    right_decimal = _decimal(right)
    difference = abs(left_decimal - right_decimal)
    scale = max(abs(left_decimal), abs(right_decimal))
    return difference <= max(
        _NUMERIC_ABSOLUTE_TOLERANCE,
        _NUMERIC_RELATIVE_TOLERANCE * scale,
    )


def _outputs_close(
    authored: Mapping[str, object],
    replayed: Mapping[str, object],
) -> bool:
    return set(authored) == set(replayed) == {"value", "exact"} and all(
        _numbers_close(authored[name], replayed[name])
        for name in ("value", "exact")
    )


def _append_validation_warning(
    issues: list[dict[str, Any]],
    *,
    code: str,
    message: str,
) -> None:
    candidate = {
        "code": code,
        "message": message,
        "severity": "warning",
        "provenance": [],
    }
    if candidate not in issues:
        issues.append(candidate)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
