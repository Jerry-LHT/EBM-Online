"""Threshold evidence registry for GRADE imprecision."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol


CACHEABLE_EVIDENCE_GRADES = {"source_backed_direct", "source_backed_derived"}


class ThresholdEvidenceRegistry(Protocol):
    def get(self, key: str) -> dict[str, Any] | None:
        """Return a cached threshold for a research key, if available."""

    def put(self, key: str, threshold: dict[str, Any]) -> bool:
        """Store a threshold if it is cache eligible; return whether it was stored."""


class InMemoryThresholdEvidenceRegistry:
    """Process-local threshold registry for validated source-backed thresholds."""

    def __init__(self, initial: dict[str, dict[str, Any]] | None = None) -> None:
        self._items = {str(key): deepcopy(value) for key, value in (initial or {}).items()}

    def get(self, key: str) -> dict[str, Any] | None:
        value = self._items.get(str(key))
        if value is None:
            return None
        result = deepcopy(value)
        result["registry_hit"] = True
        result["registry_key"] = str(key)
        return result

    def put(self, key: str, threshold: dict[str, Any]) -> bool:
        if not is_registry_cacheable(threshold):
            return False
        value = deepcopy(threshold)
        value["registry_hit"] = False
        value["registry_key"] = str(key)
        self._items[str(key)] = value
        return True

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self._items)


class NullThresholdEvidenceRegistry:
    """Registry implementation that never reads or writes."""

    def get(self, key: str) -> dict[str, Any] | None:
        return None

    def put(self, key: str, threshold: dict[str, Any]) -> bool:
        return False


def is_registry_cacheable(threshold: dict[str, Any]) -> bool:
    if not bool(threshold.get("cache_eligible")):
        return False
    if not bool(threshold.get("threshold_found")):
        return False
    if threshold.get("threshold_source_type") != "source_backed":
        return False
    if str(threshold.get("threshold_evidence_grade") or "") not in CACHEABLE_EVIDENCE_GRADES:
        return False
    if not threshold.get("source_urls"):
        return False
    if threshold.get("threshold_valid") is False:
        return False
    return True
