"""Local subprocess execution runtime adapter."""

import asyncio
import os
from datetime import UTC, datetime
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.logging import LogChunk, LogStreamPort
from hexaqueue_core.ports.runtime import ExecutionRuntimePort, ProcessExecutionResult
from hexaqueue_core.ports.storage import VolumeAllocation


class LocalSubprocessExecutionRuntimeAdapter(ExecutionRuntimePort):
    """Local subprocess execution runtime adapter."""

    def __init__(self, log_port: LogStreamPort | None = None) -> None:
        self._log_port = log_port
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    async def execute(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        """Execute job via bash subprocess with timeout and log capture."""
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
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(job.resources.walltime_seconds),
            )
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            exit_code = proc.returncode or 0

            if self._log_port:
                if stdout_data:
                    await self._log_port.write_log(
                        LogChunk(
                            job_id=job.id,
                            stream="stdout",
                            content=stdout_data.decode("utf-8", errors="replace"),
                            offset=0,
                        )
                    )
                if stderr_data:
                    await self._log_port.write_log(
                        LogChunk(
                            job_id=job.id,
                            stream="stderr",
                            content=stderr_data.decode("utf-8", errors="replace"),
                            offset=0,
                        )
                    )

            outcome = (
                TerminalOutcome.COMPLETED
                if exit_code == 0
                else TerminalOutcome.FAILED
            )
            error_msg = (
                stderr_data.decode("utf-8", errors="replace")
                if exit_code != 0
                else None
            )

            return ProcessExecutionResult(
                exit_code=exit_code,
                outcome=outcome,
                error_message=error_msg,
                walltime_seconds=elapsed,
            )

        except TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            return ProcessExecutionResult(
                exit_code=-1,
                outcome=TerminalOutcome.TIMED_OUT,
                error_message=f"Job exceeded walltime limit of {job.resources.walltime_seconds}s",
                walltime_seconds=elapsed,
            )
        finally:
            self._active_processes.pop(job.id, None)

    async def terminate(self, job_id: str, grace_period_seconds: int = 15) -> None:
        """Terminate running subprocess."""
        if proc := self._active_processes.get(job_id):
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=grace_period_seconds)
            except TimeoutError:
                proc.kill()
                await proc.wait()


__all__ = [
    "LocalSubprocessExecutionRuntimeAdapter",
]
