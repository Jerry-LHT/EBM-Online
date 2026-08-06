"""Infrastructure execution spec for resumable Evidence Synthesis.

The spec translates the task Port input into a Skill-backed Runtime request
and validates the technical artifact envelope.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable
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
from ebm_backend.online_pipeline_v2.domain.synthesis import (
    EvidenceSynthesisInput,
    EvidenceSynthesisProtocol,
    SynthesisRiskOfBiasEvidence,
    synthesis_risk_of_bias_from_artifact,
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
    EvidenceSynthesisRepository,
    StudyDataCollectionArtifactRepository,
)
from ebm_backend.online_pipeline_v2.application.ports.repositories import (
    WorkSession,
)

from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.evidence_synthesis import (
    MetaAnalysisCalculator,
    SynthesisLedgerError,
    canonical_synthesis_json_bytes,
    parse_synthesis_ledger,
    project_synthesis_csv,
    synthesis_counts,
)


_PROTOCOL_ADAPTER = TypeAdapter(EvidenceSynthesisProtocol)
_ROB_ADAPTER = TypeAdapter(SynthesisRiskOfBiasEvidence)
_PROMPT = (
    "Complete or advance Evidence Synthesis under the synthesize-evidence "
    "Skill. Interpret the complete supplied Protocol content, including "
    "narrative, structured, mixed, and partially empty fields; no individual "
    "field is an execution gate. Work only from that Protocol, the complete "
    "frozen unified Study Data Collection document, and the task-specific "
    "Risk-of-Bias evidence view. "
    "Use meta-compute for every statistical result. Use Web access only for "
    "current official or primary methodology needed to execute the Protocol; "
    "do not retrieve scientific evidence or completed-review answers."
)


class _AgentSynthesisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskWorkStatus
    issues: tuple[ArtifactIssue, ...] = ()
    blocker: str | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> "_AgentSynthesisOutput":
        if self.status is TaskWorkStatus.BLOCKED and not (
            self.blocker and self.blocker.strip()
        ):
            raise ValueError("blocked output requires blocker")
        if self.status is not TaskWorkStatus.BLOCKED and self.blocker is not None:
            raise ValueError("only blocked output may contain blocker")
        return self


_OUTPUT_ADAPTER = TypeAdapter(_AgentSynthesisOutput)


def evidence_synthesis_output_schema() -> dict[str, Any]:
    return strict_task_output_schema(_OUTPUT_ADAPTER.json_schema())


@dataclass(slots=True)
class SynthesizeEvidenceTask:
    executor: TaskExecutorPort
    data_collection_store: StudyDataCollectionArtifactRepository
    synthesis_store: EvidenceSynthesisRepository
    compute_meta_analysis: MetaAnalysisCalculator
    calculate_scalar: MetaAnalysisCalculator
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    timeout_seconds: float = 1800.0
    run_id_factory: Callable[[], str] = field(
        default=lambda: f"evidence-synthesis-{uuid4().hex}",
        repr=False,
    )

    def synthesize(
        self,
        inputs: EvidenceSynthesisInput,
        context: TaskContext,
    ) -> TaskWorkResult:
        collection = self.data_collection_store.resolve(inputs.study_data_collection)
        if collection.artifact.review_id != context.review_id:
            raise ValueError("Study Data Collection review_id does not match")
        if collection.artifact.protocol_version != context.protocol_version:
            raise ValueError("Study Data Collection Protocol version does not match")
        if inputs.risk_of_bias.package_ref.review_id != context.review_id:
            raise ValueError("Risk of Bias review_id does not match")
        if inputs.risk_of_bias.package_ref.protocol_version != context.protocol_version:
            raise ValueError("Risk of Bias Protocol version does not match")
        risk_of_bias = synthesis_risk_of_bias_from_artifact(inputs.risk_of_bias)
        binding = _synthesis_binding(
            inputs,
            context,
            collection.artifact.content_digest,
            risk_of_bias,
        )
        session = self.synthesis_store.begin(
            binding=binding,
            work_id=inputs.work_id,
        )
        try:
            run = self._run(
                inputs=inputs,
                context=context,
                session=session,
                collection_document=collection.document_path,
                risk_of_bias=risk_of_bias,
            )
            return self._persist_result(
                run,
                session,
                collection_document=collection.document_path,
                risk_of_bias=risk_of_bias,
            )
        finally:
            self.synthesis_store.release(session)

    def _run(
        self,
        *,
        inputs: EvidenceSynthesisInput,
        context: TaskContext,
        session: WorkSession,
        collection_document: Path,
        risk_of_bias: SynthesisRiskOfBiasEvidence,
    ) -> tuple[TaskRunResult, _AgentSynthesisOutput]:
        artifacts = {
            "study-data-collection": collection_document,
            "work-binding": session.root / "binding.json",
        }
        if session.checkpoint_path is not None:
            artifacts["prior-checkpoint"] = session.checkpoint_path
        request = TaskRunRequest(
            run_id=self.run_id_factory(),
            prompt=_PROMPT,
            input_data={
                "review_id": context.review_id,
                "protocol_version": context.protocol_version,
                "work_id": session.work_id,
                "protocol": _PROTOCOL_ADAPTER.dump_python(
                    inputs.protocol,
                    mode="json",
                ),
                "study_data_collection": {
                    "artifact_id": inputs.study_data_collection.artifact_id,
                    "document_path": "inputs/artifacts/study-data-collection",
                },
                "risk_of_bias": {
                    "artifact_id": inputs.risk_of_bias.package_ref.package_id,
                    "data": _ROB_ADAPTER.dump_python(
                        risk_of_bias,
                        mode="json",
                    ),
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
                        "name": "synthesis-work",
                        "path": "scripts/synthesis_work.py",
                        "purpose": "initialize, update, and validate the synthesis document",
                    },
                    {
                        "name": "scalar-calculate",
                        "path": "scripts/scalar_calculate.py",
                        "purpose": "perform auditable Decimal scalar transformations",
                    },
                    {
                        "name": "meta-compute",
                        "path": "scripts/meta_compute.py",
                        "purpose": (
                            "compute effects, variances, weights, heterogeneity, "
                            "subgroups, intervals, and tests deterministically"
                        ),
                    },
                    {
                        "name": "synthesis-finalize",
                        "path": "scripts/synthesis_finalize.py",
                        "purpose": "run final quality gates and project official CSVs",
                    },
                ),
            },
            input_artifacts=artifacts,
            output_schema=evidence_synthesis_output_schema(),
            output_artifacts={
                "document": "outputs/synthesis/document.json",
                "data_rows": (f"outputs/synthesis/{context.review_id}-data-rows.csv"),
                "subgroup_estimates": (
                    f"outputs/synthesis/{context.review_id}-subgroup-estimates.csv"
                ),
                "overall_estimates": (
                    "outputs/synthesis/"
                    f"{context.review_id}-overall-estimates-and-settings.csv"
                ),
            },
            timeout_seconds=self.timeout_seconds,
            access_mode=TaskAccessMode.WORKSPACE_WRITE,
            enable_workspace_network=True,
            enable_web_search=True,
            web_access_policy=self.web_access_policy,
            task_name="evidence_synthesis",
        )
        execution = self.executor.execute(
            request,
            output_adapter=_OUTPUT_ADAPTER,
            error_context="Agent Synthesis control output is invalid",
        )
        result = execution.result
        output = execution.output
        return result, output

    def _persist_result(
        self,
        run: tuple[TaskRunResult, _AgentSynthesisOutput],
        session: WorkSession,
        *,
        collection_document: Path,
        risk_of_bias: SynthesisRiskOfBiasEvidence,
    ) -> TaskWorkResult:
        result, output = run
        artifact = result.output_artifacts.get("document")
        if artifact is None:
            raise TaskOutputError("Agent did not produce the Synthesis document")
        require_completed = output.status is TaskWorkStatus.COMPLETED
        try:
            ledger = parse_synthesis_ledger(
                artifact.content,
                expected_binding=session.binding,
                require_completed=require_completed,
                compute=self.compute_meta_analysis,
                calculate_scalar=self.calculate_scalar,
            )
        except SynthesisLedgerError as exc:
            raise TaskOutputError(
                str(exc),
                code="synthesis_document_invalid",
                stage="artifact_validation",
                artifact="outputs/synthesis/document.json",
                contract_version="evidence-synthesis-document.v3",
            ) from exc
        try:
            upstream_warnings = _validate_upstream_references(
                ledger,
                collection_document=collection_document,
                risk_of_bias=risk_of_bias,
            )
        except TaskOutputError as exc:
            raise TaskOutputError(
                str(exc),
                code="synthesis_upstream_reference_invalid",
                stage="relationship_validation",
                artifact="outputs/synthesis/document.json",
                contract_version="evidence-synthesis-document.v3",
            ) from exc
        if ledger["status"] != output.status.value:
            raise TaskOutputError(
                "Synthesis control status does not match ledger status"
            )
        progress = synthesis_counts(ledger)
        if output.status is not TaskWorkStatus.COMPLETED:
            self.synthesis_store.checkpoint(session, artifact.content)
            issues = output.issues
            if output.status is TaskWorkStatus.BLOCKED and not any(
                issue.severity is IssueSeverity.ERROR for issue in issues
            ):
                issues = issues + (
                    ArtifactIssue(
                        code="synthesis_work_blocked",
                        message=output.blocker or "Synthesis work is blocked",
                        severity=IssueSeverity.ERROR,
                    ),
                )
            return TaskWorkResult(
                status=output.status,
                work_id=session.work_id,
                progress=progress,
                issues=issues,
                blocker=output.blocker,
            )
        authoritative = canonical_synthesis_json_bytes(ledger)
        public = {
            f"{session.binding['review_id']}-synthesis.json": authoritative,
            **project_synthesis_csv(ledger),
        }
        deterministic_issues = _deterministic_synthesis_issues(ledger)
        warnings = tuple(
            dict.fromkeys(
                (
                    *output.warnings,
                    *upstream_warnings,
                    *(issue.message for issue in deterministic_issues),
                )
            )
        )
        snapshot = self.synthesis_store.complete(
            session,
            authoritative=authoritative,
            public_files=public,
            counts=progress,
            warnings=warnings,
        )
        return TaskWorkResult(
            status=TaskWorkStatus.COMPLETED,
            artifact=snapshot.artifact,
            progress=progress,
            issues=output.issues
            + tuple(issue for issue in deterministic_issues if issue not in output.issues),
        )


def _synthesis_binding(
    inputs: EvidenceSynthesisInput,
    context: TaskContext,
    collection_digest: str,
    risk_of_bias: SynthesisRiskOfBiasEvidence,
) -> dict[str, str]:
    protocol = _PROTOCOL_ADAPTER.dump_json(inputs.protocol)
    risk = _ROB_ADAPTER.dump_json(risk_of_bias)
    return {
        "review_id": context.review_id,
        "protocol_version": context.protocol_version,
        "protocol_digest": f"sha256:{sha256(protocol).hexdigest()}",
        "study_data_collection_artifact_id": (inputs.study_data_collection.artifact_id),
        "study_data_collection_artifact_digest": collection_digest,
        "risk_of_bias_artifact_id": inputs.risk_of_bias.package_ref.package_id,
        "risk_of_bias_artifact_digest": f"sha256:{sha256(risk).hexdigest()}",
    }


def _artifact_content(result: TaskRunResult, name: str) -> bytes:
    artifact = result.output_artifacts.get(name)
    if artifact is None:
        raise TaskOutputError(f"Agent did not produce required artifact: {name}")
    return artifact.content


def _validate_upstream_references(
    ledger: dict[str, Any],
    *,
    collection_document: Path,
    risk_of_bias: SynthesisRiskOfBiasEvidence,
) -> tuple[str, ...]:
    try:
        collection = json.loads(collection_document.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskOutputError("frozen Study Data Collection is invalid") from exc
    if not isinstance(collection, dict):
        raise TaskOutputError("frozen Study Data Collection must be an object")
    study_ids = {
        str(study["study_id"])
        for study in collection.get("studies", [])
        if isinstance(study, dict) and "study_id" in study
    }
    result_ids_by_study = {
        str(study["study_id"]): {
            str(row["result_id"]): row
            for row in study.get("results", [])
            if isinstance(row, dict) and "result_id" in row
        }
        for study in collection.get("studies", [])
        if isinstance(study, dict) and "study_id" in study
    }
    risk_ids = {item.study_id for item in risk_of_bias.studies}
    warnings: list[str] = []
    for analysis in ledger["analyses"]:
        for representation in analysis["representations"]:
            if representation["study_id"] not in study_ids:
                raise TaskOutputError(
                    "Synthesis representation references unknown collected Study"
                )
            result_rows = result_ids_by_study.get(
                representation["study_id"],
                {},
            )
            if not set(representation["source_result_ids"]).issubset(result_rows):
                raise TaskOutputError(
                    "Synthesis representation references a Result outside " "its Study"
                )
            values = representation["values"]
            for source in representation["result_value_sources"]:
                result_id = source["result_id"]
                source_representation_id = source["representation_id"]
                source_representations = {
                    str(item.get("representation_id")): item
                    for item in result_rows[result_id].get(
                        "analysis_representations", []
                    )
                    if isinstance(item, dict)
                }
                source_representation = source_representations.get(
                    source_representation_id
                )
                if source_representation is None:
                    raise TaskOutputError(
                        "Synthesis projection references an unknown analysis "
                        "representation"
                    )
                try:
                    projected_value = values[source["value_name"]]
                    source_values = _index_sourced_values(
                        source_representation["result"]
                    )
                    source_value = source_values[source["source_value_id"]]["value"]
                except (KeyError, TypeError, ValueError) as exc:
                    raise TaskOutputError(
                        "Synthesis representation references an unknown source value"
                    ) from exc
                if not _same_scalar(projected_value, source_value):
                    raise TaskOutputError(
                        "Synthesis representation value does not match its "
                        "declared upstream value"
                    )
            trace_by_id = {
                str(trace.get("trace_id")): trace
                for trace in analysis.get("calculation_traces", [])
                if isinstance(trace, dict)
            }
            for source in representation.get("calculated_value_sources", []):
                trace = trace_by_id.get(str(source.get("trace_id")))
                if trace is None or trace.get("tool") != "scalar-calculate":
                    raise TaskOutputError(
                        "Synthesis scalar projection references an unknown scalar trace"
                    )
                trace_inputs = trace.get("input", {}).get("inputs")
                if not isinstance(trace_inputs, dict):
                    raise TaskOutputError("Synthesis scalar trace inputs are invalid")
                for input_projection in source.get("inputs", []):
                    result_id = str(input_projection["result_id"])
                    source_representations = {
                        str(item.get("representation_id")): item
                        for item in result_rows[result_id].get(
                            "analysis_representations", []
                        )
                        if isinstance(item, dict)
                    }
                    source_representation = source_representations.get(
                        str(input_projection["representation_id"])
                    )
                    if source_representation is None:
                        raise TaskOutputError(
                            "Synthesis scalar input references an unknown analysis representation"
                        )
                    try:
                        source_value = _index_sourced_values(
                            source_representation["result"]
                        )[input_projection["source_value_id"]]["value"]
                    except (KeyError, TypeError, ValueError) as exc:
                        raise TaskOutputError(
                            "Synthesis scalar input references an unknown source value"
                        ) from exc
                    input_name = str(input_projection["input_name"])
                    if input_name not in trace_inputs:
                        raise TaskOutputError(
                            "Synthesis scalar trace input is missing"
                        )
                    if not _same_scalar(trace_inputs[input_name], source_value):
                        raise TaskOutputError(
                            "Synthesis scalar input does not match its declared "
                            "upstream value"
                        )
                try:
                    calculated_value = trace["output"]["outputs"][
                        source["output_name"]
                    ]
                    projected_value = representation["values"][source["value_name"]]
                except (KeyError, TypeError) as exc:
                    raise TaskOutputError(
                        "Synthesis calculated value source is invalid"
                    ) from exc
                if not _same_scalar(projected_value, calculated_value):
                    representation["values"][source["value_name"]] = calculated_value
                    warning = (
                        "Synthesis scalar projection differed from deterministic "
                        "calculator output; the calculator output is authoritative."
                    )
                    warnings.append(warning)
                    _append_deterministic_synthesis_issue(
                        ledger,
                        code="synthesis_scalar_value_normalized",
                        message=warning,
                    )
        for contribution in analysis["contributions"]:
            if contribution["study_id"] not in study_ids:
                raise TaskOutputError(
                    "Synthesis contribution references unknown collected Study"
                )
        for risk_ref in analysis["risk_of_bias_refs"]:
            if risk_ref["study_id"] not in risk_ids:
                raise TaskOutputError(
                    "Synthesis Risk of Bias reference is not in the upstream artifact"
                )
    return tuple(dict.fromkeys(warnings))


def _append_deterministic_synthesis_issue(
    ledger: Mapping[str, Any],
    *,
    code: str,
    message: str,
) -> None:
    issues = ledger.get("issues")
    if not isinstance(issues, list):
        raise TaskOutputError("Synthesis issues must be a list")
    candidate = {
        "code": code,
        "message": message,
        "severity": "warning",
        "provenance": [],
    }
    if candidate not in issues:
        issues.append(candidate)


def _deterministic_synthesis_issues(
    ledger: Mapping[str, Any],
) -> tuple[ArtifactIssue, ...]:
    codes = {
        "synthesis_calculation_trace_normalized",
        "synthesis_calculated_value_normalized",
        "synthesis_scalar_value_normalized",
    }
    result: list[ArtifactIssue] = []
    for raw in ledger.get("issues", []):
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


def _index_sourced_values(value: object) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}

    def visit(item: object) -> None:
        if isinstance(item, dict):
            if set(item) == {"value_id", "value", "origin"}:
                value_id = item.get("value_id")
                if not isinstance(value_id, str) or not value_id or value_id in indexed:
                    raise ValueError("source value ids must be unique and nonblank")
                indexed[value_id] = item
                return
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return indexed


def _same_scalar(left: object, right: object) -> bool:
    if isinstance(left, int | float) and isinstance(right, int | float):
        return abs(float(left) - float(right)) <= 1e-12 * max(
            1.0,
            abs(float(left)),
            abs(float(right)),
        )
    if isinstance(left, str) and isinstance(right, int | float):
        try:
            return abs(float(left) - float(right)) <= 1e-12 * max(
                1.0,
                abs(float(left)),
                abs(float(right)),
            )
        except ValueError:
            return False
    if isinstance(right, str) and isinstance(left, int | float):
        return _same_scalar(right, left)
    return left == right
