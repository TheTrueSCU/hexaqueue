"""Unit tests for hq node CLI commands."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from hexaqueue_cli.domain.session import LocalCliSession, set_default_session
from hexaqueue_cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_session() -> None:
    """Hermetic session fixture."""
    session = LocalCliSession(concurrency=2)
    set_default_session(session)


def test_cli_node_list_command() -> None:
    """Verify hq node list displays registered compute nodes."""
    res = runner.invoke(app, ["node", "list"])
    assert res.exit_code == 0


def test_cli_node_ssh_requires_positive_admin_elevation() -> None:
    """Verify hq node ssh enforces least privilege and requires --admin."""
    # 1. Unprivileged call without --admin is rejected
    res_denied = runner.invoke(app, ["node", "ssh", "worker-01"])
    assert res_denied.exit_code == 1
    assert "Permission denied" in res_denied.stdout
    assert "--admin" in res_denied.stdout

    # 2. Privileged call with explicit --admin succeeds
    res_allowed = runner.invoke(app, ["node", "ssh", "worker-01", "--admin"])
    assert res_allowed.exit_code == 0
    assert "Bastion terminal session" in res_allowed.stdout
    assert "worker-01" in res_allowed.stdout


def test_cli_node_ssh_direct_mode() -> None:
    """Verify hq node ssh --direct invokes ssh jump host command.

    Notes/Architectural Intent:
        Ensures out-of-band direct bastion access connects via jump host.
    """
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        res = runner.invoke(
            app,
            [
                "node",
                "ssh",
                "10.0.2.202",
                "--admin",
                "--direct",
                "--jump-host",
                "1.2.3.4",
            ],
        )
        assert res.exit_code == 0
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "-J" in args
        assert "ubuntu@1.2.3.4" in args
        assert "ubuntu@10.0.2.202" in args


def test_node_ssh_direct_failure() -> None:
    """Verify 'hq node ssh --direct' propagates non-zero exit code."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=5)
        res = runner.invoke(app, ["node", "ssh", "10.0.2.202", "--admin", "--direct"])
        assert res.exit_code == 5


def test_node_ssh_direct_interrupt() -> None:
    """Verify 'hq node ssh --direct' exits with 130 on KeyboardInterrupt."""
    with patch("subprocess.run", side_effect=KeyboardInterrupt):
        res = runner.invoke(app, ["node", "ssh", "10.0.2.202", "--admin", "--direct"])
        assert res.exit_code == 130


def test_node_ssh_bastion_failure() -> None:
    """Verify 'hq node ssh' handles bastion session error gracefully."""
    with patch(
        "hexaqueue_cli.commands.node.LocalClientAdapter.create_bastion_session",
        side_effect=RuntimeError("Bastion unavailable"),
    ):
        res = runner.invoke(app, ["node", "ssh", "node-1", "--admin"])
        assert res.exit_code == 1
