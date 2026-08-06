"""Study Results v3 validation and deterministic RevMan projections."""

from __future__ import annotations

import csv
from hashlib import sha256
import io
import json
import math
from typing import Any, Callable, Mapping

from pydantic import ValidationError

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.artifact_schemas import (
    STUDY_RESULTS_DOCUMENT_V3,
)


STUDY_ARMS_HEADERS = ("Study", "Arm", "Description", "Intervention")
STUDY_RESULTS_HEADERS = (
    "Study", "Outcome", "Data type", "Effect measure", "Arm", "Reference arm",
    "Sample size", "Cases", "Mean", "SD", "SE", "Variance", "CI level",
    "CI start", "CI end", "Exp mean", "Exp CI start", "Exp CI end", "t-test",
    "z-test", "P value", "Covariance method", "Covariance", "Other arm 1",
    "Other arm 2", "Correlation arm 1", "Correlation arm 2", "Correlation",
    "Other mean", "Other SE", "Other variance", "Other CI level",
    "Other CI start", "Other CI end", "Other exp mean", "Other exp CI start",
    "Other exp CI end", "Other t-test", "Other z-test", "Other P value",
    "Footnotes",
)

_CONTINUOUS_RAW_FIELDS = {
    "mean": "Mean",
    "sd": "SD",
    "se": "SE",
    "variance": "Variance",
    "ci-level": "CI level",
    "ci-start": "CI start",
    "ci-end": "CI end",
    "sample-size": "Sample size",
    "t-test": "t-test",
    "p-value": "P value",
}
_CONTRAST_RAW_FIELDS = {
    "mean": "Mean",
    "se": "SE",
    "variance": "Variance",
    "ci-level": "CI level",
    "ci-start": "CI start",
    "ci-end": "CI end",
    "exp-mean": "Exp mean",
    "exp-ci-start": "Exp CI start",
    "exp-ci-end": "Exp CI end",
    "sample-size": "Sample size",
    "t-test": "t-test",
    "z-test": "z-test",
    "p-value": "P value",
}
_OTHER_CONTRAST_RAW_FIELDS = {
    key: f"Other {field}" for key, field in _CONTRAST_RAW_FIELDS.items()
    if field not in {"Sample size"}
}


class ResultsLedgerError(ValueError):
    """Raised when a Study Results document violates its contract."""


ResultCalculator = Callable[[dict[str, Any]], dict[str, Any]]


def parse_results_document(
    content: bytes,
    *,
    expected_binding: Mapping[str, Any],
    require_completed: bool,
    calculate: ResultCalculator,
) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultsLedgerError("Study Results document must be UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ResultsLedgerError("Study Results document must be a JSON object")
    return validate_results_document(
        value,
        expected_binding=expected_binding,
        require_completed=require_completed,
        calculate=calculate,
    )


parse_results_ledger = parse_results_document


def validate_results_document(
    document: Mapping[str, Any],
    *,
    expected_binding: Mapping[str, Any],
    calculate: ResultCalculator,
    require_completed: bool = False,
) -> dict[str, Any]:
    try:
        parsed = STUDY_RESULTS_DOCUMENT_V3.adapter.validate_python(document)
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(item) for item in first["loc"])
        raise ResultsLedgerError(
            f"Study Results document is structurally invalid at {location}: {first['msg']}"
        ) from exc
    # Validation must not normalize, fill, or rewrite the Agent artifact.
    # Preserve the caller's exact wire object as the authoritative value.
    value = dict(document)
    if value["binding"] != dict(expected_binding):
        raise ResultsLedgerError("Study Results binding does not match work")
    if require_completed and value["status"] != "completed":
        raise ResultsLedgerError("Study Results document is not completed")
    review_process = value["review_process"]
    if (
        value["status"] == "completed"
        and review_process.get("methodology_basis_status") == "verified"
        and not review_process["methodology_authorities"]
    ):
        raise ResultsLedgerError(
            "verified completed Study Results requires a consulted methodology authority"
        )

    _unique(value["review_process"]["methodology_authorities"], "authority_id")
    authority_ids = {
        item["authority_id"]
        for item in value["review_process"]["methodology_authorities"]
    }
    _unique(value["review_process"]["method_decisions"], "decision_id")
    for decision in value["review_process"]["method_decisions"]:
        if not set(decision["authority_ids"]).issubset(authority_ids):
            raise ResultsLedgerError("method decision references unknown authority")

    _unique(value["studies"], "study_id")
    global_observations: set[str] = set()
    global_results: set[str] = set()
    for study in value["studies"]:
        _validate_study(
            study,
            completed=require_completed or value["status"] == "completed",
            calculate=calculate,
            global_observations=global_observations,
            global_results=global_results,
        )
    return value


