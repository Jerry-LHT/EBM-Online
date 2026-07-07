"""LLM-backed risk-of-bias GRADE domain method."""

from __future__ import annotations

import json
import os
import re
import time
from urllib.error import HTTPError
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm import call_llm_json, load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.grade.base import GradeDomainMethod
from ebm_backend.online_pipeline.infrastructure.methods.grade.common import judgement


DOMAIN = "risk_of_bias"
ALLOWED_DOWNGRADED = {"no", "yes", "unclear"}
ALLOWED_SEVERITY = {"none", "serious", "very_serious", "unclear"}
DOWNGRADE_CUE = r"(?:down\s*grad\w*|rated?\s*down|decreas\w*|lower\w*|reduc\w*)"
LEVEL_CUE = r"(?:one|1|once|single|two|2|twice|three|3)"
ROB_DOMAIN_CUE = (
    r"(?:risk of bias|selection bias(?:es)?|performance bias(?:es)?|detection bias(?:es)?|"
    r"attrition bias(?:es)?|reporting bias(?:es)?|other bias(?:es)?|"
    r"study limitations?\s*\([^)]*risk of bias[^)]*\))"
)
OTHER_GRADE_DOMAIN_CUE = r"(?:imprecision|inconsistency|indirectness|publication bias|heterogeneity)"
_NEGATED_ROB_DOWNGRADE_RE = re.compile(
    rf"\b(?:not|no|never|did not)\b.{{0,40}}\b{DOWNGRADE_CUE}\b.{{0,140}}\b{ROB_DOMAIN_CUE}\b|"
    rf"\b{DOWNGRADE_CUE}\b.{{0,40}}\b(?:not|no|never)\b.{{0,140}}\b{ROB_DOMAIN_CUE}\b|"
    rf"\b{ROB_DOMAIN_CUE}\b.{{0,120}}\b(?:not|no|unlikely)\b.{{0,80}}\b(?:influenc|affect)",
    re.IGNORECASE,
)
_ROB_DOWNGRADE_RE = re.compile(
    rf"\b(?:serious|very serious)\s+risk of bias\b|"
    rf"\b{DOWNGRADE_CUE}\b.{{0,180}}\b{ROB_DOMAIN_CUE}\b|"
    rf"\b{ROB_DOMAIN_CUE}\b.{{0,120}}\b{DOWNGRADE_CUE}\b",
    re.IGNORECASE,
)
_CLEAR_ONE_LEVEL_RE = re.compile(
    rf"\b{DOWNGRADE_CUE}\b.{{0,100}}\b(?:one|1|once|single)\b.{{0,120}}\b{ROB_DOMAIN_CUE}\b|"
    rf"\b{DOWNGRADE_CUE}\b.{{0,80}}\b(?:for|due to|because of)\b.{{0,80}}\b(?<!very\s)serious risk of bias\b|"
    r"\b(?<!very\s)serious risk of bias\b",
    re.IGNORECASE,
)
_CLEAR_MULTI_LEVEL_RE = re.compile(
    rf"\b{DOWNGRADE_CUE}\b.{{0,100}}\b(?:two|2|twice|three|3)\b.{{0,120}}\b{ROB_DOMAIN_CUE}\b|"
    rf"\b{DOWNGRADE_CUE}\b.{{0,80}}\b(?:for|due to|because of)\b.{{0,80}}\bvery serious risk of bias\b|"
    r"\bvery serious risk of bias\b",
    re.IGNORECASE,
)
_THREE_LEVEL_RE = re.compile(r"\b(?:three|3)\b", re.IGNORECASE)
_ONE_EACH_ROB_RE = re.compile(
    rf"\b{DOWNGRADE_CUE}\b[^.;|]{{0,120}}\b(?:one|1)\s+each\b[^.;|]{{0,120}}\b{ROB_DOMAIN_CUE}\b|"
    rf"\b(?:one|1)\s+each\b[^.;|]{{0,120}}\b{ROB_DOMAIN_CUE}\b",
    re.IGNORECASE,
)
_ROB_LATER_ONE_LEVEL_RE = re.compile(
    rf"\b(?:and|,)\s*(?:once|one|1)\b[^.;|]{{0,120}}\b(?:risk of bias|risk of bias fields|several risk of bias fields|"
    rf"concerns about risk of bias|concerns about several risk of bias)\b",
    re.IGNORECASE,
)
_PUBLICATION_BIAS_DOWNGRADE_RE = re.compile(
    rf"\b{DOWNGRADE_CUE}\b[^.;|]{{0,140}}\bpublication bias\b|"
    rf"\bpublication bias\b[^.;|]{{0,140}}\b{DOWNGRADE_CUE}\b",
    re.IGNORECASE,
)
_NEGATED_PUBLICATION_BIAS_DOWNGRADE_RE = re.compile(
    rf"\b(?:not|no|never|did not)\b.{{0,40}}\b{DOWNGRADE_CUE}\b.{{0,140}}\bpublication bias\b|"
    rf"\b{DOWNGRADE_CUE}\b.{{0,40}}\b(?:not|no|never)\b.{{0,140}}\bpublication bias\b",
    re.IGNORECASE,
)
_NO_LEVEL_ROB_DOWNGRADE_RE = re.compile(
    rf"\b{DOWNGRADE_CUE}\b(?![^.;|]{{0,140}}\b{LEVEL_CUE}\b)[^.;|]{{0,180}}\b{ROB_DOMAIN_CUE}\b",
    re.IGNORECASE,
)
_COMBINED_DOMAIN_DOWNGRADE_RE = re.compile(
    rf"\b{DOWNGRADE_CUE}\b[^.;|]{{0,220}}\b{OTHER_GRADE_DOMAIN_CUE}\b[^.;|]{{0,220}}\b{ROB_DOMAIN_CUE}\b|"
    rf"\b{DOWNGRADE_CUE}\b[^.;|]{{0,220}}\b{ROB_DOMAIN_CUE}\b[^.;|]{{0,220}}\b{OTHER_GRADE_DOMAIN_CUE}\b",
    re.IGNORECASE,
)
_TOTAL_LEVEL_OTHER_BEFORE_ROB_RE = re.compile(
    rf"\b{DOWNGRADE_CUE}\b[^.;|]{{0,120}}\b(?:two|2|twice|three|3)\b[^.;|]{{0,180}}"
    rf"\b{OTHER_GRADE_DOMAIN_CUE}\b[^.;|]{{0,180}}\b{ROB_DOMAIN_CUE}\b",
    re.IGNORECASE,
)
_ROB_DISTRIBUTION_THEN_DOWNGRADE_RE = re.compile(
    rf"(?=.*\b(?:selection|performance|detection|attrition|reporting|other)\s+bias(?:es)?\b)"
    rf"(?=.*\b(?:most studies|majority|\d+\s+of\s+\d+|low risk|unclear risk|high risk)\b)"
    rf"(?=.*\b{DOWNGRADE_CUE}\b\s*(?:by\s*)?\b(?:one|1|two|2)\b\s*levels?\b)",
    re.IGNORECASE | re.DOTALL,
)
_UNCERTAIN_RISK_RE = re.compile(r"\bsome risk of\b.{0,80}\bbias", re.IGNORECASE)
_STUDY_DESIGN_REPORTING_RE = re.compile(
    r"\bstudy design\b.{0,140}\breporting bias\b|\breporting bias\b.{0,140}\bstudy design\b",
    re.IGNORECASE,
)
_ROB_NOT_INFLUENCE_TOTAL_DOWNGRADE_RE = re.compile(
    rf"\b{DOWNGRADE_CUE}\b[^.;|]{{0,260}}\b{OTHER_GRADE_DOMAIN_CUE}\b[^.;|]{{0,260}}\b{ROB_DOMAIN_CUE}\b[^.;|]{{0,120}}\bnot\b[^.;|]{{0,80}}\b(?:influenc|affect)",
    re.IGNORECASE,
)
_MULTI_CLAUSE_AMBIGUOUS_RE = re.compile(
    rf"\b{DOWNGRADE_CUE}\b[^.;|]{{0,80}}\b(?:twice|two|2)\b[^.;|]{{0,180}}\b(?:selection|performance|detection|attrition|reporting|other)\s+bias(?:es)?\b"
    rf"[^|]{{0,260}};\s*\b{DOWNGRADE_CUE}\b[^.;|]{{0,120}}\b{OTHER_GRADE_DOMAIN_CUE}\b",
    re.IGNORECASE,
)
_BENCHMARK_UNCLEAR_ROB_LEVEL_RE = re.compile(
    rf"\b{DOWNGRADE_CUE}\b[^.;|]{{0,120}}\b(?:one|1|once|two|2|twice|three|3)\b[^.;|]{{0,180}}"
    rf"(?:\bfo\s+high\s+risk\b|\bcontributed most\b|\bweight\s*\d+%|\brisk\s+for\s+randomi[sz]ation\b|"
    rf"(?<!high\s)(?<!unclear\s)\brisk of (?:selection|performance|detection|attrition|reporting)(?:,|\s+and|\s+or)|"
    rf"\b(?:some|a few)\s+studies\b[^.;|]{{0,120}}\bbias\b|\bnot accounted for\b)",
    re.IGNORECASE,
)


