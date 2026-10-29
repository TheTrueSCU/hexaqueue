"""Docker container execution runtime adapter supporting Linux and Windows.

Notes/Architectural Intent:
    Executes compute jobs inside isolated OCI containers via Docker daemon API / CLI.
    Supports both Linux rootless/rootful Docker and native Windows Containers (Process
    and Hyper-V isolation modes). Applies cgroups/Windows resource limits (--cpus, -m),
    scratch volume mounting, GPU passthrough (--gpus), and robust cross-platform
    process tree termination.
"""

import asyncio
import contextlib
import os
import shlex
import signal
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.logging import LogChunk, LogStreamPort
from hexaqueue_core.ports.runtime import ExecutionRuntimePort, ProcessExecutionResult
from hexaqueue_core.ports.storage import VolumeAllocation
from hexaqueue_worker.domain.container import DockerConfig


def _is_windows_target(job: JobSpec, config: DockerConfig) -> bool:
    """Determine whether the target container execution is a Windows container.

    Args:
        job: Job specification.
        config: Docker runtime configuration.

    Returns:
        True if target execution environment is Windows container, False otherwise.
    """
    if job.container is not None and job.container.isolation:
        return True
    if config.isolation:
        return True
    if job.container is not None and job.container.workdir:
        wd = job.container.workdir.lower()
        if wd.startswith("c:") or "\\" in wd:
            return True
    return False


class DockerExecutionRuntimeAdapter(ExecutionRuntimePort):
    """Execution runtime adapter leveraging Docker daemon on Linux and Windows.

    Args:
        config: Optional DockerConfig defining executable path, host socket, and flags.
        log_port: Optional LogStreamPort for streaming captured container logs.
        grace_period_seconds: Default seconds to wait during graceful container stop.
    """

    def __init__(
        self,
        config: DockerConfig | None = None,
        log_port: LogStreamPort | None = None,
        grace_period_seconds: int = 15,
    ) -> None:
        self._config = config or DockerConfig()
        self._log_port = log_port
        self._grace_period_seconds = grace_period_seconds
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    def _build_daemon_and_isolation_flags(
        self, job_id: str, is_win: bool, job: JobSpec
    ) -> list[str]:
        """Build initial flags for docker daemon endpoint, container name, and isolation."""
        flags = [self._config.executable_path]
        if self._config.host:
            flags.extend(["-H", self._config.host])
        flags.extend(["run", "--rm", "--name", f"hq-{job_id}"])

        isolation = (
            job.container.isolation
            if (job.container and job.container.isolation)
            else self._config.isolation
        )
        if isolation:
            flags.extend(["--isolation", isolation])

        if self._config.user:
            flags.extend(["--user", self._config.user])

        if self._config.network_mode:
            flags.extend(["--net", self._config.network_mode])

        if not is_win and self._config.seccomp_profile:
            flags.extend(["--security-opt", f"seccomp={self._config.seccomp_profile}"])

        return flags

    def _build_volume_and_resource_flags(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None,
        workdir: str,
        is_win: bool,
    ) -> list[str]:
        """Build storage mount and CPU/memory resource slicing flags."""
        flags: list[str] = ["-w", workdir]
        if scratch_volume is not None:
            flags.extend(["-v", f"{scratch_volume.mount_path}:{workdir}"])

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
        if read_only and not is_win:
            flags.extend(["--read-only", "--tmpfs", "/tmp"])

        return flags

    def _build_execution_args(
        self,
        job: JobSpec,
        environment: dict[str, str] | None,
        is_win: bool,
    ) -> list[str]:
        """Build environment variables, image tag, and command execution tokens."""
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
            cmd = f"{job.command} {shlex.join(job.args)}" if job.args else job.command
            if is_win:
                flags.extend(["cmd.exe", "/c", cmd])
            else:
                shell_prefix = self._config.shell or ["sh", "-c"]
                flags.extend([*shell_prefix, cmd])

        return flags

    def build_command(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> list[str]:
        """Construct the complete docker run command argument list.

        Args:
            job: The JobSpec to execute.
            scratch_volume: Optional scratch storage allocation for workspace mounting.
            environment: Optional extra environment variables to inject.

        Returns:
            List of CLI argument tokens forming the docker run invocation.
        """
        is_win = _is_windows_target(job, self._config)
        default_workdir = "C:\\workspace" if is_win else "/workspace"
        workdir = (
            job.container.workdir
            if (job.container and job.container.workdir)
            else default_workdir
        )

        cmd = self._build_daemon_and_isolation_flags(
            job_id=job.id, is_win=is_win, job=job
        )
        cmd.extend(
            self._build_volume_and_resource_flags(
                job=job,
                scratch_volume=scratch_volume,
                workdir=workdir,
                is_win=is_win,
            )
        )
        cmd.extend(
            self._build_execution_args(
                job=job,
                environment=environment,
                is_win=is_win,
            )
        )
        return cmd

    async def _stream_logs(
        self, job_id: str, stdout_data: bytes, stderr_data: bytes
    ) -> None:
        """Stream stdout and stderr output chunks to log port if wired."""
        if self._log_port is None:
            return
        if stdout_data:
            await self._log_port.write_log(
                LogChunk(
                    job_id=job_id,
                    stream="stdout",
                    content=stdout_data.decode(errors="replace"),
                    offset=0,
                )
            )
        if stderr_data:
            await self._log_port.write_log(
                LogChunk(
                    job_id=job_id,
                    stream="stderr",
                    content=stderr_data.decode(errors="replace"),
                    offset=0,
                )
            )

    async def execute(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        """Execute a compute job within an isolated Docker container.

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
            extra_kwargs: dict[str, Any] = {}
            if sys.platform == "win32":
                extra_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                extra_kwargs["preexec_fn"] = os.setsid

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **extra_kwargs,
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

            await self._stream_logs(job.id, stdout_data, stderr_data)

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
                error_message=f"Docker execution error: {e}",
                walltime_seconds=elapsed,
            )
        finally:
            self._active_processes.pop(job.id, None)

    async def terminate(self, job_id: str, grace_period_seconds: int = 15) -> None:
        """Gracefully stop or forcibly terminate an active Docker container.

        Args:
            job_id: The job identifier to terminate.
            grace_period_seconds: Seconds to wait after stop before forcible termination.
        """
        process = self._active_processes.get(job_id)
        if process is None:
            return

        stop_cmd = [self._config.executable_path]
        if self._config.host:
            stop_cmd.extend(["-H", self._config.host])
        stop_cmd.extend(
            [
                "stop",
                "-t",
                str(grace_period_seconds),
                f"hq-{job_id}",
            ]
        )

        with contextlib.suppress(Exception):
            stop_proc = await asyncio.create_subprocess_exec(
                *stop_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(
                stop_proc.wait(), timeout=float(grace_period_seconds + 5)
            )

        if process.returncode is None and process.pid is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                if sys.platform != "win32":
                    pgid = os.getpgid(process.pid)
                    if pgid != os.getpgrp():
                        os.killpg(pgid, signal.SIGKILL)
                    else:
                        process.kill()
                else:
                    process.kill()
            with contextlib.suppress(Exception):
                await process.wait()


__all__ = [
    "DockerExecutionRuntimeAdapter",
]
