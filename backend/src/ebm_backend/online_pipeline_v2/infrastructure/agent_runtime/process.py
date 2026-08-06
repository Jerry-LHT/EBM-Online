"""Async subprocess boundary used by real CLI runtimes."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
import time

from .contracts import ProcessResult, ProcessSpec
from .errors import (
    AgentCliNotFoundError,
    AgentOutputTooLargeError,
    AgentProcessCancelledError,
    AgentProcessTimeoutError,
)


class SubprocessRunner:
    """Launch a real executable without a shell and capture bounded output."""

    async def run(self, spec: ProcessSpec) -> ProcessResult:
        if not spec.argv:
            raise ValueError("process argv must not be empty")
        if spec.timeout_seconds <= 0:
            raise ValueError("process timeout_seconds must be positive")
        environment = os.environ.copy()
        environment.update(spec.environment_overrides)
        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *spec.argv,
                cwd=Path(spec.cwd),
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(os.name == "posix"),
            )
        except FileNotFoundError as exc:
            raise AgentCliNotFoundError(spec.argv[0]) from exc

        communicate = process.communicate(spec.stdin.encode("utf-8"))
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                communicate,
                timeout=spec.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            await _terminate(process)
            raise AgentProcessTimeoutError(spec.timeout_seconds) from exc
        except asyncio.CancelledError as exc:
            await _terminate(process)
            raise AgentProcessCancelledError(
                "Agent CLI process was cancelled"
            ) from exc

        if len(stdout_bytes) + len(stderr_bytes) > spec.max_output_bytes:
            raise AgentOutputTooLargeError(spec.max_output_bytes)
        return ProcessResult(
            returncode=process.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_seconds=time.monotonic() - started,
        )


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
        return
    except asyncio.TimeoutError:
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return
    await process.wait()

