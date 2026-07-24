"""Mode-aware inconsistency method with optional local LLM heterogeneity profiling."""

from __future__ import annotations

import json
import hashlib
import os
import time
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.client import call_llm_json
from ebm_backend.online_pipeline.infrastructure.llm.config import load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_local_llm_profile.utils import as_list, first_dict
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_local_llm_profile.prompt_loader import prompt_text
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_local_llm_profile.decision import (
    DOMAIN,
    decide_inconsistency,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_local_llm_profile.evidence import (
    extract_inconsistency_features,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_local_llm_profile.mode import (
    InconsistencyMethodConfig,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_local_llm_profile.profiler import (
    DIRECT,
    MINOR,
    SERIOUS,
    UNCLEAR,
    build_clinical_profile,
)


class Method:
    domain = DOMAIN

    def __init__(
        self,
        *,
        method_config: InconsistencyMethodConfig | None = None,
        config_path: str | None = None,
        model: str | None = None,
    ) -> None:
        self.method_config = method_config or InconsistencyMethodConfig.from_env()
        self.config_path = config_path
        self.model = model

    def run(self, *, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
        return predict(
            domain_evidence=domain_evidence,
            evidence_body=evidence_body,
            method_config=self.method_config,
            config_path=self.config_path,
            model=self.model,
        )


def predict(
    *,
    domain_evidence: dict[str, Any],
    evidence_body: dict[str, Any],
    method_config: InconsistencyMethodConfig | None = None,
    config_path: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    config = method_config or InconsistencyMethodConfig.from_env()
    features = extract_inconsistency_features(domain_evidence=domain_evidence, evidence_body=evidence_body)
    clinical_profile = build_clinical_profile(domain_evidence=domain_evidence, evidence_body=evidence_body)
    clinical_profile["method_config"] = config.audit_dict()
    if config.effective_allow_llm_profile():
        clinical_profile = _llm_refine_clinical_profile(
            domain_evidence=domain_evidence,
            evidence_body=evidence_body,
            clinical_profile=clinical_profile,
            config_path=config_path,
            model=model,
        )
        clinical_profile["method_config"] = config.audit_dict()
    return decide_inconsistency(features=features, clinical_profile=clinical_profile)


def _llm_refine_clinical_profile(
    *,
    domain_evidence: dict[str, Any],
    evidence_body: dict[str, Any],
    clinical_profile: dict[str, Any],
    config_path: str | None,
    model: str | None,
) -> dict[str, Any]:
    config = load_llm_config(config_path, required=False)
    if config is None:
        return {**clinical_profile, "fallback_reason": "missing_llm_config"}
    selected_model = model or config.model
    prompt = _llm_profile_prompt(
        domain_evidence=domain_evidence,
        evidence_body=evidence_body,
        clinical_profile=clinical_profile,
    )
    cache_key = _cache_key(model=selected_model, prompt=prompt)
    cached = _read_profile_cache(cache_key)
    if cached is not None:
        refined = _normalize_llm_profile(parsed=cached, fallback_profile=clinical_profile)
        refined["llm_used"] = True
        refined["llm_cache_hit"] = True
        return refined
    attempts = _retry_count()
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(min(2 ** (attempt - 1), 8))
        try:
            parsed = call_llm_json(
                config=config,
                system=prompt_text("profile_system.txt"),
                prompt=prompt,
                model=model,
                timeout_seconds=_timeout_seconds(),
                temperature=0,
            )
            _write_profile_cache(cache_key, parsed)
            refined = _normalize_llm_profile(parsed=parsed, fallback_profile=clinical_profile)
            refined["llm_used"] = True
            refined["llm_cache_hit"] = False
            refined["llm_attempts"] = attempt
            return refined
        except Exception as exc:  # pragma: no cover - provider dependent
            last_exc = exc
    assert last_exc is not None
    return {**clinical_profile, "fallback_reason": f"llm_error:{type(last_exc).__name__}:{last_exc}", "llm_attempts": attempts}


def _llm_profile_prompt(
    *,
    domain_evidence: dict[str, Any],
    evidence_body: dict[str, Any],
    clinical_profile: dict[str, Any],
) -> str:
    setting = first_dict(domain_evidence.get("analysis_setting"), evidence_body.get("analysis_setting"))
    study_rows = [
        {
            "study_id": row.get("study_id"),
            "data_type": row.get("data_type"),
            "comparison": row.get("comparison"),
            "outcome": row.get("outcome"),
            "subgroup": row.get("subgroup"),
        }
        for row in as_list(domain_evidence.get("meta_analysis_data_rows") or evidence_body.get("meta_analysis_data_rows"))[:80]
        if isinstance(row, dict)
    ]
    study_characteristics = [
        {
            "study_id": row.get("study_id"),
            "population": _clip_text(row.get("population"), 1200),
            "intervention_comparator": _clip_text(row.get("intervention_comparator"), 900),
            "outcomes": _clip_text(row.get("outcomes"), 900),
            "methods": _clip_text(row.get("methods"), 700),
            "notes": _clip_text(row.get("notes"), 400),
        }
        for row in as_list(domain_evidence.get("study_characteristics") or evidence_body.get("study_characteristics"))[:30]
        if isinstance(row, dict)
    ]
    payload = {
        "task": "Refine a clinical/methodological heterogeneity profile for inconsistency. Do not decide final downgrade.",
        "rating_labels": [DIRECT, MINOR, SERIOUS, UNCLEAR],
        "analysis_setting": {
            "comparison": setting.get("comparison"),
            "outcome": setting.get("outcome"),
            "timepoint": setting.get("timepoint"),
            "subgroup": setting.get("subgroup"),
            "data_type": setting.get("data_type"),
            "effect_measure": setting.get("effect_measure"),
        },
        "population_context": first_dict(domain_evidence.get("population_context"), evidence_body.get("population_context")),
        "study_rows": study_rows,
        "study_characteristics": study_characteristics,
        "rule_seed_profile": clinical_profile,
        "required_json_schema": {
            "domain_ratings": {
                "population_variability": "direct | minor_concern | serious_concern | unclear",
                "intervention_variability": "direct | minor_concern | serious_concern | unclear",
                "comparator_variability": "direct | minor_concern | serious_concern | unclear",
                "outcome_definition_variability": "direct | minor_concern | serious_concern | unclear",
                "measurement_tool_variability": "direct | minor_concern | serious_concern | unclear",
                "timepoint_variability": "direct | minor_concern | serious_concern | unclear",
                "methodological_variability": "direct | minor_concern | serious_concern | unclear",
            },
            "body_signals": [{"domain": "string", "severity": "serious | minor | unclear", "rationale": "short reason from normalized input"}],
            "not_final_grade_judgement": True,
        },
        "rules": [
            "Use serious only when heterogeneity plausibly affects consistency of effect estimates for the target outcome.",
            "If studies differ but the difference is unlikely to modify the effect estimate, use minor_concern or direct.",
            "If the text does not allow comparison across studies, use unclear rather than serious.",
            "Do not mark serious because follow-up duration, outcome lists, or study design text is long or detailed.",
            "Do not infer a downgrade from wide confidence intervals or sparse data alone.",
            "Do not use SoF text, footnotes, gold labels, review title, or web knowledge.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _normalize_llm_profile(*, parsed: dict[str, Any], fallback_profile: dict[str, Any]) -> dict[str, Any]:
    ratings = dict(first_dict(fallback_profile.get("domain_ratings")))
    parsed_ratings = first_dict(parsed.get("domain_ratings"))
    for domain, value in parsed_ratings.items():
        ratings[str(domain)] = _rating(value, fallback=ratings.get(str(domain), DIRECT))
    body_signals = [
        {
            "domain": str(signal.get("domain") or "unknown"),
            "severity": str(signal.get("severity") or "unclear"),
            "rationale": str(signal.get("rationale") or ""),
        }
        for signal in as_list(parsed.get("body_signals"))
        if isinstance(signal, dict)
    ]
    if not body_signals:
        body_signals = as_list(fallback_profile.get("body_signals"))
    return {
        **fallback_profile,
        "domain_ratings": ratings,
        "body_signals": body_signals,
        "not_final_grade_judgement": True,
    }


def _rating(value: Any, *, fallback: str) -> str:
    text = str(value or fallback or UNCLEAR)
    return text if text in {DIRECT, MINOR, SERIOUS, UNCLEAR} else UNCLEAR


def _clip_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " ..."


def _cache_key(*, model: str, prompt: str) -> str:
    payload = json.dumps(
        {"model": model, "system": prompt_text("profile_system.txt"), "prompt": prompt},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_dir() -> Path:
    raw = os.getenv("GRADE_INCONSISTENCY_LLM_CACHE_DIR") or ".cache/grade_inconsistency_llm_profile"
    return Path(raw)


def _read_profile_cache(key: str) -> dict[str, Any] | None:
    path = _cache_dir() / f"{key}.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _write_profile_cache(key: str, value: dict[str, Any]) -> None:
    path = _cache_dir() / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _retry_count() -> int:
    raw = os.getenv("GRADE_INCONSISTENCY_LLM_RETRIES") or "2"
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


def _timeout_seconds() -> float:
    raw = os.getenv("GRADE_INCONSISTENCY_LLM_TIMEOUT_SECONDS") or "45"
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 45.0


def build_method() -> Method:
    return Method()
