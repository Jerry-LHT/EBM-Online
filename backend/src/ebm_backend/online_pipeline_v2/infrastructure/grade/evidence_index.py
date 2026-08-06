"""Read deterministic GRADE-to-Synthesis relationship facts from a package."""

from __future__ import annotations

import json
from pathlib import Path


def synthesis_analysis_ids(package_directory: Path) -> frozenset[str]:
    """Return identities represented by the semantic Synthesis document.

    Analysis-level totals are deliberately not treated as SoF-row invariants:
    a valid evidence body may use a subgroup, alternative synthesis, or more
    than one Analysis. Exact count validation requires an exact estimate-level
    binding rather than an engineering guess.
    """

    value = json.loads((package_directory / "synthesis.json").read_text("utf-8"))
    analyses = value.get("analyses") if isinstance(value, dict) else None
    if not isinstance(analyses, list):
        raise ValueError("GRADE synthesis.json requires an analyses array")
    result: set[str] = set()
    for analysis in analyses:
        if not isinstance(analysis, dict):
            raise ValueError("GRADE Synthesis Analysis must be an object")
        analysis_id = _text(analysis.get("analysis_id"), "analysis_id")
        if analysis_id in result:
            raise ValueError("GRADE Synthesis Analysis ids must be unique")
        result.add(analysis_id)
    return frozenset(result)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"GRADE Synthesis {label} must contain text")
    return value.strip()
