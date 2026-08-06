from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

from benchmark.online_pipeline_v2.Q2Protocol.adapter.projection import (
    project_prediction,
)
from benchmark.online_pipeline_v2.Q2Protocol.adapter.markdown import (
    render_protocol_markdown,
)
from benchmark.online_pipeline_v2.Q2Protocol.adapter.run_manual import (
    build_service_request,
    benchmark_template,
)
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft


def _service_response(protocol) -> dict[str, object]:
    return {
        "artifact_id": "review-1:q2protocol:draft-1",
        "protocol_version": protocol.version,
        "status": "completed",
        "data": TypeAdapter(ProtocolDraft).dump_python(protocol, mode="json"),
        "issues": [],
    }


def test_service_response_projects_to_prediction_schema(protocol) -> None:
    response = _service_response(protocol)

    prediction = project_prediction(
        instance_id="q2protocol_000002",
        service_response=response,
    )

    schema_path = (
        Path(__file__).resolve().parents[3]
        / "benchmark"
        / "online_pipeline_v2"
        / "Q2Protocol"
        / "data"
        / "schemas"
        / "prediction.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(prediction)
    assert prediction["protocol"]["search_strategies"][0]["source"] == "MEDLINE"
    assert "cochrane_rob_1" in prediction["protocol"]["rob_and_reporting_bias"]


def test_benchmark_renders_protocol_markdown_deterministically(protocol) -> None:
    response = _service_response(protocol)

    first = render_protocol_markdown(response)
    second = render_protocol_markdown(response)

    assert first == second
    assert first.startswith("# Q2Protocol Audit")
    assert "# Intervention for adults" in first
    assert "## Review question" in first
    assert "### Search methods for identification of studies" in first
    assert "##### MEDLINE" in first
    assert "## Methodology basis" in first


def test_benchmark_renders_blocked_protocol_audit() -> None:
    markdown = render_protocol_markdown(
        {
            "artifact_id": "review-1:q2protocol:draft-1",
            "protocol_version": "draft-1",
            "status": "blocked",
            "data": None,
            "issues": [
                {
                    "code": "insufficient_scope",
                    "severity": "error",
                    "message": "The topic is too broad.",
                }
            ],
        }
    )

    assert "`blocked`" in markdown
    assert "`insufficient_scope`" in markdown
    assert "No Protocol artifact was produced." in markdown


def test_benchmark_request_explicitly_supplies_its_standard_constraints() -> None:
    request = build_service_request("Intervention for adults")

    standards = request["standards"]
    assert standards["risk_of_bias_tool"] == "cochrane_rob_1"
    assert standards["certainty_approach"] == "GRADE"
    assert {
        item["standard"] for item in standards["methodology_standards"]
    } == {
        "cochrane_handbook",
        "mecir",
        "revman_protocol_template",
        "cochrane_rob_1",
    }


def test_benchmark_request_supplies_default_output_template() -> None:
    request = build_service_request("Intervention for adults")

    assert request["template"] == benchmark_template()
    assert request["template"]["template_id"] == "q2protocol.benchmark.v2"
