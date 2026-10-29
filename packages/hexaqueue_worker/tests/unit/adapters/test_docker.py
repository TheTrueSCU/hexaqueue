"""Unit tests for DockerExecutionRuntimeAdapter (Issue #100)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.domain.container import ContainerMount, ContainerSpec
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.storage import VolumeAllocation
from hexaqueue_worker.adapters.docker import DockerExecutionRuntimeAdapter
from hexaqueue_worker.domain.container import DockerConfig


def test_docker_build_command_defaults() -> None:
    """Verify default command construction for standard job."""
    adapter = DockerExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-01",
        run_id="run-1",
        name="test-job",
        command="echo hello",
    )
    cmd = adapter.build_command(job)
    cmd_str = " ".join(cmd)
    has_run = "docker run --rm" in cmd_str
    assert has_run is True
    has_name = "--name hq-j-01" in cmd_str
    assert has_name is True
    has_net = "--net none" in cmd_str
    assert has_net is True
    has_workdir = "-w /workspace" in cmd_str
    assert has_workdir is True
    has_cmd = "sh -c echo hello" in cmd_str
    assert has_cmd is True


def test_docker_build_command_windows_container() -> None:
    """Verify Windows container isolation, working directory, and shell formatting."""
    adapter = DockerExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-win",
        run_id="run-1",
        name="win-job",
        command="dir",
        container=ContainerSpec(
            image="mcr.microsoft.com/windows/servercore:ltsc2022",
            isolation="process",
            workdir="C:\\app",
        ),
    )
    cmd = adapter.build_command(job)
    cmd_str = " ".join(cmd)
    has_isolation = "--isolation process" in cmd_str
    assert has_isolation is True
    has_workdir = "-w C:\\app" in cmd_str
    assert has_workdir is True
    has_cmd = "cmd.exe /c dir" in cmd_str
    assert has_cmd is True
    assert "--read-only" not in cmd_str
    assert "--security-opt" not in cmd_str


def test_docker_build_command_with_host_and_user() -> None:
    """Verify docker daemon socket URI and user flags."""
    config = DockerConfig(
        host="unix:///var/run/docker.sock",
        user="1000:1000",
        seccomp_profile="default",
    )
    adapter = DockerExecutionRuntimeAdapter(config=config)
    job = JobSpec(
        id="j-socket",
        run_id="run-1",
        name="socket-job",
        command="whoami",
    )
    cmd = adapter.build_command(job)
    cmd_str = " ".join(cmd)
    has_host = "-H unix:///var/run/docker.sock" in cmd_str
    assert has_host is True
    has_user = "--user 1000:1000" in cmd_str
    assert has_user is True
    has_seccomp = "--security-opt seccomp=default" in cmd_str
    assert has_seccomp is True


def test_docker_build_command_with_resources_and_gpu() -> None:
    """Verify resource slicing flags and GPU device attachment."""
    adapter = DockerExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-gpu",
        run_id="run-1",
        name="gpu-job",
        command="nvidia-smi",
        resources=ResourceRequirements(cpus=4, ram_mb=2048, gpus=1),
        container=ContainerSpec(image="pytorch/pytorch:latest", gpu_enabled=True),
    )
    cmd = adapter.build_command(job)
    cmd_str = " ".join(cmd)
    has_cpus = "--cpus 4" in cmd_str
    assert has_cpus is True
    has_mem = "-m 2048m" in cmd_str
    assert has_mem is True
    has_gpu = "--gpus all" in cmd_str
    assert has_gpu is True
    has_img = "pytorch/pytorch:latest" in cmd
    assert has_img is True


def test_docker_build_command_with_scratch_and_mounts(tmp_path: Path) -> None:
    """Verify scratch volume mounting and read-only extra volume mounts."""
    adapter = DockerExecutionRuntimeAdapter()
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
                    source="/host/data", target="/container/data", read_only=True
                )
            ],
        ),
    )
    cmd = adapter.build_command(job, scratch_volume=scratch)
    cmd_str = " ".join(cmd)
    expected_scratch = f"-v {tmp_path / 'scratch'}:/workspace"
    has_scratch = expected_scratch in cmd_str
    assert has_scratch is True
    has_extra = "-v /host/data:/container/data:ro" in cmd_str
    assert has_extra is True
    has_ro = "--read-only" in cmd_str
    assert has_ro is True
    has_priv = "--privileged" in cmd_str
    assert has_priv is True


def test_docker_build_command_with_entrypoint_and_env() -> None:
    """Verify entrypoint overrides, custom args, and environment variable sorting."""
    adapter = DockerExecutionRuntimeAdapter()
    job = JobSpec(
        id="j-entry",
        run_id="run-1",
        name="entry-job",
        command="placeholder",
        args=["arg1", "arg2"],
        env={"B_KEY": "val_b", "A_KEY": "val_a"},
        container=ContainerSpec(
            image="python:3.12-slim",
            entrypoint=["python", "-m"],
            extra_args=["--cap-add=SYS_PTRACE"],
        ),
    )
    cmd = adapter.build_command(job, environment={"EXTRA_KEY": "extra"})
    cmd_str = " ".join(cmd)
    has_a = "-e A_KEY=val_a" in cmd_str
    assert has_a is True
    has_b = "-e B_KEY=val_b" in cmd_str
    assert has_b is True
    has_extra = "-e EXTRA_KEY=extra" in cmd_str
    assert has_extra is True
    has_cap = "--cap-add=SYS_PTRACE" in cmd_str
    assert has_cap is True
    has_entry = "python -m arg1 arg2" in cmd_str
    assert has_entry is True


@pytest.mark.asyncio
async def test_docker_execute_success() -> None:
    """Verify successful container execution maps to COMPLETED outcome."""
    log_port = InMemoryLogStreamAdapter()
    adapter = DockerExecutionRuntimeAdapter(log_port=log_port)
    job = JobSpec(id="j-ok", run_id="r-1", name="ok-task", command="echo success")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"completed successfully\n", b""))
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
    content = logs[0].content
    assert content == "completed successfully\n"


@pytest.mark.asyncio
async def test_docker_execute_failure() -> None:
    """Verify non-zero container exit code maps to FAILED outcome."""
    log_port = InMemoryLogStreamAdapter()
    adapter = DockerExecutionRuntimeAdapter(log_port=log_port)
    job = JobSpec(id="j-err", run_id="r-1", name="err-task", command="exit 2")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"fatal: out of memory\n"))
    mock_proc.returncode = 2

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.execute(job)

    code = result.exit_code
    assert code == 2
    outcome = result.outcome
    assert outcome == TerminalOutcome.FAILED
    err_msg = result.error_message
    assert err_msg == "fatal: out of memory"


@pytest.mark.asyncio
async def test_docker_execute_timeout() -> None:
    """Verify container timeout maps to TIMED_OUT and invokes terminate."""
    adapter = DockerExecutionRuntimeAdapter()
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
    mock_proc.pid = 9999

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch.object(adapter, "terminate", new_callable=AsyncMock) as mock_terminate,
    ):
        result = await adapter.execute(job)

    code = result.exit_code
    assert code == 124
    outcome = result.outcome
    assert outcome == TerminalOutcome.TIMED_OUT
    term_called = mock_terminate.called
    assert term_called is True


@pytest.mark.asyncio
async def test_docker_execute_exception() -> None:
    """Verify unexpected subprocess exceptions map cleanly to FAILED outcome."""
    adapter = DockerExecutionRuntimeAdapter()
    job = JobSpec(id="j-exc", run_id="r-1", name="exc-task", command="test")

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("docker executable not found"),
    ):
        result = await adapter.execute(job)

    code = result.exit_code
    assert code == 1
    outcome = result.outcome
    assert outcome == TerminalOutcome.FAILED
    err_msg = result.error_message
    assert "docker executable not found" in str(err_msg)


@pytest.mark.asyncio
async def test_docker_terminate_clean_stop() -> None:
    """Verify terminate issues docker stop and waits for clean exit."""
    adapter = DockerExecutionRuntimeAdapter()
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.pid = 1234
    adapter._active_processes["j-term"] = mock_proc

    mock_stop_proc = MagicMock()
    fut = asyncio.Future()
    fut.set_result(0)
    mock_stop_proc.wait = MagicMock(return_value=fut)

    with patch("asyncio.create_subprocess_exec", return_value=mock_stop_proc):
        await adapter.terminate("j-term", grace_period_seconds=5)

    assert mock_proc.kill.called is False


@pytest.mark.asyncio
async def test_docker_terminate_fallback_kill() -> None:
    """Verify terminate issues killpg when container process does not stop in time."""
    adapter = DockerExecutionRuntimeAdapter()
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.pid = 5678
    mock_proc.wait = AsyncMock()
    adapter._active_processes["j-stubborn"] = mock_proc

    mock_stop_proc = MagicMock()
    fut = asyncio.Future()
    fut.set_result(0)
    mock_stop_proc.wait = MagicMock(return_value=fut)

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_stop_proc),
        patch("os.getpgid", return_value=5678),
        patch("os.getpgrp", return_value=1234),
        patch("os.killpg") as mock_killpg,
    ):
        await adapter.terminate("j-stubborn", grace_period_seconds=1)

    assert mock_killpg.called is True