validate_results_ledger = validate_results_document


def _validate_study(
    study: dict[str, Any],
    *,
    completed: bool,
    calculate: ResultCalculator,
    global_observations: set[str],
    global_results: set[str],
) -> None:
    coverage = _index(study["report_coverage"], "report_id")
    targets = _index(study["targets"], "target_id")
    observations = _index(study["source_observations"], "observation_id")
    arms = _index(study["arms"], "arm_id")
    arm_labels = _index(study["arms"], "label")
    derivations = _index(study["derivations"], "derivation_id")
    conflicts = _index(study["conflicts"], "conflict_id")
    results = _index(study["results"], "result_id")
    if global_observations.intersection(observations):
        raise ResultsLedgerError("observation ids must be globally unique")
    if global_results.intersection(results):
        raise ResultsLedgerError("result ids must be globally unique")
    global_observations.update(observations)
    global_results.update(results)
    if completed:
        if not study["completed"]:
            raise ResultsLedgerError("completed document requires every Study completed")
        if any(item["status"] == "not_started" for item in coverage.values()):
            raise ResultsLedgerError("completed document cannot contain not_started Reports")
    for item in coverage.values():
        if item["status"] != "not_started" and not item["attempts"]:
            raise ResultsLedgerError("attempted Report coverage requires an access attempt")
        if item["status"] in {"unavailable", "unreported", "unusable"} and not item["reason"]:
            raise ResultsLedgerError(f"{item['status']} Report coverage requires a reason")
    for target in targets.values():
        if not set(target["report_ids"]).issubset(coverage):
            raise ResultsLedgerError("result target references unknown Report")
    for observation in observations.values():
        if observation["report_id"] not in coverage:
            raise ResultsLedgerError("source observation references untracked Report")
        if observation["target_id"] is not None and observation["target_id"] not in targets:
            raise ResultsLedgerError("source observation references unknown target")
        _finite_scalar(observation["reported_value"])

    computed_derivations: dict[str, dict[str, Any]] = {}
    projected_values: dict[tuple[str, str], tuple[str, str]] = {}
    for derivation_id, derivation in derivations.items():
        try:
            computed = calculate(
                {"operation": derivation["operation"], "inputs": derivation["inputs"]}
            )
        except Exception as exc:
            raise ResultsLedgerError(
                f"derivation {derivation_id} cannot be reproduced: {exc}"
            ) from exc
        for field in ("operation", "inputs", "outputs", "input_digest", "output_digest"):
            if _canonical(computed[field]) != _canonical(derivation[field]):
                raise ResultsLedgerError(
                    f"derivation {derivation_id} {field} does not match calculator output"
                )
        computed_derivations[derivation_id] = computed
        for projection in derivation["projections"]:
            key = (projection["result_id"], projection["result_path"])
            if key in projected_values:
                raise ResultsLedgerError("derivation result projection must be unique")
            projected_values[key] = (derivation_id, projection["output_path"])

    used_derivations: set[str] = set()
    for result in results.values():
        if result["target_id"] not in targets:
            raise ResultsLedgerError("result references unknown target")
        if not set(result["source_observation_ids"]).issubset(observations):
            raise ResultsLedgerError("result references unknown source observation")
        if any(
            observations[observation_id]["target_id"] not in {
                None,
                result["target_id"],
            }
            for observation_id in result["source_observation_ids"]
        ):
            raise ResultsLedgerError("result uses an observation from another target")
        if not set(result["derivation_ids"]).issubset(derivations):
            raise ResultsLedgerError("result references unknown derivation")
        if not set(result["conflict_ids"]).issubset(conflicts):
            raise ResultsLedgerError("result references unknown conflict")
        normalization = result["normalization"]
        if normalization["kind"] == "source_only":
            continue
        revman = normalization["result"]
        target = targets[result["target_id"]]
        if revman["outcome"] != target["revman_outcome_name"]:
            raise ResultsLedgerError("RevMan outcome does not match its result target")
        _validate_revman_arms(revman, arm_labels)
        origins = _index(normalization["origins"], "result_path")
        scientific_paths = _numeric_leaf_paths(revman)
        if set(origins) != scientific_paths:
            missing = sorted(scientific_paths - set(origins))
            extra = sorted(set(origins) - scientific_paths)
            raise ResultsLedgerError(
                f"RevMan numeric origins must be exact; missing={missing}, extra={extra}"
            )
        for result_path, origin in origins.items():
            actual = _resolve_json_pointer(revman, result_path)
            if origin["kind"] == "observed":
                observation_id = origin["observation_id"]
                if observation_id not in result["source_observation_ids"]:
                    raise ResultsLedgerError("value origin is not declared by the result")
                expected = _resolve_dot_path(observations[observation_id], origin["source_path"])
            else:
                derivation_id = origin["derivation_id"]
                if derivation_id not in result["derivation_ids"]:
                    raise ResultsLedgerError("value derivation is not declared by the result")
                projection = projected_values.get((result["result_id"], result_path))
                if projection != (derivation_id, origin["source_path"]):
                    raise ResultsLedgerError("derived value lacks its exact calculator projection")
                expected = _resolve_dot_path(
                    computed_derivations[derivation_id], origin["source_path"]
                )
                used_derivations.add(derivation_id)
            if not _same_scalar(actual, expected):
                raise ResultsLedgerError("RevMan value does not match its declared origin")
    if completed and used_derivations != set(derivations):
        raise ResultsLedgerError("completed document cannot contain unused derivations")


