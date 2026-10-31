"""Domain security lifecycle and quarantine audit events.

Notes/Architectural Intent:
    Defines immutable domain events emitted during the collateral scanning,
    quarantine isolation, and active CAS storage promotion lifecycle.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.collateral import CollateralState


class SecurityScanCompletedEvent(BaseModel):
    """Event emitted whenever a collateral security scan completes.

    Args:
        collateral_id: Identifier of the examined collateral bundle.
        state: Resulting CollateralState (APPROVED, QUARANTINED, or REJECTED).
        is_clean: True if all scan engines passed with zero threat detections.
        duration_seconds: Wall-clock inspection duration in seconds.
        timestamp: Event occurrence timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    collateral_id: str = Field(description="Collateral bundle identifier")
    duration_seconds: float = Field(ge=0.0, description="Scan execution duration")
    is_clean: bool = Field(description="True if artifact is safe and clean")
    state: CollateralState = Field(description="Resulting collateral lifecycle state")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event emission timestamp",
    )


class CollateralApprovedEvent(BaseModel):
    """Event emitted when clean collateral is promoted to active storage.

    Args:
        collateral_id: Identifier of the promoted collateral bundle.
        sha256_checksum: Cryptographic digest in Content-Addressable Storage (CAS).
        active_uri: Verified active storage URI accessible to compute workers.
        duration_seconds: Scan duration before approval.
        timestamp: Event emission timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_uri: str = Field(description="Active CAS storage URI")
    collateral_id: str = Field(description="Collateral bundle identifier")
    duration_seconds: float = Field(ge=0.0, description="Scan duration before approval")
    sha256_checksum: str = Field(description="SHA-256 CAS digest")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Approval event timestamp",
    )


class CollateralQuarantinedEvent(BaseModel):
    """Event emitted when a threat is identified and collateral is isolated in quarantine vault.

    Args:
        collateral_id: Identifier of the quarantined collateral bundle.
        threat_name: Name or signature of the detected virus/malware.
        scanner_engine: Scanning engine that detected the threat.
        quarantine_uri: Storage location in isolated quarantine vault.
        timestamp: Event emission timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    collateral_id: str = Field(description="Collateral bundle identifier")
    quarantine_uri: str = Field(description="Isolated quarantine vault path")
    scanner_engine: str = Field(description="Scanning engine that flagged the threat")
    threat_name: str = Field(description="Detected malware signature or threat name")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Quarantine isolation timestamp",
    )


class CollateralRejectedEvent(BaseModel):
    """Event emitted when collateral is rejected due to policy, checksum, or format error.

    Args:
        collateral_id: Identifier of the rejected collateral bundle.
        reason: Explanation of the rejection or policy violation.
        timestamp: Event emission timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    collateral_id: str = Field(description="Collateral bundle identifier")
    reason: str = Field(description="Reason for artifact rejection")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Rejection event timestamp",
    )


__all__ = [
    "CollateralApprovedEvent",
    "CollateralQuarantinedEvent",
    "CollateralRejectedEvent",
    "SecurityScanCompletedEvent",
]
