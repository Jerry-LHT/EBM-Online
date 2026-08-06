"""Single-Agent infrastructure task for complete Study Data Collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    IssueSeverity,
    TaskContext,
    TaskWorkResult,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.study_data_collection import (
    StudyDataCollectionInput,
    StudyDataCollectionProtocol,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskAccessMode,
    TaskExecutorPort,
    TaskOutputError,
    TaskRunRequest,
    TaskRunResult,
    WebAccessPolicy,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.schema import (
    strict_task_output_schema,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.study_data_collection import (
    DataCalculator,
    StudyDataCollectionError,
    canonical_json_bytes,
    parse_study_data_collection_document,
    project_study_data_collection,
    study_data_collection_counts,
)


_PROTOCOL_ADAPTER = TypeAdapter(StudyDataCollectionProtocol)
_PROMPT = (
    "Complete the Study Data Collection task under the collect-study-data "
    "Skill. Follow the Protocol and "
    "current applicable official methodology; start from persisted Selection "
    "Report locators and discoveries, then read the linked Reports to the "
    "current evidence need without repeating resolved discovery, "
    "collect source-faithful Characteristics and Results for every Included "
    "Study. Choose the working method and available tools that fit the "
    "evidence and workload, produce the declared Study Data document, and "
    "return a control result that truthfully matches that document. "
    "Unavailable or unreported evidence is a completed local data state after "
    "the relevant investigation, not unfinished task work."
)


class _AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "blocked"]
    issues: tuple[ArtifactIssue, ...] = ()
    blocker: str | None = None
    warnings: tuple[str, ...] = ()
    human_independent_extraction_satisfied: bool = False

    @model_validator(mode="after")
    def validate_status(self) -> "_AgentOutput":
        if self.human_independent_extraction_satisfied:
            raise ValueError("automated execution cannot satisfy human independence")
        if self.status == "blocked" and not self.blocker:
            raise ValueError("blocked output requires blocker")
        if self.status != "blocked" and self.blocker is not None:
            raise ValueError("only blocked output may contain blocker")
        return self


_OUTPUT_ADAPTER = TypeAdapter(_AgentOutput)


def study_data_collection_output_schema() -> dict[str, Any]:
    return strict_task_output_schema(_OUTPUT_ADAPTER.json_schema())


@dataclass(slots=True)
class CollectStudyDataTask:
    executor: TaskExecutorPort
    selection_package_store: Any
    data_collection_store: Any
    calculate: DataCalculator
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    timeout_seconds: float = 1800.0
    run_id_factory: Callable[[], str] = field(
        default=lambda: f"study-data-collection-{uuid4().hex}",
        repr=False,
    )

    def collect(
        self,
        inputs: StudyDataCollectionInput,
        context: TaskContext,
    ) -> TaskWorkResult:
        selection_ref = inputs.selection.package_ref
        self.selection_package_store.validate(selection_ref)
        selection_directory = self.selection_package_store.resolve_manifest(
            selection_ref
        ).parent
        binding = _binding(inputs, context)
        session = self.data_collection_store.begin(
            binding=binding,
        )
        try:
            result, output = self._run(
                inputs=inputs,
                context=context,
                session=session,
                selection_directory=selection_directory,
            )
            return self._persist(
                result,
                output,
                session=session,
                selection_directory=selection_directory,
            )
        finally:
            self.data_collection_store.release(session)

    def _run(
        self,
        *,
        inputs: StudyDataCollectionInput,
        context: TaskContext,
        session: Any,
        selection_directory: Path,
    ) -> tuple[TaskRunResult, _AgentOutput]:
        artifacts: dict[str, Path] = {
            "selection-package": selection_directory,
            "work-binding": session.root / "binding.json",
        }
        request = TaskRunRequest(
            run_id=self.run_id_factory(),
            prompt=_PROMPT,
            input_data={
                "review_id": context.review_id,
                "protocol_version": context.protocol_version,
                "review_mode": "single_agent",
                "protocol": _PROTOCOL_ADAPTER.dump_python(inputs.protocol, mode="json"),
                "selection_package": {
                    "path": "inputs/artifacts/selection-package",
                    "package_id": inputs.selection.package_ref.package_id,
                    "content_digest": inputs.selection.package_ref.content_digest,
                },
                "binding": dict(session.binding),
                "binding_path": "inputs/artifacts/work-binding",
                "declared_tools": (
                    {
                        "name": "data-collection-work",
                        "path": "scripts/data_collection_work.py",
                        "purpose": "initialize, update, validate, and canonically write the document",
                    },
                    {
                        "name": "data-calculator",
                        "path": "scripts/data_calculator.py",
                        "purpose": "execute Agent-chosen numeric expressions reproducibly",
                    },
                ),
            },
            input_artifacts=artifacts,
            output_schema=study_data_collection_output_schema(),
            output_artifacts={
                "document": (
                    "outputs/study-data/"
                    f"{context.review_id}-study-data-collection.json"
                ),
            },
            timeout_seconds=self.timeout_seconds,
            access_mode=TaskAccessMode.WORKSPACE_WRITE,
            enable_workspace_network=True,
            enable_web_search=True,
            web_access_policy=self.web_access_policy,
            task_name="study_data_collection",
        )
        execution = self.executor.execute(
            request,
            output_adapter=_OUTPUT_ADAPTER,
            error_context="Agent Study Data Collection output is invalid",
        )
        return execution.result, execution.output

    def _persist(
        self,
        result: TaskRunResult,
        output: _AgentOutput,
        *,
        session: Any,
        selection_directory: Path,
    ) -> TaskWorkResult:
        artifact = result.output_artifacts.get("document")
        if artifact is None:
            raise TaskOutputError("Agent did not produce Study Data Collection document")
        completed = output.status == "completed"
        try:
            document = parse_study_data_collection_document(
                artifact.content,
                expected_binding=session.binding,
                require_completed=completed,
                calculate=self.calculate,
            )
        except StudyDataCollectionError as exc:
            raise TaskOutputError(str(exc)) from exc
        _validate_selection_identity(
            document,
            selection_directory,
            require_completed=completed,
        )
        if document["status"] != output.status:
            raise TaskOutputError("control status does not match document status")
        progress = study_data_collection_counts(document)
        if not completed:
            issues = output.issues
            if not any(
                item.severity is IssueSeverity.ERROR for item in issues
            ):
                issues += (
                    ArtifactIssue(
                        code="study_data_collection_blocked",
                        message=output.blocker or "Study Data Collection is blocked",
                        severity=IssueSeverity.ERROR,
                    ),
                )
            return TaskWorkResult(
                status=TaskWorkStatus.BLOCKED,
                work_id=session.work_id,
                progress=progress,
                issues=issues,
                blocker=output.blocker,
            )
        projections, summary = project_study_data_collection(document)
        deterministic_issues = _deterministic_calculation_issues(document)
        result_issues = output.issues + tuple(
            issue for issue in deterministic_issues if issue not in output.issues
        )
        persistence_warnings = output.warnings + tuple(
            issue.message for issue in deterministic_issues
        )
        review_id = str(session.binding["review_id"])
        public = {
            f"{review_id}-study-data-collection.json": canonical_json_bytes(document),
            **projections,
        }
        snapshot = self.data_collection_store.complete(
            session,
            authoritative=public[f"{review_id}-study-data-collection.json"],
            public_files=public,
            projection_summary=summary,
            counts=progress,
            warnings=persistence_warnings,
        )
        return TaskWorkResult(
            status=TaskWorkStatus.COMPLETED,
            artifact=snapshot.artifact,
            progress=progress,
            issues=result_issues,
        )


def _binding(
    inputs: StudyDataCollectionInput,
    context: TaskContext,
) -> dict[str, str]:
    protocol = _PROTOCOL_ADAPTER.dump_json(inputs.protocol)
    selection = inputs.selection.package_ref
    return {
        "review_id": context.review_id,
        "protocol_version": context.protocol_version,
        "protocol_digest": f"sha256:{sha256(protocol).hexdigest()}",
        "selection_package_id": selection.package_id,
        "selection_package_digest": selection.content_digest,
    }


def _deterministic_calculation_issues(
    document: Mapping[str, Any],
) -> tuple[ArtifactIssue, ...]:
    codes = {
        "calculation_replay_unavailable",
        "calculation_trace_normalized",
        "calculated_value_normalized",
        "unused_calculation",
    }
    result: list[ArtifactIssue] = []
    for raw in document.get("issues", []):
        if not isinstance(raw, Mapping) or raw.get("code") not in codes:
            continue
        result.append(
            ArtifactIssue(
                code=str(raw["code"]),
                message=str(raw["message"]),
                severity=IssueSeverity.WARNING,
            )
        )
    return tuple(result)


def _validate_selection_identity(
    document: Mapping[str, Any],
    selection_directory: Path,
    *,
    require_completed: bool,
) -> None:
    decisions = _read_jsonl(selection_directory / "study-decisions.jsonl")
    known = {
        str(item["study_id"])
        for item in _read_jsonl(selection_directory / "studies.jsonl")
    }
    included = {
        str(item["study_id"])
        for item in decisions
        if item.get("classification") == "included"
    }
    if not included.issubset(known):
        raise TaskOutputError("Selection includes an unknown Study")
    linked: dict[str, set[str]] = {study_id: set() for study_id in included}
    for link in _read_jsonl(selection_directory / "study-report-links.jsonl"):
        study_id = str(link.get("study_id", ""))
        if study_id in linked:
            linked[study_id].add(str(link.get("report_id", "")))
    actual_ids = {str(item["study_id"]) for item in document["studies"]}
    if not actual_ids.issubset(included):
        raise TaskOutputError("document contains a Study not included by Selection")
    if require_completed and actual_ids != included:
        raise TaskOutputError("completed document must cover every Included Study")
    for study in document["studies"]:
        actual_reports = {item["report_id"] for item in study["report_coverage"]}
        if actual_reports != linked[study["study_id"]]:
            raise TaskOutputError(
                "Report coverage must exactly equal Selection Study–Report links"
            )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TaskOutputError(f"{path.name} must contain JSON objects")
            values.append(value)
    return values
