"""Bounded working-decision state for the source-workspace agent."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any, Iterable


EVIDENCE_NEED_STATUSES = {"pending", "resolved", "blocked", "superseded"}


def register_evidence_needs(
    notebook: dict[str, Any],
    *,
    needs: Iterable[Any],
    source_ref: str,
) -> None:
    """Register source-local needs without reopening completed work."""

    registry = notebook.setdefault("evidence_need_registry", [])
    by_id = {
        str(row.get("need_id") or ""): row
        for row in registry
        if isinstance(row, dict) and row.get("need_id")
    }
    for raw in needs:
        text = " ".join(str(raw or "").split())
        if not text:
            continue
        need_id = evidence_need_id(text)
        existing = by_id.get(need_id)
        if existing is None:
            existing = {
                "need_id": need_id,
                "text": text,
                "status": "pending",
                "source_refs": [],
                "resolution_source_refs": [],
                "resolution_reason": None,
            }
            registry.append(existing)
            by_id[need_id] = existing
        if source_ref and source_ref not in existing["source_refs"]:
            existing["source_refs"].append(source_ref)
    _sync_legacy_needs(notebook)


def active_evidence_needs(notebook: dict[str, Any]) -> list[dict[str, Any]]:
    _ensure_registry(notebook)
    return [
        deepcopy(row)
        for row in notebook.get("evidence_need_registry") or []
        if isinstance(row, dict) and row.get("status") == "pending"
    ]


def normalize_evidence_need_updates(
    value: Any,
    *,
    known_need_ids: set[str],
    allowed_source_refs: set[str],
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("evidence_need_updates must be a list of objects")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        need_id = str(raw.get("need_id") or "").strip()
        if need_id not in known_need_ids:
            raise ValueError(f"Unknown evidence need id: {need_id}")
        if need_id in seen:
            raise ValueError(f"Duplicate evidence need update: {need_id}")
        seen.add(need_id)
        status = str(raw.get("status") or "").strip()
        if status not in EVIDENCE_NEED_STATUSES - {"pending"}:
            raise ValueError(f"Unsupported evidence need status: {status}")
        source_refs = _unique_text(raw.get("source_refs"))
        invalid_refs = [ref for ref in source_refs if ref not in allowed_source_refs]
        if invalid_refs:
            raise ValueError(
                f"Evidence need update references unread evidence: {invalid_refs}"
            )
        reason = " ".join(str(raw.get("reason") or "").split())
        if not reason:
            raise ValueError("Evidence need update requires a reason")
        if status == "resolved" and not source_refs:
            raise ValueError("A resolved evidence need requires at least one evidence source")
        result.append(
            {
                "need_id": need_id,
                "status": status,
                "source_refs": source_refs,
                "reason": reason,
            }
        )
    return result


def apply_evidence_need_updates(
    notebook: dict[str, Any],
    *,
    updates: list[dict[str, Any]],
) -> None:
    _ensure_registry(notebook)
    by_id = {
        str(row["need_id"]): row
        for row in notebook.get("evidence_need_registry") or []
        if isinstance(row, dict) and row.get("need_id")
    }
    for update in updates:
        row = by_id[str(update["need_id"])]
        row["status"] = str(update["status"])
        row["resolution_source_refs"] = list(update.get("source_refs") or [])
        row["resolution_reason"] = str(update.get("reason") or "") or None
    _sync_legacy_needs(notebook)


def working_state_snapshot(notebook: dict[str, Any]) -> dict[str, Any]:
    _ensure_registry(notebook)
    return {
        "evidence_needs": deepcopy(notebook.get("evidence_need_registry") or []),
        "open_questions": list(notebook.get("open_questions") or []),
        "claims": deepcopy(notebook.get("claims") or []),
        "alternatives": deepcopy(notebook.get("alternatives") or []),
    }


def evidence_need_id(text: str) -> str:
    normalized = " ".join(str(text or "").casefold().split())
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"need::{digest}"


def _ensure_registry(notebook: dict[str, Any]) -> None:
    if "evidence_need_registry" in notebook:
        return
    notebook["evidence_need_registry"] = []
    for text in notebook.get("evidence_needs") or []:
        register_evidence_needs(notebook, needs=[text], source_ref="")


def _sync_legacy_needs(notebook: dict[str, Any]) -> None:
    notebook["evidence_needs"] = [
        str(row.get("text") or "")
        for row in notebook.get("evidence_need_registry") or []
        if isinstance(row, dict)
        and row.get("status") == "pending"
        and str(row.get("text") or "").strip()
    ]


def _unique_text(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for raw in value:
        text = str(raw or "").strip()
        if text and text not in result:
            result.append(text)
    return result
