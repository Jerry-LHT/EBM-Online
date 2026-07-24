from __future__ import annotations

from pathlib import Path

import pytest

from ebm_backend.online_pipeline.domain.risk_of_bias import ROB1_DOMAINS
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_calibrated_slots.domain_specs import (
    SPECS_BY_ID as CALIBRATED_SPECS,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_calibrated_slots.prompt_builder import (
    build_system_prompt as build_calibrated_prompt,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_hybrid_slots.domain_specs import (
    CALIBRATED_DOMAINS,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_hybrid_slots.prompt_builder import (
    build_system_prompt as build_hybrid_prompt,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.prompt_builder import (
    build_system_prompt as build_onestep_prompt,
)


@pytest.mark.parametrize("domain_id", ROB1_DOMAINS)
def test_hybrid_prompt_preserves_its_original_prompt_selection(domain_id: str) -> None:
    expected = (
        build_calibrated_prompt(CALIBRATED_SPECS[domain_id])
        if domain_id in CALIBRATED_DOMAINS
        else build_onestep_prompt(domain_id)
    )

    assert build_hybrid_prompt(domain_id) == expected


def test_concrete_method_packages_do_not_import_each_other() -> None:
    methods_root = (
        Path(__file__).parents[3]
        / "backend/src/ebm_backend/online_pipeline/infrastructure/methods/risk_of_bias"
    )
    package_names = ("method_onestep_llm", "method_calibrated_slots", "method_hybrid_slots")

    for package_name in package_names:
        package_root = methods_root / package_name
        source = "\n".join(path.read_text(encoding="utf-8") for path in package_root.rglob("*.py"))
        for other_package_name in package_names:
            if other_package_name != package_name:
                assert f"risk_of_bias.{other_package_name}" not in source