def _validate_revman_arms(
    result: Mapping[str, Any],
    arm_labels: Mapping[str, Mapping[str, Any]],
) -> None:
    arm_level = result.get("arm-level-result")
    if arm_level:
        rows = arm_level.get("dichotomous-data-rows") or arm_level.get(
            "continuous-data-rows"
        ) or []
        seen: set[str] = set()
        for row in rows:
            arm = row["arm"]
            if arm not in arm_labels:
                raise ResultsLedgerError("RevMan row references unknown Study arm")
            if arm in seen:
                raise ResultsLedgerError("RevMan arm-level rows must use unique arms")
            seen.add(arm)
    for contrast in result.get("contrast-level-results") or []:
        reference = contrast["reference-arm"]
        if reference not in arm_labels:
            raise ResultsLedgerError("RevMan contrast references unknown reference arm")
        seen = set()
        for row in contrast["contrast-data-rows"]:
            arm = row["arm"]
            if arm not in arm_labels:
                raise ResultsLedgerError("RevMan contrast references unknown Study arm")
            if arm == reference:
                raise ResultsLedgerError("contrast arm cannot equal reference arm")
            if arm in seen:
                raise ResultsLedgerError("contrast data rows must use unique arms")
            seen.add(arm)


def project_results_csv(document: Mapping[str, Any]) -> dict[str, bytes]:
    arms: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for study in sorted(
        document["studies"], key=lambda item: (item["display_name"], item["study_id"])
    ):
        for arm in study["arms"]:
            arms.append(
                {
                    "Study": study["display_name"],
                    "Arm": arm["label"],
                    "Description": arm.get("description") or "",
                    "Intervention": arm.get("intervention") or "",
                }
            )
        for resolved in study["results"]:
            normalization = resolved["normalization"]
            if normalization["kind"] != "revman":
                continue
            rows.extend(
                _revman_rows(
                    study_name=study["display_name"],
                    revman=normalization["result"],
                )
            )
    review_id = str(document["binding"]["review_id"])
    return {
        f"{review_id}-study-arms.csv": _csv_bytes(STUDY_ARMS_HEADERS, arms),
        f"{review_id}-study-results.csv": _csv_bytes(STUDY_RESULTS_HEADERS, rows),
    }


