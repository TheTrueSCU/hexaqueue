"""Collateral ingestion and lifecycle service port interface.

Notes/Architectural Intent:
    Defines the contracts for registering, staging, scanning, pinning, and
    evicting Content-Addressable Storage (CAS) collateral bundles.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from hexaqueue_collateral.domain.models import IngestionRequest, StagedUploadDescriptor
from hexaqueue_core.domain.collateral import CollateralBundle


class CollateralServicePort(ABC):
    """Abstract port for collateral ingestion, checksum audit, active promotion, and CAS cache lifecycle.

    Notes/Architectural Intent:
        Enforces Content-Addressable Storage (CAS) deduplication, active execution
        pinning, and least-recently-used (LRU) garbage collection eviction while
        guaranteeing that running jobs and permanent golden images are immune to deletion.
    """

    @abstractmethod
    async def register(self, request: IngestionRequest) -> StagedUploadDescriptor:
        """Register a new collateral artifact and prepare its staging descriptor.

        Args:
            request: IngestionRequest with metadata, expected SHA256, and size.

        Returns:
            StagedUploadDescriptor with registered bundle and target destination.

        Raises:
            HexaqueueError: If path traversal is detected or registration fails.

        Notes/Architectural Intent:
            Checks for existing approved bundles matching the SHA-256 digest in CAS.
            If found, returns an immediate cache hit, skipping re-upload and re-scan.
        """

    @abstractmethod
    async def stage_file(
        self,
        collateral_id: str,
        source: bytes | BinaryIO | Path | str,
    ) -> CollateralBundle:
        """Stage file contents directly and verify integrity against registered checksum.

        Args:
            collateral_id: Registered collateral identifier.
            source: Raw bytes, binary stream, or path to source file.

        Returns:
            Updated CollateralBundle in UPLOADED or REJECTED state.

        Raises:
            ChecksumMismatchError: If actual stream SHA256 does not match expected SHA256.
            HexaqueueError: If collateral is not found or in invalid state.
        """

    @abstractmethod
    async def process_quarantine(self, collateral_id: str) -> CollateralBundle:
        """Execute security inspection and promote or isolate collateral.

        Args:
            collateral_id: Uploaded collateral identifier to scan.

        Returns:
            Promoted CollateralBundle in APPROVED or QUARANTINED state.

        Raises:
            HexaqueueError: If collateral is not found or in illegal state.
        """

    @abstractmethod
    async def get_bundle(self, collateral_id: str) -> CollateralBundle:
        """Retrieve current metadata and status of a collateral bundle.

        Args:
            collateral_id: Collateral identifier.

        Returns:
            The CollateralBundle instance.

        Raises:
            HexaqueueError: If collateral is not found.
        """

    @abstractmethod
    async def find_by_checksum(self, sha256_checksum: str) -> CollateralBundle | None:
        """Search Content-Addressable Storage for an existing approved bundle by digest.

        Args:
            sha256_checksum: Hexadecimal 64-character SHA-256 digest.

        Returns:
            Matching approved CollateralBundle if present in CAS active storage, or None.
        """

    @abstractmethod
    async def get_download_url(self, collateral_id: str) -> str:
        """Vend a download URL or verified file URI for an approved collateral bundle.

        Args:
            collateral_id: Collateral bundle identifier.

        Returns:
            Direct presigned download URL or verified local file URI.

        Raises:
            HexaqueueError: If collateral is not found or not in APPROVED state.

        Notes/Architectural Intent:
            Enforces that compute workers can only access verified clean collateral
            that has successfully cleared quarantine scanning.
        """

    @abstractmethod
    async def pin_bundle(self, collateral_id: str) -> CollateralBundle:
        """Pin a collateral bundle to declare active usage by a running job.

        Args:
            collateral_id: Collateral bundle identifier.

        Returns:
            Updated CollateralBundle with incremented active_pin_count.

        Raises:
            HexaqueueError: If collateral is not found.

        Notes/Architectural Intent:
            Pinned bundles are strictly protected from garbage collection eviction.
        """

    @abstractmethod
    async def unpin_bundle(self, collateral_id: str) -> CollateralBundle:
        """Unpin a collateral bundle upon job termination, release, or cancellation.

        Args:
            collateral_id: Collateral bundle identifier.

        Returns:
            Updated CollateralBundle with decremented active_pin_count.

        Raises:
            HexaqueueError: If collateral is not found or pin count is already zero.
        """

    @abstractmethod
    async def evict_expired(
        self,
        max_age_seconds: int | None = None,
        high_watermark_bytes: int | None = None,
    ) -> list[str]:
        """Evict eligible unpinned temporary collateral bundles based on TTL and LRU thresholds.

        Args:
            max_age_seconds: Optional maximum age in seconds since last access.
            high_watermark_bytes: Optional storage threshold above which LRU bundles are purged.

        Returns:
            List of evicted collateral IDs.

        Notes/Architectural Intent:
            Strict safety invariant: Bundles with active_pin_count > 0 or
            tier == CollateralTier.PERMANENT are never evicted.
        """


__all__ = [
    "CollateralServicePort",
]
