"""Unit tests for bastion session domain models and connection commands.

Notes/Architectural Intent:
    Validates model invariants, parameter sanitization, shell escaping,
    and expiration calculus for zero-trust operator bastion sessions.
"""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.domain.bastion import (
    BastionProtocolType,
    BastionSession,
    ConnectionCommand,
)


def test_bastion_protocol_types() -> None:
    """Verify supported protocol enum values."""
    assert BastionProtocolType.AWS_SSM.value == "aws_ssm"
    assert BastionProtocolType.GCP_IAP.value == "gcp_iap"
    assert BastionProtocolType.AZURE_BASTION.value == "azure_bastion"
    assert BastionProtocolType.TAILSCALE_TELEPORT.value == "tailscale_teleport"
    assert BastionProtocolType.NATIVE_BREAK_GLASS.value == "native_break_glass"


def test_connection_command_shell_string() -> None:
    """Verify safe shell escaping and environment rendering."""
    cmd = ConnectionCommand(
        command=["aws", "ssm", "start-session", "--target", "i-1234567890abcdef0"],
        env={"AWS_PROFILE": "dev-ops", "AWS_REGION": "us-west-2"},
        description="AWS SSM session",
    )
    shell_str = cmd.as_shell_string()
    assert "AWS_PROFILE=dev-ops" in shell_str
    assert "AWS_REGION=us-west-2" in shell_str
    assert "aws ssm start-session --target i-1234567890abcdef0" in shell_str


def test_connection_command_empty_rejected() -> None:
    """Verify empty command list raises ValueError."""
    with pytest.raises(ValueError, match="command list cannot be empty"):
        ConnectionCommand(command=[])


def test_bastion_session_lifecycle() -> None:
    """Verify session creation, active state, expiration, and termination."""
    now = datetime.now(UTC)
    expires = now + timedelta(hours=1)
    session = BastionSession(
        node_id="worker-node-42",
        operator_id="operator@hexaqueue.org",
        protocol=BastionProtocolType.NATIVE_BREAK_GLASS,
        token="super-secret-token",
        created_at=now,
        expires_at=expires,
        metadata={"rack": "12A"},
    )

    is_active = session.is_active
    assert is_active is True
    is_exp = session.is_expired(now + timedelta(minutes=30))
    assert is_exp is False
    is_exp_later = session.is_expired(now + timedelta(hours=2))
    assert is_exp_later is True

    session.terminate()
    is_active_after = session.is_active
    assert is_active_after is False


def test_bastion_session_invariants() -> None:
    """Verify session validation catches invalid fields."""
    now = datetime.now(UTC)
    future = now + timedelta(hours=1)

    with pytest.raises(ValueError, match="node_id cannot be blank"):
        BastionSession(
            node_id="   ",
            operator_id="op1",
            protocol=BastionProtocolType.AWS_SSM,
            token="tok",
            created_at=now,
            expires_at=future,
        )

    with pytest.raises(ValueError, match="operator_id cannot be blank"):
        BastionSession(
            node_id="node1",
            operator_id="",
            protocol=BastionProtocolType.AWS_SSM,
            token="tok",
            created_at=now,
            expires_at=future,
        )

    with pytest.raises(ValueError, match="token cannot be blank"):
        BastionSession(
            node_id="node1",
            operator_id="op1",
            protocol=BastionProtocolType.AWS_SSM,
            token="",
            created_at=now,
            expires_at=future,
        )

    with pytest.raises(
        ValueError, match="expires_at must be strictly greater than created_at"
    ):
        BastionSession(
            node_id="node1",
            operator_id="op1",
            protocol=BastionProtocolType.AWS_SSM,
            token="tok",
            created_at=now,
            expires_at=now - timedelta(seconds=1),
        )
