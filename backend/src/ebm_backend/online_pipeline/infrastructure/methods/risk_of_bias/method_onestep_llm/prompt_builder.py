"""Prompt loading for the one-step RoB method."""

from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
DOMAIN_LABELS = {
    "random_sequence_generation": "Random sequence generation (selection bias)",
    "allocation_concealment": "Allocation concealment (selection bias)",
    "blinding_participants_personnel": "Blinding of participants and personnel (performance bias)",
    "blinding_outcome_assessment": "Blinding of outcome assessment (detection bias)",
    "incomplete_outcome_data": "Incomplete outcome data (attrition bias)",
    "selective_reporting": "Selective reporting (reporting bias)",
    "other_bias": "Other bias",
}


def build_system_prompt(domain_id: str) -> str:
    template = (PROMPT_DIR / "system_prompt.txt").read_text(encoding="utf-8").rstrip("\n")
    criteria = (PROMPT_DIR / f"{domain_id}.txt").read_text(encoding="utf-8").strip()
    return template.replace("__DOMAIN_LABEL__", DOMAIN_LABELS[domain_id]).replace("__CRITERIA__", criteria)
