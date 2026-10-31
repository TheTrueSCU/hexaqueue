"""Google Cloud Identity-Aware Proxy (IAP) bastion adapter.

Notes/Architectural Intent:
    Implements keyless zero-ingress administrative access to GCP Compute Engine
    nodes via Google Identity-Aware Proxy TCP forwarding (`--tunnel-through-iap`).
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


class GCPIAPAdapter(BaseBastionAdapter):
    """Adapter for Google Cloud Identity-Aware Proxy (IAP) SSH access.

    Args:
        project: Default GCP Project ID.
        zone: Default GCP compute zone (e.g. 'us-central1-a').
        audit_logger: Optional boundary audit logger for SIEM tracking.
    """

    def __init__(
        self,
        project: str | None = None,
        zone: str | None = None,
        audit_logger: BoundaryAuditLoggerPort | None = None,
    ) -> None:
        super().__init__(
            protocol=BastionProtocolType.GCP_IAP, audit_logger=audit_logger
        )
        self.project = project
        self.zone = zone

    async def get_connection_command(
        self, node_id: str, session: BastionSession
    ) -> ConnectionCommand:
        """Render the gcloud compute ssh --tunnel-through-iap CLI invocation."""
        if not session.is_active:
            msg = f"Session '{session.session_id}' is inactive"
            raise ValueError(msg)
        if session.is_expired():
            msg = f"Session '{session.session_id}' has expired"
            raise ValueError(msg)
        if session.node_id != node_id:
            msg = f"Session targets node '{session.node_id}', not '{node_id}'"
            raise ValueError(msg)

        instance = session.metadata.get("instance_name", node_id)
        project = session.metadata.get("project", self.project)
        zone = session.metadata.get("zone", self.zone)

        cmd = [
            "gcloud",
            "compute",
            "ssh",
            str(instance),
            "--tunnel-through-iap",
        ]
        if project:
            cmd.extend(["--project", str(project)])
        if zone:
            cmd.extend(["--zone", str(zone)])

        env: dict[str, str] = {}
        if "cloudsdk_account" in session.metadata:
            env["CLOUDSDK_CORE_ACCOUNT"] = str(session.metadata["cloudsdk_account"])

        return ConnectionCommand(
            command=cmd,
            env=env,
            description=f"GCP IAP tunnel SSH to compute instance '{instance}'",
            expires_at=session.expires_at,
        )


__all__ = [
    "GCPIAPAdapter",
]
