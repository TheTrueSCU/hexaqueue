"""Unit tests for Linux Cgroups v2 compute execution runtime adapter."""

import asyncio
import signal
import sys
import tempfile
from pathlib import Path

import pytest

from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.storage import VolumeAllocation
from hexaqueue_worker.adapters.cgroups import CgroupsV2ProcessAdapter
from hexaqueue_worker.domain.cgroups import CgroupConfig, CgroupLimits


@pytest.mark.asyncio
async def test_cgroups_adapter_execute_success() -> None:
    """Verify standard command execution, exit code 0, and cgroup teardown."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = CgroupConfig(cgroup_fs_root=tmp_dir, cgroup_name_prefix="test-")
        log_port = InMemoryLogStreamAdapter()
        adapter = CgroupsV2ProcessAdapter(cgroup_config=config, log_port=log_port)

        # Pre-create procs file to test _attach_pid_to_cgroup
        job_dir = Path(tmp_dir) / "test-job-cgroup-1"
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "cgroup.procs").write_text("")

        scratch = VolumeAllocation(
            volume_id="vol-1",
            mount_path=tmp_dir,
            size_mb=100,
        )

        job = JobSpec(
            id="job-cgroup-1",
            run_id="run-1",
            name="cgroup-echo",
            command=f"{sys.executable} -c \"print('cgroup v2 running')\"",
            resources=ResourceRequirements(cpus=2, ram_mb=512, walltime_seconds=10),
        )

        result = await adapter.execute(job, scratch_volume=scratch)

        exit_code = result.exit_code
        outcome = result.outcome
        assert exit_code == 0
        assert outcome == TerminalOutcome.COMPLETED

        logs = [chunk async for chunk in log_port.stream_logs(job.id)]
        log_count = len(logs)
        assert log_count >= 1
        has_content = "cgroup v2 running" in logs[0].content
        assert has_content is True

        # Verify cgroup dir was torn down
        exists = job_dir.exists()
        assert exists is False


@pytest.mark.asyncio
async def test_cgroups_adapter_execute_failure() -> None:
    """Verify non-zero exit code capture and stderr propagation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = CgroupConfig(cgroup_fs_root=tmp_dir)
        log_port = InMemoryLogStreamAdapter()
        adapter = CgroupsV2ProcessAdapter(cgroup_config=config, log_port=log_port)

        job = JobSpec(
            id="job-cgroup-fail",
            run_id="run-1",
            name="fail-job",
            command=f"{sys.executable} -c \"import sys; sys.stderr.write('cgroup err\\n'); sys.exit(42)\"",
            resources=ResourceRequirements(walltime_seconds=10),
        )

        result = await adapter.execute(job)

        exit_code = result.exit_code
        outcome = result.outcome
        err_msg = result.error_message

        assert exit_code == 42
        assert outcome == TerminalOutcome.FAILED
        assert err_msg is not None
        assert "cgroup err" in err_msg

        logs = [chunk async for chunk in log_port.stream_logs(job.id)]
        log_count = len(logs)
        assert log_count >= 1


@pytest.mark.asyncio
async def test_cgroups_adapter_walltime_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify execution abort upon walltime expiration."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = CgroupConfig(cgroup_fs_root=tmp_dir)
        adapter = CgroupsV2ProcessAdapter(cgroup_config=config, grace_period_seconds=1)

        job = JobSpec(
            id="job-cgroup-timeout",
            run_id="run-1",
            name="sleep-job",
            command=f'{sys.executable} -c "import time; time.sleep(10)"',
            resources=ResourceRequirements(walltime_seconds=10),
        )

        # Monkeypatch asyncio.wait_for to raise TimeoutError immediately
        async def mock_wait_for(fut, timeout):
            fut.close()
            raise TimeoutError

        monkeypatch.setattr(asyncio, "wait_for", mock_wait_for)

        result = await adapter.execute(job)
        exit_code = result.exit_code
        outcome = result.outcome
        assert exit_code == 124
        assert outcome == TerminalOutcome.FAILED


