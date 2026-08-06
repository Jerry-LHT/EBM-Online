from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from typing import Callable

import pytest

from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    AgentProvider,
    AgentExecutionStatus,
    AgentRunRequest,
    AgentRunResult,
    AgentRuntimeConfig,
    ClaudeCliRuntime,
    CodexCliRuntime,
    WebAccessPolicy,
    WorkspaceRetention,
    build_agent_runtime,
    DebugBundleStore,
    JsonRunStore,
    make_responses_strict_schema,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.web_access_policy import (
    WebAccessAudit,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.contracts import (
    ProcessResult,
    ProcessSpec,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.configuration import (
    runtime_config_from_mapping,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.errors import (
    AgentConfigurationError,
    AgentOutputError,
    AgentOutputSchemaError,
    AgentProcessError,
    AgentProcessTimeoutError,
    AgentProviderMismatchError,
    AgentSkillError,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.process import (
    SubprocessRunner,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.skill_loader import (
    load_skill,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.workspace import (
    WorkspaceManager,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.web_access_policy import (
    audit_web_access,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.debug import main as debug_main


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

_OPENAI_MODEL = "openai/gpt-5.6-terra"
_OPENAI_BASE_URL = "https://rehdasu.cn/v1"
_ANTHROPIC_MODEL = "anthropic/claude-sonnet-5"
_ANTHROPIC_BASE_URL = "https://api.anthropic.com"


def _runtime_config(
    provider: AgentProvider,
    api_key: str,
) -> AgentRuntimeConfig:
    if provider is AgentProvider.OPENAI:
        model = _OPENAI_MODEL
        base_url = _OPENAI_BASE_URL
    else:
        model = _ANTHROPIC_MODEL
        base_url = _ANTHROPIC_BASE_URL
    return AgentRuntimeConfig(provider, api_key, model, base_url)


def _make_skill(tmp_path: Path, name: str = "test-skill") -> Path:
    skill = tmp_path / name
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: Return a structured test answer.\n"
        "---\n\n"
        "# Instructions\n\n"
        "Read the supplied input and return the requested JSON.\n",
        encoding="utf-8",
    )
    return skill


def _request(tmp_path: Path, *, run_id: str = "run-1") -> AgentRunRequest:
    return AgentRunRequest(
        run_id=run_id,
        prompt="Return the answer.",
        input_data={"question": "test"},
        output_schema=OUTPUT_SCHEMA,
        skill_paths=(_make_skill(tmp_path),),
        enable_web_search=False,
    )


class FakeProcessRunner:
    def __init__(
        self,
        callback: Callable[[ProcessSpec], ProcessResult],
    ) -> None:
        self.callback = callback
        self.specs: list[ProcessSpec] = []

    async def run(self, spec: ProcessSpec) -> ProcessResult:
        self.specs.append(spec)
        return self.callback(spec)


def test_runtime_config_contains_provider_connection_settings() -> None:
    openai = runtime_config_from_mapping(
        {
            "provider": "openai",
            "api_key": "secret-openai",
            "model": _OPENAI_MODEL,
            "base_url": f"{_OPENAI_BASE_URL}/",
        }
    )
    anthropic = runtime_config_from_mapping(
        {
            "provider": "anthropic",
            "api_key": "secret-anthropic",
            "model": _ANTHROPIC_MODEL,
            "base_url": _ANTHROPIC_BASE_URL,
        }
    )

    assert openai.provider is AgentProvider.OPENAI
    assert anthropic.provider is AgentProvider.ANTHROPIC
    assert "secret-openai" not in repr(openai)
    assert openai.model == _OPENAI_MODEL
    assert openai.cli_model == "gpt-5.6-terra"
    assert openai.base_url == _OPENAI_BASE_URL
    assert anthropic.model == _ANTHROPIC_MODEL
    assert anthropic.cli_model == "claude-sonnet-5"
    assert anthropic.base_url == _ANTHROPIC_BASE_URL

    with pytest.raises(AgentConfigurationError, match="openai/<model-id>"):
        runtime_config_from_mapping(
            {
                "provider": "openai",
                "api_key": "secret",
                "model": "anthropic/wrong-provider",
                "base_url": _OPENAI_BASE_URL,
            }
        )
    with pytest.raises(AgentConfigurationError, match="supports only"):
        runtime_config_from_mapping(
            {
                "provider": "openai",
                "api_key": "secret",
                "model": _OPENAI_MODEL,
                "base_url": _OPENAI_BASE_URL,
                "wire_api": "chat",
            }
        )
    with pytest.raises(AgentConfigurationError, match="absolute HTTP"):
        runtime_config_from_mapping(
            {
                "provider": "anthropic",
                "api_key": "secret",
                "model": _ANTHROPIC_MODEL,
                "base_url": "api.anthropic.com",
            }
        )


def test_web_blacklist_policy_is_enabled_by_default(tmp_path: Path) -> None:
    request = _request(tmp_path)
    assert request.web_access_policy.enabled is True


def test_output_artifact_paths_are_confined_to_outputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="below outputs"):
        replace(
            _request(tmp_path),
            output_artifacts={"records": "../records.jsonl"},
        )


def test_responses_strict_schema_normalization_is_shared_and_non_mutating() -> None:
    source = {
        "type": "object",
        "properties": {
            "value": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
            "nested": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean", "default": True},
                },
            },
        },
    }

    normalized = make_responses_strict_schema(source)

    assert source["properties"]["value"]["default"] is None
    assert normalized["required"] == ["value", "nested"]
    assert normalized["additionalProperties"] is False
    assert normalized["properties"]["nested"]["required"] == ["enabled"]
    assert (
        normalized["properties"]["nested"]["additionalProperties"] is False
    )
    assert "default" not in json.dumps(normalized)


def test_run_store_persists_redacted_terminal_failure(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request = replace(request, task_name="q2protocol")
    store = JsonRunStore(
        root=tmp_path / "records",
        policy=WebAccessPolicy(blocked_identifiers=("SECRET",)),
        debug=True,
    )

    store.start(request)
    store.fail(
        request,
        status=AgentExecutionStatus.FAILED,
        error=ValueError("SECRET must not be persisted"),
    )

    record = json.loads(
        (tmp_path / "records" / f"{request.run_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert record["status"] == "failed"
    assert "SECRET" not in json.dumps(record)
    assert record["task"] == "q2protocol"


def test_run_store_digests_large_structured_task_output(tmp_path: Path) -> None:
    request = replace(
        _request(tmp_path),
        task_name="grade_summary_of_findings",
        run_record_digest_output_fields=("artifact", "checkpoint"),
    )
    store = JsonRunStore(
        root=tmp_path / "records",
        policy=WebAccessPolicy(),
    )
    result = AgentRunResult(
        provider=AgentProvider.OPENAI,
        model=_OPENAI_MODEL,
        run_id=request.run_id,
        session_id="session-1",
        output={
            "status": "completed",
            "artifact": {"evidence_profiles": [{"evidence_body_id": "body-1"}]},
            "checkpoint": None,
        },
        events=(),
        stderr="",
        duration_seconds=0.1,
        web_access_audit=WebAccessAudit(True, False, 1, ()),
        skill_snapshots=(),
    )

    store.start(request)
    store.complete(request, result)

    record = json.loads(
        (tmp_path / "records" / f"{request.run_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert record["output"]["artifact"]["redacted"] is True
    assert record["output"]["artifact"]["sha256"].startswith("sha256:")
    assert record["output"]["checkpoint"] is None
    assert "body-1" not in json.dumps(record)


def test_runtime_records_process_failure_instead_of_masking_it(
    tmp_path: Path,
) -> None:
    request = replace(_request(tmp_path), task_name="evidence_search")
    policy = WebAccessPolicy()
    store = JsonRunStore(
        root=tmp_path / "records",
        policy=policy,
    )
    runtime = CodexCliRuntime(
        _runtime_config(AgentProvider.OPENAI, "secret"),
        process_runner=FakeProcessRunner(
            lambda spec: ProcessResult(
                returncode=2,
                stdout="",
                stderr="invalid runtime option",
                duration_seconds=0.1,
            )
        ),
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
        ),
        run_store=store,
    )

    with pytest.raises(AgentProcessError, match="invalid runtime option"):
        asyncio.run(runtime.run(request))

    record = json.loads(
        (tmp_path / "records" / f"{request.run_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert record["status"] == "failed"
    assert record["error_type"] == "AgentProcessError"
    assert record["error_code"] == "process_failed"
    assert record["provider"] == "openai"
    assert record["returncode"] == 2
    assert "invalid runtime option" not in json.dumps(record)


def test_debug_bundle_retains_redacted_execution_diagnostics(
    tmp_path: Path,
) -> None:
    secret = "provider-secret"
    blocked = "https://blocked.example/private"

    def corrected(_: ProcessSpec) -> ProcessResult:
        return ProcessResult(
            returncode=0,
                stdout=(
                    '{"type":"assistant","message":{"content":['
                    '{"type":"tool_use","name":"WebFetch","input":'
                    f'{{"query":"private","token":"{secret}"}}'
                "}]}}\n"
                '{"type":"result","session_id":"session-1",'
                '"structured_output":{"answer":"done"}}\n'
            ),
            stderr=f"diagnostic {secret}",
            duration_seconds=0.1,
        )

    request = replace(
        _request(tmp_path, run_id="debug-success"),
        prompt=f"Do not use {blocked}. Return the answer.",
        web_access_policy=WebAccessPolicy(blocked_urls=(blocked,)),
    )
    debug_store = DebugBundleStore(
        root=tmp_path / "debug",
        policy=request.web_access_policy,
        secret=secret,
    )
    runtime = ClaudeCliRuntime(
        _runtime_config(AgentProvider.ANTHROPIC, secret),
        process_runner=FakeProcessRunner(corrected),
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "workspaces",
            retention=WorkspaceRetention.ALWAYS,
        ),
        debug_store=debug_store,
    )

    result = asyncio.run(runtime.run(request))
    bundle = tmp_path / "debug" / request.run_id

    assert result.output == {"answer": "done"}
    assert (bundle / "request.json").is_file()
    assert (bundle / "events.jsonl").is_file()
    assert (bundle / "stdout.jsonl").is_file()
    assert (bundle / "structured-output.json").is_file()
    serialized = "\n".join(
        path.read_text(encoding="utf-8")
        for path in bundle.rglob("*")
        if path.is_file()
    )
    assert secret not in serialized
    assert blocked not in serialized
    stdout = (bundle / "stdout.jsonl").read_text(encoding="utf-8")
    assert "sha256:" in stdout
    assert '"json_keys"' in stdout


def test_debug_bundle_retains_failure_process_and_workspace(tmp_path: Path) -> None:
    request = _request(tmp_path, run_id="debug-failure")
    debug_store = DebugBundleStore(
        root=tmp_path / "debug",
        policy=request.web_access_policy,
        secret="secret",
    )
    runtime = CodexCliRuntime(
        _runtime_config(AgentProvider.OPENAI, "secret"),
        process_runner=FakeProcessRunner(
            lambda spec: ProcessResult(
                returncode=2,
                stdout='{"type":"error","message":"failure"}\n',
                stderr="failure details",
                duration_seconds=0.1,
            )
        ),
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "workspaces",
            retention=WorkspaceRetention.ALWAYS,
        ),
        debug_store=debug_store,
    )

    with pytest.raises(AgentProcessError):
        asyncio.run(runtime.run(request))

    bundle = tmp_path / "debug" / request.run_id
    manifest = json.loads(
        (bundle / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "failed"
    assert manifest["workspace_path"]
    assert (bundle / "stderr.txt").read_text(encoding="utf-8") == (
        "failure details"
    )
    assert (bundle / "stdout.jsonl").is_file()


def test_debug_bundle_cli_lists_paths_and_cleans(tmp_path: Path, capsys) -> None:
    request = _request(tmp_path, run_id="cli-debug")
    root = tmp_path / "debug"
    DebugBundleStore(
        root=root,
        policy=request.web_access_policy,
    ).start(request)

    assert debug_main(["--root", str(root), "list"]) == 0
    assert "cli-debug" in capsys.readouterr().out
    assert debug_main(["--root", str(root), "path", "cli-debug"]) == 0
    assert str(root / "cli-debug") in capsys.readouterr().out
    assert debug_main(["--root", str(root), "clean"]) == 0
    assert not (root / "cli-debug").exists()


def test_run_store_does_not_persist_provider_event_payloads(
    tmp_path: Path,
) -> None:
    request = replace(_request(tmp_path), task_name="study_selection")
    store = JsonRunStore(
        root=tmp_path / "records",
        policy=WebAccessPolicy(),
    )
    error = AgentProcessError(
        provider=AgentProvider.OPENAI,
        returncode=1,
        stderr=(
            '{"type":"thread.started","thread_id":"private-thread"}\n'
            '{"type":"error","message":"502 Bad Gateway",'
            '"cf-ray":"private-ray"}'
        ),
    )

    store.start(request)
    store.fail(
        request,
        status=AgentExecutionStatus.FAILED,
        error=error,
    )

    serialized = (
        tmp_path / "records" / f"{request.run_id}.json"
    ).read_text(encoding="utf-8")
    record = json.loads(serialized)
    assert record["error_code"] == "upstream_http_502"
    assert record["returncode"] == 1
    assert "private-thread" not in serialized
    assert "private-ray" not in serialized
    assert "thread.started" not in serialized


def test_web_blacklist_audit_matches_urls_domains_and_identifiers() -> None:
    policy = WebAccessPolicy(
        blocked_urls=("https://example.test/withheld-review?source=test",),
        blocked_domains=("blocked.example",),
        blocked_identifiers=("CD012345",),
    )
    audit = audit_web_access(
        policy,
        events=(
            (
                "tool_use",
                {
                    "query": "evidence for CD012345",
                    "url": "https://blocked.example/article",
                },
            ),
        ),
        output={"citation": "https://example.test/withheld-review#results"},
    )

    assert audit.enabled is True
    assert audit.potential_contamination is True
    assert {item.match_type for item in audit.violations} == {
        "blocked_domain",
        "blocked_identifier",
        "blocked_url",
    }
    serialized = repr(audit)
    assert "CD012345" not in serialized
    assert "withheld-review" not in serialized


def test_disabled_web_blacklist_does_not_inspect_values() -> None:
    policy = WebAccessPolicy(
        enabled=False,
        blocked_domains=("blocked.example",),
    )
    audit = audit_web_access(
        policy,
        events=(("tool_use", {"url": "https://blocked.example/answer"}),),
        output={},
    )

    assert audit.enabled is False
    assert audit.potential_contamination is False
    assert audit.inspected_value_count == 0
    assert audit.violations == ()


def test_runtime_rejects_config_for_another_provider() -> None:
    config = _runtime_config(AgentProvider.ANTHROPIC, "secret")
    with pytest.raises(AgentProviderMismatchError):
        CodexCliRuntime(config)


def test_factory_selects_runtime_from_provider() -> None:
    assert isinstance(
        build_agent_runtime(
            _runtime_config(AgentProvider.OPENAI, "openai-secret")
        ),
        CodexCliRuntime,
    )
    assert isinstance(
        build_agent_runtime(
            _runtime_config(AgentProvider.ANTHROPIC, "anthropic-secret")
        ),
        ClaudeCliRuntime,
    )


def test_factory_debug_mode_uses_temp_bundle_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_DEBUG", "1")
    monkeypatch.setenv("AGENT_DEBUG_ROOT", str(tmp_path / "debug-root"))
    runtime = build_agent_runtime(
        _runtime_config(AgentProvider.OPENAI, "openai-secret")
    )

    assert isinstance(runtime, CodexCliRuntime)
    assert runtime._debug_store is not None
    assert runtime._debug_store.root == tmp_path / "debug-root"
    assert runtime._workspace_manager.retention is WorkspaceRetention.ALWAYS
    assert runtime._workspace_manager.base_directory == (
        tmp_path / "debug-root" / "workspaces"
    )


def test_skill_contract_and_provider_specific_staging(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    package = load_skill(skill)
    request = AgentRunRequest(
        run_id="stage-test",
        prompt="Test staging.",
        input_data={},
        output_schema=OUTPUT_SCHEMA,
        skill_paths=(skill,),
    )

    assert package.name == "test-skill"
    assert len(package.sha256) == 64

    codex_manager = WorkspaceManager(
        base_directory=tmp_path / "codex-runs",
        retention=WorkspaceRetention.ALWAYS,
    )
    codex_workspace = codex_manager.prepare(
        request,
        provider=AgentProvider.OPENAI,
    )
    assert (codex_workspace.root / ".agents/skills/test-skill/SKILL.md").is_file()
    assert json.loads(
        (codex_workspace.root / "contracts/output-artifacts.json").read_text(
            encoding="utf-8"
        )
    ) == {}

    claude_manager = WorkspaceManager(
        base_directory=tmp_path / "claude-runs",
        retention=WorkspaceRetention.ALWAYS,
    )
    claude_workspace = claude_manager.prepare(
        request,
        provider=AgentProvider.ANTHROPIC,
    )
    plugin = claude_workspace.staged_skills.claude_plugin_path
    assert plugin is not None
    assert (plugin / "skills/test-skill/SKILL.md").is_file()
    assert (plugin / ".claude-plugin/plugin.json").is_file()


def test_skill_rejects_frontmatter_name_mismatch(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    (skill / "SKILL.md").write_text(
        "---\n" "name: another-name\n" "description: Invalid mismatch.\n" "---\n",
        encoding="utf-8",
    )
    with pytest.raises(AgentSkillError, match="must match"):
        load_skill(skill)


def test_codex_runtime_invokes_real_cli_contract_without_leaking_key(
    tmp_path: Path,
) -> None:
    credential = "codex-secret"

    def complete(spec: ProcessSpec) -> ProcessResult:
        output_index = spec.argv.index("--output-last-message") + 1
        output_path = Path(spec.argv[output_index])
        assert (spec.cwd / ".agents/skills/test-skill/SKILL.md").is_file()
        output_path.write_text('{"answer":"codex-ok"}\n', encoding="utf-8")
        return ProcessResult(
            returncode=0,
            stdout=(
                '{"type":"thread.started","thread_id":"thread-1"}\n'
                '{"type":"item.completed","item":'
                '{"type":"agent_message","text":"{\\"answer\\":\\"fallback\\"}"}}\n'
            ),
            stderr=f"diagnostic without exposing {credential}",
            duration_seconds=1.25,
        )

    runner = FakeProcessRunner(complete)
    runtime = CodexCliRuntime(
        _runtime_config(AgentProvider.OPENAI, credential),
        process_runner=runner,
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
        ),
    )
    result = asyncio.run(runtime.run(_request(tmp_path)))
    spec = runner.specs[0]

    assert result.output == {"answer": "codex-ok"}
    assert result.session_id == "thread-1"
    assert result.model == "openai/gpt-5.6-terra"
    assert result.skill_snapshots[0].name == "test-skill"
    assert len(result.skill_snapshots[0].sha256) == 64
    assert spec.argv[0:2] == ("codex", "exec")
    assert spec.argv[spec.argv.index("--model") + 1] == "gpt-5.6-terra"
    assert spec.argv[spec.argv.index("--sandbox") + 1] == "workspace-write"
    assert spec.argv[spec.argv.index("--output-schema") + 1].endswith(
        "contracts/output.schema.json"
    )
    assert "--ask-for-approval" not in spec.argv
    config_values = tuple(
        spec.argv[index + 1]
        for index, value in enumerate(spec.argv)
        if value == "-c"
    )
    assert 'model_provider="ebm_openai"' in config_values
    assert "allow_login_shell=false" in config_values
    assert (
        'model_providers.ebm_openai.base_url="https://rehdasu.cn/v1"'
        in config_values
    )
    assert (
        'model_providers.ebm_openai.env_key="CODEX_API_KEY"'
        in config_values
    )
    assert spec.environment_overrides == {
        "CODEX_API_KEY": credential,
        "PATH": (
            f"{Path(sys.executable).parent}{os.pathsep}"
            f"{os.environ.get('PATH', '')}"
        ),
    }
    assert credential not in " ".join(spec.argv)
    assert credential not in spec.stdin
    assert credential not in result.stderr
    assert "***" in result.stderr
    assert not spec.cwd.exists()


def test_codex_runtime_uses_valid_final_output_when_jsonl_is_degraded(
    tmp_path: Path,
) -> None:
    def complete(spec: ProcessSpec) -> ProcessResult:
        output_index = spec.argv.index("--output-last-message") + 1
        Path(spec.argv[output_index]).write_text(
            '{"answer":"recovered"}\n',
            encoding="utf-8",
        )
        return ProcessResult(
            returncode=0,
            stdout=(
                '{"type":"thread.started","thread_id":"thread-1"}\n'
                '{"type":"item.completed","item":{"type":"tool_call"}}\n'
                "raw tool output that is not JSONL\n"
                '{"type":"turn.completed","usage":{"input_tokens":1}}\n'
            ),
            stderr="",
            duration_seconds=0.2,
        )

    runtime = CodexCliRuntime(
        _runtime_config(AgentProvider.OPENAI, "secret"),
        process_runner=FakeProcessRunner(complete),
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
        ),
    )

    result = asyncio.run(runtime.run(_request(tmp_path)))

    assert result.output == {"answer": "recovered"}
    assert result.session_id == "thread-1"
    assert [event.event_type for event in result.events] == [
        "thread.started",
        "item.completed",
        "runtime.stdout.non_json",
        "turn.completed",
    ]
    degraded = result.events[2].payload
    assert degraded["sequence"] == 2
    assert degraded["size_bytes"] == len(
        "raw tool output that is not JSONL".encode("utf-8")
    )
    assert str(degraded["sha256"]).startswith("sha256:")
    assert degraded["audit_coverage"] == "degraded"


def test_codex_runtime_still_rejects_missing_final_output_with_bad_jsonl(
    tmp_path: Path,
) -> None:
    runtime = CodexCliRuntime(
        _runtime_config(AgentProvider.OPENAI, "secret"),
        process_runner=FakeProcessRunner(
            lambda spec: ProcessResult(
                returncode=0,
                stdout="raw tool output that is not JSONL\n",
                stderr="",
                duration_seconds=0.1,
            )
        ),
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
        ),
    )

    with pytest.raises(AgentOutputError, match="no final structured output"):
        asyncio.run(runtime.run(_request(tmp_path)))


def test_runtime_collects_declared_output_before_workspace_cleanup(
    tmp_path: Path,
) -> None:
    def complete(spec: ProcessSpec) -> ProcessResult:
        assert json.loads(
            (spec.cwd / "contracts/output-artifacts.json").read_text(
                encoding="utf-8"
            )
        ) == {"records": "outputs/search/records.jsonl"}
        assert "Read contracts/output-artifacts.json" in spec.stdin
        output_index = spec.argv.index("--output-last-message") + 1
        Path(spec.argv[output_index]).write_text(
            '{"answer":"done"}\n',
            encoding="utf-8",
        )
        artifact = spec.cwd / "outputs/search/records.jsonl"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text('{"record_id":"one"}\n', encoding="utf-8")
        return ProcessResult(
            returncode=0,
            stdout='{"type":"thread.started","thread_id":"thread-1"}\n',
            stderr="",
            duration_seconds=0.1,
        )

    request = replace(
        _request(tmp_path),
        output_artifacts={
            "records": "outputs/search/records.jsonl",
        },
        enable_workspace_network=True,
    )
    runner = FakeProcessRunner(complete)
    runtime = CodexCliRuntime(
        _runtime_config(AgentProvider.OPENAI, "secret"),
        process_runner=runner,
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
        ),
    )

    result = asyncio.run(runtime.run(request))

    assert result.output_artifacts["records"].content == (
        b'{"record_id":"one"}\n'
    )
    assert result.output_artifacts["records"].sha256.startswith("sha256:")
    assert "sandbox_workspace_write.network_access=true" in runner.specs[
        0
    ].argv
    assert not runner.specs[0].cwd.exists()


def test_runtime_web_audit_inspects_declared_output_artifacts(
    tmp_path: Path,
) -> None:
    def complete(spec: ProcessSpec) -> ProcessResult:
        output_index = spec.argv.index("--output-last-message") + 1
        Path(spec.argv[output_index]).write_text(
            '{"answer":"done"}\n',
            encoding="utf-8",
        )
        artifact = spec.cwd / "outputs/search/records.jsonl"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            '{"source_record_id":"BLOCKED-ID"}\n',
            encoding="utf-8",
        )
        return ProcessResult(
            returncode=0,
            stdout='{"type":"thread.started","thread_id":"thread-1"}\n',
            stderr="",
            duration_seconds=0.1,
        )

    request = replace(
        _request(tmp_path),
        output_artifacts={
            "records": "outputs/search/records.jsonl",
        },
        web_access_policy=WebAccessPolicy(
            blocked_identifiers=("BLOCKED-ID",),
        ),
    )
    runtime = CodexCliRuntime(
        _runtime_config(AgentProvider.OPENAI, "secret"),
        process_runner=FakeProcessRunner(complete),
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
            retention=WorkspaceRetention.ON_FAILURE,
        ),
    )

    result = asyncio.run(runtime.run(request))

    assert result.web_access_audit.potential_contamination is True
    assert result.retained_workspace is None


def test_skill_digest_changes_with_skill_content(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    first = load_skill(skill)
    (skill / "references").mkdir()
    (skill / "references" / "contract.md").write_text(
        "First contract.\n",
        encoding="utf-8",
    )
    second = load_skill(skill)

    assert first.sha256 != second.sha256


def test_generated_python_caches_do_not_change_or_stage_skill(
    tmp_path: Path,
) -> None:
    skill = _make_skill(tmp_path)
    scripts = skill / "scripts"
    scripts.mkdir()
    (scripts / "tool.py").write_text("print('ok')\n", encoding="utf-8")
    first = load_skill(skill)

    cache = scripts / "__pycache__"
    cache.mkdir()
    (cache / "tool.cpython-311.pyc").write_bytes(b"generated cache")
    (scripts / "orphan.pyc").write_bytes(b"generated cache")
    second = load_skill(skill)

    assert second.sha256 == first.sha256

    request = AgentRunRequest(
        run_id="cache-stage-test",
        prompt="Test staging.",
        input_data={},
        output_schema=OUTPUT_SCHEMA,
        skill_paths=(skill,),
    )
    workspace = WorkspaceManager(
        base_directory=tmp_path / "runs",
        retention=WorkspaceRetention.ALWAYS,
    ).prepare(request, provider=AgentProvider.OPENAI)
    staged_scripts = (
        workspace.root / ".agents/skills/test-skill/scripts"
    )

    assert (staged_scripts / "tool.py").is_file()
    assert not (staged_scripts / "__pycache__").exists()
    assert not (staged_scripts / "orphan.pyc").exists()


def test_claude_runtime_invokes_real_cli_contract_without_leaking_key(
    tmp_path: Path,
) -> None:
    credential = "claude-secret"

    def complete(spec: ProcessSpec) -> ProcessResult:
        plugin = Path(spec.argv[spec.argv.index("--plugin-dir") + 1])
        assert (plugin / "skills/test-skill/SKILL.md").is_file()
        return ProcessResult(
            returncode=0,
            stdout=(
                '{"type":"system","session_id":"session-1"}\n'
                '{"type":"result","session_id":"session-1",'
                '"structured_output":{"answer":"claude-ok"}}\n'
            ),
            stderr="",
            duration_seconds=2.0,
        )

    runner = FakeProcessRunner(complete)
    runtime = ClaudeCliRuntime(
        _runtime_config(AgentProvider.ANTHROPIC, credential),
        process_runner=runner,
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
        ),
    )
    result = asyncio.run(runtime.run(_request(tmp_path)))
    spec = runner.specs[0]

    assert result.output == {"answer": "claude-ok"}
    assert result.session_id == "session-1"
    assert result.model == "anthropic/claude-sonnet-5"
    assert spec.argv[0:2] == ("claude", "--print")
    assert spec.argv[spec.argv.index("--model") + 1] == "claude-sonnet-5"
    assert spec.environment_overrides == {
        "ANTHROPIC_API_KEY": credential,
        "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
        "PATH": (
            f"{Path(sys.executable).parent}{os.pathsep}"
            f"{os.environ.get('PATH', '')}"
        ),
    }
    assert credential not in " ".join(spec.argv)
    assert credential not in spec.stdin
    assert not spec.cwd.exists()


def test_claude_networked_skill_tools_are_scoped_to_staged_scripts(
    tmp_path: Path,
) -> None:
    request = replace(
        _request(tmp_path),
        enable_workspace_network=True,
        enable_web_search=True,
    )

    def complete(spec: ProcessSpec) -> ProcessResult:
        return ProcessResult(
            returncode=0,
            stdout=(
                '{"type":"result","session_id":"session-1",'
                '"structured_output":{"answer":"done"}}\n'
            ),
            stderr="",
            duration_seconds=0.1,
        )

    runner = FakeProcessRunner(complete)
    runtime = ClaudeCliRuntime(
        _runtime_config(AgentProvider.ANTHROPIC, "secret"),
        process_runner=runner,
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
        ),
    )

    asyncio.run(runtime.run(request))
    argv = runner.specs[0].argv
    allowed = argv[argv.index("--allowedTools") + 1]

    assert "Bash(python3 .runtime/claude-skills/skills/test-skill/scripts/*)" in (
        allowed
    )
    assert "WebSearch" in allowed
    assert "WebFetch" in allowed
    assert "Bash(*)" not in allowed


def test_invalid_agent_result_is_rejected_and_workspace_can_be_retained(
    tmp_path: Path,
) -> None:
    def complete(spec: ProcessSpec) -> ProcessResult:
        return ProcessResult(
            returncode=0,
            stdout=('{"type":"result","structured_output":{"answer":42}}\n'),
            stderr="",
            duration_seconds=0.1,
        )

    runtime = ClaudeCliRuntime(
        _runtime_config(AgentProvider.ANTHROPIC, "secret"),
        process_runner=FakeProcessRunner(complete),
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
            retention=WorkspaceRetention.ON_FAILURE,
        ),
    )

    with pytest.raises(AgentOutputSchemaError) as caught:
        asyncio.run(runtime.run(_request(tmp_path)))
    assert caught.value.retained_workspace is not None
    assert caught.value.retained_workspace.is_dir()


def test_runtime_flags_blacklisted_web_access_without_prompt_leakage(
    tmp_path: Path,
) -> None:
    blocked_url = "https://blocked.example/withheld-answer"

    def complete(spec: ProcessSpec) -> ProcessResult:
        assert blocked_url not in spec.stdin
        assert "prohibited answer sources" in spec.stdin
        return ProcessResult(
            returncode=0,
            stdout=(
                '{"type":"assistant","message":{"content":['
                '{"type":"tool_use","name":"WebFetch","input":'
                f'{{"url":"{blocked_url}"}}'
                "}]}}\n"
                '{"type":"result","structured_output":{"answer":"done"}}\n'
            ),
            stderr="",
            duration_seconds=0.1,
        )

    request = AgentRunRequest(
        run_id="blacklist-test",
        prompt="Return the answer.",
        input_data={},
        output_schema=OUTPUT_SCHEMA,
        skill_paths=(_make_skill(tmp_path),),
        web_access_policy=WebAccessPolicy(
            blocked_urls=(blocked_url,),
        ),
    )
    runtime = ClaudeCliRuntime(
        _runtime_config(AgentProvider.ANTHROPIC, "secret"),
        process_runner=FakeProcessRunner(complete),
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
            retention=WorkspaceRetention.ON_FAILURE,
        ),
    )

    result = asyncio.run(runtime.run(request))
    assert result.web_access_audit.potential_contamination is True
    assert result.retained_workspace is None


def test_runtime_can_explicitly_disable_web_blacklist(tmp_path: Path) -> None:
    blocked_url = "https://blocked.example/withheld-answer"

    def complete(spec: ProcessSpec) -> ProcessResult:
        assert "withheld benchmark answer sources" not in spec.stdin
        return ProcessResult(
            returncode=0,
            stdout=(
                '{"type":"assistant","message":{"content":['
                '{"type":"tool_use","name":"WebFetch","input":'
                f'{{"url":"{blocked_url}"}}'
                "}]}}\n"
                '{"type":"result","structured_output":{"answer":"done"}}\n'
            ),
            stderr="",
            duration_seconds=0.1,
        )

    request = AgentRunRequest(
        run_id="blacklist-disabled-test",
        prompt="Return the answer.",
        input_data={},
        output_schema=OUTPUT_SCHEMA,
        skill_paths=(_make_skill(tmp_path),),
        web_access_policy=WebAccessPolicy(
            enabled=False,
            blocked_urls=(blocked_url,),
        ),
    )
    runtime = ClaudeCliRuntime(
        _runtime_config(AgentProvider.ANTHROPIC, "secret"),
        process_runner=FakeProcessRunner(complete),
        workspace_manager=WorkspaceManager(
            base_directory=tmp_path / "runs",
        ),
    )

    result = asyncio.run(runtime.run(request))
    assert result.output == {"answer": "done"}
    assert result.web_access_audit.enabled is False
    assert result.web_access_audit.potential_contamination is False


def test_subprocess_runner_executes_without_shell() -> None:
    result = asyncio.run(
        SubprocessRunner().run(
            ProcessSpec(
                argv=(
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        "value=sys.stdin.read(); "
                        "sys.stdout.write(value.upper())"
                    ),
                ),
                cwd=Path.cwd(),
                stdin="agent runtime",
                timeout_seconds=5,
            )
        )
    )
    assert result.returncode == 0
    assert result.stdout == "AGENT RUNTIME"


def test_subprocess_runner_enforces_timeout() -> None:
    with pytest.raises(AgentProcessTimeoutError):
        asyncio.run(
            SubprocessRunner().run(
                ProcessSpec(
                    argv=(
                        sys.executable,
                        "-c",
                        "import time; time.sleep(5)",
                    ),
                    cwd=Path.cwd(),
                    stdin="",
                    timeout_seconds=0.05,
                )
            )
        )
