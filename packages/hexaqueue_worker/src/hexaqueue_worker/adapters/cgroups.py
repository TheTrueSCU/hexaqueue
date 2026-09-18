"""Linux Cgroups v2 compute execution runtime adapter.

Notes/Architectural Intent:
    Spawns compute workloads inside isolated POSIX process groups with Linux Cgroups v2
    resource limits applied (cpu.max CFS quotas and memory.max memory ceiling).
    Ensures complete, leak-free process tree teardown upon exit, cancellation, or walltime
    timeout by dispatching SIGTERM and SIGKILL across the process group.
"""

import asyncio
import contextlib
import os
import shutil
import signal
from datetime import UTC, datetime
from pathlib import Path

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.logging import LogChunk, LogStreamPort
from hexaqueue_core.ports.runtime import ExecutionRuntimePort, ProcessExecutionResult
from hexaqueue_core.ports.storage import VolumeAllocation
from hexaqueue_worker.domain.cgroups import CgroupConfig, CgroupLimits


class CgroupsV2ProcessAdapter(ExecutionRuntimePort):
    """Execution runtime adapter leveraging Linux Cgroups v2 and POSIX process groups.

    Args:
        cgroup_config: Optional CgroupConfig for cgroups v2 mount paths and prefixes.
        log_port: Optional LogStreamPort for streaming captured process logs.
        grace_period_seconds: Default seconds to wait between SIGTERM and SIGKILL.
    """

    def __init__(
        self,
        cgroup_config: CgroupConfig | None = None,
        log_port: LogStreamPort | None = None,
        grace_period_seconds: int = 15,
    ) -> None:
        self._cgroup_config = cgroup_config or CgroupConfig()
        self._log_port = log_port
        self._grace_period_seconds = grace_period_seconds
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._cgroup_dirs: dict[str, Path] = {}

    def _setup_cgroup(self, job_id: str, limits: CgroupLimits) -> Path | None:
        """Create per-job cgroup directory and write control limits.

        Args:
            job_id: Unique job identifier.
            limits: Calculated CgroupLimits.

        Returns:
            Path to cgroup directory if successfully configured, None otherwise.
        """
        cgroup_path = (
            Path(self._cgroup_config.cgroup_fs_root)
            / f"{self._cgroup_config.cgroup_name_prefix}{job_id}"
        )
        try:
            cgroup_path.mkdir(parents=True, exist_ok=True)
            (cgroup_path / "cpu.max").write_text(limits.cpu_max_str)
            (cgroup_path / "memory.max").write_text(limits.memory_max_str)
            if limits.memory_high_str is not None:
                (cgroup_path / "memory.high").write_text(limits.memory_high_str)
            return cgroup_path
        except (PermissionError, FileNotFoundError, OSError):
            return None

    def _attach_pid_to_cgroup(self, cgroup_path: Path | None, pid: int) -> None:
        """Write spawned process PID into cgroup.procs file.

        Args:
            cgroup_path: Path to target cgroup directory.
            pid: Process ID to attach.
        """
        if cgroup_path is None:
            return
        procs_file = cgroup_path / "cgroup.procs"
        try:
            if procs_file.exists():
                procs_file.write_text(str(pid))
        except OSError:
            pass

    def _teardown_cgroup(self, cgroup_path: Path | None) -> None:
        """Remove per-job cgroup directory upon completion.

        Args:
            cgroup_path: Path to cgroup directory to remove.
        """
        if cgroup_path is None:
            return
        with contextlib.suppress(OSError):
            if cgroup_path.exists():
                shutil.rmtree(cgroup_path, ignore_errors=True)

    async def _kill_process_group(
        self, proc: asyncio.subprocess.Process, grace_period_seconds: int
    ) -> None:
        """Terminate entire process group with SIGTERM escalating to SIGKILL.

        Args:
            proc: Subprocess instance to kill.
            grace_period_seconds: Seconds to wait before SIGKILL escalation.
        """
        pid = proc.pid
        if pid is None:
            return

        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(pid), signal.SIGTERM)

        wait_count = int(grace_period_seconds * 10)
        for _ in range(max(1, wait_count)):
            if proc.returncode is not None:
                return
            await asyncio.sleep(0.1)

        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(pid), signal.SIGKILL)

    async def execute(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        """Execute compute job inside cgroups v2 enclosure with resource limits.

        Args:
            job: The JobSpec to execute.
            scratch_volume: Optional scratch storage allocation for workspace cwd.
            environment: Optional environment variables to inject.

        Returns:
            ProcessExecutionResult summarizing outcome, exit code, and walltime.
        """
        cwd = scratch_volume.mount_path if scratch_volume else None
        env = os.environ.copy()
        if environment:
            env.update(environment)

        limits = CgroupLimits.from_resources(
            cpus=job.resources.cpus,
            ram_mb=job.resources.ram_mb,
        )
        cgroup_dir = self._setup_cgroup(job.id, limits)
        if cgroup_dir:
            self._cgroup_dirs[job.id] = cgroup_dir

        start_time = datetime.now(UTC)
        proc = await asyncio.create_subprocess_shell(
            job.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )
        self._active_processes[job.id] = proc
        if proc.pid is not None:
            self._attach_pid_to_cgroup(cgroup_dir, proc.pid)

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
            await self._kill_process_group(proc, self._grace_period_seconds)
            return ProcessExecutionResult(
                exit_code=124,
                outcome=TerminalOutcome.FAILED,
                walltime_seconds=max(0.0, elapsed),
                error_message=f"Job exceeded walltime limit of {job.resources.walltime_seconds}s",
            )
        finally:
            self._active_processes.pop(job.id, None)
            cgroup_path = self._cgroup_dirs.pop(job.id, None)
            self._teardown_cgroup(cgroup_path)

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
        """Forcibly terminate running job and release its cgroup enclosure."""
        proc = self._active_processes.get(job_id)
        if proc:
            await self._kill_process_group(proc, grace_period_seconds)
        cgroup_path = self._cgroup_dirs.pop(job_id, None)
        self._teardown_cgroup(cgroup_path)


__all__ = [
    "CgroupsV2ProcessAdapter",
]
