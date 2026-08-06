from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactStatus,
    TaskCompletion,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    WebAccessPolicy,
    load_web_access_policy,
)
from ebm_backend.online_pipeline_v2.interfaces.api import dependencies
from ebm_backend.online_pipeline_v2.interfaces.api.main import app


class _FakeUseCase:
    def __init__(self, protocol) -> None:
        self.protocol = protocol

    def execute(self, invocation):
        from ebm_backend.online_pipeline_v2.domain.common import build_artifact

        return build_artifact(
            context=invocation.context,
            task=invocation.context and invocation_task(),
            data=self.protocol,
            provenance=invocation.provenance,
            status=ArtifactStatus.COMPLETED,
        )


def invocation_task():
    from ebm_backend.online_pipeline_v2.domain.common import TaskName

    return TaskName.Q2PROTOCOL


def test_web_policy_loader_defaults_enabled_and_loads_hidden_rules(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("AGENT_WEB_POLICY_PATH", raising=False)
    assert load_web_access_policy() == WebAccessPolicy()
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "blocked_urls": ["https://example.test/answer"],
                "blocked_domains": [],
                "blocked_identifiers": ["hidden-id"],
            }
        ),
        encoding="utf-8",
    )

    policy = load_web_access_policy(policy_path)

    assert policy.enabled is True
    assert policy.blocked_urls == ("https://example.test/answer",)
    assert policy.blocked_identifiers == ("hidden-id",)


def test_q2protocol_http_returns_only_structured_artifact(
    protocol,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        dependencies,
        "get_q2protocol_use_case",
        lambda: _FakeUseCase(protocol),
    )
    response = TestClient(app).post(
        "/v2/tasks/q2protocol",
        json={
            "review_id": "review-1",
            "protocol_version": protocol.version,
            "provenance": [
                {"source_id": "question-1", "source_type": "user_input"}
            ],
            "topic_text": protocol.title,
            "topic_kind": "title",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["title"] == protocol.title
    assert "rendered_markdown" not in body
