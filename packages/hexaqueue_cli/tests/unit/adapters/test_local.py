"""Tests for LocalClientAdapter (local CQRS and remote HTTP modes)."""

import hashlib
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.domain.models import ClusterStatsReport
from hexaqueue_cli.domain.session import LocalCliSession
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
    PriorityBreakdown,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, RunState
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.domain.suite import SuiteSpec, TaskSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_worker.domain.pty import PtySessionInfo, PtySessionRequest


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

    fetched_runs = await client.list_runs()
    assert len(fetched_runs) == 1
    assert fetched_runs[0].run_id == run.id

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

    all_jobs = await client.list_jobs()
    assert len(all_jobs) == 1
    res_j_id = all_jobs[0].id
    assert res_j_id == "j1"

    stats = await client.get_cluster_stats()
    res_total_runs = stats.total_runs
    res_total_jobs = stats.total_jobs
    assert res_total_runs == 1
    assert res_total_jobs == 1

    nodes = await client.get_nodes()
    assert len(nodes) == 1
    res_node_id = nodes[0].worker_id
    assert res_node_id is not None

    chunks = [c async for c in client.stream_logs(job.id, follow=False)]
    assert len(chunks) == 1
    res_chunk_content = chunks[0].content
    assert res_chunk_content == "output line"


@pytest.mark.asyncio
async def test_local_client_adapter_lifecycle_and_pty(
    hermetic_local_session: LocalCliSession,
) -> None:
    """Verify hold_job, release_job, cancel_job, and create_pty_session."""
    session = hermetic_local_session
    client = LocalClientAdapter(session=session)

    run = RunSpec(id="run-ctrl-test", name="Control Test")
    job = JobSpec(id="j-ctrl", run_id=run.id, name="job-ctrl", command="echo 1")
    submission = RunSubmission(run_spec=run, jobs=[job])
    await client.submit_run(submission)

    held = await client.hold_job(job.id)
    res_held_state = held.state
    assert res_held_state == JobState.BLOCKED

    released = await client.release_job(job.id)
    res_rel_state = released.state
    assert res_rel_state == JobState.PENDING

    cancelled = await client.cancel_job(job.id)
    res_canc_state = cancelled.state
    assert res_canc_state == JobState.DONE

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


@pytest.mark.asyncio
async def test_local_client_adapter_collateral_cqrs_lifecycle(
    hermetic_local_session: LocalCliSession,
    tmp_path: Path,
) -> None:
    """Verify full collateral CQRS lifecycle and RBAC enforcement in local mode."""
    client = LocalClientAdapter(session=hermetic_local_session)
    asset = tmp_path / "weights.bin"
    payload = b"tensor-weights-v1"
    asset.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    bundle = await client.register_collateral(
        name="weights.bin",
        size_bytes=len(payload),
        checksum_sha256=digest,
        tier=CollateralTier.TEMPORARY,
        kind=CollateralKind.BUNDLE,
        target_path=str(asset),
        user_id="alice",
    )
    assert bundle.state == CollateralState.APPROVED
    assert bundle.owner == "alice"

    alice_list = await client.list_collateral(user_id="alice")
    assert [b.id for b in alice_list] == [bundle.id]

    bob_list = await client.list_collateral(user_id="bob")
    assert bob_list == []

    admin_list = await client.list_collateral(user_id="bob", elevate=True)
    assert [b.id for b in admin_list] == [bundle.id]

    with pytest.raises(PermissionDeniedError):
        await client.get_collateral(bundle.id, user_id="bob", elevate=False)

    inspected = await client.get_collateral(bundle.id, user_id="alice")
    assert inspected.id == bundle.id

    pinned = await client.pin_collateral(bundle.id, user_id="alice")
    assert pinned.active_pin_count == 1

    unpinned = await client.unpin_collateral(bundle.id, user_id="alice")
    assert unpinned.active_pin_count == 0

    with pytest.raises(PermissionDeniedError):
        await client.promote_collateral(bundle.id, user_id="alice", elevate=False)

    promoted = await client.promote_collateral(bundle.id, user_id="alice", elevate=True)
    assert promoted.tier == CollateralTier.PERMANENT

    evicted = await client.evict_expired_collateral(
        max_age_seconds=1, user_id="alice", elevate=True
    )
    assert bundle.id not in evicted

    deleted = await client.delete_collateral(bundle.id, user_id="alice", elevate=True)
    assert deleted == bundle.id


