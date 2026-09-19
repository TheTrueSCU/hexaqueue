"""Local subprocess execution runtime adapter."""

import asyncio
import contextlib
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

    async def _stream_pipe(
        self,
        reader: asyncio.StreamReader | None,
        stream_name: str,
        job_id: str,
        collected: list[str],
    ) -> None:
        """Stream a subprocess pipe line-by-line to the log port in real time.

        Args:
            reader: StreamReader for stdout or stderr.
            stream_name: 'stdout' or 'stderr'.
            job_id: Unique job identifier.
            collected: In-memory accumulator for error messages and diagnostics.

        Notes/Architectural Intent:
            Reads incremental lines as they are flushed by the subprocess rather than
            buffering the entire execution run in memory, enabling live streaming to observers.
        """
        if reader is None:
            return
        offset = 0
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                collected.append(text)
                if self._log_port:
                    await self._log_port.write_log(
                        LogChunk(
                            job_id=job_id,
                            stream=stream_name,
                            content=text,
                            offset=offset,
                        )
                    )
                    offset += 1
        except asyncio.CancelledError:
            pass

    async def execute(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        """Execute job via bash subprocess with timeout and real-time log capture.

        Args:
            job: Job specification to execute.
            scratch_volume: Ephemeral volume allocation for working directory.
            environment: Optional environment variables override.

        Returns:
            ProcessExecutionResult with terminal outcome and timings.
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

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        pipe_tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(
                self._stream_pipe(proc.stdout, "stdout", job.id, stdout_chunks)
            ),
            asyncio.create_task(
                self._stream_pipe(proc.stderr, "stderr", job.id, stderr_chunks)
            ),
        ]
        gather_task = asyncio.gather(proc.wait(), *pipe_tasks)
        try:
            await asyncio.wait_for(
                gather_task,
                timeout=float(job.resources.walltime_seconds),
            )
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            exit_code = proc.returncode or 0

            outcome = (
                TerminalOutcome.COMPLETED if exit_code == 0 else TerminalOutcome.FAILED
            )
            error_msg = "".join(stderr_chunks) if exit_code != 0 else None

            return ProcessExecutionResult(
                exit_code=exit_code,
                outcome=outcome,
                error_message=error_msg,
                walltime_seconds=elapsed,
            )

        except TimeoutError:
            gather_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await gather_task
            for t in pipe_tasks:
                t.cancel()
            await asyncio.gather(*pipe_tasks, return_exceptions=True)
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
            if self._log_port:
                await self._log_port.close_stream(job.id)
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
