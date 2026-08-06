from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    AgentRunRequest,
    build_agent_runtime,
    load_agent_runtime_config,
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_RUNTIME_TESTS") != "1",
    reason="set RUN_LIVE_AGENT_RUNTIME_TESTS=1 for a billed live CLI test",
)


def test_live_cli_executes_a_staged_skill(tmp_path: Path) -> None:
    skill = tmp_path / "runtime-smoke"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: runtime-smoke\n"
        "description: Return the input value unchanged for a runtime smoke test.\n"
        "---\n\n"
        "Read `inputs/task-input.json` and return its `value` as `value`.\n",
        encoding="utf-8",
    )
    config = load_agent_runtime_config()
    runtime = build_agent_runtime(config)
    request = AgentRunRequest(
        run_id="live-runtime-smoke",
        prompt="Execute the runtime-smoke Skill.",
        input_data={"value": "smoke"},
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        skill_paths=(skill,),
        timeout_seconds=180,
        enable_web_search=False,
    )

    capabilities = asyncio.run(runtime.check())
    result = asyncio.run(runtime.run(request))

    assert capabilities.model == result.model
    assert result.output == {"value": "smoke"}
