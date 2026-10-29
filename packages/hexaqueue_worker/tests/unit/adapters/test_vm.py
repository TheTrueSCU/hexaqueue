"""Unit tests for MicroVmExecutionRuntimeAdapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.vm import HypervisorBackend, VmSpec
from hexaqueue_core.ports.logging import LogStreamPort
from hexaqueue_core.ports.storage import VolumeAllocation
from hexaqueue_worker.adapters.vm import MicroVmExecutionRuntimeAdapter


def test_build_command_args_qemu_linux() -> None:
    """Verify QEMU command arguments for Linux guest."""
    adapter = MicroVmExecutionRuntimeAdapter()
    job = JobSpec(
        id="job-vm-1",
        run_id="run-1",
        name="linux-kernel-test",
        command="test",
        vm=VmSpec(
            image="/var/images/linux.qcow2",
            backend=HypervisorBackend.QEMU,
            vcpus=2,
            ram_mb=2048,
            kernel_path="/boot/vmlinux",
            kernel_args="console=ttyS0",
        ),
    )
    args = adapter.build_command_args(job)
    assert "qemu-system-x86_64" in args[0]
    assert "-m" in args
    assert "2048M" in args
    assert "-smp" in args
    assert "2" in args
    assert "-kernel" in args
    assert "/boot/vmlinux" in args


def test_build_command_args_qemu_windows() -> None:
    """Verify QEMU command arguments for Windows guest."""
    adapter = MicroVmExecutionRuntimeAdapter()
    job = JobSpec(
        id="job-vm-win",
        run_id="run-1",
        name="win-test",
        command="test",
        vm=VmSpec(
            image="/var/images/win.qcow2",
            is_windows=True,
            vcpus=4,
            ram_mb=8192,
        ),
    )
    args = adapter.build_command_args(job)
    assert "-vga" in args
    assert "std" in args


def test_build_command_args_qemu_with_scratch_volume() -> None:
    """Verify QEMU attaches scratch storage via virtfs."""
    adapter = MicroVmExecutionRuntimeAdapter()
    job = JobSpec(
        id="job-vm-scratch",
        run_id="run-1",
        name="scratch-test",
        command="test",
        vm=VmSpec(image="/var/images/test.qcow2"),
    )
    vol = VolumeAllocation(volume_id="vol-1", mount_path="/mnt/scratch", size_mb=1024)
    args = adapter.build_command_args(job, scratch_volume=vol)
    assert "-virtfs" in args
    mount_flag = any("path=/mnt/scratch" in arg for arg in args)
    assert mount_flag is True


def test_build_command_args_firecracker() -> None:
    """Verify Firecracker arguments."""
    adapter = MicroVmExecutionRuntimeAdapter()
    job = JobSpec(
        id="job-fc",
        run_id="run-1",
        name="fc-test",
        command="test",
        vm=VmSpec(
            image="/var/images/rootfs.ext4",
            backend=HypervisorBackend.FIRECRACKER,
        ),
    )
    args = adapter.build_command_args(job)
    assert "firecracker" in args[0]
    assert "--api-sock" in args


def test_build_command_args_cloud_hypervisor() -> None:
    """Verify Cloud-Hypervisor arguments."""
    adapter = MicroVmExecutionRuntimeAdapter()
    job = JobSpec(
        id="job-ch",
        run_id="run-1",
        name="ch-test",
        command="test",
        vm=VmSpec(
            image="/var/images/ch.raw",
            backend=HypervisorBackend.CLOUD_HYPERVISOR,
            vcpus=3,
            ram_mb=4096,
        ),
    )
    args = adapter.build_command_args(job)
    assert "cloud-hypervisor" in args[0]
    assert "--cpus" in args
    assert "boot=3" in args


@pytest.mark.asyncio
async def test_execute_success_and_log_streaming() -> None:
    """Verify execution with mock process completion and log streaming."""
    mock_log_port = AsyncMock(spec=LogStreamPort)
    adapter = MicroVmExecutionRuntimeAdapter(log_port=mock_log_port)

    job = JobSpec(
        id="job-exec-1",
        run_id="run-1",
        name="exec-test",
        command="test",
        vm=VmSpec(image="/var/images/test.qcow2"),
    )

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"VM booted successfully\n", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await adapter.execute(job)

    code = res.exit_code
    assert code == 0
    outcome = res.outcome
    assert outcome == TerminalOutcome.COMPLETED
    assert mock_log_port.write_log.call_count == 1


@pytest.mark.asyncio
async def test_execute_timeout() -> None:
    """Verify timeout outcome when hypervisor execution exceeds walltime."""
    adapter = MicroVmExecutionRuntimeAdapter()
    job = JobSpec(
        id="job-timeout",
        run_id="run-1",
        name="timeout-test",
        command="test",
        resources=ResourceRequirements(walltime_seconds=10),
        vm=VmSpec(image="/var/images/test.qcow2"),
    )

    mock_proc = AsyncMock()
    mock_proc.communicate.side_effect = TimeoutError()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await adapter.execute(job)

    outcome = res.outcome
    assert outcome == TerminalOutcome.TIMED_OUT
    code = res.exit_code
    assert code == 124


@pytest.mark.asyncio
async def test_terminate_running_process() -> None:
    """Verify terminate signals running process."""
    adapter = MicroVmExecutionRuntimeAdapter()
    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.wait.return_value = 0

    adapter._active_processes["job-term"] = mock_proc
    await adapter.terminate("job-term", grace_period_seconds=1)

    mock_proc.terminate.assert_called_once()
