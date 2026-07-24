"""Domain-to-prompt mapping for the calibrated-slots RoB method."""

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


@dataclass(frozen=True)
class DomainSpec:
    slot_id: str
    domain_label: str
    prompt_file: str


SPECS = [DomainSpec(domain_id, DOMAIN_LABELS[domain_id], f"{domain_id}.txt") for domain_id in ROB1_DOMAINS]
SPECS_BY_ID = {spec.slot_id: spec for spec in SPECS}
LLM_DOMAINS = [domain_id for domain_id in ROB1_DOMAINS if domain_id in SPECS_BY_ID]
