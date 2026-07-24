"""Create a result-blind, Meta-analysis-local synthesis plan."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm import (
    LLMAPIError,
    LLMConfig,
    call_llm_json,
    load_llm_config,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.errors import (
    MetaAnalysisConfigurationError,
    MetaAnalysisInvocationError,
    MetaAnalysisOutputError,
)


LLMJsonCaller = Callable[..., dict[str, Any]]
MAX_TARGETS = 12
MAX_UNSUPPORTED_TARGETS = 12
TIMEPOINT_STRATEGIES = {
    "exact",
    "closest_to_target",
    "earliest_in_window",
    "latest_in_window",
    "end_of_treatment",
}
TIME_UNITS = {"days", "weeks", "months", "years"}
TIMEPOINT_ANCHORS = {
    "randomization",
    "treatment_start",
    "treatment_end",
    "follow_up_start",
    "not_specified",
}
TIMEPOINT_BASES = {"question", "screening_criteria", "clinical_convention"}
CONTINUOUS_RESULT_FRAMES = {"post_intervention", "change_from_baseline"}
SUBGROUP_SCOPES = {"study_level", "participant_level"}
SUBGROUP_MEMBERSHIP_RELATIONS = {
    "not_applicable",
    "mutually_exclusive",
    "overlapping",
    "unknown",
}


class Method:
    def __init__(
        self,
        *,
        config: LLMConfig | dict[str, Any] | None = None,
        llm_caller: LLMJsonCaller = call_llm_json,
        prompt_dir: Path = Path(__file__).resolve().parent / "prompts",
        system_prompt_prefix: str = "",
    ) -> None:
        self.config = config
        self.llm_caller = llm_caller
        self.prompt_dir = prompt_dir
        self.system_prompt_prefix = system_prompt_prefix.strip()

    def run(self, *, context: dict[str, Any]) -> dict[str, Any]:
        review_id = _required_text(context.get("review_id"), "review_id")
        question_text = _required_text(context.get("question_text"), "question_text")
        question_pico = context.get("question_pico")
        screening_criteria = context.get("screening_criteria")
        if not isinstance(question_pico, dict):
            raise ValueError("question_pico must be an object")
        if not isinstance(screening_criteria, dict):
            raise ValueError("screening_criteria must be an object")
        forbidden = {"articles", "included_studies", "study_pio", "risk_of_bias"}
        leaked = sorted(forbidden.intersection(context))
        if leaked:
            raise ValueError(
                "Synthesis planning context must be result-blind; forbidden keys: "
                + ", ".join(leaked)
            )
        try:
            loaded = self.config if self.config is not None else load_llm_config()
            if loaded is None:
                raise RuntimeError("Missing required LLM config")
            config = _disable_implicit_retries(loaded)
            system_prompt = (self.prompt_dir / "system.txt").read_text(encoding="utf-8")
            if self.system_prompt_prefix:
                system_prompt = f"{self.system_prompt_prefix}\n\n{system_prompt}"
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise MetaAnalysisConfigurationError(
                stage="synthesis_planning"
            ) from exc
        request_payload = {
            "stage": "meta_analysis_synthesis_planning",
            "question_text": question_text,
            "question_pico": question_pico,
            "screening_criteria": screening_criteria,
            "workflow_constraints": (
                context.get("workflow_constraints")
                if isinstance(context.get("workflow_constraints"), dict)
                else {}
            ),
        }
        call_kwargs = {
            "config": config,
            "system": system_prompt,
            "prompt": json.dumps(
                request_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "temperature": 0,
            "max_output_tokens": 8192,
            "reasoning_effort": "none",
            "json_schema": _planning_schema(),
            "json_schema_name": "meta_analysis_synthesis_plan",
        }
        for attempt in range(1, 3):
            response: dict[str, Any] | None = None
            try:
                response = self.llm_caller(**call_kwargs)
                if not isinstance(response, dict):
                    raise ValueError(
                        "Synthesis-planning response must be a JSON object"
                    )
                return _normalize_plan(
                    response=response,
                    review_id=review_id,
                    question_text=question_text,
                    question_pico=question_pico,
                    screening_criteria=screening_criteria,
                )
            except LLMAPIError as exc:
                if not exc.retryable:
                    raise MetaAnalysisInvocationError(
                        stage="synthesis_planning",
                        attempts=attempt,
                        retry_exhausted=False,
                        context_id=review_id,
                        failure_code=exc.failure_code,
                        status_code=exc.status_code,
                        request_id=exc.request_id,
                        failure_detail=exc.provider_message,
                    ) from exc
                if attempt == 2:
                    raise MetaAnalysisInvocationError(
                        stage="synthesis_planning",
                        attempts=attempt,
                        retry_exhausted=True,
                        context_id=review_id,
                        failure_code=exc.failure_code,
                        status_code=exc.status_code,
                        request_id=exc.request_id,
                        failure_detail=exc.provider_message,
                    ) from exc
            except ValueError as exc:
                if attempt == 2:
                    raise MetaAnalysisOutputError(
                        stage="synthesis_planning",
                        attempts=attempt,
                        context_id=review_id,
                        validation_error=str(exc),
                    ) from exc
                call_kwargs["prompt"] = json.dumps(
                    {
                        **request_payload,
                        "repair": {
                            "instruction": (
                                "Return a complete replacement response that satisfies "
                                "the existing synthesis-plan contract. Do not weaken or "
                                "reinterpret the review protocol."
                            ),
                            "validation_error": str(exc),
                            "previous_response_shape": _structured_shape(response),
                        },
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        raise AssertionError("unreachable")


def _disable_implicit_retries(
    config: LLMConfig | dict[str, Any],
) -> dict[str, Any]:
    payload = config.to_dict() if isinstance(config, LLMConfig) else dict(config)
    payload["sdk_max_retries"] = 0
    payload["json_marker_retry_enabled"] = False
    return payload


def _planning_schema() -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    nullable_number = {"type": ["number", "null"]}
    string_array = {"type": "array", "items": {"type": "string"}}
    timepoint = _schema_object(
        {
            "label": {"type": "string"},
            "strategy": {
                "type": "string",
                "enum": sorted(TIMEPOINT_STRATEGIES),
            },
            "target_value": nullable_number,
            "window_start": nullable_number,
            "window_end": nullable_number,
            "unit": {"type": ["string", "null"], "enum": [*sorted(TIME_UNITS), None]},
            "anchor": {"type": "string", "enum": sorted(TIMEPOINT_ANCHORS)},
            "basis": {"type": "string", "enum": sorted(TIMEPOINT_BASES)},
            "rationale": {"type": "string"},
        }
    )
    decision_basis = _schema_object(
        {
            "outcome_measure": {"type": "string"},
            "timepoint": {"type": "string"},
            "analysis_population": {"type": "string"},
            "statistic_type": {"type": "string"},
            "source": {"type": "string"},
            "continuous_result_frame": nullable_string,
        }
    )
    selection_policy = _schema_object(
        {
            "acceptable_outcome_measures": string_array,
            "outcome_measure_priority": string_array,
            "analysis_population_priority": string_array,
            "continuous_result_frame_priority": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": sorted(CONTINUOUS_RESULT_FRAMES),
                },
            },
            "statistic_type_priority": string_array,
            "source_priority": string_array,
            "tie_policy": {"type": "string", "enum": ["unresolved"]},
            "decision_basis": decision_basis,
        }
    )
    target = _schema_object(
        {
            "population_scope": {"type": "string"},
            "experimental": {"type": "string"},
            "comparator": {"type": "string"},
            "outcome_label": {"type": "string"},
            "outcome_measure": nullable_string,
            "timepoint": timepoint,
            "subgroup_factor": nullable_string,
            "subgroup_level": nullable_string,
            "subgroup_scope": {
                "type": ["string", "null"],
                "enum": [*sorted(SUBGROUP_SCOPES), None],
            },
            "subgroup_membership_relation": {
                "type": ["string", "null"],
                "enum": [*sorted(SUBGROUP_MEMBERSHIP_RELATIONS), None],
            },
            "data_type": {
                "type": "string",
                "enum": ["Dichotomous", "Continuous"],
            },
            "result_selection_policy": selection_policy,
            "effect_measure_plan": {
                "type": "string",
                "enum": [
                    "Risk Ratio",
                    "Odds Ratio",
                    "Risk Difference",
                    "Mean Difference",
                    "Std. Mean Difference",
                ],
            },
            "analysis_model_plan": {
                "type": "string",
                "enum": ["common_effect", "varying_effects"],
            },
            "rationale": {"type": "string"},
        }
    )
    unsupported = _schema_object(
        {
            "outcome_label": {"type": "string"},
            "data_type": {"type": "string"},
            "reason_code": {
                "type": "string",
                "enum": [
                    "unsupported_data_type",
                    "insufficient_planning_basis",
                ],
            },
            "reason": {"type": "string"},
        }
    )
    return _schema_object(
        {
            "targets": {"type": "array", "items": target},
            "unsupported_targets": {"type": "array", "items": unsupported},
            "rationale": {"type": "string"},
        }
    )


def _schema_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _structured_shape(value: Any, *, depth: int = 0) -> dict[str, Any] | str:
    if depth >= 2:
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        return type(value).__name__
    if isinstance(value, dict):
        keys = sorted(str(key) for key in value)[:64]
        return {
            "type": "object",
            "keys": keys,
            "omitted_key_count": max(0, len(value) - len(keys)),
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "length": len(value),
            "item_shapes": [
                _structured_shape(item, depth=depth + 1) for item in value[:3]
            ],
        }
    return {"type": type(value).__name__}


def _normalize_plan(
    *,
    response: dict[str, Any],
    review_id: str,
    question_text: str,
    question_pico: dict[str, Any],
    screening_criteria: dict[str, Any],
) -> dict[str, Any]:
    raw_targets = response.get("targets")
    if not isinstance(raw_targets, list):
        raise ValueError("Synthesis-planning response must contain a targets list")
    raw_unsupported = response.get("unsupported_targets")
    if not isinstance(raw_unsupported, list):
        raise ValueError(
            "Synthesis-planning response must contain an unsupported_targets list"
        )
    if len(raw_targets) > MAX_TARGETS:
        raise ValueError(f"Synthesis plan exceeds target limit: {len(raw_targets)} > {MAX_TARGETS}")
    if len(raw_unsupported) > MAX_UNSUPPORTED_TARGETS:
        raise ValueError(
            "Synthesis plan exceeds unsupported-target limit: "
            f"{len(raw_unsupported)} > {MAX_UNSUPPORTED_TARGETS}"
        )
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for raw in raw_targets:
        if not isinstance(raw, dict):
            raise ValueError("Each synthesis target must be an object")
        target = _normalize_target(raw=raw, review_id=review_id, index=len(targets) + 1)
        key = (
            target["comparison"]["experimental"].casefold(),
            target["comparison"]["comparator"].casefold(),
            target["outcome"]["label"].casefold(),
            (target["outcome"]["measure"] or "").casefold(),
            (target["timepoint"]["label"] or "").casefold(),
            json.dumps(
                _operational_timepoint_signature(target["timepoint"]),
                ensure_ascii=False,
                sort_keys=True,
            ),
            (target["subgroup"]["factor"] or "").casefold(),
            (target["subgroup"]["level"] or "").casefold(),
            (target["subgroup"].get("scope") or "").casefold(),
            (target["subgroup"].get("membership_relation") or "").casefold(),
            target["data_type"],
            target["effect_measure_plan"],
            json.dumps(
                target["result_selection_policy"],
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        targets.append(target)
    unsupported_targets = [
        _normalize_unsupported_target(raw)
        for raw in raw_unsupported
        if isinstance(raw, dict)
    ]
    if len(unsupported_targets) != len(raw_unsupported):
        raise ValueError("Each unsupported synthesis target must be an object")
    status = "frozen" if targets else "not_plannable"
    hash_payload = {
        "review_id": review_id,
        "question_text": question_text,
        "question_pico": question_pico,
        "screening_criteria": screening_criteria,
        "targets": targets,
        "unsupported_targets": unsupported_targets,
    }
    plan_hash = hashlib.sha256(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "plan_id": f"meta-plan::{_slug(review_id)}::v5",
        "review_id": review_id,
        "version": "5",
        "status": status,
        "plan_hash": plan_hash,
        "targets": targets,
        "unsupported_targets": unsupported_targets,
        "screening_criteria_snapshot": screening_criteria,
        "rationale": str(response.get("rationale") or "").strip(),
    }


def _normalize_unsupported_target(raw: dict[str, Any]) -> dict[str, str]:
    data_type = _required_text(raw.get("data_type"), "unsupported target data_type")
    reason_code = str(raw.get("reason_code") or "unsupported_data_type").strip()
    if reason_code not in {"unsupported_data_type", "insufficient_planning_basis"}:
        raise ValueError(f"Unsupported synthesis target reason_code: {reason_code}")
    if data_type in {"Dichotomous", "Continuous"} and reason_code != "insufficient_planning_basis":
        raise ValueError(
            "Supported data types may be unsupported only for insufficient_planning_basis"
        )
    return {
        "outcome_label": _required_text(
            raw.get("outcome_label"),
            "unsupported target outcome_label",
        ),
        "data_type": data_type,
        "reason": _required_text(raw.get("reason"), "unsupported target reason"),
        "reason_code": reason_code,
    }


def _normalize_target(*, raw: dict[str, Any], review_id: str, index: int) -> dict[str, Any]:
    experimental = _required_text(raw.get("experimental"), "experimental")
    comparator = _required_text(raw.get("comparator"), "comparator")
    outcome_label = _required_text(raw.get("outcome_label"), "outcome_label")
    outcome_measure = _optional_text(raw.get("outcome_measure"))
    data_type = _required_text(raw.get("data_type"), "data_type")
    if data_type not in {"Dichotomous", "Continuous"}:
        raise ValueError(f"Unsupported synthesis target data_type: {data_type}")
    timepoint = _normalize_timepoint(raw.get("timepoint"))
    subgroup_factor = _optional_text(raw.get("subgroup_factor"))
    subgroup_level = _optional_text(raw.get("subgroup_level"))
    if str(subgroup_level or "").strip().casefold() in {
        "overall",
        "all participants",
        "full sample",
        "whole population",
    }:
        subgroup_factor = None
        subgroup_level = None
    if bool(subgroup_factor) != bool(subgroup_level):
        raise ValueError("subgroup_factor and subgroup_level must both be set or both be empty")
    subgroup_scope, membership_relation = _subgroup_structure(
        raw=raw,
        factor=subgroup_factor,
        level=subgroup_level,
    )
    effect_measure = _effect_measure(raw.get("effect_measure_plan"), data_type=data_type)
    analysis_model = _analysis_model(raw.get("analysis_model_plan"))
    result_selection_policy = _result_selection_policy(
        raw.get("result_selection_policy"),
        outcome_measure=outcome_measure,
        data_type=data_type,
        effect_measure=effect_measure,
    )
    timepoint_label = str(timepoint["label"])
    suffix = _slug("-".join(filter(None, [outcome_label, timepoint_label, data_type])))
    target_id = f"setting::{_slug(review_id)}::{index}::{suffix}"
    policy_hash = hashlib.sha256(
        json.dumps(
            _operational_policy_signature(result_selection_policy),
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    family_components = [
        review_id,
        experimental,
        comparator,
        outcome_label,
        outcome_measure or "unspecified-measure",
        timepoint_label,
        data_type,
        effect_measure,
        hashlib.sha256(
            json.dumps(
                _operational_timepoint_signature(timepoint),
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:12],
        policy_hash,
    ]
    family_id = "setting-family::" + "::".join(_slug(value) for value in family_components)
    return {
        "target_id": target_id,
        # A family joins overall and prespecified subgroup-level targets for the
        # same clinical analysis. The subgroup level is deliberately excluded.
        "setting_family_id": family_id,
        "population_scope": _required_text(raw.get("population_scope"), "population_scope"),
        "comparison": {"experimental": experimental, "comparator": comparator},
        "outcome": {
            "label": outcome_label,
            "measure": outcome_measure,
        },
        "timepoint": timepoint,
        "subgroup": {
            "factor": subgroup_factor,
            "level": subgroup_level,
            "scope": subgroup_scope,
            "membership_relation": membership_relation,
        },
        "data_type": data_type,
        "result_selection_policy": result_selection_policy,
        "effect_measure_plan": effect_measure,
        "analysis_model_plan": analysis_model,
        "notes": _required_text(raw.get("rationale"), "target rationale"),
    }


def _subgroup_structure(
    *,
    raw: dict[str, Any],
    factor: str | None,
    level: str | None,
) -> tuple[str | None, str | None]:
    if not factor and not level:
        return None, None
    scope = str(raw.get("subgroup_scope") or "study_level").strip().casefold()
    if scope not in SUBGROUP_SCOPES:
        raise ValueError(f"Unsupported subgroup_scope: {scope}")
    if scope == "study_level":
        return scope, "not_applicable"
    relation = str(
        raw.get("subgroup_membership_relation") or "unknown"
    ).strip().casefold()
    if relation not in SUBGROUP_MEMBERSHIP_RELATIONS - {"not_applicable"}:
        raise ValueError(
            "participant-level subgroup_membership_relation must be "
            "mutually_exclusive, overlapping, or unknown"
        )
    return scope, relation


def _result_selection_policy(
    value: Any,
    *,
    outcome_measure: str | None,
    data_type: str,
    effect_measure: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("result_selection_policy must be an object")
    acceptable = _text_list(value.get("acceptable_outcome_measures"))
    priorities = _text_list(value.get("outcome_measure_priority"))
    if outcome_measure and not _contains_text(acceptable, outcome_measure):
        acceptable.insert(0, outcome_measure)
    if outcome_measure and not _contains_text(priorities, outcome_measure):
        # The target's declared measure is its primary measurement definition.
        # Keep the frozen policy internally executable even if the model put a
        # summary-data shape in the outcome-measure list by mistake.
        priorities.insert(0, outcome_measure)
    if not acceptable or not priorities:
        raise ValueError(
            "result_selection_policy must freeze acceptable outcome measures and their priority"
        )
    for priority in priorities:
        if not _contains_text(acceptable, priority):
            # A prioritized measure is necessarily acceptable. Models sometimes
            # express the same policy across the two lists inconsistently; close
            # that representational gap without changing the priority order.
            acceptable.append(priority)
    analysis_population = _required_text_list(
        value.get("analysis_population_priority"),
        "analysis_population_priority",
    )
    statistic_type = _required_text_list(
        value.get("statistic_type_priority"),
        "statistic_type_priority",
    )
    continuous_result_frame = _continuous_result_frame_priority(
        value.get("continuous_result_frame_priority"),
        data_type=data_type,
        effect_measure=effect_measure,
    )
    source = _required_text_list(value.get("source_priority"), "source_priority")
    tie_policy = str(value.get("tie_policy") or "unresolved").strip()
    if tie_policy != "unresolved":
        raise ValueError("result_selection_policy.tie_policy must be unresolved")
    basis = value.get("decision_basis")
    if not isinstance(basis, dict):
        raise ValueError("result_selection_policy.decision_basis must be an object")
    decision_basis = {
        name: _required_text(basis.get(name), f"decision_basis.{name}")
        for name in (
            "outcome_measure",
            "timepoint",
            "analysis_population",
            "statistic_type",
            "source",
        )
    }
    if data_type == "Continuous":
        decision_basis["continuous_result_frame"] = _required_text(
            basis.get("continuous_result_frame"),
            "decision_basis.continuous_result_frame",
        )
    return {
        "acceptable_outcome_measures": acceptable,
        "outcome_measure_priority": priorities,
        "analysis_population_priority": analysis_population,
        "continuous_result_frame_priority": continuous_result_frame,
        "statistic_type_priority": statistic_type,
        "source_priority": source,
        "tie_policy": tie_policy,
        "decision_basis": decision_basis,
    }


def _operational_policy_signature(policy: dict[str, Any]) -> dict[str, Any]:
    """Return only fields whose values can change result selection.

    Explanatory prose and the provenance of a rule must not split an overall
    target from its prespecified subgroup targets when their operative rules
    are identical.
    """

    return {
        "acceptable_outcome_measures": sorted(
            str(item).strip().casefold()
            for item in policy.get("acceptable_outcome_measures") or []
        ),
        "outcome_measure_priority": policy.get("outcome_measure_priority") or [],
        "analysis_population_priority": policy.get("analysis_population_priority") or [],
        "continuous_result_frame_priority": policy.get("continuous_result_frame_priority") or [],
        "statistic_type_priority": policy.get("statistic_type_priority") or [],
        "source_priority": policy.get("source_priority") or [],
        "tie_policy": policy.get("tie_policy"),
    }


def _normalize_timepoint(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("timepoint must be an object")
    label = _required_text(value.get("label"), "timepoint.label")
    strategy = _required_text(value.get("strategy"), "timepoint.strategy")
    if strategy not in TIMEPOINT_STRATEGIES:
        raise ValueError(f"Unsupported timepoint strategy: {strategy}")
    target = _optional_number(value.get("target_value"), "timepoint.target_value")
    window_start = _optional_number(value.get("window_start"), "timepoint.window_start")
    window_end = _optional_number(value.get("window_end"), "timepoint.window_end")
    unit = _optional_text(value.get("unit"))
    anchor = str(value.get("anchor") or "not_specified").strip()
    basis = _required_text(value.get("basis"), "timepoint.basis")
    rationale = _required_text(value.get("rationale"), "timepoint.rationale")
    if unit is not None and unit not in TIME_UNITS:
        raise ValueError(f"Unsupported timepoint unit: {unit}")
    if anchor not in TIMEPOINT_ANCHORS:
        raise ValueError(f"Unsupported timepoint anchor: {anchor}")
    if basis not in TIMEPOINT_BASES:
        raise ValueError(f"Unsupported timepoint basis: {basis}")
    if strategy in {"exact", "closest_to_target"} and (target is None or unit is None):
        raise ValueError(f"{strategy} requires target_value and unit")
    if strategy in {"earliest_in_window", "latest_in_window"} and (
        window_start is None or window_end is None or unit is None
    ):
        raise ValueError(f"{strategy} requires window_start, window_end, and unit")
    if window_start is not None or window_end is not None:
        if window_start is None or window_end is None or unit is None:
            raise ValueError("A timepoint window requires both bounds and a unit")
        if window_start < 0 or window_end < window_start:
            raise ValueError("Invalid timepoint window bounds")
        if target is not None and not window_start <= target <= window_end:
            raise ValueError("timepoint target must fall inside its window")
    if target is not None and target < 0:
        raise ValueError("timepoint target_value must be non-negative")
    if strategy == "end_of_treatment" and anchor != "treatment_end":
        raise ValueError("end_of_treatment requires anchor=treatment_end")
    return {
        "label": label,
        "strategy": strategy,
        "target_value": target,
        "window_start": window_start,
        "window_end": window_end,
        "unit": unit,
        "anchor": anchor,
        "basis": basis,
        "rationale": rationale,
    }


def _operational_timepoint_signature(timepoint: dict[str, Any]) -> dict[str, Any]:
    return {
        name: timepoint.get(name)
        for name in (
            "strategy",
            "target_value",
            "window_start",
            "window_end",
            "unit",
            "anchor",
        )
    }


def _effect_measure(value: Any, *, data_type: str) -> str:
    normalized = " ".join(str(value or "").replace("_", " ").split()).casefold()
    aliases = {
        "rr": "Risk Ratio",
        "risk ratio": "Risk Ratio",
        "or": "Odds Ratio",
        "odds ratio": "Odds Ratio",
        "rd": "Risk Difference",
        "risk difference": "Risk Difference",
        "md": "Mean Difference",
        "mean difference": "Mean Difference",
        "smd": "Std. Mean Difference",
        "std. mean difference": "Std. Mean Difference",
        "standardized mean difference": "Std. Mean Difference",
        "standardised mean difference": "Std. Mean Difference",
    }
    result = aliases.get(normalized)
    allowed = (
        {"Risk Ratio", "Odds Ratio", "Risk Difference"}
        if data_type == "Dichotomous"
        else {"Mean Difference", "Std. Mean Difference"}
    )
    if result not in allowed:
        raise ValueError(
            f"effect_measure_plan {value!r} is not valid for {data_type} data"
        )
    return result


def _analysis_model(value: Any) -> str:
    normalized = " ".join(str(value or "").replace("_", " ").split()).casefold()
    if normalized in {"fixed", "fixed effect", "common", "common effect"}:
        return "common_effect"
    if normalized in {"random", "random effects", "varying", "varying effects"}:
        return "varying_effects"
    raise ValueError(
        "analysis_model_plan must freeze either common_effect or varying_effects"
    )


def _text_list(value: Any) -> list[str]:
    rows = value if isinstance(value, list) else []
    result: list[str] = []
    for row in rows:
        text = str(row or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _required_text_list(value: Any, field: str) -> list[str]:
    result = _text_list(value)
    if not result:
        raise ValueError(f"Synthesis-planning response missing {field}")
    return result


def _continuous_result_frame_priority(
    value: Any,
    *,
    data_type: str,
    effect_measure: str,
) -> list[str]:
    result = _text_list(value)
    if data_type != "Continuous":
        if result:
            raise ValueError(
                "continuous_result_frame_priority must be empty for Dichotomous targets"
            )
        return []
    if not result:
        raise ValueError(
            "Continuous targets require continuous_result_frame_priority"
        )
    invalid = [item for item in result if item not in CONTINUOUS_RESULT_FRAMES]
    if invalid:
        raise ValueError(
            "Unsupported continuous result frame(s): " + ", ".join(invalid)
        )
    if effect_measure == "Std. Mean Difference" and len(result) != 1:
        raise ValueError(
            "Std. Mean Difference targets must freeze exactly one continuous result frame"
        )
    return result


def _contains_text(values: list[str], expected: str) -> bool:
    normalized = expected.casefold().strip()
    return any(value.casefold().strip() == normalized for value in values)


def _optional_number(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not result == result or result in {float("inf"), float("-inf")}:
        raise ValueError(f"{field} must be finite")
    return result


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"Synthesis-planning response missing {field}")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "item"


def build_method(
    *,
    config: LLMConfig | dict[str, Any] | None = None,
) -> Method:
    return Method(config=config)
