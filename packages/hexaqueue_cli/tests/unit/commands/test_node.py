"""Unit tests for hq node CLI commands."""

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
