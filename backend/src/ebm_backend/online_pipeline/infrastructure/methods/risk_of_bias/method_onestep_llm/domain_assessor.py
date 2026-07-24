"""Per-domain LLM assessment for the one-step RoB method."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Callable

from ebm_backend.online_pipeline.domain.risk_of_bias import RoB1DomainJudgement
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.errors import (
    RiskOfBiasDomainInvocationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.prompt_builder import (
    DOMAIN_LABELS,
    build_system_prompt,
)


LLMJSONCaller = Callable[..., dict[str, Any]]
MAX_ATTEMPTS = 2


def domain_contract_fingerprint(domain_id: str) -> str:
    """Hash the exact prompt and schema contract used by one RoB domain."""

    payload = {
        "system_prompt": build_system_prompt(domain_id),
        "response_schema": _domain_response_schema(domain_id),
        "max_attempts": MAX_ATTEMPTS,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def assess_domain(
    *,
    config: LLMConfig,
    domain_id: str,
    evidence: str,
    study_id: str,
    caller: LLMJSONCaller = call_llm_json,
) -> RoB1DomainJudgement:
    prompt = build_system_prompt(domain_id)
    user_prompt = f"{evidence}\n\nAssess {DOMAIN_LABELS[domain_id]}. Output JSON only."
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            parsed = caller(
                config=config,
                system=prompt,
                prompt=user_prompt,
                json_schema=_domain_response_schema(domain_id),
                json_schema_name=f"risk_of_bias_{domain_id}",
            )
            judgement, rationale = _validate_domain_response(
                parsed,
                domain_id=domain_id,
            )
            return RoB1DomainJudgement(
                domain=domain_id,
                judgement=judgement,
                rationale=rationale,
            )
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                user_prompt = (
                    f"{evidence}\n\nAssess {DOMAIN_LABELS[domain_id]} again. "
                    "Your previous response could not be parsed. Return exactly one strict JSON object "
                    'with double-quoted keys and string values for "domain", "judgement", and "support_text".'
                )
    error = RiskOfBiasDomainInvocationError(
        study_id=study_id,
        domain=domain_id,
        attempts=MAX_ATTEMPTS,
    )
    raise error from last_error


def _domain_response_schema(domain_id: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["domain", "judgement", "support_text"],
        "properties": {
            "domain": {
                "type": "string",
                "enum": [DOMAIN_LABELS[domain_id]],
            },
            "judgement": {
                "type": "string",
                "enum": ["Low risk", "High risk", "Unclear risk"],
            },
            "support_text": {"type": "string", "minLength": 1},
        },
    }


def _validate_domain_response(
    value: Any,
    *,
    domain_id: str,
) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Risk of Bias domain response must be an object")
    expected_keys = {"domain", "judgement", "support_text"}
    if set(value) != expected_keys:
        raise ValueError(
            "Risk of Bias domain response must contain exactly: "
            "domain, judgement, support_text"
        )
    if value["domain"] != DOMAIN_LABELS[domain_id]:
        raise ValueError("Risk of Bias response returned the wrong domain")
    judgement_map = {
        "Low risk": "low_risk",
        "High risk": "high_risk",
        "Unclear risk": "unclear_risk",
    }
    judgement = judgement_map.get(value["judgement"])
    if judgement is None:
        raise ValueError("Risk of Bias response returned an unsupported judgement")
    if not isinstance(value["support_text"], str) or not value["support_text"].strip():
        raise ValueError("Risk of Bias support_text must be a non-empty string")
    return judgement, value["support_text"].strip()
