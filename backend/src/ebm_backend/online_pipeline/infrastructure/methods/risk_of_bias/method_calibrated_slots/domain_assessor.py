"""Per-domain LLM assessment for the calibrated-slots RoB method."""

from __future__ import annotations

import json
import time
from typing import Any

from ebm_backend.online_pipeline.domain.risk_of_bias import RoB1DomainJudgement
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_calibrated_slots.domain_specs import DomainSpec
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_calibrated_slots.prompt_builder import build_system_prompt


def assess_domain(*, config: LLMConfig, spec: DomainSpec, evidence: str) -> RoB1DomainJudgement:
    system_prompt = build_system_prompt(spec)
    user_prompt = f"{evidence}\n\nAssess {spec.domain_label}. Output JSON only."
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            parsed = call_llm_json(config=config, system=system_prompt, prompt=user_prompt)
            return RoB1DomainJudgement(
                domain=spec.slot_id,
                judgement=_normalize_judgement(parsed.get("judgement")),
                rationale=str(parsed.get("support_text") or parsed.get("rationale") or ""),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt == 0:
                user_prompt = (
                    f"{evidence}\n\nAssess {spec.domain_label} again. "
                    "Your previous response could not be parsed. Return exactly one strict JSON object "
                    'with double-quoted keys and string values for "domain", "judgement", "support_text", and "source".'
                )
            else:
                break
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    return RoB1DomainJudgement(
        domain=spec.slot_id,
        judgement="unclear_risk",
        rationale=f"LLM call failed or returned invalid JSON for {spec.domain_label}: {last_error}",
    )


def _normalize_judgement(value: Any) -> str:
    text = str(value or "").lower().strip()
    if "low" in text:
        return "low_risk"
    if "high" in text:
        return "high_risk"
    return "unclear_risk"
