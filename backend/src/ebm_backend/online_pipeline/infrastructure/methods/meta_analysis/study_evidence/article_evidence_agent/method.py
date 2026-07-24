"""Bounded article-level evidence agent for Meta-analysis study contributions."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import html
import json
import math
import os
from pathlib import Path
import re
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm import (
    LLMAPIError,
    LLMConfig,
    call_llm_json,
    load_llm_config,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.errors import (
    MetaAnalysisConfigurationError,
    MetaAnalysisInvocationError,
    MetaAnalysisOutputError,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent.calculators import (
    solve_arm,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent.schemas import (
    controller_schema,
    resolution_schema,
    support_recovery_schema,
    table_map_schema,
    table_result_schema,
    verification_schema,
)


LLMJsonCaller = Callable[..., dict[str, Any]]
MAX_CONTROLLER_TURNS = 12
MAX_SECTION_READS = 8
MAX_TABLE_READS = 32
MAX_TABLE_WORKERS = 4
MAX_SUPPORT_TABLE_READS = 8
POLICY_VERSION = "cochrane_article_evidence_v2"
SCHEMA_VERSION = "article_evidence_v2"
_REQUIRED_FIELDS = {
    "Dichotomous": ("events", "total"),
    "Continuous": ("mean", "sd", "total"),
}
_SIDE_FIELDS = {
    "Dichotomous": {
        "experimental": ("experimental_events", "experimental_total"),
        "control": ("control_events", "control_total"),
    },
    "Continuous": {
        "experimental": ("experimental_mean", "experimental_sd", "experimental_total"),
        "control": ("control_mean", "control_sd", "control_total"),
    },
}
_LOCAL_COMPATIBILITY_FIELDS = (
    "outcome_label",
    "outcome_measure",
    "unit",
    "timepoint",
    "analysis_input_representation",
    "population_or_subgroup",
    "analysis_population",
    "continuous_result_frame",
    "change_score_definition",
    "scale_direction",
)
_CROSS_TABLE_REQUIRED_IDENTITY_FIELDS = (
    "outcome_label",
    "outcome_measure",
    "timepoint",
    "analysis_input_representation",
    "analysis_population",
)


class Method:
    """Navigate one article and return all target-level study contributions."""

    def __init__(
        self,
        *,
        config: LLMConfig | dict[str, Any] | None = None,
        llm_caller: LLMJsonCaller = call_llm_json,
        prompt_dir: Path = Path(__file__).resolve().parent / "prompts",
        max_controller_turns: int = MAX_CONTROLLER_TURNS,
        max_section_reads: int = MAX_SECTION_READS,
        max_table_reads: int = MAX_TABLE_READS,
        max_table_workers: int = MAX_TABLE_WORKERS,
    ) -> None:
        self.config = config
        self.llm_caller = llm_caller
        self.prompt_dir = prompt_dir
        self.max_controller_turns = min(MAX_CONTROLLER_TURNS, max(1, max_controller_turns))
        self.max_section_reads = min(MAX_SECTION_READS, max(1, max_section_reads))
        self.max_table_reads = min(MAX_TABLE_READS, max(1, max_table_reads))
        self.max_table_workers = min(MAX_TABLE_WORKERS, max(1, max_table_workers))

    def run(
        self,
        *,
        review_id: str,
        targets: list[dict[str, Any]],
        study_id: str,
        article: dict[str, Any],
        plan_hash: str,
    ) -> dict[str, Any]:
        config = self._config()
        normalized_targets = _validate_targets(targets)
        if not normalized_targets:
            return {
                "study_id": study_id,
                "study_result_rows": [],
                "resolution_records": [],
                "data_rows": [],
                "coverage": _coverage(study_id=study_id, targets=[], status="complete"),
            }
        if str(article.get("study_id") or "") != study_id:
            raise ValueError("Article study_id does not match the article evidence task")

        context_id = f"{review_id}::{study_id}"
        debug_dir = _debug_dir(context_id)
        sections = _section_catalog(article)
        tables = _table_catalog(article)
        state: dict[str, Any] = {
            "study_map": _empty_study_map(),
            "read_sections": {},
            "table_results": {},
            "controller_turns": [],
            "warnings": [],
        }
        _write_artifact(
            debug_dir,
            "input.json",
            {
                "review_id": review_id,
                "study_id": study_id,
                "plan_hash": plan_hash,
                "targets": normalized_targets,
                "section_catalog": sections,
                "table_catalog": [_public_table_catalog(row) for row in tables],
                "policy_version": POLICY_VERSION,
                "schema_version": SCHEMA_VERSION,
            },
        )

        self._navigate(
            config=config,
            context_id=context_id,
            targets=normalized_targets,
            article=article,
            sections=sections,
            tables=tables,
            state=state,
            debug_dir=debug_dir,
        )
        candidates = [
            candidate
            for table_id in _table_order(tables)
            for candidate in (state["table_results"].get(table_id) or {}).get("candidates", [])
        ]
        support_materials = [
            material
            for table_id in _table_order(tables)
            for material in (state["table_results"].get(table_id) or {}).get(
                "support_materials",
                [],
            )
        ]
        recovered_support = self._recover_support_materials(
            config=config,
            context_id=context_id,
            candidates=candidates,
            study_map=state["study_map"],
            tables=[
                table
                for table in tables
                if table["table_id"] in state["table_results"]
            ],
            table_results=state["table_results"],
            debug_dir=debug_dir,
        )
        support_materials = _unique_materials(
            [*support_materials, *recovered_support]
        )
        source_coverage_complete = _source_coverage_complete(
            tables=tables,
            state=state,
            max_table_reads=self.max_table_reads,
        )
        resolutions = self._resolve(
            config=config,
            context_id=context_id,
            targets=normalized_targets,
            study_map=state["study_map"],
            candidates=candidates,
            support_materials=support_materials,
            source_coverage_complete=source_coverage_complete,
            debug_dir=debug_dir,
        )

        rows: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        data_rows: list[dict[str, Any]] = []
        candidate_by_id = {str(row["candidate_id"]): row for row in candidates}
        table_by_id = {str(row["table_id"]): row for row in tables}
        target_by_id = {str(row["target_id"]): row for row in normalized_targets}
        for resolution in resolutions:
            target = target_by_id[str(resolution["target_id"])]
            verified = resolution
            if resolution["status"] == "resolved":
                verified = self._verify_resolution(
                    config=config,
                    context_id=context_id,
                    target=target,
                    study_map=state["study_map"],
                    resolution=resolution,
                    candidate_by_id=candidate_by_id,
                    support_materials=support_materials,
                    table_by_id=table_by_id,
                    debug_dir=debug_dir,
                )
            assembled, assembly_error = _assemble_resolution(
                study_id=study_id,
                target=target,
                study_map=state["study_map"],
                resolution=verified,
                candidate_by_id=candidate_by_id,
                support_materials=support_materials,
                study_year=_study_year(article),
            )
            if verified["status"] == "resolved" and assembly_error:
                verified = {
                    **verified,
                    "status": "unresolved",
                    "operation": "unresolved",
                    "unresolved_candidate_ids": list(verified.get("candidate_ids") or []),
                    "reason": assembly_error,
                }
                assembled = None
            row = _study_result_row(
                study_id=study_id,
                study_year=_study_year(article),
                target=target,
                candidates=candidates,
                resolution=verified,
                source_coverage_complete=source_coverage_complete,
            )
            record = _resolution_record(
                study_id=study_id,
                target=target,
                resolution=verified,
                candidate_by_id=candidate_by_id,
                assembled=assembled,
            )
            rows.append(row)
            records.append(record)
            if assembled is not None:
                data_rows.append(assembled)

        result = {
            "study_id": study_id,
            "study_result_rows": rows,
            "resolution_records": records,
            "data_rows": data_rows,
            "coverage": _coverage(
                study_id=study_id,
                targets=normalized_targets,
                status="complete" if source_coverage_complete else "incomplete_source_coverage",
                read_section_ids=list(state["read_sections"]),
                read_table_ids=list(state["table_results"]),
                warnings=state["warnings"],
            ),
        }
        _write_artifact(
            debug_dir,
            "final.json",
            {
                "study_map": state["study_map"],
                "controller_turns": state["controller_turns"],
                "candidates": candidates,
                "support_materials": support_materials,
                "result": result,
            },
        )
        return result

    def _config(self) -> dict[str, Any]:
        try:
            loaded = self.config if self.config is not None else load_llm_config()
            if loaded is None:
                raise RuntimeError("Missing required LLM config")
            payload = loaded.to_dict() if isinstance(loaded, LLMConfig) else dict(loaded)
            payload["sdk_max_retries"] = 0
            payload["json_marker_retry_enabled"] = False
            return payload
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise MetaAnalysisConfigurationError(stage="study_evidence_agent") from exc

    def _prompt(self, name: str) -> str:
        try:
            return (self.prompt_dir / name).read_text(encoding="utf-8")
        except OSError as exc:
            raise MetaAnalysisConfigurationError(stage="study_evidence_agent") from exc

    def _navigate(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        targets: list[dict[str, Any]],
        article: dict[str, Any],
        sections: list[dict[str, Any]],
        tables: list[dict[str, Any]],
        state: dict[str, Any],
        debug_dir: Path | None,
    ) -> None:
        section_by_id = {str(row["section_id"]): row for row in sections}
        table_by_id = {str(row["table_id"]): row for row in tables}
        stalled_turns = 0
        for turn in range(1, self.max_controller_turns + 1):
            unread_section_ids = [
                row["section_id"] for row in sections if row["section_id"] not in state["read_sections"]
            ]
            unread_table_ids = [
                row["table_id"] for row in tables if row["table_id"] not in state["table_results"]
            ]
            payload = {
                "task": "navigate_article_evidence",
                "targets": [_semantic_target(row) for row in targets],
                "section_catalog": sections,
                "table_catalog": [_public_table_catalog(row) for row in tables],
                "study_map": state["study_map"],
                "read_sections": list(state["read_sections"].values()),
                "table_result_summaries": [
                    _table_result_summary(table_id, state["table_results"][table_id])
                    for table_id in _table_order(tables)
                    if table_id in state["table_results"]
                ],
                "remaining_budget": {
                    "controller_turns": self.max_controller_turns - turn + 1,
                    "section_reads": self.max_section_reads - len(state["read_sections"]),
                    "table_reads": self.max_table_reads - len(state["table_results"]),
                },
                "warnings": state["warnings"][-4:],
            }
            action = self._call(
                config=config,
                stage="study_evidence_controller",
                context_id=context_id,
                system=self._prompt("controller.txt"),
                payload=payload,
                schema=controller_schema(
                    section_ids=[str(section_id) for section_id in unread_section_ids],
                    table_ids=[str(table_id) for table_id in unread_table_ids],
                ),
                schema_name="meta_study_evidence_controller",
                max_output_tokens=4096,
                reasoning_effort="medium",
            )
            action = _normalize_controller_action(
                action,
                section_ids=set(section_by_id),
                table_ids=set(table_by_id),
            )
            state["study_map"] = _merge_study_map(state["study_map"], action["study_map"])
            state["controller_turns"].append(
                {
                    "turn": turn,
                    "action": action["action"],
                    "section_ids": action["section_ids"],
                    "table_ids": action["table_ids"],
                    "reason": action["reason"],
                }
            )
            _write_artifact(debug_dir, f"controller_turn_{turn:02d}.json", {"input": payload, "output": action})

            made_progress = False
            if action["action"] == "read_sections":
                remaining = self.max_section_reads - len(state["read_sections"])
                requested = [
                    section_id
                    for section_id in action["section_ids"]
                    if section_id in unread_section_ids
                ][: max(0, remaining)]
                for section_id in requested:
                    section = section_by_id[section_id]
                    state["read_sections"][section_id] = {
                        "section_id": section_id,
                        "title": section["title"],
                        "text": _section_text(article, section_id),
                    }
                made_progress = bool(requested)
            elif action["action"] == "extract_tables":
                remaining = self.max_table_reads - len(state["table_results"])
                requested = [
                    table_id
                    for table_id in action["table_ids"]
                    if table_id in unread_table_ids
                ][: max(0, remaining)]
                extracted = self._extract_tables(
                    config=config,
                    context_id=context_id,
                    targets=targets,
                    tables=[table_by_id[table_id] for table_id in requested],
                    debug_dir=debug_dir,
                )
                state["table_results"].update(extracted)
                made_progress = bool(requested)
            else:
                if unread_table_ids and _needs_first_support_table_search(state):
                    stalled_turns += 1
                    state["warnings"].append(
                        "Controller ready action was deferred because an incomplete result candidate "
                        "still had no typed supporting material and unread tables remained."
                    )
                    if stalled_turns >= 2:
                        return
                    continue
                return

            if made_progress:
                stalled_turns = 0
                continue
            stalled_turns += 1
            state["warnings"].append(
                f"Controller turn {turn} requested no unread source within the remaining budget."
            )
            if stalled_turns >= 2:
                return

    def _extract_tables(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        targets: list[dict[str, Any]],
        tables: list[dict[str, Any]],
        debug_dir: Path | None,
    ) -> dict[str, dict[str, Any]]:
        def extract(table: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            table_id = str(table["table_id"])
            table_map: dict[str, Any] | None = None
            if bool(table.get("complex_structure")):
                table_map = self._call(
                    config=config,
                    stage="table_structure",
                    context_id=f"{context_id}::{table_id}",
                    system=self._prompt("table_structure.txt"),
                    payload={
                        "table_id": table_id,
                        "caption": table.get("caption"),
                        "raw_xml": table.get("raw_xml"),
                    },
                    schema=table_map_schema(),
                    schema_name="meta_table_structure",
                    max_output_tokens=4096,
                    reasoning_effort="medium",
                )
                _write_artifact(debug_dir, f"table_map__{_slug(table_id)}.json", table_map)
            output = self._call(
                config=config,
                stage="table_result_extraction",
                context_id=f"{context_id}::{table_id}",
                system=self._prompt("table_results.txt"),
                payload={
                    "table_id": table_id,
                    "caption": table.get("caption"),
                    "raw_xml": table.get("raw_xml"),
                    "table_map": table_map,
                    "review_targets": [_table_target(row) for row in targets],
                },
                schema=table_result_schema(),
                schema_name="meta_table_result_blocks",
                max_output_tokens=12288,
                reasoning_effort="medium",
            )
            normalized = _normalize_table_result(
                output,
                table=table,
                targets=targets,
            )
            _write_artifact(debug_dir, f"table_results__{_slug(table_id)}.json", normalized)
            return table_id, normalized

        if not tables:
            return {}
        workers = min(self.max_table_workers, len(tables))
        if workers <= 1:
            pairs = [extract(table) for table in tables]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                pairs = list(executor.map(extract, tables))
        return dict(pairs)

    def _resolve(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        targets: list[dict[str, Any]],
        study_map: dict[str, Any],
        candidates: list[dict[str, Any]],
        support_materials: list[dict[str, Any]],
        source_coverage_complete: bool,
        debug_dir: Path | None,
    ) -> list[dict[str, Any]]:
        if not candidates:
            status = "data_unavailable" if source_coverage_complete else "unresolved"
            reason = (
                "No relevant table-local result block was found."
                if source_coverage_complete
                else "No result was found before source coverage became incomplete."
            )
            return [
                _empty_resolution(target_id=str(target["target_id"]), status=status, reason=reason)
                for target in targets
            ]
        candidate_ids = [str(row["candidate_id"]) for row in candidates]
        support_material_ids = [
            str(row["material_id"])
            for row in support_materials
            if row.get("material_id")
        ]
        output = self._call(
            config=config,
            stage="study_evidence_resolution",
            context_id=context_id,
            system=self._prompt("resolution.txt"),
            payload={
                "policy_version": POLICY_VERSION,
                "targets": [_semantic_target(row) for row in targets],
                "study_map": study_map,
                "candidates": [_candidate_summary(row) for row in candidates],
                "support_materials": [
                    _support_material_summary(row) for row in support_materials
                ],
                "source_coverage_complete": source_coverage_complete,
            },
            schema=resolution_schema(
                target_ids=[str(row["target_id"]) for row in targets],
                candidate_ids=candidate_ids,
                support_material_ids=support_material_ids,
            ),
            schema_name="meta_article_resolution",
            max_output_tokens=12288,
            reasoning_effort="medium",
        )
        resolutions = _normalize_resolutions(
            output,
            target_ids=[str(row["target_id"]) for row in targets],
            candidate_ids=set(candidate_ids),
            support_material_ids=set(support_material_ids),
            source_coverage_complete=source_coverage_complete,
        )
        _write_artifact(debug_dir, "resolution.json", {"input_candidates": [_candidate_summary(row) for row in candidates], "output": resolutions})
        return resolutions

    def _recover_support_materials(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        candidates: list[dict[str, Any]],
        study_map: dict[str, Any],
        tables: list[dict[str, Any]],
        table_results: dict[str, dict[str, Any]],
        debug_dir: Path | None,
    ) -> list[dict[str, Any]]:
        needs = _support_material_needs(candidates)
        if not needs:
            return []
        candidate_table_ids = {
            str(candidate.get("source_table_id") or "") for candidate in candidates
        }
        recovery_tables = [
            table
            for table in tables
            if str(table["table_id"]) not in candidate_table_ids
            and not (table_results.get(str(table["table_id"])) or {}).get(
                "support_materials"
            )
        ][:MAX_SUPPORT_TABLE_READS]
        if not recovery_tables:
            return []

        def recover(table: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
            table_id = str(table["table_id"])
            output = self._call(
                config=config,
                stage="support_material_recovery",
                context_id=f"{context_id}::{table_id}",
                system=self._prompt("support_materials.txt"),
                payload={
                    "table_id": table_id,
                    "caption": table.get("caption"),
                    "raw_xml": table.get("raw_xml"),
                    "study_map": study_map,
                    "material_needs": needs,
                },
                schema=support_recovery_schema(),
                schema_name="meta_support_material_recovery",
                max_output_tokens=8192,
                reasoning_effort="medium",
            )
            normalized = _normalize_support_materials(
                output.get("support_materials"),
                table=table,
                key_prefix="recovery",
            )
            _write_artifact(
                debug_dir,
                f"support_recovery__{_slug(table_id)}.json",
                {
                    "material_needs": needs,
                    "source_summary": output.get("source_summary"),
                    "support_materials": normalized,
                },
            )
            return table_id, normalized

        workers = min(self.max_table_workers, len(recovery_tables))
        if workers <= 1:
            pairs = [recover(table) for table in recovery_tables]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                pairs = list(executor.map(recover, recovery_tables))
        by_table = dict(pairs)
        return [
            material
            for table in recovery_tables
            for material in by_table.get(str(table["table_id"]), [])
        ]

    def _verify_resolution(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        target: dict[str, Any],
        study_map: dict[str, Any],
        resolution: dict[str, Any],
        candidate_by_id: dict[str, dict[str, Any]],
        support_materials: list[dict[str, Any]],
        table_by_id: dict[str, dict[str, Any]],
        debug_dir: Path | None,
    ) -> dict[str, Any]:
        candidate_ids = [
            str(candidate_id)
            for candidate_id in resolution.get("candidate_ids") or []
            if str(candidate_id) in candidate_by_id
        ]
        if not candidate_ids:
            return {
                **resolution,
                "status": "unresolved",
                "operation": "unresolved",
                "reason": "Resolved proposal did not identify a source candidate.",
            }

        current = resolution
        support_by_id = {
            str(row["material_id"]): row
            for row in support_materials
            if row.get("material_id")
        }
        for verification_round in range(1, 3):
            selected = [candidate_by_id[candidate_id] for candidate_id in candidate_ids]
            selected_support = [
                support_by_id[material_id]
                for material_id in _text_list(current.get("support_material_ids"))
                if material_id in support_by_id
            ]
            source_ids = _unique(
                [
                    *[str(row["source_table_id"]) for row in selected],
                    *[str(row["source_table_id"]) for row in selected_support],
                ]
            )
            raw_sources = [
                {
                    "table_id": source_id,
                    "caption": (table_by_id.get(source_id) or {}).get("caption"),
                    "raw_xml": (table_by_id.get(source_id) or {}).get("raw_xml"),
                }
                for source_id in source_ids
            ]
            output = self._call(
                config=config,
                stage="selected_result_verification",
                context_id=f"{context_id}::{target['target_id']}",
                system=self._prompt("verify.txt"),
                payload={
                    "target": _semantic_target(target),
                    "study_map": study_map,
                    "resolution": current,
                    "selected_candidates": selected,
                    "selected_support_materials": selected_support,
                    "raw_sources": raw_sources,
                },
                schema=verification_schema(
                    target_ids=[str(target["target_id"])],
                    candidate_ids=list(candidate_by_id),
                    support_material_ids=list(support_by_id),
                ),
                schema_name="meta_selected_result_verification",
                max_output_tokens=8192,
                reasoning_effort="medium",
            )
            _write_artifact(
                debug_dir,
                f"verification__{_slug(str(target['target_id']))}__{verification_round}.json",
                output,
            )
            if bool(output.get("valid")):
                return current
            corrected = output.get("corrected_resolution")
            if verification_round == 1 and isinstance(corrected, dict):
                normalized = _normalize_resolutions(
                    {"resolutions": [corrected]},
                    target_ids=[str(target["target_id"])],
                    candidate_ids=set(candidate_by_id),
                    support_material_ids=set(support_by_id),
                    source_coverage_complete=True,
                )[0]
                if normalized["status"] == "resolved":
                    current = normalized
                    candidate_ids = list(normalized["candidate_ids"])
                    continue
            return {
                **current,
                "status": "unresolved",
                "operation": "unresolved",
                "unresolved_candidate_ids": list(current.get("candidate_ids") or []),
                "reason": "Selected-result verification failed: " + "; ".join(_text_list(output.get("issues"))),
            }
        return current

    def _call(
        self,
        *,
        config: dict[str, Any],
        stage: str,
        context_id: str,
        system: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        schema_name: str,
        max_output_tokens: int,
        reasoning_effort: str,
    ) -> dict[str, Any]:
        kwargs = {
            "config": config,
            "system": system,
            "prompt": json.dumps(payload, ensure_ascii=False),
            "temperature": 0,
            "max_output_tokens": max_output_tokens,
            "reasoning_effort": reasoning_effort,
            "json_schema": schema,
            "json_schema_name": schema_name,
        }
        for attempt in range(1, 3):
            try:
                result = self.llm_caller(**kwargs)
                if not isinstance(result, dict):
                    raise ValueError("LLM response must be an object")
                return result
            except LLMAPIError as exc:
                if not exc.retryable:
                    raise MetaAnalysisInvocationError(
                        stage=stage,
                        attempts=attempt,
                        retry_exhausted=False,
                        context_id=context_id,
                    ) from exc
                if attempt == 2:
                    raise MetaAnalysisInvocationError(
                        stage=stage,
                        attempts=attempt,
                        retry_exhausted=True,
                        context_id=context_id,
                    ) from exc
            except (KeyError, TypeError, ValueError) as exc:
                if attempt == 2:
                    raise MetaAnalysisOutputError(
                        stage=stage,
                        attempts=attempt,
                        context_id=context_id,
                        validation_error=str(exc),
                    ) from exc
        raise AssertionError("unreachable")


def build_method(
    *,
    config: LLMConfig | dict[str, Any] | None = None,
) -> Method:
    return Method(config=config)


def _validate_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("Meta-analysis target must be an object")
        target_id = str(target.get("target_id") or "").strip()
        if not target_id or target_id in seen:
            raise ValueError("Meta-analysis targets require unique target_id values")
        data_type = str(target.get("data_type") or "")
        if data_type not in _REQUIRED_FIELDS:
            raise ValueError(f"Unsupported target data type: {data_type}")
        seen.add(target_id)
        result.append(deepcopy(target))
    return result


def _section_catalog(article: dict[str, Any]) -> list[dict[str, Any]]:
    xml = article.get("xml_content") if isinstance(article.get("xml_content"), dict) else {}
    result = []
    seen: set[str] = set()
    for index, section in enumerate(xml.get("sections") or []):
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id") or f"section-{index + 1}")
        if section_id in seen:
            section_id = f"{section_id}-{index + 1}"
        seen.add(section_id)
        result.append(
            {
                "section_id": section_id,
                "title": str(section.get("title") or ""),
                "char_count": len(str(section.get("text") or "")),
            }
        )
    return result


def _section_text(article: dict[str, Any], section_id: str) -> str:
    xml = article.get("xml_content") if isinstance(article.get("xml_content"), dict) else {}
    for section in xml.get("sections") or []:
        if isinstance(section, dict) and str(section.get("section_id") or "") == section_id:
            return str(section.get("text") or "")
    return ""


def _table_catalog(article: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    seen: dict[str, int] = {}
    for index, table in enumerate(article.get("tables") or []):
        if not isinstance(table, dict):
            continue
        raw_id = str(table.get("table_id") or f"table-{index + 1}")
        count = seen.get(raw_id, 0) + 1
        seen[raw_id] = count
        table_id = raw_id if count == 1 else f"{raw_id}-{count}"
        raw_xml = str(table.get("raw_xml") or "")
        result.append(
            {
                "table_id": table_id,
                "caption": str(table.get("caption") or ""),
                "raw_xml": raw_xml,
                "char_count": len(raw_xml),
                "complex_structure": _complex_table(raw_xml),
                "source_hash": sha256(raw_xml.encode("utf-8")).hexdigest(),
            }
        )
    return result


def _public_table_catalog(table: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_id": table["table_id"],
        "caption": table["caption"],
        "char_count": table["char_count"],
        "complex_structure": table["complex_structure"],
    }


def _complex_table(raw_xml: str) -> bool:
    lowered = raw_xml.casefold()
    return (
        bool(re.search(r"(?:rowspan|colspan)\s*=\s*['\"](?:[2-9]|[1-9][0-9]+)['\"]", lowered))
        or lowered.count("<thead") > 1
        or lowered.count("<th") >= 8
        or len(re.findall(r"<table(?:\s|>)", lowered)) > 1
        or len(raw_xml) > 35_000
    )


def _normalize_controller_action(
    value: dict[str, Any],
    *,
    section_ids: set[str],
    table_ids: set[str],
) -> dict[str, Any]:
    action = str(value.get("action") or "")
    if action not in {"read_sections", "extract_tables", "ready"}:
        raise ValueError(f"Unsupported controller action: {action}")
    study_map = value.get("study_map")
    if not isinstance(study_map, dict):
        raise ValueError("Controller must return study_map")
    return {
        "action": action,
        "section_ids": [row for row in _text_list(value.get("section_ids")) if row in section_ids],
        "table_ids": [row for row in _text_list(value.get("table_ids")) if row in table_ids],
        "study_map": study_map,
        "reason": _optional_text(value.get("reason")),
    }


def _empty_study_map() -> dict[str, Any]:
    return {
        "study_design": None,
        "population": None,
        "treatment_duration": None,
        "follow_up": [],
        "analysis_populations": [],
        "arms": [],
        "notes": [],
    }


def _merge_study_map(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(current)
    for field in ("study_design", "population", "treatment_duration"):
        if _optional_text(update.get(field)):
            result[field] = _optional_text(update.get(field))
    for field in ("follow_up", "analysis_populations", "notes"):
        result[field] = _unique([*(_text_list(result.get(field))), *(_text_list(update.get(field)))])
    arms: dict[str, dict[str, Any]] = {
        _norm(str(row.get("label") or "")): deepcopy(row)
        for row in result.get("arms") or []
        if isinstance(row, dict) and _norm(str(row.get("label") or ""))
    }
    for arm in update.get("arms") or []:
        if not isinstance(arm, dict):
            continue
        label = str(arm.get("label") or "").strip()
        key = _norm(label)
        if not key:
            continue
        existing = arms.get(key, {"label": label, "aliases": [], "role": "unclear", "description": None})
        existing["aliases"] = _unique([*(_text_list(existing.get("aliases"))), *(_text_list(arm.get("aliases")))])
        if str(arm.get("role") or "unclear") != "unclear":
            existing["role"] = str(arm["role"])
        if _optional_text(arm.get("description")):
            existing["description"] = _optional_text(arm.get("description"))
        arms[key] = existing
    result["arms"] = list(arms.values())
    return result


def _normalize_table_result(
    value: dict[str, Any],
    *,
    table: dict[str, Any],
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    status = str(value.get("source_status") or "")
    if status not in {"results_found", "no_relevant_results", "unreadable"}:
        raise ValueError(f"Unsupported table source status: {status}")
    candidates = []
    raw_xml = str(table.get("raw_xml") or "")
    raw_text = _xml_text(raw_xml)
    for index, block in enumerate(value.get("result_blocks") or []):
        if not isinstance(block, dict):
            continue
        data_type = str(block.get("data_type") or "")
        if data_type not in _REQUIRED_FIELDS:
            continue
        local_setting = _block_local_setting(block)
        arms = []
        uncertainties = _text_list(block.get("uncertainties"))
        for arm_index, arm in enumerate(block.get("arms") or []):
            if not isinstance(arm, dict):
                continue
            label = str(arm.get("label") or "").strip()
            quote = str(arm.get("source_quote") or "").strip()
            if not label:
                continue
            if quote and not _quote_matches_source(quote, raw_text):
                uncertainties.append(f"Source quote for arm '{label}' could not be matched verbatim after XML text normalization.")
            materials = _arm_materials(
                arm=arm,
                arm_label=label,
                local_setting=local_setting,
                table=table,
                block_index=index,
                arm_index=arm_index,
            )
            calculation = solve_arm(data_type=data_type, materials=materials)
            uncertainties.extend(calculation.warnings)
            arms.append(
                {
                    "label": label,
                    "events": calculation.values.get("events"),
                    "total": calculation.values.get("total"),
                    "mean": calculation.values.get("mean"),
                    "sd": calculation.values.get("sd"),
                    "materials": materials,
                    "field_traces": calculation.field_traces,
                    "source_quote": quote,
                }
            )
        if not arms:
            continue
        block_materials = [
            material
            for material_index, raw_material in enumerate(block.get("block_materials") or [])
            if (
                material := _normalize_material(
                    raw=raw_material,
                    arm_label=None,
                    local_setting=local_setting,
                    table=table,
                    material_key=f"block-{index}-{material_index}",
                )
            )
            is not None
        ]
        statistic_profile = _statistic_profile(
            data_type=data_type,
            arms=arms,
            block_materials=block_materials,
            reported_statistic_type=local_setting.get("statistic_type"),
        )
        local_setting = {
            **local_setting,
            "reported_statistic_type": local_setting.get("statistic_type"),
            "statistic_type": statistic_profile["canonical_statistic_type"],
            "analysis_input_representation": statistic_profile[
                "analysis_input_representation"
            ],
            "reported_statistic_kinds": statistic_profile[
                "reported_statistic_kinds"
            ],
            "statistic_type_status": statistic_profile["status"],
        }
        uncertainties.extend(statistic_profile["warnings"])
        identity = json.dumps(
            {"table": table["table_id"], "setting": local_setting, "arms": [row["label"] for row in arms], "index": index},
            ensure_ascii=False,
            sort_keys=True,
        )
        candidate_id = f"candidate::{_slug(str(table['table_id']))}::{sha256(identity.encode('utf-8')).hexdigest()[:14]}"
        candidates.append(
            {
                "candidate_id": candidate_id,
                "source_table_id": str(table["table_id"]),
                "source_hash": str(table["source_hash"]),
                "data_type": data_type,
                "local_setting": local_setting,
                "arms": arms,
                "block_materials": block_materials,
                "uncertainties": _unique(uncertainties),
                "source_spans": _unique_dicts([
                    {
                        "source_id": str(table["table_id"]),
                        "table_id": str(table["table_id"]),
                        "text": material["source_quote"],
                    }
                    for row in arms
                    for material in row["materials"]
                    if material.get("source_quote")
                ]),
            }
        )
    support_materials = _normalize_support_materials(
        value.get("support_materials"),
        table=table,
        key_prefix="support",
    )
    return {
        "source_status": status,
        "source_summary": _optional_text(value.get("source_summary")),
        "candidates": candidates,
        "support_materials": support_materials,
        "target_count": len(targets),
    }


def _normalize_support_materials(
    values: Any,
    *,
    table: dict[str, Any],
    key_prefix: str,
) -> list[dict[str, Any]]:
    support_materials = []
    for index, support in enumerate(values or []):
        if not isinstance(support, dict):
            continue
        local_setting = {
            "outcome_label": _optional_text(support.get("outcome_label")),
            "outcome_measure": _optional_text(support.get("outcome_measure")),
            "timepoint": _optional_text(support.get("timepoint")),
            "population_or_subgroup": _optional_text(support.get("population_or_subgroup")),
            "analysis_population": _optional_text(support.get("analysis_population")),
        }
        material = _normalize_material(
            raw=support.get("material"),
            arm_label=_optional_text(support.get("arm_label")),
            local_setting=local_setting,
            table=table,
            material_key=f"{key_prefix}-{index}",
        )
        if material is not None:
            support_materials.append(material)
    return support_materials


def _support_material_needs(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    material_kinds = {
        "events": ["event_count", "non_event_count", "percentage"],
        "total": [
            "analyzed_total",
            "result_denominator",
            "outcome_complete_count",
            "randomized_total",
            "baseline_total",
            "attrition_count",
        ],
        "mean": ["mean"],
        "sd": [
            "standard_deviation",
            "variance",
            "standard_error",
            "confidence_interval",
        ],
    }
    needs = []
    for candidate in candidates:
        data_type = str(candidate.get("data_type") or "")
        for arm in candidate.get("arms") or []:
            missing = [
                field
                for field in _REQUIRED_FIELDS.get(data_type, ())
                if arm.get(field) is None
            ]
            if not missing:
                continue
            needs.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "source_table_id": candidate.get("source_table_id"),
                    "data_type": data_type,
                    "arm_label": arm.get("label"),
                    "local_setting": candidate.get("local_setting") or {},
                    "missing_fields": missing,
                    "acceptable_material_kinds": _unique(
                        [kind for field in missing for kind in material_kinds[field]]
                    ),
                }
            )
    return needs


def _block_local_setting(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "outcome_label": _optional_text(block.get("outcome_label")),
        "outcome_measure": _optional_text(block.get("outcome_measure")),
        "unit": _optional_text(block.get("unit")),
        "timepoint": _optional_text(block.get("timepoint")),
        "statistic_type": _optional_text(block.get("statistic_type")),
        "population_or_subgroup": _optional_text(block.get("population_or_subgroup")),
        "analysis_population": _optional_text(block.get("analysis_population")),
        "continuous_result_frame": _optional_text(block.get("continuous_result_frame")),
        "change_score_definition": _optional_text(block.get("change_score_definition")),
        "scale_direction": _optional_text(block.get("scale_direction")) or "unclear",
        "table_local_notes": "; ".join(_text_list(block.get("table_local_notes"))) or None,
    }


def _statistic_profile(
    *,
    data_type: str,
    arms: list[dict[str, Any]],
    block_materials: list[dict[str, Any]],
    reported_statistic_type: Any,
) -> dict[str, Any]:
    arm_materials = [
        material
        for arm in arms
        for material in arm.get("materials") or []
        if isinstance(material, dict)
    ]
    all_materials = [*arm_materials, *block_materials]
    reported_kinds = sorted(
        {
            str(material.get("kind") or "")
            for material in all_materials
            if str(material.get("kind") or "")
        }
    )
    complete_arm_input = bool(arms) and all(
        all(arm.get(field) is not None for field in _REQUIRED_FIELDS.get(data_type, ()))
        for arm in arms
    )
    if data_type == "Dichotomous" and complete_arm_input:
        representation = "dichotomous_arm_events_total"
        canonical = (
            "events/N (%)" if "percentage" in reported_kinds else "events/N"
        )
    elif data_type == "Continuous" and complete_arm_input:
        representation = "continuous_arm_mean_sd_total"
        canonical = "mean/SD/N"
    elif _has_between_group_effect_with_uncertainty(all_materials):
        representation = "between_group_effect_with_uncertainty"
        canonical = "effect estimate with uncertainty"
    else:
        representation = "incomplete_arm_data"
        canonical = (
            "incomplete dichotomous arm data"
            if data_type == "Dichotomous"
            else "incomplete continuous arm data"
        )

    reported = _optional_text(reported_statistic_type)
    declared_family = _declared_statistic_family(reported)
    expected_family = {
        "dichotomous_arm_events_total": "dichotomous_arm",
        "continuous_arm_mean_sd_total": "continuous_arm",
        "between_group_effect_with_uncertainty": "between_group_effect",
    }.get(representation)
    if reported is None:
        status = "derived" if expected_family else "unclear"
    elif declared_family is None or expected_family is None:
        status = "unclear"
    elif declared_family == expected_family:
        status = "consistent"
    else:
        status = "conflict"
    warnings = (
        ["reported_statistic_type_conflicts_with_typed_materials"]
        if status == "conflict"
        else []
    )
    return {
        "reported_statistic_kinds": reported_kinds,
        "analysis_input_representation": representation,
        "canonical_statistic_type": canonical,
        "status": status,
        "warnings": warnings,
    }


def _has_between_group_effect_with_uncertainty(
    materials: list[dict[str, Any]],
) -> bool:
    between_group = [
        material
        for material in materials
        if material.get("statistical_scope") == "between_group"
    ]
    kinds = {str(material.get("kind") or "") for material in between_group}
    return "effect_estimate" in kinds and bool(
        kinds
        & {
            "standard_error",
            "confidence_interval",
            "t_statistic",
            "f_statistic",
            "p_value",
        }
    )


def _declared_statistic_family(value: str | None) -> str | None:
    normalized = _norm(value or "")
    if not normalized:
        return None
    if re.search(
        r"\b(?:risk ratio|odds ratio|risk difference|mean difference|standardized mean difference|standardised mean difference|hazard ratio|effect estimate)\b",
        normalized,
    ):
        return "between_group_effect"
    if re.search(r"\bp\s*(?:-|\s)?value\b|\bp\s*[<=>]", normalized):
        return "p_value"
    if re.search(r"\b(?:event|events|non event|count|percentage|proportion)\b", normalized):
        return "dichotomous_arm"
    if re.search(
        r"\b(?:mean|standard deviation|standard error|variance|sd|se)\b",
        normalized,
    ):
        return "continuous_arm"
    return None


def _arm_materials(
    *,
    arm: dict[str, Any],
    arm_label: str,
    local_setting: dict[str, Any],
    table: dict[str, Any],
    block_index: int,
    arm_index: int,
) -> list[dict[str, Any]]:
    quote = str(arm.get("source_quote") or "").strip()
    materials: list[dict[str, Any]] = []

    def add(kind: str, value: Any, *, suffix: str, **metadata: Any) -> None:
        if _optional_number(value) is None:
            return
        raw = {
            "kind": kind,
            "value": value,
            "lower": None,
            "upper": None,
            "confidence_level": None,
            "decimal_places": None,
            "statistical_scope": "arm",
            "applies_to": "event_risk" if kind in {"event_count", "non_event_count", "analyzed_total", "result_denominator", "randomized_total", "baseline_total", "percentage"} else "mean",
            "source_quote": quote,
            "notes": None,
            "uncertainties": [],
            **metadata,
        }
        material = _normalize_material(
            raw=raw,
            arm_label=arm_label,
            local_setting=local_setting,
            table=table,
            material_key=f"block-{block_index}-arm-{arm_index}-{suffix}",
        )
        if material is not None:
            materials.append(material)

    add("event_count", arm.get("events"), suffix="events")
    add("non_event_count", arm.get("non_events"), suffix="non-events")
    total_kind = (
        str(arm.get("total_kind") or "unclear")
        if "total_kind" in arm
        else "analyzed"
    )
    total_material_kind = {
        "analyzed": "analyzed_total",
        "result_denominator": "result_denominator",
        "randomized": "randomized_total",
        "baseline": "baseline_total",
    }.get(total_kind)
    if total_kind == "unclear" and _reported_dichotomous_denominator_is_confirmed(arm):
        total_material_kind = "result_denominator"
    if total_material_kind is not None:
        add(total_material_kind, arm.get("total"), suffix="total")
    add(
        "percentage",
        arm.get("percentage"),
        suffix="percentage",
        decimal_places=arm.get("percentage_decimal_places"),
    )
    add("mean", arm.get("mean"), suffix="mean")
    add("standard_deviation", arm.get("sd"), suffix="sd")
    add("variance", arm.get("variance"), suffix="variance")
    uncertainty_scope = str(arm.get("uncertainty_scope") or "unclear")
    statistical_scope, applies_to = {
        "arm_mean": ("arm", "mean"),
        "arm_change_mean": ("arm", "change_mean"),
        "between_group": ("between_group", "mean_difference"),
        "unclear": ("unclear", "unclear"),
    }.get(uncertainty_scope, ("unclear", "unclear"))
    add(
        "standard_error",
        arm.get("se"),
        suffix="se",
        statistical_scope=statistical_scope,
        applies_to=applies_to,
    )
    lower = _optional_number(arm.get("ci_lower"))
    upper = _optional_number(arm.get("ci_upper"))
    if lower is not None and upper is not None:
        material = _normalize_material(
            raw={
                "kind": "confidence_interval",
                "value": None,
                "lower": lower,
                "upper": upper,
                "confidence_level": arm.get("ci_level"),
                "decimal_places": None,
                "statistical_scope": statistical_scope,
                "applies_to": applies_to,
                "source_quote": quote,
                "notes": None,
                "uncertainties": [],
            },
            arm_label=arm_label,
            local_setting=local_setting,
            table=table,
            material_key=f"block-{block_index}-arm-{arm_index}-ci",
        )
        if material is not None:
            materials.append(material)
    return materials


def _normalize_material(
    *,
    raw: Any,
    arm_label: str | None,
    local_setting: dict[str, Any],
    table: dict[str, Any],
    material_key: str,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "")
    if not kind:
        return None
    payload = {
        "kind": kind,
        "value": _optional_number(raw.get("value")),
        "lower": _optional_number(raw.get("lower")),
        "upper": _optional_number(raw.get("upper")),
        "confidence_level": _optional_number(raw.get("confidence_level")),
        "decimal_places": _optional_int(raw.get("decimal_places")),
        "statistical_scope": str(raw.get("statistical_scope") or "unclear"),
        "applies_to": str(raw.get("applies_to") or "unclear"),
        "arm_label": arm_label,
        "local_setting": deepcopy(local_setting),
        "source_table_id": str(table["table_id"]),
        "source_hash": str(table["source_hash"]),
        "source_quote": str(raw.get("source_quote") or "").strip(),
        "notes": _optional_text(raw.get("notes")),
        "uncertainties": _text_list(raw.get("uncertainties")),
        "trace_warnings": [],
    }
    if payload["source_quote"] and not _quote_matches_source(
        payload["source_quote"],
        _xml_text(str(table.get("raw_xml") or "")),
    ):
        payload["trace_warnings"] = ["source_quote_not_found_in_source_table"]
    if payload["source_quote"] and not _material_numbers_match_locator(payload):
        payload["uncertainties"] = _unique(
            [*payload["uncertainties"], "numeric_value_not_found_in_source_locator"]
        )
    identity = json.dumps(
        {"table": table["table_id"], "key": material_key, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "material_id": f"material::{_slug(str(table['table_id']))}::{sha256(identity.encode('utf-8')).hexdigest()[:14]}",
        **payload,
    }


def _reported_dichotomous_denominator_is_confirmed(arm: dict[str, Any]) -> bool:
    events = _optional_int(arm.get("events"))
    total = _optional_int(arm.get("total"))
    percentage = _optional_number(arm.get("percentage"))
    decimals = _optional_int(arm.get("percentage_decimal_places"))
    if (
        events is None
        or total is None
        or total <= 0
        or percentage is None
        or decimals is None
        or not 0 <= decimals <= 6
    ):
        return False
    tolerance = 0.5 * (10 ** (-decimals)) + 1e-12
    return abs((100.0 * events / total) - percentage) <= tolerance


def _material_numbers_match_locator(material: dict[str, Any]) -> bool:
    required = [
        value
        for field in ("value", "lower", "upper")
        if (value := _optional_number(material.get(field))) is not None
    ]
    if not required:
        return True
    quote = re.sub(
        r"\u2212\s*(?=\d)",
        "-",
        str(material.get("source_quote") or ""),
    )
    tokens: list[float] = []
    for token in re.findall(
        r"(?<![A-Za-z0-9.])[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?",
        quote,
    ):
        variants = {token.replace(",", "")}
        if token.count(",") == 1 and "." not in token:
            variants.add(token.replace(",", "."))
        for variant in variants:
            try:
                tokens.append(float(variant))
            except ValueError:
                continue
    return all(
        any(math.isclose(value, token, rel_tol=0.0, abs_tol=1e-12) for token in tokens)
        for value in required
    )


def _quote_matches_source(quote: str, raw_text: str) -> bool:
    normalized_source = _norm(raw_text)
    fragments = [
        _norm(_xml_text(fragment))
        for fragment in re.split(r"\s*(?:\.\.\.|…)\s*", quote)
    ]
    fragments = [fragment for fragment in fragments if fragment]
    return bool(fragments) and all(fragment in normalized_source for fragment in fragments)


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    data_type = str(candidate["data_type"])
    local_setting = candidate["local_setting"]
    return {
        "candidate_id": candidate["candidate_id"],
        "source_table_id": candidate["source_table_id"],
        "data_type": data_type,
        "local_setting": local_setting,
        "reported_statistic_type": local_setting.get("reported_statistic_type"),
        "analysis_input_representation": local_setting.get(
            "analysis_input_representation"
        ),
        "reported_statistic_kinds": local_setting.get("reported_statistic_kinds") or [],
        "statistic_type_status": local_setting.get("statistic_type_status"),
        "arms": [
            {
                "label": arm["label"],
                "available_fields": [field for field in _REQUIRED_FIELDS[data_type] if arm.get(field) is not None],
                "material_kinds": _unique(
                    [str(material.get("kind") or "") for material in arm.get("materials") or []]
                ),
            }
            for arm in candidate["arms"]
        ],
        "uncertainties": candidate["uncertainties"],
    }


def _support_material_summary(material: dict[str, Any]) -> dict[str, Any]:
    return {
        "material_id": material.get("material_id"),
        "kind": material.get("kind"),
        "arm_label": material.get("arm_label"),
        "local_setting": material.get("local_setting"),
        "statistical_scope": material.get("statistical_scope"),
        "applies_to": material.get("applies_to"),
        "source_table_id": material.get("source_table_id"),
        "uncertainties": material.get("uncertainties") or [],
    }


def _normalize_resolutions(
    value: dict[str, Any],
    *,
    target_ids: list[str],
    candidate_ids: set[str],
    support_material_ids: set[str],
    source_coverage_complete: bool,
) -> list[dict[str, Any]]:
    by_target: dict[str, dict[str, Any]] = {}
    for row in value.get("resolutions") or []:
        if not isinstance(row, dict):
            continue
        target_id = str(row.get("target_id") or "")
        if target_id not in target_ids or target_id in by_target:
            continue
        status = str(row.get("status") or "unresolved")
        selected = [candidate_id for candidate_id in _text_list(row.get("candidate_ids")) if candidate_id in candidate_ids]
        selected_support = [
            material_id
            for material_id in _text_list(row.get("support_material_ids"))
            if material_id in support_material_ids
        ]
        excluded = [candidate_id for candidate_id in _text_list(row.get("excluded_candidate_ids")) if candidate_id in candidate_ids]
        unresolved = [candidate_id for candidate_id in _text_list(row.get("unresolved_candidate_ids")) if candidate_id in candidate_ids]
        bindings = []
        for binding in row.get("field_bindings") or []:
            if not isinstance(binding, dict) or str(binding.get("candidate_id") or "") not in candidate_ids:
                continue
            bindings.append(
                {
                    "field": str(binding.get("field") or ""),
                    "candidate_id": str(binding.get("candidate_id") or ""),
                    "arm_label": str(binding.get("arm_label") or ""),
                }
            )
        if status == "data_unavailable" and not source_coverage_complete:
            status = "unresolved"
            unresolved = _unique([*unresolved, *selected])
        if status == "data_unavailable" and (selected or unresolved):
            status = "unresolved"
            unresolved = _unique([*unresolved, *selected])
        by_target[target_id] = {
            "target_id": target_id,
            "status": status,
            "operation": _optional_text(row.get("operation")),
            "candidate_ids": _unique(selected),
            "support_material_ids": _unique(selected_support),
            "experimental_arm_labels": _text_list(row.get("experimental_arm_labels")),
            "control_arm_labels": _text_list(row.get("control_arm_labels")),
            "field_bindings": bindings,
            "excluded_candidate_ids": _unique(excluded),
            "unresolved_candidate_ids": _unique(unresolved),
            "reason": str(row.get("reason") or ""),
        }
    return [
        by_target.get(
            target_id,
            _empty_resolution(
                target_id=target_id,
                status="unresolved",
                reason="Article resolver did not return a decision for this target.",
            ),
        )
        for target_id in target_ids
    ]


def _empty_resolution(*, target_id: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "status": status,
        "operation": "unresolved" if status == "unresolved" else "exclude",
        "candidate_ids": [],
        "support_material_ids": [],
        "experimental_arm_labels": [],
        "control_arm_labels": [],
        "field_bindings": [],
        "excluded_candidate_ids": [],
        "unresolved_candidate_ids": [],
        "reason": reason,
    }


def _assemble_resolution(
    *,
    study_id: str,
    target: dict[str, Any],
    study_map: dict[str, Any],
    resolution: dict[str, Any],
    candidate_by_id: dict[str, dict[str, Any]],
    support_materials: list[dict[str, Any]],
    study_year: str | None,
    allow_unoriented_post_intervention: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    if resolution.get("status") != "resolved":
        return None, None
    selected = [
        candidate_by_id[candidate_id]
        for candidate_id in resolution.get("candidate_ids") or []
        if candidate_id in candidate_by_id
    ]
    if not selected:
        return None, "Resolution selected no available candidate."
    data_type = str(target.get("data_type") or "")
    if any(str(row.get("data_type") or "") != data_type for row in selected):
        return None, "Resolution selected a candidate with the wrong data type."
    operation = str(resolution.get("operation") or "select_direct")
    support_by_id = {
        str(row["material_id"]): row
        for row in support_materials
        if row.get("material_id")
    }
    selected_support = [
        support_by_id[material_id]
        for material_id in _text_list(resolution.get("support_material_ids"))
        if material_id in support_by_id
    ]
    if len(selected) > 1 and operation not in {"cross_table_assembly", "deduplicate_same_result"}:
        return None, "Multiple source blocks require an explicit cross-table or duplicate operation."
    if operation == "cross_table_assembly":
        # A single result candidate plus typed supporting material (for
        # example, an outcome-complete denominator found in prose) is not a
        # merge of multiple result blocks.  Apply the strict identity gate to
        # multiple result candidates, while still keeping explicit conflict
        # checks for the selected candidate.  Requiring every identity field
        # for the candidate in this case incorrectly rejects otherwise
        # well-supported results when the article does not name an analysis
        # population.
        error = _cross_table_compatibility(
            selected,
            require_complete_identity=len(selected) > 1,
        )
        if error:
            return None, error
        if not resolution.get("field_bindings") and not selected_support:
            return None, "Cross-table assembly requires explicit field bindings or supporting materials."
    elif selected_support:
        return None, "Supporting materials may only be used by cross-table assembly."

    requested_experimental = _text_list(resolution.get("experimental_arm_labels"))
    requested_control = _text_list(resolution.get("control_arm_labels"))
    requested_experimental_ids = _text_list(
        resolution.get("experimental_arm_ids")
    )
    requested_control_ids = _text_list(resolution.get("control_arm_ids"))
    if not requested_experimental or not requested_control:
        return None, "Resolution must identify at least one experimental and one control arm."
    experimental_refs, error = _canonical_arm_refs(
        selected=selected,
        requested_labels=requested_experimental,
        requested_ids=requested_experimental_ids,
        study_map=study_map,
    )
    if error:
        return None, error
    control_refs, error = _canonical_arm_refs(
        selected=selected,
        requested_labels=requested_control,
        requested_ids=requested_control_ids,
        study_map=study_map,
    )
    if error:
        return None, error
    experimental_labels = [str(row["label"]) for row in experimental_refs]
    control_labels = [str(row["label"]) for row in control_refs]
    experimental_ids = {
        str(row.get("arm_id") or "") for row in experimental_refs if row.get("arm_id")
    }
    control_ids = {
        str(row.get("arm_id") or "") for row in control_refs if row.get("arm_id")
    }
    same_arm = bool(experimental_ids & control_ids)
    if not experimental_ids or not control_ids:
        same_arm = any(
            _labels_equivalent(experimental, control, study_map)
            for experimental in experimental_labels
            for control in control_labels
        )
    if same_arm:
        return None, "Experimental and control labels resolve to the same article arm."

    bindings = resolution.get("field_bindings") or []
    experimental, exp_provenance, error = _resolved_arms(
        selected=selected,
        arm_refs=experimental_refs,
        side="experimental",
        data_type=data_type,
        bindings=bindings,
        study_map=study_map,
        cross_table=operation == "cross_table_assembly",
        support_materials=selected_support,
    )
    if error:
        return None, error
    control, control_provenance, error = _resolved_arms(
        selected=selected,
        arm_refs=control_refs,
        side="control",
        data_type=data_type,
        bindings=bindings,
        study_map=study_map,
        cross_table=operation == "cross_table_assembly",
        support_materials=selected_support,
    )
    if error:
        return None, error

    try:
        if data_type == "Dichotomous":
            exp_data = _combine_dichotomous(experimental)
            control_data = _combine_dichotomous(control)
            result_data = {
                "experimental_events": exp_data["events"],
                "experimental_total": exp_data["total"],
                "control_events": control_data["events"],
                "control_total": control_data["total"],
            }
            alignment = None
        else:
            exp_data = _combine_continuous(experimental)
            control_data = _combine_continuous(control)
            result_data = {
                "experimental_mean": exp_data["mean"],
                "experimental_sd": exp_data["sd"],
                "experimental_total": exp_data["total"],
                "control_mean": control_data["mean"],
                "control_sd": control_data["sd"],
                "control_total": control_data["total"],
            }
            alignment = _continuous_alignment(selected[0]["local_setting"])
            if alignment["effect_multiplier"] not in {-1, 1}:
                if (
                    allow_unoriented_post_intervention
                    and alignment["result_frame"] == "post_intervention"
                    and alignment["change_score_definition"] == "not_applicable"
                ):
                    alignment = {
                        **alignment,
                        "scale_direction": "unclear",
                        "effect_multiplier": 1,
                        "status": "ready",
                        "clinical_direction_status": "unknown",
                        "rationale": (
                            "The post-intervention result is retained on its reported "
                            "experimental-minus-control measurement scale; the clinical "
                            "meaning of higher versus lower scores remains unknown."
                        ),
                    }
                else:
                    return None, "Continuous result lacks an interpretable scale/change direction."
    except ValueError as exc:
        return None, str(exc)

    target_id = str(target["target_id"])
    resolution_id = f"resolution::{target_id}::{_slug(study_id)}"
    candidate_ids = [str(row["candidate_id"]) for row in selected]
    provenance = {**exp_provenance, **control_provenance}
    source_spans = _unique_dicts(
        [
            *[span for row in selected for span in row.get("source_spans") or []],
            *[
                {
                    "source_id": material["source_table_id"],
                    "table_id": material["source_table_id"],
                    "text": material["source_quote"],
                }
                for material in selected_support
                if material.get("source_quote")
            ],
        ]
    )
    calculated = any(
        row.get("method") != "direct"
        for row in provenance.values()
        if isinstance(row, dict)
    )
    derived = (
        calculated
        or operation != "select_direct"
        or len(experimental) > 1
        or len(control) > 1
    )
    derivation = (
        {
            "method": operation,
            "computed_fields": list(result_data),
            "input_values": {"field_provenance": provenance},
            "formula": "; ".join(
                _unique(
                    [
                        str(row.get("formula"))
                        for row in provenance.values()
                        if isinstance(row, dict) and row.get("formula")
                    ]
                )
            )
            or "deterministic arm-level aggregation",
            "notes": "No LLM arithmetic was used.",
        }
        if derived
        else None
    )
    result_item = {
        "candidate_id": f"resolved::{_slug(target_id)}::{_slug(study_id)}",
        "source_candidate_ids": candidate_ids,
        "match_status": "matched",
        "study_result_setting": _external_setting(selected[0]["local_setting"], experimental_labels, control_labels),
        "data_type": data_type,
        "result_data": result_data,
        "include_in_estimate": True,
        "analysis_disposition": "ready_for_estimate",
        "resolution_reason": resolution_id,
        "resolution_operation": operation,
        "derivation": derivation,
        "source_spans": source_spans,
        "numeric_extraction": {"field_provenance": provenance},
        "continuous_effect_alignment": alignment,
    }
    return (
        {
            "data_row_id": f"data-row::{_slug(target_id)}::{_slug(study_id)}",
            "row_id": f"data-row::{_slug(target_id)}::{_slug(study_id)}",
            "setting_id": target_id,
            "setting_family_id": str(target.get("setting_family_id") or target_id),
            "study_id": study_id,
            "study_year": study_year,
            "data_type": data_type,
            "comparison": {
                "experimental_arm": " + ".join(experimental_labels),
                "control_arm": " + ".join(control_labels),
            },
            "outcome": {
                "label": str((target.get("outcome") or {}).get("label") or ""),
                "timepoint": _optional_text((target.get("timepoint") or {}).get("label")),
            },
            "subgroup": target.get("subgroup") or {"factor": None, "level": None},
            "result_data": result_data,
            "source_candidate_ids": candidate_ids,
            "resolution_id": resolution_id,
            "result_items": [result_item],
            "derivation": derivation,
            "continuous_effect_alignment": alignment,
            "source_spans": source_spans,
            "analysis_status": "pending",
        },
        None,
    )


def _resolved_arms(
    *,
    selected: list[dict[str, Any]],
    arm_refs: list[dict[str, str | None]],
    side: str,
    data_type: str,
    bindings: list[dict[str, Any]],
    study_map: dict[str, Any],
    cross_table: bool,
    support_materials: list[dict[str, Any]],
) -> tuple[list[dict[str, float]], dict[str, Any], str | None]:
    result: list[dict[str, float]] = []
    provenance: dict[str, Any] = {}
    for arm_ref in arm_refs:
        label = str(arm_ref["label"])
        arm_id = str(arm_ref.get("arm_id") or "")
        matching = [
            (candidate, arm)
            for candidate in selected
            for arm in candidate.get("arms") or []
            if (
                str(arm.get("article_arm_id") or "") == arm_id
                if arm_id
                else _labels_equivalent(
                    label, str(arm.get("label") or ""), study_map
                )
            )
        ]
        if not matching:
            return [], {}, f"No source arm identifies '{label}'."

        materials: list[dict[str, Any]] = []
        material_by_id: dict[str, dict[str, Any]] = {}
        for candidate, arm in matching:
            for material in _candidate_arm_materials(candidate=candidate, arm=arm):
                local_field = _material_output_field(str(material.get("kind") or ""))
                if local_field is not None:
                    canonical = _canonical_field(side=side, local_field=local_field)
                    bound = _binding_for(
                        bindings,
                        field=canonical,
                        arm_label=label,
                        arm_id=arm_id or None,
                        study_map=study_map,
                    )
                    if bound is not None and candidate["candidate_id"] != bound["candidate_id"]:
                        continue
                owned = {
                    **deepcopy(material),
                    "candidate_id": candidate["candidate_id"],
                    "source_arm_label": arm.get("label"),
                }
                materials.append(owned)
                if owned.get("material_id"):
                    material_by_id[str(owned["material_id"])] = owned

        if cross_table and support_materials:
            prepared, support_index = _compatible_support_materials(
                support_materials=support_materials,
                arm_id=arm_id or None,
                arm_label=label,
                side=side,
                candidate_setting=selected[0]["local_setting"],
                study_map=study_map,
            )
            materials.extend(prepared)
            material_by_id.update(support_index)

        calculation = solve_arm(data_type=data_type, materials=materials)
        missing = [
            field for field in _REQUIRED_FIELDS[data_type]
            if calculation.values.get(field) is None
        ]
        if missing:
            warning_text = ", ".join(calculation.warnings) or "no compatible material"
            canonical_missing = ", ".join(
                _canonical_field(side=side, local_field=field) for field in missing
            )
            return [], {}, f"Missing {canonical_missing} for arm '{label}' ({warning_text})."
        values = {
            field: float(calculation.values[field])
            for field in _REQUIRED_FIELDS[data_type]
        }
        result.append(values)
        for local_field, trace in calculation.field_traces.items():
            canonical = _canonical_field(side=side, local_field=local_field)
            provenance[f"{canonical}::{label}"] = _field_provenance(
                trace=trace,
                material_by_id=material_by_id,
                arm_label=label,
            )
    return result, provenance, None


def _candidate_arm_materials(
    *,
    candidate: dict[str, Any],
    arm: dict[str, Any],
) -> list[dict[str, Any]]:
    existing = [deepcopy(row) for row in arm.get("materials") or [] if isinstance(row, dict)]
    if existing:
        return existing
    kind_by_field = {
        "events": "event_count",
        "total": "result_denominator",
        "mean": "mean",
        "sd": "standard_deviation",
    }
    result = []
    for field, kind in kind_by_field.items():
        value = _optional_number(arm.get(field))
        if value is None:
            continue
        result.append(
            {
                "material_id": f"legacy::{candidate['candidate_id']}::{_slug(str(arm.get('label') or 'arm'))}::{kind}",
                "kind": kind,
                "value": value,
                "lower": None,
                "upper": None,
                "confidence_level": None,
                "decimal_places": None,
                "statistical_scope": "arm",
                "applies_to": "event_risk" if kind in {"event_count", "analyzed_total", "result_denominator"} else "mean",
                "arm_label": arm.get("label"),
                "local_setting": deepcopy(candidate.get("local_setting") or {}),
                "source_table_id": candidate.get("source_table_id"),
                "source_hash": candidate.get("source_hash"),
                "source_quote": arm.get("source_quote") or "",
                "notes": None,
                "uncertainties": [],
            }
        )
    return result


def _material_output_field(kind: str) -> str | None:
    if kind in {"event_count", "non_event_count", "percentage"}:
        return "events"
    if kind in {
        "analyzed_total",
        "result_denominator",
        "randomized_total",
        "baseline_total",
        "outcome_complete_count",
        "attrition_count",
    }:
        return "total"
    if kind == "mean":
        return "mean"
    if kind in {"standard_deviation", "variance", "standard_error", "confidence_interval"}:
        return "sd"
    return None


def _compatible_support_materials(
    *,
    support_materials: list[dict[str, Any]],
    arm_id: str | None,
    arm_label: str,
    side: str,
    candidate_setting: dict[str, Any],
    study_map: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    arm_materials = [
        deepcopy(material)
        for material in support_materials
        if (
            str(material.get("article_arm_id") or "") == arm_id
            if arm_id and material.get("article_arm_id")
            else _labels_equivalent(
                arm_label,
                str(material.get("arm_label") or ""),
                study_map,
            )
        )
    ]
    material_by_id = {
        str(material["material_id"]): material
        for material in arm_materials
        if material.get("material_id")
    }
    usable: list[dict[str, Any]] = []
    zero_attrition: list[dict[str, Any]] = []
    enrollment: list[dict[str, Any]] = []
    for material in arm_materials:
        kind = str(material.get("kind") or "")
        verified_field = str(material.get("verified_field") or "")
        expected_prefix = "experimental_" if side == "experimental" else "control_"
        if verified_field and not verified_field.startswith(expected_prefix):
            continue
        # Source-workspace materials carrying verified_field have already passed
        # source-local validation and target-level cross-source adjudication.
        # Requiring exact non-empty legacy setting strings here would overturn
        # that semantic decision when a table omits (for example) a timepoint.
        scope_compatible = bool(verified_field) or _outcome_scope_compatible(
            material.get("local_setting") or {}, candidate_setting
        )
        if kind in {
            "event_count",
            "non_event_count",
            "percentage",
            "mean",
            "standard_deviation",
            "variance",
            "standard_error",
            "confidence_interval",
            "analyzed_total",
            "result_denominator",
        } and scope_compatible:
            usable.append(material)
        elif kind == "outcome_complete_count" and scope_compatible:
            usable.append(
                _promoted_analyzed_total(
                    source=material,
                    inputs=[material],
                    formula="analyzed_total = outcome_complete_count",
                    assumptions=["completion_count_is_for_the_same_arm_outcome_and_timepoint"],
                )
            )
        elif kind == "attrition_count" and scope_compatible and _optional_number(
            material.get("value")
        ) == 0:
            zero_attrition.append(material)
        elif kind in {"randomized_total", "baseline_total"}:
            enrollment.append(material)

    if zero_attrition:
        for material in enrollment:
            usable.append(
                _promoted_analyzed_total(
                    source=material,
                    inputs=[material, *zero_attrition],
                    formula="analyzed_total = enrollment_total when compatible outcome attrition is zero",
                    assumptions=[
                        "zero_attrition_is_for_the_same_arm_outcome_and_timepoint",
                        "no_other_outcome_specific_exclusions_are_reported",
                    ],
                )
            )
    for material in usable:
        if material.get("material_id"):
            material_by_id[str(material["material_id"])] = material
    return usable, material_by_id


def _outcome_scope_compatible(
    material_setting: dict[str, Any],
    candidate_setting: dict[str, Any],
) -> bool:
    for field in ("outcome_label", "timepoint"):
        left = _norm(str(material_setting.get(field) or ""))
        right = _norm(str(candidate_setting.get(field) or ""))
        if not left or not right or left != right:
            return False
    for field in (
        "outcome_measure",
        "population_or_subgroup",
        "analysis_population",
    ):
        left = _norm(str(material_setting.get(field) or ""))
        right = _norm(str(candidate_setting.get(field) or ""))
        if left and right and left != right:
            return False
    return True


def _promoted_analyzed_total(
    *,
    source: dict[str, Any],
    inputs: list[dict[str, Any]],
    formula: str,
    assumptions: list[str],
) -> dict[str, Any]:
    input_ids = [str(row["material_id"]) for row in inputs if row.get("material_id")]
    identity = json.dumps({"formula": formula, "inputs": input_ids}, sort_keys=True)
    return {
        **deepcopy(source),
        "material_id": f"derived-material::{sha256(identity.encode('utf-8')).hexdigest()[:14]}",
        "kind": "analyzed_total",
        "derivation_trace": {
            "method": "calculated",
            "formula": formula,
            "input_material_ids": input_ids,
            "assumptions": assumptions,
        },
    }


def _field_provenance(
    *,
    trace: dict[str, Any],
    material_by_id: dict[str, dict[str, Any]],
    arm_label: str,
) -> dict[str, Any]:
    material_ids = _text_list(trace.get("input_material_ids"))
    sources = [material_by_id[material_id] for material_id in material_ids if material_id in material_by_id]
    table_ids = _unique([str(row.get("source_table_id") or "") for row in sources])
    candidate_ids = _unique([str(row.get("candidate_id") or "") for row in sources])
    result = {
        "calculator_version": trace.get("calculator_version"),
        "method": str(trace.get("method") or "direct"),
        "formula": trace.get("formula"),
        "assumptions": _text_list(trace.get("assumptions")),
        "material_ids": material_ids,
        "table_ids": table_ids,
        "candidate_ids": candidate_ids,
        "arm_label": arm_label,
    }
    if len(table_ids) == 1:
        result["table_id"] = table_ids[0]
    if len(candidate_ids) == 1:
        result["candidate_id"] = candidate_ids[0]
    return result


def _canonical_arm_labels(
    *,
    selected: list[dict[str, Any]],
    requested_labels: list[str],
    study_map: dict[str, Any],
) -> tuple[list[str], str | None]:
    source_labels = _unique(
        [
            str(arm.get("label") or "")
            for candidate in selected
            for arm in candidate.get("arms") or []
            if str(arm.get("label") or "").strip()
        ]
    )
    canonical: list[str] = []
    for requested in requested_labels:
        matches = [
            label
            for label in source_labels
            if _labels_equivalent(requested, label, study_map)
        ]
        if not matches:
            return [], f"Arm label '{requested}' does not identify a selected source arm."
        first = matches[0]
        if any(not _labels_equivalent(first, other, study_map) for other in matches[1:]):
            return [], f"Arm label '{requested}' maps to multiple distinct source arms."
        exact = next((label for label in matches if _norm(label) == _norm(requested)), None)
        representative = exact or first
        if any(
            _labels_equivalent(representative, existing, study_map)
            for existing in canonical
        ):
            continue
        canonical.append(representative)
    return canonical, None


def _canonical_arm_refs(
    *,
    selected: list[dict[str, Any]],
    requested_labels: list[str],
    requested_ids: list[str],
    study_map: dict[str, Any],
) -> tuple[list[dict[str, str | None]], str | None]:
    """Resolve source arms by stable identity when the caller provides it.

    The label-only path remains for the archived article-evidence method.  The
    production source-workspace method supplies IDs, so shared role words or
    overlapping label variants cannot merge distinct randomized arms here.
    """

    if not requested_ids:
        labels, error = _canonical_arm_labels(
            selected=selected,
            requested_labels=requested_labels,
            study_map=study_map,
        )
        return ([{"arm_id": None, "label": label} for label in labels], error)

    refs: list[dict[str, str | None]] = []
    for arm_id in requested_ids:
        source_arms = [
            arm
            for candidate in selected
            for arm in candidate.get("arms") or []
            if str(arm.get("article_arm_id") or "") == arm_id
        ]
        if not source_arms:
            return [], f"Article arm id '{arm_id}' does not identify a selected source arm."
        map_labels = [
            str(arm.get("label") or "")
            for arm in study_map.get("arms") or []
            if isinstance(arm, dict) and str(arm.get("arm_id") or "") == arm_id
        ]
        if len(map_labels) != 1:
            return [], f"Article arm id '{arm_id}' is absent or duplicated in the study map."
        refs.append({"arm_id": arm_id, "label": map_labels[0]})
    return refs, None


def _candidate_with_value(
    candidates: list[dict[str, Any]],
    *,
    label: str,
    field: str,
    study_map: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    matches = []
    for candidate in candidates:
        for arm in candidate.get("arms") or []:
            if _labels_equivalent(label, str(arm.get("label") or ""), study_map) and arm.get(field) is not None:
                matches.append((candidate, arm))
    if len(matches) != 1:
        return None
    return matches[0]


def _binding_for(
    bindings: list[dict[str, Any]],
    *,
    field: str,
    arm_label: str,
    arm_id: str | None = None,
    study_map: dict[str, Any],
) -> dict[str, Any] | None:
    matches = [
        row
        for row in bindings
        if str(row.get("field") or "") == field
        and (
            str(row.get("arm_id") or "") == arm_id
            if arm_id
            else _labels_equivalent(
                arm_label, str(row.get("arm_label") or ""), study_map
            )
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _cross_table_compatibility(
    candidates: list[dict[str, Any]],
    *,
    require_complete_identity: bool = True,
) -> str | None:
    if require_complete_identity:
        for field in _CROSS_TABLE_REQUIRED_IDENTITY_FIELDS:
            if any(
                not _norm(_candidate_identity_value(row, field)) for row in candidates
            ):
                return (
                    "Cross-table assembly lacks explicit "
                    f"{field} identity in every source block."
                )
    compatibility_fields = _LOCAL_COMPATIBILITY_FIELDS
    if str(candidates[0].get("data_type") or "") == "Dichotomous":
        compatibility_fields = tuple(
            field
            for field in compatibility_fields
            if field not in {"unit", "continuous_result_frame", "change_score_definition", "scale_direction"}
        )
    for field in compatibility_fields:
        values = {
            _norm(_candidate_identity_value(row, field)) for row in candidates
        }
        values.discard("")
        if len(values) > 1:
            return f"Cross-table assembly has conflicting {field} values."
    material_kinds = {
        str(material.get("kind") or "")
        for candidate in candidates
        for arm in candidate.get("arms") or []
        for material in arm.get("materials") or []
    }
    if material_kinds & {"randomized_total", "baseline_total"}:
        return "Cross-table assembly cannot use baseline/randomized enrollment as an analyzed outcome denominator."
    return None


def _candidate_identity_value(candidate: dict[str, Any], field: str) -> str:
    local_setting = candidate.get("local_setting") or {}
    value = local_setting.get(field)
    if field != "analysis_input_representation":
        return str(value or "")
    explicit = _optional_text(value)
    if explicit:
        return explicit
    declared_family = _declared_statistic_family(
        _optional_text(local_setting.get("statistic_type"))
    )
    return {
        "dichotomous_arm": "dichotomous_arm_events_total",
        "continuous_arm": "continuous_arm_mean_sd_total",
    }.get(declared_family, "")


def _combine_dichotomous(arms: list[dict[str, float]]) -> dict[str, int]:
    events = sum(_integer(row["events"], name="events") for row in arms)
    total = sum(_integer(row["total"], name="total") for row in arms)
    if total <= 0 or events < 0 or events > total:
        raise ValueError("Invalid dichotomous event/total values after arm aggregation.")
    return {"events": events, "total": total}


def _combine_continuous(arms: list[dict[str, float]]) -> dict[str, float | int]:
    totals = [_integer(row["total"], name="total") for row in arms]
    if any(total <= 1 for total in totals):
        raise ValueError("Continuous arm totals must be greater than one.")
    means = [float(row["mean"]) for row in arms]
    sds = [float(row["sd"]) for row in arms]
    if any(not math.isfinite(value) for value in [*means, *sds]) or any(sd < 0 for sd in sds):
        raise ValueError("Continuous means/SDs must be finite and SDs non-negative.")
    total = sum(totals)
    mean = sum(n * value for n, value in zip(totals, means, strict=True)) / total
    if len(arms) == 1:
        sd = sds[0]
    else:
        numerator = sum(
            (n - 1) * sd * sd + n * (value - mean) ** 2
            for n, value, sd in zip(totals, means, sds, strict=True)
        )
        sd = math.sqrt(numerator / (total - 1))
    return {"mean": mean, "sd": sd, "total": total}


def _continuous_alignment(setting: dict[str, Any]) -> dict[str, Any]:
    frame = _norm(str(setting.get("continuous_result_frame") or ""))
    if frame in {"final", "final value", "post intervention", "post-intervention", "endpoint"}:
        normalized_frame = "post_intervention"
    elif "change" in frame:
        normalized_frame = "change_from_baseline"
    else:
        normalized_frame = "unclear"
    explicit_change_direction = str(
        setting.get("change_score_direction") or ""
    )
    change = _norm(str(setting.get("change_score_definition") or ""))
    if explicit_change_direction in {
        "post_minus_baseline",
        "baseline_minus_post",
        "not_applicable",
        "unclear",
    }:
        change_definition = explicit_change_direction
    elif "post" in change and "baseline" in change and change.index("post") < change.index("baseline"):
        change_definition = "post_minus_baseline"
    elif "baseline" in change and "post" in change and change.index("baseline") < change.index("post"):
        change_definition = "baseline_minus_post"
    else:
        change_definition = "not_applicable" if normalized_frame == "post_intervention" else "unclear"
    direction = str(setting.get("scale_direction") or "unclear")
    multiplier: int | None = None
    if direction in {"higher_is_better", "higher_is_worse"}:
        multiplier = 1 if direction == "higher_is_better" else -1
        if normalized_frame == "change_from_baseline" and change_definition == "baseline_minus_post":
            multiplier *= -1
        if normalized_frame == "change_from_baseline" and change_definition == "unclear":
            multiplier = None
    if normalized_frame == "unclear":
        multiplier = None
    return {
        "result_frame": normalized_frame,
        "change_score_definition": change_definition,
        "scale_direction": direction,
        "effect_multiplier": multiplier,
        "status": "ready" if multiplier in {-1, 1} else "uncertain",
        "rationale": "Direction is derived from the source-local scale and change-score definitions.",
    }


def _study_result_row(
    *,
    study_id: str,
    study_year: str | None,
    target: dict[str, Any],
    candidates: list[dict[str, Any]],
    resolution: dict[str, Any],
    source_coverage_complete: bool,
) -> dict[str, Any]:
    target_id = str(target["target_id"])
    selected = set(_text_list(resolution.get("candidate_ids")))
    excluded = set(_text_list(resolution.get("excluded_candidate_ids")))
    unresolved = set(_text_list(resolution.get("unresolved_candidate_ids")))
    items = []
    for candidate in candidates:
        if candidate["data_type"] != target["data_type"]:
            continue
        candidate_id = str(candidate["candidate_id"])
        disposition = (
            "selected_for_resolution"
            if candidate_id in selected
            else "excluded"
            if candidate_id in excluded
            else "unresolved"
            if candidate_id in unresolved
            else "available"
        )
        items.append(
            {
                "candidate_id": candidate_id,
                "match_status": "matched" if candidate_id in selected else "possible",
                "study_result_setting": _external_setting(candidate["local_setting"], [], []),
                "data_type": candidate["data_type"],
                "result_data": None,
                "include_in_estimate": None,
                "analysis_disposition": disposition,
                "resolution_reason": resolution.get("reason"),
                "source_spans": candidate["source_spans"],
                "confidence": "uncertain" if candidate["uncertainties"] else "source_grounded",
                "study_local_note": "; ".join(candidate["uncertainties"]) or None,
                "study_local_result": {
                    "source_table_id": candidate["source_table_id"],
                    "arms": candidate["arms"],
                },
                "numeric_extraction": {"arms": candidate["arms"]},
            }
        )
    status = "extracted" if resolution["status"] == "resolved" else resolution["status"]
    if not source_coverage_complete and status == "data_unavailable":
        status = "unresolved"
    return {
        "row_id": f"study-result::{_slug(target_id)}::{_slug(study_id)}",
        "setting_id": target_id,
        "study_id": study_id,
        "study_year": study_year,
        "extraction_status": status,
        "data_type": target["data_type"],
        "comparison": {
            "experimental_arm": str((target.get("comparison") or {}).get("experimental") or ""),
            "control_arm": str((target.get("comparison") or {}).get("comparator") or ""),
        },
        "outcome": {
            "label": str((target.get("outcome") or {}).get("label") or ""),
            "timepoint": _optional_text((target.get("timepoint") or {}).get("label")),
        },
        "subgroup": target.get("subgroup") or {"factor": None, "level": None},
        "missing_reason": None if resolution["status"] == "resolved" else resolution["status"],
        "result_items": items,
        "candidate_results": items,
        "study_result_note": resolution.get("reason"),
        "extraction_status_reason": None if source_coverage_complete else "incomplete_source_coverage",
        "notes": "",
    }


def _resolution_record(
    *,
    study_id: str,
    target: dict[str, Any],
    resolution: dict[str, Any],
    candidate_by_id: dict[str, dict[str, Any]],
    assembled: dict[str, Any] | None,
) -> dict[str, Any]:
    target_id = str(target["target_id"])
    candidate_ids = _text_list(resolution.get("candidate_ids"))
    spans = _unique_dicts(
        [
            span
            for candidate_id in candidate_ids
            for span in (candidate_by_id.get(candidate_id) or {}).get("source_spans") or []
        ]
        + (assembled.get("source_spans") or [] if assembled else [])
    )
    return {
        "resolution_id": f"resolution::{target_id}::{_slug(study_id)}",
        "target_id": target_id,
        "study_id": study_id,
        "status": resolution["status"],
        "operation": resolution.get("operation"),
        "contributing_candidate_ids": candidate_ids if assembled is not None else [],
        "unresolved_candidate_ids": _text_list(resolution.get("unresolved_candidate_ids")),
        "applied_rule_ids": [POLICY_VERSION],
        "excluded_candidate_ids": _text_list(resolution.get("excluded_candidate_ids")),
        "reason": str(resolution.get("reason") or ""),
        "dependency_group_id": f"dependency::{target_id}::{_slug(study_id)}",
        "source_spans": spans,
        "candidate_dispositions": [
            {
                "candidate_id": candidate_id,
                "disposition": "selected" if candidate_id in candidate_ids else "not_selected",
            }
            for candidate_id in candidate_by_id
        ],
        "derivation": assembled.get("derivation") if assembled else None,
    }


def _external_setting(
    local: dict[str, Any],
    experimental_labels: list[str],
    control_labels: list[str],
) -> dict[str, Any]:
    return {
        "row_label": None,
        "outcome_label": local.get("outcome_label"),
        "outcome_measure": local.get("outcome_measure"),
        "timepoint": local.get("timepoint"),
        "statistic_type": local.get("statistic_type"),
        "reported_statistic_type": local.get("reported_statistic_type"),
        "analysis_input_representation": local.get(
            "analysis_input_representation"
        ),
        "reported_statistic_kinds": local.get("reported_statistic_kinds") or [],
        "statistic_type_status": local.get("statistic_type_status"),
        "population_or_subgroup": local.get("population_or_subgroup"),
        "analysis_population": local.get("analysis_population"),
        "experimental_arm_label": " + ".join(experimental_labels) or None,
        "control_arm_label": " + ".join(control_labels) or None,
        "continuous_result_frame": local.get("continuous_result_frame"),
        "change_score_definition": local.get("change_score_definition"),
        "table_local_notes": local.get("table_local_notes"),
    }


def _semantic_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": target.get("target_id"),
        "population_scope": target.get("population_scope"),
        "comparison": target.get("comparison"),
        "outcome": target.get("outcome"),
        "timepoint": target.get("timepoint"),
        "subgroup": target.get("subgroup"),
        "data_type": target.get("data_type"),
        "result_selection_policy": target.get("result_selection_policy"),
        "effect_measure_plan": target.get("effect_measure_plan"),
    }


def _table_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": target.get("target_id"),
        "comparison": target.get("comparison"),
        "outcome": target.get("outcome"),
        "timepoint": target.get("timepoint"),
        "subgroup": target.get("subgroup"),
        "data_type": target.get("data_type"),
    }


def _table_result_summary(table_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_id": table_id,
        "source_status": result.get("source_status"),
        "source_summary": result.get("source_summary"),
        "candidates": [_candidate_summary(row) for row in result.get("candidates") or []],
        "support_materials": [
            _support_material_summary(row)
            for row in result.get("support_materials") or []
        ],
    }


def _needs_first_support_table_search(state: dict[str, Any]) -> bool:
    results = [
        result
        for result in (state.get("table_results") or {}).values()
        if isinstance(result, dict)
    ]
    if any(result.get("support_materials") for result in results):
        return False
    for result in results:
        for candidate in result.get("candidates") or []:
            data_type = str(candidate.get("data_type") or "")
            required = _REQUIRED_FIELDS.get(data_type, ())
            for arm in candidate.get("arms") or []:
                if any(arm.get(field) is None for field in required):
                    return True
    return False


def _source_coverage_complete(
    *,
    tables: list[dict[str, Any]],
    state: dict[str, Any],
    max_table_reads: int,
) -> bool:
    unread = [row for row in tables if row["table_id"] not in state["table_results"]]
    if not unread:
        return True
    if _needs_first_support_table_search(state):
        return False
    if len(state["table_results"]) >= max_table_reads:
        return False
    # The controller may stop after documenting why unread tables are irrelevant.
    last = state["controller_turns"][-1] if state["controller_turns"] else {}
    return last.get("action") == "ready" and bool(str(last.get("reason") or "").strip())


def _coverage(
    *,
    study_id: str,
    targets: list[dict[str, Any]],
    status: str,
    read_section_ids: list[str] | None = None,
    read_table_ids: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "study_id": study_id,
        "expected_target_ids": [str(row.get("target_id") or "") for row in targets],
        "status": status,
        "read_section_ids": read_section_ids or [],
        "read_table_ids": read_table_ids or [],
        "warnings": warnings or [],
    }


def _labels_equivalent(first: str, second: str, study_map: dict[str, Any]) -> bool:
    first_keys = _label_variants(first)
    second_keys = _label_variants(second)
    if first_keys & second_keys:
        return True
    for arm in study_map.get("arms") or []:
        if not isinstance(arm, dict):
            continue
        labels = set().union(
            _label_variants(str(arm.get("label") or "")),
            *(_label_variants(row) for row in _text_list(arm.get("aliases"))),
        )
        if first_keys & labels and second_keys & labels:
            return True
    return False


def _label_variants(value: str) -> set[str]:
    variants = {_norm(value), _norm(re.sub(r"\([^)]*\)", " ", value))}
    variants.update(_norm(match) for match in re.findall(r"\(([^)]*)\)", value))
    return {variant for variant in variants if variant}


def _canonical_field(*, side: str, local_field: str) -> str:
    return f"{side}_{local_field}"


def _integer(value: Any, *, name: str) -> int:
    number = float(value)
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{name} must be a finite integer")
    return int(number)


def _optional_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: Any) -> int | None:
    number = _optional_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _study_year(article: dict[str, Any]) -> str | None:
    metadata = article.get("metadata") if isinstance(article.get("metadata"), dict) else {}
    return _optional_text(metadata.get("publication_year"))


def _table_order(tables: list[dict[str, Any]]) -> list[str]:
    return [str(row["table_id"]) for row in tables]


def _xml_text(raw_xml: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", raw_xml))


def _norm(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return normalized[:100] or "item"


def _optional_text(value: Any) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _optional_text(item))]


def _unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _unique_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _unique_materials(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for value in values:
        key = json.dumps(
            {
                field: value.get(field)
                for field in (
                    "kind",
                    "value",
                    "lower",
                    "upper",
                    "confidence_level",
                    "statistical_scope",
                    "applies_to",
                    "arm_label",
                    "local_setting",
                    "source_table_id",
                    "source_quote",
                )
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _debug_dir(context_id: str) -> Path | None:
    root = os.environ.get("META_STUDY_EVIDENCE_DEBUG_DIR") or os.environ.get("SUBTASK2_TARGETED_DEBUG_DIR")
    if not root:
        return None
    return Path(root) / _slug(context_id)


def _write_artifact(root: Path | None, name: str, payload: Any) -> None:
    if root is None:
        return
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
