"""Domain models and operations for collateral staging and promotion."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralTier,
)


class IngestionRequest(BaseModel):
    """Request payload to initiate collateral registration.

    Args:
        job_id: ID of the job associated with this collateral.
        filename: Base filename of the artifact.
        size_bytes: Expected payload size in bytes.
        sha256_checksum: Hexadecimal SHA-256 digest string.
        kind: Classification kind (OS_IMAGE, CONTAINER_IMAGE, TEST_BINARY, DATASET, BUNDLE).
        tier: Retention tier (PERMANENT or TEMPORARY).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str = Field(description="Artifact filename")
    job_id: str = Field(description="Job identifier")
    kind: CollateralKind = Field(
        default=CollateralKind.BUNDLE, description="Collateral classification"
    )
    sha256_checksum: str = Field(
        min_length=64, max_length=64, description="Expected hex SHA-256 digest"
    )
    size_bytes: int = Field(ge=0, description="Payload size in bytes")
    tier: CollateralTier = Field(
        default=CollateralTier.TEMPORARY, description="Retention tier"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate request invariants."""
        if not self.job_id.strip():
            msg = "job_id cannot be empty"
            raise ValueError(msg)
        if not self.filename.strip():
            msg = "filename cannot be empty"
            raise ValueError(msg)
        return self


class StagedUploadDescriptor(BaseModel):
    """Upload target descriptor with presigned or local destination information.

    Args:
        bundle: Initial registered CollateralBundle.
        upload_url: Presigned PUT/POST URL or local file path destination.
        staging_path: Internal staging storage location.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle: CollateralBundle = Field(description="Registered collateral bundle")
    staging_path: str = Field(description="Internal staging filesystem path or URI")
    upload_url: str = Field(description="Direct upload endpoint or destination")


__all__ = [
    "IngestionRequest",
    "StagedUploadDescriptor",
]
