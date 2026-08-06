"""Application orchestration for the Q2Protocol professional task."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any, Callable, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, TypeAdapter

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.schema import (
    strict_task_output_schema,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    ArtifactStatus,
    DomainValidationError,
    Provenance,
    TaskCompletion,
)
from ebm_backend.online_pipeline_v2.domain.protocol import (
    MethodologyBasisStatus,
    ProtocolDraft,
    ProtocolStandards,
    ProtocolTemplate,
    Q2ProtocolInput,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskAccessMode,
    TaskExecutorPort,
    TaskOutputError,
    TaskRunRequest,
    TaskRunResult,
    WebAccessPolicy,
)


_PROMPT = (
    "Draft the complete Q2Protocol artifact described by the Skill. "
    "Use the supplied protocol_version as the document version. Work "
    "prospectively, select appropriate methodology where standards are "
    "unconstrained, obey every supplied standards constraint, verify "
    "methodology citations, and do not retrieve a "
    "withheld target Review or historical Protocol."
)


class _AgentQ2ProtocolOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ArtifactStatus
    data: ProtocolDraft | None
    issues: tuple[ArtifactIssue, ...]


_OUTPUT_ADAPTER = TypeAdapter(_AgentQ2ProtocolOutput)


def q2protocol_output_schema(
    protocol_version: str,
    standards: ProtocolStandards | None = None,
) -> dict[str, Any]:
    """Return the strict per-invocation JSON Schema given to the Agent."""
    normalized_version = protocol_version.strip()
    if not normalized_version:
        raise ValueError("protocol_version must not be blank")

    schema = deepcopy(_OUTPUT_ADAPTER.json_schema())
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        raise RuntimeError("Q2Protocol output schema has no definitions")

    protocol_schema = definitions["ProtocolDraft"]
    protocol_schema["properties"]["schema_version"] = {
        "type": "string",
        "const": "protocol-artifact.v2",
    }
    protocol_schema["properties"]["version"] = {
        "type": "string",
        "const": normalized_version,
    }
    protocol_schema["properties"]["profile"] = {
        "type": "string",
        "const": "cochrane_intervention_v1",
    }
    protocol_schema["properties"]["document_status"] = {
        "type": "string",
        "const": "draft",
    }
    if standards is not None:
        if standards.risk_of_bias_tool is not None:
            definitions["RiskOfBiasPlan"]["properties"]["tool"] = {
                "type": "string",
                "const": standards.risk_of_bias_tool,
            }
        if standards.certainty_approach is not None:
            definitions["CertaintyPlan"]["properties"]["approach"] = {
                "type": "string",
                "const": standards.certainty_approach,
            }
    return strict_task_output_schema(schema)


@dataclass(slots=True)
class DraftProtocolTask:
    """Implement DraftProtocolPort through an installed Codex or Claude CLI."""

    executor: TaskExecutorPort
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    timeout_seconds: float = 900.0
    run_id_factory: Callable[[], str] = field(
        default=lambda: f"q2protocol-{uuid4().hex}",
        repr=False,
    )

    def draft(
        self,
        inputs: Q2ProtocolInput,
        protocol_version: str,
    ) -> TaskCompletion[ProtocolDraft]:
        request = TaskRunRequest(
            run_id=self.run_id_factory(),
            prompt=_PROMPT,
            input_data=_input_data(inputs, protocol_version),
            output_schema=q2protocol_output_schema(
                protocol_version,
                inputs.standards,
            ),
            timeout_seconds=self.timeout_seconds,
            access_mode=TaskAccessMode.READ_ONLY,
            enable_web_search=True,
            web_access_policy=self.web_access_policy,
            task_name="q2protocol",
        )
        execution = self.executor.execute(
            request,
            output_adapter=_OUTPUT_ADAPTER,
            error_context=(
                "Agent Q2Protocol output cannot form the domain artifact"
            ),
        )
        result = execution.result
        parsed = execution.output
        if parsed.data is not None:
            _validate_standard_constraints(parsed.data, inputs.standards)
            _validate_template_constraints(parsed.data, inputs.template)
        if parsed.data is not None and parsed.data.version != protocol_version:
            raise TaskOutputError(
                "Agent Protocol version does not match the requested version"
            )
        try:
            return TaskCompletion(
                status=parsed.status,
                data=parsed.data,
                issues=parsed.issues,
                additional_provenance=_provenance(result, parsed.data),
            )
        except DomainValidationError as exc:
            raise TaskOutputError(
                f"Agent Q2Protocol completion is invalid: {exc}"
            ) from exc


def _input_data(
    inputs: Q2ProtocolInput,
    protocol_version: str,
) -> dict[str, object]:
    return {
        "protocol_version": protocol_version,
        "topic_text": inputs.topic_text,
        "topic_kind": inputs.topic_kind.value,
        "scope_notes": list(inputs.scope_notes),
        "standards": _standards_data(inputs.standards),
        "template": (
            TypeAdapter(ProtocolTemplate).dump_python(inputs.template, mode="json")
            if inputs.template is not None
            else None
        ),
        "background_sources": [
            {
                "source_id": source.source_id,
                "source_type": source.source_type,
                "locator": source.locator,
                "excerpt": source.excerpt,
            }
            for source in inputs.background_sources
        ],
    }


def _standards_data(
    standards: ProtocolStandards | None,
) -> dict[str, object] | None:
    if standards is None:
        return None
    return {
        "methodology_standards": [
            {
                "standard": item.standard,
                "title": item.title,
                "version_or_revision": item.version_or_revision,
                "sections": list(item.sections),
                "url": item.url,
            }
            for item in standards.methodology_standards
        ],
        "risk_of_bias_tool": standards.risk_of_bias_tool,
        "certainty_approach": standards.certainty_approach,
        "additional_requirements": list(standards.additional_requirements),
    }


def _validate_standard_constraints(
    protocol: ProtocolDraft,
    standards: ProtocolStandards | None,
) -> None:
    if standards is None:
        return
    if (
        standards.risk_of_bias_tool is not None
        and protocol.methods.risk_of_bias.tool != standards.risk_of_bias_tool
    ):
        raise TaskOutputError(
            "Agent Protocol risk-of-bias tool does not match the supplied "
            "standards constraint"
        )
    if (
        standards.certainty_approach is not None
        and protocol.methods.certainty.approach != standards.certainty_approach
    ):
        raise TaskOutputError(
            "Agent Protocol certainty approach does not match the supplied "
            "standards constraint"
        )
    profile = protocol.methodology_profile
    if profile.basis_status is MethodologyBasisStatus.VERIFIED:
        actual = {item.standard: item for item in profile.authorities}
        mismatched: list[str] = []
        for required in standards.methodology_standards:
            selected = actual.get(required.standard)
            if selected is None or (
                selected.title != required.title
                or selected.version_or_revision != required.version_or_revision
                or selected.sections != required.sections
                or selected.url != required.url
            ):
                mismatched.append(required.standard)
        if mismatched:
            raise TaskOutputError(
                "Agent Protocol methodology basis does not exactly match supplied "
                f"standards: {mismatched}"
            )
    elif profile.basis_status is MethodologyBasisStatus.LLM_FALLBACK:
        referenced = {
            standard
            for decision in profile.decisions
            for standard in decision.authority_standards
        }
        missing = {
            required.standard
            for required in standards.methodology_standards
            if required.standard not in referenced
        }
        if missing:
            raise TaskOutputError(
                "Agent Protocol fallback did not preserve supplied methodology "
                f"constraints: {sorted(missing)}"
            )


def _validate_template_constraints(
    protocol: ProtocolDraft,
    template: ProtocolTemplate | None,
) -> None:
    if template is None:
        return
    document = protocol.document
    if (
        document.template_id != template.template_id
        or document.version_or_revision != template.version_or_revision
        or document.review_type is not template.review_type
        or document.language != template.language
        or document.tense != template.tense
    ):
        raise TaskOutputError(
            "Agent Protocol document does not match the supplied template identity"
        )
    actual = {
        item.section_id: item
        for item in document.sections
    }
    mismatched = []
    for required in template.sections:
        selected = actual.get(required.section_id)
        if selected is None or (
            selected.title != required.title
            or selected.semantic_section is not required.semantic_section
            or selected.order != required.order
            or selected.required is not required.required
        ):
            mismatched.append(required.section_id)
    if mismatched:
        raise TaskOutputError(
            "Agent Protocol document does not preserve supplied template "
            f"sections: {mismatched}"
        )


def _provenance(
    result: TaskRunResult,
    protocol: ProtocolDraft | None,
) -> tuple[Provenance, ...]:
    values: list[Provenance] = [
        Provenance(
            source_id=result.model,
            source_type="agent_runtime_model",
            locator=result.session_id or result.run_id,
        )
    ]
    values.append(
        Provenance(
            source_id=result.run_id,
            source_type="agent_web_access_audit",
            locator=(
                "enabled"
                if result.web_access_audit.enabled
                else "disabled"
            ),
            excerpt=json.dumps(
                {
                    "potential_contamination": (
                        result.web_access_audit.potential_contamination
                    ),
                    "inspected_value_count": (
                        result.web_access_audit.inspected_value_count
                    ),
                    "violation_count": len(
                        result.web_access_audit.violations
                    ),
                },
                sort_keys=True,
            ),
        )
    )
    values.extend(
        Provenance(
            source_id=snapshot.sha256,
            source_type="agent_skill",
            locator=snapshot.name,
        )
        for snapshot in result.skill_snapshots
    )
    if protocol is not None:
        values.extend(
            Provenance(
                source_id=reference.standard,
                source_type="methodology_standard",
                locator=reference.url,
                excerpt=reference.version_or_revision,
            )
            for reference in protocol.methodology_profile.authorities
        )
    return tuple(values)
