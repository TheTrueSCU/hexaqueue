"""Unit tests for TailscaleTeleportAdapter.

Notes/Architectural Intent:
    Validates Tailscale SSH and Teleport tsh command generation,
    mode switching, and session validation.
"""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.adapters.bastion.tailscale import TailscaleTeleportAdapter
from hexaqueue_core.domain.bastion import (
    BastionProtocolType,
)


@pytest.mark.anyio
async def test_tailscale_mode_connection_command() -> None:
    """Verify Tailscale SSH command rendering."""
    adapter = TailscaleTeleportAdapter(mode="tailscale")
    session = await adapter.generate_session_token(
        node_id="bare-metal-01",
        operator_id="eng-bob",
        duration_seconds=3600,
    )
    session.metadata["tailnet"] = "corp.ts.net"

    proto = session.protocol
    assert proto == BastionProtocolType.TAILSCALE_TELEPORT

    cmd = await adapter.get_connection_command("bare-metal-01", session)
    assert cmd.command == ["tailscale", "ssh", "eng-bob@bare-metal-01"]
    assert cmd.env.get("TAILSCALE_TAILNET") == "corp.ts.net"


@pytest.mark.anyio
async def test_teleport_mode_connection_command() -> None:
    """Verify Teleport tsh ssh command rendering."""
    adapter = TailscaleTeleportAdapter(
        mode="teleport", proxy_host="teleport.infra.company.com:443"
    )
    session = await adapter.generate_session_token(
        node_id="edge-worker-cluster",
        operator_id="spiffe://hexaqueue.org/operators/alice",
        duration_seconds=1800,
    )
    session.metadata["teleport_cluster"] = "edge-east"

    cmd = await adapter.get_connection_command("edge-worker-cluster", session)
    tokens = cmd.command
    assert tokens == [
        "tsh",
        "ssh",
        "alice@edge-worker-cluster",
        "--proxy",
        "teleport.infra.company.com:443",
        "--cluster",
        "edge-east",
    ]


def test_invalid_mode_rejected() -> None:
    """Verify initialization rejects unrecognized mode."""
    with pytest.raises(ValueError, match="mode must be 'tailscale' or 'teleport'"):
        TailscaleTeleportAdapter(mode="invalid")  # ty: ignore[invalid-argument-type] # type: ignore[arg-type]


@pytest.mark.anyio
async def test_tailscale_session_validation_failures() -> None:
    """Verify error checking for invalid, inactive, or expired sessions."""
    adapter = TailscaleTeleportAdapter()
    session = await adapter.generate_session_token("node-1", "op-1")

    with pytest.raises(ValueError, match="targets node 'node-1', not 'node-2'"):
        await adapter.get_connection_command("node-2", session)

    session.terminate()
    with pytest.raises(ValueError, match="is inactive"):
        await adapter.get_connection_command("node-1", session)

    session.is_active = True
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(ValueError, match="has expired"):
        await adapter.get_connection_command("node-1", session)
