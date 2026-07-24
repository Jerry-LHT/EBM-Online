"""Deterministic risk-of-bias GRADE domain method."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_deterministic.utils import as_list, norm_text, not_serious, serious, unclear


DOMAIN = "risk_of_bias"


class Method:
    domain = DOMAIN

    def run(self, *, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
        return predict(domain_evidence=domain_evidence, evidence_body=evidence_body)


def predict(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    assessments = as_list(domain_evidence.get("risk_of_bias_assessments"))
    missing = as_list(domain_evidence.get("risk_of_bias_missing_study_ids"))
    if not assessments:
        if missing:
            return unclear(DOMAIN, "Risk-of-bias assessments are missing for contributing studies.")
        return not_serious(DOMAIN, "No study-level risk-of-bias concerns were provided.")

    high = 0
    unclear_count = 0
    total = 0
    high_domains = 0
    for assessment in assessments:
        if not isinstance(assessment, dict):
            continue
        overall_value = assessment.get("overall")
        if isinstance(overall_value, dict):
            overall_value = overall_value.get("judgement")
        overall = norm_text(overall_value)
        domains = as_list(assessment.get("domains"))
        domain_judgements = [norm_text(domain.get("judgement")) for domain in domains if isinstance(domain, dict)]
        total += 1
        if overall == "high_risk" or "high_risk" in domain_judgements:
            high += 1
        elif overall == "unclear_risk" or "unclear_risk" in domain_judgements:
            unclear_count += 1
        high_domains += sum(1 for judgement in domain_judgements if judgement == "high_risk")

    if high and (high / max(total, 1) >= 0.5 or high_domains >= 2):
        return serious(DOMAIN, "Multiple contributing studies or domains have high risk of bias.")
    if high:
        return serious(DOMAIN, "At least one contributing study has high risk of bias.")
    if unclear_count or missing:
        return unclear(DOMAIN, "Risk-of-bias evidence is incomplete or unclear for contributing studies.")
    return not_serious(DOMAIN, "Available study-level risk-of-bias assessments do not show important concerns.")


def build_method() -> Method:
    return Method()
