"""Native in-memory break-glass bastion adapter.

Notes/Architectural Intent:
    Provides an air-gapped, zero-external-dependency emergency break-glass
    bastion double and session governor. Generates native Hexaqueue node break-glass
    tunnel commands with ephemeral cryptographically signed tokens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hexaqueue_core.adapters.bastion.base import BaseBastionAdapter
from hexaqueue_core.domain.bastion import (
    BastionProtocolType,
    BastionSession,
    ConnectionCommand,
)

if TYPE_CHECKING:
    from hexaqueue_core.ports.security import BoundaryAuditLoggerPort


class NativeBreakGlassAdapter(BaseBastionAdapter):
    """Adapter for native in-memory break-glass emergency maintenance tunnels.

    Args:
        audit_logger: Optional boundary audit logger for SIEM tracking.
    """

    def __init__(
        self,
        audit_logger: BoundaryAuditLoggerPort | None = None,
    ) -> None:
        super().__init__(
            protocol=BastionProtocolType.NATIVE_BREAK_GLASS,
            audit_logger=audit_logger,
        )

    async def get_connection_command(
        self, node_id: str, session: BastionSession
    ) -> ConnectionCommand:
        """Render the native Hexaqueue node break-glass CLI invocation."""
        if not session.is_active:
            msg = f"Session '{session.session_id}' is inactive"
            raise ValueError(msg)
        if session.is_expired():
            msg = f"Session '{session.session_id}' has expired"
            raise ValueError(msg)
        if session.node_id != node_id:
            msg = f"Session targets node '{session.node_id}', not '{node_id}'"
            raise ValueError(msg)

        cmd = [
            "hq",
            "node",
            "break-glass",
            "--node",
            node_id,
            "--session",
            session.session_id,
            "--token",
            session.token,
        ]

        env = {
            "HQ_BASTION_SESSION": session.session_id,
            "HQ_BASTION_TOKEN": session.token,
        }

        return ConnectionCommand(
            command=cmd,
            env=env,
            description=f"Native Hexaqueue break-glass maintenance tunnel to '{node_id}'",
            expires_at=session.expires_at,
        )


__all__ = [
    "NativeBreakGlassAdapter",
]
