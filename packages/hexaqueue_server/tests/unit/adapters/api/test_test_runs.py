"""Unit tests for distributed test slice dispatch API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from hexaqueue_server.adapters.api.app import create_server_app
from hexaqueue_server.adapters.api.test_runs import (
    TestSliceDispatch,
    _execute_slice,
)


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    """Verify cluster health check endpoint returns 200 OK."""
    app = create_server_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_execute_empty_slice() -> None:
    """Verify executing an empty slice returns immediate empty outcome."""
    slice_spec = TestSliceDispatch(
        slice_id="s0",
        slice_index=0,
        total_slices=1,
        test_nodeids=[],
    )
    res = await _execute_slice(slice_spec, worker_index=0, is_free_tier=True)
    assert res.slice_id == "s0"
    assert res.worker_id == "worker-local-0"
    assert len(res.outcomes) == 0


@pytest.mark.asyncio
async def test_execute_slice_mocked_subprocess() -> None:
    """Verify slice execution parsing mocked subprocess exit code."""
    slice_spec = TestSliceDispatch(
        slice_id="s1",
        slice_index=1,
        total_slices=2,
        test_nodeids=["test_a.py::test_one", "test_b.py::test_two"],
    )

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"2 passed in 0.1s", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await _execute_slice(slice_spec, worker_index=1, is_free_tier=True)

    assert res.slice_id == "s1"
    assert res.worker_id == "worker-local-1"
    assert len(res.outcomes) == 2
    assert res.outcomes[0].outcome == "passed"
    assert res.outcomes[1].outcome == "passed"


@pytest.mark.asyncio
async def test_dispatch_test_run_endpoint() -> None:
    """Verify POST /api/v1/test/runs endpoint dispatches slices."""
    app = create_server_app()
    transport = ASGITransport(app=app)
    payload = {
        "session_id": "sess-01",
        "pool": "default",
        "free_tier": True,
        "slices": [
            {
                "slice_id": "s0",
                "slice_index": 0,
                "total_slices": 1,
                "test_nodeids": [],
            }
        ],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/test/runs", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "reports" in data
        assert len(data["reports"]) == 1
        assert data["reports"][0]["slice_id"] == "s0"
