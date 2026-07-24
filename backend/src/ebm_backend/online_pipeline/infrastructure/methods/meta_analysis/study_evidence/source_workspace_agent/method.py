"""Bounded source-workspace Evidence Agent for Meta-analysis Study Evidence."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Lock
import time
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
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent import (
    method as stable_core,
)

from .deterministic_bridge import POLICY_VERSION, build_result
from .context import (
    CallAliases,
    compile_adjudication_context,
    compile_arm_context,
    compile_census_context,
    compile_investigation_context,
    compile_resolution_context,
    compile_source_verification_context,
    request_input_summary,
)
from .evidence_state import (
    apply_arm_reconciliation,
    arm_observations,
    article_arm_ids,
    candidate_summary,
    decision_required_evidence_locators,
    decision_required_source_refs,
    decision_optional_source_refs,
    decision_evidence_locators,
    decision_source_refs,
    default_section_queries,
    empty_notebook,
    _available_source_refs,
    material_index,
    material_summary,
    merge_census_observations,
    merge_investigator_update,
    normalize_census_response,
    normalize_arm_reconciliation_response,
    normalize_cross_source_adjudication_response,
    normalize_investigator_response,
    normalize_resolution_response,
    normalize_source_verification_response,
    normalize_verification_response,
    semantic_notebook,
    semantic_target,
    unique_dicts,
    unique_text,
)
from .schemas import (
    arm_reconciliation_schema,
    cross_source_adjudication_schema,
    investigator_schema,
    resolution_schema,
    source_verification_schema,
    table_census_schema,
    verification_schema,
)
from .source_workspace import SourceWindow, SourceWorkspace
from .working_state import active_evidence_needs, working_state_snapshot


LLMJsonCaller = Callable[..., dict[str, Any]]
METHOD_VERSION = "source_workspace_agent_v16_direction_adjudication"
SCHEMA_VERSION = "source_workspace_agent_v16_direction_adjudication"
MAX_TABLES = 32
MAX_TABLE_WINDOWS = 32
# Raw tables are independent semantic and failure domains.  A census request may
# contain multiple windows only when they belong to the same raw table; windows
# from different tables must never share one provider request.
MAX_TABLES_PER_BUNDLE = 1
MAX_TABLE_BUNDLE_CHARS = 60_000
MAX_SOURCE_WINDOW_CHARS = 48_000
MAX_TABLE_WORKERS = 4
DEFAULT_LLM_TIMEOUT_SECONDS = 300.0
MAX_INVESTIGATION_ROUNDS = 2
MAX_SECTION_SEARCHES = 6
MAX_SECTION_READ_WINDOWS = 8
MAX_BOOTSTRAP_SECTION_SEARCHES = 3
MAX_BOOTSTRAP_SECTION_READ_WINDOWS = 4
MAX_SECTION_CONTEXT_CHARS = 160_000
MAX_VERIFICATION_SOURCE_REFS = 8
MAX_CONTEXT_SOURCE_CHARS = 48_000
MAX_VERIFICATION_CONTEXT_CHARS = 160_000
MAX_VERIFICATION_WINDOWS = 24
MAX_SCOPE_AUDIT_CONTEXT_CHARS = 160_000
MAX_SCOPE_AUDIT_WINDOWS = 24
MAX_SCOPE_AUDIT_ROUNDS = 1
MAX_CANDIDATES_PER_ARTICLE = 96
MAX_SUPPORT_MATERIALS_PER_ARTICLE = 192
MAX_TARGETS_PER_ARTICLE = 12
MAX_LLM_STAGE_CALLS_PER_ARTICLE = (
    MAX_TABLE_WINDOWS  # char limits can make every census window its own bundle
    + MAX_INVESTIGATION_ROUNDS
    + 1  # article-arm reconciliation
    + 1  # result-blind resolution
    + (MAX_TARGETS_PER_ARTICLE * MAX_VERIFICATION_SOURCE_REFS)
    + MAX_TARGETS_PER_ARTICLE  # cross-source adjudication groups
)
MAX_PROVIDER_ATTEMPTS_PER_ARTICLE = MAX_LLM_STAGE_CALLS_PER_ARTICLE * 2


class Method:
    """Investigate one article while code owns budgets, state and arithmetic."""

    def __init__(
        self,
        *,
        config: LLMConfig | dict[str, Any] | None = None,
        llm_caller: LLMJsonCaller = call_llm_json,
        prompt_dir: Path = Path(__file__).resolve().parent / "prompts",
        max_table_workers: int = MAX_TABLE_WORKERS,
        max_investigation_rounds: int = MAX_INVESTIGATION_ROUNDS,
        max_section_searches: int = MAX_SECTION_SEARCHES,
        max_section_read_windows: int = MAX_SECTION_READ_WINDOWS,
        llm_timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        cache_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.llm_caller = llm_caller
        self.prompt_dir = prompt_dir
        self.max_table_workers = min(MAX_TABLE_WORKERS, max(1, max_table_workers))
        self.max_investigation_rounds = min(
            MAX_INVESTIGATION_ROUNDS, max(1, max_investigation_rounds)
        )
        self.max_section_searches = min(
            MAX_SECTION_SEARCHES, max(1, max_section_searches)
        )
        self.max_section_read_windows = min(
            MAX_SECTION_READ_WINDOWS, max(1, max_section_read_windows)
        )
        self.llm_timeout_seconds = float(llm_timeout_seconds)
        if self.llm_timeout_seconds <= 0:
            raise ValueError("llm_timeout_seconds must be greater than zero")
        configured_cache = os.getenv("EBM_META_SOURCE_WORKSPACE_CACHE_DIR")
        self.cache_dir = cache_dir or (Path(configured_cache) if configured_cache else None)
        self._artifact_lock = Lock()

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
        normalized_targets = stable_core._validate_targets(targets)
        if len(normalized_targets) > MAX_TARGETS_PER_ARTICLE:
            raise ValueError(
                "Source-workspace Study Evidence supports at most "
                f"{MAX_TARGETS_PER_ARTICLE} frozen targets per article"
            )
        if not normalized_targets:
            return {
                "study_id": study_id,
                "study_result_rows": [],
                "resolution_records": [],
                "data_rows": [],
                "coverage": _coverage(
                    study_id=study_id,
                    targets=[],
                    workspace=None,
                    notebook=None,
                    status="complete",
                    omitted_table_refs=[],
                    partial_table_refs=[],
                    empty_table_refs=[],
                    investigation_finished=True,
                ),
            }

        workspace = SourceWorkspace.from_article(study_id=study_id, article=article)
        context_id = f"{METHOD_VERSION}::{review_id}::{study_id}"
        debug_dir = stable_core._debug_dir(context_id)
        notebook = empty_notebook(workspace=workspace)
        call_trace: list[dict[str, Any]] = []
        stable_core._write_artifact(
            debug_dir,
            "input.json",
            {
                "review_id": review_id,
                "study_id": study_id,
                "plan_hash": plan_hash,
                "targets": normalized_targets,
                "source_manifest": workspace.manifest(),
                "method_version": METHOD_VERSION,
                "schema_version": SCHEMA_VERSION,
                "limits": self._limits(config=config),
            },
        )

        all_table_windows, omitted_table_refs = workspace.table_windows(
            max_window_chars=MAX_SOURCE_WINDOW_CHARS,
            max_tables=MAX_TABLES,
        )
        table_windows, partial_table_refs = _bounded_table_windows(
            all_table_windows,
            max_windows=MAX_TABLE_WINDOWS,
        )
        if partial_table_refs:
            notebook["warnings"].append("table_window_cap_exceeded")
        empty_table_refs = [
            row.source_ref for row in workspace.tables[:MAX_TABLES] if not row.content.strip()
        ]
        bundles = workspace.bundle_windows(
            table_windows,
            max_sources=MAX_TABLES_PER_BUNDLE,
            max_bundle_chars=MAX_TABLE_BUNDLE_CHARS,
        )
        census_results = self._run_table_census(
            config=config,
            context_id=context_id,
            plan_hash=plan_hash,
            targets=normalized_targets,
            workspace=workspace,
            bundles=bundles,
            debug_dir=debug_dir,
        )
        for bundle_index, observations, trace in census_results:
            bundle = bundles[bundle_index]
            merge_census_observations(
                notebook,
                observations=observations,
                window_keys=[_window_key(row) for row in bundle],
            )
            call_trace.extend(trace)
            self._write_state_checkpoint(
                debug_dir,
                f"census_{bundle_index:03d}_state.json",
                notebook=notebook,
                transition={
                    "stage": "table_census_merge",
                    "bundle_index": bundle_index,
                    "source_refs": [row["source_ref"] for row in observations],
                },
            )
        _validate_state_size(notebook, context_id=context_id)
        stable_core._write_artifact(
            debug_dir,
            "census_state.json",
            {
                "notebook": semantic_notebook(notebook),
                "expected_table_windows": [_window_key(row) for row in table_windows],
                "omitted_table_refs": omitted_table_refs,
                "partial_table_refs": partial_table_refs,
                "empty_table_refs": empty_table_refs,
            },
        )

        investigation_finished, investigator_trace = self._investigate_sections(
            config=config,
            context_id=context_id,
            targets=normalized_targets,
            workspace=workspace,
            notebook=notebook,
            debug_dir=debug_dir,
        )
        call_trace.extend(investigator_trace)
        _validate_state_size(notebook, context_id=context_id)
        self._write_state_checkpoint(
            debug_dir,
            "investigation_state.json",
            notebook=notebook,
            transition={
                "stage": "article_investigation",
                "finished": investigation_finished,
            },
        )

        arm_trace = self._reconcile_article_arms(
            config=config,
            context_id=context_id,
            workspace=workspace,
            notebook=notebook,
            debug_dir=debug_dir,
        )
        call_trace.extend(arm_trace)
        _validate_state_size(notebook, context_id=context_id)

        expected_windows = {_window_key(row) for row in table_windows}
        read_windows = set(notebook["coverage"]["read_table_windows"])
        table_coverage_complete = (
            not omitted_table_refs
            and not partial_table_refs
            and not empty_table_refs
            and read_windows == expected_windows
        )
        investigation_status = str(
            notebook["coverage"].get("investigation_status")
            or ("finished" if investigation_finished else "budget_exhausted")
        )
        article_coverage_complete = table_coverage_complete and investigation_finished

        resolution_context = compile_resolution_context(
            targets=normalized_targets,
            notebook=notebook,
            table_coverage_complete=table_coverage_complete,
            investigation_status=investigation_status,
        )
        decisions, _, trace = self._call_validated(
            config=config,
            stage="source_workspace_resolution",
            context_id=context_id,
            system=self._prompt("result_blind_resolution.txt"),
            payload=resolution_context.payload,
            schema=resolution_schema(
                target_ids=[str(row["target_id"]) for row in normalized_targets],
                candidate_ids=[
                    str(row["candidate_id"]) for row in notebook["candidates"]
                ],
                material_ids=list(material_index(notebook)),
                arm_ids=article_arm_ids(notebook["study_map"]),
                source_refs=sorted(_available_source_refs(notebook)),
            ),
            schema_name="meta_source_workspace_resolution",
            max_output_tokens=8_192,
            validator=lambda value: normalize_resolution_response(
                value,
                targets=normalized_targets,
                notebook=notebook,
                table_coverage_complete=table_coverage_complete,
                investigation_status=investigation_status,
            ),
            debug_dir=debug_dir,
            artifact_prefix="resolution",
            aliases=resolution_context.aliases,
        )
        call_trace.extend(trace)
        for decision in decisions:
            decision["verification_dependencies"] = {
                "required_source_refs": decision_required_source_refs(
                    decision, notebook=notebook
                ),
                "optional_source_refs": decision_optional_source_refs(
                    decision, notebook=notebook
                ),
            }
        self._write_state_checkpoint(
            debug_dir,
            "resolution_state.json",
            notebook=notebook,
            transition={"stage": "result_blind_resolution", "decisions": decisions},
        )

        verdicts, verification_trace = self._verify_ready_decisions_source_isolated(
            config=config,
            context_id=context_id,
            targets=normalized_targets,
            decisions=decisions,
            notebook=notebook,
            workspace=workspace,
            debug_dir=debug_dir,
        )
        call_trace.extend(verification_trace)
        self._write_state_checkpoint(
            debug_dir,
            "verification_state.json",
            notebook=notebook,
            transition={"stage": "source_verification", "verdicts": verdicts},
        )

        coverage_status = (
            "complete" if article_coverage_complete else "incomplete_source_coverage"
        )
        coverage = _coverage(
            study_id=study_id,
            targets=normalized_targets,
            workspace=workspace,
            notebook=notebook,
            status=coverage_status,
            omitted_table_refs=omitted_table_refs,
            partial_table_refs=partial_table_refs,
            empty_table_refs=empty_table_refs,
            investigation_finished=investigation_finished,
        )
        result = build_result(
            study_id=study_id,
            study_year=stable_core._study_year(article),
            targets=normalized_targets,
            notebook=notebook,
            decisions=decisions,
            verdicts=verdicts,
            coverage_complete=article_coverage_complete,
            coverage=coverage,
        )
        stable_core._write_artifact(
            debug_dir,
            "final.json",
            {
                "decisions": decisions,
                "verdicts": verdicts,
                "notebook": semantic_notebook(notebook),
                "coverage": coverage,
                "call_trace": call_trace,
                "result": result,
            },
        )
        return result

    def _run_table_census(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        plan_hash: str,
        targets: list[dict[str, Any]],
        workspace: SourceWorkspace,
        bundles: list[list[SourceWindow]],
        debug_dir: Path | None,
    ) -> list[tuple[int, list[dict[str, Any]], list[dict[str, Any]]]]:
        if not bundles:
            return []

        def run_bundle(
            bundle_index: int,
            bundle: list[SourceWindow],
        ) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
            source_payloads = [row.to_payload() for row in bundle]
            source_refs = unique_text(row["source_ref"] for row in source_payloads)
            if len(source_refs) != 1:
                raise ValueError(
                    "Source-workspace table census must isolate each raw table in "
                    "its own LLM request"
                )
            census_context = compile_census_context(
                targets=targets,
                source_payloads=source_payloads,
            )
            payload = census_context.payload
            artifact_prefix = f"census_{bundle_index:03d}"
            cache_key = self._cache_key(
                stage="table_census",
                config=config,
                plan_hash=plan_hash,
                payload=payload,
                prompt_name="table_census.txt",
                source_identity=[
                    {
                        "source_ref": row.source_ref,
                        "source_hash": row.source_hash,
                        "start": row.start,
                        "end": row.end,
                        "window_index": row.window_index,
                        "window_count": row.window_count,
                    }
                    for row in bundle
                ],
            )
            cached = self._cache_get(cache_key)
            if cached is not None:
                try:
                    normalized = normalize_census_response(
                        cached,
                        workspace=workspace,
                        source_payloads=source_payloads,
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    # A cache entry is an optimization, not an authority.  A
                    # changed contract, partial write, or older response must
                    # fall back to a fresh provider call instead of turning a
                    # stale cache into an article-level failure.
                    stable_core._write_artifact(
                        debug_dir,
                        f"{artifact_prefix}_cache.json",
                        {
                            "cache_key": cache_key,
                            "status": "invalidated",
                            "validation_error": str(exc),
                        },
                    )
                    cached = None
                else:
                    stable_core._write_artifact(
                        debug_dir,
                        f"{artifact_prefix}_cache.json",
                        {"cache_key": cache_key, "status": "hit"},
                    )
                    return (
                        bundle_index,
                        normalized,
                        [
                            {
                                "stage": "source_workspace_table_census",
                                "context_id": f"{context_id}::census-{bundle_index}",
                                "attempt": 0,
                                "status": "cache_hit",
                            }
                        ],
                    )
            normalized, raw_response, trace = self._call_validated(
                config=config,
                stage="source_workspace_table_census",
                context_id=f"{context_id}::census-{bundle_index}",
                system=self._prompt("table_census.txt"),
                payload=payload,
                schema=table_census_schema(source_refs=source_refs),
                schema_name="meta_source_workspace_table_census",
                max_output_tokens=12_288,
                validator=lambda value: normalize_census_response(
                    value,
                    workspace=workspace,
                    source_payloads=source_payloads,
                ),
                debug_dir=debug_dir,
                artifact_prefix=artifact_prefix,
                aliases=census_context.aliases,
            )
            self._cache_put(cache_key, raw_response)
            return bundle_index, normalized, trace

        results: list[tuple[int, list[dict[str, Any]], list[dict[str, Any]]]] = []
        worker_count = min(self.max_table_workers, len(bundles))
        if worker_count == 1:
            results = [run_bundle(index, bundle) for index, bundle in enumerate(bundles)]
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(run_bundle, index, bundle): index
                    for index, bundle in enumerate(bundles)
                }
                for future in as_completed(futures):
                    results.append(future.result())
        return sorted(results, key=lambda row: row[0])

    def _investigate_sections(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        targets: list[dict[str, Any]],
        workspace: SourceWorkspace,
        notebook: dict[str, Any],
        debug_dir: Path | None,
    ) -> tuple[bool, list[dict[str, Any]]]:
        bootstrap_search_budget = min(
            MAX_BOOTSTRAP_SECTION_SEARCHES,
            (
                self.max_section_searches - 1
                if self.max_section_searches > 1
                else self.max_section_searches
            ),
        )
        bootstrap_window_budget = min(
            MAX_BOOTSTRAP_SECTION_READ_WINDOWS,
            (
                self.max_section_read_windows - 1
                if self.max_section_read_windows > 1
                else self.max_section_read_windows
            ),
        )
        queries = default_section_queries(
            targets=targets,
            notebook=notebook,
            limit=bootstrap_search_budget,
        )
        front_matter_sources = workspace.read_sources(
            workspace.front_matter_refs,
            max_windows=bootstrap_window_budget,
            max_total_chars=MAX_SECTION_CONTEXT_CHARS,
        )
        remaining_bootstrap_windows = max(
            0, bootstrap_window_budget - len(front_matter_sources)
        )
        searched_sources = workspace.search_sections(
            queries,
            max_results=remaining_bootstrap_windows,
            max_total_chars=MAX_SECTION_CONTEXT_CHARS,
        )
        front_matter_ref_set = {
            str(row["source_ref"]) for row in front_matter_sources
        }
        latest_sources = [
            *front_matter_sources,
            *[
                row
                for row in searched_sources
                if str(row["source_ref"]) not in front_matter_ref_set
            ][:remaining_bootstrap_windows],
        ]
        latest_sources, section_context_limited = _bound_context_payloads(
            latest_sources,
            max_total_chars=MAX_SECTION_CONTEXT_CHARS,
        )
        if section_context_limited or _payloads_mark_actual_context_limited(
            [*front_matter_sources, *searched_sources]
        ):
            notebook["warnings"].append("section_context_budget_exceeded")
        notebook["coverage"]["section_searches"] = list(queries)
        notebook["coverage"]["read_section_refs"] = unique_text(
            row["source_ref"] for row in latest_sources
        )
        notebook["coverage"]["investigation_status"] = "running"
        remaining_searches = self.max_section_searches - len(queries)
        remaining_windows = self.max_section_read_windows - len(latest_sources)
        traces: list[dict[str, Any]] = []
        finished = False

        for round_index in range(1, self.max_investigation_rounds + 1):
            # A fetched source must always be followed by a model turn that can
            # consume it. Reserve the last turn for a final state transition.
            allowed_actions = (
                {"finish"}
                if round_index == self.max_investigation_rounds
                else {"finish", "search_sections", "read_sources"}
            )
            investigation_context = compile_investigation_context(
                targets=targets,
                workspace=workspace,
                notebook=notebook,
                latest_sources=latest_sources,
                context_budget_exceeded=_payloads_mark_actual_context_limited(
                    latest_sources
                ),
                max_total_chars=MAX_SECTION_CONTEXT_CHARS,
                source_bundle_status=_source_bundle_status(latest_sources),
                remaining_budget={
                    "investigation_rounds": self.max_investigation_rounds
                    - round_index
                    + 1,
                    "section_searches": max(0, remaining_searches),
                    "source_read_windows": max(0, remaining_windows),
                },
            )
            payload = investigation_context.payload
            update, _, trace = self._call_validated(
                config=config,
                stage="source_workspace_investigation",
                context_id=f"{context_id}::investigation-{round_index}",
                system=self._prompt("investigator.txt"),
                payload=payload,
                schema=investigator_schema(
                    table_refs=workspace.table_refs,
                    section_refs=workspace.section_refs,
                    evidence_need_ids=[
                        str(row["need_id"])
                        for row in active_evidence_needs(notebook)
                    ],
                    allowed_actions=sorted(allowed_actions),
                ),
                schema_name="meta_source_workspace_investigation",
                max_output_tokens=8_192,
                validator=lambda value: normalize_investigator_response(
                    value,
                    workspace=workspace,
                    notebook=notebook,
                    latest_source_payloads=latest_sources,
                    allowed_actions=allowed_actions,
                ),
                debug_dir=debug_dir,
                artifact_prefix=f"investigation_{round_index:02d}",
                aliases=investigation_context.aliases,
            )
            traces.extend(trace)
            merge_investigator_update(notebook, update=update)
            _validate_state_size(notebook, context_id=context_id)
            self._write_state_checkpoint(
                debug_dir,
                f"investigation_{round_index:02d}_state.json",
                notebook=notebook,
                transition={
                    "stage": "article_investigation_round",
                    "round": round_index,
                    "action": update["action"],
                    "action_status": "requested",
                    "remaining_searches": remaining_searches,
                    "remaining_windows": remaining_windows,
                },
            )
            notebook["coverage"]["investigation_rounds_completed"] = round_index
            if update["action"] == "finish":
                finished = True
                notebook["coverage"]["investigation_status"] = "finished"
                notebook["coverage"]["investigation_pending_action"] = None
                break
            requested_queries: list[str] = []
            requested_source_refs: list[str] = []
            if update["action"] == "search_sections":
                requested = update["queries"][: max(0, remaining_searches)]
                requested_queries = list(requested)
                if not requested:
                    notebook["warnings"].append("section_search_budget_exhausted")
                    latest_sources = []
                else:
                    latest_sources = workspace.search_sections(
                        requested,
                        max_results=max(0, remaining_windows),
                        max_total_chars=MAX_SECTION_CONTEXT_CHARS,
                    )
                    latest_sources, limited = _bound_context_payloads(
                        latest_sources,
                        max_total_chars=MAX_SECTION_CONTEXT_CHARS,
                    )
                    if limited or _payloads_mark_actual_context_limited(
                        latest_sources
                    ):
                        notebook["warnings"].append(
                            "section_context_budget_exceeded"
                        )
                    remaining_searches -= len(requested)
                    remaining_windows -= len(latest_sources)
                    notebook["coverage"]["section_searches"] = unique_text(
                        [
                            *notebook["coverage"]["section_searches"],
                            *requested,
                        ]
                    )
            else:
                requested_source_refs = list(update["source_refs"])
                latest_sources = workspace.read_sources(
                    update["source_refs"],
                    max_windows=max(0, remaining_windows),
                    max_total_chars=MAX_SECTION_CONTEXT_CHARS,
                )
                latest_sources, limited = _bound_context_payloads(
                    latest_sources,
                    max_total_chars=MAX_SECTION_CONTEXT_CHARS,
                )
                if limited or _payloads_mark_actual_context_limited(latest_sources):
                    notebook["warnings"].append("section_context_budget_exceeded")
                remaining_windows -= len(latest_sources)
            notebook["coverage"]["read_section_refs"] = unique_text(
                [
                    *notebook["coverage"]["read_section_refs"],
                    *[
                        row["source_ref"]
                        for row in latest_sources
                        if row.get("source_kind") == "section"
                    ],
                ]
            )
            self._write_state_checkpoint(
                debug_dir,
                f"investigation_{round_index:02d}_action_state.json",
                notebook=notebook,
                transition={
                    "stage": "article_investigation_action",
                    "round": round_index,
                    "action": update["action"],
                    "action_status": "executed",
                    "requested_queries": requested_queries,
                    "requested_source_refs": requested_source_refs,
                    "returned_source_refs": unique_text(
                        row.get("source_ref") for row in latest_sources
                    ),
                    "returned_window_keys": [
                        _payload_window_key(row) for row in latest_sources
                    ],
                    "transport_limit_reasons": _payload_limit_reasons(
                        latest_sources
                    ),
                    "remaining_searches": remaining_searches,
                    "remaining_windows": remaining_windows,
                },
            )
        if not finished:
            notebook["warnings"].append("investigation_round_budget_exhausted")
            notebook["coverage"]["investigation_status"] = "budget_exhausted"
            notebook["coverage"]["investigation_pending_action"] = None
        return finished, traces

    def _reconcile_article_arms(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        workspace: SourceWorkspace,
        notebook: dict[str, Any],
        debug_dir: Path | None,
    ) -> list[dict[str, Any]]:
        observations = arm_observations(notebook)
        if not observations:
            notebook["arm_identity"] = {
                "observations": [],
                "canonical_arms": [],
                "unresolved": [],
                "observation_to_arm_id": {},
                "notes": ["No source-local randomized-arm observations were available."],
            }
            return []
        valid_source_refs = set(workspace.table_refs) | set(workspace.section_refs)
        arm_context = compile_arm_context(
            observations=observations,
            notebook=notebook,
        )
        reconciliation, _, trace = self._call_validated(
            config=config,
            stage="source_workspace_arm_reconciliation",
            context_id=f"{context_id}::arm-reconciliation",
            system=self._prompt("arm_reconciliation.txt"),
            payload=arm_context.payload,
            schema=arm_reconciliation_schema(
                observation_ids=[str(row["observation_id"]) for row in observations],
                source_refs=sorted(valid_source_refs),
            ),
            schema_name="meta_source_workspace_arm_reconciliation",
            max_output_tokens=6_144,
            validator=lambda value: normalize_arm_reconciliation_response(
                value,
                observations=observations,
                valid_source_refs=valid_source_refs,
            ),
            debug_dir=debug_dir,
            artifact_prefix="arm_reconciliation",
            aliases=arm_context.aliases,
        )
        apply_arm_reconciliation(
            notebook,
            observations=observations,
            reconciliation=reconciliation,
        )
        stable_core._write_artifact(
            debug_dir,
            "arm_identity.json",
            notebook["arm_identity"],
        )
        return trace

    def _verify_ready_decisions(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        targets: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        notebook: dict[str, Any],
        workspace: SourceWorkspace,
        debug_dir: Path | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Legacy multi-source verifier retained only for artifact comparison."""

        return self._verify_ready_decisions_legacy(
            config=config,
            context_id=context_id,
            targets=targets,
            decisions=decisions,
            notebook=notebook,
            workspace=workspace,
            debug_dir=debug_dir,
        )

    def _verify_ready_decisions_source_isolated(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        targets: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        notebook: dict[str, Any],
        workspace: SourceWorkspace,
        debug_dir: Path | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Verify raw sources independently, then adjudicate grounded evidence cards."""

        ready = [row for row in decisions if row["status"] == "ready"]
        if not ready:
            return [], []
        target_by_id = {str(row["target_id"]): row for row in targets}
        all_verdicts: list[dict[str, Any]] = []
        traces: list[dict[str, Any]] = []

        for group_index, group in enumerate(
            _verification_groups(ready, notebook=notebook), start=1
        ):
            source_refs = unique_text(
                source_ref
                for decision in group
                for source_ref in decision_required_source_refs(
                    decision, notebook=notebook
                )
            )
            optional_source_refs = unique_text(
                source_ref
                for decision in group
                for source_ref in decision_optional_source_refs(
                    decision, notebook=notebook
                )
            )
            if not source_refs:
                raise ValueError("Ready decisions require at least one evidence source")
            verification_dependencies = [
                {
                    "target_id": str(decision["target_id"]),
                    "required_source_refs": decision_required_source_refs(
                        decision, notebook=notebook
                    ),
                    "optional_source_refs": decision_optional_source_refs(
                        decision, notebook=notebook
                    ),
                }
                for decision in group
            ]
            self._write_state_checkpoint(
                debug_dir,
                f"verification_{group_index:02d}_plan_state.json",
                notebook=notebook,
                transition={
                    "stage": "source_verification_plan",
                    "group": group_index,
                    "required_source_refs": source_refs,
                    "optional_source_refs": optional_source_refs,
                    "dependencies": verification_dependencies,
                },
            )

            def verify_source(
                source_index: int,
                source_ref: str,
            ) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
                source = workspace.source(source_ref)
                locators = [
                    locator
                    for decision in group
                    for locator in decision_required_evidence_locators(
                        decision, notebook=notebook
                    )
                    if str(locator.get("source_ref") or "") == source_ref
                ]
                if source.source_kind == "section" and locators:
                    source_payloads = workspace.evidence_windows(
                        evidence_locators=locators,
                        max_windows=MAX_VERIFICATION_WINDOWS,
                        max_total_chars=MAX_VERIFICATION_CONTEXT_CHARS,
                    )
                else:
                    source_payloads = workspace.read_sources(
                        [source_ref],
                        max_window_chars=MAX_CONTEXT_SOURCE_CHARS,
                        max_windows=MAX_VERIFICATION_WINDOWS,
                        max_total_chars=MAX_VERIFICATION_CONTEXT_CHARS,
                    )
                source_payloads, context_limited = _bound_context_payloads(
                    source_payloads,
                    max_total_chars=MAX_VERIFICATION_CONTEXT_CHARS,
                )
                if not source_payloads:
                    raise ValueError(
                        f"No raw source window available for verification: {source_ref}"
                    )
                source_bundle_status = workspace.source_bundle_coverage(
                    source_refs=[source_ref],
                    payloads=source_payloads,
                )
                if context_limited or _payloads_mark_actual_context_limited(
                    source_payloads
                ):
                    notebook["warnings"].append(
                        f"source_verification_context_budget_exceeded:{source_ref}"
                    )
                if source_bundle_status["source_content_partial"]:
                    notebook["warnings"].append(
                        f"source_verification_source_partial:{source_ref}"
                    )
                candidate_ids = _source_local_candidate_ids(
                    group,
                    notebook=notebook,
                    source_ref=source_ref,
                )
                source_materials = _source_local_support_materials(
                    group,
                    notebook=notebook,
                    source_ref=source_ref,
                )
                group_targets = [
                    target_by_id[str(row["target_id"])] for row in group
                ]
                supported_representations = [
                        _supported_result_representations(
                            target_by_id[str(row["target_id"])]
                        )
                        for row in group
                ]
                proposals = [
                    _source_local_verification_proposal(
                        row,
                        notebook=notebook,
                        source_ref=source_ref,
                    )
                    for row in group
                ]
                verification_context = compile_source_verification_context(
                    targets=group_targets,
                    supported_representations=supported_representations,
                    notebook=notebook,
                    proposals=proposals,
                    candidate_ids=candidate_ids,
                    source_materials=source_materials,
                    source_payloads=source_payloads,
                    source_ref=source_ref,
                    source_kind=source.source_kind,
                    context_budget_exceeded=context_limited
                    or _payloads_mark_actual_context_limited(source_payloads),
                    source_bundle_status=source_bundle_status,
                )
                payload = verification_context.payload
                reviews, _, source_trace = self._call_validated(
                    config=config,
                    stage="source_workspace_source_verification",
                    context_id=(
                        f"{context_id}::verification-{group_index}::source-{source_index}"
                    ),
                    system=self._prompt("source_verification.txt"),
                    payload=payload,
                    schema=source_verification_schema(
                        target_ids=[str(row["target_id"]) for row in group],
                        candidate_ids=candidate_ids,
                        arm_ids=article_arm_ids(notebook["study_map"]),
                        source_ref=source_ref,
                    ),
                    schema_name="meta_source_workspace_source_verification",
                    max_output_tokens=12_288,
                    validator=lambda value: normalize_source_verification_response(
                        value,
                        decisions=group,
                        targets=targets,
                        notebook=notebook,
                        workspace=workspace,
                        source_payloads=source_payloads,
                        source_ref=source_ref,
                    ),
                    debug_dir=debug_dir,
                    artifact_prefix=(
                        f"verification_{group_index:02d}_source_{source_index:02d}"
                    ),
                    aliases=verification_context.aliases,
                )
                return source_index, reviews, source_trace

            def collect_source(
                source_index: int,
                source_ref: str,
            ) -> tuple[
                int,
                str,
                list[dict[str, Any]],
                list[dict[str, Any]],
                Exception | None,
            ]:
                try:
                    index, reviews, source_trace = verify_source(
                        source_index, source_ref
                    )
                    return index, source_ref, reviews, source_trace, None
                except Exception as exc:
                    attempt_history = getattr(exc, "attempt_history", None)
                    source_trace = (
                        list(attempt_history)
                        if isinstance(attempt_history, list)
                        else []
                    )
                    return source_index, source_ref, [], source_trace, exc

            source_results: list[
                tuple[
                    int,
                    str,
                    list[dict[str, Any]],
                    list[dict[str, Any]],
                    Exception | None,
                ]
            ] = []
            worker_count = min(self.max_table_workers, len(source_refs))
            if worker_count == 1:
                source_results = [
                    collect_source(index, source_ref)
                    for index, source_ref in enumerate(source_refs, start=1)
                ]
            else:
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    futures = {
                        executor.submit(collect_source, index, source_ref): index
                        for index, source_ref in enumerate(source_refs, start=1)
                    }
                    for future in as_completed(futures):
                        source_results.append(future.result())
            source_results.sort(key=lambda row: row[0])
            source_outcomes = [
                {
                    "source_index": source_index,
                    "source_ref": source_ref,
                    "status": "failed" if error else "accepted",
                    "review_count": len(reviews),
                    **(
                        {"failure": _source_verification_failure_summary(error)}
                        if error
                        else {}
                    ),
                }
                for source_index, source_ref, reviews, _, error in source_results
            ]
            self._write_state_checkpoint(
                debug_dir,
                f"verification_{group_index:02d}_sources_state.json",
                notebook=notebook,
                transition={
                    "stage": "source_verification_results",
                    "group": group_index,
                    "outcomes": source_outcomes,
                },
            )
            for _, _, _, source_trace, _ in source_results:
                traces.extend(source_trace)
            source_failures = [
                error
                for _, _, _, _, error in source_results
                if error is not None
            ]
            if source_failures:
                _raise_required_source_verification_failure(
                    source_failures[0],
                    context_id=context_id,
                )
            source_reviews = [
                review
                for _, _, reviews, _, _ in source_results
                for review in reviews
            ]

            evidence_ids = unique_text(
                str(evidence["evidence_id"])
                for review in source_reviews
                for evidence in review.get("verified_evidence") or []
            )
            candidate_ids = unique_text(
                [
                    *[
                        str(candidate_id)
                        for decision in group
                        for candidate_id in decision.get("candidate_ids") or []
                    ],
                    *[
                        str(candidate_id)
                        for review in source_reviews
                        for candidate_id in review.get("selected_candidate_ids") or []
                    ],
                    *[
                        str(evidence.get("candidate_id") or "")
                        for review in source_reviews
                        for evidence in review.get("verified_evidence") or []
                    ],
                ]
            )
            adjudication_targets = [
                target_by_id[str(row["target_id"])] for row in group
            ]
            adjudication_representations = [
                    _supported_result_representations(
                        target_by_id[str(row["target_id"])]
                    )
                    for row in group
            ]
            adjudication_proposals = [
                _verification_proposal(row, notebook=notebook) for row in group
            ]
            adjudication_context = compile_adjudication_context(
                targets=adjudication_targets,
                supported_representations=adjudication_representations,
                notebook=notebook,
                proposals=adjudication_proposals,
                source_reviews=source_reviews,
                verification_dependencies=verification_dependencies,
            )
            verdicts, _, adjudication_trace = self._call_validated(
                config=config,
                stage="source_workspace_cross_source_adjudication",
                context_id=f"{context_id}::adjudication-{group_index}",
                system=self._prompt("cross_source_adjudication.txt"),
                payload=adjudication_context.payload,
                schema=cross_source_adjudication_schema(
                    target_ids=[str(row["target_id"]) for row in group],
                    candidate_ids=candidate_ids,
                    arm_ids=article_arm_ids(notebook["study_map"]),
                    evidence_ids=evidence_ids,
                ),
                schema_name="meta_source_workspace_cross_source_adjudication",
                max_output_tokens=8_192,
                validator=lambda value: normalize_cross_source_adjudication_response(
                    value,
                    decisions=group,
                    targets=targets,
                    notebook=notebook,
                    source_reviews=source_reviews,
                ),
                debug_dir=debug_dir,
                artifact_prefix=f"adjudication_{group_index:02d}",
                aliases=adjudication_context.aliases,
            )
            traces.extend(adjudication_trace)
            all_verdicts.extend(verdicts)

        ready_order = [str(row["target_id"]) for row in ready]
        by_id = {str(row["target_id"]): row for row in all_verdicts}
        return [by_id[target_id] for target_id in ready_order], traces

    def _verify_ready_decisions_legacy(
        self,
        *,
        config: dict[str, Any],
        context_id: str,
        targets: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        notebook: dict[str, Any],
        workspace: SourceWorkspace,
        debug_dir: Path | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ready = [row for row in decisions if row["status"] == "ready"]
        if not ready:
            return [], []
        target_by_id = {str(row["target_id"]): row for row in targets}
        all_verdicts: list[dict[str, Any]] = []
        traces: list[dict[str, Any]] = []
        for group_index, group in enumerate(
            _verification_groups(ready, notebook=notebook), start=1
        ):
            evidence_locators = unique_dicts(
                [
                    locator
                    for decision in group
                    for locator in decision_evidence_locators(
                        decision, notebook=notebook
                    )
                ]
            )
            # A provisional decision may contain only a candidate handle (or a
            # partial field proposal).  In that case there is no material quote
            # from which to build a reread window, so include a bounded prefix of
            # each selected candidate table.  This is source transport only; no
            # table structure is interpreted here.
            locator_refs = {
                str(locator.get("source_ref") or "")
                for locator in evidence_locators
            }
            for decision in group:
                if not decision.get("provisional_for_verification"):
                    continue
                for candidate_id in decision.get("candidate_ids") or []:
                    candidate = next(
                        (
                            row
                            for row in notebook["candidates"]
                            if str(row.get("candidate_id") or "")
                            == str(candidate_id)
                        ),
                        None,
                    )
                    source_ref = str((candidate or {}).get("source_table_id") or "")
                    if not source_ref or source_ref in locator_refs:
                        continue
                    candidate_locators = [
                        {
                            **source_window,
                            "source_quote": str(material.get("source_quote") or ""),
                        }
                        for arm in (candidate or {}).get("arms") or []
                        for material in arm.get("materials") or []
                        for source_window in material.get("source_windows") or []
                    ]
                    if candidate_locators:
                        evidence_locators.extend(candidate_locators)
                        locator_refs.add(source_ref)
                        continue
                    source = workspace.source(source_ref)
                    evidence_locators.append(
                        {
                            "source_ref": source.source_ref,
                            "source_kind": source.source_kind,
                            "source_hash": source.source_hash,
                            "transport": {
                                "start": 0,
                                "end": min(len(source.content), MAX_CONTEXT_SOURCE_CHARS),
                                "window_index": 0,
                                "window_count": 1,
                            },
                            "source_quote": "",
                        }
                    )
                    locator_refs.add(source_ref)
            # A resolver-selected semantic source handle is deliberately
            # re-read from the full bounded source, rather than trusting the
            # short search snippet that led to it.
            for decision in group:
                for source_ref in decision.get("context_source_refs") or []:
                    source = workspace.source(str(source_ref))
                    if source.source_kind != "section":
                        continue
                    evidence_locators.append(
                        {
                            "source_ref": source.source_ref,
                            "source_kind": source.source_kind,
                            "source_hash": source.source_hash,
                            "transport": {
                                "start": 0,
                                "end": min(
                                    len(source.content), MAX_CONTEXT_SOURCE_CHARS
                                ),
                                "window_index": 0,
                                "window_count": 1,
                            },
                            "source_quote": "",
                        }
                    )
            evidence_locators = unique_dicts(evidence_locators)
            source_payloads = workspace.evidence_windows(
                evidence_locators=evidence_locators,
                max_windows=MAX_VERIFICATION_WINDOWS,
                max_total_chars=MAX_VERIFICATION_CONTEXT_CHARS,
            )
            source_payloads, verification_context_limited = _bound_context_payloads(
                source_payloads,
                max_total_chars=MAX_VERIFICATION_CONTEXT_CHARS,
            )
            if verification_context_limited or _payloads_mark_context_limited(
                source_payloads
            ):
                notebook["warnings"].append("verification_context_budget_exceeded")
            supplied_refs = unique_text(row["source_ref"] for row in source_payloads)
            # Keep resolver-selected candidate handles available even when a
            # source-window budget prevented their table from being reread. The
            # verifier can then return an honest unresolved verdict; it is not
            # forced to invent a different candidate merely because its source
            # was omitted from the bounded bundle.
            selected_candidate_ids = unique_text(
                candidate_id
                for decision in group
                for candidate_id in decision.get("candidate_ids") or []
            )
            candidate_ids = unique_text(
                [
                    *selected_candidate_ids,
                    *[
                        str(candidate["candidate_id"])
                        for candidate in notebook["candidates"]
                        if str(candidate["source_table_id"]) in supplied_refs
                    ],
                ]
            )
            payload = {
                "task": "reconstruct_and_verify_proposed_article_contributions",
                "targets": [
                    semantic_target(target_by_id[str(row["target_id"])])
                    for row in group
                ],
                "study_map": notebook["study_map"],
                "proposals": [
                    _verification_proposal(row, notebook=notebook) for row in group
                ],
                "candidate_context": [
                    candidate_summary(candidate, include_values=True)
                    for candidate in notebook["candidates"]
                    if str(candidate["candidate_id"]) in candidate_ids
                ],
                "support_material_context": _verification_support_material_context(
                    group,
                    notebook=notebook,
                ),
                "raw_source_bundle": source_payloads,
                "source_bundle_status": {
                    "context_budget_exceeded": verification_context_limited
                    or _payloads_mark_context_limited(source_payloads),
                    "max_total_chars": MAX_VERIFICATION_CONTEXT_CHARS,
                    "max_windows": MAX_VERIFICATION_WINDOWS,
                },
            }
            verdicts, _, trace = self._call_validated(
                config=config,
                stage="source_workspace_verification",
                context_id=f"{context_id}::verification-{group_index}",
                system=self._prompt("evidence_verification.txt"),
                payload=payload,
                schema=verification_schema(
                    target_ids=[str(row["target_id"]) for row in group],
                    candidate_ids=candidate_ids,
                    arm_ids=article_arm_ids(notebook["study_map"]),
                    source_refs=supplied_refs,
                ),
                schema_name="meta_source_workspace_verification",
                max_output_tokens=12_288,
                validator=lambda value: normalize_verification_response(
                    value,
                    decisions=group,
                    targets=targets,
                    notebook=notebook,
                    workspace=workspace,
                    source_payloads=source_payloads,
                ),
                debug_dir=debug_dir,
                artifact_prefix=f"verification_{group_index:02d}",
            )
            traces.extend(trace)
            risk_by_target = {
                str(row["target_id"]): _scope_audit_reasons(
                    row,
                    workspace=workspace,
                    verification_context_limited=(
                        verification_context_limited
                        or _payloads_mark_context_limited(source_payloads)
                    ),
                )
                for row in verdicts
            }
            audit_targets = [
                row
                for row in verdicts
                if risk_by_target[str(row["target_id"])]
            ]
            if audit_targets:
                audit_ids = [str(row["target_id"]) for row in audit_targets]
                audit_id_set = set(audit_ids)
                audit_decisions = [
                    row for row in group if str(row["target_id"]) in audit_id_set
                ]
                audit_locators = unique_dicts(
                    [
                        locator
                        for decision in audit_decisions
                        for locator in decision_evidence_locators(
                            decision, notebook=notebook
                        )
                    ]
                    + [
                        locator
                        for verdict in audit_targets
                        for locator in _verdict_scope_locators(
                            verdict, workspace=workspace
                        )
                    ]
                )
                audit_refs = unique_text(
                    [
                        *[
                            source_ref
                            for decision in audit_decisions
                            for source_ref in decision_source_refs(
                                decision, notebook=notebook
                            )
                        ],
                        *[
                            str(field.get("source_ref") or "")
                            for verdict in audit_targets
                            for field in verdict.get("verified_fields") or []
                        ],
                        *[
                            str(supporting.get("source_ref") or "")
                            for verdict in audit_targets
                            for field in verdict.get("verified_fields") or []
                            for supporting in (
                                field.get("evidence_scope") or {}
                            ).get("supporting_quotes")
                            or []
                            if isinstance(supporting, dict)
                        ],
                    ]
                )
                audit_source_payloads = workspace.scope_audit_windows(
                    source_refs=audit_refs,
                    evidence_locators=audit_locators,
                    max_windows=MAX_SCOPE_AUDIT_WINDOWS,
                    max_total_chars=MAX_SCOPE_AUDIT_CONTEXT_CHARS,
                )
                if not audit_source_payloads:
                    audit_source_payloads = list(source_payloads)
                audit_bundle_status = workspace.source_bundle_coverage(
                    source_refs=audit_refs,
                    payloads=audit_source_payloads,
                )
                if audit_bundle_status["context_budget_exceeded"]:
                    notebook["warnings"].append(
                        "scope_audit_context_budget_exceeded"
                    )
                    notebook["coverage"][
                        "scope_context_incomplete_target_ids"
                    ] = unique_text(
                        [
                            *notebook["coverage"][
                                "scope_context_incomplete_target_ids"
                            ],
                            *audit_ids,
                        ]
                    )
                notebook["coverage"]["scope_audit_target_ids"] = unique_text(
                    [
                        *notebook["coverage"]["scope_audit_target_ids"],
                        *audit_ids,
                    ]
                )
                notebook["coverage"]["scope_audit_reasons"].update(
                    {target_id: risk_by_target[target_id] for target_id in audit_ids}
                )
                audit_supplied_refs = unique_text(
                    row["source_ref"] for row in audit_source_payloads
                )
                audit_candidate_ids = unique_text(
                    [
                        *[
                            candidate_id
                            for verdict in audit_targets
                            for candidate_id in verdict.get(
                                "selected_candidate_ids"
                            )
                            or []
                        ],
                        *[
                            str(candidate["candidate_id"])
                            for candidate in notebook["candidates"]
                            if str(candidate["source_table_id"])
                            in audit_supplied_refs
                        ],
                    ]
                )
                audit_payload = {
                    "task": "bounded_source_scope_audit",
                    "targets": [
                        semantic_target(target_by_id[target_id])
                        for target_id in audit_ids
                    ],
                    "study_map": notebook["study_map"],
                    "proposals": [
                        _verification_proposal(row, notebook=notebook)
                        for row in audit_decisions
                    ],
                    "initial_verdicts": [
                        _scope_audit_verdict(row) for row in audit_targets
                    ],
                    "risk_signals": [
                        {
                            "target_id": target_id,
                            "reasons": risk_by_target[target_id],
                        }
                        for target_id in audit_ids
                    ],
                    "candidate_context": [
                        candidate_summary(candidate, include_values=True)
                        for candidate in notebook["candidates"]
                        if str(candidate["candidate_id"])
                        in audit_candidate_ids
                    ],
                    "raw_source_bundle": audit_source_payloads,
                    "source_bundle_status": {
                        **audit_bundle_status,
                        "max_total_chars": MAX_SCOPE_AUDIT_CONTEXT_CHARS,
                        "max_windows": MAX_SCOPE_AUDIT_WINDOWS,
                        "max_rounds": MAX_SCOPE_AUDIT_ROUNDS,
                    },
                }
                audited, _, audit_trace = self._call_validated(
                    config=config,
                    stage="source_workspace_scope_audit",
                    context_id=f"{context_id}::scope-audit-{group_index}",
                    system=self._prompt("scope_audit.txt"),
                    payload=audit_payload,
                    schema=verification_schema(
                        target_ids=audit_ids,
                        candidate_ids=audit_candidate_ids,
                        arm_ids=article_arm_ids(notebook["study_map"]),
                        source_refs=audit_supplied_refs,
                    ),
                    schema_name="meta_source_workspace_scope_audit",
                    max_output_tokens=12_288,
                    validator=lambda value: normalize_verification_response(
                        value,
                        decisions=audit_decisions,
                        targets=targets,
                        notebook=notebook,
                        workspace=workspace,
                        source_payloads=audit_source_payloads,
                    ),
                    debug_dir=debug_dir,
                    artifact_prefix=f"scope_audit_{group_index:02d}",
                )
                traces.extend(audit_trace)
                audited_by_id = {str(row["target_id"]): row for row in audited}
                verdicts = [
                    audited_by_id.get(str(row["target_id"]), row)
                    for row in verdicts
                ]
            all_verdicts.extend(verdicts)
        ready_order = [str(row["target_id"]) for row in ready]
        by_id = {str(row["target_id"]): row for row in all_verdicts}
        return [by_id[target_id] for target_id in ready_order], traces

    def _call_validated(
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
        validator: Callable[[dict[str, Any]], Any],
        debug_dir: Path | None,
        artifact_prefix: str,
        aliases: CallAliases | None = None,
    ) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
        prompt_payload = payload
        call_aliases = aliases or CallAliases(real_to_alias={})
        model_schema = call_aliases.encode(schema)
        traces: list[dict[str, Any]] = []
        for attempt in range(1, 3):
            response: dict[str, Any] | None = None
            model_response: dict[str, Any] | None = None
            provider_metadata: dict[str, Any] = {}
            model_payload = call_aliases.encode(prompt_payload)
            started = time.perf_counter()
            started_at = time.time()
            input_summary = request_input_summary(
                config=config,
                system=system,
                payload=model_payload,
                schema=model_schema,
                max_output_tokens=max_output_tokens,
                alias_map=call_aliases.artifact_map(),
            )
            started_record = {
                "stage": stage,
                "context_id": context_id,
                "attempt": attempt,
                "status": "started",
                "started_at_unix": started_at,
                "input_summary": input_summary,
                "alias_map": call_aliases.artifact_map(),
            }
            stable_core._write_artifact(
                debug_dir,
                f"{artifact_prefix}_attempt_{attempt}.json",
                started_record,
            )
            self._append_call_ledger(debug_dir, started_record)
            if not input_summary["fits_context_window"]:
                detail = (
                    "compiled request exceeds context budget: "
                    f"estimated_input_tokens={input_summary['estimated_input_tokens']}, "
                    f"input_token_budget={input_summary['input_token_budget']}"
                )
                failed_record = {
                    **started_record,
                    "status": "context_budget_exceeded",
                    "failure_code": "context_budget_exceeded",
                    "failure_detail": detail,
                }
                stable_core._write_artifact(
                    debug_dir,
                    f"{artifact_prefix}_attempt_{attempt}.json",
                    failed_record,
                )
                self._append_call_ledger(debug_dir, failed_record)
                raise MetaAnalysisInvocationError(
                    stage=stage,
                    attempts=0,
                    retry_exhausted=False,
                    context_id=context_id,
                    failure_code="context_budget_exceeded",
                    failure_detail=detail,
                    attempt_history=[failed_record],
                )
            try:
                model_response = self.llm_caller(
                    config=config,
                    system=system,
                    prompt=json.dumps(
                        model_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    timeout_seconds=self.llm_timeout_seconds,
                    temperature=0,
                    max_output_tokens=max_output_tokens,
                    reasoning_effort="medium",
                    json_schema=model_schema,
                    json_schema_name=schema_name,
                    metadata_sink=provider_metadata.update,
                )
                if not isinstance(model_response, dict):
                    raise ValueError("LLM response must be an object")
                response = call_aliases.decode(model_response)
                normalized = validator(response)
                elapsed = time.perf_counter() - started
                accepted_record = {
                    "stage": stage,
                    "context_id": context_id,
                    "attempt": attempt,
                    "status": "accepted",
                    "started_at_unix": started_at,
                    "elapsed_seconds": elapsed,
                    "input_summary": input_summary,
                    "provider_metadata": provider_metadata,
                }
                traces.append(accepted_record)
                stable_core._write_artifact(
                    debug_dir,
                    f"{artifact_prefix}_attempt_{attempt}.json",
                    {
                        **accepted_record,
                        "alias_map": call_aliases.artifact_map(),
                        "response": response,
                    },
                )
                self._append_call_ledger(debug_dir, accepted_record)
                return normalized, response, traces
            except LLMAPIError as exc:
                elapsed = time.perf_counter() - started
                error_record = {
                    "stage": stage,
                    "context_id": context_id,
                    "attempt": attempt,
                    "status": "provider_error",
                    "started_at_unix": started_at,
                    "elapsed_seconds": elapsed,
                    "retryable": exc.retryable,
                    "status_code": exc.status_code,
                    "failure_code": exc.failure_code,
                    "request_id": exc.request_id,
                    "failure_detail": exc.provider_message,
                    "input_summary": input_summary,
                    "provider_metadata": provider_metadata,
                }
                traces.append(error_record)
                stable_core._write_artifact(
                    debug_dir,
                    f"{artifact_prefix}_attempt_{attempt}.json",
                    {
                        **error_record,
                        "alias_map": call_aliases.artifact_map(),
                        "provider_message": exc.provider_message,
                    },
                )
                self._append_call_ledger(debug_dir, error_record)
                if not exc.retryable or attempt == 2:
                    raise MetaAnalysisInvocationError(
                        stage=stage,
                        attempts=attempt,
                        retry_exhausted=bool(exc.retryable and attempt == 2),
                        context_id=context_id,
                        failure_code=exc.failure_code,
                        status_code=exc.status_code,
                        request_id=exc.request_id,
                        failure_detail=exc.provider_message,
                        attempt_history=traces,
                    ) from exc
            except (KeyError, TypeError, ValueError) as exc:
                elapsed = time.perf_counter() - started
                failure_code = _output_failure_code(exc)
                invalid_record = {
                    "stage": stage,
                    "context_id": context_id,
                    "attempt": attempt,
                    "status": "invalid_output",
                    "started_at_unix": started_at,
                    "elapsed_seconds": elapsed,
                    "validation_error": str(exc),
                    "failure_code": failure_code,
                    "input_summary": input_summary,
                    "provider_metadata": provider_metadata,
                }
                traces.append(invalid_record)
                stable_core._write_artifact(
                    debug_dir,
                    f"{artifact_prefix}_attempt_{attempt}.json",
                    {
                        **invalid_record,
                        "alias_map": call_aliases.artifact_map(),
                        "response": response,
                    },
                )
                self._append_call_ledger(debug_dir, invalid_record)
                if attempt == 2:
                    raise MetaAnalysisOutputError(
                        stage=stage,
                        attempts=attempt,
                        context_id=context_id,
                        validation_error=str(exc),
                        failure_code=failure_code,
                        attempt_history=traces,
                    ) from exc
                prompt_payload = {
                    **payload,
                    "repair": {
                        "instruction": (
                            "Return a complete replacement response for the same task. "
                            "Do not merely patch the prior JSON."
                        ),
                        "validation_error": str(exc),
                        # The original task payload is sent again.  Keep only
                        # the shape of the failed response so a malformed or
                        # very large JSON cannot recursively inflate retry
                        # context or anchor the model to bad values.
                        "previous_response_shape": _structured_shape(response),
                    },
                }
        raise AssertionError("unreachable")

    def _append_call_ledger(
        self,
        debug_dir: Path | None,
        record: dict[str, Any],
    ) -> None:
        if debug_dir is None:
            return
        debug_dir.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._artifact_lock:
            with (debug_dir / "call_ledger.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(serialized + "\n")

    def _write_state_checkpoint(
        self,
        debug_dir: Path | None,
        name: str,
        *,
        notebook: dict[str, Any],
        transition: dict[str, Any],
    ) -> None:
        stable_core._write_artifact(
            debug_dir,
            name,
            _state_checkpoint_payload(notebook=notebook, transition=transition),
        )

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
            raise MetaAnalysisConfigurationError(stage="source_workspace_agent") from exc

    def _prompt(self, name: str) -> str:
        try:
            return (self.prompt_dir / name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise MetaAnalysisConfigurationError(stage="source_workspace_agent") from exc

    def _limits(self, *, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "max_tables": MAX_TABLES,
            "max_table_windows": MAX_TABLE_WINDOWS,
            "max_tables_per_bundle": MAX_TABLES_PER_BUNDLE,
            "max_table_bundle_chars": MAX_TABLE_BUNDLE_CHARS,
            "max_table_workers": self.max_table_workers,
            "llm_timeout_seconds": self.llm_timeout_seconds,
            "max_investigation_rounds": self.max_investigation_rounds,
            "max_section_searches": self.max_section_searches,
            "max_section_read_windows": self.max_section_read_windows,
            "max_bootstrap_section_searches": min(
                MAX_BOOTSTRAP_SECTION_SEARCHES, self.max_section_searches
            ),
            "max_bootstrap_section_read_windows": min(
                MAX_BOOTSTRAP_SECTION_READ_WINDOWS,
                self.max_section_read_windows,
            ),
            "max_section_context_chars": MAX_SECTION_CONTEXT_CHARS,
            "max_verification_context_chars": MAX_VERIFICATION_CONTEXT_CHARS,
            "max_verification_windows": MAX_VERIFICATION_WINDOWS,
            "max_scope_audit_context_chars": MAX_SCOPE_AUDIT_CONTEXT_CHARS,
            "max_scope_audit_windows": MAX_SCOPE_AUDIT_WINDOWS,
            "max_scope_audit_rounds": MAX_SCOPE_AUDIT_ROUNDS,
            "max_targets_per_article": MAX_TARGETS_PER_ARTICLE,
            "max_llm_stage_calls_per_article": MAX_LLM_STAGE_CALLS_PER_ARTICLE,
            "max_provider_attempts_per_stage": 2,
            "max_provider_attempts_per_article": MAX_PROVIDER_ATTEMPTS_PER_ARTICLE,
            "context_window_tokens": int(
                config.get("context_window_tokens") or 128_000
            ),
        }

    def _cache_key(
        self,
        *,
        stage: str,
        config: dict[str, Any],
        plan_hash: str,
        payload: dict[str, Any],
        prompt_name: str,
        source_identity: list[dict[str, Any]] | None = None,
    ) -> str:
        key_payload = {
            "stage": stage,
            "method_version": METHOD_VERSION,
            "schema_version": SCHEMA_VERSION,
            "model": str(config.get("model") or ""),
            "plan_hash": plan_hash,
            "prompt_hash": sha256(
                self._prompt(prompt_name).encode("utf-8")
            ).hexdigest(),
            "payload": payload,
            "source_identity": source_identity or [],
        }
        return sha256(
            json.dumps(key_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        if self.cache_dir is None:
            return None
        path = self.cache_dir / "table_census" / f"{key}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _cache_put(self, key: str, value: dict[str, Any]) -> None:
        if self.cache_dir is None:
            return
        root = self.cache_dir / "table_census"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{key}.json"
        temporary = root / f".{key}.{os.getpid()}.tmp"
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)


def build_method(
    *,
    config: LLMConfig | dict[str, Any] | None = None,
) -> Method:
    return Method(config=config)


def _verification_proposal(
    decision: dict[str, Any],
    *,
    notebook: dict[str, Any],
) -> dict[str, Any]:
    return {
        "target_id": decision["target_id"],
        "selected_candidate_ids": list(decision["candidate_ids"]),
        "selected_candidates": [
            {"candidate_id": candidate_id}
            for candidate_id in decision["candidate_ids"]
        ],
        "experimental_arm_ids": list(decision["experimental_arm_ids"]),
        "control_arm_ids": list(decision["control_arm_ids"]),
        "experimental_arm_labels": decision["experimental_arm_labels"],
        "control_arm_labels": decision["control_arm_labels"],
        "selected_field_evidence": [
            {
                "field": field["field"],
                "material_ids": list(field["material_ids"]),
            }
            for field in decision["field_evidence"]
        ],
        "alternative_material_ids": list(decision["alternative_material_ids"]),
        "context_source_refs": list(decision.get("context_source_refs") or []),
        "provisional_for_verification": bool(
            decision.get("provisional_for_verification")
        ),
        "assumptions": decision["assumptions"],
        "reason": decision["reason"],
    }


def _source_local_verification_proposal(
    decision: dict[str, Any],
    *,
    notebook: dict[str, Any],
    source_ref: str,
) -> dict[str, Any]:
    """Keep the target proposal while removing other sources' materials."""

    proposal = _verification_proposal(decision, notebook=notebook)
    materials = material_index(notebook)
    proposal["selected_field_evidence"] = [
        {
            "field": field["field"],
            "material_ids": [
                material_id
                for material_id in field["material_ids"]
                if _material_source_ref(materials.get(material_id)) == source_ref
            ],
        }
        for field in decision["field_evidence"]
        if any(
            _material_source_ref(materials.get(material_id)) == source_ref
            for material_id in field["material_ids"]
        )
    ]
    proposal["alternative_material_ids"] = []
    proposal["context_source_refs"] = [
        ref
        for ref in decision.get("context_source_refs") or []
        if str(ref) == source_ref
    ]
    proposal["source_local_candidate_ids"] = _source_local_candidate_ids(
        [decision],
        notebook=notebook,
        source_ref=source_ref,
    )
    proposal["verification_source_ref"] = source_ref
    return proposal


def _source_local_candidate_ids(
    decisions: list[dict[str, Any]],
    *,
    notebook: dict[str, Any],
    source_ref: str,
) -> list[str]:
    """Return candidates on the required source-verification path only.

    Resolver-excluded candidates remain visible in resolution artifacts. They
    must not be able to invalidate an otherwise usable selected contribution.
    """

    candidate_by_id = {
        str(candidate["candidate_id"]): candidate
        for candidate in notebook["candidates"]
    }
    relevant_ids = unique_text(
        str(candidate_id)
        for decision in decisions
        for candidate_id in decision.get("candidate_ids") or []
    )
    return [
        candidate_id
        for candidate_id in relevant_ids
        if candidate_id in candidate_by_id
        and str(candidate_by_id[candidate_id].get("source_table_id") or "")
        == source_ref
    ]


def _source_local_support_materials(
    decisions: list[dict[str, Any]],
    *,
    notebook: dict[str, Any],
    source_ref: str,
) -> list[dict[str, Any]]:
    materials = material_index(notebook)
    selected_ids = unique_text(
        material_id
        for decision in decisions
        for field in decision.get("field_evidence") or []
        for material_id in field.get("material_ids") or []
    )
    return [
        materials[material_id]
        for material_id in selected_ids
        if material_id in materials
        and not str(materials[material_id].get("candidate_id") or "")
        and _material_source_ref(materials[material_id]) == source_ref
    ]


def _material_source_ref(material: dict[str, Any] | None) -> str:
    if not material:
        return ""
    return str(
        material.get("source_ref")
        or material.get("source_table_id")
        or ""
    )


def _supported_result_representations(target: dict[str, Any]) -> dict[str, Any]:
    target_id = str(target.get("target_id") or "")
    if str(target.get("data_type") or "") == "Dichotomous":
        alternatives = [
            {
                "representation": "arm_events_total",
                "required_fields": [
                    "experimental_events",
                    "experimental_total",
                    "control_events",
                    "control_total",
                ],
                "optional_fields": [],
            }
        ]
    else:
        arm_representation = {
            "representation": "arm_mean_sd_total",
            "required_fields": [
                "experimental_mean",
                "experimental_sd",
                "experimental_total",
                "control_mean",
                "control_sd",
                "control_total",
            ],
            "optional_fields": [],
        }
        direct_representation = {
            "representation": "direct_effect_uncertainty",
            "required_fields": ["direct_effect", "direct_uncertainty"],
            "optional_fields": ["experimental_total", "control_total"],
        }
        policy = target.get("result_selection_policy") or {}
        priorities = [
            str(value).strip().casefold()
            for value in policy.get("statistic_type_priority") or []
            if str(value).strip()
        ]
        if not priorities:
            alternatives = [arm_representation, direct_representation]
        else:
            alternatives = []
            for priority in priorities:
                if (
                    ("arm" in priority and "mean" in priority)
                    or "mean, standard deviation" in priority
                    or "mean/sd" in priority
                ):
                    if arm_representation not in alternatives:
                        alternatives.append(arm_representation)
                elif (
                    "direct" in priority
                    or "between-group" in priority
                    or "adjusted mean difference" in priority
                ):
                    if direct_representation not in alternatives:
                        alternatives.append(direct_representation)
            if not alternatives:
                # Preserve compatibility for older, free-text policies that do
                # not identify a known representation.
                alternatives = [arm_representation, direct_representation]
    return {"target_id": target_id, "alternatives": alternatives}


def _verification_support_material_context(
    decisions: list[dict[str, Any]],
    *,
    notebook: dict[str, Any],
) -> list[dict[str, Any]]:
    materials = material_index(notebook)
    material_ids = unique_text(
        [
            *[
                material_id
                for decision in decisions
                for field in decision["field_evidence"]
                for material_id in field["material_ids"]
            ],
            *[
                material_id
                for decision in decisions
                for material_id in decision["alternative_material_ids"]
            ],
        ]
    )
    return [
        material_summary(materials[material_id], include_values=True)
        for material_id in material_ids
        if material_id in materials
        and not str(materials[material_id].get("candidate_id") or "")
    ]


def _verification_groups(
    decisions: list[dict[str, Any]],
    *,
    notebook: dict[str, Any],
) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_refs: set[str] = set()
    for decision in decisions:
        refs = set(decision_required_source_refs(decision, notebook=notebook))
        if current and len(current_refs | refs) > MAX_VERIFICATION_SOURCE_REFS:
            groups.append(current)
            current = []
            current_refs = set()
        current.append(decision)
        current_refs |= refs
    if current:
        groups.append(current)
    return groups


def _scope_audit_reasons(
    verdict: dict[str, Any],
    *,
    workspace: SourceWorkspace,
    verification_context_limited: bool,
) -> list[str]:
    """Return general semantic-scope risks; never choose a source value."""

    reasons: list[str] = []
    competing = list(verdict.get("competing_interpretations") or [])
    if verdict.get("status") == "unresolved":
        # An unresolved verdict may still contain a plausible candidate and
        # selected source handles.  Give the bounded audit one opportunity to
        # recover a best-supported value; only an unresolved verdict with no
        # evidence to reread is terminal at this stage.
        if verdict.get("selected_candidate_ids"):
            reasons.append("verification_unresolved")
        if competing:
            reasons.append("competing_interpretations")
        if verification_context_limited:
            reasons.append("verification_context_incomplete")
        return unique_text(reasons)
    if competing:
        reasons.append("competing_interpretations")
    if verification_context_limited:
        reasons.append("verification_context_incomplete")

    fields = list(verdict.get("verified_fields") or [])
    field_source_refs = unique_text(
        str(field.get("source_ref") or "") for field in fields
    )
    source_refs = unique_text(
        [
            *field_source_refs,
            *[
                str(supporting.get("source_ref") or "")
                for field in fields
                for supporting in (field.get("evidence_scope") or {}).get(
                    "supporting_quotes"
                )
                or []
                if isinstance(supporting, dict)
            ],
        ]
    )
    # A section quote often supplies ordinary context (for example, the
    # article's endpoint definition) while the numeric field remains wholly
    # table-local.  Count that as cross-source binding only when a field is
    # actually supported by another table/source, or when the field itself is
    # sourced from prose.  This preserves the audit signal for genuine
    # cross-table denominator/arm assembly without making every contextual
    # citation trigger an extra LLM round.
    cross_source_binding = len(field_source_refs) > 1
    for field in fields:
        field_ref = str(field.get("source_ref") or "")
        if not field_ref:
            continue
        field_source = workspace.source(field_ref)
        for supporting in (field.get("evidence_scope") or {}).get(
            "supporting_quotes"
        ) or []:
            if not isinstance(supporting, dict):
                continue
            supporting_ref = str(supporting.get("source_ref") or "")
            if not supporting_ref or supporting_ref == field_ref:
                continue
            supporting_source = workspace.source(supporting_ref)
            if (
                supporting_source.source_kind == "table"
                or field_source.source_kind == "section"
            ):
                cross_source_binding = True
                break
        if cross_source_binding:
            break
    if cross_source_binding:
        reasons.append("cross_source_field_binding")
    for source_ref in source_refs:
        source = workspace.source(source_ref)
        if source.has_scope_linkage_markup:
            reasons.append(f"source_scope_linkage_markup:{source_ref}")

    for field in fields:
        field_name = str(field.get("field") or "")
        evidence_scope = field.get("evidence_scope") or {}
        scope_status = str(evidence_scope.get("scope_status") or "")
        if scope_status != "complete":
            reasons.append(f"field_scope_{scope_status or 'missing'}:{field_name}")
        if evidence_scope.get("footnote_links"):
            reasons.append(f"field_footnote_link:{field_name}")
        confidence = str(field.get("selection_confidence") or "")
        if confidence != "high":
            reasons.append(f"field_confidence_{confidence or 'missing'}:{field_name}")
        if field_name.endswith("_total") and str(
            field.get("selection_basis") or ""
        ) != "direct":
            reasons.append(f"inferred_denominator_scope:{field_name}")
    return unique_text(reasons)


def _verdict_scope_locators(
    verdict: dict[str, Any],
    *,
    workspace: SourceWorkspace,
) -> list[dict[str, Any]]:
    locators: list[dict[str, Any]] = []
    for field in verdict.get("verified_fields") or []:
        source_ref = str(field.get("source_ref") or "")
        if not source_ref:
            continue
        source = workspace.source(source_ref)
        material = field.get("material") or {}
        material_quote = str(material.get("source_quote") or "").strip()
        source_windows = list(material.get("source_windows") or [])
        for window in source_windows:
            locators.append({**window, "source_quote": material_quote})
        local_quotes = [
            material_quote,
            *[
                str(link.get("text") or "")
                for link in (field.get("evidence_scope") or {}).get(
                    "footnote_links"
                )
                or []
                if isinstance(link, dict)
            ],
        ]
        for quote in unique_text(local_quotes):
            locators.append(
                {
                    "source_ref": source_ref,
                    "source_kind": source.source_kind,
                    "source_hash": source.source_hash,
                    "transport": {
                        "start": 0,
                        "end": len(source.content),
                        "window_index": 0,
                        "window_count": 1,
                    },
                    "source_quote": quote,
                }
            )
        for supporting in (field.get("evidence_scope") or {}).get(
            "supporting_quotes"
        ) or []:
            if not isinstance(supporting, dict):
                continue
            supporting_ref = str(supporting.get("source_ref") or "")
            quote = str(supporting.get("quote") or "").strip()
            if not supporting_ref or not quote:
                continue
            supporting_source = workspace.source(supporting_ref)
            locators.append(
                {
                    "source_ref": supporting_ref,
                    "source_kind": supporting_source.source_kind,
                    "source_hash": supporting_source.source_hash,
                    "transport": {
                        "start": 0,
                        "end": len(supporting_source.content),
                        "window_index": 0,
                        "window_count": 1,
                    },
                    "source_quote": quote,
                }
            )
    return unique_dicts(locators)


def _scope_audit_verdict(verdict: dict[str, Any]) -> dict[str, Any]:
    material_keys = (
        "kind",
        "value",
        "lower",
        "upper",
        "confidence_level",
        "decimal_places",
        "statistical_scope",
        "applies_to",
        "source_quote",
        "interpretation",
        "uncertainties",
    )
    return {
        "target_id": str(verdict.get("target_id") or ""),
        "status": str(verdict.get("status") or ""),
        "selected_candidate_ids": list(
            verdict.get("selected_candidate_ids") or []
        ),
        "experimental_arm_ids": list(verdict.get("experimental_arm_ids") or []),
        "control_arm_ids": list(verdict.get("control_arm_ids") or []),
        "experimental_arm_labels": list(
            verdict.get("experimental_arm_labels") or []
        ),
        "control_arm_labels": list(verdict.get("control_arm_labels") or []),
        "field_evidence": [
            {
                "field": str(field.get("field") or ""),
                "candidate_id": field.get("candidate_id"),
                "source_ref": str(field.get("source_ref") or ""),
                "source_kind": str(field.get("source_kind") or ""),
                "arm_id": str(field.get("arm_id") or ""),
                "observed_arm_label": str(field.get("arm_label") or ""),
                "material": {
                    key: (field.get("material") or {}).get(key)
                    for key in material_keys
                },
                "evidence_scope": field.get("evidence_scope") or {},
                "selection_basis": str(field.get("selection_basis") or ""),
                "selection_confidence": str(
                    field.get("selection_confidence") or ""
                ),
                "selection_rationale": str(
                    field.get("selection_rationale") or ""
                ),
            }
            for field in verdict.get("verified_fields") or []
        ],
        "competing_interpretations": list(
            verdict.get("competing_interpretations") or []
        ),
        "assumptions": list(verdict.get("assumptions") or []),
        "reason": str(verdict.get("reason") or ""),
    }


def _coverage(
    *,
    study_id: str,
    targets: list[dict[str, Any]],
    workspace: SourceWorkspace | None,
    notebook: dict[str, Any] | None,
    status: str,
    omitted_table_refs: list[str],
    partial_table_refs: list[str],
    empty_table_refs: list[str],
    investigation_finished: bool,
) -> dict[str, Any]:
    coverage_state = notebook.get("coverage") if notebook else {}
    warnings = list(notebook.get("warnings") or []) if notebook else []
    if omitted_table_refs:
        warnings.append("table_source_cap_exceeded")
    if partial_table_refs:
        warnings.append("table_window_cap_exceeded")
    if empty_table_refs:
        warnings.append("empty_raw_table_source")
    table_transport_status = (
        "complete"
        if not omitted_table_refs
        and not partial_table_refs
        and not empty_table_refs
        else "incomplete"
    )
    investigation_status = str(
        coverage_state.get("investigation_status")
        or ("finished" if investigation_finished else "budget_exhausted")
    )
    return {
        "study_id": study_id,
        "expected_target_ids": [str(row.get("target_id") or "") for row in targets],
        "status": status,
        "read_section_ids": list(coverage_state.get("read_section_refs") or []),
        "read_table_ids": list(coverage_state.get("read_table_ids") or []),
        "unreadable_table_ids": list(empty_table_refs),
        "omitted_table_ids": list(omitted_table_refs),
        "partial_table_ids": list(partial_table_refs),
        "table_transport_status": table_transport_status,
        "scope_audit_target_ids": list(
            coverage_state.get("scope_audit_target_ids") or []
        ),
        "scope_context_incomplete_target_ids": list(
            coverage_state.get("scope_context_incomplete_target_ids") or []
        ),
        "scope_audit_reasons": dict(
            coverage_state.get("scope_audit_reasons") or {}
        ),
        "investigation_finished": investigation_finished,
        "investigation_status": investigation_status,
        "investigation_rounds_completed": int(
            coverage_state.get("investigation_rounds_completed") or 0
        ),
        "investigation_pending_action": coverage_state.get(
            "investigation_pending_action"
        ),
        "article_hash": workspace.article_hash if workspace else None,
        "warnings": unique_text(warnings),
        "policy_version": POLICY_VERSION,
        "schema_version": SCHEMA_VERSION,
        "table_coverage_policy": "bounded_raw_table_windows_seen_by_table_census",
    }


def _validate_state_size(
    notebook: dict[str, Any],
    *,
    context_id: str,
) -> None:
    validation_error: str | None = None
    if len(notebook["candidates"]) > MAX_CANDIDATES_PER_ARTICLE:
        validation_error = (
            f"Article evidence exceeded {MAX_CANDIDATES_PER_ARTICLE} candidates"
        )
    elif len(notebook["support_materials"]) > MAX_SUPPORT_MATERIALS_PER_ARTICLE:
        validation_error = (
            f"Article evidence exceeded {MAX_SUPPORT_MATERIALS_PER_ARTICLE} support materials"
        )
    if validation_error:
        raise MetaAnalysisOutputError(
            stage="source_workspace_evidence_state",
            attempts=1,
            context_id=context_id,
            validation_error=validation_error,
        )


def _window_key(window: SourceWindow) -> str:
    return (
        f"{window.source_ref}:{window.start}:{window.end}:"
        f"{window.source_hash[:16]}"
    )


def _bounded_table_windows(
    windows: list[SourceWindow],
    *,
    max_windows: int,
) -> tuple[list[SourceWindow], list[str]]:
    """Select a fair, deterministic set of intact table windows.

    Long tables may span several transport windows. Selection rotates across
    table sources so an early long table cannot consume the article budget.
    Raw table content is neither inspected nor transformed here.
    """

    rows = list(windows)
    if len(rows) <= max_windows:
        return rows, []

    source_order: list[str] = []
    indices_by_source: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        if row.source_ref not in indices_by_source:
            source_order.append(row.source_ref)
            indices_by_source[row.source_ref] = []
        indices_by_source[row.source_ref].append(index)

    selected_indices: set[int] = set()
    round_index = 0
    while len(selected_indices) < max_windows:
        made_progress = False
        for source_ref in source_order:
            source_indices = indices_by_source[source_ref]
            if round_index >= len(source_indices):
                continue
            selected_indices.add(source_indices[round_index])
            made_progress = True
            if len(selected_indices) == max_windows:
                break
        if not made_progress:
            break
        round_index += 1

    partial_source_refs = [
        source_ref
        for source_ref in source_order
        if any(index not in selected_indices for index in indices_by_source[source_ref])
    ]
    return (
        [row for index, row in enumerate(rows) if index in selected_indices],
        partial_source_refs,
    )


def _output_failure_code(error: Exception) -> str:
    message = " ".join(str(error).lower().split())
    if any(
        marker in message
        for marker in (
            "response contained no complete text",
            "response was incomplete",
            "response reported an error",
        )
    ):
        return "provider_incomplete_response"
    if "json" in message and any(
        marker in message for marker in ("decode", "parse", "object")
    ):
        return "invalid_model_json"
    if any(
        marker in message
        for marker in (
            "unknown source id",
            "invalid or duplicate census source ref",
            "must use the current raw source bundle",
            "source kind does not match source ref",
        )
    ):
        return "model_output_source_scope_violation"
    if "footnote" in message:
        return "model_output_footnote_provenance_invalid"
    return "invalid_model_output"


def _source_verification_failure_summary(error: Exception) -> dict[str, Any]:
    return {
        "error_type": type(error).__name__,
        "stage": str(
            getattr(error, "stage", "source_workspace_source_verification")
        ),
        "failure_code": str(
            getattr(error, "failure_code", _output_failure_code(error))
        ),
        "attempts": int(getattr(error, "attempts", 1) or 1),
        "failure_detail": " ".join(
            str(
                getattr(error, "failure_detail", None)
                or getattr(error, "validation_error", None)
                or error
            ).split()
        )[:500],
    }


def _raise_required_source_verification_failure(
    error: Exception,
    *,
    context_id: str,
) -> None:
    if isinstance(error, (MetaAnalysisInvocationError, MetaAnalysisOutputError)):
        raise error
    if isinstance(error, (KeyError, TypeError, ValueError)):
        raise MetaAnalysisOutputError(
            stage="source_workspace_source_verification",
            attempts=1,
            context_id=context_id,
            validation_error=str(error),
            failure_code=_output_failure_code(error),
        ) from error
    raise error


def _state_checkpoint_payload(
    *,
    notebook: dict[str, Any],
    transition: dict[str, Any],
) -> dict[str, Any]:
    return {
        "transition": transition,
        "canonical_evidence": {
            "study_map": notebook.get("study_map") or {},
            "candidates": [
                candidate_summary(row, include_values=False)
                for row in notebook.get("candidates") or []
            ],
            "support_materials": [
                material_summary(row, include_values=False)
                for row in notebook.get("support_materials") or []
            ],
        },
        "working_decision_state": working_state_snapshot(notebook),
        "trace_state": {
            "coverage": notebook.get("coverage") or {},
            "warnings": list(notebook.get("warnings") or []),
        },
    }


def _structured_shape(value: Any, *, depth: int = 0) -> dict[str, Any] | str:
    """Return a bounded structural description for an invalid LLM response.

    Retry context needs to explain what failed, but it should not echo a large
    prior response containing stale numbers or source text.  This helper keeps
    only object keys, array lengths, and a few nested shapes.
    """

    if depth >= 2:
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        return type(value).__name__
    if isinstance(value, dict):
        keys = sorted(str(key) for key in value)[:64]
        omitted = max(0, len(value) - len(keys))
        result: dict[str, Any] = {
            "type": "object",
            "keys": keys,
        }
        if omitted:
            result["omitted_key_count"] = omitted
        return result
    if isinstance(value, list):
        return {
            "type": "array",
            "length": len(value),
            "item_shapes": [
                _structured_shape(item, depth=depth + 1)
                for item in value[:3]
            ],
        }
    return {"type": type(value).__name__}


def _bound_context_payloads(
    payloads: list[dict[str, Any]],
    *,
    max_total_chars: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Keep complete source windows under a stage-level context budget.

    Source windows are never cut or semantically rewritten here.  Dropped
    windows are surfaced to the caller so the final coverage record can state
    that the source bundle was incomplete.
    """

    if max_total_chars <= 0:
        return [], bool(payloads)
    result: list[dict[str, Any]] = []
    used = 0
    limited = False
    for payload in payloads:
        content = str(payload.get("raw_xml") or payload.get("text") or "")
        if result and used + len(content) > max_total_chars:
            limited = True
            break
        if not result and len(content) > max_total_chars:
            # A single source window should normally be below the budget.  If
            # an upstream adapter violates that invariant, keep it intact and
            # make the violation visible rather than truncating raw evidence.
            result.append(payload)
            limited = True
            break
        result.append(payload)
        used += len(content)
    if limited and result:
        reasons = list(result[-1].get("transport_limit_reasons") or [])
        if "char_budget_limited" not in reasons:
            reasons.append("char_budget_limited")
        result[-1]["transport_limit_reasons"] = reasons
        result[-1]["context_budget_exceeded"] = True
    return result, limited


def _payloads_mark_context_limited(payloads: list[dict[str, Any]]) -> bool:
    return any(bool(row.get("context_budget_exceeded")) for row in payloads)


def _payloads_mark_actual_context_limited(
    payloads: list[dict[str, Any]],
) -> bool:
    return "char_budget_limited" in _payload_limit_reasons(payloads)


def _payload_limit_reasons(payloads: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for payload in payloads:
        typed = payload.get("transport_limit_reasons")
        if isinstance(typed, list):
            values = typed
        elif payload.get("context_budget_exceeded"):
            values = ["source_content_partial"]
        else:
            values = []
        for value in values:
            reason = str(value or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
    return reasons


def _source_bundle_status(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = _payload_limit_reasons(payloads)
    return {
        "char_budget_limited": "char_budget_limited" in reasons,
        "source_window_limited": "source_window_limited" in reasons,
        "search_result_limited": "search_result_limited" in reasons,
        "source_content_partial": "source_content_partial" in reasons,
        "transport_limit_reasons": reasons,
    }


def _payload_window_key(payload: dict[str, Any]) -> str:
    transport = (
        payload.get("transport")
        if isinstance(payload.get("transport"), dict)
        else {}
    )
    return "::".join(
        [
            str(payload.get("source_ref") or ""),
            str(transport.get("window_index", 0)),
            str(transport.get("start", "")),
            str(transport.get("end", "")),
        ]
    )