@pytest.mark.asyncio
async def test_remote_client_adapter_mock_transport(tmp_path: Path) -> None:
    """Verify remote mode routes CQRS and HTTP endpoints cleanly without fake local nodes."""
    calls: list[tuple[str, str, dict[str, str], bytes]] = []
    sample_payload = b"remote-artifact"
    sample_digest = hashlib.sha256(sample_payload).hexdigest()
    now = datetime.now(UTC)

    bundle = CollateralBundle(
        id="col-remote-1",
        job_id="alice",
        owner="alice",
        filename="remote.tar.gz",
        size_bytes=len(sample_payload),
        sha256_checksum=sample_digest,
        tier=CollateralTier.TEMPORARY,
        kind=CollateralKind.BUNDLE,
        state=CollateralState.APPROVED,
        staging_uri="s3://bucket/staging/col-remote-1",
        active_uri="s3://bucket/cas/col-remote-1",
    )
    run_report = RunStatusReport(
        run_id="run-remote-1",
        owner="alice",
        state=RunState.RUNNING,
        total_jobs=1,
        completed_jobs=0,
        failed_jobs=0,
        running_jobs=1,
        pending_jobs=0,
        created_at=now,
        updated_at=now,
    )
    job = JobSpec(
        id="job-remote-1",
        run_id="run-remote-1",
        name="remote-job",
        user="alice",
        owner="alice",
        command="echo remote",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            (request.method, request.url.path, dict(request.headers), request.content)
        )
        path = request.url.path
        if path == "/v1/stats":
            stats = ClusterStatsReport(total_runs=3, total_jobs=7, active_workers=2)
            return httpx.Response(200, json=stats.model_dump(mode="json"))
        if path == "/v1/nodes":
            return httpx.Response(200, json=[])
        if path == "/v1/runs":
            return httpx.Response(200, json=[run_report.model_dump(mode="json")])
        if path == "/v1/suites":
            return httpx.Response(201, json=run_report.model_dump(mode="json"))
        if path == "/v1/jobs":
            return httpx.Response(200, json=[job.model_dump(mode="json")])
        if path == "/v1/jobs/job-remote-1/explain":
            report = SchedulingDecisionReport(
                job_id="job-remote-1",
                user="alice",
                state=JobState.PENDING,
                queue_position=1,
                queue_total=1,
                priority_breakdown=PriorityBreakdown(
                    base_score=10.0,
                    age_score=0.0,
                    fairshare_score=10.0,
                    preemption_bonus=0.0,
                    total_priority=20.0,
                    age_seconds=0.0,
                    fairshare_factor=1.0,
                    target_share=1.0,
                    actual_usage=0.0,
                ),
                summary="Queued remotely",
            )
            return httpx.Response(200, json=report.model_dump(mode="json"))
        if path == "/v1/fairshare":
            tree = FairShareTreeReport(
                root=FairShareNodeReport(
                    id="root",
                    shares=1.0,
                    target_share=1.0,
                    raw_usage=1.0,
                    decayed_usage=1.0,
                    fairshare_factor=1.0,
                    children=[],
                ),
                half_life_seconds=86400.0,
                total_decayed_usage=1.0,
            )
            return httpx.Response(200, json=tree.model_dump(mode="json"))
        if path == "/v1/nodes/w-1/ssh":
            info = PtySessionInfo(
                session_id="bastion-remote",
                job_id="bastion-w-1",
                user_id="alice",
                pid=42,
            )
            return httpx.Response(200, json=info.model_dump(mode="json"))
        if path == "/v1/jobs/job-remote-1/logs/download-url":
            return httpx.Response(
                200,
                json={
                    "job_id": "job-remote-1",
                    "download_url": "https://s3.example/remote.log",
                    "storage_key": "logs/job-remote-1/stdout_stderr.log",
                    "expires_in_seconds": 900,
                },
            )
        if path == "/v1/collateral/stage":
            return httpx.Response(200, json=bundle.model_dump(mode="json"))
        if path == "/v1/collateral":
            return httpx.Response(200, json=[bundle.model_dump(mode="json")])
        if path == f"/v1/collateral/{bundle.id}/promote":
            promoted_b = bundle.model_copy(update={"tier": CollateralTier.PERMANENT})
            return httpx.Response(200, json=promoted_b.model_dump(mode="json"))
        return httpx.Response(404, json={"detail": json.dumps({"path": path})})

    client = LocalClientAdapter(
        controller_url="http://remote:8000",
        admin_token="adm-secret",
        transport=httpx.MockTransport(handler),
    )

    stats = await client.get_cluster_stats()
    assert stats.total_runs == 3
    assert stats.active_workers == 2

    nodes = await client.get_nodes()
    assert nodes == []

    runs = await client.list_runs(user_id="alice")
    assert len(runs) == 1
    assert runs[0].run_id == "run-remote-1"

    jobs = await client.list_jobs(user_id="alice")
    assert [j.id for j in jobs] == ["job-remote-1"]

    suite_rep = await client.submit_suite(
        SuiteSpec(
            id="run-remote-1",
            name="remote-suite",
            tasks=[TaskSpec(id="t1", name="t1", command="echo 1")],
        ),
        user_id="alice",
    )
    assert suite_rep.run_id == "run-remote-1"

    explained = await client.explain_job("job-remote-1", requesting_user="alice")
    assert explained.summary == "Queued remotely"

    fairshare = await client.get_fairshare_tree(requesting_user="alice")
    assert fairshare.root.id == "root"

    bastion = await client.create_bastion_session("w-1", user_id="alice", elevate=True)
    assert bastion.session_id == "bastion-remote"

    dl_url = await client.get_log_download_url("job-remote-1", user_id="alice")
    assert dl_url == "https://s3.example/remote.log"

    local_file = tmp_path / "remote.tar.gz"
    local_file.write_bytes(sample_payload)
    staged = await client.register_collateral(
        name="remote.tar.gz",
        size_bytes=len(sample_payload),
        checksum_sha256=sample_digest,
        target_path=str(local_file),
        user_id="alice",
    )
    assert staged.id == "col-remote-1"

    listed_col = await client.list_collateral(user_id="alice")
    assert len(listed_col) == 1

    promoted = await client.promote_collateral(bundle.id, user_id="alice", elevate=True)
    assert promoted.tier == CollateralTier.PERMANENT

    promote_calls = [c for c in calls if c[1] == f"/v1/collateral/{bundle.id}/promote"]
    assert len(promote_calls) == 1
    assert promote_calls[0][2]["x-hexaqueue-user"] == "alice"
    assert promote_calls[0][2]["x-hexaqueue-elevate"] == "true"
    assert promote_calls[0][2]["x-hexaqueue-admin-token"] == "adm-secret"
