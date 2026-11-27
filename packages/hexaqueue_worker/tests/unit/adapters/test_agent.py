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
    _build_task_env,
    _find_uv_binary,
    _resolve_command_invocation,
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
    mock_proc.stdout.readline = AsyncMock(side_effect=[b"1 passed in 0.05s\n", b""])
    mock_proc.stderr.readline = AsyncMock(side_effect=[b""])
    mock_proc.wait = AsyncMock(return_value=0)
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
    mock_proc.stdout.readline = AsyncMock(side_effect=[b"1 passed in 0.02s\n", b""])
    mock_proc.stderr.readline = AsyncMock(side_effect=[b""])
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0

    with (
        patch("shutil.which", return_value="/custom/bin/uv"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
    ):
        report = await agent.execute_slice(lease)
        assert report.slice_id == "sl-uv"
        assert report.exit_code == 0
        call_args = mock_exec.call_args[0]
        ws_str = str(workspace)
        expected_prefix = (
            "/custom/bin/uv",
            "run",
            "--project",
            ws_str,
            "--all-packages",
            "--all-extras",
            "--all-groups",
            "pytest",
        )
        assert call_args[:8] == expected_prefix
        assert "-p" in call_args
        assert "no:hexaqueue" in call_args
        no_hq_idx = call_args.index("no:hexaqueue")
        prev_flag = call_args[no_hq_idx - 1]
        assert prev_flag == "-p"


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


@pytest.mark.asyncio
async def test_worker_agent_strips_internal_env_from_pytest_slice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify worker control-plane env vars do not leak into pytest slice subprocesses."""
    monkeypatch.setenv("HEXAQUEUE_CONTROLLER_URL", "http://live-controller:8001")
    monkeypatch.setenv("HEXAQUEUE_URL", "http://live-controller:8000")
    monkeypatch.setenv("HEXAQUEUE_JOIN_TOKEN", "secret-join-token")

    cfg = WorkerAgentConfig(worker_id="w-env-pytest", scratch_dir=tmp_path)
    agent = WorkerAgent(cfg)
    lease = _make_dummy_lease("sl-env")

    mock_proc = AsyncMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=[b""])
    mock_proc.stderr.readline = AsyncMock(side_effect=[b""])
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        report = await agent.execute_slice(lease)

    exit_code = report.exit_code
    assert exit_code == 0
    call_args = mock_exec.call_args[0]
    assert "-p" in call_args
    assert "no:hexaqueue" in call_args
    call_env = mock_exec.call_args.kwargs["env"]
    has_ctrl_url = "HEXAQUEUE_CONTROLLER_URL" in call_env
    has_hq_url = "HEXAQUEUE_URL" in call_env
    has_join_token = "HEXAQUEUE_JOIN_TOKEN" in call_env
    assert has_ctrl_url is False
    assert has_hq_url is False
    assert has_join_token is False


@pytest.mark.asyncio
async def test_worker_agent_command_task_strips_internal_env_but_honors_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify command tasks strip inherited worker env but keep explicit task overrides."""
    monkeypatch.setenv("HEXAQUEUE_CONTROLLER_URL", "http://live-controller:8001")
    monkeypatch.setenv("HEXAQUEUE_URL", "http://live-controller:8000")
    monkeypatch.setenv("HEXAQUEUE_JOIN_TOKEN", "secret-join-token")

    cfg = WorkerAgentConfig(worker_id="w-env-cmd", scratch_dir=tmp_path)
    agent = WorkerAgent(cfg)
    now = datetime.now(UTC)
    task = SliceTaskDescriptor(
        session_id="run-env-cmd",
        slice_id="job-env-1",
        command="python",
        args=["-V"],
        env={"HEXAQUEUE_CONTROLLER_URL": "http://explicit-task-target:9000"},
        task_type="job",
    )
    lease = SliceLease(
        task=task,
        worker_id="w-env-cmd",
        state=SliceLeaseState.LEASED,
        leased_at=now,
        expires_at=now + timedelta(seconds=60),
    )

    mock_proc = AsyncMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=[b"Python 3.13\n", b""])
    mock_proc.stderr.readline = AsyncMock(side_effect=[b""])
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        report = await agent.execute_slice(lease)

    exit_code = report.exit_code
    assert exit_code == 0
    call_env = mock_exec.call_args.kwargs["env"]
    ctrl_val = call_env.get("HEXAQUEUE_CONTROLLER_URL")
    has_hq_url = "HEXAQUEUE_URL" in call_env
    has_join_token = "HEXAQUEUE_JOIN_TOKEN" in call_env
    assert ctrl_val == "http://explicit-task-target:9000"
    assert has_hq_url is False
    assert has_join_token is False


