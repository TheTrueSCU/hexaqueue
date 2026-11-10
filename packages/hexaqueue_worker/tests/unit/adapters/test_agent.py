"""Unit tests for the autonomous compute worker daemon agent.

Notes/Architectural Intent:
    Validates WorkerAgent configuration loading from environment variables,
    lifecycle registration with central coordinator, heartbeat lease renewal,
    pull-based leasing, collateral unpacking, execution error isolation,
    coverage artifact uploading, and graceful scale-to-zero idle termination.
    Enforces side-effect free assertions to prevent CodeQL warnings.
"""

from __future__ import annotations

import io
import os
import sys
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from hexaqueue_core.domain.lease import (
    SliceLease,
    SliceLeaseState,
    SliceReportPayload,
    SliceTaskDescriptor,
)
from hexaqueue_worker.adapters.agent import (
    WorkerAgent,
    WorkerAgentConfig,
    main,
)


def _make_dummy_tarball() -> bytes:
    """Generate in-memory tarball for collateral extraction tests."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"print('hello from slice')\n"
        ti = tarfile.TarInfo(name="test_script.py")
        ti.size = len(data)
        tar.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _make_dummy_lease(
    slice_id: str = "sl-1",
    collateral_url: str | None = None,
    coverage_upload_url: str | None = None,
) -> SliceLease:
    """Generate sample SliceLease instance for unit testing."""
    now = datetime.now(UTC)
    task = SliceTaskDescriptor(
        session_id="sess-test",
        slice_id=slice_id,
        slice_index=0,
        total_slices=1,
        test_nodeids=["tests/test_demo.py::test_alpha"],
        collateral_download_url=collateral_url,
        coverage_upload_url=coverage_upload_url,
        coverage_sources=["mypkg"] if coverage_upload_url else [],
    )
    return SliceLease(
        task=task,
        worker_id="w-test",
        state=SliceLeaseState.LEASED,
        leased_at=now,
        expires_at=now + timedelta(seconds=60),
    )


def test_worker_agent_config_defaults() -> None:
    """Verify default configuration attributes of WorkerAgentConfig."""
    cfg = WorkerAgentConfig()
    assert cfg.controller_url == "http://localhost:8001"
    assert cfg.join_token is None
    assert cfg.ocpus == 1
    assert cfg.memory_mb == 6144
    assert cfg.idle_timeout_seconds == 180.0
    assert cfg.scratch_dir is None
    worker_id_len = len(cfg.worker_id)
    assert worker_id_len > 0


def test_worker_agent_config_from_env() -> None:
    """Verify loading WorkerAgentConfig from environment variable overrides."""
    env = {
        "HEXAQUEUE_CONTROLLER_URL": "http://10.0.1.101:8001/",
        "HEXAQUEUE_JOIN_TOKEN": "cluster-secret-key",
        "HEXAQUEUE_WORKER_ID": "worker-custom-99",
        "HEXAQUEUE_WORKER_HOSTNAME": "worker-99.internal",
        "HEXAQUEUE_WORKER_IP": "10.0.2.105",
        "HEXAQUEUE_WORKER_OCPUS": "4",
        "HEXAQUEUE_WORKER_MEMORY_MB": "24576",
        "HEXAQUEUE_AGENT_IDLE_TIMEOUT": "60.0",
        "HEXAQUEUE_AGENT_SCRATCH_DIR": "/tmp/custom-scratch",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = WorkerAgentConfig.from_env()
        assert cfg.controller_url == "http://10.0.1.101:8001"
        assert cfg.join_token == "cluster-secret-key"
        assert cfg.worker_id == "worker-custom-99"
        assert cfg.hostname == "worker-99.internal"
        assert cfg.ip_address == "10.0.2.105"
        assert cfg.ocpus == 4
        assert cfg.memory_mb == 24576
        assert cfg.idle_timeout_seconds == 60.0
        assert cfg.scratch_dir == Path("/tmp/custom-scratch")


def test_worker_agent_headers() -> None:
    """Verify authorization headers with and without join token."""
    cfg_no_token = WorkerAgentConfig(join_token=None)
    agent1 = WorkerAgent(cfg_no_token)
    h1 = agent1._headers()
    assert "x-hexaqueue-join-token" not in h1

    cfg_token = WorkerAgentConfig(join_token="secret-abc")
    agent2 = WorkerAgent(cfg_token)
    h2 = agent2._headers()
    assert h2.get("x-hexaqueue-join-token") == "secret-abc"


@pytest.mark.asyncio
async def test_worker_agent_register() -> None:
    """Verify worker registration HTTP contract and error handling."""
    agent = WorkerAgent(WorkerAgentConfig(worker_id="w-reg"))
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    # Success case (201)
    mock_resp = MagicMock(status_code=201)
    mock_client.post.return_value = mock_resp
    registered = await agent.register(mock_client)
    assert registered is True

    # Failure case (500)
    mock_resp.status_code = 500
    failed = await agent.register(mock_client)
    assert failed is False

    # Exception case
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")
    exc_failed = await agent.register(mock_client)
    assert exc_failed is False


@pytest.mark.asyncio
async def test_worker_agent_heartbeat() -> None:
    """Verify worker heartbeat reporting active lease set."""
    agent = WorkerAgent(WorkerAgentConfig(worker_id="w-hb"))
    agent._active_leases.add("lease-alpha")
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    # Success (200)
    mock_resp = MagicMock(status_code=200)
    mock_client.post.return_value = mock_resp
    hb_ok = await agent.heartbeat(mock_client)
    assert hb_ok is True

    # Error
    mock_resp.status_code = 404
    hb_fail = await agent.heartbeat(mock_client)
    assert hb_fail is False


@pytest.mark.asyncio
async def test_worker_agent_lease_slice() -> None:
    """Verify long-polling lease acquisition."""
    agent = WorkerAgent(WorkerAgentConfig(worker_id="w-lease"))
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    # Empty queue (204)
    mock_204 = MagicMock(status_code=204, content=b"")
    mock_client.post.return_value = mock_204
    lease_none = await agent.lease_slice(mock_client)
    assert lease_none is None

    # Granted lease (200)
    dummy = _make_dummy_lease("sl-granted")
    mock_200 = MagicMock(
        status_code=200,
        content=b"{}",
        json=lambda: dummy.model_dump(mode="json"),
    )
    mock_client.post.return_value = mock_200
    lease_res = await agent.lease_slice(mock_client)
    assert lease_res is not None
    assert lease_res.task.slice_id == "sl-granted"


@pytest.mark.asyncio
async def test_worker_agent_unpack_collateral(tmp_path: Path) -> None:
    """Verify collateral tarball download and extraction into workspace."""
    agent = WorkerAgent(WorkerAgentConfig())
    workspace = tmp_path / "workspace"
    tar_bytes = _make_dummy_tarball()

    mock_resp = MagicMock()
    mock_resp.read.side_effect = [tar_bytes, b""]
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = await agent._unpack_collateral("https://storage/tarball", workspace)
        assert res is True
        target_file = workspace / "test_script.py"
        exists = target_file.exists()
        assert exists is True


@pytest.mark.asyncio
async def test_worker_agent_upload_coverage(tmp_path: Path) -> None:
    """Verify .coverage file upload via presigned PUT."""
    agent = WorkerAgent(WorkerAgentConfig())
    cov_path = tmp_path / ".coverage"

    # File does not exist
    res_missing = await agent._upload_coverage("https://upload-par", cov_path)
    assert res_missing is False

    # File exists and uploaded successfully
    cov_path.write_bytes(b"SQLite format 3\x00coverage-data")
    mock_resp = MagicMock(status=200)
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res_ok = await agent._upload_coverage("https://upload-par", cov_path)
        assert res_ok is True


@pytest.mark.asyncio
async def test_worker_agent_execute_slice_success(tmp_path: Path) -> None:
    """Verify successful slice execution with mocked subprocess."""
    cfg = WorkerAgentConfig(worker_id="w-exec", scratch_dir=tmp_path)
    agent = WorkerAgent(cfg)
    lease = _make_dummy_lease("sl-ok")

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"1 passed in 0.05s", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        report = await agent.execute_slice(lease)
        assert report.slice_id == "sl-ok"
        assert report.worker_id == "w-exec"
        assert report.exit_code == 0
        outcomes_len = len(report.outcomes)
        assert outcomes_len == 1
        assert report.outcomes[0]["outcome"] == "passed"


@pytest.mark.asyncio
async def test_worker_agent_execute_slice_uv_project(tmp_path: Path) -> None:
    """Verify slice execution uses uv run --project when pyproject.toml is present."""
    cfg = WorkerAgentConfig(worker_id="w-uv", scratch_dir=tmp_path)
    agent = WorkerAgent(cfg)
    lease = _make_dummy_lease("sl-uv")

    workspace = tmp_path / "sess-test"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "pyproject.toml").write_text("[project]\nname = 'test-pkg'\n")

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"1 passed in 0.02s", b"")
    mock_proc.returncode = 0

    with (
        patch("shutil.which", return_value="/custom/bin/uv"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
    ):
        report = await agent.execute_slice(lease)
        assert report.slice_id == "sl-uv"
        assert report.exit_code == 0
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "/custom/bin/uv"
        assert call_args[1] == "run"
        assert call_args[2] == "--project"
        assert call_args[3] == str(workspace)
        assert call_args[4] == "pytest"


@pytest.mark.asyncio
async def test_worker_agent_execute_slice_collateral_failure(tmp_path: Path) -> None:
    """Verify execution reports failure when collateral download fails."""
    cfg = WorkerAgentConfig(worker_id="w-err", scratch_dir=tmp_path)
    agent = WorkerAgent(cfg)
    lease = _make_dummy_lease("sl-bad", collateral_url="https://bad-url")

    with patch.object(agent, "_unpack_collateral", return_value=False):
        report = await agent.execute_slice(lease)
        assert report.slice_id == "sl-bad"
        assert report.exit_code == 1
        assert "Failed to download" in (report.error_message or "")


@pytest.mark.asyncio
async def test_worker_agent_report_slice() -> None:
    """Verify slice outcome report transmission to coordinator."""
    agent = WorkerAgent(WorkerAgentConfig(worker_id="w-rep"))
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    report = SliceReportPayload(
        lease_id="lease-xyz",
        slice_id="sl-xyz",
        worker_id="w-rep",
        exit_code=0,
        duration_seconds=1.5,
    )

    mock_resp = MagicMock(status_code=200)
    mock_client.post.return_value = mock_resp
    reported = await agent.report_slice(mock_client, report)
    assert reported is True


@pytest.mark.asyncio
async def test_worker_agent_run_step() -> None:
    """Verify complete run_step cycle when lease is available."""
    agent = WorkerAgent(WorkerAgentConfig(worker_id="w-step"))
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    dummy_lease = _make_dummy_lease("sl-step")
    dummy_report = SliceReportPayload(
        lease_id=dummy_lease.lease_id,
        slice_id=dummy_lease.task.slice_id,
        worker_id="w-step",
        exit_code=0,
        duration_seconds=0.1,
    )

    with (
        patch.object(agent, "lease_slice", return_value=dummy_lease),
        patch.object(agent, "execute_slice", return_value=dummy_report),
        patch.object(agent, "report_slice", return_value=True),
    ):
        processed = await agent.run_step(mock_client)
        assert processed is True
        active_len = len(agent._active_leases)
        assert active_len == 0


@pytest.mark.asyncio
async def test_worker_agent_run_lifecycle_and_stop() -> None:
    """Verify worker agent lifecycle loop and stop_event behavior."""
    cfg = WorkerAgentConfig(
        worker_id="w-life",
        heartbeat_interval_seconds=0.01,
        poll_timeout_seconds=0.01,
        idle_timeout_seconds=0.05,
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    agent = WorkerAgent(cfg, client=mock_client)

    with (
        patch.object(agent, "register", return_value=True),
        patch.object(agent, "heartbeat", return_value=True),
        patch.object(agent, "run_step", return_value=False),
    ):
        # Let agent run until idle timeout terminates it
        await agent.run()
        stopped = agent._stop_event.is_set()
        assert stopped is False  # Loop exited on idle timeout


@pytest.mark.asyncio
async def test_worker_agent_run_registration_failure() -> None:
    """Verify worker agent raises RuntimeError if registration retries fail."""
    cfg = WorkerAgentConfig(worker_id="w-fail")
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    agent = WorkerAgent(cfg, client=mock_client)

    with (
        patch.object(agent, "register", return_value=False),
        patch("asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(RuntimeError, match="failed to register with coordinator"),
    ):
        await agent.run()


def test_worker_agent_main_entrypoint() -> None:
    """Verify worker agent main entrypoint constructs config and runs agent."""
    with (
        patch("hexaqueue_worker.adapters.agent.asyncio.run") as mock_run,
        patch("hexaqueue_worker.adapters.agent.WorkerAgent") as mock_agent_cls,
    ):
        main()
        call_count = mock_run.call_count
        assert call_count == 1
        agent_inst_count = mock_agent_cls.call_count
        assert agent_inst_count == 1


@pytest.mark.asyncio
async def test_worker_agent_execute_command_task(tmp_path: Path) -> None:
    """Verify worker agent executes arbitrary batch command task."""
    cfg = WorkerAgentConfig(worker_id="w-cmd", scratch_dir=tmp_path)
    agent = WorkerAgent(cfg)
    now = datetime.now(UTC)
    task = SliceTaskDescriptor(
        session_id="run-cmd-test",
        slice_id="job-1",
        command=sys.executable,
        args=["-c", "import os; print(os.environ.get('CUSTOM_VAR', '')); exit(0)"],
        env={"CUSTOM_VAR": "val1"},
        task_type="job",
    )
    lease = SliceLease(
        task=task,
        worker_id="w-cmd",
        state=SliceLeaseState.LEASED,
        leased_at=now,
        expires_at=now + timedelta(seconds=60),
    )
    report = await agent.execute_slice(lease)
    exit_code = report.exit_code
    assert exit_code == 0
    slice_id = report.slice_id
    assert slice_id == "job-1"
    error_msg = report.error_message
    assert error_msg is None
    outcomes_len = len(report.outcomes)
    assert outcomes_len == 1
    outcome_status = report.outcomes[0]["outcome"]
    assert outcome_status == "passed"
    stdout_txt = report.stdout or ""
    assert "val1" in stdout_txt
