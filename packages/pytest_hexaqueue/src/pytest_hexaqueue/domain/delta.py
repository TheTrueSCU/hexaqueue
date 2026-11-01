"""Domain models for workspace delta snapshotting and content-addressed test code synchronization.

Notes/Architectural Intent:
    Captures file manifests and cryptographic SHA-256 hashes of test source code,
    enabling incremental delta synchronization to remote cluster workers via
    Hexaqueue Collateral CAS storage without syncing unmodified files.
"""

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceDeltaBundle(BaseModel):
    """Manifest of workspace files and cryptographic SHA-256 content digests.

    Args:
        bundle_id: Content-addressed identifier (hexadecimal SHA-256).
        git_commit: Optional base Git commit SHA.
        file_hashes: Mapping of relative file paths to their SHA-256 checksums.
        total_files: Total count of files included in the delta bundle.
        total_bytes: Total size of all files in bytes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_id: str = Field(description="Content-addressed bundle SHA-256 digest")
    file_hashes: dict[str, str] = Field(
        default_factory=dict, description="Relative file paths to SHA-256 digests"
    )
    git_commit: str | None = Field(
        default=None, description="Current Git head commit hash"
    )
    total_bytes: int = Field(ge=0, description="Total size in bytes")
    total_files: int = Field(ge=0, description="Total files count")


__all__ = [
    "WorkspaceDeltaBundle",
]