@pytest.mark.asyncio
async def test_worker_agent_execute_command_task_single_string_and_shell(
    tmp_path: Path,
) -> None:
    """Verify single-string commands with args=[] and shell metacharacters execute."""
    cfg = WorkerAgentConfig(worker_id="w-shell", scratch_dir=tmp_path)
    agent = WorkerAgent(cfg)
    now = datetime.now(UTC)

    split_task = SliceTaskDescriptor(
        session_id="run-split",
        slice_id="job-split",
        command="echo 'Hello World'",
        args=[],
        task_type="job",
    )
    split_lease = SliceLease(
        task=split_task,
        worker_id="w-shell",
        state=SliceLeaseState.LEASED,
        leased_at=now,
        expires_at=now + timedelta(seconds=60),
    )
    split_report = await agent.execute_slice(split_lease)
    split_code = split_report.exit_code
    split_stdout = split_report.stdout or ""
    assert split_code == 0
    assert "Hello World" in split_stdout

    shell_task = SliceTaskDescriptor(
        session_id="run-shell",
        slice_id="job-shell",
        command="echo alpha && echo beta",
        args=[],
        task_type="job",
    )
    shell_lease = SliceLease(
        task=shell_task,
        worker_id="w-shell",
        state=SliceLeaseState.LEASED,
        leased_at=now,
        expires_at=now + timedelta(seconds=60),
    )
    shell_report = await agent.execute_slice(shell_lease)
    shell_code = shell_report.exit_code
    shell_stdout = shell_report.stdout or ""
    assert shell_code == 0
    assert "alpha" in shell_stdout
    assert "beta" in shell_stdout


@pytest.mark.asyncio
async def test_worker_agent_execute_slice_exception_does_not_raise_unbound_inline_cov(
    tmp_path: Path,
) -> None:
    """Verify command spawn failures return failed SliceReportPayload without UnboundLocalError."""
    cfg = WorkerAgentConfig(worker_id="w-unbound", scratch_dir=tmp_path)
    agent = WorkerAgent(cfg)
    now = datetime.now(UTC)
    task = SliceTaskDescriptor(
        session_id="run-err",
        slice_id="job-err",
        command="nonexistent-cmd",
        task_type="job",
    )
    lease = SliceLease(
        task=task,
        worker_id="w-unbound",
        state=SliceLeaseState.LEASED,
        leased_at=now,
        expires_at=now + timedelta(seconds=60),
    )

    with patch.object(
        agent, "_run_command_task", side_effect=FileNotFoundError("boom")
    ):
        report = await agent.execute_slice(lease)

    exit_code = report.exit_code
    cov_data = report.coverage_data
    error_msg = report.error_message or ""
    assert exit_code == 1
    assert cov_data is None
    assert "boom" in error_msg


@pytest.mark.asyncio
async def test_worker_agent_run_step_reports_unexpected_execute_slice_error() -> None:
    """Verify run_step catches unexpected execute_slice errors and reports failure."""
    agent = WorkerAgent(WorkerAgentConfig(worker_id="w-step-err"))
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    dummy_lease = _make_dummy_lease("sl-crash")

    with (
        patch.object(agent, "lease_slice", return_value=dummy_lease),
        patch.object(
            agent, "execute_slice", side_effect=RuntimeError("unexpected crash")
        ),
        patch.object(agent, "report_slice", return_value=True) as mock_report,
    ):
        processed = await agent.run_step(mock_client)

    assert processed is True
    active_len = len(agent._active_leases)
    assert active_len == 0
    reported_payload = mock_report.call_args[0][1]
    assert reported_payload.exit_code == 1
    assert "unexpected crash" in (reported_payload.error_message or "")


@pytest.mark.asyncio
async def test_worker_agent_heartbeat_reregisters_on_404() -> None:
    """Verify heartbeat self-heals by re-registering and retrying after HTTP 404."""
    agent = WorkerAgent(WorkerAgentConfig(worker_id="w-reheal"))
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [
        MagicMock(status_code=404),
        MagicMock(status_code=201),
        MagicMock(status_code=200),
    ]

    hb_ok = await agent.heartbeat(mock_client)
    assert hb_ok is True

    call_count = mock_client.post.call_count
    assert call_count == 3

    second_url = mock_client.post.call_args_list[1].args[0]
    third_url = mock_client.post.call_args_list[2].args[0]
    assert second_url.endswith("/worker/register")
    assert third_url.endswith("/worker/w-reheal/heartbeat")


