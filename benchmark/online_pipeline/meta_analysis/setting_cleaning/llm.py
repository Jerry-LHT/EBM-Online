"""LLM calls for meta-analysis setting cleaning."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm import call_llm_json
from benchmark.online_pipeline.q2pico.evaluation.judge import load_llm_config
from benchmark.online_pipeline.shared.prompts import render_prompt_template


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
FIELD_PROMPTS = {
    "comparison": PROMPT_DIR / "comparison_extraction_v1.txt",
    "outcome": PROMPT_DIR / "outcome_extraction_v1.txt",
    "timepoint": PROMPT_DIR / "timepoint_extraction_v1.txt",
}
LLM_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0, 20.0)


def extract_field_with_llm(*, field: str, candidate: dict[str, Any], llm_config: str | Path) -> dict[str, Any]:
    if field not in FIELD_PROMPTS:
        raise ValueError(f"Unsupported LLM extraction field: {field}")
    config = load_llm_config(llm_config)
    prompt = render_prompt_template(FIELD_PROMPTS[field], {"input_json": json.dumps(candidate, ensure_ascii=False)})
    parsed = _call_llm_json_with_retries(
        config=config,
        prompt=prompt,
        system=f"You extract the {field} field for a meta-analysis setting. Return only JSON.",
    )
    return coerce_field_extraction(field=field, candidate_id=str(candidate["candidate_id"]), parsed=parsed)


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
    if isinstance(exc, (ConnectionError, TimeoutError, json.JSONDecodeError)):
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


def coerce_field_extraction(*, field: str, candidate_id: str, parsed: dict[str, Any]) -> dict[str, Any]:
    base = {
        "candidate_id": candidate_id,
        "confidence": _nullable_text(parsed.get("confidence")) or "medium",
        "warnings": [str(item) for item in parsed.get("warnings") or []],
        "method": f"llm_{field}_v1",
    }
    if field == "comparison":
        comparison = parsed.get("comparison") if isinstance(parsed.get("comparison"), dict) else {}
        structure = parsed.get("comparison_structure") if isinstance(parsed.get("comparison_structure"), dict) else {}
        return {
            **base,
            "comparison": {
                "experimental": _nullable_text(comparison.get("experimental")),
                "comparator": _nullable_text(comparison.get("comparator")),
            },
            "comparison_structure": {
                "type": _comparison_structure_type(structure.get("type")),
                "rationale": _nullable_text(structure.get("rationale")),
            },
        }
    if field == "outcome":
        outcome = parsed.get("outcome") if isinstance(parsed.get("outcome"), dict) else {}
        return {
            **base,
            "outcome": {
                "outcome_concept": _nullable_text(outcome.get("outcome_concept")),
                "outcome_measure": _nullable_text(outcome.get("outcome_measure")),
            },
        }
    if field == "timepoint":
        timepoint = parsed.get("timepoint") if isinstance(parsed.get("timepoint"), dict) else {}
        return {
            **base,
            "timepoint": {
                "label": _nullable_text(timepoint.get("label")),
                "window": _nullable_text(timepoint.get("window")),
            },
        }
    raise ValueError(f"Unsupported field extraction: {field}")


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text or text.lower() in {"null", "none", "not specified", "not_applicable"}:
        return None
    return text


def _comparison_structure_type(value: Any) -> str:
    text = _nullable_text(value)
    if text in {"pairwise", "single_arm_or_index_only", "multi_arm", "unclear", "not_reported"}:
        return text
    return "unclear"
