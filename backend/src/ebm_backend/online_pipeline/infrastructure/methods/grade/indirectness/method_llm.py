"""Single LLM adjudicator for GRADE indirectness."""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.client import call_llm_json
from ebm_backend.online_pipeline.infrastructure.llm.config import load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.grade.base import GradeDomainMethod
from ebm_backend.online_pipeline.infrastructure.methods.grade.common import as_list, first_dict, judgement


DOMAIN = "indirectness"
SEVERITY_LEVELS = {"none": 0, "serious": 1, "very_serious": 2}
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
DOMAINS = ("population", "intervention", "comparator", "direct_comparison", "outcome", "timepoint", "setting")
LLM_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0)


class Method(GradeDomainMethod):
    domain = DOMAIN

    def __init__(self, *, config_path: str | None = None, model: str | None = None) -> None:
        self.config_path = config_path
        self.model = model

    def run(self, *, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
        return predict(
            domain_evidence=domain_evidence,
            evidence_body=evidence_body,
            config_path=self.config_path,
            model=self.model,
        )

    def run_batch_instances(self, *, method_instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return predict_batch_instances(
            method_instances=method_instances,
            config_path=self.config_path,
            model=self.model,
        )


def predict(
    *,
    domain_evidence: dict[str, Any],
    evidence_body: dict[str, Any],
    config_path: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    evidence_package = _build_evidence_package(domain_evidence=domain_evidence, evidence_body=evidence_body)
    config = load_llm_config(config_path, required=False)
    if config is None:
        return _unclear(evidence_package=evidence_package, fallback_reason="missing_llm_config")
    try:
        raw = _call_llm_json_with_retries(
            config=config,
            system=_prompt_text("system.txt"),
            prompt=_prompt(evidence_package),
            model=model,
            temperature=0,
        )
    except Exception as exc:  # pragma: no cover - provider/network dependent
        return _unclear(evidence_package=evidence_package, fallback_reason=f"llm_error:{type(exc).__name__}:{exc}")
    return _judgement_from_llm(raw=raw, evidence_package=evidence_package)


def predict_batch_instances(
    *,
    method_instances: list[dict[str, Any]],
    config_path: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    batch_items = [_batch_item(method_instance) for method_instance in method_instances]
    config = load_llm_config(config_path, required=False)
    if config is None:
        return [
            _batch_output(
                method_instance=item["method_instance"],
                judgement_payload=_unclear(
                    evidence_package=item["evidence_package"],
                    fallback_reason="missing_llm_config",
                ),
                batch_size=len(batch_items),
            )
            for item in batch_items
        ]
    try:
        raw = _call_llm_json_with_retries(
            config=config,
            system=_prompt_text("system.txt"),
            prompt=_batch_prompt(batch_items),
            model=model,
            temperature=0,
        )
    except Exception as exc:  # pragma: no cover - provider/network dependent
        if len(batch_items) > 1:
            return [
                _batch_output(
                    method_instance=item["method_instance"],
                    judgement_payload=_predict_with_config(
                        evidence_package=item["evidence_package"],
                        config=config,
                        model=model,
                        fallback_prefix=f"batch_split_after:{type(exc).__name__}",
                    ),
                    batch_size=1,
                )
                for item in batch_items
            ]
        return [
            _batch_output(
                method_instance=item["method_instance"],
                judgement_payload=_unclear(
                    evidence_package=item["evidence_package"],
                    fallback_reason=f"llm_error:{type(exc).__name__}:{exc}",
                ),
                batch_size=len(batch_items),
            )
            for item in batch_items
        ]

    raw_by_id = _batch_raw_by_id(raw)
    outputs = []
    for item in batch_items:
        instance_id = str(item["method_instance"].get("instance_id") or "")
        raw_row = raw_by_id.get(instance_id)
        if raw_row is None:
            judgement_payload = _predict_with_config(
                evidence_package=item["evidence_package"],
                config=config,
                model=model,
                fallback_prefix="missing_batch_judgement",
            )
        else:
            judgement_payload = _judgement_from_llm(raw=raw_row, evidence_package=item["evidence_package"])
        outputs.append(
            _batch_output(
                method_instance=item["method_instance"],
                judgement_payload=judgement_payload,
                batch_size=len(batch_items),
            )
        )
    return outputs


def _predict_with_config(
    *,
    evidence_package: dict[str, Any],
    config: Any,
    model: str | None,
    fallback_prefix: str,
) -> dict[str, Any]:
    try:
        raw = _call_llm_json_with_retries(
            config=config,
            system=_prompt_text("system.txt"),
            prompt=_prompt(evidence_package),
            model=model,
            temperature=0,
        )
    except Exception as exc:  # pragma: no cover - provider/network dependent
        return _unclear(
            evidence_package=evidence_package,
            fallback_reason=f"{fallback_prefix}:llm_error:{type(exc).__name__}:{exc}",
        )
    result = _judgement_from_llm(raw=raw, evidence_package=evidence_package)
    debug = result.get("debug")
    if isinstance(debug, dict):
        debug["fallback_recovered_from"] = fallback_prefix
    return result


def _call_llm_json_with_retries(**kwargs: Any) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(len(LLM_RETRY_DELAYS_SECONDS) + 1):
        try:
            return call_llm_json(**kwargs)
        except Exception as exc:  # pragma: no cover - provider/network dependent
            last_exc = exc
            if attempt >= len(LLM_RETRY_DELAYS_SECONDS):
                break
            if not _should_retry_llm_error(exc):
                break
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])
    if last_exc is None:
        raise RuntimeError("LLM call failed without an exception")
    raise last_exc


def _should_retry_llm_error(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, json.JSONDecodeError):
        return True
    code = getattr(exc, "code", None)
    if code in {408, 409, 429, 500, 502, 503, 504}:
        return True
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "429",
            "too many requests",
            "timeout",
            "temporarily",
            "rate limit",
            "remote end closed connection",
            "connection",
            "ssl",
            "eof",
            "reset by peer",
            "urlopen error",
        )
    )


