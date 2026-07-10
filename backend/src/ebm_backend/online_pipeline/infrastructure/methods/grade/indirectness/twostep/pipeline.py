"""Pipeline orchestration for the two-step indirectness method."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.config import load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.twostep.evidence import (
    _build_evidence_package,
    _dict,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.twostep.llm import call_json_with_retries
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.twostep.normalization import (
    _judgement_from_llm,
    _unclear,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.twostep.prompts import (
    adjudication_prompt,
    extraction_prompt,
    prompt_text,
    threshold_prompt,
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
    return _predict_with_config(
        evidence_package=evidence_package,
        config=config,
        model=model,
        fallback_prefix="twostep",
    )


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
    return [
        _batch_output(
            method_instance=item["method_instance"],
            judgement_payload=_predict_with_config(
                evidence_package=item["evidence_package"],
                config=config,
                model=model,
                fallback_prefix="twostep_batch_item",
            ),
            batch_size=len(batch_items),
        )
        for item in batch_items
    ]


def _predict_with_config(
    *,
    evidence_package: dict[str, Any],
    config: Any,
    model: str | None,
    fallback_prefix: str,
) -> dict[str, Any]:
    try:
        extraction = _extract_with_config(evidence_package=evidence_package, config=config, model=model)
        threshold_policy = _threshold_with_config(
            evidence_package=evidence_package,
            extraction=extraction,
            config=config,
            model=model,
        )
        raw = _adjudicate_with_config(
            evidence_package=evidence_package,
            extraction=extraction,
            threshold_policy=threshold_policy,
            config=config,
            model=model,
        )
    except Exception as exc:  # pragma: no cover - provider/network dependent
        return _unclear(
            evidence_package=evidence_package,
            fallback_reason=f"{fallback_prefix}:llm_error:{type(exc).__name__}:{exc}",
        )
    result = _judgement_from_llm(
        raw=raw,
        evidence_package=evidence_package,
        extraction=extraction,
        threshold_policy=threshold_policy,
    )
    debug = result.get("debug")
    if isinstance(debug, dict):
        debug["fallback_recovered_from"] = fallback_prefix
    return result


def _extract_with_config(*, evidence_package: dict[str, Any], config: Any, model: str | None) -> dict[str, Any]:
    return call_json_with_retries(
        config=config,
        system=prompt_text("system.txt"),
        prompt=extraction_prompt(evidence_package),
        model=model,
        temperature=0,
    )


def _threshold_with_config(
    *,
    evidence_package: dict[str, Any],
    extraction: dict[str, Any],
    config: Any,
    model: str | None,
) -> dict[str, Any]:
    return call_json_with_retries(
        config=config,
        system=prompt_text("system.txt"),
        prompt=threshold_prompt(evidence_package=evidence_package, extraction=extraction),
        model=model,
        temperature=0,
    )


def _adjudicate_with_config(
    *,
    evidence_package: dict[str, Any],
    extraction: dict[str, Any],
    threshold_policy: dict[str, Any],
    config: Any,
    model: str | None,
) -> dict[str, Any]:
    return call_json_with_retries(
        config=config,
        system=prompt_text("system.txt"),
        prompt=adjudication_prompt(
            evidence_package=evidence_package,
            extraction=extraction,
            threshold_policy=threshold_policy,
        ),
        model=model,
        temperature=0,
    )


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
