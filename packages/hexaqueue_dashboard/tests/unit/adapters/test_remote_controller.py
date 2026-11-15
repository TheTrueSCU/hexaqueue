"""Unit tests for HttpSchedulerControllerAdapter using hermetic httpx.MockTransport."""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import httpx
import pytest
from pydantic import SecretStr

from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import RunState, TerminalOutcome
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_dashboard.adapters.remote_controller import (
    HttpSchedulerControllerAdapter,
)
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission

if TYPE_CHECKING:
    from hexaqueue_server.domain.memento import SchedulerMemento


def _sample_job(job_id: str = "job-1") -> JobSpec:
    return JobSpec(
        id=job_id,
        run_id="run-1",
        name="smoke-job",
        command="echo",
        args=["hello"],
    )


def _sample_node(node_id: str = "node-1") -> ComputeNodeProfile:
    return ComputeNodeProfile(node_id=node_id)


def _sample_run_report(run_id: str = "run-1") -> RunStatusReport:
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


@pytest.mark.asyncio
async def test_remote_controller_queries_and_headers() -> None:
    """Verify HTTP methods, auth headers, and model deserialization."""
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        if request.method == "GET" and request.url.path == "/v1/jobs":
            return httpx.Response(200, json=[_sample_job().model_dump(mode="json")])
        if request.method == "GET" and request.url.path == "/v1/jobs/job-1":
            return httpx.Response(200, json=_sample_job().model_dump(mode="json"))
        if request.method == "GET" and request.url.path == "/v1/runs/run-1":
            return httpx.Response(
                200, json=_sample_run_report().model_dump(mode="json")
            )
        if request.method == "GET" and request.url.path == "/v1/nodes/profiles":
            return httpx.Response(
                200,
                json={
                    "nodes": [_sample_node().model_dump(mode="json")],
                    "total_nodes": 1,
                },
            )
        if request.method == "GET" and request.url.path == "/v1/dlq":
            return httpx.Response(200, json={"records": [], "total_count": 0})
        return httpx.Response(404, json={"detail": "not found"})

    adapter = HttpSchedulerControllerAdapter(
        base_url="http://controller.local:8000",
        admin_token=SecretStr("secret-admin-tok"),
        user_id="dash-svc",
        elevate=True,
        transport=httpx.MockTransport(handler),
    )

    jobs = await adapter.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "job-1"
    assert captured_headers["x-hexaqueue-user"] == "dash-svc"
    assert captured_headers["x-hexaqueue-elevate"] == "true"
    assert captured_headers["x-hexaqueue-admin-token"] == "secret-admin-tok"

    job = await adapter.get_job("job-1")
    assert job.id == "job-1"

    report = await adapter.get_run_status("run-1")
    assert report.run_id == "run-1"

    nodes = await adapter.list_nodes()
    assert len(nodes) == 1
    assert nodes[0].node_id == "node-1"

    dlq = await adapter.list_dead_letters()
    assert dlq == []


@pytest.mark.asyncio
async def test_remote_controller_mutations() -> None:
    """Verify job/run/node mutation endpoints serialize payloads and parse responses."""
    seen_paths: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append((request.method, request.url.path))
        if request.url.path == "/v1/runs":
            return httpx.Response(
                201, json=_sample_run_report().model_dump(mode="json")
            )
        if request.url.path == "/v1/runs/run-1/cancel":
            return httpx.Response(
                200, json=_sample_run_report().model_dump(mode="json")
            )
        if request.url.path == "/v1/runs/run-1/rewind":
            return httpx.Response(
                200,
                json={
                    "run_id": "run-1",
                    "rewound_job_ids": ["job-1"],
                    "re_enqueued_job_ids": ["job-1"],
                    "unaffected_job_ids": [],
                },
            )
        if request.url.path in {
            "/v1/jobs/job-1/hold",
            "/v1/jobs/job-1/release",
            "/v1/jobs/job-1/cancel",
        }:
            return httpx.Response(200, json=_sample_job().model_dump(mode="json"))
        if request.url.path in {"/v1/jobs/job-1/complete", "/v1/jobs/job-1/fail"}:
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/nodes/register":
            body = json.loads(request.content.decode())
            assert body["profile"]["node_id"] == "node-1"
            return httpx.Response(
                201, json={"status": "REGISTERED", "node_id": "node-1"}
            )
        if request.url.path == "/v1/nodes/heartbeat":
            return httpx.Response(200, json=_sample_node().model_dump(mode="json"))
        if request.url.path == "/v1/scheduler/simulate-placement":
            return httpx.Response(
                200,
                json={
                    "all_schedulable": True,
                    "items": [],
                    "required_ephemeral_bursts": 0,
                    "simulated_at": datetime.now(UTC).isoformat(),
                },
            )
        return httpx.Response(404)

    adapter = HttpSchedulerControllerAdapter(transport=httpx.MockTransport(handler))

    submission = RunSubmission(
        run_spec=RunSpec(id="run-1", name="smoke", jobs=[_sample_job()]),
        jobs=[_sample_job()],
        dependencies={},
    )
    sub_report = await adapter.submit_run(submission)
    assert sub_report.run_id == "run-1"

    held = await adapter.hold_job("job-1")
    assert held.id == "job-1"

    released = await adapter.release_job("job-1")
    assert released.id == "job-1"

    cancelled_job = await adapter.cancel_job("job-1")
    assert cancelled_job.id == "job-1"

    await adapter.update_job_outcome(
        "job-1", TerminalOutcome.COMPLETED, walltime_seconds=1.2
    )
    await adapter.update_job_outcome("job-1", TerminalOutcome.FAILED, reason="boom")

    cancelled_run = await adapter.cancel_run("run-1")
    assert cancelled_run.run_id == "run-1"

    rewound = await adapter.rewind_run("run-1", ["job-1"])
    assert rewound.run_id == "run-1"

    await adapter.register_node(_sample_node())
    hb_node = await adapter.heartbeat_node("node-1", active_job_ids=["job-1"])
    assert hb_node.node_id == "node-1"

    sim = await adapter.simulate_placement([_sample_job()])
    assert sim.all_schedulable is True
    assert ("POST", "/v1/runs") in seen_paths


@pytest.mark.asyncio
async def test_remote_controller_errors_and_internal_methods() -> None:
    """Verify HTTP error translation and NotImplementedError for internal-only methods."""

    def failing_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "controller busy"})

    adapter = HttpSchedulerControllerAdapter(
        transport=httpx.MockTransport(failing_handler)
    )

    with pytest.raises(HexaqueueError, match="Controller HTTP 503"):
        await adapter.list_jobs()

    with pytest.raises(NotImplementedError):
        await adapter.evaluate_node_failures()

    with pytest.raises(NotImplementedError):
        await adapter.schedule_placement("job-1")

    with pytest.raises(NotImplementedError):
        adapter.create_memento()

    with pytest.raises(NotImplementedError):
        adapter.restore_memento(cast("SchedulerMemento", object()))