def _prompt(evidence_package: dict[str, Any]) -> str:
    template = _prompt_text("user_template.txt")
    return (
        template.replace("{{EVIDENCE_JSON}}", json.dumps(evidence_package, ensure_ascii=False, indent=2, sort_keys=True))
        .replace("{{OUTPUT_SCHEMA_JSON}}", json.dumps(_output_schema(), ensure_ascii=False, indent=2, sort_keys=True))
    )


def _batch_prompt(batch_items: list[dict[str, Any]]) -> str:
    template = _prompt_text("batch_user_template.txt")
    evidence_items = [
        {
            "instance_id": str(item["method_instance"].get("instance_id") or ""),
            "normalized_evidence": item["evidence_package"],
        }
        for item in batch_items
    ]
    return (
        template.replace("{{BATCH_EVIDENCE_JSON}}", json.dumps(evidence_items, ensure_ascii=False, indent=2, sort_keys=True))
        .replace("{{BATCH_OUTPUT_SCHEMA_JSON}}", json.dumps(_batch_output_schema(), ensure_ascii=False, indent=2, sort_keys=True))
    )


@lru_cache(maxsize=None)
def _prompt_text(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def _output_schema() -> dict[str, Any]:
    payload = json.loads((PROMPT_DIR / "output_schema.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Indirectness output schema must be a JSON object")
    return payload


@lru_cache(maxsize=1)
def _batch_output_schema() -> dict[str, Any]:
    payload = json.loads((PROMPT_DIR / "batch_output_schema.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Indirectness batch output schema must be a JSON object")
    return payload


def _batch_item(method_instance: dict[str, Any]) -> dict[str, Any]:
    evidence_package = _build_evidence_package(
        domain_evidence=_dict(method_instance.get("domain_evidence")),
        evidence_body=_dict(method_instance.get("evidence_body")),
    )
    return {"method_instance": method_instance, "evidence_package": evidence_package}


def _batch_output(
    *,
    method_instance: dict[str, Any],
    judgement_payload: dict[str, Any],
    batch_size: int,
) -> dict[str, Any]:
    debug = judgement_payload.get("debug")
    if isinstance(debug, dict):
        debug["batch_mode"] = True
        debug["batch_size"] = batch_size
    return {
        "instance_id": method_instance.get("instance_id"),
        "sof_row_id": method_instance.get("sof_row_id"),
        "review_id": method_instance.get("review_id"),
        "domain": method_instance.get("domain"),
        "judgement": judgement_payload,
    }


def _batch_raw_by_id(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = raw.get("judgements") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        instance_id = str(row.get("instance_id") or "")
        if instance_id:
            result[instance_id] = row
    return result


def _build_evidence_package(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    review_scope_pico = first_dict(domain_evidence.get("review_scope_pico"), evidence_body.get("review_scope_pico"))
    synthesis_target_pico = first_dict(domain_evidence.get("synthesis_target_pico"), evidence_body.get("synthesis_target_pico"))
    sof_display_context = first_dict(domain_evidence.get("sof_display_context"), evidence_body.get("sof_display_context"))
    evidence_found = first_dict(domain_evidence.get("evidence_found"), evidence_body.get("evidence_found"))
    if review_scope_pico or synthesis_target_pico or sof_display_context or evidence_found:
        return _build_official_pico_evidence_package(domain_evidence=domain_evidence, evidence_body=evidence_body)
    target_question = first_dict(domain_evidence.get("target_question"), evidence_body.get("target_question"))
    if target_question or evidence_found:
        return _build_v2_evidence_package(domain_evidence=domain_evidence, evidence_body=evidence_body)
    return _build_legacy_evidence_package(domain_evidence=domain_evidence, evidence_body=evidence_body)


def _build_official_pico_evidence_package(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    review_scope_pico = first_dict(domain_evidence.get("review_scope_pico"), evidence_body.get("review_scope_pico"))
    synthesis_target_pico = first_dict(domain_evidence.get("synthesis_target_pico"), evidence_body.get("synthesis_target_pico"))
    sof_display_context = first_dict(domain_evidence.get("sof_display_context"), evidence_body.get("sof_display_context"))
    evidence_found = first_dict(domain_evidence.get("evidence_found"), evidence_body.get("evidence_found"))
    study_rows = [row for row in as_list(evidence_found.get("study_result_rows")) if isinstance(row, dict)]
    study_characteristics = [
        _compact_study(item)
        for item in as_list(evidence_found.get("study_characteristics"))
        if isinstance(item, dict)
    ]
    return {
        "input_policy": str(domain_evidence.get("input_policy") or "indirectness_allowed_input_only"),
        "review_scope_pico": _compact_review_scope_pico(review_scope_pico),
        "synthesis_target_pico": _compact_synthesis_target_pico(synthesis_target_pico),
        "sof_display_context": _compact_sof_display_context(sof_display_context),
        "evidence_found": {
            "included_study_ids": as_list(evidence_found.get("included_study_ids")),
            "study_characteristics_missing_study_ids": as_list(evidence_found.get("study_characteristics_missing_study_ids")),
            "study_count": len(study_characteristics),
            "study_characteristics": study_characteristics,
            "study_result_rows": [_compact_row(row) for row in study_rows],
        },
    }


def _build_v2_evidence_package(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    target_question = first_dict(domain_evidence.get("target_question"), evidence_body.get("target_question"))
    evidence_found = first_dict(domain_evidence.get("evidence_found"), evidence_body.get("evidence_found"))
    study_rows = [row for row in as_list(evidence_found.get("study_result_rows")) if isinstance(row, dict)]
    study_characteristics = [
        _compact_study(item)
        for item in as_list(evidence_found.get("study_characteristics"))
        if isinstance(item, dict)
    ]
    return {
        "input_policy": str(domain_evidence.get("input_policy") or "indirectness_allowed_input_only"),
        "target_question": _compact_target_question(target_question),
        "evidence_found": {
            "included_study_ids": as_list(evidence_found.get("included_study_ids")),
            "study_characteristics_missing_study_ids": as_list(evidence_found.get("study_characteristics_missing_study_ids")),
            "study_count": len(study_characteristics),
            "study_characteristics": study_characteristics,
            "study_result_rows": [_compact_row(row) for row in study_rows],
        },
    }


def _compact_review_scope_pico(review_scope_pico: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_text": review_scope_pico.get("question_text"),
        "population": as_list(review_scope_pico.get("population")),
        "intervention": as_list(review_scope_pico.get("intervention")),
        "comparator": as_list(review_scope_pico.get("comparator")),
        "outcome": as_list(review_scope_pico.get("outcome")),
    }


def _compact_synthesis_target_pico(synthesis_target_pico: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_text": synthesis_target_pico.get("question_text"),
        "population": _compact_target_value(first_dict(synthesis_target_pico.get("population"))),
        "intervention": _compact_target_value(first_dict(synthesis_target_pico.get("intervention"))),
        "comparator": _compact_target_value(first_dict(synthesis_target_pico.get("comparator"))),
        "outcome": _compact_target_value(first_dict(synthesis_target_pico.get("outcome"))),
        "timepoint": _compact_target_value(first_dict(synthesis_target_pico.get("timepoint"))),
        "subgroup": _compact_target_value(first_dict(synthesis_target_pico.get("subgroup"))),
        "setting": _compact_target_value(first_dict(synthesis_target_pico.get("setting"))),
    }


def _compact_target_value(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": item.get("value"),
        "source": item.get("source"),
        "measure": item.get("measure"),
        "data_type": item.get("data_type"),
        "effect_measure": item.get("effect_measure"),
        "benefit_direction": item.get("benefit_direction"),
    }


def _compact_sof_display_context(sof_display_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "population": sof_display_context.get("population"),
        "intervention": sof_display_context.get("intervention"),
        "comparator": sof_display_context.get("comparator"),
        "outcome": sof_display_context.get("outcome"),
        "timepoint": sof_display_context.get("timepoint"),
        "setting": sof_display_context.get("setting"),
        "participants": sof_display_context.get("participants"),
        "studies": sof_display_context.get("studies"),
        "table_title": sof_display_context.get("table_title"),
    }


def _build_legacy_evidence_package(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    setting = first_dict(domain_evidence.get("analysis_setting"), evidence_body.get("analysis_setting"))
    population_context = first_dict(domain_evidence.get("population_context"))
    study_rows = [row for row in as_list(domain_evidence.get("study_result_rows") or evidence_body.get("study_result_rows")) if isinstance(row, dict)]
    study_characteristics = [
        _compact_study(item)
        for item in as_list(domain_evidence.get("study_characteristics") or evidence_body.get("study_characteristics"))
        if isinstance(item, dict)
    ]
    return {
        "input_policy": str(domain_evidence.get("input_policy") or "indirectness_allowed_input_only"),
        "target": {
            "population": str(population_context.get("text") or ""),
            "population_source": str(population_context.get("source") or "missing"),
            "analysis_setting": _compact_setting(setting),
        },
        "included_study_ids": as_list(domain_evidence.get("included_study_ids") or evidence_body.get("included_study_ids")),
        "study_characteristics_missing_study_ids": as_list(
            domain_evidence.get("study_characteristics_missing_study_ids")
            or evidence_body.get("study_characteristics_missing_study_ids")
        ),
        "study_count": len(study_characteristics),
        "study_characteristics": study_characteristics,
        "study_result_rows": [_compact_row(row) for row in study_rows],
    }


def _compact_target_question(target_question: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_text": target_question.get("question_text"),
        "population": _compact_target_domain(first_dict(target_question.get("population"))),
        "intervention": _compact_target_domain(first_dict(target_question.get("intervention"))),
        "comparator": _compact_target_domain(first_dict(target_question.get("comparator"))),
        "outcome": _compact_target_domain(first_dict(target_question.get("outcome"))),
        "timepoint": _compact_target_domain(first_dict(target_question.get("timepoint"))),
        "subgroup": _compact_target_domain(first_dict(target_question.get("subgroup"))),
        "setting": _compact_target_domain(first_dict(target_question.get("setting"))),
    }


def _compact_target_domain(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary": item.get("primary"),
        "source": item.get("source"),
        "review_pico": as_list(item.get("review_pico")),
        "question_pico": as_list(item.get("question_pico")),
        "sof_context": item.get("sof_context"),
        "measure": item.get("measure"),
        "data_type": item.get("data_type"),
        "effect_measure": item.get("effect_measure"),
        "benefit_direction": item.get("benefit_direction"),
    }


def _compact_setting(setting: dict[str, Any]) -> dict[str, Any]:
    comparison = first_dict(setting.get("comparison"))
    outcome = first_dict(setting.get("outcome"))
    timepoint = first_dict(setting.get("timepoint"))
    subgroup = first_dict(setting.get("subgroup"))
    return {
        "comparison": {
            "experimental": comparison.get("experimental"),
            "comparator": comparison.get("comparator"),
            "text": comparison.get("text"),
        },
        "outcome": {
            "label": outcome.get("label"),
            "measure": outcome.get("measure"),
            "benefit_direction": outcome.get("benefit_direction"),
        },
        "timepoint": {
            "label": timepoint.get("label"),
            "window": timepoint.get("window"),
        },
        "subgroup": {
            "level": subgroup.get("level"),
            "source": subgroup.get("source"),
        },
        "data_type": setting.get("data_type"),
        "effect_measure": setting.get("effect_measure"),
    }


def _compact_study(study: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_id": study.get("study_id"),
        "population": _clip(study.get("population")),
        "intervention_comparator": _clip(study.get("intervention_comparator")),
        "outcomes": _clip(study.get("outcomes")),
        "methods": _clip(study.get("methods")),
        "notes": _clip(study.get("notes")),
    }


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_id": row.get("study_id"),
        "study_year": row.get("study_year"),
        "comparison": first_dict(row.get("comparison")),
        "outcome": first_dict(row.get("outcome")),
        "subgroup": first_dict(row.get("subgroup")),
        "analysis_note": _clip(row.get("analysis_note"), limit=300),
    }


def _judgement_from_llm(*, raw: dict[str, Any], evidence_package: dict[str, Any]) -> dict[str, Any]:
    severity = _severity(raw.get("severity"))
    downgraded = _downgraded(raw.get("downgraded"), severity)
    levels = _levels(raw.get("levels"), severity)
    if severity == "unclear" or downgraded == "unclear" or levels == "unclear":
        result = judgement(
            DOMAIN,
            downgraded="unclear",
            severity="unclear",
            levels="unclear",
            level_evaluable=False,
            rationale=str(raw.get("rationale") or "Indirectness could not be evaluated from the normalized input."),
        )
    else:
        result = judgement(
            DOMAIN,
            downgraded=downgraded,
            severity=severity,
            levels=levels,
            level_evaluable=True,
            rationale=str(raw.get("rationale") or ""),
        )
    result["debug"] = _debug(raw=raw, evidence_package=evidence_package, fallback_reason=None)
    return result


def _unclear(*, evidence_package: dict[str, Any], fallback_reason: str) -> dict[str, Any]:
    result = judgement(
        DOMAIN,
        downgraded="unclear",
        severity="unclear",
        levels="unclear",
        level_evaluable=False,
        rationale="Indirectness could not be evaluated because the LLM adjudicator was unavailable.",
    )
    result["debug"] = _debug(raw={}, evidence_package=evidence_package, fallback_reason=fallback_reason)
    return result


def _debug(*, raw: dict[str, Any], evidence_package: dict[str, Any], fallback_reason: str | None) -> dict[str, Any]:
    evidence_found = first_dict(evidence_package.get("evidence_found"))
    domain_comparisons = _domain_comparisons(raw.get("domain_comparisons"))
    debug = {
        "method": "method_llm",
        "input_policy": evidence_package.get("input_policy"),
        "population_source": _population_source(evidence_package),
        "llm_used": fallback_reason is None,
        "evidence_profile": _evidence_profile(raw.get("evidence_profile")),
        "directness_ratings": _directness_ratings(raw.get("directness_ratings")),
        "indirectness_domains": _domains(raw.get("indirectness_domains")),
        "domain_assessments": _domain_assessments(raw.get("domain_assessments"), fallback=domain_comparisons),
        "domain_comparisons": domain_comparisons,
        "supporting_evidence": _string_list(raw.get("supporting_evidence")),
        "counter_evidence": _string_list(raw.get("counter_evidence")),
        "confidence": _confidence(raw.get("confidence")),
        "decision_features": {
            "study_count": evidence_found.get("study_count", evidence_package.get("study_count")),
            "result_row_count": len(as_list(evidence_found.get("study_result_rows", evidence_package.get("study_result_rows")))),
            "missing_study_characteristics_count": len(
                as_list(
                    evidence_found.get(
                        "study_characteristics_missing_study_ids",
                        evidence_package.get("study_characteristics_missing_study_ids"),
                    )
                )
            ),
        },
    }
    if fallback_reason:
        debug["fallback_reason"] = fallback_reason
    return debug


def _population_source(evidence_package: dict[str, Any]) -> Any:
    synthesis_target_pico = first_dict(evidence_package.get("synthesis_target_pico"))
    if synthesis_target_pico:
        population = first_dict(synthesis_target_pico.get("population"))
        return population.get("source")
    target_question = first_dict(evidence_package.get("target_question"))
    if target_question:
        population = first_dict(target_question.get("population"))
        return population.get("source")
    return (evidence_package.get("target") or {}).get("population_source")


def _severity(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"none", "serious", "very_serious"}:
        return text
    return "unclear"


def _downgraded(value: Any, severity: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"yes", "no", "unclear"}:
        return text
    if severity == "none":
        return "no"
    if severity in {"serious", "very_serious"}:
        return "yes"
    return "unclear"


def _levels(value: Any, severity: str) -> int | str:
    if severity in SEVERITY_LEVELS:
        return SEVERITY_LEVELS[severity]
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return "unclear"
    return parsed if parsed in {0, 1, 2} else "unclear"


def _domains(value: Any) -> list[str]:
    return [item for item in _string_list(value) if item in set(DOMAINS)]


def _domain_assessments(value: Any, *, fallback: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    assessments: dict[str, dict[str, Any]] = {}
    for domain in DOMAINS:
        fallback_item = fallback.get(domain) if isinstance(fallback, dict) and isinstance(fallback.get(domain), dict) else {}
        item = source.get(domain) if isinstance(source.get(domain), dict) else fallback_item
        assessments[domain] = {
            "concern_level": _concern_level(item.get("concern_level")),
            "supporting_evidence": _string_list(item.get("supporting_evidence")),
            "counter_evidence": _string_list(item.get("counter_evidence")),
            "applicability_impact": str(item.get("applicability_impact") or ""),
        }
    return assessments


def _evidence_profile(value: Any) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    sections = (
        "population_scope",
        "intervention_variants",
        "comparator_context",
        "outcome_measurement",
        "follow_up",
        "setting_era_context",
        "representativeness_limits",
    )
    profile: dict[str, dict[str, Any]] = {}
    for section in sections:
        item = source.get(section) if isinstance(source.get(section), dict) else {}
        profile[section] = {
            "summary": str(item.get("summary") or ""),
            "findings": _string_list(item.get("findings")),
            "limits": _string_list(item.get("limits")),
            "applicability_impact": str(item.get("applicability_impact") or ""),
        }
    return profile


def _directness_ratings(value: Any) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    ratings: dict[str, dict[str, Any]] = {}
    for domain in DOMAINS:
        item = source.get(domain) if isinstance(source.get(domain), dict) else {}
        ratings[domain] = {
            "rating": _directness_rating(item.get("rating")),
            "rationale": str(item.get("rationale") or ""),
            "applicability_concern": str(item.get("applicability_concern") or ""),
        }
    return ratings


def _domain_comparisons(value: Any) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    comparisons: dict[str, dict[str, Any]] = {}
    for domain in DOMAINS:
        item = source.get(domain) if isinstance(source.get(domain), dict) else {}
        comparisons[domain] = {
            "target": str(item.get("target") or ""),
            "evidence_found": str(item.get("evidence_found") or ""),
            "relation": _relation(item.get("relation")),
            "concern_level": _concern_level(item.get("concern_level")),
            "applicability_impact": str(item.get("applicability_impact") or ""),
            "supporting_evidence": _string_list(item.get("supporting_evidence")),
            "counter_evidence": _string_list(item.get("counter_evidence")),
        }
    return comparisons


def _concern_level(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"none", "minor", "serious", "very_serious", "unclear"}:
        return text
    return "unclear"


def _relation(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"same", "narrower_but_applicable", "broader_but_applicable", "partial_overlap", "different", "unclear"}:
        return text
    return "unclear"


def _directness_rating(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"yes", "probably_yes", "probably_no", "no", "unclear"}:
        return text
    return "unclear"


def _confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"low", "moderate", "high"} else "low"


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in as_list(value) if str(item).strip()]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clip(value: Any, *, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def build_method() -> Method:
    return Method()
