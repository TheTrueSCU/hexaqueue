"""Domain models for Hexaqueue Web Dashboard presentation layer.

Notes/Architectural Intent:
    Represents presentation-layer views, requests, and session states for
    the Web Dashboard console. Strictly adheres to hexagonal boundaries:
    models remain decoupled from underlying storage engines and web frameworks.
"""

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.collateral import CollateralKind, CollateralTier


class DashboardUserSession(BaseModel):
    """User session context within the Web Dashboard.

    Args:
        user_id: Natural identity of current session owner.
        is_admin: Whether the user possesses administrative privileges.
        elevated: Whether the user has actively unlocked administrative mode.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevated: bool = Field(
        default=False,
        description="Whether administrative mode is positively unlocked",
    )
    is_admin: bool = Field(
        default=False, description="Whether user possesses admin role"
    )
    user_id: str = Field(default="default", description="Natural user identity")


class DashboardJobAction(BaseModel):
    """Action payload for job lifecycle manipulations from the Web Dashboard.

    Args:
        action: Target lifecycle action ('hold', 'release', 'cancel').
        reason: Optional human-readable reason for audit log.
        elevate: Positive confirmation to use administrative override.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(description="Target lifecycle action (hold, release, cancel)")
    elevate: bool = Field(
        default=False,
        description="Positive confirmation for administrative elevation",
    )
    reason: str | None = Field(
        default=None, description="Optional audit log explanation"
    )


class DashboardCollateralRequest(BaseModel):
    """Collateral upload staging request from Web Dashboard.

    Args:
        name: Logical collateral file name.
        size_bytes: Payload size in bytes.
        checksum_sha256: SHA-256 cryptographic digest.
        tier: Retention tier.
        kind: Artifact kind.
        target_path: Target path inside worker container.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    checksum_sha256: str = Field(description="SHA-256 cryptographic checksum")
    kind: CollateralKind = Field(
        default=CollateralKind.BUNDLE, description="Collateral artifact kind"
    )
    name: str = Field(description="Asset logical filename")
    size_bytes: int = Field(gt=0, description="Payload size in bytes")
    target_path: str = Field(default="", description="Target staging path on worker")
    tier: CollateralTier = Field(
        default=CollateralTier.TEMPORARY, description="Retention tier"
    )


class DashboardBastionRequest(BaseModel):
    """Bastion terminal session request on a worker node.

    Args:
        node_id: Target compute node worker identifier.
        session_id: Unique interactive session identifier.
        elevate: Explicit administrative elevation confirmation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False,
        description="Explicit administrative elevation confirmation",
    )
    node_id: str = Field(description="Target compute node worker ID")
    session_id: str = Field(default="", description="Optional session identifier")


class DashboardOverviewReport(BaseModel):
    """Aggregated dashboard cluster summary report.

    Args:
        total_jobs: Total registered jobs across all states.
        running_jobs: Currently executing jobs.
        pending_jobs: Pending or queued jobs waiting for execution.
        active_workers: Count of registered live worker nodes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_workers: int = Field(description="Count of live worker nodes")
    pending_jobs: int = Field(description="Queued or waiting jobs")
    running_jobs: int = Field(description="Active running jobs")
    total_jobs: int = Field(description="Total jobs in cluster")


__all__ = [
    "DashboardBastionRequest",
    "DashboardCollateralRequest",
    "DashboardJobAction",
    "DashboardOverviewReport",
    "DashboardUserSession",
]
