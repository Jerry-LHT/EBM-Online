from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import pytest
from pydantic import TypeAdapter

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactStatus,
    IssueSeverity,
)
from ebm_backend.online_pipeline_v2.domain.protocol import (
    MethodologyBasisStatus,
    MethodologyDecision,
    MethodologyDecisionOrigin,
    MethodologyRequirement,
    ProtocolDraft,
    ProtocolTemplate,
    ProtocolTemplateSection,
    ProtocolReviewType,
    ProtocolSemanticSection,
    ProtocolStandards,
    Q2ProtocolInput,
    TopicKind,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    AgentAccessMode,
    AgentProvider,
    AgentRunRequest,
    AgentRunResult,
    AgentSkillSnapshot,
    WebAccessAudit,
    WebAccessPolicy,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.errors import (
    AgentProcessError,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskOutputError,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution import (
    AgentTaskExecutorAdapter,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.q2protocol import (
    DraftProtocolTask,
)


_PROTOCOL_ADAPTER = TypeAdapter(ProtocolDraft)
_SKILL_ROOT = (
    Path(__file__).parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/"
    "agent_execution/skills/q2protocol/draft-q2protocol"
)


def _executor(runtime) -> AgentTaskExecutorAdapter:
    return AgentTaskExecutorAdapter(runtime, (_SKILL_ROOT,))


class FakeRuntime:
    provider = AgentProvider.OPENAI

    def __init__(
        self,
        output: Mapping[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.output = output
        self.error = error
        self.requests: list[AgentRunRequest] = []

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.output is not None
        return AgentRunResult(
            provider=self.provider,
            model="openai/gpt-5.6-terra",
            run_id=request.run_id,
            session_id="session-1",
            output=self.output,
            events=(),
            stderr="",
            duration_seconds=1.0,
            web_access_audit=WebAccessAudit(
                enabled=True,
                potential_contamination=False,
                inspected_value_count=0,
                violations=(),
            ),
            skill_snapshots=(
                AgentSkillSnapshot(
                    name="draft-q2protocol",
                    sha256="a" * 64,
                ),
            ),
        )


def _completed_output(protocol: ProtocolDraft) -> dict[str, object]:
    return {
        "status": "completed",
        "data": _PROTOCOL_ADAPTER.dump_python(protocol, mode="json"),
        "issues": [],
    }


def _inputs() -> Q2ProtocolInput:
    return Q2ProtocolInput(
        topic_text="Intervention for adults",
        topic_kind=TopicKind.TITLE,
    )


def test_adapter_builds_fixed_read_only_agent_request(
    protocol: ProtocolDraft,
) -> None:
    runtime = FakeRuntime(_completed_output(protocol))
    policy = WebAccessPolicy(blocked_identifiers=("hidden-id",))
    adapter = DraftProtocolTask(
        executor=_executor(runtime),
        web_access_policy=policy,
        run_id_factory=lambda: "q2protocol-test",
    )

    completion = adapter.draft(_inputs(), protocol.version)
    request = runtime.requests[0]

    assert completion.status is ArtifactStatus.COMPLETED
    assert completion.data == protocol
    assert request.access_mode is AgentAccessMode.READ_ONLY
    assert request.enable_web_search is True
    assert request.web_access_policy is policy
    assert request.skill_paths[0].name == "draft-q2protocol"
    assert request.input_data["standards"] is None
    assert request.input_data["template"] is None
    assert "methodology_options" not in request.input_data
    assert "rob_version" not in request.input_data
    assert (
        request.output_schema["$defs"]["RiskOfBiasPlan"]["properties"]["tool"]["type"]
        == "string"
    )
    assert (
        "const"
        not in request.output_schema["$defs"]["RiskOfBiasPlan"]["properties"]["tool"]
    )
    assert (
        request.output_schema["$defs"]["ProtocolDraft"]["properties"]["version"][
            "const"
        ]
        == protocol.version
    )
    assert request.output_schema["type"] == "object"
    _assert_strict_object_schemas(request.output_schema)
    assert not _contains_key(request.output_schema, "default")
    for keyword in (
        "allOf",
        "not",
        "dependentRequired",
        "dependentSchemas",
        "if",
        "then",
        "else",
    ):
        assert not _contains_key(request.output_schema, keyword)
    provenance_types = {item.source_type for item in completion.additional_provenance}
    assert provenance_types == {
        "agent_runtime_model",
        "agent_skill",
        "agent_web_access_audit",
        "methodology_standard",
    }
    audit = next(
        item
        for item in completion.additional_provenance
        if item.source_type == "agent_web_access_audit"
    )
    assert audit.locator == "enabled"
    assert '"potential_contamination": false' in (audit.excerpt or "")


def test_adapter_applies_partial_standard_constraints(
    protocol: ProtocolDraft,
) -> None:
    standards = ProtocolStandards(
        methodology_standards=(
            MethodologyRequirement(
                standard="cochrane_handbook",
                title=protocol.methodology_basis[0].title,
                version_or_revision=protocol.methodology_basis[0].version_or_revision,
                sections=protocol.methodology_basis[0].sections,
                url=protocol.methodology_basis[0].url,
            ),
        ),
        risk_of_bias_tool="cochrane_rob_1",
        certainty_approach="GRADE",
    )
    inputs = Q2ProtocolInput(
        topic_text="Intervention for adults",
        topic_kind=TopicKind.TITLE,
        standards=standards,
    )
    runtime = FakeRuntime(_completed_output(protocol))
    adapter = DraftProtocolTask(
        executor=_executor(runtime),
        run_id_factory=lambda: "q2protocol-test",
    )

    adapter.draft(inputs, protocol.version)
    request = runtime.requests[0]

    assert request.input_data["standards"]["risk_of_bias_tool"] == "cochrane_rob_1"
    assert (
        request.output_schema["$defs"]["RiskOfBiasPlan"]["properties"]["tool"][
            "const"
        ]
        == "cochrane_rob_1"
    )
    assert (
        request.output_schema["$defs"]["CertaintyPlan"]["properties"]["approach"][
            "const"
        ]
        == "GRADE"
    )


def test_adapter_serializes_and_enforces_supplied_template(
    protocol: ProtocolDraft,
) -> None:
    template = ProtocolTemplate(
        template_id=protocol.document.template_id,
        version_or_revision=protocol.document.version_or_revision,
        review_type=ProtocolReviewType.INTERVENTION,
        language=protocol.document.language,
        tense=protocol.document.tense,
        sections=tuple(
            ProtocolTemplateSection(
                section_id=item.section_id,
                title=item.title,
                semantic_section=item.semantic_section,
                order=item.order,
                required=item.required,
            )
            for item in protocol.document.sections
        ),
    )
    inputs = Q2ProtocolInput(
        topic_text="Intervention for adults",
        topic_kind=TopicKind.TITLE,
        template=template,
    )
    runtime = FakeRuntime(_completed_output(protocol))
    adapter = DraftProtocolTask(
        executor=_executor(runtime),
        run_id_factory=lambda: "q2protocol-test",
    )

    adapter.draft(inputs, protocol.version)

    assert runtime.requests[0].input_data["template"]["sections"][0] == {
        "section_id": "title",
        "title": "Title",
        "semantic_section": "title",
        "order": 0,
        "required": True,
    }

    mismatched = replace(
        protocol,
        document=replace(protocol.document, template_id="wrong-template"),
    )
    adapter = DraftProtocolTask(
        executor=_executor(FakeRuntime(_completed_output(mismatched))),
        run_id_factory=lambda: "q2protocol-test",
    )
    with pytest.raises(TaskOutputError, match="template identity"):
        adapter.draft(inputs, protocol.version)


def test_adapter_rejects_methodology_reference_with_changed_revision(
    protocol: ProtocolDraft,
) -> None:
    required = protocol.methodology_basis[0]
    standards = ProtocolStandards(
        methodology_standards=(
            MethodologyRequirement(
                standard=required.standard,
                title=required.title,
                version_or_revision=required.version_or_revision,
                sections=required.sections,
                url=required.url,
            ),
        )
    )
    changed = replace(
        protocol,
        methodology_profile=replace(
            protocol.methodology_profile,
            authorities=(
                replace(required, version_or_revision="Different revision"),
                *protocol.methodology_basis[1:],
            ),
        ),
    )
    adapter = DraftProtocolTask(
        executor=_executor(FakeRuntime(_completed_output(changed))),
        run_id_factory=lambda: "q2protocol-test",
    )

    with pytest.raises(TaskOutputError, match="exactly match"):
        adapter.draft(
            Q2ProtocolInput(
                topic_text="Intervention for adults",
                topic_kind=TopicKind.TITLE,
                standards=standards,
            ),
            protocol.version,
        )


def test_adapter_accepts_agent_selected_standard_when_unconstrained(
    protocol: ProtocolDraft,
) -> None:
    selected = replace(
        protocol,
        methods=replace(
            protocol.methods,
            risk_of_bias=replace(
                protocol.methods.risk_of_bias,
                tool="cochrane_rob_2",
            ),
        ),
    )
    adapter = DraftProtocolTask(
        executor=_executor(FakeRuntime(_completed_output(selected))),
        run_id_factory=lambda: "q2protocol-test",
    )

    completion = adapter.draft(_inputs(), protocol.version)

    assert completion.data is not None
    assert completion.data.methods.risk_of_bias.tool == "cochrane_rob_2"


def test_adapter_accepts_coherent_protocol_with_llm_methodology_fallback(
    protocol: ProtocolDraft,
) -> None:
    fallback = replace(
        protocol,
        methodology_profile=replace(
            protocol.methodology_profile,
            authorities=(),
            basis_status=MethodologyBasisStatus.LLM_FALLBACK,
            fallback_model="openai/gpt-5.6-terra",
            fallback_note="Official guidance was unavailable and remains unverified.",
        ),
    )
    adapter = DraftProtocolTask(
        executor=_executor(FakeRuntime(_completed_output(fallback))),
        run_id_factory=lambda: "q2protocol-test",
    )

    completion = adapter.draft(_inputs(), protocol.version)

    assert completion.status is ArtifactStatus.COMPLETED
    assert completion.data is not None
    assert completion.data.methodology_profile.basis_status is MethodologyBasisStatus.LLM_FALLBACK


def test_adapter_accepts_supplied_standards_with_llm_methodology_fallback(
    protocol: ProtocolDraft,
) -> None:
    standards = ProtocolStandards(
        methodology_standards=(
            MethodologyRequirement(
                standard="cochrane_handbook",
                title="Cochrane Handbook",
                version_or_revision="Current online revision",
                sections=("Methods",),
                url="https://example.test/handbook",
            ),
        ),
        risk_of_bias_tool="cochrane_rob_1",
        certainty_approach="GRADE",
    )
    fallback = replace(
        protocol,
        methodology_profile=replace(
            protocol.methodology_profile,
            decisions=(
                MethodologyDecision(
                    decision_id="fallback-method",
                    topic="Review methodology",
                    decision="Use the supplied standard provisionally.",
                    origin=MethodologyDecisionOrigin.SUPPLIED,
                    rationale="The authority was inaccessible.",
                    authority_standards=("cochrane_handbook",),
                ),
            ),
            authorities=(),
            basis_status=MethodologyBasisStatus.LLM_FALLBACK,
            fallback_model="openai/gpt-5.6-terra",
            fallback_note="Official guidance was unavailable.",
        ),
    )
    completion = DraftProtocolTask(
        executor=_executor(FakeRuntime(_completed_output(fallback))),
        run_id_factory=lambda: "q2protocol-test",
    ).draft(
        Q2ProtocolInput(
            topic_text="Intervention for adults",
            topic_kind=TopicKind.TITLE,
            standards=standards,
        ),
        protocol.version,
    )

    assert completion.status is ArtifactStatus.COMPLETED


def test_adapter_rejects_output_that_violates_standard_constraint(
    protocol: ProtocolDraft,
) -> None:
    mismatched = replace(
        protocol,
        methods=replace(
            protocol.methods,
            risk_of_bias=replace(
                protocol.methods.risk_of_bias,
                tool="cochrane_rob_2",
            ),
        ),
    )
    inputs = Q2ProtocolInput(
        topic_text="Intervention for adults",
        topic_kind=TopicKind.TITLE,
        standards=ProtocolStandards(risk_of_bias_tool="cochrane_rob_1"),
    )
    adapter = DraftProtocolTask(
        executor=_executor(FakeRuntime(_completed_output(mismatched))),
        run_id_factory=lambda: "q2protocol-test",
    )

    with pytest.raises(TaskOutputError, match="risk-of-bias tool"):
        adapter.draft(inputs, protocol.version)


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            _contains_key(nested, key) for nested in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(nested, key) for nested in value)
    return False


def _assert_strict_object_schemas(value: object) -> None:
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            assert value.get("additionalProperties") is False
            assert value.get("required") == list(properties)
        for nested in value.values():
            _assert_strict_object_schemas(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_strict_object_schemas(nested)


def test_adapter_rejects_missing_methodology_profile(
    protocol: ProtocolDraft,
) -> None:
    output = _completed_output(protocol)
    assert isinstance(output["data"], dict)
    output["data"].pop("methodology_profile")
    adapter = DraftProtocolTask(
        executor=_executor(FakeRuntime(output)),
        run_id_factory=lambda: "q2protocol-test",
    )

    with pytest.raises(TaskOutputError, match="domain artifact"):
        adapter.draft(_inputs(), protocol.version)


def test_adapter_maps_agent_blocked_completion() -> None:
    output = {
        "status": "blocked",
        "data": None,
        "issues": [
            {
                "code": "insufficient_scope",
                "message": "The topic cannot support a usable Protocol.",
                "severity": "error",
                "provenance": [],
            }
        ],
    }
    adapter = DraftProtocolTask(
        executor=_executor(FakeRuntime(output)),
        run_id_factory=lambda: "q2protocol-test",
    )

    completion = adapter.draft(_inputs(), "protocol-1")

    assert completion.status is ArtifactStatus.BLOCKED
    assert completion.data is None
    assert completion.issues[0].severity is IssueSeverity.ERROR


def test_adapter_does_not_convert_runtime_failure_to_business_status() -> None:
    failure = AgentProcessError(
        provider=AgentProvider.OPENAI,
        returncode=1,
        stderr="failed",
    )
    adapter = DraftProtocolTask(
        executor=_executor(FakeRuntime(error=failure)),
        run_id_factory=lambda: "q2protocol-test",
    )

    with pytest.raises(AgentProcessError):
        adapter.draft(_inputs(), "protocol-1")
