"""Portable semantic checks and CSV projection for Synthesis documents."""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any, Mapping


DATA_ROWS_HEADERS = (
    "Analysis group",
    "Analysis number",
    "Analysis name",
    "Subgroup",
    "Applicability",
    "Study",
    "Study year",
    "GIV Mean",
    "GIV SE",
    "Experimental mean",
    "Experimental SD",
    "Experimental cases",
    "Experimental N",
    "Control mean",
    "Control SD",
    "Control cases",
    "Control N",
    "O-E",
    "Variance",
    "Weight",
    "Mean",
    "CI start",
    "CI end",
    "Footnotes",
)
SUBGROUP_ESTIMATES_HEADERS = (
    "Analysis group",
    "Analysis number",
    "Subgroup",
    "Subgroup number",
    "Experimental cases",
    "Experimental N",
    "Control cases",
    "Control N",
    "Weight",
    "Mean",
    "CI start",
    "CI end",
    "Heterogeneity Tau²",
    "Tau² CI start",
    "Tau² CI end",
    "Heterogeneity Chi²",
    "Heterogeneity df",
    "Heterogeneity P",
    "Heterogeneity I²",
    "Effect Z",
    "Effect T",
    "Effect P",
    "ID",
)
OVERALL_ESTIMATES_HEADERS = (
    "Analysis group",
    "Analysis number",
    "Analysis name",
    "Analysis group name",
    "Data source",
    "Data source eligibility",
    "Data type",
    "Log-scale data",
    "Outcome",
    "Intervention grouping",
    "Experimental intervention",
    "Control intervention",
    "Subgroup by",
    "Filter criteria",
    "Experimental group label",
    "Control group label",
    "Statistical method",
    "Effect measure",
    "Unit of effect measure",
    "Analysis model",
    "Heterogeneity estimator",
    "Tau² CI",
    "Subgroup estimates",
    "Overall estimates",
    "Test for subgroup differences",
    "Prediction interval",
    "Swap event and non-event",
    "CI method",
    "CI/PI level",
    "Sort by",
    "Graph label (left)",
    "Graph label (right)",
    "Graph scale",
    "Show risk of bias",
    "Experimental cases",
    "Experimental N",
    "Control cases",
    "Control N",
    "Mean",
    "CI start",
    "CI end",
    "PI start",
    "PI end",
    "Heterogeneity Tau²",
    "Tau² CI start",
    "Tau² CI end",
    "Heterogeneity Chi²",
    "Heterogeneity df",
    "Heterogeneity P",
    "Heterogeneity I²",
    "Effect Z",
    "Effect T",
    "Effect P",
    "Subgroup Chi²",
    "Subgroup df",
    "Subgroup P",
    "Subgroup I²",
    "ID",
)
_CALCULATED_FIELDS = {
    "data_rows": {"Weight", "Mean", "CI start", "CI end"},
    "subgroup_estimates": {
        "Experimental cases",
        "Experimental N",
        "Control cases",
        "Control N",
        "Weight",
        "Mean",
        "CI start",
        "CI end",
        "Heterogeneity Tau²",
        "Tau² CI start",
        "Tau² CI end",
        "Heterogeneity Chi²",
        "Heterogeneity df",
        "Heterogeneity P",
        "Heterogeneity I²",
        "Effect Z",
        "Effect T",
        "Effect P",
    },
    "overall_estimates_and_settings": {
        "Experimental cases",
        "Experimental N",
        "Control cases",
        "Control N",
        "Mean",
        "CI start",
        "CI end",
        "PI start",
        "PI end",
        "Heterogeneity Tau²",
        "Tau² CI start",
        "Tau² CI end",
        "Heterogeneity Chi²",
        "Heterogeneity df",
        "Heterogeneity P",
        "Heterogeneity I²",
        "Effect Z",
        "Effect T",
        "Effect P",
        "Subgroup Chi²",
        "Subgroup df",
        "Subgroup P",
        "Subgroup I²",
    },
}
_TOOL_INPUT_TO_DATA_ROW = {
    "experimental_cases": "Experimental cases",
    "experimental_n": "Experimental N",
    "control_cases": "Control cases",
    "control_n": "Control N",
    "experimental_mean": "Experimental mean",
    "experimental_sd": "Experimental SD",
    "control_mean": "Control mean",
    "control_sd": "Control SD",
    "effect": "GIV Mean",
    "se": "GIV SE",
    "variance": "Variance",
    "o_minus_e": "O-E",
}
_TOOL_STUDY_METADATA_FIELDS = {"study_id", "subgroup"}
_RAW_DATA_ROW_FIELDS = set(_TOOL_INPUT_TO_DATA_ROW.values())
_SETTING_TEXT_FIELDS = (
    "data_type",
    "effect_measure",
    "statistical_method",
    "analysis_model",
    "heterogeneity_estimator",
    "ci_method",
)
_SETTING_BOOL_FIELDS = ("prediction_interval", "tau2_ci")


