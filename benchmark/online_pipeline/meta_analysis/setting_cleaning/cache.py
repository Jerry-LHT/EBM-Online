"""Cache identity helpers for meta-analysis setting cleaning."""

from __future__ import annotations

from typing import Any

from benchmark.online_pipeline.shared.building import sha256_json


COMPARISON_CACHE_VERSION = "comparison_v2"
COMPARISON_PROMPT_VERSION = "comparison_extraction_v1"
SETTING_CLEANING_VERSION = "setting_cleaning_v2"
_KEY_DIGEST_LENGTH = 32


def comparison_cache_input(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical prompt input used for comparison-cache identity."""

    explicit = candidate.get("explicit_labels") if isinstance(candidate.get("explicit_labels"), dict) else {}
    return {
        "candidate_id": _clean_identifier(candidate.get("candidate_id")),
        "review_id": _clean_identifier(candidate.get("review_id")),
        "analysis_group": _clean_identifier(candidate.get("analysis_group")),
        "analysis_number": _clean_identifier(candidate.get("analysis_number")),
        "analysis_name": _clean_text(candidate.get("analysis_name")),
        "analysis_group_name": _clean_text(candidate.get("analysis_group_name")),
        "explicit_labels": {
            "experimental_group_label": _clean_text(explicit.get("experimental_group_label")),
            "control_group_label": _clean_text(explicit.get("control_group_label")),
        },
    }


def comparison_cache_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    cache_input = comparison_cache_input(candidate)
    source_hash = sha256_json(cache_input)
    digest = sha256_json(
        {
            "cache_version": COMPARISON_CACHE_VERSION,
            "prompt_version": COMPARISON_PROMPT_VERSION,
            "source_hash": source_hash,
            "cache_input": cache_input,
        }
    )
    return {
        "cache_key": f"{COMPARISON_CACHE_VERSION}::{digest[:_KEY_DIGEST_LENGTH]}",
        "cache_version": COMPARISON_CACHE_VERSION,
        "prompt_version": COMPARISON_PROMPT_VERSION,
        "source_hash": source_hash,
        "cache_input": cache_input,
    }


def comparison_cache_key(candidate: dict[str, Any]) -> str:
    return str(comparison_cache_metadata(candidate)["cache_key"])


def comparison_cache_row(candidate: dict[str, Any], extraction: dict[str, Any]) -> dict[str, Any]:
    metadata = comparison_cache_metadata(candidate)
    return {
        **extraction,
        **metadata,
        "candidate_id": candidate.get("candidate_id"),
    }


def is_valid_comparison_cache_row(row: dict[str, Any], candidate: dict[str, Any] | None = None) -> bool:
    if not isinstance(row, dict):
        return False
    cache_key = str(row.get("cache_key") or "")
    if not cache_key.startswith(f"{COMPARISON_CACHE_VERSION}::"):
        return False
    if row.get("cache_version") != COMPARISON_CACHE_VERSION:
        return False
    if row.get("prompt_version") != COMPARISON_PROMPT_VERSION:
        return False
    if not row.get("source_hash"):
        return False
    if candidate is None:
        return True
    expected = comparison_cache_metadata(candidate)
    return (
        cache_key == expected["cache_key"]
        and row.get("source_hash") == expected["source_hash"]
    )


def setting_has_valid_comparison_cache(setting: dict[str, Any], candidate: dict[str, Any]) -> bool:
    cleaning = setting.get("cleaning") if isinstance(setting.get("cleaning"), dict) else {}
    cache_key = ((cleaning.get("field_cache_keys") or {}).get("comparison"))
    source_hash = ((cleaning.get("field_cache_source_hashes") or {}).get("comparison"))
    expected = comparison_cache_metadata(candidate)
    return (
        cleaning.get("cleaning_version") == SETTING_CLEANING_VERSION
        and cache_key == expected["cache_key"]
        and source_hash == expected["source_hash"]
    )


def comparison_cache_cleaning_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = comparison_cache_metadata(candidate)
    return {
        "field_cache_keys": {"comparison": metadata["cache_key"]},
        "field_cache_source_hashes": {"comparison": metadata["source_hash"]},
        "field_prompt_versions": {"comparison": COMPARISON_PROMPT_VERSION},
        "cleaning_version": SETTING_CLEANING_VERSION,
    }


def _clean_identifier(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None
