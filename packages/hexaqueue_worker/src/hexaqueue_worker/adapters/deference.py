"""Native Deference execution runtime adapter for cloud-managed environments.

Notes/Architectural Intent:
    Used when worker processes execute inside cloud container orchestrators (such as
    AWS Batch ECS tasks, GCP Batch VM instances, or Kubernetes pods). Under this model,
    cgroups and container boundaries are enforced by the underlying Cloud Service Provider,
    allowing Hexaqueue to execute commands directly without redundant containerization.
"""

import asyncio
import contextlib
import os
from datetime import UTC, datetime

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.logging import LogChunk, LogStreamPort
from hexaqueue_core.ports.runtime import ExecutionRuntimePort, ProcessExecutionResult
from hexaqueue_core.ports.storage import VolumeAllocation


class NativeDeferenceRuntimeAdapter(ExecutionRuntimePort):
    """Execution runtime adapter deferring process boundary isolation to CSP infrastructure.

    Args:
        log_port: Optional LogStreamPort for streaming captured logs.
    """

    def __init__(self, log_port: LogStreamPort | None = None) -> None:
        self._log_port = log_port
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    async def execute(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        """Execute job directly, delegating isolation to cloud orchestrator.

        Args:
            job: The JobSpec to execute.
            scratch_volume: Optional scratch storage workspace.
            environment: Optional environment variables to inject.

        Returns:
            ProcessExecutionResult summarizing execution outcome.
        """
        cwd = scratch_volume.mount_path if scratch_volume else None
        env = os.environ.copy()
        if environment:
            env.update(environment)

        start_time = datetime.now(UTC)
        proc = await asyncio.create_subprocess_shell(
            job.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        self._active_processes[job.id] = proc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(job.resources.walltime_seconds),
            )
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            exit_code = proc.returncode or 0

            if self._log_port:
                await self._emit_logs(job.id, stdout_bytes, stderr_bytes)

            outcome = (
                TerminalOutcome.COMPLETED if exit_code == 0 else TerminalOutcome.FAILED
            )
            err_msg = (
                stderr_bytes.decode("utf-8", errors="replace")
                if exit_code != 0 and stderr_bytes
                else None
            )

            return ProcessExecutionResult(
                exit_code=exit_code,
                outcome=outcome,
                walltime_seconds=max(0.0, elapsed),
                error_message=err_msg,
            )
        except TimeoutError:
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            await self.terminate(job.id)
            return ProcessExecutionResult(
                exit_code=124,
                outcome=TerminalOutcome.FAILED,
                walltime_seconds=max(0.0, elapsed),
                error_message=f"Job exceeded walltime limit of {job.resources.walltime_seconds}s",
            )
        finally:
            self._active_processes.pop(job.id, None)

    async def _emit_logs(
        self, job_id: str, stdout_bytes: bytes, stderr_bytes: bytes
    ) -> None:
        """Emit captured stdout and stderr bytes to log port."""
        if not self._log_port:
            return
        if stdout_bytes:
            await self._log_port.write_log(
                LogChunk(
                    job_id=job_id,
                    stream="stdout",
                    content=stdout_bytes.decode("utf-8", errors="replace"),
                    offset=0,
                )
            )
        if stderr_bytes:
            await self._log_port.write_log(
                LogChunk(
                    job_id=job_id,
                    stream="stderr",
                    content=stderr_bytes.decode("utf-8", errors="replace"),
                    offset=0,
                )
            )

    async def terminate(self, job_id: str, grace_period_seconds: int = 15) -> None:
        """Terminate job process if actively executing."""
        proc = self._active_processes.get(job_id)
        if proc and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=float(grace_period_seconds))
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()


__all__ = [
    "NativeDeferenceRuntimeAdapter",
]
