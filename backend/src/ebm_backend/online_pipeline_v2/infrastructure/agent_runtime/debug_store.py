"""Local, opt-in diagnostics for Agent Runtime executions.

Debug bundles are deliberately separate from product artifacts and the normal
redacted RunRecord.  They live below a caller-selected temporary directory by
default and contain bounded, policy-redacted projections rather than raw
provider tool payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping

from .contracts import (
    AgentEvent,
    AgentExecutionStatus,
    AgentOutputArtifact,
    AgentRunRequest,
    AgentRunResult,
    ProcessResult,
)
from .web_access_policy import WebAccessPolicy


_TEXT_LIMIT = 64 * 1024
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|token)",
    re.IGNORECASE,
)
_DROP_KEYS = {
    "blocked_urls",
    "blocked_domains",
    "blocked_identifiers",
    "environment",
    "environment_overrides",
}
_SAFE_EVENT_FIELDS = {
    "code",
    "error_type",
    "item_id",
    "model",
    "name",
    "role",
    "session_id",
    "status",
    "stop_reason",
    "subtype",
    "thread_id",
    "tool_name",
    "type",
}
_PAYLOAD_VALUE_KEYS = {
    "arguments",
    "content",
    "data",
    "input",
    "message",
    "output",
    "result",
    "text",
}


def default_debug_root() -> Path:
    return Path(tempfile.gettempdir()) / "ebm-agent-debug"


@dataclass(slots=True)
class DebugBundleStore:
    """Write one inspectable bundle per opt-in Agent run."""

    root: Path
    policy: WebAccessPolicy
    secret: str = ""

    def start(self, request: AgentRunRequest) -> Path:
        policy = request.web_access_policy
        bundle = self._bundle_path(request.run_id)
        bundle.mkdir(parents=True, exist_ok=True)
        self._write_json(
            bundle / "manifest.json",
            {
                "schema_version": "agent-debug-bundle.v1",
                "run_id": request.run_id,
                "task": request.task_name,
                "status": "running",
                "started_at": _now(),
            },
        )
        self._write_json(
            bundle / "request.json",
            _safe_request(request, policy, self.secret),
        )
        return bundle

    def complete(
        self,
        request: AgentRunRequest,
        result: AgentRunResult,
        *,
        bundle: Path,
        process: ProcessResult,
    ) -> Path:
        policy = request.web_access_policy
        self._write_process(bundle, process, result.events, policy)
        self._write_output(bundle, result.output, result.output_artifacts, policy)
        self._write_json(
            bundle / "manifest.json",
            {
                "schema_version": "agent-debug-bundle.v1",
                "run_id": request.run_id,
                "task": request.task_name,
                "status": "completed",
                "provider": result.provider.value,
                "model": result.model,
                "session_id": result.session_id,
                "duration_seconds": result.duration_seconds,
                "process": _process_metadata(process),
                "finished_at": _now(),
                "workspace_path": str(result.retained_workspace)
                if result.retained_workspace is not None
                else None,
                "skill_snapshots": [
                    {"name": item.name, "sha256": item.sha256}
                    for item in result.skill_snapshots
                ],
                "web_access": {
                    "enabled": result.web_access_audit.enabled,
                    "potential_contamination": (
                        result.web_access_audit.potential_contamination
                    ),
                    "inspected_value_count": (
                        result.web_access_audit.inspected_value_count
                    ),
                    "violation_count": len(result.web_access_audit.violations),
                },
            },
        )
        return bundle

    def fail(
        self,
        request: AgentRunRequest,
        *,
        bundle: Path,
        error: BaseException,
        status: AgentExecutionStatus = AgentExecutionStatus.FAILED,
        process: ProcessResult | None = None,
        events: Iterable[AgentEvent] = (),
        output: Mapping[str, Any] | None = None,
        output_artifacts: Mapping[str, AgentOutputArtifact] | None = None,
        retained_workspace: Path | None = None,
    ) -> Path:
        policy = request.web_access_policy
        if process is not None:
            self._write_process(bundle, process, events, policy)
        if output is not None or output_artifacts:
            self._write_output(
                bundle,
                output or {},
                output_artifacts or {},
                policy,
            )
        self._write_json(
            bundle / "failure.json",
            {
                "error_type": type(error).__name__,
                "message": _safe_text(str(error), policy, self.secret),
                "retained_workspace": (
                    str(retained_workspace) if retained_workspace else None
                ),
            },
        )
        self._write_json(
            bundle / "manifest.json",
            {
                "schema_version": "agent-debug-bundle.v1",
                "run_id": request.run_id,
                "task": request.task_name,
                "status": status.value,
                "finished_at": _now(),
                "process": _process_metadata(process),
                "workspace_path": (
                    str(retained_workspace) if retained_workspace else None
                ),
            },
        )
        return bundle

    def list(self) -> tuple[dict[str, Any], ...]:
        if not self.root.is_dir():
            return ()
        records: list[dict[str, Any]] = []
        for manifest in sorted(self.root.glob("*/manifest.json")):
            try:
                value = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                value["bundle_path"] = str(manifest.parent)
                records.append(value)
        return tuple(records)

    def path(self, run_id: str) -> Path:
        bundle = self._bundle_path(run_id)
        if not bundle.is_dir():
            raise FileNotFoundError(f"debug bundle does not exist: {run_id}")
        return bundle

    def clean(self) -> int:
        if not self.root.is_dir():
            return 0
        removed = 0
        for child in self.root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
                removed += 1
        return removed

    def _bundle_path(self, run_id: str) -> Path:
        if not run_id or "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
            raise ValueError("debug run_id is not a safe path component")
        bundle = self.root.expanduser().resolve() / run_id
        if not bundle.is_relative_to(self.root.expanduser().resolve()):
            raise ValueError("debug bundle path escapes root")
        return bundle

    def _write_process(
        self,
        bundle: Path,
        process: ProcessResult,
        events: Iterable[AgentEvent],
        policy: WebAccessPolicy,
    ) -> None:
        _write_text(
            bundle / "stderr.txt",
            _safe_text(process.stderr, policy, self.secret),
        )
        lines: list[str] = []
        for index, event in enumerate(events):
            payload = _event_projection(event.payload)
            lines.append(
                json.dumps(
                    {
                        "sequence": index,
                        "event_type": event.event_type,
                        "payload_sha256": _digest(event.payload),
                        "payload_keys": sorted(
                            str(key) for key in event.payload
                        ),
                        "safe_payload": payload,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        _write_text(bundle / "events.jsonl", "\n".join(lines) + ("\n" if lines else ""))
        stdout_lines = []
        for index, line in enumerate(process.stdout.splitlines()):
            stdout_lines.append(
                json.dumps(
                    _stdout_projection(index, line),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        _write_text(
            bundle / "stdout.jsonl",
            "\n".join(stdout_lines) + ("\n" if stdout_lines else ""),
        )

    def _write_output(
        self,
        bundle: Path,
        output: Mapping[str, Any],
        artifacts: Mapping[str, AgentOutputArtifact],
        policy: WebAccessPolicy,
    ) -> None:
        self._write_json(
            bundle / "structured-output.json",
            _safe_value(output, policy, self.secret),
        )
        artifact_root = bundle / "artifacts"
        for name, artifact in artifacts.items():
            relative = Path(artifact.relative_path)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.parts
            ):
                continue
            target = artifact_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(artifact.content)
            self._write_json(
                artifact_root / f"{name}.manifest.json",
                {
                    "name": name,
                    "relative_path": artifact.relative_path,
                    "sha256": artifact.sha256,
                    "size_bytes": len(artifact.content),
                },
            )

    def _write_json(self, path: Path, value: object) -> None:
        _write_text(
            path,
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
        )


def _safe_request(
    request: AgentRunRequest,
    policy: WebAccessPolicy,
    secret: str,
) -> dict[str, Any]:
    return {
        "run_id": request.run_id,
        "task": request.task_name,
        "prompt": _safe_text(request.prompt, policy, secret),
        "input_data": _safe_value(request.input_data, policy, secret),
        "output_schema": _safe_value(request.output_schema, policy, secret),
        "input_artifacts": sorted(request.input_artifacts),
        "output_artifacts": dict(request.output_artifacts),
        "timeout_seconds": request.timeout_seconds,
        "access_mode": request.access_mode.value,
        "enable_workspace_network": request.enable_workspace_network,
        "enable_web_search": request.enable_web_search,
    }


def _safe_value(value: object, policy: WebAccessPolicy, secret: str) -> object:
    if isinstance(value, str):
        return _safe_text(value, policy, secret)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            if name.casefold() in _DROP_KEYS or _SENSITIVE_KEY.search(name):
                result[name] = "<redacted>"
            else:
                result[name] = _safe_value(item, policy, secret)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, policy, secret) for item in value]
    if isinstance(value, bytes):
        return {"redacted": True, "sha256": _digest(value), "size_bytes": len(value)}
    return value


def _event_projection(value: object) -> object:
    """Describe event shape without retaining provider content fields."""
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            normalized = name.casefold()
            if normalized in _PAYLOAD_VALUE_KEYS or _SENSITIVE_KEY.search(name):
                result[name] = {
                    "redacted": True,
                    "sha256": _digest(item),
                    "type": _value_type(item),
                }
            elif normalized in _SAFE_EVENT_FIELDS:
                result[name] = _event_scalar(item)
            elif isinstance(item, Mapping):
                result[name] = {
                    "type": "object",
                    "keys": sorted(str(child) for child in item),
                }
            elif isinstance(item, (list, tuple)):
                result[name] = {
                    "type": "array",
                    "count": len(item),
                }
            else:
                result[name] = {
                    "type": _value_type(item),
                    "sha256": _digest(item),
                }
        return result
    return {"type": _value_type(value), "sha256": _digest(value)}


def _event_scalar(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {
        "type": _value_type(value),
        "sha256": _digest(value),
    }


def _value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _safe_text(value: str, policy: WebAccessPolicy, secret: str) -> str:
    redacted = value.replace(secret, "<redacted-secret>") if secret else value
    for blocked_url in policy.blocked_urls:
        redacted = redacted.replace(blocked_url, "<redacted-url>")
    for domain in policy.blocked_domains:
        redacted = re.sub(re.escape(domain), "<redacted-domain>", redacted, flags=re.I)
    for identifier in policy.blocked_identifiers:
        redacted = re.sub(
            re.escape(identifier),
            "<redacted-identifier>",
            redacted,
            flags=re.I,
        )
    if len(redacted) > _TEXT_LIMIT:
        return redacted[:_TEXT_LIMIT] + "…"
    return redacted


def _stdout_projection(index: int, line: str) -> dict[str, object]:
    """Keep stdout inspectable without persisting raw provider payloads."""
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        parsed = None
    projection: dict[str, object] = {
        "sequence": index,
        "sha256": _digest(line),
        "size_bytes": len(line.encode("utf-8")),
    }
    if isinstance(parsed, Mapping):
        projection["json_keys"] = sorted(str(key) for key in parsed)
        projection["json_type"] = "object"
    elif parsed is not None:
        projection["json_type"] = type(parsed).__name__
    else:
        projection["json_type"] = "text"
    return projection


def _process_metadata(process: ProcessResult | None) -> dict[str, object] | None:
    if process is None:
        return None
    return {
        "returncode": process.returncode,
        "duration_seconds": process.duration_seconds,
        "stdout_bytes": len(process.stdout.encode("utf-8")),
        "stderr_bytes": len(process.stderr.encode("utf-8")),
    }


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