def _revman_rows(*, study_name: str, revman: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    arm_level = revman.get("arm-level-result")
    if arm_level:
        for source in arm_level.get("dichotomous-data-rows") or []:
            row = _empty_result_row(study_name, revman["outcome"], "Dichotomous")
            row.update(
                {
                    "Arm": source["arm"],
                    "Cases": source["cases"],
                    "Sample size": source["sample-size"],
                    "Footnotes": arm_level.get("footnote") or "",
                }
            )
            rows.append(row)
        for source in arm_level.get("continuous-data-rows") or []:
            row = _empty_result_row(study_name, revman["outcome"], "Continuous")
            row["Arm"] = source["arm"]
            for key, field in (("mean", "Mean"), ("sd", "SD"), ("sample-size", "Sample size")):
                if source.get(key) is not None:
                    row[field] = source[key]
            _copy_fields(row, source.get("raw-data") or {}, _CONTINUOUS_RAW_FIELDS)
            row["Footnotes"] = arm_level.get("footnote") or ""
            rows.append(row)
    for contrast in revman.get("contrast-level-results") or []:
        data_type = (
            "Continuous"
            if contrast["effect-measure"] in {"MD", "SMD"}
            else "Dichotomous"
        )
        for source in contrast["contrast-data-rows"]:
            row = _empty_result_row(study_name, revman["outcome"], data_type)
            row.update(
                {
                    "Effect measure": contrast["effect-measure"],
                    "Arm": source["arm"],
                    "Reference arm": contrast["reference-arm"],
                    "Footnotes": contrast.get("footnote") or "",
                }
            )
            if source.get("mean") is not None:
                row["Mean"] = source["mean"]
            if source.get("se") is not None:
                row["SE"] = source["se"]
            if source.get("sample-size") is not None:
                row["Sample size"] = source["sample-size"]
            _copy_fields(row, source.get("raw-data") or {}, _CONTRAST_RAW_FIELDS)
            _project_covariance(row, contrast.get("covariance"))
            rows.append(row)
    return rows


def _project_covariance(row: dict[str, Any], covariance: Mapping[str, Any] | None) -> None:
    if not covariance:
        return
    if covariance.get("method") is not None:
        row["Covariance method"] = covariance["method"]
    if covariance.get("value") is not None:
        row["Covariance"] = covariance["value"]
    raw = covariance.get("raw-data") or {}
    other = raw.get("data-on-another-contrast")
    if other:
        row["Other arm 1"] = other["arm-1"]
        row["Other arm 2"] = other["arm-2"]
        _copy_fields(row, other["raw-data"], _OTHER_CONTRAST_RAW_FIELDS)
    correlated = raw.get("data-on-correlation")
    if correlated:
        row["Correlation arm 1"] = correlated["contrast-2"]["arm-1"]
        row["Correlation arm 2"] = correlated["contrast-2"]["arm-2"]
        row["Correlation"] = correlated["correlation"]


def _copy_fields(
    row: dict[str, Any], source: Mapping[str, Any], fields: Mapping[str, str]
) -> None:
    for key, destination in fields.items():
        if source.get(key) is not None:
            row[destination] = source[key]


def _empty_result_row(study: str, outcome: str, data_type: str) -> dict[str, Any]:
    row = {name: "" for name in STUDY_RESULTS_HEADERS}
    row.update({"Study": study, "Outcome": outcome, "Data type": data_type})
    return row


def projection_summary(document: Mapping[str, Any]) -> dict[str, Any]:
    normalized: list[str] = []
    source_only: list[dict[str, str]] = []
    projected_rows = 0
    for study in document["studies"]:
        for result in study["results"]:
            normalization = result["normalization"]
            if normalization["kind"] == "revman":
                normalized.append(result["result_id"])
                projected_rows += len(
                    _revman_rows(
                        study_name=study["display_name"],
                        revman=normalization["result"],
                    )
                )
            else:
                source_only.append(
                    {
                        "result_id": result["result_id"],
                        "reason": normalization["reason"],
                    }
                )
    return {
        "normalized_result_ids": normalized,
        "source_only_results": source_only,
        "normalized_result_count": len(normalized),
        "source_only_result_count": len(source_only),
        "projected_row_count": projected_rows,
    }


def results_counts(document: Mapping[str, Any]) -> dict[str, int]:
    studies = document["studies"]
    summary = projection_summary(document)
    return {
        "study_count": len(studies),
        "report_count": sum(len(item["report_coverage"]) for item in studies),
        "source_observation_count": sum(len(item["source_observations"]) for item in studies),
        "result_count": sum(len(item["results"]) for item in studies),
        "normalized_result_count": summary["normalized_result_count"],
        "projected_row_count": summary["projected_row_count"],
        "study_arm_count": sum(len(item["arms"]) for item in studies),
        "unresolved_conflict_count": sum(
            sum(not conflict["resolved"] for conflict in item["conflicts"])
            for item in studies
        ),
    }


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def canonical_json_digest(value: Mapping[str, Any]) -> str:
    return f"sha256:{sha256(canonical_json_bytes(value)).hexdigest()}"


def validate_completed_projections(
    document: Mapping[str, Any],
    *,
    authoritative: bytes,
    public_csvs: Mapping[str, bytes],
) -> dict[str, Any]:
    expected_document = canonical_json_bytes(document)
    if authoritative != expected_document:
        raise ResultsLedgerError("authoritative Results JSON is not canonical")
    expected_csvs = project_results_csv(document)
    if dict(public_csvs) != expected_csvs:
        raise ResultsLedgerError("RevMan CSVs do not match Results JSON projection")
    summary = projection_summary(document)
    if summary["normalized_result_count"] and not summary["projected_row_count"]:
        raise ResultsLedgerError("normalized RevMan results must project at least one row")
    return summary


def validate_csv_projection(document: Mapping[str, Any], artifacts: Mapping[str, bytes]) -> None:
    if dict(artifacts) != project_results_csv(document):
        raise ResultsLedgerError("RevMan CSVs do not match Results JSON projection")


def _csv_bytes(headers: tuple[str, ...], rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=headers, extrasaction="raise", lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {name: "" if row.get(name) is None else row.get(name, "") for name in headers}
        )
    return stream.getvalue().encode()


def _index(items: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        value = item[field]
        if not isinstance(value, str) or not value.strip():
            raise ResultsLedgerError(f"{field} must not be blank")
        if value in result:
            raise ResultsLedgerError(f"{field} values must be unique")
        result[value] = item
    return result


def _unique(items: list[dict[str, Any]], field: str) -> None:
    _index(items, field)


def _finite_scalar(scalar: Mapping[str, Any]) -> None:
    value = scalar["value"]
    if isinstance(value, float) and not math.isfinite(value):
        raise ResultsLedgerError("numeric Study Result values must be finite")


def _numeric_leaf_paths(value: object, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if type(value) in {int, float}:
        if isinstance(value, float) and not math.isfinite(value):
            raise ResultsLedgerError("numeric RevMan values must be finite")
        paths.add(prefix)
    elif isinstance(value, dict):
        for key, child in value.items():
            paths.update(
                _numeric_leaf_paths(
                    child,
                    f"{prefix}/{str(key).replace('~', '~0').replace('/', '~1')}",
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.update(_numeric_leaf_paths(child, f"{prefix}/{index}"))
    return paths


def _resolve_json_pointer(value: object, path: str) -> object:
    current = value
    if not path.startswith("/"):
        raise ResultsLedgerError("result_path must be a JSON Pointer")
    for raw in path[1:].split("/"):
        component = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and component in current:
            current = current[component]
        elif isinstance(current, list) and component.isdigit() and int(component) < len(current):
            current = current[int(component)]
        else:
            raise ResultsLedgerError(f"result_path does not exist: {path}")
    return current


def _resolve_dot_path(value: Mapping[str, Any], path: str) -> object:
    current: object = value
    for component in path.split("."):
        if isinstance(current, dict) and component in current:
            current = current[component]
        elif isinstance(current, list) and component.isdigit() and int(component) < len(current):
            current = current[int(component)]
        else:
            raise ResultsLedgerError(f"origin path does not exist: {path}")
    return current


def _same_scalar(left: object, right: object) -> bool:
    if type(left) in {int, float} and type(right) in {int, float}:
        return abs(float(left) - float(right)) <= 1e-12 * max(
            1.0, abs(float(left)), abs(float(right))
        )
    return left == right


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
