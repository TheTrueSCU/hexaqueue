"""Unit tests for hq admin session CLI commands.

Notes/Architectural Intent:
    Validates administrative elevation enforcement (--admin), session creation,
    connection command rendering across protocols, session listing, and revocation.
"""

from typer.testing import CliRunner

from hexaqueue_cli.commands.admin import get_bastion_adapter
from hexaqueue_cli.main import app
from hexaqueue_core.adapters.bastion import (
    AWSSSMAdapter,
    AzureBastionAdapter,
    GCPIAPAdapter,
    NativeBreakGlassAdapter,
    TailscaleTeleportAdapter,
)
from hexaqueue_core.domain.bastion import BastionProtocolType

runner = CliRunner()


def test_admin_session_create_requires_admin_elevation() -> None:
    """Verify hq admin session create rejects unprivileged calls without --admin."""
    res = runner.invoke(app, ["admin", "session", "create", "node-gpu-01"])
    assert res.exit_code == 1
    assert "Permission denied" in res.stdout
    assert "--admin" in res.stdout


def test_admin_session_create_native_break_glass() -> None:
    """Verify hq admin session create generates native break-glass command."""
    res = runner.invoke(
        app,
        [
            "admin",
            "session",
            "create",
            "node-gpu-01",
            "--admin",
            "--protocol",
            "native_break_glass",
            "--operator",
            "alice",
        ],
    )
    assert res.exit_code == 0
    assert "Bastion session" in res.stdout
    assert "break-glass" in res.stdout
    assert "node-gpu-01" in res.stdout
    assert "HQ_BASTION_SESSION" in res.stdout


def test_admin_session_create_aws_ssm() -> None:
    """Verify hq admin session create generates AWS SSM command."""
    res = runner.invoke(
        app,
        [
            "admin",
            "session",
            "create",
            "i-0123456789abcdef0",
            "--admin",
            "--protocol",
            "aws_ssm",
            "--operator",
            "bob",
        ],
    )
    assert res.exit_code == 0
    assert "aws ssm start-session" in res.stdout
    assert "i-0123456789abcdef0" in res.stdout


def test_admin_session_list_and_terminate() -> None:
    """Verify listing and terminating active sessions."""
    # 1. List sessions
    res_list = runner.invoke(
        app, ["admin", "session", "list", "--protocol", "native_break_glass"]
    )
    assert res_list.exit_code == 0

    # 2. Terminate session
    res_term = runner.invoke(
        app,
        [
            "admin",
            "session",
            "terminate",
            "bastion-sample",
            "--protocol",
            "native_break_glass",
        ],
    )
    # The session doesn't exist so error is reported with code 1
    assert res_term.exit_code == 1
    assert "Error terminating bastion session" in res_term.stdout


def test_get_bastion_adapter_resolution() -> None:
    """Verify adapter factory instantiates correct implementation per protocol."""
    aws_ad = get_bastion_adapter(BastionProtocolType.AWS_SSM)
    assert isinstance(aws_ad, AWSSSMAdapter)

    gcp_ad = get_bastion_adapter(BastionProtocolType.GCP_IAP)
    assert isinstance(gcp_ad, GCPIAPAdapter)

    az_ad = get_bastion_adapter(BastionProtocolType.AZURE_BASTION)
    assert isinstance(az_ad, AzureBastionAdapter)

    ts_ad = get_bastion_adapter(BastionProtocolType.TAILSCALE_TELEPORT)
    assert isinstance(ts_ad, TailscaleTeleportAdapter)

    nat_ad = get_bastion_adapter(BastionProtocolType.NATIVE_BREAK_GLASS)
    assert isinstance(nat_ad, NativeBreakGlassAdapter)