def validate_synthesis_ledger(
    ledger: Mapping[str, Any],
    *,
    expected_binding: Mapping[str, Any],
    require_completed: bool = False,
) -> None:
    if ledger.get("schema_version") != "evidence-synthesis-document.v3":
        raise ValueError("unsupported Synthesis ledger schema")
    if ledger.get("binding") != dict(expected_binding):
        raise ValueError("Synthesis ledger binding does not match")
    status = ledger.get("status")
    if status not in {"incomplete", "blocked", "completed"}:
        raise ValueError("Synthesis status is invalid")
    if require_completed and status != "completed":
        raise ValueError("Synthesis ledger is not completed")
    analyses = ledger.get("analyses")
    if not isinstance(analyses, list):
        raise ValueError("analyses must be a list")
    if require_completed and not analyses:
        raise ValueError(
            "completed Synthesis requires at least one analysis disposition"
        )
    identifiers: set[str] = set()
    for analysis in analyses:
        if not isinstance(analysis, dict):
            raise ValueError("analysis must be an object")
        for field in (
            "representations",
            "risk_of_bias_refs",
            "calculation_traces",
            "data_rows",
            "subgroup_estimates",
            "overall_estimates_and_settings",
            "issues",
        ):
            analysis.setdefault(field, [])
        for field in ("alternative_synthesis", "no_pooling", "no_evidence"):
            analysis.setdefault(field, None)
        identifier = _text(analysis.get("analysis_id"), "analysis_id")
        if identifier in identifiers:
            raise ValueError("analysis ids must be unique")
        identifiers.add(identifier)
        definition = _object(analysis, "definition")
        for field in (
            "population",
            "intervention",
            "comparator",
            "outcome",
            "time_point",
        ):
            _text(definition.get(field), field)
        compatibility = _object(analysis, "compatibility")
        for field in ("rationale", "clinical", "methodological", "statistical"):
            _text(compatibility.get(field), f"compatibility {field}")
        settings = _object(analysis, "settings")
        representation_ids: set[str] = set()
        for representation in _objects(analysis, "representations"):
            representation.setdefault("calculated_value_sources", [])
            _text(representation.get("representation_id"), "representation_id")
            representation_id = representation["representation_id"]
            if representation_id in representation_ids:
                raise ValueError("representation ids must be unique")
            representation_ids.add(representation_id)
            _text(representation.get("study_id"), "study_id")
            _text(representation.get("data_type"), "data_type")
            _text(representation.get("effect_measure"), "effect_measure")
            result_ids = _strings(representation, "source_result_ids")
            if not result_ids:
                raise ValueError("representation requires source Results")
            values = representation.get("values")
            if not isinstance(values, dict) or not values:
                raise ValueError("representation values must be an object")
            sourced_names: set[str] = set()
            for source in _objects(
                representation,
                "result_value_sources",
            ):
                result_id = _text(source.get("result_id"), "result_id")
                if result_id not in result_ids:
                    raise ValueError(
                        "result projection must reference source_result_ids"
                    )
                _text(source.get("representation_id"), "source representation_id")
                _text(source.get("source_value_id"), "source value id")
                name = _text(source.get("value_name"), "value name")
                if name not in values or name in sourced_names:
                    raise ValueError("representation value source must be unique")
                sourced_names.add(name)
            for source in _objects(
                representation,
                "calculated_value_sources",
            ):
                _text(source.get("trace_id"), "calculated value trace id")
                if source.get("output_name") not in {"value", "exact"}:
                    raise ValueError("calculated value output_name is invalid")
                name = _text(source.get("value_name"), "value name")
                if name not in values or name in sourced_names:
                    raise ValueError("representation value source must be unique")
                sourced_names.add(name)
                inputs = _objects(source, "inputs")
                if not inputs:
                    raise ValueError("scalar projection requires source inputs")
                input_names: set[str] = set()
                for source in inputs:
                    result_id = _text(source.get("result_id"), "scalar result_id")
                    if result_id not in result_ids:
                        raise ValueError("scalar input references an undeclared Result")
                    _text(source.get("representation_id"), "scalar representation_id")
                    _text(source.get("source_value_id"), "scalar source value id")
                    input_name = _text(source.get("input_name"), "scalar input_name")
                    if input_name in input_names:
                        raise ValueError("scalar input names must be unique")
                    input_names.add(input_name)
            for field, value in values.items():
                if value is not None and value != "" and field not in sourced_names:
                    raise ValueError(
                        f"representation value {field} has no Results projection"
                    )
        for contribution in _objects(analysis, "contributions"):
            _text(contribution.get("study_id"), "study_id")
            if not isinstance(contribution.get("included"), bool):
                raise ValueError("contribution included must be boolean")
            _text(contribution.get("reason"), "reason")
        for risk in _objects(analysis, "risk_of_bias_refs"):
            _text(risk.get("study_id"), "study_id")
            _text(risk.get("reference"), "reference")
            if risk.get("used_as_statistical_weight") is not False:
                raise ValueError("RoB must not be used as statistical weight")
        _rows(analysis, "data_rows", DATA_ROWS_HEADERS)
        _rows(analysis, "subgroup_estimates", SUBGROUP_ESTIMATES_HEADERS)
        _rows(
            analysis,
            "overall_estimates_and_settings",
            OVERALL_ESTIMATES_HEADERS,
        )
        traces = _objects(analysis, "calculation_traces")
        for trace in traces:
            for field in (
                "trace_id",
                "tool",
                "engine_id",
                "engine_version",
                "input_digest",
                "output_digest",
            ):
                _text(trace.get(field), field)
            if trace["tool"] not in {"meta-compute", "scalar-calculate"}:
                raise ValueError("calculation uses an undeclared tool")
            if not isinstance(trace.get("input"), dict):
                raise ValueError("calculation input must be an object")
            if not isinstance(trace.get("output"), dict):
                raise ValueError("calculation output must be an object")
            for field in (
                "representation_projections",
                "input_projections",
                "projections",
            ):
                if not isinstance(trace.get(field), list) or any(
                    not isinstance(item, dict) for item in trace[field]
                ):
                    raise ValueError(f"calculation {field} must be a list of objects")
        no_pooling = analysis.get("no_pooling")
        if no_pooling is not None:
            if not isinstance(no_pooling, dict):
                raise ValueError("no_pooling must be an object")
            _text(no_pooling.get("reason"), "no-pooling reason")
        alternative_synthesis = analysis.get("alternative_synthesis")
        if alternative_synthesis is not None:
            if not isinstance(alternative_synthesis, dict):
                raise ValueError("alternative_synthesis must be an object")
            for field in ("method", "result", "rationale"):
                _text(
                    alternative_synthesis.get(field),
                    f"alternative synthesis {field}",
                )
            limitations = alternative_synthesis.get("limitations", [])
            if not isinstance(limitations, list) or any(
                not isinstance(item, str) or not item.strip() for item in limitations
            ):
                raise ValueError("alternative synthesis limitations must be text items")
        no_evidence = analysis.get("no_evidence")
        if no_evidence is not None:
            if not isinstance(no_evidence, dict):
                raise ValueError("no_evidence must be an object")
            _text(no_evidence.get("reason"), "no-evidence reason")
        dispositions = sum(
            (
                bool(analysis["data_rows"]),
                alternative_synthesis is not None,
                no_pooling is not None,
                no_evidence is not None,
            )
        )
        origin = analysis.get("origin", "protocol_planned")
        if origin not in {
            "protocol_planned",
            "protocol_interpretation",
            "post_hoc",
        }:
            raise ValueError("analysis origin is invalid")
        if origin == "post_hoc":
            _text(analysis.get("change_rationale"), "post-hoc change rationale")
        if dispositions > 1:
            raise ValueError("an Analysis must have one synthesis disposition")
        if analysis["data_rows"]:
            for field in _SETTING_TEXT_FIELDS:
                _text(settings.get(field), field)
            confidence_level = settings.get("confidence_level")
            if (
                isinstance(confidence_level, bool)
                or not isinstance(confidence_level, int | float)
                or not math.isfinite(float(confidence_level))
                or not 0 < float(confidence_level) < 1
            ):
                raise ValueError(
                    "confidence_level must be a finite number between zero and one"
                )
            for field in _SETTING_BOOL_FIELDS:
                if not isinstance(settings.get(field), bool):
                    raise ValueError(f"{field} must be boolean")
        if require_completed:
            if dispositions != 1:
                raise ValueError(
                    "completed Analysis requires one synthesis disposition"
                )
            if analysis["data_rows"] and not analysis["overall_estimates_and_settings"]:
                raise ValueError("meta-analysis requires settings/result row")
            if analysis["data_rows"] and not analysis["calculation_traces"]:
                raise ValueError("computed Analysis requires calculation trace")
            if analysis["data_rows"] and len(traces) != 1:
                raise ValueError(
                    "computed Analysis requires exactly one meta-compute trace"
                )
    if require_completed:
        _verify_calculations(ledger)


