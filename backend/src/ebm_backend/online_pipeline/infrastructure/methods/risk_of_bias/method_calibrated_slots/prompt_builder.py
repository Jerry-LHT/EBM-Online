"""Prompt loading for the calibrated-slots RoB method."""

from pathlib import Path

from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_calibrated_slots.domain_specs import DomainSpec


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def build_system_prompt(spec: DomainSpec) -> str:
    template = (PROMPT_DIR / "system_prompt.txt").read_text(encoding="utf-8").rstrip("\n")
    criteria = (PROMPT_DIR / spec.prompt_file).read_text(encoding="utf-8")
    return template.replace("__DOMAIN_LABEL__", spec.domain_label).replace("__CRITERIA__", criteria)
