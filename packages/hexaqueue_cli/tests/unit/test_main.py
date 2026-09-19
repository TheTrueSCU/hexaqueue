import asyncio
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from hexaqueue_cli.domain.session import LocalCliSession, set_default_session
from hexaqueue_cli.main import app

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
    try:
        yield session
    finally:
        for s_id in list(session.pty._sessions.keys()):
            asyncio.run(session.pty.terminate_session(s_id))
        set_default_session(None)


def test_main_cli_help() -> None:
    """Verify main entrypoint displays help."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "Hexaqueue" in res.stdout
    assert "why" in res.stdout
    assert "explain" in res.stdout
    assert "fairshare" in res.stdout


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
    """Verify hold, release, logs, exec, attach, and cancel commands."""
    import asyncio

    from hexaqueue_core.domain.job import JobSpec
    from hexaqueue_core.domain.run import RunSpec
    from hexaqueue_core.ports.logging import LogChunk
    from hexaqueue_server.domain.models import RunSubmission

    session = hermetic_cli_session
    run = RunSpec(id="run-main-test", name="Main Test")
    job = JobSpec(id="job-main-test", run_id=run.id, name="job-m", command="echo hello")
    submission = RunSubmission(run_spec=run, jobs=[job])
    asyncio.run(session.controller.submit_run(submission))

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
    from hexaqueue_worker.domain.pty import PtySessionInfo

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
    async def _mock_stream(*args, **kwargs):
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


def test_main_cli_error_paths() -> None:
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