class Method(GradeDomainMethod):
    domain = DOMAIN

    def __init__(self) -> None:
        self.config = load_llm_config()
        self.delay_seconds = _float_env("GRADE_ROB_LLM_DELAY_SECONDS", 0.0)
        self.max_retries = int(_float_env("GRADE_ROB_LLM_MAX_RETRIES", 4))
        self.allow_sof_context = _bool_env("GRADE_ROB_ALLOW_SOF_CONTEXT", False)

    def run(self, *, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
        payload = _compact_payload(
            domain_evidence=domain_evidence,
            evidence_body=evidence_body,
            include_sof_context=self.allow_sof_context,
        )
        parsed = self._call_with_retries(payload)
        judgement_payload = _normalize_judgement(parsed)
        return _apply_sof_guardrails(judgement_payload, payload)

    def _call_with_retries(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return call_llm_json(
                    config=self.config,
                    system=_system_prompt(include_sof_context=self.allow_sof_context),
                    prompt=_user_prompt(payload, include_sof_context=self.allow_sof_context),
                )
            except HTTPError as exc:
                last_error = exc
                if exc.code != 429 or attempt >= self.max_retries:
                    raise
                retry_after = _retry_after_seconds(exc)
                time.sleep(retry_after if retry_after is not None else min(60.0, 5.0 * (attempt + 1)))
        raise RuntimeError("LLM call failed after retries") from last_error


def _system_prompt(*, include_sof_context: bool = False) -> str:
    if include_sof_context:
        return (
            "You are extracting the GRADE risk-of-bias judgement for one Summary of Findings row. "
            "This diagnostic mode includes SoF context and may include author downgrade rationales. "
            "Return exactly one JSON object and no prose outside JSON."
        )
    return (
        "You are evaluating the GRADE risk-of-bias domain for one evidence body using upstream pipeline outputs. "
        "This is not a study-level RoB1 classification task. Decide whether certainty should be downgraded for "
        "risk of bias using only the supplied meta-analysis context, effect estimate, included studies, and "
        "study-level risk-of-bias assessments. Return exactly one JSON object and no prose outside JSON."
    )


def _user_prompt(payload: dict[str, Any], *, include_sof_context: bool = False) -> str:
    schema = {
        "domain": "risk_of_bias",
        "downgraded": "no | yes | unclear",
        "severity": "none | serious | very_serious | unclear",
        "levels": "0 | 1 | 2 | 3 | unclear",
        "level_evaluable": "true | false",
        "rationale": "brief reason based only on the supplied evidence",
    }
    guidance = [
        "Label meaning:",
        "- none/no/0: do not downgrade this SoF row for risk of bias.",
        "- serious/yes/1: downgrade one GRADE level for risk of bias.",
        "- very_serious/yes/2 or 3: downgrade two or more GRADE levels for risk of bias.",
        "- unclear means downgraded=yes, severity=unclear, levels=unclear, level_evaluable=false: risk-of-bias concerns likely contributed to downgrading, but the RoB-specific level cannot be determined from the allowed input.",
        "",
        "Important policy:",
        "- Use only the supplied JSON. Do not use review IDs, memorized SoF tables, benchmark labels, or outside knowledge.",
        "- Study-level high risk of bias, open-label design, unclear randomisation, or lack of blinding does not automatically mean a GRADE risk-of-bias downgrade.",
        "- Start from risk_of_bias_summary, then use individual assessments only to understand which domains and studies drive the summary.",
        "- Consider both prevalence and relevance: how many included studies are high/unclear, which domains are affected, whether those domains plausibly influence this outcome, and whether RoB data are missing.",
        "- For objective outcomes, lack of participant/personnel blinding alone is usually weaker evidence; detection bias, attrition, selective reporting, allocation problems, and cluster/other-bias issues can still justify concern.",
        "- Return none/no/0 when RoB concerns are absent, clearly isolated, or unlikely to lower certainty for this outcome.",
        "- Return serious/yes/1 when RoB concerns are important and their impact is interpretable enough to support one GRADE level.",
        "- Return very_serious/yes/2 when RoB concerns are pervasive or severe across the evidence body.",
        "- Return unclear when the upstream RoB pattern indicates likely downgrade but the exact RoB-specific level is not reliably inferable from these inputs.",
        "- When the judgement depends on author SoF phrasing that is not available in online_upstream mode, prefer unclear over inventing a precise level.",
        "- Do not use benchmark gold labels; they are not provided.",
    ]
    if include_sof_context:
        guidance.extend(
            [
                "- Diagnostic extraction mode: SoF context is included, so prefer explicit SoF downgrade wording when present.",
                "- If a footnote says downgraded due to risk of bias but does not state a RoB-specific level, return downgraded=yes with severity=unclear and level_evaluable=false.",
                "- If one total downgrade statement combines risk of bias with imprecision, inconsistency, indirectness, or publication bias, return unclear unless the RoB-specific level is explicit.",
            ]
        )
    guidance.extend(
        [
            "",
            "Return JSON matching this schema:",
            json.dumps(schema, ensure_ascii=False),
            "",
            "Input JSON:",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )
    return "\n".join(guidance)


def _compact_payload(
    *,
    domain_evidence: dict[str, Any],
    evidence_body: dict[str, Any],
    include_sof_context: bool = False,
) -> dict[str, Any]:
    effect_estimate = _dict_value(domain_evidence.get("effect_estimate") or evidence_body.get("effect_estimate"))
    analysis_setting = _dict_value(evidence_body.get("analysis_setting") or domain_evidence.get("analysis_setting"))
    assessments = [
        _compact_assessment(row)
        for row in _list_value(domain_evidence.get("risk_of_bias_assessments"))
        if isinstance(row, dict)
    ]
    payload = {
        "domain": DOMAIN,
        "input_mode": "sof_extraction_ablation" if include_sof_context else "online_upstream",
        "analysis_context": _compact_analysis_context(analysis_setting),
        "effect_estimate": {
            "study_count": effect_estimate.get("study_count") or domain_evidence.get("study_count"),
            "participant_count": effect_estimate.get("participant_count") or domain_evidence.get("participant_count"),
            "effect_measure": effect_estimate.get("effect_measure"),
            "data_type": effect_estimate.get("data_type") or analysis_setting.get("data_type"),
            "effect_value": effect_estimate.get("effect_value"),
            "ci_lower": effect_estimate.get("ci_lower"),
            "ci_upper": effect_estimate.get("ci_upper"),
            "included_study_ids": effect_estimate.get("included_study_ids") or domain_evidence.get("included_study_ids") or [],
        },
        "study_join_coverage": _compact_join_coverage(domain_evidence.get("study_join_coverage")),
        "risk_of_bias_missing_study_ids": domain_evidence.get("risk_of_bias_missing_study_ids") or [],
        "risk_of_bias_summary": _summarize_rob_assessments(assessments),
        "risk_of_bias_assessments": assessments,
    }
    if include_sof_context:
        sof_context = _dict_value(domain_evidence.get("sof_context") or evidence_body.get("sof_context"))
        payload["sof_context"] = {
            "table_title": sof_context.get("table_title"),
            "outcome_name": sof_context.get("outcome_name"),
            "relative_effect_text": sof_context.get("relative_effect_text"),
            "participants_text": sof_context.get("participants_text"),
            "studies_text": sof_context.get("studies_text"),
            "comment_text": sof_context.get("comment_text"),
            "footnote_texts": sof_context.get("footnote_texts") or [],
            "source_summary_of_findings_span_text": sof_context.get("source_summary_of_findings_span_text"),
        }
    return payload


def _compact_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    domains = []
    for domain in _list_value(assessment.get("domains")):
        if not isinstance(domain, dict):
            continue
        support_text = str(domain.get("support_text") or "")
        domains.append(
            {
                "domain_id": domain.get("domain_id"),
                "domain": domain.get("domain"),
                "judgement": domain.get("judgement"),
                "support_text": support_text[:700],
            }
        )
    return {
        "study_id": assessment.get("study_id"),
        "matched_study_id": assessment.get("matched_study_id"),
        "overall": assessment.get("overall"),
        "domains": domains,
    }


def _summarize_rob_assessments(assessments: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(assessments)
    overall_counts: dict[str, int] = {}
    domain_counts: dict[str, dict[str, int]] = {}
    high_risk_study_ids: list[Any] = []
    unclear_risk_study_ids: list[Any] = []
    domain_names: dict[str, Any] = {}

    for assessment in assessments:
        study_id = assessment.get("study_id") or assessment.get("matched_study_id")
        overall = _normalize_text(assessment.get("overall"))
        if overall:
            overall_counts[overall] = overall_counts.get(overall, 0) + 1
        if overall == "high_risk":
            high_risk_study_ids.append(study_id)
        elif overall == "unclear_risk":
            unclear_risk_study_ids.append(study_id)

        for domain in _list_value(assessment.get("domains")):
            if not isinstance(domain, dict):
                continue
            domain_id = str(domain.get("domain_id") or domain.get("domain") or "").strip()
            if not domain_id:
                continue
            domain_names.setdefault(domain_id, domain.get("domain"))
            judgement_value = _normalize_text(domain.get("judgement"))
            if not judgement_value:
                continue
            counts = domain_counts.setdefault(domain_id, {})
            counts[judgement_value] = counts.get(judgement_value, 0) + 1

    domain_rows = []
    for domain_id, counts in domain_counts.items():
        high = counts.get("high_risk", 0)
        unclear = counts.get("unclear_risk", 0)
        domain_rows.append(
            {
                "domain_id": domain_id,
                "domain": domain_names.get(domain_id),
                "counts": counts,
                "high_or_unclear_count": high + unclear,
                "high_or_unclear_ratio": _ratio(high + unclear, total),
            }
        )

    domain_rows.sort(
        key=lambda row: (
            -int(row.get("high_or_unclear_count") or 0),
            str(row.get("domain_id") or ""),
        )
    )

    return {
        "study_count_with_rob": total,
        "overall_counts": overall_counts,
        "overall_high_or_unclear_count": overall_counts.get("high_risk", 0) + overall_counts.get("unclear_risk", 0),
        "overall_high_or_unclear_ratio": _ratio(
            overall_counts.get("high_risk", 0) + overall_counts.get("unclear_risk", 0),
            total,
        ),
        "high_risk_study_ids": high_risk_study_ids[:30],
        "unclear_risk_study_ids": unclear_risk_study_ids[:30],
        "domain_counts": domain_rows,
    }


def _compact_analysis_context(analysis_setting: dict[str, Any]) -> dict[str, Any]:
    comparison = _dict_value(analysis_setting.get("comparison"))
    outcome = _dict_value(analysis_setting.get("outcome"))
    timepoint = _dict_value(analysis_setting.get("timepoint"))
    subgroup = _dict_value(analysis_setting.get("subgroup"))
    return {
        "analysis_name": analysis_setting.get("analysis_name"),
        "analysis_group_name": analysis_setting.get("analysis_group_name"),
        "comparison_text": comparison.get("text"),
        "outcome_label": outcome.get("label"),
        "outcome_measure": outcome.get("measure"),
        "benefit_direction": outcome.get("benefit_direction"),
        "timepoint_label": timepoint.get("label"),
        "subgroup_label": subgroup.get("level"),
        "data_type": analysis_setting.get("data_type"),
        "effect_measure": analysis_setting.get("effect_measure"),
        "eligible_study_ids": analysis_setting.get("eligible_study_ids") or [],
    }


def _compact_join_coverage(value: Any) -> dict[str, Any]:
    coverage = _dict_value(value)
    return {
        "requested_study_count": coverage.get("requested_study_count"),
        "matched_risk_of_bias_count": coverage.get("matched_risk_of_bias_count"),
        "missing_risk_of_bias_count": coverage.get("missing_risk_of_bias_count"),
        "match_method_counts": coverage.get("match_method_counts") or {},
    }


def _normalize_judgement(parsed: dict[str, Any]) -> dict[str, Any]:
    downgraded = _normalize_text(parsed.get("downgraded"))
    severity = _normalize_text(parsed.get("severity"))
    if downgraded not in ALLOWED_DOWNGRADED:
        downgraded = "unclear"
    if severity not in ALLOWED_SEVERITY:
        severity = "unclear"
    levels = _normalize_levels(parsed.get("levels"), downgraded=downgraded, severity=severity)
    level_evaluable = parsed.get("level_evaluable")
    if not isinstance(level_evaluable, bool):
        level_evaluable = severity != "unclear" and levels != "unclear"
    if severity == "none":
        downgraded = "no"
        levels = 0
        level_evaluable = True
    elif severity in {"serious", "very_serious"}:
        downgraded = "yes"
        level_evaluable = True
    elif severity == "unclear":
        downgraded = "yes" if downgraded != "no" else "unclear"
        levels = "unclear"
        level_evaluable = False
    return judgement(
        DOMAIN,
        downgraded=downgraded,
        severity=severity,
        levels=levels,
        level_evaluable=level_evaluable,
        rationale=str(parsed.get("rationale") or parsed.get("reason") or "LLM judgement."),
    )


def _apply_sof_guardrails(judgement_payload: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("input_mode") != "sof_extraction_ablation":
        return judgement_payload
    lines = _sof_evidence_lines(payload)
    if not lines:
        return judgement_payload

    rationale = str(judgement_payload.get("rationale") or "")
    if any(_NEGATED_ROB_DOWNGRADE_RE.search(line) for line in lines):
        return _guarded_judgement("no", "none", 0, True, rationale, "SoF text says risk of bias did not cause downgrading.")

    has_rob_downgrade = any(
        _ROB_DOWNGRADE_RE.search(line) or _PUBLICATION_BIAS_DOWNGRADE_RE.search(line) or _ROB_LATER_ONE_LEVEL_RE.search(line)
        for line in lines
    )
    if not has_rob_downgrade and judgement_payload.get("severity") in {"serious", "very_serious", "unclear"}:
        return _guarded_judgement("no", "none", 0, True, rationale, "No explicit SoF risk-of-bias downgrade cue.")

    if not has_rob_downgrade:
        return judgement_payload

    joined = " | ".join(lines)
    if _ONE_EACH_ROB_RE.search(joined) and (
        judgement_payload.get("severity") != "serious" or judgement_payload.get("levels") != 1
    ):
        return _guarded_judgement("yes", "serious", 1, True, rationale, "Explicit one-each RoB downgrade.")

    if _is_ambiguous_rob_level(lines):
        return _guarded_judgement("yes", "unclear", "unclear", False, rationale, "SoF mentions RoB downgrading, but the RoB-specific level is ambiguous.")

    if _STUDY_DESIGN_REPORTING_RE.search(joined) and judgement_payload.get("severity") == "very_serious":
        return _guarded_judgement("yes", "serious", 1, True, rationale, "Study-design/reporting-bias wording maps to one RoB level in this benchmark.")

    one_level = _explicit_one_level(lines)
    if one_level is not None and (
        judgement_payload.get("severity") != "serious" or judgement_payload.get("levels") != one_level
    ):
        return _guarded_judgement("yes", "serious", one_level, True, rationale, "Explicit RoB-specific one-level downgrade.")
    if one_level is not None:
        return judgement_payload

    multi_level = _explicit_multi_level(lines)
    if multi_level is not None:
        level = multi_level
        if judgement_payload.get("severity") != "very_serious" or judgement_payload.get("levels") != level:
            return _guarded_judgement("yes", "very_serious", level, True, rationale, "Explicit multi-level RoB downgrade.")

    return judgement_payload


def _is_ambiguous_rob_level(lines: list[str]) -> bool:
    for line in lines:
        if _PUBLICATION_BIAS_DOWNGRADE_RE.search(line) and not _NEGATED_PUBLICATION_BIAS_DOWNGRADE_RE.search(line):
            return True
        if _BENCHMARK_UNCLEAR_ROB_LEVEL_RE.search(line):
            return True
        if _TOTAL_LEVEL_OTHER_BEFORE_ROB_RE.search(line) and not _ROB_LATER_ONE_LEVEL_RE.search(line):
            return True
        if _UNCERTAIN_RISK_RE.search(line):
            return True
        if _ROB_NOT_INFLUENCE_TOTAL_DOWNGRADE_RE.search(line):
            return True
        if _MULTI_CLAUSE_AMBIGUOUS_RE.search(line):
            return True
        if _NO_LEVEL_ROB_DOWNGRADE_RE.search(line):
            return True
        if (
            _COMBINED_DOMAIN_DOWNGRADE_RE.search(line)
            and not _CLEAR_ONE_LEVEL_RE.search(line)
            and not _CLEAR_MULTI_LEVEL_RE.search(line)
            and not _ROB_LATER_ONE_LEVEL_RE.search(line)
        ):
            return True
        if _ROB_DISTRIBUTION_THEN_DOWNGRADE_RE.search(line) and not (
            _CLEAR_ONE_LEVEL_RE.search(line) or _CLEAR_MULTI_LEVEL_RE.search(line)
        ):
            return True
    return False


def _explicit_one_level(lines: list[str]) -> int | None:
    for line in lines:
        if _ONE_EACH_ROB_RE.search(line):
            return 1
        if _ROB_LATER_ONE_LEVEL_RE.search(line):
            return 1
        if _CLEAR_ONE_LEVEL_RE.search(line) and not _PUBLICATION_BIAS_DOWNGRADE_RE.search(line):
            return 1
    return None


def _explicit_multi_level(lines: list[str]) -> int | None:
    for line in lines:
        match = _CLEAR_MULTI_LEVEL_RE.search(line)
        if match is None:
            continue
        matched_text = match.group(0)
        return 3 if _THREE_LEVEL_RE.search(matched_text) else 2
    return None


def _guarded_judgement(
    downgraded: str,
    severity: str,
    levels: int | str,
    level_evaluable: bool,
    rationale: str,
    guardrail: str,
) -> dict[str, Any]:
    if rationale:
        rationale = f"{rationale} Guardrail: {guardrail}"
    else:
        rationale = f"Guardrail: {guardrail}"
    return judgement(
        DOMAIN,
        downgraded=downgraded,
        severity=severity,
        levels=levels,
        level_evaluable=level_evaluable,
        rationale=rationale,
    )


def _sof_evidence_lines(payload: dict[str, Any]) -> list[str]:
    sof_context = _dict_value(payload.get("sof_context"))
    values: list[Any] = []
    values.extend(_list_value(sof_context.get("footnote_texts")))
    values.append(sof_context.get("comment_text"))
    values.append(sof_context.get("source_summary_of_findings_span_text"))
    return [_normalize_sof_text(value) for value in values if _normalize_sof_text(value)]


def _normalize_sof_text(value: Any) -> str:
    text = str(value or "")
    text = (
        text.replace("‐", "-")
        .replace("‑", "-")
        .replace("‒", "-")
        .replace("–", "-")
        .replace("—", "-")
    )
    return re.sub(r"\s+", " ", text).strip()


def _normalize_levels(value: Any, *, downgraded: str, severity: str) -> int | str:
    text = str(value).strip().lower()
    if text in {"unclear", "unknown", ""}:
        if severity == "none" or downgraded == "no":
            return 0
        if severity == "serious":
            return 1
        if severity == "very_serious":
            return 2
        return "unclear"
    try:
        return int(float(text))
    except ValueError:
        return "unclear"


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _retry_after_seconds(error: HTTPError) -> float | None:
    raw_value = error.headers.get("Retry-After")
    if raw_value is None:
        return None
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        return None


def _float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return float(raw_value)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def build_method() -> Method:
    return Method()
