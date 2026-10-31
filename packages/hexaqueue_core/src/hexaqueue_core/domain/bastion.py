"""Cloud-agnostic bastion session and operator access domain models.

Notes/Architectural Intent:
    Defines foundational value objects and session entities for zero-trust
    operator maintenance access. Decouples elevated terminal access from specific
    cloud infrastructure (AWS SSM, GCP IAP, Azure Bastion, Tailscale/Teleport, Native).
"""

from __future__ import annotations

import shlex
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BastionProtocolType(StrEnum):
    """Supported cloud-agnostic bastion and session tunnel protocols."""

    AWS_SSM = "aws_ssm"
    GCP_IAP = "gcp_iap"
    AZURE_BASTION = "azure_bastion"
    TAILSCALE_TELEPORT = "tailscale_teleport"
    NATIVE_BREAK_GLASS = "native_break_glass"


class ConnectionCommand(BaseModel):
    """Executable command structure rendered by a bastion adapter.

    Args:
        command: Argument list for executing the zero-trust tunnel.
        env: Ephemeral environment variables required for connection.
        description: Human-readable guidance or connection summary.
        expires_at: Optional timestamp when the connection token/lease expires.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: list[str] = Field(description="Command executable and argument tokens")
    env: dict[str, str] = Field(
        default_factory=dict, description="Session environment variables"
    )
    description: str = Field(
        default="", description="Operator guidance or connection summary"
    )
    expires_at: datetime | None = Field(
        default=None, description="Expiration timestamp for connection credentials"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate command invariants."""
        if not self.command:
            msg = "command list cannot be empty"
            raise ValueError(msg)
        return self

    def as_shell_string(self) -> str:
        """Render the command and environment as a single copy-pasteable shell invocation.

        Returns:
            Formatted shell command string.
        """
        env_prefix = " ".join(
            f"{k}={shlex.quote(v)}" for k, v in sorted(self.env.items())
        )
        cmd_str = " ".join(shlex.quote(token) for token in self.command)
        if env_prefix:
            return f"{env_prefix} {cmd_str}"
        return cmd_str


class BastionSession(BaseModel):
    """Active administrative or break-glass operator maintenance session.

    Args:
        session_id: Unique session identifier.
        node_id: Target compute node or host identifier.
        operator_id: Identity of the operator or engineer requesting access.
        protocol: Selected bastion tunnel protocol.
        token: Cryptographic ephemeral credential or lease token.
        created_at: Session establishment timestamp (UTC).
        expires_at: Session expiration timestamp (UTC).
        is_active: Whether the session is currently active and valid.
        metadata: Provider-specific connection attributes (e.g. AWS region, instance ID, GCP zone).
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(
        default_factory=lambda: f"bastion-{uuid4().hex[:12]}",
        description="Unique session identifier",
    )
    node_id: str = Field(description="Target compute node identifier")
    operator_id: str = Field(description="Authenticated operator requesting access")
    protocol: BastionProtocolType = Field(description="Bastion access protocol")
    token: str = Field(description="Ephemeral cryptographic authorization token")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Session creation timestamp",
    )
    expires_at: datetime = Field(description="Session expiration timestamp")
    is_active: bool = Field(
        default=True, description="Active status of the bastion session"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Provider-specific connection metadata"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate session invariants."""
        if not self.node_id.strip():
            msg = "node_id cannot be blank"
            raise ValueError(msg)
        if not self.operator_id.strip():
            msg = "operator_id cannot be blank"
            raise ValueError(msg)
        if not self.token.strip():
            msg = "token cannot be blank"
            raise ValueError(msg)
        if self.expires_at <= self.created_at:
            msg = "expires_at must be strictly greater than created_at"
            raise ValueError(msg)
        return self

    def is_expired(self, current_time: datetime | None = None) -> bool:
        """Check whether the session has passed its expiration time.

        Args:
            current_time: Optional explicit timestamp (defaults to datetime.now(UTC)).

        Returns:
            True if current_time >= expires_at.
        """
        now = current_time if current_time is not None else datetime.now(UTC)
        return now >= self.expires_at

    def terminate(self) -> None:
        """Terminate the active session."""
        self.is_active = False


__all__ = [
    "BastionProtocolType",
    "BastionSession",
    "ConnectionCommand",
]
