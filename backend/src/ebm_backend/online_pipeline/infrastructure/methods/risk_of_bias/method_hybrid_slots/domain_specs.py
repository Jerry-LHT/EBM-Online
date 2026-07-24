"""Domain-to-prompt mapping for the hybrid-slots RoB method."""

from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.domain.risk_of_bias import ROB1_DOMAINS


DOMAIN_LABELS = {
    "random_sequence_generation": "Random sequence generation (selection bias)",
    "allocation_concealment": "Allocation concealment (selection bias)",
    "blinding_participants_personnel": "Blinding of participants and personnel (performance bias)",
    "blinding_outcome_assessment": "Blinding of outcome assessment (detection bias)",
    "incomplete_outcome_data": "Incomplete outcome data (attrition bias)",
    "selective_reporting": "Selective reporting (reporting bias)",
    "other_bias": "Other bias",
}
CALIBRATED_DOMAINS = {"blinding_participants_personnel", "blinding_outcome_assessment", "other_bias"}
LLM_DOMAINS = list(ROB1_DOMAINS)


@dataclass(frozen=True)
class DomainSpec:
    slot_id: str
    domain_label: str
    prompt_file: str
    calibrated: bool


SPECS_BY_ID = {
    domain_id: DomainSpec(
        slot_id=domain_id,
        domain_label=DOMAIN_LABELS[domain_id],
        prompt_file=f"{domain_id}.txt",
        calibrated=domain_id in CALIBRATED_DOMAINS,
    )
    for domain_id in ROB1_DOMAINS
}
