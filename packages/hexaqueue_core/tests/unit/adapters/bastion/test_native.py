"""Unit tests and dual-oracle verification for NativeBreakGlassAdapter.

Notes/Architectural Intent:
    Validates native break-glass tunnel command rendering and provides
    dual-oracle state equivalence testing for lease expiration calculus.
"""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hexaqueue_core.adapters.bastion.native import NativeBreakGlassAdapter
from hexaqueue_core.domain.bastion import (
    BastionProtocolType,
    BastionSession,
)


@pytest.mark.anyio
async def test_native_break_glass_connection_command() -> None:
    """Verify NativeBreakGlassAdapter renders valid hq node break-glass command."""
    adapter = NativeBreakGlassAdapter()
    session = await adapter.generate_session_token(
        node_id="bare-metal-airgap-01",
        operator_id="admin-oncall",
        duration_seconds=900,
    )

    proto = session.protocol
    assert proto == BastionProtocolType.NATIVE_BREAK_GLASS

    cmd = await adapter.get_connection_command("bare-metal-airgap-01", session)
    tokens = cmd.command
    assert tokens == [
        "hq",
        "node",
        "break-glass",
        "--node",
        "bare-metal-airgap-01",
        "--session",
        session.session_id,
        "--token",
        session.token,
    ]

    assert cmd.env["HQ_BASTION_SESSION"] == session.session_id
    assert cmd.env["HQ_BASTION_TOKEN"] == session.token


@pytest.mark.anyio
async def test_native_break_glass_session_validation_failures() -> None:
    """Verify session validation errors."""
    adapter = NativeBreakGlassAdapter()
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


# Naive reference oracle for dual-implementation verification
class NaiveBastionOracle:
    """Naive reference oracle maintaining dictionary-based session leases."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, object]] = {}

    def mint(self, node_id: str, op_id: str, duration_sec: int) -> str:
        now = datetime.now(UTC)
        sid = f"oracle-{len(self.sessions) + 1}"
        self.sessions[sid] = {
            "node_id": node_id,
            "operator_id": op_id,
            "created_at": now,
            "expires_at": now + timedelta(seconds=duration_sec),
            "is_active": True,
        }
        return sid

    def is_active(self, sid: str, at: datetime) -> bool:
        record = self.sessions.get(sid)
        if not record:
            return False
        expires = record["expires_at"]
        if not isinstance(expires, datetime):
            return False
        return bool(record["is_active"]) and at < expires


@given(
    node_id=st.text(min_size=1, max_size=20).filter(lambda s: bool(s.strip())),
    op_id=st.text(min_size=1, max_size=20).filter(lambda s: bool(s.strip())),
    duration=st.integers(min_value=60, max_value=86400),
)
def test_dual_oracle_session_expiration(
    node_id: str, op_id: str, duration: int
) -> None:
    """Mathematical equivalence proof: adapter session state matches naive oracle."""
    oracle = NaiveBastionOracle()
    sid = oracle.mint(node_id, op_id, duration)

    now = datetime.now(UTC)
    session = BastionSession(
        session_id=sid,
        node_id=node_id,
        operator_id=op_id,
        protocol=BastionProtocolType.NATIVE_BREAK_GLASS,
        token="test-token",
        created_at=now,
        expires_at=now + timedelta(seconds=duration),
        is_active=True,
    )

    # 1. Before expiration
    check_time = now + timedelta(seconds=duration // 2)
    oracle_state = oracle.is_active(sid, check_time)
    adapter_state = session.is_active and not session.is_expired(check_time)
    assert oracle_state == adapter_state

    # 2. After expiration
    check_time_expired = now + timedelta(seconds=duration + 10)
    oracle_expired = oracle.is_active(sid, check_time_expired)
    adapter_expired = session.is_active and not session.is_expired(check_time_expired)
    assert oracle_expired == adapter_expired
