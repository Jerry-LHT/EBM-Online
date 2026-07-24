from __future__ import annotations

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.study_pio.extraction_study_pico_slotwise_llm.parsing import (
    parse_interventions,
    parse_outcomes,
    parse_warnings,
    validate_stage_payload,
)


def test_parser_rejects_string_timepoints_instead_of_splitting_characters() -> None:
    with pytest.raises(ValueError, match="timepoints must be an array"):
        parse_outcomes(
            {
                "outcomes": [
                    {
                        "outcome_label": "Mortality",
                        "measurement": "All-cause mortality",
                        "timepoints": "12 weeks",
                    }
                ]
            }
        )


def test_parser_rejects_string_warnings() -> None:
    with pytest.raises(ValueError, match="warnings must be an array"):
        parse_warnings({"warnings": "missing evidence"})


def test_parser_rejects_missing_arm_description_and_extra_stage_fields() -> None:
    with pytest.raises(ValueError, match="invalid fields"):
        parse_interventions({"interventions": [{"label": "Drug"}]})

    with pytest.raises(ValueError, match="extra=.*unexpected"):
        validate_stage_payload(
            stage="intervention_comparator",
            payload={
                "interventions": [],
                "comparators": [],
                "warnings": [],
                "unexpected": True,
            },
        )
