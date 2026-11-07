"""Unit tests for internal worker pool API endpoints.

Notes/Architectural Intent:
    Validates cluster join token authentication, worker lifecycle registration,
    heartbeat renewals, pull-based slice leasing, and slice outcome reporting
    via SliceLeaseCoordinator. Ensures side-effect free assertions to prevent CodeQL alerts.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from hexastack_core.domain.exceptions import DependencyResolutionError
from hexastack_core.infra.container import create_container
from httpx import ASGITransport, AsyncClient

from hexaqueue_core.domain.lease import (
    SliceReportPayload,
    WorkerRegistration,
)
from hexaqueue_server.adapters.api.test_runs import TestSliceDispatch
from hexaqueue_server.adapters.api.worker_pool import (
    create_worker_pool_router,
    get_lease_coordinator,
)
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator


def _create_test_app(coordinator: SliceLeaseCoordinator | None = None) -> FastAPI:
    """Helper to instantiate test FastAPI app with worker pool router."""
    app = FastAPI()
    container = create_container()
    coord = coordinator or SliceLeaseCoordinator()
    container.add_instance(coord, declared_class=SliceLeaseCoordinator)
    app.state.container = container
    router = create_worker_pool_router(coordinator=coord)
    app.include_router(router)
    return app


def test_get_lease_coordinator_dependency() -> None:
    """Verify get_lease_coordinator resolves from request application container."""
    mock_request = MagicMock()
    container = create_container()
    coord = SliceLeaseCoordinator()
    container.add_instance(coord, declared_class=SliceLeaseCoordinator)
    mock_request.app.state.container = container

    resolved = get_lease_coordinator(mock_request)
    assert resolved is coord

    empty_request = MagicMock()
    empty_request.app.state.container = create_container()
    with pytest.raises(DependencyResolutionError, match="not registered"):
        get_lease_coordinator(empty_request)


@pytest.mark.asyncio
async def test_worker_registration_and_stats() -> None:
    """Verify worker node registration and pool capacity telemetry."""
    coord = SliceLeaseCoordinator()
    app = _create_test_app(coord)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Check initial stats
        stats_resp = await client.get("/worker/stats")
        code = stats_resp.status_code
        assert code == 200
        stats_data = stats_resp.json()
        assert stats_data["active_workers"] == 0
        assert stats_data["pending_slices"] == 0
        assert stats_data["active_leases"] == 0

        # Register worker
        reg_payload = {
            "worker_id": "worker-phx-1",
            "hostname": "worker-phx-1.local",
            "ip_address": "10.0.2.15",
            "ocpus": 4,
            "memory_mb": 24576,
            "labels": {"zone": "phx-ad-1"},
        }
        reg_resp = await client.post("/worker/register", json=reg_payload)
        reg_code = reg_resp.status_code
        assert reg_code == 201
        res_data = reg_resp.json()
        assert res_data["status"] == "registered"
        assert res_data["worker_id"] == "worker-phx-1"

        # Check updated stats
        stats_resp2 = await client.get("/worker/stats")
        stats_data2 = stats_resp2.json()
        assert stats_data2["active_workers"] == 1


@pytest.mark.asyncio
async def test_worker_heartbeat() -> None:
    """Verify heartbeat recording for registered and unregistered workers."""
    coord = SliceLeaseCoordinator()
    app = _create_test_app(coord)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Heartbeat for unknown worker fails with 404
        hb_unknown = await client.post(
            "/worker/unknown-worker/heartbeat",
            json={"active_lease_ids": []},
        )
        hb_unknown_code = hb_unknown.status_code
        assert hb_unknown_code == 404

        # Register worker
        await coord.register_worker(
            WorkerRegistration(
                worker_id="w-1",
                hostname="h1",
                ip_address="10.0.2.10",
                ocpus=2,
                memory_mb=12288,
            )
        )

        # Heartbeat with no body
        hb_empty = await client.post("/worker/w-1/heartbeat")
        hb_empty_code = hb_empty.status_code
        assert hb_empty_code == 200
        data1 = hb_empty.json()
        assert data1["status"] == "ok"

        # Heartbeat with active leases
        hb_active = await client.post(
            "/worker/w-1/heartbeat",
            json={"active_lease_ids": ["lease-123"]},
        )
        hb_active_code = hb_active.status_code
        assert hb_active_code == 200
        data2 = hb_active.json()
        assert data2["status"] == "ok"


@pytest.mark.asyncio
async def test_lease_slice_empty_and_available() -> None:
    """Verify pull leasing returns 204 when empty and grants lease when tasks are enqueued."""
    coord = SliceLeaseCoordinator()
    app = _create_test_app(coord)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register worker
        await coord.register_worker(
            WorkerRegistration(
                worker_id="w-pull",
                hostname="pull-host",
                ip_address="10.0.2.20",
                ocpus=4,
                memory_mb=16384,
            )
        )

        # Long poll with timeout 0 -> returns 204
        lease_resp = await client.post(
            "/worker/w-pull/lease",
            json={"available_ocpus": 4, "timeout_seconds": 0.0},
        )
        lease_code = lease_resp.status_code
        assert lease_code == 204

        # Enqueue slices into coordinator
        slices = [
            TestSliceDispatch(
                slice_id="sl-1",
                slice_index=0,
                total_slices=1,
                test_nodeids=["tests/test_demo.py::test_alpha"],
            )
        ]
        await coord.enqueue_session_slices(
            session_id="sess-abc",
            slices=slices,
            collateral_id="col-999",
            coverage_sources=["mypkg"],
        )

        # Poll again without body parameters (defaults applied)
        lease_resp2 = await client.post("/worker/w-pull/lease")
        lease_code2 = lease_resp2.status_code
        assert lease_code2 == 200
        lease_data = lease_resp2.json()
        assert lease_data["worker_id"] == "w-pull"
        assert lease_data["task"]["slice_id"] == "sl-1"
        assert lease_data["task"]["session_id"] == "sess-abc"


@pytest.mark.asyncio
async def test_report_slice_outcome_success_and_conflict() -> None:
    """Verify slice outcome reporting records results or rejects invalid leases."""
    coord = SliceLeaseCoordinator()
    app = _create_test_app(coord)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Report for nonexistent lease fails with 409
        bad_report = SliceReportPayload(
            lease_id="invalid-lease",
            slice_id="sl-x",
            worker_id="w-1",
            exit_code=0,
            duration_seconds=1.2,
        )
        bad_resp = await client.post(
            "/worker/w-1/report",
            json=bad_report.model_dump(),
        )
        bad_code = bad_resp.status_code
        assert bad_code == 409

        # Register and enqueue
        await coord.register_worker(
            WorkerRegistration(
                worker_id="w-rep",
                hostname="h-rep",
                ip_address="10.0.2.30",
                ocpus=2,
                memory_mb=8192,
            )
        )
        slices = [
            TestSliceDispatch(
                slice_id="sl-ok",
                slice_index=0,
                total_slices=1,
                test_nodeids=["tests/test_x.py::test_pass"],
            )
        ]
        ev = await coord.enqueue_session_slices(session_id="sess-ok", slices=slices)
        lease = await coord.lease_slice(worker_id="w-rep", available_ocpus=2)
        assert lease is not None

        # Report valid outcome
        valid_report = SliceReportPayload(
            lease_id=lease.lease_id,
            slice_id="sl-ok",
            worker_id="w-rep",
            exit_code=0,
            duration_seconds=2.45,
            outcomes=[
                {
                    "nodeid": "tests/test_x.py::test_pass",
                    "outcome": "passed",
                    "duration_seconds": 2.45,
                }
            ],
        )
        good_resp = await client.post(
            "/worker/w-rep/report",
            json=valid_report.model_dump(),
        )
        good_code = good_resp.status_code
        assert good_code == 200
        res = good_resp.json()
        assert res["status"] == "recorded"
        assert res["slice_id"] == "sl-ok"

        # Session event triggered
        ev_set = ev.is_set()
        assert ev_set is True


@pytest.mark.asyncio
async def test_join_token_security_enforcement() -> None:
    """Verify cluster join token header validation."""
    coord = SliceLeaseCoordinator()
    app = _create_test_app(coord)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.dict("os.environ", {"HEXAQUEUE_JOIN_TOKEN": "secret-cluster-token"}):
            # Missing token header
            resp_missing = await client.get("/worker/stats")
            code_missing = resp_missing.status_code
            assert code_missing == 403

            # Incorrect token header
            resp_bad = await client.get(
                "/worker/stats",
                headers={"x-hexaqueue-join-token": "wrong-token"},
            )
            code_bad = resp_bad.status_code
            assert code_bad == 403

            # Correct token header
            resp_ok = await client.get(
                "/worker/stats",
                headers={"x-hexaqueue-join-token": "secret-cluster-token"},
            )
            code_ok = resp_ok.status_code
            assert code_ok == 200
