"""Risk-of-bias domain objects."""

from __future__ import annotations

from dataclasses import dataclass, field

from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan


ROB1_DOMAINS = [
    "random_sequence_generation",
    "allocation_concealment",
    "blinding_participants_personnel",
    "blinding_outcome_assessment",
    "incomplete_outcome_data",
    "selective_reporting",
    "other_bias",
]

DEFAULT_ROB1_DOMAINS = list(ROB1_DOMAINS)

MAX_RISK_OF_BIAS_ITEMS_PER_RUN = 500


@dataclass(frozen=True)
class RiskOfBiasDomainConfig:
    assessed_domains: list[str] = field(
        default_factory=lambda: list(DEFAULT_ROB1_DOMAINS)
    )
    overall_key_domains: list[str] = field(
        default_factory=lambda: list(DEFAULT_ROB1_DOMAINS)
    )

    def __post_init__(self) -> None:
        _validate_domain_list(self.assessed_domains, "assessed_domains")
        _validate_domain_list(self.overall_key_domains, "overall_key_domains")
        assessed = set(self.assessed_domains)
        missing = [
            domain for domain in self.overall_key_domains if domain not in assessed
        ]
        if missing:
            raise ValueError(
                "overall_key_domains must be a subset of assessed_domains; "
                f"missing: {', '.join(missing)}"
            )


@dataclass(frozen=True)
class RoB1DomainJudgement:
    domain: str
    judgement: str
    rationale: str
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)


@dataclass(frozen=True)
class RoB1OverallJudgement:
    judgement: str
    rationale: str
    driving_domains: list[str] = field(default_factory=list)
    basis: str = "configured_key_domains"


@dataclass(frozen=True)
class RiskOfBiasAssessment:
    study_id: str
    domains: list[RoB1DomainJudgement] = field(default_factory=list)
    overall: RoB1OverallJudgement = field(
        default_factory=lambda: RoB1OverallJudgement(
            judgement="unclear_risk",
            rationale="Overall risk of bias was not computed.",
        )
    )
    assessed_domains: list[str] = field(default_factory=list)
    overall_key_domains: list[str] = field(default_factory=list)
    unassessed_domains: list[str] = field(default_factory=list)
    notes: str = ""


def summarize_rob1_overall(
    *,
    judgements: list[RoB1DomainJudgement],
    key_domains: list[str],
) -> RoB1OverallJudgement:
    by_domain = {item.domain: item for item in judgements}
    missing = [domain for domain in key_domains if domain not in by_domain]
    if missing:
        raise ValueError(
            "Cannot summarize overall risk of bias without all key domains; "
            f"missing: {', '.join(missing)}"
        )

    high = [
        domain
        for domain in key_domains
        if by_domain[domain].judgement == "high_risk"
    ]
    if high:
        return RoB1OverallJudgement(
            judgement="high_risk",
            rationale=(
                "High risk was identified in the configured key domain(s): "
                f"{', '.join(high)}."
            ),
            driving_domains=high,
        )

    unclear = [
        domain
        for domain in key_domains
        if by_domain[domain].judgement == "unclear_risk"
    ]
    if unclear:
        return RoB1OverallJudgement(
            judgement="unclear_risk",
            rationale=(
                "Unclear risk was identified in the configured key domain(s): "
                f"{', '.join(unclear)}; no configured key domain was high risk."
            ),
            driving_domains=unclear,
        )

    invalid = [
        domain
        for domain in key_domains
        if by_domain[domain].judgement != "low_risk"
    ]
    if invalid:
        raise ValueError(
            "Unsupported RoB 1 judgement for key domain(s): "
            f"{', '.join(invalid)}"
        )
    return RoB1OverallJudgement(
        judgement="low_risk",
        rationale="All configured key domains were judged at low risk of bias.",
    )


def _validate_domain_list(domains: list[str], field_name: str) -> None:
    if not domains:
        raise ValueError(f"{field_name} must not be empty")
    if len(set(domains)) != len(domains):
        raise ValueError(f"{field_name} must not contain duplicate domains")
    unknown = [domain for domain in domains if domain not in ROB1_DOMAINS]
    if unknown:
        raise ValueError(
            f"{field_name} contains unsupported RoB 1 domain(s): {', '.join(unknown)}"
        )
