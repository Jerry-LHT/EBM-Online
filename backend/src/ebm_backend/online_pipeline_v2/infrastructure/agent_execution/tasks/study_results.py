"""Infrastructure execution spec for resumable Study Results extraction.

The spec owns Agent-visible request construction and deterministic output
decoding; the Application boundary owns the public task Port.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.schema import (
    strict_task_output_schema,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    IssueSeverity,
    TaskContext,
    TaskWorkResult,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.study_data import (
    StudyResultsInput,
    StudyResultsProtocol,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskAccessMode,
    TaskExecutorPort,
    TaskOutputError,
    TaskRunRequest,
    TaskRunResult,
    WebAccessPolicy,
)
from ebm_backend.online_pipeline_v2.application.ports.repositories import (
    SelectionPackageRepository,
)
from ebm_backend.online_pipeline_v2.application.ports.repositories import (
    StudyResultsRepository,
    WorkSession,
)

from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.study_results import (
    ResultCalculator,
    ResultsLedgerError,
    parse_results_document,
    results_counts,
    validate_completed_projections,
)


_PROTOCOL_ADAPTER = TypeAdapter(StudyResultsProtocol)
_PROMPT = (
    "Complete or advance the Study Results work under the extract-study-results "
    "Skill. Inspect only legitimate linked Report evidence, use the declared "
    "deterministic tools for document operations and calculations, and return "
    "only the compact control result. Never use a completed review, benchmark "
    "answer, or model-generated arithmetic."
)
class _AgentResultsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskWorkStatus
    issues: tuple[ArtifactIssue, ...] = ()
    blocker: str | None = None
    warnings: tuple[str, ...] = ()
    human_independent_extraction_satisfied: bool = False

    @model_validator(mode="after")
    def validate_status(self) -> "_AgentResultsOutput":
        if self.human_independent_extraction_satisfied:
            raise ValueError("automated runs cannot claim human independent extraction")
        if self.status is TaskWorkStatus.BLOCKED and not (
            self.blocker and self.blocker.strip()
        ):
            raise ValueError("blocked output requires blocker")
        if self.status is not TaskWorkStatus.BLOCKED and self.blocker is not None:
            raise ValueError("only blocked output may contain blocker")
        return self


_OUTPUT_ADAPTER = TypeAdapter(_AgentResultsOutput)


def study_results_output_schema() -> dict[str, Any]:
    return strict_task_output_schema(_OUTPUT_ADAPTER.json_schema())


@dataclass(frozen=True, slots=True)
class _ResultsRun:
    role: str
    result: TaskRunResult
    output: _AgentResultsOutput


@dataclass(slots=True)
class CollectStudyResultsTask:
    executor: TaskExecutorPort
    selection_package_store: SelectionPackageRepository
    results_store: StudyResultsRepository
    calculate_result: ResultCalculator
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    timeout_seconds: float = 1800.0
    run_id_factory: Callable[[str], str] = field(
        default=lambda role: f"study-results-{role}-{uuid4().hex}",
        repr=False,
    )

    def collect(
        self,
        inputs: StudyResultsInput,
        context: TaskContext,
    ) -> TaskWorkResult:
        self.selection_package_store.validate(inputs.selection_package)
        selection_directory = self.selection_package_store.resolve_manifest(
            inputs.selection_package
        ).parent
        binding = _results_binding(inputs, context)
        session = self.results_store.begin(
            binding=binding,
            work_id=inputs.work_id,
        )
        try:
            canonical = self._run(
                role="primary-agent",
                prompt=_PROMPT,
                inputs=inputs,
                context=context,
                session=session,
                selection_directory=selection_directory,
            )
            return self._persist_result(
                canonical,
                session,
                selection_directory,
            )
        finally:
            self.results_store.release(session)

    def _run(
        self,
        *,
        role: str,
        prompt: str,
        inputs: StudyResultsInput,
        context: TaskContext,
        session: WorkSession,
        selection_directory: Path,
    ) -> _ResultsRun:
        artifacts: dict[str, Path] = {
            "selection-package": selection_directory,
            "work-binding": session.root / "binding.json",
        }
        if session.checkpoint_path is not None:
            artifacts["prior-checkpoint"] = session.checkpoint_path
        request = TaskRunRequest(
            run_id=self.run_id_factory(role),
            prompt=prompt,
            input_data={
                "review_id": context.review_id,
                "protocol_version": context.protocol_version,
                "work_id": session.work_id,
                "agent_role": role,
                "review_mode": "single_agent",
                "protocol": _PROTOCOL_ADAPTER.dump_python(
                    inputs.protocol,
                    mode="json",
                ),
                "selection_package": {
                    "path": "inputs/artifacts/selection-package",
                    "package_id": inputs.selection_package.package_id,
                    "content_digest": inputs.selection_package.content_digest,
                },
                "prior_checkpoint": (
                    "inputs/artifacts/prior-checkpoint"
                    if session.checkpoint_path is not None
                    else None
                ),
                "binding": dict(session.binding),
                "binding_path": "inputs/artifacts/work-binding",
                "declared_tools": (
                    {
                        "name": "result-work",
                        "path": "scripts/result_work.py",
                        "purpose": "initialize, update, and validate the Results document",
                    },
                    {
                        "name": "result-calculator",
                        "path": "scripts/result_calculator.py",
                        "purpose": "perform deterministic numeric transformations",
                    },
                    {
                        "name": "result-finalize",
                        "path": "scripts/result_finalize.py",
                        "purpose": "finalize canonical JSON and deterministic projections",
                    },
                ),
            },
            input_artifacts=artifacts,
            output_schema=study_results_output_schema(),
            output_artifacts={
                "document": (
                    f"outputs/results/{context.review_id}-study-results.json"
                ),
                "projection_summary": "outputs/results/projection-summary.json",
                "study_arms": (f"outputs/results/{context.review_id}-study-arms.csv"),
                "study_results": (
                    f"outputs/results/{context.review_id}-study-results.csv"
                ),
            },
            timeout_seconds=self.timeout_seconds,
            access_mode=TaskAccessMode.WORKSPACE_WRITE,
            enable_workspace_network=True,
            enable_web_search=True,
            web_access_policy=self.web_access_policy,
            task_name="study_data_collection.results",
        )
        execution = self.executor.execute(
            request,
            output_adapter=_OUTPUT_ADAPTER,
            error_context="Agent Results control output is invalid",
        )
        result = execution.result
        output = execution.output
        return _ResultsRun(role=role, result=result, output=output)

    def _persist_result(
        self,
        run: _ResultsRun,
        session: WorkSession,
        selection_directory: Path,
    ) -> TaskWorkResult:
        artifact = run.result.output_artifacts.get("document")
        if artifact is None:
            raise TaskOutputError("Agent did not produce the Study Results document")
        require_completed = run.output.status is TaskWorkStatus.COMPLETED
        try:
            document = parse_results_document(
                artifact.content,
                expected_binding=session.binding,
                require_completed=require_completed,
                calculate=self.calculate_result,
            )
        except ResultsLedgerError as exc:
            raise TaskOutputError(str(exc)) from exc
        _validate_selection_identity(
            document,
            selection_directory,
            require_completed=require_completed,
        )
        if document["status"] != run.output.status.value:
            raise TaskOutputError(
                "Results control status does not match document status"
            )
        progress = results_counts(document)
        if run.output.status is not TaskWorkStatus.COMPLETED:
            self.results_store.checkpoint(session, artifact.content)
            issues = run.output.issues
            if run.output.status is TaskWorkStatus.BLOCKED and not any(
                issue.severity is IssueSeverity.ERROR for issue in issues
            ):
                issues = issues + (
                    ArtifactIssue(
                        code="results_work_blocked",
                        message=run.output.blocker or "Results work is blocked",
                        severity=IssueSeverity.ERROR,
                    ),
                )
            return TaskWorkResult(
                status=run.output.status,
                work_id=session.work_id,
                progress=progress,
                issues=issues,
                blocker=run.output.blocker,
            )

        csvs = {
            f"{session.binding['review_id']}-study-arms.csv": _artifact_content(
                run.result,
                "study_arms",
            ),
            f"{session.binding['review_id']}-study-results.csv": _artifact_content(
                run.result,
                "study_results",
            ),
        }
        try:
            deterministic_summary = validate_completed_projections(
                document,
                authoritative=artifact.content,
                public_csvs=csvs,
            )
            try:
                submitted_summary = json.loads(
                    _artifact_content(
                        run.result,
                        "projection_summary",
                    ).decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ResultsLedgerError(
                    "projection summary must be UTF-8 JSON"
                ) from exc
            if submitted_summary != deterministic_summary:
                raise ResultsLedgerError(
                    "projection summary does not match deterministic projection"
                )
        except ResultsLedgerError as exc:
            raise TaskOutputError(str(exc)) from exc
        warnings = tuple(
            dict.fromkeys(
                run.output.warnings
                + (
                    "Automated Agent execution does not satisfy Cochrane "
                    "human independent duplicate extraction.",
                )
            )
        )
        snapshot = self.results_store.complete(
            session,
            authoritative=artifact.content,
            public_files={
                f"{session.binding['review_id']}-study-results.json": artifact.content,
                **csvs,
            },
            projection_summary=deterministic_summary,
            counts=progress,
            warnings=warnings,
        )
        return TaskWorkResult(
            status=TaskWorkStatus.COMPLETED,
            artifact=snapshot.artifact,
            progress=progress,
            issues=run.output.issues,
        )


def _results_binding(
    inputs: StudyResultsInput,
    context: TaskContext,
) -> dict[str, str]:
    protocol_json = _PROTOCOL_ADAPTER.dump_json(inputs.protocol)
    return {
        "review_id": context.review_id,
        "protocol_version": context.protocol_version,
        "protocol_digest": f"sha256:{sha256(protocol_json).hexdigest()}",
        "selection_package_id": inputs.selection_package.package_id,
        "selection_package_digest": inputs.selection_package.content_digest,
    }




def _artifact_content(result: TaskRunResult, name: str) -> bytes:
    artifact = result.output_artifacts.get(name)
    if artifact is None:
        raise TaskOutputError(f"Agent did not produce required artifact: {name}")
    return artifact.content


def _validate_selection_identity(
    ledger: Mapping[str, Any],
    selection_directory: Path,
    *,
    require_completed: bool,
) -> None:
    decisions = _read_jsonl(selection_directory / "study-decisions.jsonl")
    studies = {
        str(item["study_id"]): item
        for item in _read_jsonl(selection_directory / "studies.jsonl")
    }
    included = {
        str(item["study_id"])
        for item in decisions
        if item.get("classification") == "included"
    }
    if not included.issubset(studies):
        raise TaskOutputError(
            "Selection Package has an included decision for an unknown Study"
        )
    linked_reports: dict[str, set[str]] = {study_id: set() for study_id in included}
    for link in _read_jsonl(selection_directory / "study-report-links.jsonl"):
        study_id = str(link.get("study_id", ""))
        if study_id in linked_reports:
            linked_reports[study_id].add(str(link.get("report_id", "")))
    ledger_ids = {str(item["study_id"]) for item in ledger["studies"]}
    if not ledger_ids.issubset(included):
        raise TaskOutputError(
            "Results ledger contains a Study not included by Study Selection"
        )
    if require_completed and ledger_ids != included:
        raise TaskOutputError(
            "completed Results ledger must cover every included Study"
        )
    for study in ledger["studies"]:
        actual = {str(item["report_id"]) for item in study["report_coverage"]}
        expected = linked_reports[str(study["study_id"])]
        if actual != expected:
            raise TaskOutputError(
                "Results report coverage must equal the Study-Report links"
            )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TaskOutputError(
                f"Selection collection {path.name} must contain objects"
            )
        values.append(value)
    return values
