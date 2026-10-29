"""MicroVM and hardware virtual machine execution runtime adapter.

Notes/Architectural Intent:
    Executes compute jobs inside isolated MicroVMs and Virtual Machines
    (QEMU, Firecracker, Cloud-Hypervisor). Provides hardware-level virtualization,
    dedicated Linux/Windows kernels, virtio-fs scratch storage passing, and
    serial console output streaming to LogStreamPort in real time.
"""

import asyncio
import contextlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.vm import HypervisorBackend, VmSpec
from hexaqueue_core.ports.logging import LogChunk, LogStreamPort
from hexaqueue_core.ports.runtime import ExecutionRuntimePort, ProcessExecutionResult
from hexaqueue_core.ports.storage import VolumeAllocation
from hexaqueue_worker.domain.vm import MicroVmConfig


def _build_qemu_args(
    vm: VmSpec,
    config: MicroVmConfig,
    scratch_volume: VolumeAllocation | None,
) -> list[str]:
    """Construct argument list for QEMU hypervisor invocation.

    Args:
        vm: Virtual machine specification from job.
        config: Worker microVM configuration.
        scratch_volume: Optional scratch storage volume to attach via virtio-fs/9p.

    Returns:
        List of command-line flags and parameters for QEMU.
    """
    args = [
        config.qemu_binary,
        "-m",
        f"{vm.ram_mb}M",
        "-smp",
        str(vm.vcpus),
        "-nographic",
        "-serial",
        "stdio",
    ]

    if vm.enable_kvm and config.enable_kvm and sys.platform.startswith("linux"):
        args.append("-enable-kvm")

    if vm.is_windows:
        args.extend(["-cpu", "host", "-vga", "std"])
    else:
        args.extend(["-cpu", "host"])

    args.extend(["-drive", f"file={vm.image},if=virtio,format=qcow2"])

    if vm.kernel_path:
        args.extend(["-kernel", vm.kernel_path])
        if vm.kernel_args:
            args.extend(["-append", vm.kernel_args])

    if scratch_volume is not None:
        mount_path = getattr(scratch_volume, "mount_path", str(scratch_volume))
        args.extend(
            [
                "-virtfs",
                f"local,path={mount_path},mount_tag=scratch,security_model=none",
            ]
        )

    for dev in vm.passthrough_devices:
        args.extend(["-device", f"vfio-pci,host={dev}"])

    return args


def _build_firecracker_args(
    vm: VmSpec,
    config: MicroVmConfig,
    socket_path: str,
) -> list[str]:
    """Construct argument list for Firecracker invocation.

    Args:
        vm: Virtual machine specification from job.
        config: Worker microVM configuration.
        socket_path: Host API socket path.

    Returns:
        List of command-line arguments for Firecracker.
    """
    return [
        config.firecracker_binary,
        "--api-sock",
        socket_path,
    ]


class MicroVmExecutionRuntimeAdapter(ExecutionRuntimePort):
    """Adapter for executing workloads in hardware MicroVMs and VMs."""

    def __init__(
        self,
        config: MicroVmConfig | None = None,
        log_port: LogStreamPort | None = None,
        grace_period_seconds: int = 15,
    ) -> None:
        """Initialize MicroVM execution runtime adapter.

        Args:
            config: Worker MicroVM configuration.
            log_port: Optional LogStreamPort for capturing serial console logs.
            grace_period_seconds: Seconds to wait after SIGTERM before SIGKILL.
        """
        self._config = config or MicroVmConfig()
        self._log_port = log_port
        self._grace_period_seconds = grace_period_seconds
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    def build_command_args(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
    ) -> list[str]:
        """Build the hypervisor command-line arguments for a job.

        Args:
            job: The JobSpec to execute.
            scratch_volume: Optional scratch volume allocation.

        Returns:
            List of executable strings for the hypervisor invocation.
        """
        vm = job.vm or VmSpec(
            image=job.command,
            backend=self._config.default_backend,
        )

        if vm.backend == HypervisorBackend.FIRECRACKER:
            socket_path = str(Path(self._config.socket_dir) / f"{job.id}.sock")
            return _build_firecracker_args(vm, self._config, socket_path)

        if vm.backend == HypervisorBackend.CLOUD_HYPERVISOR:
            return [
                self._config.cloud_hypervisor_binary,
                "--cpus",
                f"boot={vm.vcpus}",
                "--memory",
                f"size={vm.ram_mb}M",
                "--disk",
                f"path={vm.image}",
                "--serial",
                "tty",
                "--console",
                "off",
            ]

        return _build_qemu_args(vm, self._config, scratch_volume)

    async def execute(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        """Execute a compute job inside a dedicated MicroVM or VM.

        Args:
            job: The complete JobSpec definition to execute.
            scratch_volume: Optional scratch storage allocation.
            environment: Optional environment variables to pass to the hypervisor process.

        Returns:
            ProcessExecutionResult summarizing exit code, walltime, and outcome.

        Raises:
            HexaqueueError: If hypervisor fails to launch.
        """
        cmd_args = self.build_command_args(job, scratch_volume)
        env = os.environ.copy()
        if environment:
            env.update(environment)

        start_time = datetime.now(UTC)
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                cmd_args[0],
                *cmd_args[1:],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self._active_processes[job.id] = proc

            timeout = (
                job.resources.walltime_seconds
                if (job.resources and job.resources.walltime_seconds)
                else self._config.default_timeout_seconds
            )

            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            elapsed = (datetime.now(UTC) - start_time).total_seconds()

            if self._log_port is not None:
                await self._stream_logs(job.id, stdout_data, stderr_data)

            exit_code = proc.returncode if proc.returncode is not None else 0
            outcome = (
                TerminalOutcome.COMPLETED if exit_code == 0 else TerminalOutcome.FAILED
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
                walltime_seconds=max(0.0, elapsed),
            )
        except TimeoutError:
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            await self.terminate(job.id, grace_period_seconds=2)
            return ProcessExecutionResult(
                exit_code=124,
                outcome=TerminalOutcome.TIMED_OUT,
                error_message=f"Job exceeded walltime limit of {timeout}s",
                walltime_seconds=elapsed,
            )
        except Exception as err:
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            msg = f"Hypervisor execution error for job '{job.id}': {err}"
            raise HexaqueueError(msg) from err
        finally:
            self._active_processes.pop(job.id, None)

    async def _stream_logs(
        self, job_id: str, stdout_data: bytes, stderr_data: bytes
    ) -> None:
        """Helper to stream serial console logs to the LogStreamPort."""
        if not self._log_port:
            return
        if stdout_data:
            chunk = LogChunk(
                job_id=job_id,
                stream="stdout",
                content=stdout_data.decode("utf-8", errors="replace"),
                offset=0,
                timestamp=datetime.now(UTC),
            )
            await self._log_port.write_log(chunk)
        if stderr_data:
            chunk = LogChunk(
                job_id=job_id,
                stream="stderr",
                content=stderr_data.decode("utf-8", errors="replace"),
                offset=0,
                timestamp=datetime.now(UTC),
            )
            await self._log_port.write_log(chunk)

    async def terminate(self, job_id: str, grace_period_seconds: int = 15) -> None:
        """Forcibly interrupt or terminate a running hypervisor process.

        Args:
            job_id: The job identifier to terminate.
            grace_period_seconds: Grace period duration before SIGKILL.
        """
        proc = self._active_processes.get(job_id)
        if proc is None or proc.returncode is not None:
            return

        with contextlib.suppress(ProcessLookupError):
            proc.terminate()

        try:
            await asyncio.wait_for(proc.wait(), timeout=grace_period_seconds)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
