"""Microsoft Azure Bastion zero-trust keyless SSH adapter.

Notes/Architectural Intent:
    Implements keyless administrative access to Azure VMs using Microsoft Entra
    ID authentication via Azure Bastion host data plane APIs (`az network bastion ssh`).
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


class AzureBastionAdapter(BaseBastionAdapter):
    """Adapter for Azure Bastion native SSH client access.

    Args:
        bastion_name: Name of the Azure Bastion host resource.
        resource_group: Resource group containing the Azure Bastion host.
        subscription: Optional Azure subscription identifier.
        audit_logger: Optional boundary audit logger for SIEM tracking.
    """

    def __init__(
        self,
        bastion_name: str | None = None,
        resource_group: str | None = None,
        subscription: str | None = None,
        audit_logger: BoundaryAuditLoggerPort | None = None,
    ) -> None:
        super().__init__(
            protocol=BastionProtocolType.AZURE_BASTION, audit_logger=audit_logger
        )
        self.bastion_name = bastion_name
        self.resource_group = resource_group
        self.subscription = subscription

    async def get_connection_command(
        self, node_id: str, session: BastionSession
    ) -> ConnectionCommand:
        """Render the az network bastion ssh CLI invocation."""
        if not session.is_active:
            msg = f"Session '{session.session_id}' is inactive"
            raise ValueError(msg)
        if session.is_expired():
            msg = f"Session '{session.session_id}' has expired"
            raise ValueError(msg)
        if session.node_id != node_id:
            msg = f"Session targets node '{session.node_id}', not '{node_id}'"
            raise ValueError(msg)

        target_id = session.metadata.get("target_resource_id", node_id)
        bastion = session.metadata.get("bastion_name", self.bastion_name)
        rg = session.metadata.get("resource_group", self.resource_group)
        sub = session.metadata.get("subscription", self.subscription)
        auth_type = session.metadata.get("auth_type", "AAD")

        cmd = [
            "az",
            "network",
            "bastion",
            "ssh",
            "--target-resource-id",
            str(target_id),
            "--auth-type",
            str(auth_type),
        ]
        if bastion:
            cmd.extend(["--name", str(bastion)])
        if rg:
            cmd.extend(["--resource-group", str(rg)])
        if sub:
            cmd.extend(["--subscription", str(sub)])

        env: dict[str, str] = {}
        if "azure_tenant" in session.metadata:
            env["AZURE_TENANT_ID"] = str(session.metadata["azure_tenant"])

        return ConnectionCommand(
            command=cmd,
            env=env,
            description=f"Azure Bastion native SSH tunnel to target '{target_id}'",
            expires_at=session.expires_at,
        )


__all__ = [
    "AzureBastionAdapter",
]
