"""Unit tests for ApptainerExecutionRuntimeAdapter (Issue #30)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.domain.container import ContainerMount, ContainerSpec
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.storage import VolumeAllocation
from hexaqueue_worker.adapters.apptainer import ApptainerExecutionRuntimeAdapter
from hexaqueue_worker.domain.container import ApptainerConfig


def test_apptainer_build_command_defaults() -> None:
    """Verify default command construction for standard job."""
    adapter = ApptainerExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-app-01",
        run_id="run-1",
        name="test-app-job",
        command="hostname",
    )
    cmd = adapter.build_command(job)
    cmd_str = " ".join(cmd)
    has_exec = "apptainer exec" in cmd_str
    assert has_exec is True
    has_contain = "--containall" in cmd_str
    assert has_contain is True
    has_clean = "--cleanenv" in cmd_str
    assert has_clean is True
    has_pwd = "--pwd /workspace" in cmd_str
    assert has_pwd is True
    has_image = "docker://alpine:latest" in cmd_str
    assert has_image is True


def test_apptainer_build_command_with_gpu() -> None:
    """Verify GPU acceleration flags."""
    adapter = ApptainerExecutionRuntimeAdapter(
        config=ApptainerConfig(nv_gpu=True, rocm_gpu=True)
    )
    job = JobSpec(
        id="j-gpu",
        run_id="run-1",
        name="gpu-job",
        command="nvidia-smi",
        resources=ResourceRequirements(gpus=1),
        container=ContainerSpec(
            image="/shared/images/cuda.sif",
            gpu_enabled=True,
        ),
    )
    cmd = adapter.build_command(job)
    cmd_str = " ".join(cmd)
    has_nv = "--nv" in cmd_str
    assert has_nv is True
    has_rocm = "--rocm" in cmd_str
    assert has_rocm is True
    has_sif = "/shared/images/cuda.sif" in cmd_str
    assert has_sif is True


def test_apptainer_build_command_scratch_and_mounts(tmp_path: Path) -> None:
    """Verify scratch volume binding and extra directory mounts."""
    adapter = ApptainerExecutionRuntimeAdapter()
    scratch = VolumeAllocation(
        volume_id="vol-app-01",
        mount_path=str(tmp_path / "scratch"),
        size_mb=200,
    )
    job = JobSpec(
        id="j-app-scratch",
        run_id="run-1",
        name="app-scratch-job",
        command="echo ok",
        container=ContainerSpec(
            image="docker://python:3.13-slim",
            mounts=[
                ContainerMount(
                    source="/host/dataset", target="/mnt/data", read_only=True
                )
            ],
            extra_args=["--fakeroot"],
        ),
    )
    cmd = adapter.build_command(job, scratch_volume=scratch)
    cmd_str = " ".join(cmd)
    expected_scratch = f"--bind {tmp_path / 'scratch'}:/workspace"
    has_scratch = expected_scratch in cmd_str
    assert has_scratch is True
    has_dataset = "--bind /host/dataset:/mnt/data:ro" in cmd_str
    assert has_dataset is True
    has_fakeroot = "--fakeroot" in cmd_str
    assert has_fakeroot is True


@pytest.mark.asyncio
async def test_apptainer_execute_success() -> None:
    """Verify successful execution maps to COMPLETED outcome."""
    log_port = InMemoryLogStreamAdapter()
    adapter = ApptainerExecutionRuntimeAdapter(log_port=log_port)
    job = JobSpec(id="j-app-ok", run_id="r-1", name="ok-task", command="true")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"apptainer stdout\n", b""))
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
    assert logged_out == "apptainer stdout\n"


@pytest.mark.asyncio
async def test_apptainer_execute_failure() -> None:
    """Verify non-zero exit code maps to FAILED outcome."""
    adapter = ApptainerExecutionRuntimeAdapter()
    job = JobSpec(id="j-app-fail", run_id="r-1", name="fail-task", command="false")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"image not found\n"))
    mock_proc.returncode = 2

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.execute(job)

    code = result.exit_code
    assert code == 2
    outcome = result.outcome
    assert outcome == TerminalOutcome.FAILED
    err = result.error_message
    assert err == "image not found"


@pytest.mark.asyncio
async def test_apptainer_execute_timeout() -> None:
    """Verify walltime timeout maps to TIMED_OUT outcome."""
    adapter = ApptainerExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-app-timeout",
        run_id="r-1",
        name="timeout-task",
        command="sleep 100",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=TimeoutError())
    mock_proc.returncode = None
    mock_proc.pid = 88888

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
async def test_apptainer_terminate() -> None:
    """Verify terminate issues SIGTERM to process group."""
    adapter = ApptainerExecutionRuntimeAdapter()
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.pid = 54321
    mock_proc.wait = AsyncMock(return_value=0)
    adapter._active_processes["j-app-kill"] = mock_proc

    with (
        patch("os.getpgid", return_value=54321),
        patch("os.killpg") as mock_killpg,
    ):
        await adapter.terminate("j-app-kill", grace_period_seconds=5)

    kill_called = mock_killpg.called
    assert kill_called is True


def test_apptainer_build_command_with_entrypoint_and_env() -> None:
    """Verify entrypoint, args, and environment variable formatting."""
    adapter = ApptainerExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-app-entry",
        run_id="run-1",
        name="entry-job",
        command="fallback",
        args=["arg1", "--flag"],
        env={"VAR_A": "val_a"},
        container=ContainerSpec(
            image="custom.sif",
            entrypoint=["python", "-m", "worker"],
        ),
    )
    cmd = adapter.build_command(job, environment={"VAR_B": "val_b"})
    cmd_str = " ".join(cmd)
    has_env_a = "--env VAR_A=val_a" in cmd_str
    assert has_env_a is True
    has_env_b = "--env VAR_B=val_b" in cmd_str
    assert has_env_b is True
    has_entry = "python -m worker arg1 --flag" in cmd_str
    assert has_entry is True


@pytest.mark.asyncio
async def test_apptainer_execute_with_stderr_logging() -> None:
    """Verify stderr log recording when process writes to stderr."""
    log_port = InMemoryLogStreamAdapter()
    adapter = ApptainerExecutionRuntimeAdapter(log_port=log_port)
    job = JobSpec(id="j-app-stderr", run_id="r-1", name="stderr-task", command="cmd")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"out\n", b"apptainer err\n"))
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
    assert err_chunk.content == "apptainer err\n"


@pytest.mark.asyncio
async def test_apptainer_execute_exception() -> None:
    """Verify exception during process creation results in FAILED outcome."""
    adapter = ApptainerExecutionRuntimeAdapter()
    job = JobSpec(id="j-app-exc", run_id="r-1", name="exc-task", command="cmd")

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
async def test_apptainer_terminate_missing_job() -> None:
    """Verify terminate returns gracefully when job is not running."""
    adapter = ApptainerExecutionRuntimeAdapter()
    res = await adapter.terminate("non-existent-job")
    assert res is None


@pytest.mark.asyncio
async def test_apptainer_terminate_sigkill_timeout() -> None:
    """Verify SIGKILL is sent when SIGTERM wait times out."""
    adapter = ApptainerExecutionRuntimeAdapter()
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.pid = 99123
    mock_proc.wait = AsyncMock(side_effect=[TimeoutError(), 0])
    adapter._active_processes["j-app-timeout-term"] = mock_proc

    with (
        patch("os.getpgid", return_value=99123),
        patch("os.killpg") as mock_killpg,
    ):
        await adapter.terminate("j-app-timeout-term", grace_period_seconds=1)

    calls = mock_killpg.call_args_list
    assert len(calls) >= 2
