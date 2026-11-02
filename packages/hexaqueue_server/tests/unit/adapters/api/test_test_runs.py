"""Unit tests for distributed test slice dispatch API endpoints."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from hexaqueue_server.adapters.api.app import create_server_app
from hexaqueue_server.adapters.api.test_runs import (
    TestSliceDispatch,
    _build_slice_cmd,
    _execute_slice,
    get_worker_semaphore,
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


def test_build_slice_cmd_container() -> None:
    """Verify container command construction with volume mounts and isolation."""
    slice_spec = TestSliceDispatch(
        slice_id="s-cont-0",
        slice_index=0,
        total_slices=1,
        test_nodeids=["tests/unit/test_demo.py::test_it"],
    )
    cmd, provider, worker_id = _build_slice_cmd(
        slice_spec,
        worker_index=0,
        is_container=True,
        container_image="custom-worker:v1",
    )
    assert provider == "CONTAINER"
    assert worker_id == "worker-container-0"
    assert "run" in cmd
    assert "--rm" in cmd
    assert "custom-worker:v1" in cmd
    assert "pytest" in cmd
    assert "tests/unit/test_demo.py::test_it" in cmd
    assert "no:cacheprovider" in cmd
    assert "consider_namespace_packages=true" in " ".join(cmd)

    # Also test local command construction
    local_cmd, local_provider, local_worker_id = _build_slice_cmd(
        slice_spec,
        worker_index=1,
        is_container=False,
        container_image=None,
    )
    assert local_provider == "LOCAL"
    assert local_worker_id == "worker-local-1"
    assert "-m" in local_cmd
    assert "pytest" in local_cmd
    assert "no:cacheprovider" in local_cmd
    assert "consider_namespace_packages=true" in " ".join(local_cmd)


def test_build_slice_cmd_custom_csp_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify provider and worker_id dynamically resolve explicit CSP environment."""
    monkeypatch.setenv("HEXAQUEUE_CSP_PROVIDER", "OCI")
    slice_spec = TestSliceDispatch(
        slice_id="s-oci-1",
        slice_index=2,
        total_slices=4,
        test_nodeids=["tests/unit/test_demo.py::test_it"],
    )
    cmd, provider, worker_id = _build_slice_cmd(
        slice_spec,
        worker_index=2,
        is_container=False,
        container_image=None,
    )
    assert provider == "OCI"
    assert worker_id == "worker-oci-2"
    assert "-m" in cmd


@pytest.mark.asyncio
async def test_execute_slice_container_mocked() -> None:
    """Verify executing slice in container mode returns CONTAINER provider telemetry."""
    slice_spec = TestSliceDispatch(
        slice_id="s-cont-1",
        slice_index=0,
        total_slices=1,
        test_nodeids=["tests/unit/test_demo.py::test_it"],
    )

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"1 passed in 0.05s", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await _execute_slice(
            slice_spec,
            worker_index=0,
            is_free_tier=True,
            is_container=True,
            container_image="hexaqueue-worker:latest",
        )

    assert res.provider == "CONTAINER"
    assert res.worker_id == "worker-container-0"
    assert len(res.outcomes) == 1
    assert res.outcomes[0].outcome == "passed"


@pytest.mark.asyncio
async def test_dispatch_test_run_container_mode() -> None:
    """Verify POST /api/v1/test/runs with container=True propagates CONTAINER provider."""
    app = create_server_app()
    transport = ASGITransport(app=app)
    payload = {
        "session_id": "sess-cont",
        "pool": "container",
        "container": True,
        "container_image": "hexaqueue-worker:latest",
        "free_tier": True,
        "slices": [
            {
                "slice_id": "sc0",
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
        assert data["reports"][0]["provider"] == "CONTAINER"
        assert data["reports"][0]["worker_id"] == "worker-container-0"


def test_build_slice_cmd_with_coverage() -> None:
    """Verify slice command construction appends --cov flags when requested."""
    slice_spec = TestSliceDispatch(
        slice_id="s-cov-0",
        slice_index=0,
        total_slices=1,
        test_nodeids=["tests/unit/test_demo.py::test_it"],
    )
    cmd, provider, worker_id = _build_slice_cmd(
        slice_spec,
        worker_index=0,
        is_container=False,
        container_image=None,
        coverage_sources=["packages/my_pkg/src"],
    )
    is_local = provider == "LOCAL"
    is_worker = worker_id == "worker-local-0"
    has_cov = "--cov=packages/my_pkg/src" in cmd
    has_report = "--cov-report=" in cmd
    has_fail_under = "--cov-fail-under=0" in cmd
    assert is_local is True
    assert is_worker is True
    assert has_cov is True
    assert has_report is True
    assert has_fail_under is True


@pytest.mark.asyncio
async def test_execute_slice_with_coverage_serialization(tmp_path: Path) -> None:
    """Verify executing slice with coverage serializes sqlite database to base64."""
    slice_spec = TestSliceDispatch(
        slice_id="s-cov-1",
        slice_index=0,
        total_slices=1,
        test_nodeids=["tests/unit/test_demo.py::test_it"],
    )

    cov_file = Path(f".coverage.hq.{slice_spec.slice_id}")
    cov_file.write_bytes(b"dummy-sqlite-data")

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"1 passed", b"")
    mock_proc.returncode = 0

    try:
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            res = await _execute_slice(
                slice_spec,
                worker_index=0,
                is_free_tier=True,
                is_container=False,
                container_image=None,
                coverage_sources=["packages/my_pkg"],
            )

        cov_data = res.coverage_data
        has_cov = cov_data is not None and "sqlite_b64" in cov_data
        assert has_cov is True
    finally:
        if cov_file.exists():
            cov_file.unlink()


def test_get_worker_semaphore_dependency() -> None:
    """Verify get_worker_semaphore resolves existing or initializes default on app.state."""
    req = MagicMock()
    req.app.state.worker_semaphore = None
    sem1 = get_worker_semaphore(req)
    assert isinstance(sem1, asyncio.Semaphore)
    sem2 = get_worker_semaphore(req)
    assert sem2 is sem1
