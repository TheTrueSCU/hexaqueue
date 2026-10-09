"""Domain models and operations for collateral staging and promotion."""

from pathlib import Path
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
        ttl_seconds: Optional custom time-to-live in seconds for TEMPORARY collateral.
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
    ttl_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Optional custom time-to-live in seconds for TEMPORARY collateral",
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
        cleaned_name = Path(self.filename.strip()).name
        if (
            not cleaned_name
            or cleaned_name != self.filename.strip()
            or ".." in self.filename
            or "/" in self.filename
            or "\\" in self.filename
        ):
            msg = "filename must be a valid relative filename without directory traversal components"
            raise ValueError(msg)
        return self


class StagedUploadDescriptor(BaseModel):
    """Upload target descriptor with presigned or local destination information.

    Args:
        bundle: Initial registered CollateralBundle.
        upload_url: Presigned PUT/POST URL or local file path destination.
        staging_path: Internal staging filesystem path or URI.
        is_cache_hit: Whether an identical approved bundle was reused from CAS.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle: CollateralBundle = Field(description="Registered collateral bundle")
    staging_path: str = Field(description="Internal staging filesystem path or URI")
    upload_url: str = Field(description="Direct upload endpoint or destination")
    is_cache_hit: bool = Field(
        default=False,
        description="Whether identical approved bundle was found in CAS",
    )

    @property
    def collateral_id(self) -> str:
        """Convenience property returning the unique collateral bundle identifier."""
        return self.bundle.id


__all__ = [
    "IngestionRequest",
    "StagedUploadDescriptor",
]
