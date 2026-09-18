"""Apptainer / Singularity HPC container execution runtime adapter.

Notes/Architectural Intent:
    Executes compute jobs inside isolated unprivileged containers via Apptainer/Singularity.
    Supports native SIF images, OCI/Docker registries (docker://), HPC GPU acceleration
    (--nv and --rocm), bind mounting scratch workspaces, and clean process group termination.
"""

import asyncio
import contextlib
import os
import signal
from datetime import UTC, datetime

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.logging import LogChunk, LogStreamPort
from hexaqueue_core.ports.runtime import ExecutionRuntimePort, ProcessExecutionResult
from hexaqueue_core.ports.storage import VolumeAllocation
from hexaqueue_worker.domain.container import ApptainerConfig


class ApptainerExecutionRuntimeAdapter(ExecutionRuntimePort):
    """Execution runtime adapter leveraging Apptainer/Singularity for HPC workloads.

    Args:
        config: Optional ApptainerConfig defining CLI paths and containment options.
        log_port: Optional LogStreamPort for streaming captured logs.
        grace_period_seconds: Default seconds to wait during graceful termination.
    """

    def __init__(
        self,
        config: ApptainerConfig | None = None,
        log_port: LogStreamPort | None = None,
        grace_period_seconds: int = 15,
    ) -> None:
        self._config = config or ApptainerConfig()
        self._log_port = log_port
        self._grace_period_seconds = grace_period_seconds
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    def _build_isolation_flags(self) -> list[str]:
        """Build Apptainer environment isolation flags."""
        flags = [self._config.executable_path, "exec"]
        if self._config.containall:
            flags.append("--containall")
        if self._config.cleanenv:
            flags.append("--cleanenv")
        if self._config.writable_tmpfs:
            flags.append("--writable-tmpfs")
        return flags

    def _build_volume_and_gpu_flags(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None,
        workdir: str,
    ) -> list[str]:
        """Build storage mount bindings and GPU passthrough flags."""
        flags: list[str] = ["--pwd", workdir]
        if scratch_volume is not None:
            flags.extend(["--bind", f"{scratch_volume.mount_path}:{workdir}"])

        if job.container is not None:
            for mount in job.container.mounts:
                ro_suffix = ":ro" if mount.read_only else ""
                flags.extend(["--bind", f"{mount.source}:{mount.target}{ro_suffix}"])

        has_gpu = job.resources.gpus > 0 or (
            job.container is not None and job.container.gpu_enabled
        )
        if has_gpu:
            if self._config.nv_gpu:
                flags.append("--nv")
            if self._config.rocm_gpu:
                flags.append("--rocm")

        return flags

    def _build_execution_args(
        self,
        job: JobSpec,
        environment: dict[str, str] | None,
    ) -> list[str]:
        """Build environment, image, and command execution tokens."""
        flags: list[str] = []
        merged_env = {**job.env, **(environment or {})}
        for k, v in sorted(merged_env.items()):
            flags.extend(["--env", f"{k}={v}"])

        if job.container is not None and job.container.extra_args:
            flags.extend(job.container.extra_args)

        image = (
            job.container.image
            if (job.container and job.container.image)
            else self._config.default_image
        )
        flags.append(image)

        if job.container is not None and job.container.entrypoint:
            flags.extend(job.container.entrypoint)
            flags.extend(job.args)
        else:
            flags.extend(["sh", "-c", job.command])

        return flags

    def build_command(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> list[str]:
        """Construct the complete apptainer exec command arguments.

        Args:
            job: The JobSpec to execute.
            scratch_volume: Optional scratch storage allocation for workspace mounting.
            environment: Optional extra environment variables to inject.

        Returns:
            List of CLI argument tokens forming the apptainer command.
        """
        workdir = (
            job.container.workdir
            if (job.container and job.container.workdir)
            else "/workspace"
        )
        cmd = self._build_isolation_flags()
        cmd.extend(
            self._build_volume_and_gpu_flags(
                job=job,
                scratch_volume=scratch_volume,
                workdir=workdir,
            )
        )
        cmd.extend(
            self._build_execution_args(
                job=job,
                environment=environment,
            )
        )
        return cmd

    async def execute(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        """Execute a compute job within an Apptainer HPC container.

        Args:
            job: The JobSpec definition to execute.
            scratch_volume: Optional scratch storage allocation.
            environment: Optional environment variables to inject.

        Returns:
            ProcessExecutionResult summarizing container outcome, exit code, and walltime.
        """
        start_time = datetime.now(UTC)
        cmd = self.build_command(
            job=job,
            scratch_volume=scratch_volume,
            environment=environment,
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid,
            )
            self._active_processes[job.id] = process

            walltime_limit = (
                job.resources.walltime_seconds
                if job.resources.walltime_seconds > 0
                else None
            )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(), timeout=walltime_limit
                )
            except TimeoutError:
                await self.terminate(job.id, grace_period_seconds=2)
                elapsed = (datetime.now(UTC) - start_time).total_seconds()
                return ProcessExecutionResult(
                    exit_code=124,
                    outcome=TerminalOutcome.TIMED_OUT,
                    error_message=f"Apptainer execution exceeded walltime timeout of {walltime_limit}s",
                    walltime_seconds=elapsed,
                )

            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            exit_code = process.returncode or 0

            if self._log_port is not None:
                if stdout_data:
                    await self._log_port.write_log(
                        LogChunk(
                            job_id=job.id,
                            stream="stdout",
                            content=stdout_data.decode(errors="replace"),
                            offset=0,
                        )
                    )
                if stderr_data:
                    await self._log_port.write_log(
                        LogChunk(
                            job_id=job.id,
                            stream="stderr",
                            content=stderr_data.decode(errors="replace"),
                            offset=0,
                        )
                    )

            if exit_code == 0:
                outcome = TerminalOutcome.COMPLETED
                err_msg = None
            else:
                outcome = TerminalOutcome.FAILED
                err_msg = (
                    stderr_data.decode(errors="replace").strip()
                    or f"Apptainer exited with code {exit_code}"
                )

            return ProcessExecutionResult(
                exit_code=exit_code,
                outcome=outcome,
                error_message=err_msg,
                walltime_seconds=elapsed,
            )
        except Exception as e:
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            return ProcessExecutionResult(
                exit_code=1,
                outcome=TerminalOutcome.FAILED,
                error_message=f"Apptainer execution error: {e}",
                walltime_seconds=elapsed,
            )
        finally:
            self._active_processes.pop(job.id, None)

    async def terminate(self, job_id: str, grace_period_seconds: int = 15) -> None:
        """Gracefully terminate an active Apptainer process group.

        Args:
            job_id: The job identifier to terminate.
            grace_period_seconds: Seconds to wait after SIGTERM before SIGKILL.
        """
        process = self._active_processes.get(job_id)
        if process is None:
            return

        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)

        try:
            await asyncio.wait_for(process.wait(), timeout=float(grace_period_seconds))
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            with contextlib.suppress(Exception):
                await process.wait()


__all__ = [
    "ApptainerExecutionRuntimeAdapter",
]
