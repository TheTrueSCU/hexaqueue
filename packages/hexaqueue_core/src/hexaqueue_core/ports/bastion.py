"""Cloud-agnostic bastion and operator access port interface.

Notes/Architectural Intent:
    Defines the abstract driving/driven port for zero-trust administrative terminal
    access to worker compute nodes across AWS SSM, GCP IAP, Azure Bastion,
    Tailscale/Teleport, and Native Break-Glass tunnels.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from hexaqueue_core.domain.bastion import BastionSession, ConnectionCommand


class BastionAccessPort(ABC):
    """Abstract port for cloud-agnostic bastion maintenance sessions and tunnels.

    Notes/Architectural Intent:
        Guarantees that administrative session creation, ephemeral connection command
        generation, session termination, and active session auditing are strictly
        decoupled from any single cloud provider's proprietary APIs.
    """

    @abstractmethod
    async def generate_session_token(
        self, node_id: str, operator_id: str, duration_seconds: int = 3600
    ) -> BastionSession:
        """Mint a new ephemeral bastion session and credential token for an operator.

        Args:
            node_id: Target compute node or host identifier.
            operator_id: Identity of the requesting engineer or operator.
            duration_seconds: Maximum lease duration before token expiration (default 3600s).

        Returns:
            The minted BastionSession with active token and expiration timestamp.

        Raises:
            ValueError: If node_id or operator_id is invalid or duration <= 0.
        """

    @abstractmethod
    async def get_connection_command(
        self, node_id: str, session: BastionSession
    ) -> ConnectionCommand:
        """Render the zero-trust CLI or tunnel command required to connect to the node.

        Args:
            node_id: Target compute node identifier.
            session: Valid and active BastionSession.

        Returns:
            Executable ConnectionCommand with tokens, environment, and expiration.

        Raises:
            ValueError: If the session is inactive, expired, or targets a different node.
        """

    @abstractmethod
    async def terminate_session(self, session_id: str) -> None:
        """Revoke an active bastion session lease immediately.

        Args:
            session_id: Unique session identifier to revoke.

        Returns:
            None.

        Raises:
            KeyError: If session_id does not exist.
        """

    @abstractmethod
    async def audit_active_sessions(self) -> list[BastionSession]:
        """Audit and list all currently active and unexpired administrative sessions.

        Returns:
            List of active BastionSession records.
        """


__all__ = [
    "BastionAccessPort",
]