def project_synthesis_csv(ledger: Mapping[str, Any]) -> dict[str, bytes]:
    review_id = str(ledger["binding"]["review_id"])
    analyses = sorted(ledger["analyses"], key=lambda row: str(row["analysis_id"]))
    projections = (
        ("data-rows", "data_rows", DATA_ROWS_HEADERS),
        ("subgroup-estimates", "subgroup_estimates", SUBGROUP_ESTIMATES_HEADERS),
        (
            "overall-estimates-and-settings",
            "overall_estimates_and_settings",
            OVERALL_ESTIMATES_HEADERS,
        ),
    )
    return {
        f"{review_id}-{suffix}.csv": _csv(
            headers,
            [row for analysis in analyses for row in analysis[field]],
        )
        for suffix, field, headers in projections
    }


def _rows(value: Mapping[str, Any], field: str, headers: tuple[str, ...]) -> None:
    for row in _objects(value, field):
        if set(row) - set(headers):
            raise ValueError(f"{field} contains unsupported CSV fields")


def _csv(headers: tuple[str, ...], rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                name: "" if row.get(name) is None else row.get(name, "")
                for name in headers
            }
        )
    return stream.getvalue().encode("utf-8")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be blank")
    return value.strip()


def _object(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = value.get(field)
    if not isinstance(result, dict):
        raise ValueError(f"{field} must be an object")
    return result


def _objects(value: Mapping[str, Any], field: str) -> list[dict[str, Any]]:
    optional = {
        "calculated_value_sources",
        "risk_of_bias_refs",
        "calculation_traces",
        "data_rows",
        "subgroup_estimates",
        "overall_estimates_and_settings",
        "issues",
    }
    result = value.get(field, []) if field in optional else value.get(field)
    if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
        raise ValueError(f"{field} must be a list of objects")
    return result


def _strings(value: Mapping[str, Any], field: str) -> list[str]:
    result = value.get(field)
    if not isinstance(result, list) or any(
        not isinstance(row, str) or not row.strip() for row in result
    ):
        raise ValueError(f"{field} must be a list of strings")
    return result


def _verify_calculations(ledger: Mapping[str, Any]) -> None:
    for analysis in ledger["analyses"]:
        collections = {
            "data_rows": analysis.get("data_rows", []),
            "subgroup_estimates": analysis.get("subgroup_estimates", []),
            "overall_estimates_and_settings": analysis.get(
                "overall_estimates_and_settings", []
            ),
        }
        projected_targets: set[tuple[str, int, str]] = set()
        input_projected_targets: set[tuple[str, int, str]] = set()
        for trace in analysis.get("calculation_traces", []):
            if trace["tool"] == "scalar-calculate":
                from scalar_calculate import calculate

                computed = calculate(trace["input"])
            else:
                # The numerical stack is imported only for a meta-analysis.
                from meta_compute import compute_meta_analysis

                computed = compute_meta_analysis(trace["input"])
            mismatches = []
            if not _numeric_tree_close(trace["output"], computed):
                mismatches.append("output")
            for field in (
                "input_digest",
                "output_digest",
                "engine_id",
                "engine_version",
            ):
                if trace[field] != computed[field]:
                    mismatches.append(field)
            if mismatches:
                _append_calculation_warning(
                    ledger,
                    code="synthesis_calculation_trace_normalized",
                    message=(
                        f"Calculation trace {trace['trace_id']} differed from "
                        f"deterministic calculator fields {sorted(set(mismatches))}; "
                        "the calculator output is authoritative."
                    ),
                )
            trace["output"] = computed
            for field in (
                "input_digest",
                "output_digest",
                "engine_id",
                "engine_version",
            ):
                trace[field] = computed[field]
            if trace["tool"] == "scalar-calculate":
                if computed.get("schema_version") != "scalar-calculate-output.v1":
                    raise ValueError("scalar calculator returned an invalid contract")
                if any(
                    trace.get(field)
                    for field in (
                        "representation_projections",
                        "input_projections",
                        "projections",
                    )
                ):
                    raise ValueError("scalar trace mappings are invalid")
                continue
            _validate_trace_semantics(analysis, trace, computed)
            _validate_settings_projection(analysis, computed)
            required_output_mappings = _required_output_mappings(
                analysis,
                computed,
            )
            expected_input_paths = _tool_input_paths(trace["input"])
            projected_input_paths: set[str] = set()
            for projection in trace["input_projections"]:
                collection_name = projection.get("collection")
                collection = collections.get(collection_name)
                index = projection.get("row_index")
                field = projection.get("field")
                input_path = projection.get("input_path")
                if (
                    collection_name != "data_rows"
                    or collection is None
                    or not isinstance(index, int)
                    or index < 0
                    or index >= len(collection)
                    or not isinstance(field, str)
                    or field not in collection[index]
                    or not isinstance(input_path, str)
                    or input_path not in expected_input_paths
                ):
                    raise ValueError("calculator input projection target is invalid")
                study_index, input_field = expected_input_paths[input_path]
                if (
                    index != study_index
                    or _TOOL_INPUT_TO_DATA_ROW[input_field] != field
                ):
                    raise ValueError(
                        "calculator input projection does not match Data rows"
                    )
                target = (collection_name, index, field)
                if (
                    target in input_projected_targets
                    or input_path in projected_input_paths
                ):
                    raise ValueError("calculator input projections must be one-to-one")
                input_projected_targets.add(target)
                projected_input_paths.add(input_path)
                if not _same(
                    collection[index][field],
                    _resolve(trace["input"], input_path),
                ):
                    raise ValueError(
                        "calculator input projection does not match tool input"
                    )
            if projected_input_paths != set(expected_input_paths):
                raise ValueError(
                    "every calculator Study input requires a Data rows projection"
                )
            for projection in trace["projections"]:
                collection = collections.get(projection.get("collection"))
                index = projection.get("row_index")
                field = projection.get("field")
                if (
                    collection is None
                    or not isinstance(index, int)
                    or index < 0
                    or index >= len(collection)
                    or not isinstance(field, str)
                    or field not in collection[index]
                    or field not in _CALCULATED_FIELDS[projection["collection"]]
                ):
                    raise ValueError("calculation projection target is invalid")
                expected = _resolve(computed, projection.get("output_path"))
                actual = collection[index][field]
                target = (projection["collection"], index, field)
                if target in projected_targets:
                    raise ValueError("calculation projection target is duplicated")
                if required_output_mappings.get(target) != projection.get(
                    "output_path"
                ):
                    raise ValueError(
                        "calculation projection path does not match CSV field"
                    )
                projected_targets.add(target)
                if not _same(actual, expected):
                    _append_calculation_warning(
                        ledger,
                        code="synthesis_calculated_value_normalized",
                        message=(
                            f"Calculated Synthesis field {projection['collection']}"
                            f"[{index}].{field} differed from deterministic calculator "
                            "output; the calculator output is authoritative."
                        ),
                    )
                    collection[index][field] = expected
            if not set(required_output_mappings).issubset(projected_targets):
                raise ValueError(
                    "required calculator output field is without a verified "
                    "projection"
                )
        for collection_name, rows in collections.items():
            for index, row in enumerate(rows):
                if collection_name == "data_rows":
                    for field in _RAW_DATA_ROW_FIELDS:
                        if (
                            row.get(field) not in {None, ""}
                            and (
                                collection_name,
                                index,
                                field,
                            )
                            not in input_projected_targets
                        ):
                            raise ValueError(
                                f"{collection_name}[{index}].{field} has no "
                                "verified calculator input projection"
                            )
                for field in _CALCULATED_FIELDS[collection_name]:
                    if (
                        row.get(field) not in {None, ""}
                        and (
                            collection_name,
                            index,
                            field,
                        )
                        not in projected_targets
                    ):
                        raise ValueError(
                            f"{collection_name}[{index}].{field} has no "
                            "verified calculation projection"
                        )


def _required_output_mappings(
    analysis: Mapping[str, Any],
    computed: Mapping[str, Any],
) -> dict[tuple[str, int, str], str]:
    mappings: dict[tuple[str, int, str], str] = {}

    def add(collection: str, index: int, field: str, path: str) -> None:
        mappings[(collection, index, field)] = path

    studies = computed.get("studies")
    if not isinstance(studies, list) or len(studies) != len(analysis["data_rows"]):
        raise ValueError(
            "Data rows must contain exactly one row per meta-compute Study"
        )
    for index in range(len(studies)):
        for field, output_field in (
            ("Weight", "weight_percent"),
            ("Mean", "estimate"),
            ("CI start", "ci_start"),
            ("CI end", "ci_end"),
        ):
            add("data_rows", index, field, f"studies.{index}.{output_field}")

    overall = computed.get("overall")
    if not isinstance(overall, dict):
        raise ValueError("meta-compute overall output is missing")
    for field, output_field in (
        ("Mean", "estimate"),
        ("CI start", "ci_start"),
        ("CI end", "ci_end"),
        ("Heterogeneity Chi²", "heterogeneity_q"),
        ("Heterogeneity df", "heterogeneity_df"),
        ("Heterogeneity I²", "i2"),
        ("Effect P", "effect_p"),
    ):
        add(
            "overall_estimates_and_settings",
            0,
            field,
            f"overall.{output_field}",
        )
    effect_field = (
        "Effect T" if overall.get("effect_statistic_name") == "T" else "Effect Z"
    )
    add(
        "overall_estimates_and_settings",
        0,
        effect_field,
        "overall.effect_statistic",
    )
    if overall.get("heterogeneity_p") is not None:
        add(
            "overall_estimates_and_settings",
            0,
            "Heterogeneity P",
            "overall.heterogeneity_p",
        )
    if computed["settings"]["analysis_model"] == "random":
        add(
            "overall_estimates_and_settings",
            0,
            "Heterogeneity Tau²",
            "overall.tau2",
        )
    _add_optional_interval(
        mappings,
        collection="overall_estimates_and_settings",
        index=0,
        output=overall.get("prediction_interval"),
        output_prefix="overall.prediction_interval",
        start_field="PI start",
        end_field="PI end",
    )
    _add_optional_interval(
        mappings,
        collection="overall_estimates_and_settings",
        index=0,
        output=overall.get("tau2_ci"),
        output_prefix="overall.tau2_ci",
        start_field="Tau² CI start",
        end_field="Tau² CI end",
    )
    for output_field, csv_field in (
        ("experimental_cases", "Experimental cases"),
        ("experimental_n", "Experimental N"),
        ("control_cases", "Control cases"),
        ("control_n", "Control N"),
    ):
        if output_field in overall:
            add(
                "overall_estimates_and_settings",
                0,
                csv_field,
                f"overall.{output_field}",
            )
    difference = computed.get("subgroup_difference")
    if isinstance(difference, dict):
        for field, output_field in (
            ("Subgroup Chi²", "chi2"),
            ("Subgroup df", "df"),
            ("Subgroup P", "p"),
            ("Subgroup I²", "i2"),
        ):
            add(
                "overall_estimates_and_settings",
                0,
                field,
                f"subgroup_difference.{output_field}",
            )

    subgroups = computed.get("subgroups")
    if not isinstance(subgroups, list):
        raise ValueError("meta-compute subgroup output is invalid")
    rows = analysis["subgroup_estimates"]
    if (len(subgroups) > 1 and len(rows) != len(subgroups)) or (
        rows and len(rows) != len(subgroups)
    ):
        raise ValueError(
            "Subgroup estimates must contain one row per computed subgroup"
        )
    for index, subgroup in enumerate(subgroups if rows else []):
        if rows[index].get("Subgroup") != subgroup.get("subgroup"):
            raise ValueError(
                "Subgroup estimate row does not match meta-compute subgroup"
            )
        for field, output_field in (
            ("Weight", "weight_percent"),
            ("Mean", "estimate"),
            ("CI start", "ci_start"),
            ("CI end", "ci_end"),
            ("Heterogeneity Chi²", "heterogeneity_q"),
            ("Heterogeneity df", "heterogeneity_df"),
            ("Heterogeneity I²", "i2"),
            ("Effect P", "effect_p"),
        ):
            add(
                "subgroup_estimates",
                index,
                field,
                f"subgroups.{index}.{output_field}",
            )
        effect_field = (
            "Effect T" if subgroup.get("effect_statistic_name") == "T" else "Effect Z"
        )
        add(
            "subgroup_estimates",
            index,
            effect_field,
            f"subgroups.{index}.effect_statistic",
        )
        if subgroup.get("heterogeneity_p") is not None:
            add(
                "subgroup_estimates",
                index,
                "Heterogeneity P",
                f"subgroups.{index}.heterogeneity_p",
            )
        if computed["settings"]["analysis_model"] == "random":
            add(
                "subgroup_estimates",
                index,
                "Heterogeneity Tau²",
                f"subgroups.{index}.tau2",
            )
        _add_optional_interval(
            mappings,
            collection="subgroup_estimates",
            index=index,
            output=subgroup.get("tau2_ci"),
            output_prefix=f"subgroups.{index}.tau2_ci",
            start_field="Tau² CI start",
            end_field="Tau² CI end",
        )
        for output_field, csv_field in (
            ("experimental_cases", "Experimental cases"),
            ("experimental_n", "Experimental N"),
            ("control_cases", "Control cases"),
            ("control_n", "Control N"),
        ):
            if output_field in subgroup:
                add(
                    "subgroup_estimates",
                    index,
                    csv_field,
                    f"subgroups.{index}.{output_field}",
                )
    return mappings


def _add_optional_interval(
    mappings: dict[tuple[str, int, str], str],
    *,
    collection: str,
    index: int,
    output: object,
    output_prefix: str,
    start_field: str,
    end_field: str,
) -> None:
    if isinstance(output, dict):
        mappings[(collection, index, start_field)] = f"{output_prefix}.start"
        mappings[(collection, index, end_field)] = f"{output_prefix}.end"


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _resolve(value: Mapping[str, Any], path: object) -> object:
    if not isinstance(path, str) or not path:
        raise ValueError("calculation output path is invalid")
    current: object = value
    for component in path.split("."):
        if isinstance(current, dict) and component in current:
            current = current[component]
            continue
        if (
            isinstance(current, list)
            and component.isdigit()
            and 0 <= int(component) < len(current)
        ):
            current = current[int(component)]
            continue
        raise ValueError("calculation output path does not exist")
    return current


def _same(left: object, right: object) -> bool:
    if isinstance(left, int | float) and isinstance(right, int | float):
        return abs(float(left) - float(right)) <= 1e-12 * max(
            1.0,
            abs(float(left)),
            abs(float(right)),
        )
    return left == right


def _numeric_tree_close(left: object, right: object) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _numeric_tree_close(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _numeric_tree_close(a, b) for a, b in zip(left, right, strict=True)
        )
    return _same(left, right)


def _append_calculation_warning(
    ledger: Mapping[str, Any],
    *,
    code: str,
    message: str,
) -> None:
    issues = ledger.get("issues")
    if not isinstance(issues, list):
        raise ValueError("Synthesis issues must be a list")
    candidate = {
        "code": code,
        "message": message,
        "severity": "warning",
        "provenance": [],
    }
    if candidate not in issues:
        issues.append(candidate)


def _validate_trace_semantics(
    analysis: Mapping[str, Any],
    trace: Mapping[str, Any],
    computed: Mapping[str, Any],
) -> None:
    studies = trace["input"].get("studies")
    if not isinstance(studies, list):
        raise ValueError("meta-compute input studies must be a list")
    tool_ids = {item.get("study_id") for item in studies if isinstance(item, dict)}
    if len(tool_ids) != len(studies) or any(
        not isinstance(item, str) or not item for item in tool_ids
    ):
        raise ValueError("meta-compute Study ids must be unique and nonblank")
    included_ids = {
        item["study_id"] for item in analysis["contributions"] if item["included"]
    }
    if tool_ids != included_ids:
        raise ValueError("meta-compute Studies must match included contributions")
    representations = {
        item["representation_id"]: item for item in analysis["representations"]
    }
    representations_by_study: dict[str, list[Mapping[str, Any]]] = {}
    for representation in analysis["representations"]:
        representations_by_study.setdefault(
            representation["study_id"],
            [],
        ).append(representation)
    if any(
        len(representations_by_study.get(study_id, [])) != 1
        for study_id in included_ids
    ):
        raise ValueError("each included Study requires exactly one representation")
    expected_input_paths = _tool_input_paths(trace["input"])
    projected_input_paths: set[str] = set()
    for projection in trace["representation_projections"]:
        representation_id = projection.get("representation_id")
        value_name = projection.get("value_name")
        input_path = projection.get("input_path")
        if (
            not isinstance(representation_id, str)
            or representation_id not in representations
            or not isinstance(value_name, str)
            or value_name not in representations[representation_id]["values"]
            or not isinstance(input_path, str)
            or input_path not in expected_input_paths
        ):
            raise ValueError("representation projection is invalid")
        study_index, _ = expected_input_paths[input_path]
        representation = representations[representation_id]
        if representation["study_id"] != studies[study_index]["study_id"]:
            raise ValueError("representation projection crosses Studies")
        if input_path in projected_input_paths:
            raise ValueError("calculator input may have only one representation source")
        projected_input_paths.add(input_path)
        if not _same(
            representation["values"][value_name],
            _resolve(trace["input"], input_path),
        ):
            raise ValueError("representation projection does not match tool input")
    if projected_input_paths != set(expected_input_paths):
        raise ValueError(
            "every calculator Study input requires a representation projection"
        )
    for field in _SETTING_TEXT_FIELDS:
        if _semantic_setting(field, analysis["settings"][field]) != (
            _semantic_setting(field, computed["settings"][field])
        ):
            raise ValueError(f"analysis setting {field} does not match tool")
    for field in ("confidence_level", *_SETTING_BOOL_FIELDS):
        if computed["settings"].get(field) != analysis["settings"][field]:
            raise ValueError(f"analysis setting {field} does not match tool")
    for field in (
        "heterogeneity_estimator",
        "ci_method",
        "confidence_level",
        "prediction_interval",
        "tau2_ci",
    ):
        if field not in trace["input"]:
            raise ValueError(f"calculation input must explicitly declare {field}")


def _validate_settings_projection(
    analysis: Mapping[str, Any],
    computed: Mapping[str, Any],
) -> None:
    rows = analysis["overall_estimates_and_settings"]
    if len(rows) != 1:
        raise ValueError(
            "each computed Analysis requires exactly one overall settings row"
        )
    row = rows[0]
    settings = computed["settings"]
    for field, row_field in (
        ("data_type", "Data type"),
        ("effect_measure", "Effect measure"),
        ("statistical_method", "Statistical method"),
        ("analysis_model", "Analysis model"),
        ("ci_method", "CI method"),
    ):
        if _semantic_setting(field, row.get(row_field)) != _semantic_setting(
            field,
            settings[field],
        ):
            raise ValueError(f"overall settings row {row_field} does not match tool")
    if settings["analysis_model"] == "fixed":
        if row.get("Heterogeneity estimator") != "#N/A":
            raise ValueError(
                "fixed-effect overall settings row requires "
                "Heterogeneity estimator #N/A"
            )
    elif _semantic_setting(
        "heterogeneity_estimator",
        row.get("Heterogeneity estimator"),
    ) != _semantic_setting(
        "heterogeneity_estimator",
        settings["heterogeneity_estimator"],
    ):
        raise ValueError(
            "overall settings row Heterogeneity estimator does not match tool"
        )
    expected_level = f"{float(settings['confidence_level']) * 100:g}%"
    if row.get("CI/PI level") != expected_level:
        raise ValueError("overall settings row CI/PI level does not match tool")
    for setting, row_field in (
        ("prediction_interval", "Prediction interval"),
        ("tau2_ci", "Tau² CI"),
    ):
        if row.get(row_field) != settings[setting]:
            raise ValueError(f"overall settings row {row_field} does not match tool")


def _semantic_setting(field: str, value: object) -> str:
    normalized = "".join(
        character for character in str(value).upper() if character.isalnum()
    )
    aliases = {
        "effect_measure": {
            "RISKRATIO": "RR",
            "RELATIVERISK": "RR",
            "ODDSRATIO": "OR",
            "RISKDIFFERENCE": "RD",
            "MEANDIFFERENCE": "MD",
            "STANDARDIZEDMEANDIFFERENCE": "SMD",
            "STANDARDISEDMEANDIFFERENCE": "SMD",
            "LOGODDSRATIO": "LOGOR",
            "LOGHAZARDRATIO": "LOGHR",
        },
        "statistical_method": {
            "MANTELHAENSZEL": "MH",
            "INVERSEVARIANCE": "IV",
        },
        "analysis_model": {
            "FIXEDEFFECT": "FIXED",
            "COMMONEFFECT": "FIXED",
            "RANDOMEFFECTS": "RANDOM",
        },
    }
    return aliases.get(field, {}).get(normalized, normalized)


def _tool_input_paths(
    calculation_input: Mapping[str, Any],
) -> dict[str, tuple[int, str]]:
    studies = calculation_input.get("studies")
    if not isinstance(studies, list):
        raise ValueError("meta-compute input studies must be a list")
    paths: dict[str, tuple[int, str]] = {}
    for index, study in enumerate(studies):
        if not isinstance(study, dict):
            raise ValueError("meta-compute Study input must be an object")
        unsupported = set(study) - (
            set(_TOOL_INPUT_TO_DATA_ROW) | _TOOL_STUDY_METADATA_FIELDS
        )
        if unsupported:
            raise ValueError(
                f"meta-compute Study input has untracked fields: "
                f"{sorted(unsupported)}"
            )
        for field in _TOOL_INPUT_TO_DATA_ROW:
            if field in study and study[field] not in {None, ""}:
                paths[f"studies.{index}.{field}"] = (index, field)
    return paths
