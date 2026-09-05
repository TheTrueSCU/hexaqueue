"""Collateral and artifact lifecycle domain models.

Notes/Architectural Intent:
    Defines the states and invariant models for job collateral bundles.
    Collateral flows through an isolated quarantine pipeline before promotion
    to active compute storage.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CollateralState(StrEnum):
    r"""Lifecycle states for uploaded job collateral bundles.

    State Progression:
        REGISTERED -> UPLOADED -> SCANNING -> APPROVED -> [Clean Active Storage]
                                           \-> QUARANTINED (Threat detected / isolated)
                                           \-> REJECTED (Policy/MIME/Checksum violation)
    """

    REGISTERED = "REGISTERED"
    UPLOADED = "UPLOADED"
    SCANNING = "SCANNING"
    APPROVED = "APPROVED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class CollateralBundle(BaseModel):
    """Domain model representing a job collateral bundle.

    Args:
        id: Unique collateral bundle identifier.
        job_id: Associated job identifier.
        filename: Original submitted filename.
        size_bytes: Size in bytes of the collateral.
        sha256_checksum: Hex-encoded SHA-256 checksum.
        state: Current collateral lifecycle state.
        staging_uri: Isolated quarantine/staging object storage URI.
        active_uri: Verified clean storage URI (set only upon APPROVED state).
        quarantine_reason: Reason if QUARANTINED or REJECTED.
        created_at: Creation timestamp in UTC.
        updated_at: Last state update timestamp in UTC.

    Raises:
        ValueError: If active_uri is set prior to APPROVED state or if state
            transitions violate domain invariants.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Unique collateral identifier")
    job_id: str = Field(description="Associated job ID")
    filename: str = Field(description="Original filename")
    size_bytes: int = Field(ge=0, description="Size in bytes")
    sha256_checksum: str = Field(description="SHA-256 digest")
    state: CollateralState = Field(
        default=CollateralState.REGISTERED, description="Lifecycle state"
    )
    staging_uri: str = Field(description="Quarantine / staging URI")
    active_uri: str | None = Field(default=None, description="Clean active storage URI")
    quarantine_reason: str | None = Field(
        default=None, description="Reason if quarantined or rejected"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate state invariants."""
        if self.state != CollateralState.APPROVED and self.active_uri is not None:
            msg = f"active_uri can only be set when state is APPROVED, got {self.state}"
            raise ValueError(msg)
        if (
            self.state in (CollateralState.QUARANTINED, CollateralState.REJECTED)
            and not self.quarantine_reason
        ):
            msg = f"quarantine_reason must be provided when state is {self.state}"
            raise ValueError(msg)
        return self
