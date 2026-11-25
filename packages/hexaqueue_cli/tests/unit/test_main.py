"""Unit tests for root hq CLI entrypoint (hexaqueue_cli.main)."""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.domain.models import ClusterStatsReport
from hexaqueue_cli.domain.session import (
    LocalCliSession,
    get_active_controller_url,
    set_active_controller_url,
    set_default_session,
)
from hexaqueue_cli.main import app
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import RunState
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_worker.domain.pty import PtySessionInfo
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse

runner = CliRunner()


@pytest.fixture
def hermetic_cli_session() -> Generator[LocalCliSession]:
    """Provide an isolated, hermetically sealed CLI session with clean teardown.

    Notes/Architectural Intent:
        Initializes an independent LocalCliSession, sets it as global default for
        CLI command dispatch, and cleanly terminates all PTY subprocesses upon test completion.
    """
    session = LocalCliSession(concurrency=2)
    set_default_session(session)
    set_active_controller_url(None)
    try:
        yield session
    finally:
        for s_id in list(session.pty._sessions.keys()):
            asyncio.run(session.pty.terminate_session(s_id))
        set_default_session(None)
        set_active_controller_url(None)


def test_main_cli_help() -> None:
    """Verify main entrypoint displays help."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "Hexaqueue" in res.stdout
    assert "why" in res.stdout
    assert "explain" in res.stdout
    assert "fairshare" in res.stdout
    assert "jobs" in res.stdout


def test_main_cli_explain_commands_help() -> None:
    """Verify help messages for why, explain, and fairshare commands."""
    res_why = runner.invoke(app, ["why", "--help"])
    assert res_why.exit_code == 0
    assert "why a job is currently waiting" in res_why.stdout

    res_exp = runner.invoke(app, ["explain", "--help"])
    assert res_exp.exit_code == 0
    assert "priority math" in res_exp.stdout

    res_fs = runner.invoke(app, ["fairshare", "--help"])
    assert res_fs.exit_code == 0
    assert "fair-share tree" in res_fs.stdout


def test_main_cli_operator_commands_help() -> None:
    """Verify help messages for operator commands."""
    commands = [
        ("stat", "cluster state and backlog"),
        ("top", "live cluster and queue monitoring"),
        ("nodes", "compute worker nodes telemetry"),
        ("quota", "hierarchical fair-share tree"),
        ("jobs", "registered jobs"),
        ("list", "registered jobs"),
        ("hold", "administrative hold on a pending job"),
        ("release", "administrative hold on a job"),
        ("cancel", "Cancel an active pipeline run or individual job"),
        ("logs", "stdout and stderr logs"),
        ("exec", "interactive PTY session"),
        ("attach", "interactive bash shell"),
    ]
    for cmd, expected in commands:
        res = runner.invoke(app, [cmd, "--help"])
        assert res.exit_code == 0
        assert expected in res.stdout


def test_main_cli_fairshare_run(
    hermetic_cli_session: LocalCliSession,
) -> None:
    """Verify hq fairshare execution in json and table formats."""
    res_json = runner.invoke(app, ["fairshare", "-f", "json"])
    assert res_json.exit_code == 0
    assert '"root"' in res_json.stdout

    res_tbl = runner.invoke(app, ["fairshare"])
    assert res_tbl.exit_code == 0
    assert "Root Hierarchy" in res_tbl.stdout


def test_main_cli_stat_and_nodes_and_quota(
    hermetic_cli_session: LocalCliSession,
) -> None:
    """Verify hq stat, hq nodes, and hq quota execution."""
    res_stat = runner.invoke(app, ["stat"])
    assert res_stat.exit_code == 0
    assert "Hexaqueue Cluster Status" in res_stat.stdout

    res_stat_json = runner.invoke(app, ["stat", "-f", "json"])
    assert res_stat_json.exit_code == 0
    assert '"total_jobs"' in res_stat_json.stdout

    res_nodes = runner.invoke(app, ["nodes"])
    assert res_nodes.exit_code == 0
    assert "Compute Nodes Telemetry" in res_nodes.stdout

    res_nodes_json = runner.invoke(app, ["nodes", "-f", "json"])
    assert res_nodes_json.exit_code == 0
    assert '"worker_id"' in res_nodes_json.stdout

    res_quota = runner.invoke(app, ["quota"])
    assert res_quota.exit_code == 0
    assert "Root Hierarchy" in res_quota.stdout


def test_main_cli_top_once(
    hermetic_cli_session: LocalCliSession,
) -> None:
    """Verify hq top --once static dashboard output."""
    res = runner.invoke(app, ["top", "--once"])
    assert res.exit_code == 0
    assert "Hexaqueue Cluster Summary" in res.stdout
    assert "Worker Nodes" in res.stdout
    assert "Active & Queued Jobs" in res.stdout


def test_main_cli_job_lifecycle_commands(
    hermetic_cli_session: LocalCliSession,
) -> None:
    """Verify job lifecycle, logs, exec, attach, status, and explainability commands."""
    session = hermetic_cli_session
    run = RunSpec(id="run-main-test", name="Main Test")
    job = JobSpec(id="job-main-test", run_id=run.id, name="job-m", command="echo hello")
    submission = RunSubmission(run_spec=run, jobs=[job])
    asyncio.run(session.controller.submit_run(submission))

    # Test jobs and list alias
    res_jobs = runner.invoke(app, ["jobs", "-f", "json"])
    assert res_jobs.exit_code == 0
    listed_jobs = json.loads(res_jobs.stdout)
    assert [item["id"] for item in listed_jobs] == ["job-main-test"]

    res_list_alias = runner.invoke(
        app, ["list", "--run-id", "run-main-test", "-f", "table"]
    )
    assert res_list_alias.exit_code == 0
    assert "job-main-test" in res_list_alias.stdout

    # Test hold
    res_hold = runner.invoke(app, ["hold", job.id])
    assert res_hold.exit_code == 0
    assert "placed on administrative hold" in res_hold.stdout

    # Test release
    res_release = runner.invoke(app, ["release", job.id])
    assert res_release.exit_code == 0
    assert "released from hold" in res_release.stdout

    # Test logs without logs
    res_no_logs = runner.invoke(app, ["logs", "non-existent-job"])
    assert res_no_logs.exit_code == 0
    assert "No logs recorded" in res_no_logs.stdout

    # Test logs with recorded log
    asyncio.run(
        session.log_stream.write_log(
            LogChunk(job_id=job.id, content="log line from job\n", offset=0)
        )
    )
    res_logs = runner.invoke(app, ["logs", job.id])
    assert res_logs.exit_code == 0
    assert "log line from job" in res_logs.stdout

    # Test exec and attach with mocked PTY session
    mock_session_info = PtySessionInfo(
        session_id="pty-test-123",
        job_id=job.id,
        user_id="default",
        pid=9999,
    )
    with patch(
        "hexaqueue_cli.adapters.local.LocalClientAdapter.create_pty_session",
        new=AsyncMock(return_value=mock_session_info),
    ):
        res_exec = runner.invoke(app, ["exec", job.id, "echo", "test"])
        assert res_exec.exit_code == 0
        assert "Attached PTY session" in res_exec.stdout

        res_attach = runner.invoke(app, ["attach", job.id])
        assert res_attach.exit_code == 0
        assert "Attached shell session" in res_attach.stdout

    # Test cancel by job id
    res_cancel_job = runner.invoke(app, ["cancel", job.id])
    assert res_cancel_job.exit_code == 0
    assert f"Job '{job.id}' cancelled" in res_cancel_job.stdout

    # Test cancel by run id
    res_cancel_run = runner.invoke(app, ["cancel", run.id])
    assert res_cancel_run.exit_code == 0
    assert f"Run '{run.id}' cancelled" in res_cancel_run.stdout

    # Test status for run and job
    res_status_run = runner.invoke(app, ["status", run.id])
    assert res_status_run.exit_code == 0
    res_status_job = runner.invoke(app, ["status", job.id])
    assert res_status_job.exit_code == 0

    # Test why and explain
    res_why = runner.invoke(app, ["why", job.id])
    assert res_why.exit_code == 0
    res_explain = runner.invoke(app, ["explain", job.id])
    assert res_explain.exit_code == 0

    # Test logs with follow and tail
    async def _mock_stream(*args: object, **kwargs: object) -> AsyncIterator[LogChunk]:
        yield LogChunk(
            job_id="job-stream-test",
            content="stream stderr line\n",
            offset=0,
            stream="stderr",
        )

    with patch(
        "hexaqueue_cli.adapters.local.LocalClientAdapter.stream_logs",
        side_effect=_mock_stream,
    ):
        res_follow = runner.invoke(app, ["logs", "-f", "job-stream-test"])
        assert res_follow.exit_code == 0
        assert "stderr" in res_follow.stdout

    res_tail = runner.invoke(app, ["logs", job.id, "-n", "1"])
    assert res_tail.exit_code == 0
    assert "log line from job" in res_tail.stdout

    res_url = runner.invoke(app, ["logs", job.id, "--url"])
    assert res_url.exit_code == 0
    assert "stdout_stderr.log" in res_url.stdout


def test_main_cli_error_paths(
    hermetic_cli_session: LocalCliSession,
) -> None:
    """Verify CLI error paths return exit code 1."""
    res_status_err = runner.invoke(app, ["status", "non-existent-xyz"])
    assert res_status_err.exit_code == 1

    res_cancel_err = runner.invoke(app, ["cancel", "non-existent-xyz"])
    assert res_cancel_err.exit_code == 1

    res_hold_err = runner.invoke(app, ["hold", "non-existent-xyz"])
    assert res_hold_err.exit_code == 1

    res_release_err = runner.invoke(app, ["release", "non-existent-xyz"])
    assert res_release_err.exit_code == 1

    res_why_err = runner.invoke(app, ["why", "non-existent-xyz"])
    assert res_why_err.exit_code == 1

    res_explain_err = runner.invoke(app, ["explain", "non-existent-xyz"])
    assert res_explain_err.exit_code == 1


def test_main_cli_root_url_callback_and_reset(
    hermetic_cli_session: LocalCliSession,
) -> None:
    """Verify root --url propagates to commands and resets on next invocation."""
    observed_urls: list[str | None] = []
    real_cls = LocalClientAdapter

    def fake_adapter(
        session: LocalCliSession | None = None,
        *,
        controller_url: str | None = None,
        admin_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> LocalClientAdapter:
        observed_urls.append(controller_url or get_active_controller_url())
        return real_cls(session=hermetic_cli_session)

    with patch("hexaqueue_cli.main.LocalClientAdapter", side_effect=fake_adapter):
        res_remote = runner.invoke(app, ["--url", "http://root-ctrl:8000", "stat"])
        assert res_remote.exit_code == 0

        res_local = runner.invoke(app, ["stat"])
        assert res_local.exit_code == 0

    assert observed_urls == ["http://root-ctrl:8000", None]
    assert get_active_controller_url() is None


def test_main_cli_remote_e2e_mock_transport(
    hermetic_cli_session: LocalCliSession,
) -> None:
    """Verify full CliRunner -> LocalClientAdapter -> HttpAdapters -> MockTransport flow."""
    now = datetime.now(UTC)
    payload = b"e2e-bundle"
    digest = hashlib.sha256(payload).hexdigest()
    bundle = CollateralBundle(
        id="col-e2e-1",
        job_id="alice",
        owner="alice",
        filename="e2e.tar.gz",
        size_bytes=len(payload),
        sha256_checksum=digest,
        tier=CollateralTier.TEMPORARY,
        kind=CollateralKind.BUNDLE,
        state=CollateralState.APPROVED,
        staging_uri="s3://bucket/staging/col-e2e-1",
        active_uri="s3://bucket/cas/col-e2e-1",
    )
    run_report = RunStatusReport(
        run_id="run-e2e-1",
        owner="alice",
        state=RunState.RUNNING,
        total_jobs=2,
        completed_jobs=1,
        failed_jobs=0,
        running_jobs=1,
        pending_jobs=0,
        created_at=now,
        updated_at=now,
    )
    job = JobSpec(
        id="job-e2e-1",
        run_id="run-e2e-1",
        name="step-1",
        user="alice",
        owner="alice",
        command="python run.py",
    )
    node_pulse = NodeTelemetryPulse(
        worker_id="oci-node-1",
        memory_total_mb=24000,
        memory_used_mb=1200,
        scratch_total_mb=10000,
        scratch_used_mb=500,
        active_jobs=1,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/stats":
            stats = ClusterStatsReport(
                total_runs=1, total_jobs=2, running_jobs=1, active_workers=1
            )
            return httpx.Response(200, json=stats.model_dump(mode="json"))
        if path == "/v1/jobs":
            return httpx.Response(200, json=[job.model_dump(mode="json")])
        if path == "/v1/runs":
            return httpx.Response(200, json=[run_report.model_dump(mode="json")])
        if path == "/v1/collateral":
            return httpx.Response(200, json=[bundle.model_dump(mode="json")])
        if path == "/v1/nodes":
            return httpx.Response(200, json=[node_pulse.model_dump(mode="json")])
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
        return httpx.Response(404, json={"detail": f"Unhandled {path}"})

    real_cls = LocalClientAdapter
    mock_transport = httpx.MockTransport(handler)

    def make_client(
        session: LocalCliSession | None = None,
        *,
        controller_url: str | None = None,
        admin_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> LocalClientAdapter:
        return real_cls(
            controller_url=controller_url or "http://remote-e2e:8000",
            admin_token=admin_token or "e2e-token",
            transport=mock_transport,
        )

    with (
        patch("hexaqueue_cli.main.LocalClientAdapter", side_effect=make_client),
        patch("hexaqueue_cli.commands.run.LocalClientAdapter", side_effect=make_client),
        patch(
            "hexaqueue_cli.commands.collateral.LocalClientAdapter",
            side_effect=make_client,
        ),
        patch(
            "hexaqueue_cli.commands.node.LocalClientAdapter", side_effect=make_client
        ),
    ):
        stat_res = runner.invoke(
            app, ["stat", "--url", "http://remote-e2e:8000", "-f", "json"]
        )
        assert stat_res.exit_code == 0
        assert json.loads(stat_res.stdout)["active_workers"] == 1

        jobs_res = runner.invoke(
            app,
            [
                "--url",
                "http://remote-e2e:8000",
                "jobs",
                "--user",
                "alice",
                "-f",
                "json",
            ],
        )
        assert jobs_res.exit_code == 0
        assert json.loads(jobs_res.stdout)[0]["id"] == "job-e2e-1"

        runs_res = runner.invoke(
            app,
            [
                "run",
                "list",
                "--url",
                "http://remote-e2e:8000",
                "--user",
                "alice",
                "-f",
                "json",
            ],
        )
        assert runs_res.exit_code == 0
        assert json.loads(runs_res.stdout)[0]["run_id"] == "run-e2e-1"

        col_res = runner.invoke(
            app,
            [
                "collateral",
                "list",
                "--url",
                "http://remote-e2e:8000",
                "--user",
                "alice",
                "-f",
                "json",
            ],
        )
        assert col_res.exit_code == 0
        assert json.loads(col_res.stdout)[0]["id"] == "col-e2e-1"

        nodes_res = runner.invoke(
            app, ["node", "list", "--url", "http://remote-e2e:8000", "-f", "json"]
        )
        assert nodes_res.exit_code == 0
        assert json.loads(nodes_res.stdout)[0]["worker_id"] == "oci-node-1"

        fs_res = runner.invoke(
            app, ["fairshare", "--url", "http://remote-e2e:8000", "-f", "json"]
        )
        assert fs_res.exit_code == 0
        assert json.loads(fs_res.stdout)["root"]["id"] == "root"
