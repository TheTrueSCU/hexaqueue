"""Unit tests for Linux Cgroups v2 compute execution runtime adapter."""

import asyncio
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
from hexaqueue_worker.domain.cgroups import CgroupConfig


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
