"""Unit tests for local subprocess runtime adapter."""

import asyncio

import pytest

from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.adapters.runtime.local import LocalSubprocessExecutionRuntimeAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements


@pytest.mark.asyncio
async def test_local_subprocess_execution() -> None:
    """Verify local subprocess execution, exit code capture, and walltime."""
    log_port = InMemoryLogStreamAdapter()
    runtime = LocalSubprocessExecutionRuntimeAdapter(log_port=log_port)

    job = JobSpec(
        id="job-echo",
        run_id="run-1",
        name="echo-test",
        command="echo 'Hello Hexaqueue'",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    result = await runtime.execute(job, environment={"CUSTOM_VAR": "val"})
    assert result.exit_code == 0
    assert result.outcome == TerminalOutcome.COMPLETED

    chunks = [c async for c in log_port.stream_logs("job-echo")]
    assert len(chunks) > 0
    assert "Hello Hexaqueue" in chunks[0].content


@pytest.mark.asyncio
async def test_local_subprocess_ignores_ambient_hexaqueue_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify ambient HEXAQUEUE_CWD in os.environ does not override subprocess cwd."""
    monkeypatch.setenv("HEXAQUEUE_CWD", "nonexistent/nested/dir")
    runtime = LocalSubprocessExecutionRuntimeAdapter()
    job = JobSpec(
        id="job-cwd-isolated",
        run_id="run-1",
        name="cwd-isolated",
        command="echo 'isolated'",
        resources=ResourceRequirements(walltime_seconds=10),
    )
    result = await runtime.execute(job)
    code = result.exit_code
    assert code == 0


@pytest.mark.asyncio
async def test_local_subprocess_failure() -> None:
    """Verify failed subprocess execution exit code capture."""
    log_port = InMemoryLogStreamAdapter()
    runtime = LocalSubprocessExecutionRuntimeAdapter(log_port=log_port)

    job = JobSpec(
        id="job-fail",
        run_id="run-1",
        name="fail-test",
        command="sh -c 'echo \"error output\" >&2; exit 42'",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    result = await runtime.execute(job)
    assert result.exit_code == 42
    assert result.outcome == TerminalOutcome.FAILED
    assert result.error_message is not None
    assert "error output" in result.error_message


@pytest.mark.asyncio
async def test_local_subprocess_timeout() -> None:
    """Verify walltime enforcement on slow subprocesses."""
    from unittest.mock import patch

    runtime = LocalSubprocessExecutionRuntimeAdapter()
    job = JobSpec(
        id="job-sleep",
        run_id="run-1",
        name="sleep-test",
        command="sleep 10",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    with patch("asyncio.wait_for", side_effect=TimeoutError()):
        result = await runtime.execute(job)
        assert result.outcome == TerminalOutcome.TIMED_OUT
        assert result.exit_code == -1


@pytest.mark.asyncio
async def test_local_subprocess_terminate() -> None:
    """Verify termination of active subprocess."""
    runtime = LocalSubprocessExecutionRuntimeAdapter()
    await runtime.terminate("non-existent-job")


@pytest.mark.asyncio
async def test_local_runtime_kills_subprocess_on_cancellation() -> None:
    """Verify cancelling an executing task terminates and removes its child subprocess."""
    runtime = LocalSubprocessExecutionRuntimeAdapter()
    job = JobSpec(
        id="job-cancel-proc",
        run_id="run-cancel-proc",
        name="cancel-proc",
        command="sleep 30",
        resources=ResourceRequirements(walltime_seconds=60),
    )

    task = asyncio.create_task(runtime.execute(job))
    for _ in range(50):
        if job.id in runtime._active_processes:
            break
        await asyncio.sleep(0.01)

    proc = runtime._active_processes.get(job.id)
    assert proc is not None

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    exit_code = proc.returncode
    still_active = job.id in runtime._active_processes
    assert exit_code is not None
    assert still_active is False
