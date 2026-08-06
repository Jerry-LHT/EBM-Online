"""Backend-owned, redacted persistence for Agent execution records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .contracts import (
    AgentExecutionStatus,
    AgentRunRequest,
    AgentRunResult,
)
from .errors import (
    AgentAuthenticationError,
    AgentCliCapabilityError,
    AgentCliNotFoundError,
    AgentConfigurationError,
    AgentOutputError,
    AgentProcessCancelledError,
    AgentProcessError,
    AgentProcessTimeoutError,
)
from .web_access_policy import WebAccessPolicy


@dataclass(slots=True)
class JsonRunStore:
    """Persist one JSON record per execution without raw policy or tool data."""

    root: Path
    policy: WebAccessPolicy
    debug: bool = False
    _started_at: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self._started_at is None:
            self._started_at = {}

    def start(self, request: AgentRunRequest) -> None:
        assert self._started_at is not None
        started_at = _now()
        self._started_at[request.run_id] = started_at
        self._write(
            request.run_id,
            {
                "schema_version": "agent-run.v1",
                "run_id": request.run_id,
                "task": request.task_name,
                "status": AgentExecutionStatus.RUNNING.value,
                "started_at": started_at,
                "debug": self.debug,
                "input": {
                    "keys": sorted(str(key) for key in request.input_data),
                    "sha256": _digest_json(request.input_data),
                },
            },
        )

    def complete(
        self,
        request: AgentRunRequest,
        result: AgentRunResult,
        *,
        debug_bundle_path: Path | None = None,
    ) -> None:
        assert self._started_at is not None
        self._write(
            request.run_id,
            {
                "schema_version": "agent-run.v1",
                "run_id": request.run_id,
                "task": request.task_name,
                "status": AgentExecutionStatus.COMPLETED.value,
                "started_at": self._started_at.pop(request.run_id, None),
                "finished_at": _now(),
                "provider": result.provider.value,
                "model": result.model,
                "session_id": result.session_id,
                "duration_seconds": result.duration_seconds,
                "output": _record_output(result.output, request, self.policy),
                "event_types": [event.event_type for event in result.events],
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
                "retained_workspace": (
                    str(result.retained_workspace)
                    if self.debug and result.retained_workspace is not None
                    else None
                ),
                "debug_bundle_path": (
                    str(debug_bundle_path) if self.debug and debug_bundle_path else None
                ),
            },
        )

    def fail(
        self,
        request: AgentRunRequest,
        *,
        status: AgentExecutionStatus,
        error: BaseException,
        retained_workspace: Path | None = None,
        debug_bundle_path: Path | None = None,
    ) -> None:
        assert self._started_at is not None
        failure = _failure_metadata(error)
        self._write(
            request.run_id,
            {
                "schema_version": "agent-run.v1",
                "run_id": request.run_id,
                "task": request.task_name,
                "status": status.value,
                "started_at": self._started_at.pop(request.run_id, None),
                "finished_at": _now(),
                "error_type": type(error).__name__,
                **failure,
                "retained_workspace": (
                    str(retained_workspace)
                    if self.debug and retained_workspace
                    else None
                ),
                "debug_bundle_path": (
                    str(debug_bundle_path) if self.debug and debug_bundle_path else None
                ),
            },
        )

    def _write(self, run_id: str, payload: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{run_id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _record_output(
    output: Mapping[str, Any],
    request: AgentRunRequest,
    policy: WebAccessPolicy,
) -> Any:
    redacted = _redact(output, policy)
    if not isinstance(redacted, Mapping):
        return redacted
    recorded = dict(redacted)
    for field_name in request.run_record_digest_output_fields:
        if field_name not in output:
            continue
        value = output[field_name]
        if value is None:
            recorded[field_name] = None
            continue
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        recorded[field_name] = {
            "redacted": True,
            "sha256": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
            "size_bytes": len(encoded),
        }
    return recorded


def _redact(value: Any, policy: WebAccessPolicy) -> Any:
    if isinstance(value, str):
        return _redact_text(value, policy)
    if isinstance(value, Mapping):
        return {str(key): _redact(item, policy) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, policy) for item in value]
    return value


def _redact_text(value: str, policy: WebAccessPolicy) -> str:
    redacted = value
    for blocked_url in policy.blocked_urls:
        redacted = redacted.replace(blocked_url, "<redacted-url>")
    for blocked_domain in policy.blocked_domains:
        redacted = re.sub(
            re.escape(blocked_domain),
            "<redacted-domain>",
            redacted,
            flags=re.IGNORECASE,
        )
    for identifier in policy.blocked_identifiers:
        redacted = re.sub(
            re.escape(identifier),
            "<redacted-identifier>",
            redacted,
            flags=re.IGNORECASE,
        )
    return redacted


def _failure_metadata(error: BaseException) -> dict[str, object]:
    """Return stable diagnostics without persisting provider event payloads."""
    if isinstance(error, AgentProcessError):
        return {
            "error_code": _process_error_code(error.stderr),
            "provider": error.provider.value,
            "returncode": error.returncode,
        }
    if isinstance(error, AgentProcessTimeoutError):
        return {
            "error_code": "process_timeout",
            "timeout_seconds": error.timeout_seconds,
        }
    if isinstance(error, AgentProcessCancelledError):
        return {"error_code": "process_cancelled"}
    if isinstance(error, AgentAuthenticationError):
        return {"error_code": "authentication_failed"}
    if isinstance(error, AgentCliNotFoundError):
        return {
            "error_code": "cli_not_found",
            "binary": error.binary,
        }
    if isinstance(error, AgentCliCapabilityError):
        return {
            "error_code": "cli_capability_missing",
            "provider": error.provider.value,
            "missing_flags": list(error.missing_flags),
        }
    if isinstance(error, AgentConfigurationError):
        return {"error_code": "configuration_error"}
    if isinstance(error, AgentOutputError):
        return {"error_code": "invalid_agent_output"}
    return {"error_code": "unexpected_error"}


def _process_error_code(stderr: str) -> str:
    normalized = stderr.casefold()
    if "502 bad gateway" in normalized:
        return "upstream_http_502"
    if "operation not permitted" in normalized or "permission denied" in normalized:
        return "permission_denied"
    if "429" in normalized or "rate limit" in normalized:
        return "rate_limited"
    if "timed out" in normalized or "timeout" in normalized:
        return "upstream_timeout"
    return "process_failed"
