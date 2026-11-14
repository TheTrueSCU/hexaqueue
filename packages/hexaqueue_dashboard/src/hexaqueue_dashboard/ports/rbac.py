"""Abstract port for Hexaqueue Dashboard RBAC principal and policy persistence.

Notes/Architectural Intent:
    Isolates `DashboardAuthManager` and RBAC administration routes from concrete
    storage engines (Oracle Autonomous DB, local SQLite, or in-memory stores).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from hexaqueue_dashboard.domain.rbac import RbacPrincipal


class RbacPolicyPort(ABC):
    """Abstract repository port for persisting and querying RBAC principals.

    Notes/Architectural Intent:
        Enables swapping Oracle ADB (`OracleAdbRbacPolicyAdapter`) with a local
        SQLite database (`SqliteRbacPolicyAdapter`) or an in-memory store
        (`InMemoryRbacPolicyAdapter`) without changing auth or domain logic.
    """

    @abstractmethod
    def get_principal(self, principal_id: str) -> RbacPrincipal | None:
        """Fetch an RBAC principal by identifier.

        Args:
            principal_id: Unique principal name.

        Returns:
            Matching RbacPrincipal if found, otherwise None.
        """

    @abstractmethod
    def upsert_principal(self, principal: RbacPrincipal) -> None:
        """Create or update an RBAC principal record.

        Args:
            principal: RbacPrincipal to persist.
        """

    @abstractmethod
    def list_principals(self) -> list[RbacPrincipal]:
        """List all persisted RBAC principals.

        Returns:
            List of RbacPrincipal instances sorted by principal_id.
        """

    @abstractmethod
    def delete_principal(self, principal_id: str) -> bool:
        """Delete an RBAC principal by identifier.

        Args:
            principal_id: Target principal name.

        Returns:
            True if a record was removed, False if not found.
        """


__all__ = [
    "RbacPolicyPort",
]
