"""Rootless Podman container execution runtime adapter.

Notes/Architectural Intent:
    Executes compute jobs inside isolated OCI containers via rootless Podman.
    Applies cgroups v2 resource slicing (--cpus, -m), user namespace preservation
    (--userns=keep-id), scratch directory mounting, GPU passthrough, and clean process
    tree termination.
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
from hexaqueue_worker.domain.container import PodmanConfig


class PodmanExecutionRuntimeAdapter(ExecutionRuntimePort):
    """Execution runtime adapter leveraging rootless Podman OCI containers.

    Args:
        config: Optional PodmanConfig defining binary paths, isolation flags, and defaults.
        log_port: Optional LogStreamPort for streaming captured container logs.
        grace_period_seconds: Default seconds to wait during graceful container stop.
    """

    def __init__(
        self,
        config: PodmanConfig | None = None,
        log_port: LogStreamPort | None = None,
        grace_period_seconds: int = 15,
    ) -> None:
        self._config = config or PodmanConfig()
        self._log_port = log_port
        self._grace_period_seconds = grace_period_seconds
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    def _build_isolation_flags(self, job_id: str) -> list[str]:
        """Build flags for container identity, user namespaces, and network isolation."""
        flags = [self._config.executable_path, "run", "--rm", "--name", f"hq-{job_id}"]
        if self._config.rootless:
            flags.extend(["--userns", self._config.userns_mode])
        if self._config.network_mode:
            flags.extend(["--net", self._config.network_mode])
        if self._config.seccomp_profile:
            flags.extend(["--security-opt", f"seccomp={self._config.seccomp_profile}"])
        return flags

    def _build_volume_and_resource_flags(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None,
        workdir: str,
    ) -> list[str]:
        """Build storage mount and cgroups resource slicing flags."""
        flags: list[str] = ["-w", workdir]
        if scratch_volume is not None:
            relabel = ":Z" if self._config.selinux_relabel else ""
            flags.extend(["-v", f"{scratch_volume.mount_path}:{workdir}{relabel}"])

        if job.container is not None:
            for mount in job.container.mounts:
                ro_suffix = ":ro" if mount.read_only else ""
                flags.extend(["-v", f"{mount.source}:{mount.target}{ro_suffix}"])

        if job.resources.cpus > 0:
            flags.extend(["--cpus", str(job.resources.cpus)])

        if job.resources.ram_mb > 0:
            flags.extend(["-m", f"{job.resources.ram_mb}m"])

        has_gpu = job.resources.gpus > 0 or (
            job.container is not None and job.container.gpu_enabled
        )
        if has_gpu and self._config.gpu_flag:
            flags.extend(self._config.gpu_flag.split())

        read_only = self._config.read_only_rootfs or (
            job.container is not None and job.container.read_only_rootfs
        )
        if read_only:
            flags.extend(["--read-only", "--tmpfs", "/tmp"])

        return flags

    def _build_execution_args(
        self,
        job: JobSpec,
        environment: dict[str, str] | None,
    ) -> list[str]:
        """Build environment, privileges, image, and command execution arguments."""
        flags: list[str] = []
        merged_env = {**job.env, **(environment or {})}
        for k, v in sorted(merged_env.items()):
            flags.extend(["-e", f"{k}={v}"])

        if job.container is not None and job.container.privileged:
            flags.append("--privileged")

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
        """Construct the complete podman run command arguments.

        Args:
            job: The JobSpec to execute.
            scratch_volume: Optional scratch storage allocation for workspace mounting.
            environment: Optional extra environment variables to inject.

        Returns:
            List of CLI argument tokens forming the podman command.
        """
        workdir = (
            job.container.workdir
            if (job.container and job.container.workdir)
            else "/workspace"
        )
        cmd = self._build_isolation_flags(job.id)
        cmd.extend(
            self._build_volume_and_resource_flags(
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
        """Execute a compute job within a rootless Podman OCI container.

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
                    error_message=f"Container execution exceeded walltime timeout of {walltime_limit}s",
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
                    or f"Container exited with code {exit_code}"
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
                error_message=f"Podman execution error: {e}",
                walltime_seconds=elapsed,
            )
        finally:
            self._active_processes.pop(job.id, None)

    async def terminate(self, job_id: str, grace_period_seconds: int = 15) -> None:
        """Gracefully stop or forcibly terminate an active Podman container.

        Args:
            job_id: The job identifier to terminate.
            grace_period_seconds: Seconds to wait after SIGTERM before SIGKILL.
        """
        process = self._active_processes.get(job_id)
        if process is None:
            return

        stop_cmd = [
            self._config.executable_path,
            "stop",
            "-t",
            str(grace_period_seconds),
            f"hq-{job_id}",
        ]
        with contextlib.suppress(Exception):
            stop_proc = await asyncio.create_subprocess_exec(
                *stop_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(
                stop_proc.wait(), timeout=float(grace_period_seconds + 5)
            )

        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            with contextlib.suppress(Exception):
                await process.wait()


__all__ = [
    "PodmanExecutionRuntimeAdapter",
]
