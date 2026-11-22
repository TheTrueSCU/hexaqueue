"""Unit tests for HttpSchedulerControllerAdapter HTTP client operations."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from hexaqueue_core.domain.cqrs import ClusterStatsReport
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
    PriorityBreakdown,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, RunState
from hexaqueue_core.domain.suite import SuiteSpec, TaskSpec
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.adapters.http.controller import HttpSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunStatusReport
from hexaqueue_worker.domain.pty import PtySessionInfo, PtySessionRequest


def _run_report(run_id: str = "run-1") -> RunStatusReport:
    now = datetime.now(UTC)
    return RunStatusReport(
        run_id=run_id,
        state=RunState.RUNNING,
        total_jobs=1,
        completed_jobs=0,
        failed_jobs=0,
        running_jobs=1,
        pending_jobs=0,
        created_at=now,
        updated_at=now,
    )


def _explain_report(job_id: str = "job-1") -> SchedulingDecisionReport:
    breakdown = PriorityBreakdown(
        base_score=100.0,
        age_score=10.0,
        fairshare_score=50.0,
        preemption_bonus=0.0,
        total_priority=160.0,
        age_seconds=5.0,
        fairshare_factor=1.0,
        target_share=0.5,
        actual_usage=0.0,
    )
    return SchedulingDecisionReport(
        job_id=job_id,
        user="alice",
        state=JobState.PENDING,
        queue_position=1,
        queue_total=1,
        priority_breakdown=breakdown,
        summary="Ready",
    )


@pytest.mark.asyncio
async def test_controller_extended_remote_endpoints_and_acting_as() -> None:
    """Verify extended HTTP controller methods and acting_as ContextVar header propagation."""
    seen: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), dict(request.headers)))
        path = request.url.path
        if path == "/v1/stats":
            report = ClusterStatsReport(total_runs=2, total_jobs=3, active_workers=2)
            return httpx.Response(200, json=report.model_dump(mode="json"))
        if path == "/v1/fairshare":
            tree = FairShareTreeReport(
                root=FairShareNodeReport(
                    id="root",
                    shares=1.0,
                    target_share=1.0,
                    raw_usage=0.0,
                    decayed_usage=0.0,
                    fairshare_factor=1.0,
                    children=[],
                ),
                half_life_seconds=86400.0,
                total_decayed_usage=0.0,
            )
            return httpx.Response(200, json=tree.model_dump(mode="json"))
        if path == "/v1/jobs/job-1/explain":
            return httpx.Response(
                200, json=_explain_report("job-1").model_dump(mode="json")
            )
        if path == "/v1/jobs/job-1/logs":
            chunk = LogChunk(job_id="job-1", content="line 1\n", offset=0)
            return httpx.Response(200, json=[chunk.model_dump(mode="json")])
        if path == "/v1/jobs/job-1/logs/download-url":
            return httpx.Response(
                200,
                json={
                    "job_id": "job-1",
                    "download_url": "https://cdn.example/job-1.log",
                    "storage_key": "logs/job-1/stdout_stderr.log",
                    "expires_in_seconds": 300,
                },
            )
        if path == "/v1/runs":
            return httpx.Response(
                200, json=[_run_report("run-1").model_dump(mode="json")]
            )
        if path == "/v1/suites":
            body = json.loads(request.content.decode())
            assert body["suite_spec"]["id"] == "suite-1"
            return httpx.Response(
                201, json=_run_report("suite-1").model_dump(mode="json")
            )
        if path == "/v1/nodes":
            pulse = NodeTelemetryPulse(
                worker_id="w-1",
                memory_total_mb=1024,
                memory_used_mb=256,
                scratch_total_mb=1024,
                scratch_used_mb=128,
            )
            return httpx.Response(200, json=[pulse.model_dump(mode="json")])
        if path == "/v1/nodes/w-1/ssh":
            info = PtySessionInfo(
                session_id="bastion-1",
                job_id="",
                user_id="alice",
                pid=99,
            )
            return httpx.Response(200, json=info.model_dump(mode="json"))
        if path == "/v1/jobs/job-1/pty":
            info = PtySessionInfo(
                session_id="pty-1",
                job_id="job-1",
                user_id="alice",
                pid=100,
            )
            return httpx.Response(200, json=info.model_dump(mode="json"))
        return httpx.Response(404, json={"detail": "unknown"})

    adapter = HttpSchedulerControllerAdapter(
        base_url="http://controller.local:8000",
        admin_token=SecretStr("tok-123"),
        user_id="cli",
        elevate=False,
        transport=httpx.MockTransport(handler),
    )

    stats = await adapter.get_queue_stats()
    assert stats.total_runs == 2
    assert stats.active_workers == 2

    with adapter.acting_as("alice", True):
        fairshare = await adapter.get_fairshare_tree()
        explained = await adapter.explain_job("job-1")
        bastion = await adapter.create_bastion_session("w-1")

    assert fairshare.root.id == "root"
    assert explained.job_id == "job-1"
    assert bastion.session_id == "bastion-1"

    logs = await adapter.get_logs("job-1", tail=10)
    assert len(logs) == 1
    assert logs[0].content == "line 1\n"

    dl_url = await adapter.get_job_log_download_url("job-1", expires_in_seconds=300)
    assert dl_url == "https://cdn.example/job-1.log"

    runs = await adapter.list_runs(limit=25)
    assert len(runs) == 1
    assert runs[0].run_id == "run-1"

    suite = SuiteSpec(
        id="suite-1",
        name="demo-suite",
        matrix={"x": ["1"]},
        tasks=[TaskSpec(id="t1", name="t1", command="echo 1")],
    )
    suite_report = await adapter.submit_suite(suite)
    assert suite_report.run_id == "suite-1"

    pulses = await adapter.list_node_pulses()
    assert len(pulses) == 1
    assert pulses[0].worker_id == "w-1"

    pty_info = await adapter.create_pty_session(
        PtySessionRequest(job_id="job-1", session_id="pty-1", user_id="alice")
    )
    assert pty_info.session_id == "pty-1"

    # After exiting acting_as, default user_id/elevate must be restored.
    assert seen[0][2]["x-hexaqueue-user"] == "cli"
    assert seen[0][2]["x-hexaqueue-elevate"] == "false"
    assert seen[1][2]["x-hexaqueue-user"] == "alice"
    assert seen[1][2]["x-hexaqueue-elevate"] == "true"
    assert seen[-1][2]["x-hexaqueue-user"] == "cli"
    assert seen[-1][2]["x-hexaqueue-elevate"] == "false"


@pytest.mark.asyncio
async def test_controller_transport_error_wrapped_in_hexaqueue_error() -> None:
    """Verify network/transport failures raise HexaqueueError."""

    def transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    adapter = HttpSchedulerControllerAdapter(
        transport=httpx.MockTransport(transport_error)
    )
    with pytest.raises(HexaqueueError, match="Failed to reach controller"):
        await adapter.get_queue_stats()
    assert isinstance(JobSpec(id="j", run_id="r", name="n", command="true"), JobSpec)
