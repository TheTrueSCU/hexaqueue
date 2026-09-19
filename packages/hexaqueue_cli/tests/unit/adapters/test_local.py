"""Tests for LocalClientAdapter."""

from collections.abc import AsyncGenerator

import pytest

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.domain.session import LocalCliSession
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunSubmission


@pytest.fixture
async def hermetic_local_session() -> AsyncGenerator[LocalCliSession]:
    """Provide an isolated LocalCliSession with guaranteed async teardown.

    Notes/Architectural Intent:
        Hermetically seals each test with a pristine in-memory session and cleanly
        tears down all registered PTY sessions and background workers upon test completion.
    """
    session = LocalCliSession(concurrency=2)
    try:
        yield session
    finally:
        for s_id in list(session.pty._sessions.keys()):
            await session.pty.terminate_session(s_id)
        await session.stop()


@pytest.mark.asyncio
async def test_local_client_adapter_operations(
    hermetic_local_session: LocalCliSession,
) -> None:
    """Verify LocalClientAdapter forwards operations to in-process session."""
    client = LocalClientAdapter(session=hermetic_local_session)
    session = hermetic_local_session

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
    res_cancel_id = cancel_report.run_id
    assert res_cancel_id == run.id

    explain_report = await client.explain_job(job.id)
    res_job_id = explain_report.job_id
    assert res_job_id == job.id

    tree_report = await client.get_fairshare_tree()
    res_root_id = tree_report.root.id
    assert res_root_id == "root"

    # Test list_jobs
    all_jobs = await client.list_jobs()
    assert len(all_jobs) == 1
    res_j_id = all_jobs[0].id
    assert res_j_id == "j1"

    # Test get_cluster_stats
    stats = await client.get_cluster_stats()
    res_total_runs = stats.total_runs
    res_total_jobs = stats.total_jobs
    assert res_total_runs == 1
    assert res_total_jobs == 1

    # Test get_nodes
    nodes = await client.get_nodes()
    assert len(nodes) == 1
    res_node_id = nodes[0].worker_id
    assert res_node_id is not None

    # Test stream_logs
    chunks = [c async for c in client.stream_logs(job.id, follow=False)]
    assert len(chunks) == 1
    res_chunk_content = chunks[0].content
    assert res_chunk_content == "output line"


@pytest.mark.asyncio
async def test_local_client_adapter_lifecycle_and_pty(
    hermetic_local_session: LocalCliSession,
) -> None:
    """Verify hold_job, release_job, cancel_job, and create_pty_session."""
    from hexaqueue_core.domain.lifecycle import JobState
    from hexaqueue_worker.domain.pty import PtySessionRequest

    session = hermetic_local_session
    client = LocalClientAdapter(session=session)

    run = RunSpec(id="run-ctrl-test", name="Control Test")
    job = JobSpec(id="j-ctrl", run_id=run.id, name="job-ctrl", command="echo 1")
    submission = RunSubmission(run_spec=run, jobs=[job])
    await client.submit_run(submission)

    # Test hold_job
    held = await client.hold_job(job.id)
    res_held_state = held.state
    assert res_held_state == JobState.BLOCKED

    # Test release_job
    released = await client.release_job(job.id)
    res_rel_state = released.state
    assert res_rel_state == JobState.PENDING

    # Test cancel_job
    cancelled = await client.cancel_job(job.id)
    res_canc_state = cancelled.state
    assert res_canc_state == JobState.DONE

    # Test create_pty_session
    pty_req = PtySessionRequest(
        session_id="pty-test-1",
        job_id=job.id,
        user_id="operator-user",
        roles=["operator"],
        command=["echo", "test"],
    )
    pty_info = await client.create_pty_session(pty_req, job_owner="operator-user")
    res_sess_id = pty_info.session_id
    assert res_sess_id == "pty-test-1"
    await session.pty.terminate_session(pty_info.session_id)
