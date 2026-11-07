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
    _cleanup_session_workspace,
    _execute_slice,
    _extract_collateral_workspace,
    _fetch_git_target,
    _prepare_session_workspace,
    get_worker_semaphore,
)


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    """Verify cluster health check endpoint returns 200 OK and capacity metadata."""
    app = create_server_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"
        assert "cores" in data
        assert "provider" in data


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

    with (
        patch(
            "hexaqueue_server.adapters.api.test_runs._prepare_session_workspace",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "hexaqueue_server.adapters.api.test_runs._cleanup_session_workspace",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
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


@pytest.mark.asyncio
async def test_dispatch_test_run_with_worker_pool() -> None:
    """Verify POST /api/v1/test/runs delegates slices to active worker pool."""
    from hexastack_core.infra.container import create_container

    from hexaqueue_core.domain.lease import SliceReportPayload, WorkerRegistration
    from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator

    coord = SliceLeaseCoordinator()
    await coord.register_worker(
        WorkerRegistration(
            worker_id="w-remote-1",
            hostname="remote-1",
            ip_address="10.0.2.50",
            ocpus=4,
            memory_mb=16384,
        )
    )
    container = create_container()
    container.add_instance(coord, declared_class=SliceLeaseCoordinator)
    app = create_server_app(container=container)
    transport = ASGITransport(app=app)

    async def _mock_worker() -> None:
        lease = await coord.lease_slice(worker_id="w-remote-1", timeout_seconds=5.0)
        if lease is not None:
            report = SliceReportPayload(
                lease_id=lease.lease_id,
                slice_id=lease.task.slice_id,
                worker_id="w-remote-1",
                exit_code=0,
                duration_seconds=1.23,
                outcomes=[
                    {
                        "nodeid": lease.task.test_nodeids[0],
                        "outcome": "passed",
                        "duration_seconds": 1.23,
                    }
                ],
            )
            await coord.report_slice_outcome(report)

    worker_task = asyncio.create_task(_mock_worker())
    payload = {
        "session_id": "sess-remote",
        "free_tier": True,
        "slices": [
            {
                "slice_id": "s-rem-0",
                "slice_index": 0,
                "total_slices": 1,
                "test_nodeids": ["tests/test_remote.py::test_fn"],
            }
        ],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/test/runs", json=payload)
        code = resp.status_code
        assert code == 200
        data = resp.json()
        reports = data.get("reports", [])
        reports_len = len(reports)
        assert reports_len == 1
        assert reports[0]["provider"] == "oci_worker_pool"
        assert reports[0]["worker_id"] == "w-remote-1"

    await worker_task


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


@pytest.mark.asyncio
async def test_prepare_and_cleanup_session_workspace_no_git(tmp_path: Path) -> None:
    """Verify _prepare_session_workspace returns None when not in a git repo."""
    res = await _prepare_session_workspace("sess-1", repo_root=tmp_path)
    assert res is None


@pytest.mark.asyncio
async def test_prepare_and_cleanup_session_workspace_mocked(tmp_path: Path) -> None:
    """Verify worktree creation and teardown invoking git subprocess commands."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        workspace = await _prepare_session_workspace(
            session_id="sess-mock",
            git_commit="abc1234",
            repo_root=tmp_path,
        )
        assert workspace is not None
        assert "sess-mock" in str(workspace)

        await _cleanup_session_workspace(workspace, repo_root=tmp_path)


@pytest.mark.asyncio
async def test_fetch_git_target_none() -> None:
    """Verify _fetch_git_target no-ops cleanly when commit and ref are omitted."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        await _fetch_git_target(Path("/fake"), None, None)
        assert not mock_exec.called


@pytest.mark.asyncio
async def test_sync_workspace_and_venv_slice_cmd(tmp_path: Path) -> None:
    """Verify workspace environment sync and .venv/bin/python slice command resolution."""
    from hexaqueue_server.adapters.api.test_runs import _sync_workspace_environment

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n", encoding="utf-8"
    )
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await _sync_workspace_environment(tmp_path)
        called = mock_exec.called
        assert called is True

    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_python = venv_bin / "python"
    venv_python.write_text("#!/bin/sh\n", encoding="utf-8")

    slice_spec = TestSliceDispatch(
        slice_id="s-venv-0",
        slice_index=0,
        total_slices=1,
        test_nodeids=["tests/unit/test_demo.py::test_it"],
    )
    cmd, _, _ = _build_slice_cmd(
        slice_spec,
        worker_index=0,
        is_container=False,
        container_image=None,
        workspace_dir=tmp_path,
    )
    first_arg = cmd[0]
    assert first_arg == str(venv_python)


@pytest.mark.asyncio
async def test_extract_collateral_workspace_local(tmp_path: Path) -> None:
    """Verify local collateral tarball is extracted successfully into workspace."""
    import tarfile

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    sample_file = src_dir / "sample.py"
    sample_file.write_text("print('hello')\n", encoding="utf-8")

    tar_path = tmp_path / "bundle.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(sample_file, arcname="sample.py")

    bundle_mock = MagicMock()
    bundle_mock.active_uri = str(tar_path)
    bundle_mock.staging_uri = None

    collateral_svc = AsyncMock()
    collateral_svc.get_bundle.return_value = bundle_mock

    target_dir = tmp_path / "target_workspace"
    success = await _extract_collateral_workspace("col-1", collateral_svc, target_dir)
    assert success is True
    extracted_file = target_dir / "sample.py"
    assert extracted_file.exists()


@pytest.mark.asyncio
async def test_extract_collateral_workspace_remote_par(tmp_path: Path) -> None:
    """Verify remote HTTPS PAR collateral tarball is downloaded and unpacked."""
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"def test_remote(): pass\n"
        tarinfo = tarfile.TarInfo(name="test_remote.py")
        tarinfo.size = len(data)
        tar.addfile(tarinfo, io.BytesIO(data))
    tar_bytes = buf.getvalue()

    bundle_mock = MagicMock()
    bundle_mock.active_uri = None
    bundle_mock.staging_uri = None

    collateral_svc = AsyncMock()
    collateral_svc.get_bundle.return_value = bundle_mock
    collateral_svc.get_download_url.return_value = (
        "https://objectstorage.us-phoenix-1.oraclecloud.com/p/test/tar.gz"
    )

    class MockHttpResp:
        def __init__(self, data: bytes) -> None:
            self._io = io.BytesIO(data)

        def read(self, *args, **kwargs) -> bytes:
            return self._io.read(*args, **kwargs)

        def __enter__(self) -> "MockHttpResp":
            return self

        def __exit__(self, *args) -> None:
            pass

    target_dir = tmp_path / "remote_workspace"
    with patch("urllib.request.urlopen", return_value=MockHttpResp(tar_bytes)):
        success = await _extract_collateral_workspace(
            "col-2", collateral_svc, target_dir
        )
        assert success is True
        extracted_file = target_dir / "test_remote.py"
        assert extracted_file.exists()


@pytest.mark.asyncio
async def test_extract_collateral_workspace_failure(tmp_path: Path) -> None:
    """Verify failure to retrieve collateral returns False gracefully."""
    collateral_svc = AsyncMock()
    collateral_svc.get_bundle.side_effect = RuntimeError("Not found")

    target_dir = tmp_path / "fail_workspace"
    success = await _extract_collateral_workspace(
        "col-fail", collateral_svc, target_dir
    )
    assert success is False
