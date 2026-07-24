"""Method-local prompt loading for the hybrid RoB method."""

from pathlib import Path

from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_hybrid_slots.domain_specs import SPECS_BY_ID


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def build_system_prompt(domain_id: str) -> str:
    spec = SPECS_BY_ID[domain_id]
    template_name = "system_prompt_calibrated.txt" if spec.calibrated else "system_prompt_current.txt"
    template = (PROMPT_DIR / template_name).read_text(encoding="utf-8").rstrip("\n")
    criteria_path = PROMPT_DIR / spec.prompt_file
    criteria = criteria_path.read_text(encoding="utf-8")
    if not spec.calibrated:
        criteria = criteria.strip()
    return template.replace("__DOMAIN_LABEL__", spec.domain_label).replace("__CRITERIA__", criteria)