def test_worker_agent_from_env_parses_slice_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify WorkerAgentConfig.from_env parses HEXAQUEUE_SLICE_TIMEOUT_SECONDS."""
    monkeypatch.setenv("HEXAQUEUE_SLICE_TIMEOUT_SECONDS", "123.5")
    cfg = WorkerAgentConfig.from_env()
    assert cfg.slice_timeout_seconds == 123.5


@pytest.mark.asyncio
async def test_worker_agent_heartbeat_terminates_cancelled_lease_subprocess(
    tmp_path: Path,
) -> None:
    """Verify heartbeat cancelled_lease_ids terminates active child process group."""
    import asyncio

    cfg = WorkerAgentConfig(worker_id="w-cancel-proc", scratch_dir=tmp_path)
    agent = WorkerAgent(cfg)
    now = datetime.now(UTC)
    task = SliceTaskDescriptor(
        session_id="run-cancel-proc",
        slice_id="job-cancel-proc",
        command=sys.executable,
        args=["-c", "import time; time.sleep(30)"],
        task_type="job",
    )
    lease = SliceLease(
        task=task,
        worker_id="w-cancel-proc",
        state=SliceLeaseState.LEASED,
        leased_at=now,
        expires_at=now + timedelta(seconds=60),
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    hb_resp = MagicMock(status_code=200)
    hb_resp.json.return_value = {
        "status": "ok",
        "cancelled_lease_ids": [lease.lease_id],
    }
    mock_client.post.return_value = hb_resp

    async def _trigger_cancel_hb() -> None:
        for _ in range(50):
            if lease.lease_id in agent._active_procs:
                hb_ok = await agent.heartbeat(mock_client)
                assert hb_ok is True
                return
            await asyncio.sleep(0.05)

    hb_task = asyncio.create_task(_trigger_cancel_hb())
    report = await agent.execute_slice(lease)
    await hb_task

    exit_code = report.exit_code
    err_msg = (report.error_message or "").lower()
    assert exit_code == 130
    assert "cancelled" in err_msg


@pytest.mark.asyncio
async def test_worker_agent_enforces_slice_timeout_seconds(tmp_path: Path) -> None:
    """Verify slice_timeout_seconds terminates hung subprocess with exit code 124."""
    cfg = WorkerAgentConfig(
        worker_id="w-slice-to",
        scratch_dir=tmp_path,
        slice_timeout_seconds=0.25,
    )
    agent = WorkerAgent(cfg)
    now = datetime.now(UTC)
    task = SliceTaskDescriptor(
        session_id="run-slice-to",
        slice_id="job-slice-to",
        command=sys.executable,
        args=["-c", "import time; time.sleep(30)"],
        task_type="job",
    )
    lease = SliceLease(
        task=task,
        worker_id="w-slice-to",
        state=SliceLeaseState.LEASED,
        leased_at=now,
        expires_at=now + timedelta(seconds=60),
    )

    report = await agent.execute_slice(lease)
    exit_code = report.exit_code
    stderr_text = (report.stderr or "").lower()
    assert exit_code == 124
    assert "exceeded worker timeout" in stderr_text


def test_resolve_command_invocation_uv_project_syncs_workspace_extras(
    tmp_path: Path,
) -> None:
    """Verify command tasks include workspace/extra/group sync flags under uv projects."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test-pkg'\n")

    with patch("shutil.which", return_value="/custom/bin/uv"):
        use_shell, cmd = _resolve_command_invocation("pytest", ["-q"], tmp_path)

    expected = [
        "/custom/bin/uv",
        "run",
        "--project",
        str(tmp_path),
        "--all-packages",
        "--all-extras",
        "--all-groups",
        "pytest",
        "-q",
    ]
    assert use_shell is False
    assert cmd == expected


def test_find_uv_binary_falls_back_to_home_local_bin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify _find_uv_binary falls back to ~/.local/bin/uv when not on PATH."""
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    uv_bin = local_bin / "uv"
    uv_bin.write_text("#!/bin/sh\nexit 0\n")
    uv_bin.chmod(0o700)

    monkeypatch.setattr("shutil.which", lambda _cmd: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    resolved = _find_uv_binary()
    assert resolved == str(uv_bin)


def test_build_task_env_strips_worker_venv_and_adds_uv_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify _build_task_env isolates child env from worker virtualenv and exposes uv."""
    worker_venv = tmp_path / "daemon-venv"
    worker_venv_bin = worker_venv / "bin"
    worker_venv_bin.mkdir(parents=True)
    uv_dir = tmp_path / "custom" / ".local" / "bin"
    uv_bin = uv_dir / "uv"

    monkeypatch.setenv("VIRTUAL_ENV", str(worker_venv))
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(worker_venv))
    monkeypatch.setenv("UV_PYTHON", "3.13")
    monkeypatch.setenv("PYTHONHOME", str(worker_venv))
    monkeypatch.setenv("PATH", f"{worker_venv_bin}{os.pathsep}/usr/bin")
    monkeypatch.setattr(
        "hexaqueue_worker.adapters.agent._find_uv_binary",
        lambda: str(uv_bin),
    )

    task_env = _build_task_env(tmp_path)
    for var in (
        "VIRTUAL_ENV",
        "UV_RUN_RECURSION_DEPTH",
        "UV_PROJECT_ENVIRONMENT",
        "UV_PYTHON",
        "PYTHONHOME",
    ):
        assert var not in task_env

    path_entries = task_env["PATH"].split(os.pathsep)
    assert str(worker_venv_bin) not in path_entries
    assert "/usr/bin" in path_entries
    assert str(uv_dir) in path_entries
