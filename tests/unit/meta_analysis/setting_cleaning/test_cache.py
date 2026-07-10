from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.online_pipeline.meta_analysis import builder as meta_builder
from benchmark.online_pipeline.meta_analysis.setting_cleaning.cache import (
    COMPARISON_CACHE_VERSION,
    SETTING_CLEANING_VERSION,
    comparison_cache_cleaning_metadata,
    comparison_cache_key,
    comparison_cache_metadata,
    is_valid_comparison_cache_row,
    setting_has_valid_comparison_cache,
)


def _candidate(*, analysis_name: str) -> dict:
    return {
        "candidate_id": f"candidate::CD001431::11::{analysis_name}",
        "review_id": "CD001431",
        "analysis_group": "11",
        "analysis_number": analysis_name,
        "analysis_name": analysis_name,
        "analysis_group_name": "Choice",
        "explicit_labels": {
            "experimental_group_label": None,
            "control_group_label": None,
        },
    }


def _family(candidate: dict) -> dict:
    return {
        "candidate_id": candidate["candidate_id"],
        "setting_family_id": candidate["candidate_id"].replace("candidate::", "setting-family::"),
        "review_id": candidate["review_id"],
        "analysis_group": candidate["analysis_group"],
        "analysis_number": candidate["analysis_number"],
        "analysis_name": candidate["analysis_name"],
        "analysis_group_name": candidate["analysis_group_name"],
        "explicit_labels": candidate["explicit_labels"],
        "method_source": {},
        "study_row_source": {},
    }


def test_comparison_v2_key_includes_analysis_name():
    first = _candidate(analysis_name="Choice: surgery over conservative option")
    second = _candidate(analysis_name="Choice for screening")

    assert comparison_cache_key(first).startswith(f"{COMPARISON_CACHE_VERSION}::")
    assert comparison_cache_key(first) != comparison_cache_key(second)


def test_old_comparison_cache_row_is_rejected():
    candidate = _candidate(analysis_name="Choice for screening")
    old_row = {
        "candidate_id": candidate["candidate_id"],
        "cache_key": "comparison::abc123",
        "comparison": {"experimental": "surgery", "comparator": "conservative option"},
    }

    assert not is_valid_comparison_cache_row(old_row, candidate)


def test_source_hash_mismatch_is_rejected():
    candidate = _candidate(analysis_name="Choice for screening")
    metadata = comparison_cache_metadata(candidate)
    row = {
        "candidate_id": candidate["candidate_id"],
        "cache_key": metadata["cache_key"],
        "cache_version": metadata["cache_version"],
        "prompt_version": metadata["prompt_version"],
        "source_hash": "wrong",
    }

    assert not is_valid_comparison_cache_row(row, candidate)


def test_setting_validity_requires_v2_metadata():
    candidate = _candidate(analysis_name="Choice for screening")
    setting = {
        "candidate_id": candidate["candidate_id"],
        "cleaning": {
            "method": "llm_direct_fields_v1",
            **comparison_cache_cleaning_metadata(candidate),
        },
    }

    assert setting_has_valid_comparison_cache(setting, candidate)

    legacy_setting = {
        "candidate_id": candidate["candidate_id"],
        "cleaning": {
            "method": "llm_direct_fields_v1",
            "field_cache_keys": {"comparison": "comparison::abc123"},
        },
    }
    assert not setting_has_valid_comparison_cache(legacy_setting, candidate)


def test_meta_builder_rejects_legacy_setting_cleaning():
    candidate = _candidate(analysis_name="Choice for screening")
    family = _family(candidate)
    setting = {
        **family,
        "cleaning": {
            "method": "llm_direct_fields_v1",
            "field_cache_keys": {"comparison": "comparison::abc123"},
        },
    }

    with pytest.raises(ValueError, match=SETTING_CLEANING_VERSION):
        meta_builder._validate_setting_families(  # noqa: SLF001
            setting_families=[setting],
            families=[family],
            source_path=Path("setting_cleaned.jsonl"),
        )