@pytest.mark.asyncio
async def test_cgroups_adapter_terminate_active_process() -> None:
    """Verify terminate stops an active running process group."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = CgroupConfig(cgroup_fs_root=tmp_dir)
        adapter = CgroupsV2ProcessAdapter(cgroup_config=config, grace_period_seconds=1)

        proc = await asyncio.create_subprocess_shell(
            f'{sys.executable} -c "import time; time.sleep(10)"',
            start_new_session=True,
        )
        adapter._active_processes["job-term"] = proc
        cgroup_path = Path(tmp_dir) / "hq-job-term"
        cgroup_path.mkdir(parents=True, exist_ok=True)
        adapter._cgroup_dirs["job-term"] = cgroup_path

        await adapter.terminate("job-term", grace_period_seconds=1)

        is_done = proc.returncode is not None
        assert is_done is True
        cgroup_exists = cgroup_path.exists()
        assert cgroup_exists is False


@pytest.mark.asyncio
async def test_cgroups_adapter_environment_and_cuda_injection() -> None:
    """Verify environment variable injection into subprocess."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = CgroupConfig(cgroup_fs_root=tmp_dir)
        adapter = CgroupsV2ProcessAdapter(cgroup_config=config)

        job = JobSpec(
            id="job-cgroup-env",
            run_id="run-1",
            name="env-job",
            command=f"{sys.executable} -c \"import os; assert os.environ.get('CUDA_VISIBLE_DEVICES') == '0,1'\"",
            resources=ResourceRequirements(walltime_seconds=10),
        )

        result = await adapter.execute(job, environment={"CUDA_VISIBLE_DEVICES": "0,1"})
        exit_code = result.exit_code
        outcome = result.outcome
        assert exit_code == 0
        assert outcome == TerminalOutcome.COMPLETED


