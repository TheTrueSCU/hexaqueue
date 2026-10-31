"""Unit tests for BaseBastionAdapter session management and audit logging.

Notes/Architectural Intent:
    Verifies that BaseBastionAdapter correctly handles session token generation,
    in-memory lifecycle tracking, lease expiration, and audit emission.
"""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.adapters.bastion.base import BaseBastionAdapter
from hexaqueue_core.domain.bastion import (
    BastionProtocolType,
    BastionSession,
    ConnectionCommand,
)
from hexaqueue_core.ports.security import (
    BoundaryAuditLoggerPort,
    BoundaryAuditRecord,
)


class DummyAuditLogger(BoundaryAuditLoggerPort):
    """Test double capturing boundary audit records."""

    def __init__(self) -> None:
        self.records: list[BoundaryAuditRecord] = []

    async def log_access(self, record: BoundaryAuditRecord) -> None:
        self.records.append(record)

    async def get_recent_records(self, limit: int = 100) -> list[BoundaryAuditRecord]:
        return list(self.records[:limit])


class DummyBastionAdapter(BaseBastionAdapter):
    """Concrete subclass for testing base session logic."""

    async def get_connection_command(
        self, node_id: str, session: BastionSession
    ) -> ConnectionCommand:
        return ConnectionCommand(command=["dummy", "connect", node_id])


@pytest.mark.anyio
async def test_base_bastion_adapter_generate_session() -> None:
    """Verify session token minting and validation."""
    logger = DummyAuditLogger()
    adapter = DummyBastionAdapter(
        protocol=BastionProtocolType.NATIVE_BREAK_GLASS, audit_logger=logger
    )

    session = await adapter.generate_session_token(
        node_id="worker-01",
        operator_id="operator@hexaqueue.org",
        duration_seconds=1800,
    )

    node_val = session.node_id
    assert node_val == "worker-01"
    op_val = session.operator_id
    assert op_val == "operator@hexaqueue.org"
    proto_val = session.protocol
    assert proto_val == BastionProtocolType.NATIVE_BREAK_GLASS
    assert len(session.token) > 20
    is_active = session.is_active
    assert is_active is True

    # Verify audit emission
    rec_count = len(logger.records)
    assert rec_count == 1
    assert logger.records[0].action == "bastion_session_minted"
    assert logger.records[0].target_boundary == "bastion:native_break_glass"
    assert logger.records[0].target_resource_id == f"worker-01:{session.session_id}"


@pytest.mark.anyio
async def test_base_bastion_adapter_validation_errors() -> None:
    """Verify parameter validations on session token generation."""
    adapter = DummyBastionAdapter(protocol=BastionProtocolType.NATIVE_BREAK_GLASS)

    with pytest.raises(ValueError, match="node_id cannot be blank"):
        await adapter.generate_session_token(node_id="", operator_id="op1")

    with pytest.raises(ValueError, match="operator_id cannot be blank"):
        await adapter.generate_session_token(node_id="n1", operator_id="   ")

    with pytest.raises(ValueError, match="duration_seconds must be positive"):
        await adapter.generate_session_token(
            node_id="n1", operator_id="op1", duration_seconds=0
        )


@pytest.mark.anyio
async def test_base_bastion_adapter_audit_active_and_terminate() -> None:
    """Verify active session auditing and termination flow."""
    logger = DummyAuditLogger()
    adapter = DummyBastionAdapter(
        protocol=BastionProtocolType.NATIVE_BREAK_GLASS, audit_logger=logger
    )

    s1 = await adapter.generate_session_token("n1", "op1", duration_seconds=3600)
    s2 = await adapter.generate_session_token("n2", "op2", duration_seconds=3600)

    active = await adapter.audit_active_sessions()
    act_count = len(active)
    assert act_count == 2

    # Terminate s1
    await adapter.terminate_session(s1.session_id)
    active_after = await adapter.audit_active_sessions()
    act_after_count = len(active_after)
    assert act_after_count == 1
    assert active_after[0].session_id == s2.session_id

    # Verify termination audit
    term_recs = [r for r in logger.records if r.action == "bastion_session_terminated"]
    term_count = len(term_recs)
    assert term_count == 1
    assert term_recs[0].target_resource_id == f"n1:{s1.session_id}"

    # Terminating nonexistent raises KeyError
    with pytest.raises(KeyError, match="Session 'missing' not found"):
        await adapter.terminate_session("missing")


@pytest.mark.anyio
async def test_base_bastion_adapter_excludes_expired_sessions() -> None:
    """Verify that expired sessions are excluded from audit_active_sessions."""
    adapter = DummyBastionAdapter(protocol=BastionProtocolType.NATIVE_BREAK_GLASS)

    session = await adapter.generate_session_token("n1", "op1", duration_seconds=10)
    # Manually backdate expiration to simulate time passage
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    active = await adapter.audit_active_sessions()
    count = len(active)
    assert count == 0
