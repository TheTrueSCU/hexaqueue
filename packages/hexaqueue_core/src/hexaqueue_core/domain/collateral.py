"""Collateral and artifact lifecycle domain models.

Notes/Architectural Intent:
    Defines the states, kinds, retention tiers, and invariant models for job
    collateral bundles. Collateral flows through an isolated direct-to-object-store
    quarantine pipeline before promotion to clean active compute storage.
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


class CollateralTier(StrEnum):
    """Retention tier for collateral in Content-Addressable Storage (CAS).

    Tiers:
        PERMANENT: Golden images, prod base environments, and datasets exempt from GC.
        TEMPORARY: Ephemeral development binaries and PR builds subject to LRU eviction.
    """

    PERMANENT = "PERMANENT"
    TEMPORARY = "TEMPORARY"


class CollateralKind(StrEnum):
    """Categorical classification of the collateral payload."""

    OS_IMAGE = "OS_IMAGE"
    CONTAINER_IMAGE = "CONTAINER_IMAGE"
    TEST_BINARY = "TEST_BINARY"
    DATASET = "DATASET"
    BUNDLE = "BUNDLE"


VALID_COLLATERAL_TRANSITIONS: dict[CollateralState, set[CollateralState]] = {
    CollateralState.REGISTERED: {CollateralState.UPLOADED, CollateralState.REJECTED},
    CollateralState.UPLOADED: {CollateralState.SCANNING, CollateralState.REJECTED},
    CollateralState.SCANNING: {
        CollateralState.APPROVED,
        CollateralState.QUARANTINED,
        CollateralState.REJECTED,
    },
    CollateralState.APPROVED: set(),
    CollateralState.QUARANTINED: set(),
    CollateralState.REJECTED: set(),
}


def can_transition_collateral(
    from_state: CollateralState, to_state: CollateralState
) -> bool:
    """Verify if a collateral state transition is legally permissible.

    Args:
        from_state: Current state of the collateral bundle.
        to_state: Target transition state.

    Returns:
        True if the transition is allowed by the lifecycle state machine, False otherwise.
    """
    if from_state == to_state:
        return True
    return to_state in VALID_COLLATERAL_TRANSITIONS.get(from_state, set())


class CollateralBundle(BaseModel):
    """Domain model representing a job collateral bundle in CAS.

    Args:
        id: Unique collateral bundle identifier (e.g. 'col_84920').
        job_id: Associated job identifier.
        filename: Original submitted filename.
        size_bytes: Size in bytes of the collateral.
        sha256_checksum: Hex-encoded expected SHA-256 checksum digest.
        kind: Categorical classification (OS_IMAGE, CONTAINER_IMAGE, etc.).
        tier: Retention tier (PERMANENT vs TEMPORARY).
        state: Current collateral lifecycle state.
        staging_uri: Isolated quarantine/staging object storage URI.
        active_uri: Verified clean storage URI (set only upon APPROVED state).
        quarantine_reason: Reason if QUARANTINED or REJECTED.
        active_pin_count: Number of running jobs actively referencing this bundle.
        created_at: Creation timestamp in UTC.
        updated_at: Last state update timestamp in UTC.

    Raises:
        ValueError: If active_uri is set prior to APPROVED state or if state
            invariants are violated.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Unique collateral identifier")
    job_id: str = Field(description="Associated job ID")
    filename: str = Field(description="Original filename")
    size_bytes: int = Field(ge=0, description="Size in bytes")
    sha256_checksum: str = Field(
        min_length=64, max_length=64, description="Hex SHA-256 digest"
    )
    kind: CollateralKind = Field(
        default=CollateralKind.BUNDLE, description="Classification kind"
    )
    tier: CollateralTier = Field(
        default=CollateralTier.TEMPORARY, description="Retention tier"
    )
    state: CollateralState = Field(
        default=CollateralState.REGISTERED, description="Lifecycle state"
    )
    staging_uri: str = Field(description="Quarantine / staging URI")
    active_uri: str | None = Field(default=None, description="Clean active storage URI")
    quarantine_reason: str | None = Field(
        default=None, description="Reason if quarantined or rejected"
    )
    active_pin_count: int = Field(
        default=0, ge=0, description="Active job pin reference count"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate state and URI invariants.

        Returns:
            The validated CollateralBundle instance.

        Raises:
            ValueError: If active_uri is present when not APPROVED, or if
                quarantine_reason is missing when in QUARANTINED/REJECTED state.
        """
        if self.state != CollateralState.APPROVED and self.active_uri is not None:
            msg = f"active_uri can only be set when state is APPROVED, got {self.state}"
            raise ValueError(msg)

        if self.state == CollateralState.APPROVED and self.active_uri is None:
            msg = "active_uri must be provided when state is APPROVED"
            raise ValueError(msg)

        if (
            self.state in (CollateralState.QUARANTINED, CollateralState.REJECTED)
            and not self.quarantine_reason
        ):
            msg = f"quarantine_reason must be provided when state is {self.state}"
            raise ValueError(msg)

        return self
