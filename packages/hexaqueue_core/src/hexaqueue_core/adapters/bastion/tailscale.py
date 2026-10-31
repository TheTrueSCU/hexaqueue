"""Tailscale and Teleport zero-trust identity-based SSH adapter.

Notes/Architectural Intent:
    Implements wireguard/ephemeral-certificate operator access across on-prem,
    edge bare-metal, and multi-cloud nodes without exposing public SSH ports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from hexaqueue_core.adapters.bastion.base import BaseBastionAdapter
from hexaqueue_core.domain.bastion import (
    BastionProtocolType,
    BastionSession,
    ConnectionCommand,
)

if TYPE_CHECKING:
    from hexaqueue_core.ports.security import BoundaryAuditLoggerPort


class TailscaleTeleportAdapter(BaseBastionAdapter):
    """Adapter for Tailscale SSH or Teleport (`tsh`) zero-trust access.

    Args:
        mode: Engine mode, either 'tailscale' or 'teleport' (default 'tailscale').
        proxy_host: Optional Teleport auth proxy host or Tailnet domain.
        audit_logger: Optional boundary audit logger for SIEM tracking.
    """

    def __init__(
        self,
        mode: Literal["tailscale", "teleport"] = "tailscale",
        proxy_host: str | None = None,
        audit_logger: BoundaryAuditLoggerPort | None = None,
    ) -> None:
        super().__init__(
            protocol=BastionProtocolType.TAILSCALE_TELEPORT,
            audit_logger=audit_logger,
        )
        if mode not in ("tailscale", "teleport"):
            msg = f"mode must be 'tailscale' or 'teleport', got '{mode}'"
            raise ValueError(msg)
        self.mode = mode
        self.proxy_host = proxy_host

    async def get_connection_command(
        self, node_id: str, session: BastionSession
    ) -> ConnectionCommand:
        """Render the tailscale ssh or tsh ssh CLI invocation."""
        if not session.is_active:
            msg = f"Session '{session.session_id}' is inactive"
            raise ValueError(msg)
        if session.is_expired():
            msg = f"Session '{session.session_id}' has expired"
            raise ValueError(msg)
        if session.node_id != node_id:
            msg = f"Session targets node '{session.node_id}', not '{node_id}'"
            raise ValueError(msg)

        mode = session.metadata.get("mode", self.mode)
        proxy = session.metadata.get("proxy_host", self.proxy_host)
        operator = session.operator_id.split("/")[-1]
        target_host = session.metadata.get("hostname", node_id)

        env: dict[str, str] = {}

        if mode == "teleport":
            cmd = ["tsh", "ssh", f"{operator}@{target_host}"]
            if proxy:
                cmd.extend(["--proxy", str(proxy)])
            if "teleport_cluster" in session.metadata:
                cmd.extend(["--cluster", str(session.metadata["teleport_cluster"])])
            desc = f"Teleport zero-trust SSH to target '{target_host}'"
        else:
            cmd = ["tailscale", "ssh", f"{operator}@{target_host}"]
            if "tailnet" in session.metadata:
                env["TAILSCALE_TAILNET"] = str(session.metadata["tailnet"])
            desc = f"Tailscale mesh SSH to target '{target_host}'"

        return ConnectionCommand(
            command=cmd,
            env=env,
            description=desc,
            expires_at=session.expires_at,
        )


__all__ = [
    "TailscaleTeleportAdapter",
]
