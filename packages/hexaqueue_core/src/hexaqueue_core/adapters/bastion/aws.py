"""AWS Systems Manager (SSM) Session Manager bastion adapter.

Notes/Architectural Intent:
    Implements zero-ingress administrative access to EC2 compute nodes via AWS SSM.
    Generates deterministic `aws ssm start-session` command structures without requiring
    open SSH ports or public IPv4 addresses.
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


class AWSSSMAdapter(BaseBastionAdapter):
    """Adapter for AWS Systems Manager Session Manager access.

    Args:
        region_name: Default AWS region for SSM connections (e.g. 'us-east-1').
        document_name: Optional SSM session document (e.g. 'SSM-SessionManagerRunShell').
        audit_logger: Optional boundary audit logger for SIEM tracking.
    """

    def __init__(
        self,
        region_name: str | None = None,
        document_name: str | None = None,
        audit_logger: BoundaryAuditLoggerPort | None = None,
    ) -> None:
        super().__init__(
            protocol=BastionProtocolType.AWS_SSM, audit_logger=audit_logger
        )
        self.region_name = region_name
        self.document_name = document_name

    async def get_connection_command(
        self, node_id: str, session: BastionSession
    ) -> ConnectionCommand:
        """Render the AWS SSM start-session CLI invocation."""
        if not session.is_active:
            msg = f"Session '{session.session_id}' is inactive"
            raise ValueError(msg)
        if session.is_expired():
            msg = f"Session '{session.session_id}' has expired"
            raise ValueError(msg)
        if session.node_id != node_id:
            msg = f"Session targets node '{session.node_id}', not '{node_id}'"
            raise ValueError(msg)

        # Instance ID can be overridden in session metadata or fall back to node_id
        target = session.metadata.get("instance_id", node_id)
        region = session.metadata.get("region", self.region_name)
        document = session.metadata.get("document_name", self.document_name)

        cmd = ["aws", "ssm", "start-session", "--target", str(target)]
        if region:
            cmd.extend(["--region", str(region)])
        if document:
            cmd.extend(["--document-name", str(document)])

        env: dict[str, str] = {}
        if "aws_profile" in session.metadata:
            env["AWS_PROFILE"] = str(session.metadata["aws_profile"])

        return ConnectionCommand(
            command=cmd,
            env=env,
            description=f"AWS SSM zero-ingress session to target '{target}'",
            expires_at=session.expires_at,
        )


__all__ = [
    "AWSSSMAdapter",
]
