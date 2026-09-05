"""Unit tests for local subprocess runtime adapter."""

import pytest
from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.adapters.runtime.local import LocalSubprocessExecutionRuntimeAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements


@pytest.mark.asyncio
async def test_local_subprocess_execution():
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

    result = await runtime.execute(job)
    assert result.exit_code == 0
    assert result.outcome == TerminalOutcome.COMPLETED

    chunks = [c async for c in log_port.stream_logs("job-echo")]
    assert len(chunks) > 0
    assert "Hello Hexaqueue" in chunks[0].content


@pytest.mark.asyncio
async def test_local_subprocess_failure():
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
async def test_local_subprocess_timeout():
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
async def test_local_subprocess_terminate():
    """Verify termination of active subprocess."""
    runtime = LocalSubprocessExecutionRuntimeAdapter()
    await runtime.terminate("non-existent-job")
