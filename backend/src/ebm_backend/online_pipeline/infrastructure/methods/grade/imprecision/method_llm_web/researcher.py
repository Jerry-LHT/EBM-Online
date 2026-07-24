"""LLM web threshold research for GRADE imprecision."""

from __future__ import annotations

import json
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.client import call_llm_json
from ebm_backend.online_pipeline.infrastructure.llm.config import load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.thresholds import (
    fallback_threshold,
    normalize_threshold_result,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.prompt_loader import prompt_text
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.registry import (
    NullThresholdEvidenceRegistry,
    ThresholdEvidenceRegistry,
)


class LLMWebThresholdResearcher:
    """Find outcome-specific decision thresholds; do not make the GRADE judgement."""

    def __init__(
        self,
        *,
        config_path: str | None = None,
        model: str | None = None,
        registry: ThresholdEvidenceRegistry | None = None,
    ) -> None:
        self.config_path = config_path
        self.model = model
        self.registry = registry or NullThresholdEvidenceRegistry()

    def research(
        self,
        *,
        threshold_context: dict[str, Any] | None = None,
        audit_context: dict[str, Any] | None = None,
        setting_context: dict[str, Any] | None = None,
        numeric_features: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        research_context = threshold_context or _legacy_threshold_context(setting_context or {}, numeric_features or {})
        registry_key = str(research_context.get("threshold_research_key") or "")
        cached = self.registry.get(registry_key) if registry_key else None
        if cached is not None:
            cached["registry_stored"] = False
            return _with_context(cached, research_context, audit_context)
        config = load_llm_config(self.config_path, required=False)
        if config is None:
            return _with_context(fallback_threshold("missing_llm_config"), research_context, audit_context)
        if config.api_mode != "responses":
            return _with_context(fallback_threshold("web_search_requires_responses_api_mode"), research_context, audit_context)
        try:
            result = call_llm_json(
                config=config,
                system=prompt_text("threshold_system.txt"),
                prompt=threshold_prompt(threshold_context=research_context),
                model=self.model,
                temperature=0,
                tools=[{"type": "web_search"}],
            )
        except Exception as exc:  # pragma: no cover - network/provider dependent
            return _with_context(fallback_threshold(f"llm_web_error:{type(exc).__name__}:{exc}"), research_context, audit_context)
        threshold = normalize_threshold_result(result)
        threshold["registry_hit"] = False
        threshold["registry_key"] = registry_key
        threshold["registry_stored"] = bool(registry_key and self.registry.put(registry_key, threshold))
        return _with_context(threshold, research_context, audit_context)


class FallbackThresholdResearcher:
    """Deterministic researcher for tests and offline runs."""

    def research(
        self,
        *,
        threshold_context: dict[str, Any] | None = None,
        audit_context: dict[str, Any] | None = None,
        setting_context: dict[str, Any] | None = None,
        numeric_features: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        research_context = threshold_context or _legacy_threshold_context(setting_context or {}, numeric_features or {})
        return _with_context(fallback_threshold("offline_fallback"), research_context, audit_context)


def threshold_prompt(*, threshold_context: dict[str, Any]) -> str:
    outcome_type = str(threshold_context.get("outcome_type") or threshold_context.get("threshold_scale_context") or "").lower()
    if "continuous" in outcome_type:
        type_specific_task = (
            "Continuous outcome: identify the scale name, range, and direction, then find the MID/MCID. "
            "If no MID is directly found, derive one only from relevant source material or a clearly applicable scale convention. "
            "If the scale is unknown and no defensible MID can be reasoned, set threshold_kind='unavailable'."
        )
    elif "dichotomous" in outcome_type or "binary" in outcome_type:
        type_specific_task = (
            "Dichotomous outcome: prefer a clinically important absolute risk difference per 1000. "
            "If sources provide a relative threshold or enough source material to derive an absolute threshold, report it. "
            "Do not treat disease definitions, relapse definitions, diagnostic criteria, or severity cutoffs as imprecision thresholds. "
            "If no source-backed threshold is usable, provide a non-cacheable reasoned fallback absolute threshold per 1000 when clinically defensible."
        )
    else:
        type_specific_task = (
            "Use the outcome type and effect scale to find or derive a clinically important threshold. "
            "If not possible, provide a non-cacheable reasoned fallback only when clinically defensible."
        )
    payload = {
        "task": (
            "Find thresholds relevant to judging imprecision for this GRADE evidence body. "
            "Use the contextualization_mode in threshold_context. For systematic_review_minimally_contextualized mode, "
            "seek MID/MCID, clinical importance thresholds, and OIS assumptions suitable for review-level certainty, "
            "not recommendation-specific values/preferences or resource-use thresholds. "
            "Only use the structured threshold_context and web sources. "
            "The current effect estimate and confidence interval are intentionally not provided. "
            "Do not run a generic condition/outcome definition search. Search specifically for GRADE imprecision decision thresholds, "
            "minimal important differences, clinically important differences, absolute risk difference thresholds, non-inferiority margins, "
            "sample-size assumptions that prespecify a clinically important difference, guideline panel thresholds, "
            "and scale-specific MID/MCID evidence. Prefer GRADE/Cochrane methods guidance, guideline panel documents, "
            "scale validation papers, and clinical MID/MCID literature over disease definitions or review results. "
            + type_specific_task
        ),
        "threshold_context": threshold_context,
        "required_json_schema": {
            "research_workflow": {
                "query_plan": ["targeted query intents; never include review title, current effect, CI, or SoF footnote"],
                "retrieved_candidates": [
                    {
                        "source_url": "string",
                        "value_found": "string",
                        "candidate_type": "mid | absolute_risk_difference | ratio | ois | sample_size_assumption | scale_info | disease_definition | diagnostic_criterion | severity_cutoff | observed_effect | other",
                        "decision_threshold_signal": "explicit | derived | absent",
                        "applicability": "direct | indirect | general | not_applicable",
                    }
                ],
                "rejected_candidates": [
                    {
                        "source_url": "string",
                        "value_found": "string",
                        "rejection_reason": "disease_definition | diagnostic_criterion | severity_cutoff | wrong_scale | observed_effect | not_decision_threshold | insufficient_detail | other",
                    }
                ],
                "accepted_threshold": "object or null",
                "normalization": "string",
            },
            "outcome_type": "dichotomous | continuous | time_to_event | other",
            "contextualization_mode": "systematic_review_minimally_contextualized | guideline_panel_contextualized | custom_panel_contextualized",
            "scale_identified": "boolean",
            "scale_name": "string or null",
            "scale_range": "string or null",
            "scale_direction": "higher_is_better | lower_is_better | higher_is_worse | lower_is_worse | unknown",
            "threshold_kind": "absolute_risk_difference | ratio | continuous_mid | ois | unavailable",
            "derivation_type": "direct_source | derived_from_source | llm_reasoned_fallback | unavailable",
            "threshold_applicability": "direct | indirect | general_grade_default | not_applicable",
            "search_plan": ["string search intents actually pursued"],
            "accepted_candidates": [
                {
                    "source_url": "string",
                    "value_found": "string",
                    "candidate_type": "mid | absolute_risk_difference | ratio | ois | sample_size_assumption | scale_info | other",
                    "why_usable": "string",
                }
            ],
            "rejected_materials": [
                {
                    "source_url": "string",
                    "value_found": "string",
                    "rejection_reason": "disease_definition | diagnostic_criterion | severity_cutoff | wrong_scale | observed_effect | not_decision_threshold | insufficient_detail | other",
                }
            ],
            "threshold_found": "boolean",
            "reasoned_fallback": "boolean",
            "threshold_scale": "absolute_risk_difference_per_1000 | ratio | continuous_mid | none",
            "important_benefit": "number or null",
            "important_harm": "number or null",
            "minimal_important_difference": "number or null",
            "source_values": "object with extracted source values used for direct or derived thresholds",
            "threshold_derivation": "string explaining any calculation or why direct source is used",
            "fallback_scale": "absolute_risk_difference_per_1000 | ratio | continuous_mid | none",
            "fallback_benefit": "number or null",
            "fallback_harm": "number or null",
            "fallback_mid": "number or null",
            "fallback_rationale": "string",
            "optimal_information_size_notes": "string",
            "source_urls": ["string"],
            "source_confidence": "high | medium | low | none",
            "outcome_direction": "higher_is_better | lower_is_better | higher_is_worse | lower_is_worse | unknown",
            "cache_eligible": "boolean",
            "applicability_notes": "string",
        },
        "output_rules": [
            "Return threshold_found=true only for a threshold usable for imprecision on the requested outcome type.",
            "Populate research_workflow. It is the audit trail for the bounded workflow and must be consistent with accepted_candidates and rejected_materials.",
            "Use derivation_type='direct_source' only when the source directly states an MID/MCID, clinical decision threshold, non-inferiority margin, guideline panel threshold, or clinically important difference.",
            "Use derivation_type='derived_from_source' only when source material supports a transparent calculation from a prespecified clinically important difference.",
            "Use derivation_type='llm_reasoned_fallback' and reasoned_fallback=true when no usable source-backed threshold exists but a clinical fallback is defensible.",
            "For systematic_review_minimally_contextualized mode, reject recommendation direction, values/preferences, cost/resource thresholds, and overall panel tradeoff statements unless they contain an explicit MID/MCID, non-inferiority margin, decision threshold, or OIS/sample-size assumption.",
            "If a source only reports observed effects, event rates, absolute effects, confidence intervals, or a Summary of Findings row, reject it as not_decision_threshold.",
            "If a source provides only a disease definition, relapse definition, diagnostic cutoff, severity cutoff, or scale description without MID/decision threshold, reject it.",
            "If using the generic GRADE relative effect thresholds around RR 0.75 and 1.25, set threshold_applicability='general_grade_default' and cache_eligible=false; do not mark it direct to the outcome.",
            "For dichotomous absolute risk difference per 1000, benefit and harm must straddle 0; use negative values for fewer bad events when lower is better.",
            "For continuous MID, benefit and harm must straddle 0 on the effect scale.",
            "For ratio thresholds, benefit and harm must straddle 1.",
            "Do not set cache_eligible=true for llm_reasoned_fallback or general_grade_default.",
            "When source-backed threshold is unavailable, reasoned_fallback=true is required unless scale_identified=false for a continuous outcome or the outcome is uninterpretable.",
            "Always include rejected_materials when you found numeric values that are not usable as imprecision thresholds.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _with_context(threshold: dict[str, Any], threshold_context: dict[str, Any], audit_context: dict[str, Any] | None = None) -> dict[str, Any]:
    threshold = _enforce_context_compatibility(threshold, threshold_context)
    threshold["threshold_research_context"] = threshold_context
    threshold["threshold_audit_context"] = audit_context or {}
    threshold["threshold_research_key"] = threshold_context.get("threshold_research_key")
    return threshold


def _enforce_context_compatibility(threshold: dict[str, Any], threshold_context: dict[str, Any]) -> dict[str, Any]:
    if threshold.get("threshold_source_type") != "source_backed":
        return threshold
    if threshold.get("threshold_applicability") == "not_applicable":
        fallback = fallback_threshold("source_backed_threshold_not_applicable_to_requested_outcome")
        fallback["llm_raw_threshold"] = threshold
        fallback["source_urls"] = threshold.get("source_urls") or []
        fallback["applicability_notes"] = threshold.get("applicability_notes") or fallback["applicability_notes"]
        return fallback
    expected_scale = str(threshold_context.get("threshold_scale_context") or "")
    returned_scale = str(threshold.get("threshold_scale") or "")
    valid = bool(threshold.get("threshold_valid", True))
    compatible = True
    if expected_scale == "dichotomous_absolute_risk" and returned_scale not in {"absolute_risk_difference_per_1000", "ratio"}:
        compatible = False
    if expected_scale.startswith("continuous") and returned_scale not in {"continuous_mid"}:
        compatible = False
    if compatible and valid:
        return threshold
    fallback = fallback_threshold("source_backed_threshold_not_applicable_to_requested_scale")
    fallback["llm_raw_threshold"] = threshold
    fallback["incompatible_threshold_scale"] = returned_scale
    fallback["expected_threshold_scale_context"] = expected_scale
    fallback["source_urls"] = threshold.get("source_urls") or []
    fallback["applicability_notes"] = threshold.get("applicability_notes") or fallback["applicability_notes"]
    return fallback


def _legacy_threshold_context(setting_context: dict[str, Any], numeric_features: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition_context": setting_context.get("population"),
        "outcome_concept": setting_context.get("outcome"),
        "outcome_measure_or_scale": None,
        "timepoint_window": setting_context.get("timepoint"),
        "threshold_scale_context": numeric_features.get("data_type") or setting_context.get("data_type"),
        "data_type": numeric_features.get("data_type") or setting_context.get("data_type"),
        "intervention_context": None,
        "comparator_context": None,
        "contextualization_mode": "systematic_review_minimally_contextualized",
        "analysis_setting_context": {},
        "input_policy": "legacy_setting_context_no_effect_estimate",
        "sof_context_used": False,
        "question_text_used_for_threshold_research": False,
        "question_pico_used_for_threshold_research": False,
        "effect_estimate_used_for_threshold_research": False,
        "threshold_research_key": "",
    }
