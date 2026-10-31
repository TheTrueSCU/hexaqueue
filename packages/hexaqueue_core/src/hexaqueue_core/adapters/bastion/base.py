"""Base session-governed bastion adapter with audit trail support.

Notes/Architectural Intent:
    Provides thread-safe in-memory session lease management, token generation,
    session pruning, and optional SIEM boundary access audit logging for all
    cloud and on-prem bastion adapters.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from hexaqueue_core.domain.bastion import (
    BastionProtocolType,
    BastionSession,
)
from hexaqueue_core.domain.security import BoundaryAuditRecord
from hexaqueue_core.ports.bastion import BastionAccessPort

if TYPE_CHECKING:
    from hexaqueue_core.ports.security import BoundaryAuditLoggerPort


class BaseBastionAdapter(BastionAccessPort):
    """Base class for pluggable zero-trust bastion adapters.

    Args:
        protocol: The BastionProtocolType implemented by this adapter.
        audit_logger: Optional BoundaryAuditLoggerPort to capture access audit records.
    """

    def __init__(
        self,
        protocol: BastionProtocolType,
        audit_logger: BoundaryAuditLoggerPort | None = None,
    ) -> None:
        self.protocol = protocol
        self.audit_logger = audit_logger
        self._sessions: dict[str, BastionSession] = {}
        self._lock = asyncio.Lock()

    async def generate_session_token(
        self, node_id: str, operator_id: str, duration_seconds: int = 3600
    ) -> BastionSession:
        """Mint a new ephemeral session with cryptographic lease token."""
        if not node_id or not node_id.strip():
            msg = "node_id cannot be blank"
            raise ValueError(msg)
        if not operator_id or not operator_id.strip():
            msg = "operator_id cannot be blank"
            raise ValueError(msg)
        if duration_seconds <= 0:
            msg = "duration_seconds must be positive"
            raise ValueError(msg)

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=duration_seconds)
        token = secrets.token_urlsafe(32)

        session = BastionSession(
            session_id=f"bastion-{uuid4().hex[:12]}",
            node_id=node_id.strip(),
            operator_id=operator_id.strip(),
            protocol=self.protocol,
            token=token,
            created_at=now,
            expires_at=expires_at,
            is_active=True,
        )

        async with self._lock:
            self._sessions[session.session_id] = session

        await self._emit_audit(
            action="bastion_session_minted",
            node_id=node_id,
            operator_id=operator_id,
            session_id=session.session_id,
        )
        return session

    async def terminate_session(self, session_id: str) -> None:
        """Terminate and revoke an active session."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                msg = f"Session '{session_id}' not found"
                raise KeyError(msg)
            session.terminate()

        await self._emit_audit(
            action="bastion_session_terminated",
            node_id=session.node_id,
            operator_id=session.operator_id,
            session_id=session.session_id,
        )

    async def audit_active_sessions(self) -> list[BastionSession]:
        """Audit and list all currently active and unexpired administrative sessions."""
        now = datetime.now(UTC)
        async with self._lock:
            active: list[BastionSession] = []
            for session in self._sessions.values():
                if session.is_active and not session.is_expired(now):
                    active.append(session)
            return active

    async def _emit_audit(
        self, action: str, node_id: str, operator_id: str, session_id: str
    ) -> None:
        """Emit boundary audit record if an audit logger is attached."""
        if not self.audit_logger:
            return

        caller_uri = (
            operator_id
            if operator_id.startswith("spiffe://")
            else f"spiffe://hexaqueue.org/operators/{operator_id}"
        )
        record = BoundaryAuditRecord(
            action=action,
            target_boundary=f"bastion:{self.protocol.value}",
            target_resource_id=f"{node_id}:{session_id}",
            authorization_verdict="ALLOWED",
            caller_spiffe_id=caller_uri,
        )
        await self.audit_logger.log_access(record)


__all__ = [
    "BaseBastionAdapter",
]