@pytest.mark.asyncio
async def test_cgroups_adapter_setup_failure() -> None:
    """Verify execution succeeds even if cgroup setup fails gracefully."""
    # Point to an unwritable / non-existent root that cannot be created
    config = CgroupConfig(cgroup_fs_root="/proc/sys/fs/uncreatable/cgroup")
    adapter = CgroupsV2ProcessAdapter(cgroup_config=config)

    job = JobSpec(
        id="job-cgroup-nofs",
        run_id="run-1",
        name="nofs-job",
        command=f"{sys.executable} -c \"print('ok')\"",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    result = await adapter.execute(job)
    exit_code = result.exit_code
    outcome = result.outcome
    assert exit_code == 0
    assert outcome == TerminalOutcome.COMPLETED


@pytest.mark.asyncio
async def test_cgroups_adapter_helper_null_cases() -> None:
    """Verify helpers handle None gracefully without exceptions."""
    adapter = CgroupsV2ProcessAdapter()
    adapter._attach_pid_to_cgroup(None, 123)
    adapter._teardown_cgroup(None)

    from unittest.mock import MagicMock

    mock_proc = MagicMock()
    mock_proc.pid = None
    await adapter._kill_process_group(mock_proc, grace_period_seconds=1)


def test_cgroups_adapter_setup_exist_ok(tmp_path: Path) -> None:
    """Verify _setup_cgroup succeeds even if directory already exists."""
    config = CgroupConfig(cgroup_fs_root=str(tmp_path))
    adapter = CgroupsV2ProcessAdapter(cgroup_config=config)
    limits = CgroupLimits.from_resources(cpus=1, ram_mb=512)

    # First setup creates the dir
    p1 = adapter._setup_cgroup("j-exist", limits)
    assert p1 is not None
    assert p1.exists() is True

    # Second setup with same ID should not raise FileExistsError (exist_ok=True)
    p2 = adapter._setup_cgroup("j-exist", limits)
    assert p2 is not None
    assert p2 == p1


@pytest.mark.asyncio
async def test_cgroups_adapter_kill_process_group_guards() -> None:
    """Verify process termination guards against self-termination and escalates to SIGKILL."""
    from unittest.mock import MagicMock, patch

    adapter = CgroupsV2ProcessAdapter()

    # 1. Distinct PGID -> uses os.killpg
    proc_external = MagicMock()
    proc_external.pid = 9999
    proc_external.returncode = 0

    with (
        patch("os.getpgid", return_value=9999),
        patch("os.getpgrp", return_value=1111),
        patch("os.killpg") as mock_killpg,
    ):
        await adapter._kill_process_group(proc_external, grace_period_seconds=0)
        assert mock_killpg.called is True
        assert mock_killpg.call_args_list[0][0] == (9999, signal.SIGTERM)

    # 2. Same PGID as test runner -> uses proc.terminate(), NEVER os.killpg
    proc_own = MagicMock()
    proc_own.pid = 2222
    proc_own.returncode = 0
    proc_own.terminate = MagicMock()

    with (
        patch("os.getpgid", return_value=1111),
        patch("os.getpgrp", return_value=1111),
        patch("os.killpg") as mock_killpg_own,
    ):
        await adapter._kill_process_group(proc_own, grace_period_seconds=0)
        assert mock_killpg_own.called is False
        assert proc_own.terminate.called is True

    # 3. Grace period sleep and SIGKILL escalation when returncode remains None
    proc_stubborn = MagicMock()
    proc_stubborn.pid = 8888
    proc_stubborn.returncode = None
    proc_stubborn.kill = MagicMock()

    sleep_calls: list[float] = []

    async def mock_sleep(secs):
        sleep_calls.append(secs)

    with (
        patch("os.getpgid", return_value=8888),
        patch("os.getpgrp", return_value=1111),
        patch("os.killpg") as mock_killpg_stubborn,
        patch("asyncio.sleep", side_effect=mock_sleep),
    ):
        await adapter._kill_process_group(proc_stubborn, grace_period_seconds=0.2)
        # 0.2 * 10 = 2 sleep cycles
        assert len(sleep_calls) == 2
        assert mock_killpg_stubborn.call_count == 2
        assert mock_killpg_stubborn.call_args_list[1][0] == (8888, signal.SIGKILL)


@pytest.mark.asyncio
async def test_cgroups_adapter_error_message_and_stderr() -> None:
    """Verify error_message is only populated on non-zero exit code when stderr is non-empty."""
    from unittest.mock import AsyncMock, MagicMock, patch

    adapter = CgroupsV2ProcessAdapter()
    job = JobSpec(id="j-err", run_id="r1", name="j-err", command="true")

    # 1. Exit code 1 with stderr -> error_message set
    proc_fail = MagicMock()
    proc_fail.pid = 1234
    proc_fail.returncode = 1
    proc_fail.communicate = AsyncMock(return_value=(b"", b"failure reason"))

    with (
        patch("asyncio.create_subprocess_shell", return_value=proc_fail),
        patch.object(adapter, "_setup_cgroup", return_value=None),
        patch.object(adapter, "_teardown_cgroup"),
    ):
        res_fail = await adapter.execute(job)
        assert res_fail.exit_code == 1
        assert res_fail.outcome == TerminalOutcome.FAILED
        assert res_fail.error_message == "failure reason"

    # 2. Exit code 0 with stderr -> error_message is None, outcome is COMPLETED
    proc_ok_stderr = MagicMock()
    proc_ok_stderr.pid = 1234
    proc_ok_stderr.returncode = 0
    proc_ok_stderr.communicate = AsyncMock(return_value=(b"stdout", b"warning banner"))

    with (
        patch("asyncio.create_subprocess_shell", return_value=proc_ok_stderr),
        patch.object(adapter, "_setup_cgroup", return_value=None),
        patch.object(adapter, "_teardown_cgroup"),
    ):
        res_ok = await adapter.execute(job)
        assert res_ok.exit_code == 0
        assert res_ok.outcome == TerminalOutcome.COMPLETED
        assert res_ok.error_message is None


def test_cgroups_adapter_setup_nested_parents(tmp_path: Path) -> None:
    """Verify _setup_cgroup creates nested parent directories when parents=True."""
    nested_root = tmp_path / "deep" / "nested" / "cgroups"
    config = CgroupConfig(cgroup_fs_root=str(nested_root))
    adapter = CgroupsV2ProcessAdapter(cgroup_config=config)
    limits = CgroupLimits.from_resources(cpus=1, ram_mb=512)
    path = adapter._setup_cgroup("j-nested", limits)
    assert path is not None
    assert path.exists() is True


@pytest.mark.asyncio
async def test_cgroups_adapter_start_new_session_flag() -> None:
    """Verify create_subprocess_shell is invoked with start_new_session=True."""
    from unittest.mock import AsyncMock, patch

    adapter = CgroupsV2ProcessAdapter()
    job = JobSpec(id="j-session", run_id="r1", name="j-session", command="true")
    proc = AsyncMock()
    proc.pid = 1234
    proc.returncode = 0
    proc.communicate.return_value = (b"", b"")
    with patch("asyncio.create_subprocess_shell", return_value=proc) as mock_shell:
        await adapter.execute(job)
        assert mock_shell.call_args.kwargs.get("start_new_session") is True
