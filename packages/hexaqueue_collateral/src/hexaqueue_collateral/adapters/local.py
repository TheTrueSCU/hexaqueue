"""Local filesystem collateral staging and ingestion service adapter.

Notes/Architectural Intent:
    Implements full direct-to-disk staging, incremental SHA256 checksum
    verification, and promotion to verified content-addressable active storage
    located at ~/.hexaqueue/collateral/active/<sha256>/<filename>.
"""

import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from hexaqueue_collateral.domain.models import IngestionRequest, StagedUploadDescriptor
from hexaqueue_collateral.ports.service import CollateralServicePort
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralState,
    can_transition_collateral,
)
from hexaqueue_core.domain.exceptions import (
    ChecksumMismatchError,
    HexaqueueError,
)
from hexaqueue_core.ports.security import SecurityQuarantinePort


class LocalCollateralServiceAdapter(CollateralServicePort):
    """Local filesystem implementation of CollateralServicePort."""

    def __init__(
        self,
        base_dir: str | Path | None = None,
        security_port: SecurityQuarantinePort | None = None,
    ) -> None:
        """Initialize local collateral service with storage directories.

        Args:
            base_dir: Base directory for collateral storage (defaults to ~/.hexaqueue/collateral).
            security_port: Optional security scanner port (defaults to NoOp if None).
        """
        self._base_dir = (
            Path(base_dir) if base_dir else Path.home() / ".hexaqueue" / "collateral"
        )
        self._staging_dir = self._base_dir / "staging"
        self._active_dir = self._base_dir / "active"
        self._quarantine_dir = self._base_dir / "quarantine"

        self._staging_dir.mkdir(parents=True, exist_ok=True)
        self._active_dir.mkdir(parents=True, exist_ok=True)
        self._quarantine_dir.mkdir(parents=True, exist_ok=True)

        self._security_port = security_port
        self._bundles: dict[str, CollateralBundle] = {}

    async def register(self, request: IngestionRequest) -> StagedUploadDescriptor:
        """Register a new collateral artifact and prepare its staging descriptor."""
        collateral_id = f"col-{uuid4().hex[:10]}"
        dest_staging_path = self._staging_dir / collateral_id / request.filename

        bundle = CollateralBundle(
            id=collateral_id,
            job_id=request.job_id,
            filename=request.filename,
            size_bytes=request.size_bytes,
            sha256_checksum=request.sha256_checksum,
            kind=request.kind,
            tier=request.tier,
            state=CollateralState.REGISTERED,
            staging_uri=str(dest_staging_path),
            active_uri=None,
        )
        self._bundles[collateral_id] = bundle

        return StagedUploadDescriptor(
            bundle=bundle,
            upload_url=f"file://{dest_staging_path}",
            staging_path=str(dest_staging_path),
        )

    async def stage_file(
        self,
        collateral_id: str,
        source: bytes | BinaryIO | Path | str,
    ) -> CollateralBundle:
        """Stage file contents directly and verify integrity against registered checksum."""
        bundle = await self.get_bundle(collateral_id)
        if not can_transition_collateral(bundle.state, CollateralState.UPLOADED):
            msg = f"Cannot stage file: illegal state transition from {bundle.state} to UPLOADED"
            raise HexaqueueError(msg)

        dest_path = Path(bundle.staging_uri)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        hasher = hashlib.sha256()
        actual_size = 0

        if isinstance(source, bytes):
            hasher.update(source)
            actual_size = len(source)
            dest_path.write_bytes(source)
        elif isinstance(source, (str, Path)) and Path(source).is_file():
            src_path = Path(source)
            with src_path.open("rb") as f_in, dest_path.open("wb") as f_out:
                while chunk := f_in.read(65536):
                    hasher.update(chunk)
                    actual_size += len(chunk)
                    f_out.write(chunk)
        elif hasattr(source, "read"):
            reader = source.read
            with dest_path.open("wb") as f_out:
                while True:
                    raw_chunk = reader(65536)  # ty: ignore
                    if not raw_chunk:
                        break
                    chunk = (
                        raw_chunk.encode("utf-8")
                        if isinstance(raw_chunk, str)
                        else bytes(raw_chunk)
                    )
                    hasher.update(chunk)
                    actual_size += len(chunk)
                    f_out.write(chunk)
        else:
            msg = f"Unsupported source type for collateral staging: {type(source)}"
            raise HexaqueueError(msg)

        actual_sha = hasher.hexdigest()
        if actual_sha.lower() != bundle.sha256_checksum.lower():
            # Checksum mismatch: reject bundle and cleanup staging
            dest_path.unlink(missing_ok=True)
            rejected_bundle = CollateralBundle(
                id=bundle.id,
                job_id=bundle.job_id,
                filename=bundle.filename,
                size_bytes=actual_size,
                sha256_checksum=bundle.sha256_checksum,
                kind=bundle.kind,
                tier=bundle.tier,
                state=CollateralState.REJECTED,
                staging_uri=bundle.staging_uri,
                quarantine_reason=f"SHA-256 checksum mismatch: expected {bundle.sha256_checksum}, got {actual_sha}",
            )
            self._bundles[collateral_id] = rejected_bundle
            msg = f"Checksum mismatch for collateral '{collateral_id}'"
            raise ChecksumMismatchError(msg)

        uploaded_bundle = CollateralBundle(
            id=bundle.id,
            job_id=bundle.job_id,
            filename=bundle.filename,
            size_bytes=actual_size,
            sha256_checksum=bundle.sha256_checksum,
            kind=bundle.kind,
            tier=bundle.tier,
            state=CollateralState.UPLOADED,
            staging_uri=bundle.staging_uri,
        )
        self._bundles[collateral_id] = uploaded_bundle
        return uploaded_bundle

    async def process_quarantine(self, collateral_id: str) -> CollateralBundle:
        """Execute security inspection and promote or isolate collateral."""
        bundle = await self.get_bundle(collateral_id)
        if bundle.state != CollateralState.UPLOADED:
            msg = f"Cannot process quarantine for collateral in state {bundle.state}"
            raise HexaqueueError(msg)

        # Scanning phase
        scanning_bundle = CollateralBundle(
            id=bundle.id,
            job_id=bundle.job_id,
            filename=bundle.filename,
            size_bytes=bundle.size_bytes,
            sha256_checksum=bundle.sha256_checksum,
            kind=bundle.kind,
            tier=bundle.tier,
            state=CollateralState.SCANNING,
            staging_uri=bundle.staging_uri,
        )
        self._bundles[collateral_id] = scanning_bundle

        if self._security_port:
            next_state, reason = await self._security_port.scan_collateral(
                scanning_bundle
            )
        else:
            next_state, reason = CollateralState.APPROVED, None

        staged_path = Path(bundle.staging_uri)

        if next_state == CollateralState.APPROVED:
            # Promote to CAS active storage: active/<sha256>/<filename>
            active_target_dir = self._active_dir / bundle.sha256_checksum
            active_target_dir.mkdir(parents=True, exist_ok=True)
            active_path = active_target_dir / bundle.filename
            shutil.copy2(staged_path, active_path)

            approved_bundle = CollateralBundle(
                id=bundle.id,
                job_id=bundle.job_id,
                filename=bundle.filename,
                size_bytes=bundle.size_bytes,
                sha256_checksum=bundle.sha256_checksum,
                kind=bundle.kind,
                tier=bundle.tier,
                state=CollateralState.APPROVED,
                staging_uri=bundle.staging_uri,
                active_uri=str(active_path),
            )
            self._bundles[collateral_id] = approved_bundle
            return approved_bundle

        if next_state == CollateralState.QUARANTINED:
            quarantine_target_dir = self._quarantine_dir / bundle.id
            quarantine_target_dir.mkdir(parents=True, exist_ok=True)
            quarantine_path = quarantine_target_dir / bundle.filename
            shutil.move(staged_path, quarantine_path)

            quarantined_bundle = CollateralBundle(
                id=bundle.id,
                job_id=bundle.job_id,
                filename=bundle.filename,
                size_bytes=bundle.size_bytes,
                sha256_checksum=bundle.sha256_checksum,
                kind=bundle.kind,
                tier=bundle.tier,
                state=CollateralState.QUARANTINED,
                staging_uri=str(quarantine_path),
                quarantine_reason=reason or "Threat detected during security scan",
            )
            self._bundles[collateral_id] = quarantined_bundle
            return quarantined_bundle

        # Rejected
        rejected_bundle = CollateralBundle(
            id=bundle.id,
            job_id=bundle.job_id,
            filename=bundle.filename,
            size_bytes=bundle.size_bytes,
            sha256_checksum=bundle.sha256_checksum,
            kind=bundle.kind,
            tier=bundle.tier,
            state=CollateralState.REJECTED,
            staging_uri=bundle.staging_uri,
            quarantine_reason=reason or "Security scan rejected artifact",
        )
        self._bundles[collateral_id] = rejected_bundle
        return rejected_bundle

    async def get_bundle(self, collateral_id: str) -> CollateralBundle:
        """Retrieve current metadata and status of a collateral bundle."""
        if collateral_id not in self._bundles:
            msg = f"Collateral with id '{collateral_id}' not found"
            raise HexaqueueError(msg)
        return self._bundles[collateral_id]


__all__ = [
    "LocalCollateralServiceAdapter",
]
