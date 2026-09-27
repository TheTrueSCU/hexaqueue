"""Unit tests for Native Deference execution runtime adapter."""

import asyncio
import sys
import tempfile

import pytest

from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.storage import VolumeAllocation
from hexaqueue_worker.adapters.deference import NativeDeferenceRuntimeAdapter


@pytest.mark.asyncio
async def test_native_deference_execute_success() -> None:
    """Verify standard execution through native deference adapter."""
    log_port = InMemoryLogStreamAdapter()
    adapter = NativeDeferenceRuntimeAdapter(log_port=log_port)

    with tempfile.TemporaryDirectory() as tmp_dir:
        scratch = VolumeAllocation(
            volume_id="vol-def-1",
            mount_path=tmp_dir,
            size_mb=50,
        )

        job = JobSpec(
            id="job-def-1",
            run_id="run-1",
            name="echo-def",
            command=f"{sys.executable} -c \"print('deference executed')\"",
            resources=ResourceRequirements(walltime_seconds=10),
        )

        result = await adapter.execute(job, scratch_volume=scratch)

        exit_code = result.exit_code
        outcome = result.outcome
        assert exit_code == 0
        assert outcome == TerminalOutcome.COMPLETED

        logs = [chunk async for chunk in log_port.stream_logs(job.id)]
        log_count = len(logs)
        assert log_count >= 1
        has_text = "deference executed" in logs[0].content
        assert has_text is True


@pytest.mark.asyncio
async def test_native_deference_execute_failure() -> None:
    """Verify non-zero return code and stderr capture."""
    log_port = InMemoryLogStreamAdapter()
    adapter = NativeDeferenceRuntimeAdapter(log_port=log_port)

    job = JobSpec(
        id="job-def-fail",
        run_id="run-1",
        name="fail-def",
        command=f"{sys.executable} -c \"import sys; sys.stderr.write('def err\\n'); sys.exit(9)\"",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    result = await adapter.execute(job)

    exit_code = result.exit_code
    outcome = result.outcome
    err_msg = result.error_message

    assert exit_code == 9
    assert outcome == TerminalOutcome.FAILED
    assert err_msg is not None
    assert "def err" in err_msg

    logs = [chunk async for chunk in log_port.stream_logs(job.id)]
    log_count = len(logs)
    assert log_count >= 1


@pytest.mark.asyncio
async def test_native_deference_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify walltime expiration abort in native deference adapter."""
    adapter = NativeDeferenceRuntimeAdapter()

    job = JobSpec(
        id="job-def-timeout",
        run_id="run-1",
        name="sleep-def",
        command=f'{sys.executable} -c "import time; time.sleep(10)"',
        resources=ResourceRequirements(walltime_seconds=10),
    )

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
async def test_native_deference_terminate_active() -> None:
    """Verify termination of active running subprocess."""
    adapter = NativeDeferenceRuntimeAdapter()

    proc = await asyncio.create_subprocess_shell(
        f'{sys.executable} -c "import time; time.sleep(10)"'
    )
    adapter._active_processes["job-def-active"] = proc

    await adapter.terminate("job-def-active", grace_period_seconds=1)
    is_done = proc.returncode is not None
    assert is_done is True

    # Test terminate on non-running job safely completes
    await adapter.terminate("non-existent-job")


@pytest.mark.asyncio
async def test_native_deference_error_message_and_stderr() -> None:
    """Verify error_message is only populated on non-zero exit code when stderr is non-empty."""
    from unittest.mock import AsyncMock, MagicMock, patch

    adapter = NativeDeferenceRuntimeAdapter()
    job = JobSpec(id="j-err", run_id="r1", name="j-err", command="true")

    # 1. Exit code 1 with stderr -> error_message set
    proc_fail = MagicMock()
    proc_fail.pid = 1234
    proc_fail.returncode = 1
    proc_fail.communicate = AsyncMock(return_value=(b"", b"def failure reason"))

    with patch("asyncio.create_subprocess_shell", return_value=proc_fail):
        res_fail = await adapter.execute(job)
        assert res_fail.exit_code == 1
        assert res_fail.outcome == TerminalOutcome.FAILED
        assert res_fail.error_message == "def failure reason"

    # 2. Exit code 0 with stderr -> error_message is None, outcome is COMPLETED
    proc_ok_stderr = MagicMock()
    proc_ok_stderr.pid = 1234
    proc_ok_stderr.returncode = 0
    proc_ok_stderr.communicate = AsyncMock(return_value=(b"stdout", b"warning banner"))

    with patch("asyncio.create_subprocess_shell", return_value=proc_ok_stderr):
        res_ok = await adapter.execute(job)
        assert res_ok.exit_code == 0
        assert res_ok.outcome == TerminalOutcome.COMPLETED
        assert res_ok.error_message is None
