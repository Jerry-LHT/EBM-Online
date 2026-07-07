"""LLM and normalized judges for Study PIO evaluation."""

from __future__ import annotations

import concurrent.futures
import json
import re
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm import call_llm_json
from benchmark.online_pipeline.q2pico.evaluation.judge import load_llm_config
from benchmark.online_pipeline.shared.jsonl import append_jsonl, read_jsonl, write_jsonl
from benchmark.online_pipeline.shared.prompts import render_prompt_template


FIELDS = ("population", "intervention_comparator", "outcomes")
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
JUDGE_PROMPT = PROMPT_DIR / "judge_claim_match_v1.txt"


def judge_predictions(
    *,
    instances: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    gold_by_id: dict[str, dict[str, Any]],
    judge_mode: str,
    llm_config: str | Path,
    output_path: str | Path | None = None,
    failure_output_path: str | Path | None = None,
    resume: bool = False,
    workers: int = 1,
) -> list[dict[str, Any]]:
    if judge_mode == "normalized":
        rows = normalized_claim_judge(instances=instances, predictions=predictions, gold_by_id=gold_by_id)
        if output_path is not None:
            write_jsonl(output_path, rows)
        return rows
    if judge_mode == "llm":
        return llm_claim_judge(
            instances=instances,
            predictions=predictions,
            gold_by_id=gold_by_id,
            llm_config=llm_config,
            output_path=output_path,
            failure_output_path=failure_output_path,
            resume=resume,
            workers=workers,
        )
    raise ValueError("judge_mode must be 'llm' or 'normalized'")


