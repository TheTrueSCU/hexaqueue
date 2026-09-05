"""Tests for LocalClientAdapter."""

import pytest

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.domain.session import LocalCliSession
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunSubmission


@pytest.mark.asyncio
async def test_local_client_adapter_operations() -> None:
    """Verify LocalClientAdapter forwards operations to in-process session."""
    session = LocalCliSession(concurrency=2)
    client = LocalClientAdapter(session=session)

    run = RunSpec(id="run-cli-test", name="CLI Test")
    job = JobSpec(id="j1", run_id=run.id, name="job-1", command="echo test")
    submission = RunSubmission(run_spec=run, jobs=[job])

    report = await client.submit_run(submission)
    assert report.run_id == run.id

    fetched_report = await client.get_run_status(run.id)
    assert fetched_report.run_id == run.id

    fetched_job = await client.get_job(job.id)
    assert fetched_job.id == job.id

    await session.log_stream.write_log(
        LogChunk(job_id=job.id, content="output line", offset=0)
    )
    logs = await client.get_logs(job.id)
    assert len(logs) == 1
    assert logs[0].content == "output line"

    cancel_report = await client.cancel_run(run.id)
    assert cancel_report.run_id == run.id
