"""Validation and deterministic projections for Synthesis documents."""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any, Callable, Mapping

from pydantic import ValidationError

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.artifact_schemas import (
    EVIDENCE_SYNTHESIS_DOCUMENT_V3,
)


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
    "data_rows": {
        "Weight",
        "Mean",
        "CI start",
        "CI end",
    },
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


class SynthesisLedgerError(ValueError):
    """Raised when Synthesis state violates its deterministic contract."""


MetaAnalysisCalculator = Callable[[dict[str, Any]], dict[str, Any]]


def parse_synthesis_ledger(
    content: bytes,
    *,
    expected_binding: Mapping[str, Any],
    require_completed: bool,
    compute: MetaAnalysisCalculator,
    calculate_scalar: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SynthesisLedgerError("Synthesis document must be UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SynthesisLedgerError("Synthesis document must be a JSON object")
    try:
        document = EVIDENCE_SYNTHESIS_DOCUMENT_V3.adapter.validate_python(value)
    except ValidationError as exc:
        raise SynthesisLedgerError(
            "Synthesis document does not match evidence-synthesis-document.v3"
        ) from exc
    normalized = document.model_dump(mode="json")
    validate_synthesis_ledger(
        normalized,
        expected_binding=expected_binding,
        require_completed=require_completed,
        compute=compute,
        calculate_scalar=calculate_scalar,
    )
    return normalized


def validate_synthesis_ledger(
    ledger: Mapping[str, Any],
    *,
    expected_binding: Mapping[str, Any],
    compute: MetaAnalysisCalculator,
    require_completed: bool = False,
    calculate_scalar: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> None:
    if ledger.get("schema_version") != "evidence-synthesis-document.v3":
        raise SynthesisLedgerError("unsupported Synthesis ledger schema")
    if ledger.get("binding") != dict(expected_binding):
        raise SynthesisLedgerError("Synthesis ledger binding does not match work")
    status = ledger.get("status")
    if status not in {"incomplete", "blocked", "completed"}:
        raise SynthesisLedgerError("Synthesis ledger status is invalid")
    if require_completed and status != "completed":
        raise SynthesisLedgerError("Synthesis ledger is not completed")
    analyses = ledger.get("analyses")
    if not isinstance(analyses, list):
        raise SynthesisLedgerError("analyses must be a list")
    if require_completed and not analyses:
        raise SynthesisLedgerError(
            "completed Synthesis requires at least one analysis disposition"
        )
    analysis_ids: set[str] = set()
    for analysis in analyses:
        if not isinstance(analysis, dict):
            raise SynthesisLedgerError("analysis entry must be an object")
        analysis_id = _text(analysis.get("analysis_id"), "analysis_id")
        if analysis_id in analysis_ids:
            raise SynthesisLedgerError("analysis ids must be unique")
        analysis_ids.add(analysis_id)
        definition = analysis.get("definition")
        if not isinstance(definition, dict):
            raise SynthesisLedgerError("analysis definition must be an object")
        for field in (
            "population",
            "intervention",
            "comparator",
            "outcome",
            "time_point",
        ):
            _text(definition.get(field), f"analysis definition {field}")
        compatibility = analysis.get("compatibility")
        if not isinstance(compatibility, dict):
            raise SynthesisLedgerError("analysis compatibility must be an object")
        for field in ("rationale", "clinical", "methodological", "statistical"):
            _text(compatibility.get(field), f"analysis compatibility {field}")
        settings = analysis.get("settings")
        if not isinstance(settings, dict):
            raise SynthesisLedgerError("analysis settings must be an object")
        representations = _objects(analysis, "representations")
        representation_ids: set[str] = set()
        for representation in representations:
            representation_id = _text(
                representation.get("representation_id"),
                "representation_id",
            )
            if representation_id in representation_ids:
                raise SynthesisLedgerError(
                    "representation ids must be unique per analysis"
                )
            representation_ids.add(representation_id)
            _text(representation.get("study_id"), "representation study_id")
            _text(representation.get("data_type"), "representation data_type")
            _text(
                representation.get("effect_measure"),
                "representation effect_measure",
            )
            result_ids = _strings(
                representation,
                "source_result_ids",
            )
            if not result_ids:
                raise SynthesisLedgerError(
                    "analysis representation requires source Results"
                )
            values = representation.get("values")
            if not isinstance(values, dict) or not values:
                raise SynthesisLedgerError("analysis representation requires values")
            result_value_sources = _objects(
                representation,
                "result_value_sources",
            )
            sourced_value_names: set[str] = set()
            for source in result_value_sources:
                result_id = _text(
                    source.get("result_id"),
                    "representation value source result_id",
                )
                if result_id not in result_ids:
                    raise SynthesisLedgerError(
                        "representation value source references a Result outside "
                        "source_result_ids"
                    )
                _text(
                    source.get("representation_id"),
                    "representation value source representation_id",
                )
                _text(source.get("source_value_id"), "source value id")
                value_name = _text(
                    source.get("value_name"),
                    "representation value name",
                )
                if value_name not in values:
                    raise SynthesisLedgerError(
                        "representation value source names an unknown value"
                    )
                if value_name in sourced_value_names:
                    raise SynthesisLedgerError(
                        "representation value sources must be unique"
                    )
                sourced_value_names.add(value_name)
            for source in _objects(
                representation,
                "calculated_value_sources",
            ):
                _text(source.get("trace_id"), "calculated value trace_id")
                if source.get("output_name") not in {"value", "exact"}:
                    raise SynthesisLedgerError(
                        "calculated value output name is invalid"
                    )
                value_name = _text(
                    source.get("value_name"),
                    "calculated representation value name",
                )
                if value_name not in values:
                    raise SynthesisLedgerError(
                        "calculated value source names an unknown value"
                    )
                if value_name in sourced_value_names:
                    raise SynthesisLedgerError(
                        "representation value sources must be unique"
                    )
                sourced_value_names.add(value_name)
                inputs = _objects(source, "inputs")
                if not inputs:
                    raise SynthesisLedgerError(
                        "scalar projection requires at least one source input"
                    )
                input_names: set[str] = set()
                for input_projection in inputs:
                    result_id = _text(
                        input_projection.get("result_id"),
                        "scalar input result_id",
                    )
                    if result_id not in result_ids:
                        raise SynthesisLedgerError(
                            "scalar input references a Result outside source_result_ids"
                        )
                    _text(
                        input_projection.get("representation_id"),
                        "scalar input representation_id",
                    )
                    _text(
                        input_projection.get("source_value_id"),
                        "scalar input source value id",
                    )
                    input_name = _text(
                        input_projection.get("input_name"),
                        "scalar input name",
                    )
                    if input_name in input_names:
                        raise SynthesisLedgerError(
                            "scalar projection input names must be unique"
                        )
                    input_names.add(input_name)
            for value_field, value in values.items():
                if value not in {None, ""} and value_field not in sourced_value_names:
                    raise SynthesisLedgerError(
                        f"representation value {value_field} has no direct or "
                        "calculated source projection"
                    )
        for contribution in _objects(analysis, "contributions"):
            _text(contribution.get("study_id"), "contribution study_id")
            if not isinstance(contribution.get("included"), bool):
                raise SynthesisLedgerError("contribution included must be boolean")
            _text(contribution.get("reason"), "contribution reason")
        for risk_ref in _objects(analysis, "risk_of_bias_refs"):
            _text(risk_ref.get("study_id"), "RoB reference study_id")
            _text(risk_ref.get("reference"), "RoB reference")
            if risk_ref.get("used_as_statistical_weight") is not False:
                raise SynthesisLedgerError(
                    "Risk of Bias must not be used as a statistical weight"
                )
        _validate_rows(analysis, "data_rows", DATA_ROWS_HEADERS)
        _validate_rows(
            analysis,
            "subgroup_estimates",
            SUBGROUP_ESTIMATES_HEADERS,
        )
        _validate_rows(
            analysis,
            "overall_estimates_and_settings",
            OVERALL_ESTIMATES_HEADERS,
        )
        traces = _objects(analysis, "calculation_traces")
        for trace in traces:
            _text(trace.get("trace_id"), "calculation trace id")
            if trace.get("tool") not in {"meta-compute", "scalar-calculate"}:
                raise SynthesisLedgerError(
                    "calculation trace uses an undeclared deterministic tool"
                )
            _text(trace.get("engine_id"), "calculation engine id")
            _text(trace.get("engine_version"), "calculation engine version")
            _text(trace.get("input_digest"), "calculation input digest")
            _text(trace.get("output_digest"), "calculation output digest")
            if not isinstance(trace.get("input"), dict):
                raise SynthesisLedgerError("calculation trace input must be an object")
            if not isinstance(trace.get("output"), dict):
                raise SynthesisLedgerError("calculation trace output must be an object")
            projections = trace.get("projections")
            if not isinstance(projections, list) or any(
                not isinstance(item, dict) for item in projections
            ):
                raise SynthesisLedgerError(
                    "calculation trace projections must be a list of objects"
                )
            for field in ("representation_projections", "input_projections"):
                projections = trace.get(field)
                if not isinstance(projections, list) or any(
                    not isinstance(item, dict) for item in projections
                ):
                    raise SynthesisLedgerError(
                        f"calculation trace {field} must be a list of objects"
                    )
        no_pooling = analysis.get("no_pooling")
        if no_pooling is not None:
            if not isinstance(no_pooling, dict):
                raise SynthesisLedgerError("no_pooling must be an object")
            _text(no_pooling.get("reason"), "no-pooling reason")
        alternative_synthesis = analysis.get("alternative_synthesis")
        if alternative_synthesis is not None:
            if not isinstance(alternative_synthesis, dict):
                raise SynthesisLedgerError("alternative_synthesis must be an object")
            _text(
                alternative_synthesis.get("method"),
                "alternative synthesis method",
            )
            _text(
                alternative_synthesis.get("result"),
                "alternative synthesis result",
            )
            _text(
                alternative_synthesis.get("rationale"),
                "alternative synthesis rationale",
            )
            limitations = alternative_synthesis.get("limitations", [])
            if not isinstance(limitations, list) or any(
                not isinstance(item, str) or not item.strip() for item in limitations
            ):
                raise SynthesisLedgerError(
                    "alternative synthesis limitations must be text items"
                )
        no_evidence = analysis.get("no_evidence")
        if no_evidence is not None:
            if not isinstance(no_evidence, dict):
                raise SynthesisLedgerError("no_evidence must be an object")
            _text(no_evidence.get("reason"), "no-evidence reason")
        dispositions = sum(
            (
                bool(analysis["data_rows"]),
                alternative_synthesis is not None,
                no_pooling is not None,
                no_evidence is not None,
            )
        )
        if dispositions > 1:
            raise SynthesisLedgerError(
                "an analysis must have one synthesis disposition"
            )
        if analysis["data_rows"]:
            for field in _SETTING_TEXT_FIELDS:
                _text(settings.get(field), f"analysis setting {field}")
            confidence_level = settings.get("confidence_level")
            if (
                isinstance(confidence_level, bool)
                or not isinstance(confidence_level, int | float)
                or not math.isfinite(float(confidence_level))
                or not 0 < float(confidence_level) < 1
            ):
                raise SynthesisLedgerError(
                    "analysis setting confidence_level must be a finite number "
                    "between zero and one"
                )
            for field in _SETTING_BOOL_FIELDS:
                if not isinstance(settings.get(field), bool):
                    raise SynthesisLedgerError(
                        f"analysis setting {field} must be boolean"
                    )
        origin = analysis.get("origin", "protocol_planned")
        if origin not in {
            "protocol_planned",
            "protocol_interpretation",
            "post_hoc",
        }:
            raise SynthesisLedgerError("analysis origin is invalid")
        if origin == "post_hoc":
            _text(analysis.get("change_rationale"), "post-hoc change rationale")
        if require_completed:
            if dispositions != 1:
                raise SynthesisLedgerError(
                    "every completed analysis requires one synthesis disposition"
                )
            if analysis["data_rows"] and not analysis["overall_estimates_and_settings"]:
                raise SynthesisLedgerError(
                    "meta-analysis requires an overall settings/result row"
                )
            if analysis["data_rows"] and not analysis["calculation_traces"]:
                raise SynthesisLedgerError(
                    "computed analysis requires calculation traces"
                )
            if analysis["data_rows"] and len(traces) != 1:
                raise SynthesisLedgerError(
                    "each computed analysis requires exactly one reproducible "
                    "meta-compute trace"
                )
    if require_completed:
        verify_synthesis_calculations(
            ledger,
            compute=compute,
            calculate_scalar=calculate_scalar,
        )


def verify_synthesis_calculations(
    ledger: Mapping[str, Any],
    *,
    compute: MetaAnalysisCalculator,
    calculate_scalar: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> None:
    for analysis in ledger["analyses"]:
        collections = {
            "data_rows": analysis["data_rows"],
            "subgroup_estimates": analysis["subgroup_estimates"],
            "overall_estimates_and_settings": analysis[
                "overall_estimates_and_settings"
            ],
        }
        projected_targets: set[tuple[str, int, str]] = set()
        input_projected_targets: set[tuple[str, int, str]] = set()
        for trace in analysis["calculation_traces"]:
            calculator = (
                compute if trace["tool"] == "meta-compute" else calculate_scalar
            )
            if calculator is None:
                raise SynthesisLedgerError(
                    "scalar calculation trace requires the Decimal calculator"
                )
            try:
                computed = calculator(trace["input"])
            except Exception as exc:
                raise SynthesisLedgerError(
                    f"calculation trace {trace['trace_id']} cannot be reproduced: {exc}"
                ) from exc
            mismatches: list[str] = []
            if not _numeric_tree_close(trace["output"], computed):
                mismatches.append("output")
            for field in (
                "input_digest",
                "output_digest",
                "engine_id",
                "engine_version",
            ):
                if trace[field] != computed.get(field):
                    mismatches.append(field)
            if mismatches:
                _append_synthesis_warning(
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
            if trace["tool"] == "meta-compute":
                _validate_trace_semantics(analysis, trace, computed)
                _validate_settings_projection(analysis, computed)
            else:
                _validate_scalar_trace(trace, computed)
                continue
            required_output_mappings = _required_output_mappings(
                analysis,
                computed,
            )
            expected_input_paths = _tool_input_paths(trace["input"])
            projected_input_paths: set[str] = set()
            for projection in trace["input_projections"]:
                collection = projection.get("collection")
                index = projection.get("row_index")
                field = projection.get("field")
                input_path = projection.get("input_path")
                if (
                    collection != "data_rows"
                    or not isinstance(index, int)
                    or index < 0
                    or index >= len(collections["data_rows"])
                    or not isinstance(field, str)
                    or field not in collections["data_rows"][index]
                    or not isinstance(input_path, str)
                    or input_path not in expected_input_paths
                ):
                    raise SynthesisLedgerError(
                        "calculator input projection target is invalid"
                    )
                study_index, input_field = expected_input_paths[input_path]
                if (
                    index != study_index
                    or _TOOL_INPUT_TO_DATA_ROW[input_field] != field
                ):
                    raise SynthesisLedgerError(
                        "calculator input projection does not match its "
                        "Data rows field"
                    )
                target = (collection, index, field)
                if (
                    target in input_projected_targets
                    or input_path in projected_input_paths
                ):
                    raise SynthesisLedgerError(
                        "calculator input projections must be one-to-one"
                    )
                input_projected_targets.add(target)
                projected_input_paths.add(input_path)
                expected = _resolve_path(trace["input"], input_path)
                actual = collections[collection][index][field]
                if not _same_scalar(actual, expected):
                    raise SynthesisLedgerError(
                        "calculator input projection does not match tool input"
                    )
            if projected_input_paths != set(expected_input_paths):
                raise SynthesisLedgerError(
                    "every calculator Study input value requires a Data rows "
                    "projection"
                )
            for projection in trace["projections"]:
                collection = projection.get("collection")
                if collection not in collections:
                    raise SynthesisLedgerError(
                        "calculation projection collection is invalid"
                    )
                index = projection.get("row_index")
                field = projection.get("field")
                output_path = projection.get("output_path")
                if (
                    not isinstance(index, int)
                    or index < 0
                    or index >= len(collections[collection])
                    or not isinstance(field, str)
                    or field not in collections[collection][index]
                    or field not in _CALCULATED_FIELDS[collection]
                    or not isinstance(output_path, str)
                    or not output_path
                ):
                    raise SynthesisLedgerError(
                        "calculation projection target is invalid"
                    )
                expected = _resolve_path(computed, output_path)
                actual = collections[collection][index][field]
                target = (collection, index, field)
                if target in projected_targets:
                    raise SynthesisLedgerError(
                        "calculation projection target must be unique"
                    )
                if required_output_mappings.get(target) != output_path:
                    raise SynthesisLedgerError(
                        "calculation projection path does not match its "
                        "official CSV field"
                    )
                projected_targets.add(target)
                if not _same_scalar(actual, expected):
                    _append_synthesis_warning(
                        ledger,
                        code="synthesis_calculated_value_normalized",
                        message=(
                            f"Calculated Synthesis field {collection}[{index}].{field} "
                            "differed from deterministic calculator output; the "
                            "calculator output is authoritative."
                        ),
                    )
                    collections[collection][index][field] = expected
            if not set(required_output_mappings).issubset(projected_targets):
                raise SynthesisLedgerError(
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
                            raise SynthesisLedgerError(
                                f"{collection_name}[{index}].{field} is a "
                                "source value without a verified calculator "
                                "input projection"
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
                        raise SynthesisLedgerError(
                            f"{collection_name}[{index}].{field} is a "
                            "calculated value without a verified projection"
                        )


def _required_output_mappings(
    analysis: Mapping[str, Any],
    computed: Mapping[str, Any],
) -> dict[tuple[str, int, str], str]:
    mappings: dict[tuple[str, int, str], str] = {}

    def add(
        collection: str,
        index: int,
        field: str,
        output_path: str,
    ) -> None:
        mappings[(collection, index, field)] = output_path

    studies = computed.get("studies")
    if not isinstance(studies, list) or len(studies) != len(analysis["data_rows"]):
        raise SynthesisLedgerError(
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
        raise SynthesisLedgerError("meta-compute overall output is missing")
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
    for input_field, csv_field in (
        ("experimental_cases", "Experimental cases"),
        ("experimental_n", "Experimental N"),
        ("control_cases", "Control cases"),
        ("control_n", "Control N"),
    ):
        if input_field in overall:
            add(
                "overall_estimates_and_settings",
                0,
                csv_field,
                f"overall.{input_field}",
            )
    subgroup_difference = computed.get("subgroup_difference")
    if isinstance(subgroup_difference, dict):
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
        raise SynthesisLedgerError("meta-compute subgroup output is invalid")
    subgroup_rows = analysis["subgroup_estimates"]
    if (len(subgroups) > 1 and len(subgroup_rows) != len(subgroups)) or (
        subgroup_rows and len(subgroup_rows) != len(subgroups)
    ):
        raise SynthesisLedgerError(
            "Subgroup estimates must contain one row per computed subgroup"
        )
    for index, subgroup in enumerate(subgroups if subgroup_rows else []):
        if subgroup_rows[index].get("Subgroup") != subgroup.get("subgroup"):
            raise SynthesisLedgerError(
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
        subgroup_effect_field = (
            "Effect T" if subgroup.get("effect_statistic_name") == "T" else "Effect Z"
        )
        add(
            "subgroup_estimates",
            index,
            subgroup_effect_field,
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


def project_synthesis_csv(
    ledger: Mapping[str, Any],
) -> dict[str, bytes]:
    review_id = str(ledger["binding"]["review_id"])
    analyses = sorted(
        ledger["analyses"],
        key=lambda item: str(item["analysis_id"]),
    )
    data_rows = [row for analysis in analyses for row in analysis["data_rows"]]
    subgroup_rows = [
        row for analysis in analyses for row in analysis["subgroup_estimates"]
    ]
    overall_rows = [
        row
        for analysis in analyses
        for row in analysis["overall_estimates_and_settings"]
    ]
    return {
        f"{review_id}-data-rows.csv": _csv_bytes(
            DATA_ROWS_HEADERS,
            data_rows,
        ),
        f"{review_id}-subgroup-estimates.csv": _csv_bytes(
            SUBGROUP_ESTIMATES_HEADERS,
            subgroup_rows,
        ),
        f"{review_id}-overall-estimates-and-settings.csv": _csv_bytes(
            OVERALL_ESTIMATES_HEADERS,
            overall_rows,
        ),
    }


def canonical_synthesis_json_bytes(ledger: Mapping[str, Any]) -> bytes:
    return (_canonical(ledger) + "\n").encode("utf-8")


def synthesis_counts(ledger: Mapping[str, Any]) -> dict[str, int]:
    analyses = ledger["analyses"]
    return {
        "analysis_count": len(analyses),
        "representation_count": sum(len(item["representations"]) for item in analyses),
        "included_contribution_count": sum(
            sum(bool(row["included"]) for row in item["contributions"])
            for item in analyses
        ),
        "data_row_count": sum(len(item["data_rows"]) for item in analyses),
        "subgroup_estimate_count": sum(
            len(item["subgroup_estimates"]) for item in analyses
        ),
        "overall_estimate_count": sum(
            len(item["overall_estimates_and_settings"]) for item in analyses
        ),
        "no_pooling_count": sum(
            item.get("no_pooling") is not None for item in analyses
        ),
        "other_synthesis_count": sum(
            item.get("alternative_synthesis") is not None for item in analyses
        ),
        "no_evidence_count": sum(
            item.get("no_evidence") is not None for item in analyses
        ),
    }


def validate_csv_projection(
    ledger: Mapping[str, Any],
    artifacts: Mapping[str, bytes],
) -> None:
    expected = project_synthesis_csv(ledger)
    if set(artifacts) != set(expected):
        raise SynthesisLedgerError(
            "completed Synthesis output must contain exactly three official CSVs"
        )
    for name, content in expected.items():
        if artifacts[name] != content:
            raise SynthesisLedgerError(
                f"{name} does not match the frozen Synthesis ledger projection"
            )


def _validate_rows(
    analysis: Mapping[str, Any],
    field: str,
    headers: tuple[str, ...],
) -> None:
    for row in _objects(analysis, field):
        unexpected = set(row) - set(headers)
        if unexpected:
            raise SynthesisLedgerError(
                f"{field} has unsupported CSV fields: {sorted(unexpected)}"
            )


def _csv_bytes(
    headers: tuple[str, ...],
    rows: list[dict[str, Any]],
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=headers,
        extrasaction="raise",
        lineterminator="\n",
    )
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
        raise SynthesisLedgerError(f"{field} must not be blank")
    return value.strip()


def _objects(
    value: Mapping[str, Any],
    field: str,
) -> list[dict[str, Any]]:
    result = value.get(field)
    if not isinstance(result, list) or any(
        not isinstance(item, dict) for item in result
    ):
        raise SynthesisLedgerError(f"{field} must be a list of objects")
    return result


def _strings(
    value: Mapping[str, Any],
    field: str,
) -> list[str]:
    result = value.get(field)
    if not isinstance(result, list) or any(
        not isinstance(item, str) or not item.strip() for item in result
    ):
        raise SynthesisLedgerError(f"{field} must be a list of nonblank strings")
    if len(set(result)) != len(result):
        raise SynthesisLedgerError(f"{field} must contain unique values")
    return result


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _resolve_path(value: Mapping[str, Any], path: str) -> object:
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
        else:
            raise SynthesisLedgerError(
                f"calculation output path does not exist: {path}"
            )
    return current


def _same_scalar(left: object, right: object) -> bool:
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
    return _same_scalar(left, right)


def _append_synthesis_warning(
    ledger: Mapping[str, Any],
    *,
    code: str,
    message: str,
) -> None:
    issues = ledger.get("issues")
    if not isinstance(issues, list):
        raise SynthesisLedgerError("Synthesis issues must be a list")
    candidate = {
        "code": code,
        "message": message,
        "severity": "warning",
        "provenance": [],
    }
    if candidate not in issues:
        issues.append(candidate)


def _validate_scalar_trace(
    trace: Mapping[str, Any],
    computed: Mapping[str, Any],
) -> None:
    if computed.get("schema_version") != "scalar-calculate-output.v1":
        raise SynthesisLedgerError("scalar calculator returned an invalid contract")
    if any(
        trace.get(field)
        for field in (
            "representation_projections",
            "input_projections",
            "projections",
        )
    ):
        raise SynthesisLedgerError(
            "scalar trace mappings belong in representation calculated_value_sources"
        )


def _validate_trace_semantics(
    analysis: Mapping[str, Any],
    trace: Mapping[str, Any],
    computed: Mapping[str, Any],
) -> None:
    tool_studies = trace["input"].get("studies")
    if not isinstance(tool_studies, list):
        raise SynthesisLedgerError("meta-compute input studies must be a list")
    tool_study_ids = {
        item.get("study_id") for item in tool_studies if isinstance(item, dict)
    }
    if len(tool_study_ids) != len(tool_studies) or any(
        not isinstance(item, str) or not item for item in tool_study_ids
    ):
        raise SynthesisLedgerError(
            "meta-compute input requires unique nonblank Study ids"
        )
    included_study_ids = {
        item["study_id"] for item in analysis["contributions"] if item["included"]
    }
    if tool_study_ids != included_study_ids:
        raise SynthesisLedgerError(
            "meta-compute Study ids must exactly match included contributions"
        )
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
        for study_id in included_study_ids
    ):
        raise SynthesisLedgerError(
            "each included Study requires exactly one analysis representation"
        )
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
            raise SynthesisLedgerError("analysis representation projection is invalid")
        study_index, _ = expected_input_paths[input_path]
        tool_study = tool_studies[study_index]
        representation = representations[representation_id]
        if representation["study_id"] != tool_study["study_id"]:
            raise SynthesisLedgerError(
                "analysis representation projection crosses Study boundaries"
            )
        if input_path in projected_input_paths:
            raise SynthesisLedgerError(
                "calculator input value may have only one representation source"
            )
        projected_input_paths.add(input_path)
        expected = representation["values"][value_name]
        actual = _resolve_path(trace["input"], input_path)
        if not _same_scalar(actual, expected):
            raise SynthesisLedgerError(
                "analysis representation projection does not match tool input"
            )
    if projected_input_paths != set(expected_input_paths):
        raise SynthesisLedgerError(
            "every calculator Study input value requires an analysis "
            "representation projection"
        )
    expected_settings = {
        field: analysis["settings"][field] for field in _SETTING_TEXT_FIELDS
    }
    computed_settings = computed.get("settings")
    if not isinstance(computed_settings, dict):
        raise SynthesisLedgerError("meta-compute output settings are missing")
    for field, expected in expected_settings.items():
        if _semantic_setting(field, expected) != _semantic_setting(
            field,
            computed_settings.get(field),
        ):
            raise SynthesisLedgerError(
                f"analysis setting {field} does not match meta-compute"
            )
    for field in ("confidence_level", *_SETTING_BOOL_FIELDS):
        if computed_settings.get(field) != analysis["settings"][field]:
            raise SynthesisLedgerError(
                f"analysis setting {field} does not match meta-compute"
            )
    for field in (
        "heterogeneity_estimator",
        "ci_method",
        "confidence_level",
        "prediction_interval",
        "tau2_ci",
    ):
        if field not in trace["input"]:
            raise SynthesisLedgerError(
                f"meta-compute input must explicitly declare {field}"
            )


def _validate_settings_projection(
    analysis: Mapping[str, Any],
    computed: Mapping[str, Any],
) -> None:
    rows = analysis["overall_estimates_and_settings"]
    if len(rows) != 1:
        raise SynthesisLedgerError(
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
            raise SynthesisLedgerError(
                f"overall settings row {row_field} does not match "
                "meta-compute settings"
            )
    if settings["analysis_model"] == "fixed":
        if row.get("Heterogeneity estimator") != "#N/A":
            raise SynthesisLedgerError(
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
        raise SynthesisLedgerError(
            "overall settings row Heterogeneity estimator does not match "
            "meta-compute settings"
        )
    expected_level = f"{float(settings['confidence_level']) * 100:g}%"
    if row.get("CI/PI level") != expected_level:
        raise SynthesisLedgerError(
            "overall settings row CI/PI level does not match "
            "meta-compute confidence_level"
        )
    for setting, row_field in (
        ("prediction_interval", "Prediction interval"),
        ("tau2_ci", "Tau² CI"),
    ):
        if row.get(row_field) != settings[setting]:
            raise SynthesisLedgerError(
                f"overall settings row {row_field} does not match "
                "meta-compute settings"
            )


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
        raise SynthesisLedgerError("meta-compute input studies must be a list")
    paths: dict[str, tuple[int, str]] = {}
    for index, study in enumerate(studies):
        if not isinstance(study, dict):
            raise SynthesisLedgerError("meta-compute Study input must be an object")
        unsupported = set(study) - (
            set(_TOOL_INPUT_TO_DATA_ROW) | _TOOL_STUDY_METADATA_FIELDS
        )
        if unsupported:
            raise SynthesisLedgerError(
                f"meta-compute Study input has untracked fields: "
                f"{sorted(unsupported)}"
            )
        for field in _TOOL_INPUT_TO_DATA_ROW:
            if field in study and study[field] not in {None, ""}:
                paths[f"studies.{index}.{field}"] = (index, field)
    return paths