def normalized_claim_judge(
    *,
    instances: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    gold_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    predictions_by_id = {str(row["instance_id"]): row for row in predictions}
    rows: list[dict[str, Any]] = []
    for instance in instances:
        instance_id = str(instance["instance_id"])
        prediction = predictions_by_id[instance_id]
        gold = gold_by_id[instance_id]
        for field in FIELDS:
            gold_text = str(gold.get(field) or "")
            predicted_text = str(prediction.get(field) or "")
            matched = _normalize(gold_text) == _normalize(predicted_text)
            rows.append(
                {
                    "instance_id": instance_id,
                    "study_id": str(gold.get("study_id") or ""),
                    "field": field,
                    "gold_claims": [gold_text] if gold_text else [],
                    "predicted_claims": [predicted_text] if predicted_text else [],
                    "matches": [{"gold_index": 0, "predicted_index": 0, "rationale": "Normalized exact match."}] if matched and gold_text else [],
                    "unmatched_gold_indices": [] if matched or not gold_text else [0],
                    "unmatched_predicted_indices": [] if matched or not predicted_text else [0],
                    "judge_mode": "normalized",
                }
            )
    return rows


def llm_claim_judge(
    *,
    instances: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    gold_by_id: dict[str, dict[str, Any]],
    llm_config: str | Path,
    output_path: str | Path | None = None,
    failure_output_path: str | Path | None = None,
    resume: bool = False,
    workers: int = 1,
) -> list[dict[str, Any]]:
    config = load_llm_config(llm_config)
    if workers <= 0:
        raise ValueError("workers must be positive")
    predictions_by_id = {str(row["instance_id"]): row for row in predictions}
    existing_rows = _completed_resume_rows(output_path) if resume and output_path is not None else []
    completed_fields = _completed_fields(existing_rows)
    if output_path is not None:
        write_jsonl(output_path, existing_rows)
    rows = list(existing_rows)

    tasks: list[tuple[dict[str, Any], str]] = []
    for instance in instances:
        instance_id = str(instance["instance_id"])
        for field in FIELDS:
            if field not in completed_fields.get(instance_id, set()):
                tasks.append((instance, field))

    def judge_one_field(instance: dict[str, Any], field: str) -> dict[str, Any]:
        instance_id = str(instance["instance_id"])
        prediction = predictions_by_id[instance_id]
        gold = gold_by_id[instance_id]
        prompt = _build_field_prompt(instance=instance, gold=gold, prediction=prediction, field=field)
        parsed = _call_llm_json(config=config, prompt=prompt)
        return _coerce_field_row(instance_id=instance_id, parsed=parsed, gold=gold, prediction=prediction, field=field)

    max_workers = min(workers, max(1, len(tasks)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(judge_one_field, instance, field): (str(instance["instance_id"]), field)
            for instance, field in tasks
        }
        for future in concurrent.futures.as_completed(future_to_task):
            instance_id, field = future_to_task[future]
            try:
                row = future.result()
            except Exception as exc:
                if failure_output_path is not None:
                    append_jsonl(
                        failure_output_path,
                        [
                            {
                                "instance_id": instance_id,
                                "field": field,
                                "error_type": type(exc).__name__,
                                "message": str(exc),
                                "judge_mode": "llm",
                            }
                        ],
                    )
                continue
            rows.append(row)
            if output_path is not None:
                append_jsonl(output_path, [row])
    return rows


def _completed_resume_rows(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    resolved = Path(path)
    if not resolved.exists():
        return []
    rows = read_jsonl(resolved)
    seen: set[tuple[str, str]] = set()
    completed_rows: list[dict[str, Any]] = []
    for row in rows:
        instance_id = str(row.get("instance_id") or "")
        field = str(row.get("field") or "")
        key = (instance_id, field)
        if instance_id and field in FIELDS and key not in seen:
            completed_rows.append(row)
            seen.add(key)
    return completed_rows


def _complete_instance_ids(rows: list[dict[str, Any]]) -> set[str]:
    fields_by_instance: dict[str, set[str]] = {}
    for row in rows:
        instance_id = str(row.get("instance_id") or "")
        field = str(row.get("field") or "")
        if instance_id and field in FIELDS:
            fields_by_instance.setdefault(instance_id, set()).add(field)
    return {instance_id for instance_id, fields in fields_by_instance.items() if set(FIELDS).issubset(fields)}


def _completed_fields(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    fields_by_instance: dict[str, set[str]] = {}
    for row in rows:
        instance_id = str(row.get("instance_id") or "")
        field = str(row.get("field") or "")
        if instance_id and field in FIELDS:
            fields_by_instance.setdefault(instance_id, set()).add(field)
    return fields_by_instance


def _build_prompt(*, instance: dict[str, Any], gold: dict[str, Any], prediction: dict[str, Any]) -> str:
    payload = {
        "study_id": instance.get("study_id"),
        "question_pico": instance.get("question_pico"),
        "gold": {field: gold.get(field) or "" for field in FIELDS},
        "predicted": {field: prediction.get(field) or "" for field in FIELDS},
    }
    return render_prompt_template(JUDGE_PROMPT, {"input_json": json.dumps(payload, ensure_ascii=False)})


def _build_field_prompt(*, instance: dict[str, Any], gold: dict[str, Any], prediction: dict[str, Any], field: str) -> str:
    payload = {
        "study_id": instance.get("study_id"),
        "question_pico": instance.get("question_pico"),
        "gold": {field: gold.get(field) or ""},
        "predicted": {field: prediction.get(field) or ""},
    }
    prompt = render_prompt_template(JUDGE_PROMPT, {"input_json": json.dumps(payload, ensure_ascii=False)})
    return (
        f"{prompt}\n\nJudge only the '{field}' field. "
        f"Return the same JSON shape, but include only fields.{field}."
    )


def _call_llm_json(*, config: dict[str, str], prompt: str) -> dict[str, Any]:
    timeout_seconds = config.get("judge_timeout_seconds") or config.get("timeout_seconds")
    return call_llm_json(
        config=config,
        system="You are a strict clinical evidence semantic matching judge. Return only valid JSON.",
        prompt=prompt,
        timeout_seconds=float(timeout_seconds) if timeout_seconds else None,
    )


def _coerce_rows(*, instance_id: str, parsed: dict[str, Any], gold: dict[str, Any], prediction: dict[str, Any]) -> list[dict[str, Any]]:
    fields_payload = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    rows: list[dict[str, Any]] = []
    for field in FIELDS:
        payload = fields_payload.get(field) if isinstance(fields_payload.get(field), dict) else {}
        gold_claims = [str(item) for item in payload.get("gold_claims") or []]
        predicted_claims = [str(item) for item in payload.get("predicted_claims") or []]
        if not gold_claims and gold.get(field):
            gold_claims = [str(gold.get(field) or "")]
        if not predicted_claims and prediction.get(field):
            predicted_claims = [str(prediction.get(field) or "")]
        matches = _valid_matches(payload.get("matches") or [], len(gold_claims), len(predicted_claims))
        matched_gold = {int(match["gold_index"]) for match in matches}
        matched_predicted = {int(match["predicted_index"]) for match in matches}
        rows.append(
            {
                "instance_id": instance_id,
                "study_id": str(gold.get("study_id") or ""),
                "field": field,
                "gold_claims": gold_claims,
                "predicted_claims": predicted_claims,
                "matches": matches,
                "unmatched_gold_indices": [index for index in range(len(gold_claims)) if index not in matched_gold],
                "unmatched_predicted_indices": [index for index in range(len(predicted_claims)) if index not in matched_predicted],
                "judge_mode": "llm",
            }
        )
    return rows


def _coerce_field_row(*, instance_id: str, parsed: dict[str, Any], gold: dict[str, Any], prediction: dict[str, Any], field: str) -> dict[str, Any]:
    fields_payload = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    payload = fields_payload.get(field) if isinstance(fields_payload.get(field), dict) else {}
    gold_claims = [str(item) for item in payload.get("gold_claims") or []]
    predicted_claims = [str(item) for item in payload.get("predicted_claims") or []]
    if not gold_claims and gold.get(field):
        gold_claims = [str(gold.get(field) or "")]
    if not predicted_claims and prediction.get(field):
        predicted_claims = [str(prediction.get(field) or "")]
    matches = _valid_matches(payload.get("matches") or [], len(gold_claims), len(predicted_claims))
    matched_gold = {int(match["gold_index"]) for match in matches}
    matched_predicted = {int(match["predicted_index"]) for match in matches}
    return {
        "instance_id": instance_id,
        "study_id": str(gold.get("study_id") or ""),
        "field": field,
        "gold_claims": gold_claims,
        "predicted_claims": predicted_claims,
        "matches": matches,
        "unmatched_gold_indices": [index for index in range(len(gold_claims)) if index not in matched_gold],
        "unmatched_predicted_indices": [index for index in range(len(predicted_claims)) if index not in matched_predicted],
        "judge_mode": "llm",
    }


def _valid_matches(raw_matches: list[Any], gold_count: int, predicted_count: int) -> list[dict[str, Any]]:
    matches = []
    used_gold: set[int] = set()
    used_predicted: set[int] = set()
    for item in raw_matches:
        if not isinstance(item, dict):
            continue
        try:
            gold_index = int(item.get("gold_index"))
            predicted_index = int(item.get("predicted_index"))
        except (TypeError, ValueError):
            continue
        if gold_index < 0 or gold_index >= gold_count or predicted_index < 0 or predicted_index >= predicted_count:
            continue
        if gold_index in used_gold or predicted_index in used_predicted:
            continue
        used_gold.add(gold_index)
        used_predicted.add(predicted_index)
        matches.append({"gold_index": gold_index, "predicted_index": predicted_index, "rationale": str(item.get("rationale") or "")})
    return matches


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM judge response JSON must be an object")
    return parsed


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())
