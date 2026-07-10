"""Source-signal cache derived from discovery outputs."""

from __future__ import annotations

from typing import Any


def build_source_signal_cache(source_outputs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    for output in source_outputs:
        source_id = str(output.get("source_id") or "")
        if not source_id:
            continue
        candidates = [item for item in (output.get("candidates") or []) if isinstance(item, dict)]
        best_status = _best_status([str(item.get("match_status") or "") for item in candidates])
        cache[source_id] = {
            "source_id": source_id,
            "source_type": output.get("source_type"),
            "brief_summary": output.get("brief_summary"),
            "warnings": output.get("warnings") or [],
            "candidate_count": len(candidates),
            "best_match_status": best_status,
            "candidate_data_types": sorted(
                {
                    str(item.get("candidate_data_type") or "").strip()
                    for item in candidates
                    if str(item.get("candidate_data_type") or "").strip()
                }
            ),
            "setting_signals": [
                item.get("study_result_setting") if isinstance(item.get("study_result_setting"), dict) else {}
                for item in candidates
            ],
        }
    return cache


def score_candidate_for_completion(
    *,
    candidate: dict[str, Any],
    signal_cache: dict[str, dict[str, Any]],
) -> float:
    score = 0.0
    status = str(candidate.get("match_status") or "").strip().lower()
    if status == "matched":
        score += 4.0
    elif status == "possible":
        score += 2.0

    confidence = str(candidate.get("confidence") or "").strip().lower()
    if confidence == "high":
        score += 1.5
    elif confidence == "medium":
        score += 0.75

    candidate_setting = candidate.get("study_result_setting") if isinstance(candidate.get("study_result_setting"), dict) else {}
    source_ids = [str(value or "") for value in (candidate.get("source_ids") or []) if str(value or "")]
    if not source_ids and candidate.get("source_id"):
        source_ids = [str(candidate.get("source_id") or "")]
    for source_id in source_ids:
        signal = signal_cache.get(source_id) or {}
        if str(signal.get("source_type") or "") == "table":
            score += 1.0
        elif str(signal.get("source_type") or "") == "text":
            score += 0.25
        if str(signal.get("best_match_status") or "") == "matched":
            score += 0.5
        for source_setting in signal.get("setting_signals") or []:
            if isinstance(source_setting, dict):
                score += _semantic_overlap(candidate_setting=candidate_setting, source_setting=source_setting)
    return score


def select_candidates_for_completion(
    *,
    candidates: list[dict[str, Any]],
    signal_cache: dict[str, dict[str, Any]],
    matched_limit: int | None = None,
    possible_limit: int = 2,
    fallback_limit: int = 3,
) -> list[dict[str, Any]]:
    matched = [candidate for candidate in candidates if str(candidate.get("match_status") or "").strip().lower() == "matched"]
    possible = [candidate for candidate in candidates if str(candidate.get("match_status") or "").strip().lower() == "possible"]
    if matched_limit is not None and matched_limit >= 0:
        matched = _ranked_candidates(matched, signal_cache)[:matched_limit]
    ranked_possible = _ranked_candidates(possible, signal_cache)
    if matched:
        selected_possible = ranked_possible[:possible_limit]
    else:
        selected_possible = ranked_possible[:fallback_limit]
    selected = matched + selected_possible
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for candidate in selected:
        candidate_id = str(candidate.get("candidate_id") or "")
        if candidate_id and candidate_id in seen:
            continue
        if candidate_id:
            seen.add(candidate_id)
        ordered.append(candidate)
    return ordered


def _ranked_candidates(candidates: list[dict[str, Any]], signal_cache: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [
        (score_candidate_for_completion(candidate=candidate, signal_cache=signal_cache), index, candidate)
        for index, candidate in enumerate(candidates)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _, _, candidate in scored]


def _best_status(statuses: list[str]) -> str:
    priority = {"matched": 3, "possible": 2, "related": 1, "rejected": 0}
    best = "rejected"
    best_score = -1
    for status in statuses:
        normalized = str(status or "").strip().lower()
        score = priority.get(normalized, -1)
        if score > best_score:
            best = normalized or "rejected"
            best_score = score
    return best


def _semantic_overlap(*, candidate_setting: dict[str, Any], source_setting: dict[str, Any]) -> float:
    score = 0.0
    for key in ("outcome_label", "outcome_measure", "timepoint", "population_or_subgroup", "experimental_arm_label", "control_arm_label"):
        left = str(candidate_setting.get(key) or "").strip().lower()
        right = str(source_setting.get(key) or "").strip().lower()
        if not left or not right:
            continue
        if left == right:
            score += 0.5
        elif left in right or right in left:
            score += 0.25
    return score
