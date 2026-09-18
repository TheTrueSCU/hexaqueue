"""Unit tests for PodmanExecutionRuntimeAdapter (Issue #30)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.domain.container import ContainerMount, ContainerSpec
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.storage import VolumeAllocation
from hexaqueue_worker.adapters.podman import PodmanExecutionRuntimeAdapter


def test_podman_build_command_defaults() -> None:
    """Verify default command construction for standard job."""
    adapter = PodmanExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-01",
        run_id="run-1",
        name="test-job",
        command="echo hello",
    )
    cmd = adapter.build_command(job)
    cmd_str = " ".join(cmd)
    has_run = "podman run --rm" in cmd_str
    assert has_run is True
    has_name = "--name hq-j-01" in cmd_str
    assert has_name is True
    has_userns = "--userns keep-id" in cmd_str
    assert has_userns is True
    has_net = "--net none" in cmd_str
    assert has_net is True
    has_cmd = "sh -c echo hello" in cmd_str
    assert has_cmd is True


def test_podman_build_command_with_cgroups_and_gpu() -> None:
    """Verify resource slicing flags and GPU attachment."""
    adapter = PodmanExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-gpu",
        run_id="run-1",
        name="gpu-job",
        command="nvidia-smi",
        resources=ResourceRequirements(cpus=4, ram_mb=2048, gpus=1),
        container=ContainerSpec(image="pytorch/pytorch:latest", gpu_enabled=True),
    )
    cmd = adapter.build_command(job)
    has_cpus = "--cpus 4" in " ".join(cmd)
    assert has_cpus is True
    has_mem = "-m 2048m" in " ".join(cmd)
    assert has_mem is True
    has_gpu = "--gpus all" in " ".join(cmd)
    assert has_gpu is True
    has_img = "pytorch/pytorch:latest" in cmd
    assert has_img is True


def test_podman_build_command_with_scratch_and_mounts(tmp_path: Path) -> None:
    """Verify scratch volume mounting with SELinux relabeling and extra mounts."""
    adapter = PodmanExecutionRuntimeAdapter()
    scratch = VolumeAllocation(
        volume_id="vol-01",
        mount_path=str(tmp_path / "scratch"),
        size_mb=100,
    )
    job = JobSpec(
        id="j-scratch",
        run_id="run-1",
        name="scratch-job",
        command="ls -la",
        container=ContainerSpec(
            image="alpine:latest",
            read_only_rootfs=True,
            privileged=True,
            mounts=[
                ContainerMount(
                    source="/host/ref", target="/container/ref", read_only=True
                )
            ],
        ),
    )
    cmd = adapter.build_command(job, scratch_volume=scratch)
    cmd_str = " ".join(cmd)
    expected_scratch = f"-v {tmp_path / 'scratch'}:/workspace:Z"
    has_scratch = expected_scratch in cmd_str
    assert has_scratch is True
    has_extra_mount = "-v /host/ref:/container/ref:ro" in cmd_str
    assert has_extra_mount is True
    has_ro = "--read-only" in cmd_str
    assert has_ro is True
    has_priv = "--privileged" in cmd_str
    assert has_priv is True


@pytest.mark.asyncio
async def test_podman_execute_success() -> None:
    """Verify successful execution maps to COMPLETED outcome."""
    log_port = InMemoryLogStreamAdapter()
    adapter = PodmanExecutionRuntimeAdapter(log_port=log_port)
    job = JobSpec(id="j-ok", run_id="r-1", name="ok-task", command="true")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"output message\n", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.execute(job)

    code = result.exit_code
    assert code == 0
    outcome = result.outcome
    assert outcome == TerminalOutcome.COMPLETED
    logs = [chunk async for chunk in log_port.stream_logs(job.id)]
    log_len = len(logs)
    assert log_len == 1
    logged_out = logs[0].content
    assert logged_out == "output message\n"


@pytest.mark.asyncio
async def test_podman_execute_failure() -> None:
    """Verify non-zero exit code maps to FAILED outcome."""
    adapter = PodmanExecutionRuntimeAdapter()
    job = JobSpec(id="j-fail", run_id="r-1", name="fail-task", command="false")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"permission denied\n"))
    mock_proc.returncode = 127

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.execute(job)

    code = result.exit_code
    assert code == 127
    outcome = result.outcome
    assert outcome == TerminalOutcome.FAILED
    err = result.error_message
    assert err == "permission denied"


@pytest.mark.asyncio
async def test_podman_execute_timeout() -> None:
    """Verify walltime timeout maps to TIMED_OUT outcome."""
    adapter = PodmanExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-timeout",
        run_id="r-1",
        name="timeout-task",
        command="sleep 100",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=TimeoutError())
    mock_proc.returncode = None
    mock_proc.pid = 99999

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch.object(adapter, "terminate", new_callable=AsyncMock) as mock_term,
    ):
        result = await adapter.execute(job)

    term_called = mock_term.called
    assert term_called is True
    outcome = result.outcome
    assert outcome == TerminalOutcome.TIMED_OUT
    code = result.exit_code
    assert code == 124


@pytest.mark.asyncio
async def test_podman_terminate() -> None:
    """Verify terminate issues podman stop command."""
    adapter = PodmanExecutionRuntimeAdapter()
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.pid = 12345
    adapter._active_processes["j-kill"] = mock_proc

    mock_stop_proc = MagicMock()
    mock_stop_proc.wait = AsyncMock(return_value=0)

    with patch(
        "asyncio.create_subprocess_exec", return_value=mock_stop_proc
    ) as mock_exec:
        await adapter.terminate("j-kill", grace_period_seconds=5)

    exec_called = mock_exec.called
    assert exec_called is True
    call_args = mock_exec.call_args[0]
    has_stop = "stop" in call_args
    assert has_stop is True
    has_timeout = "-t" in call_args and "5" in call_args
    assert has_timeout is True


def test_podman_build_command_with_entrypoint_and_env() -> None:
    """Verify entrypoint, args, and environment variable formatting."""
    adapter = PodmanExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-entry",
        run_id="run-1",
        name="entry-job",
        command="fallback",
        args=["arg1", "--flag"],
        env={"VAR_A": "val_a"},
        container=ContainerSpec(
            image="custom:latest",
            entrypoint=["python", "-m", "worker"],
        ),
    )
    cmd = adapter.build_command(job, environment={"VAR_B": "val_b"})
    cmd_str = " ".join(cmd)
    has_env_a = "-e VAR_A=val_a" in cmd_str
    assert has_env_a is True
    has_env_b = "-e VAR_B=val_b" in cmd_str
    assert has_env_b is True
    has_entry = "python -m worker arg1 --flag" in cmd_str
    assert has_entry is True


@pytest.mark.asyncio
async def test_podman_execute_with_stderr_logging() -> None:
    """Verify stderr log recording when process writes to stderr."""
    log_port = InMemoryLogStreamAdapter()
    adapter = PodmanExecutionRuntimeAdapter(log_port=log_port)
    job = JobSpec(id="j-stderr", run_id="r-1", name="stderr-task", command="cmd")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"out\n", b"err line\n"))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.execute(job)

    code = result.exit_code
    assert code == 0
    logs = [chunk async for chunk in log_port.stream_logs(job.id)]
    log_count = len(logs)
    assert log_count == 2
    err_chunk = logs[1]
    assert err_chunk.stream == "stderr"
    assert err_chunk.content == "err line\n"


@pytest.mark.asyncio
async def test_podman_execute_exception() -> None:
    """Verify exception during process creation results in FAILED outcome."""
    adapter = PodmanExecutionRuntimeAdapter()
    job = JobSpec(id="j-exc", run_id="r-1", name="exc-task", command="cmd")

    with patch(
        "asyncio.create_subprocess_exec", side_effect=RuntimeError("Subprocess failed")
    ):
        result = await adapter.execute(job)

    outcome = result.outcome
    assert outcome == TerminalOutcome.FAILED
    code = result.exit_code
    assert code == 1
    has_err = "Subprocess failed" in (result.error_message or "")
    assert has_err is True


@pytest.mark.asyncio
async def test_podman_terminate_missing_job() -> None:
    """Verify terminate returns gracefully when job is not running."""
    adapter = PodmanExecutionRuntimeAdapter()
    res = await adapter.terminate("non-existent-job")
    assert res is None


@pytest.mark.asyncio
async def test_podman_terminate_fallback_sigkill() -> None:
    """Verify fallback to SIGKILL when container process does not stop cleanly."""
    adapter = PodmanExecutionRuntimeAdapter()
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.pid = 4321
    mock_proc.wait = AsyncMock(return_value=0)
    adapter._active_processes["j-stubborn"] = mock_proc

    mock_stop_proc = MagicMock()
    mock_stop_proc.wait = AsyncMock(return_value=0)

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_stop_proc),
        patch("os.getpgid", return_value=4321),
        patch("os.killpg") as mock_killpg,
    ):
        await adapter.terminate("j-stubborn", grace_period_seconds=1)

    kill_called = mock_killpg.called
    assert kill_called is True
