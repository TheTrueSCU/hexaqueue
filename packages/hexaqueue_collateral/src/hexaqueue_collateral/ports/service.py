"""Collateral ingestion and lifecycle service port interface."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from hexaqueue_collateral.domain.models import IngestionRequest, StagedUploadDescriptor
from hexaqueue_core.domain.collateral import CollateralBundle


class CollateralServicePort(ABC):
    """Abstract port for collateral ingestion, checksum audit, and active promotion."""

    @abstractmethod
    async def register(self, request: IngestionRequest) -> StagedUploadDescriptor:
        """Register a new collateral artifact and prepare its staging descriptor.

        Args:
            request: IngestionRequest with metadata, expected SHA256, and size.

        Returns:
            StagedUploadDescriptor with registered bundle and target destination.
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


__all__ = [
    "CollateralServicePort",
]
