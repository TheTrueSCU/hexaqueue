"""Local filesystem collateral staging and ingestion service adapter.

Notes/Architectural Intent:
    Implements full direct-to-disk staging, incremental SHA256 checksum
    verification, Content-Addressable Storage (CAS) deduplication, active
    job reference pinning, and least-recently-used (LRU) garbage collection eviction
    at ~/.hexaqueue/collateral/active/<sha256>/<filename>.
"""

import hashlib
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from hexaqueue_collateral.domain.models import IngestionRequest, StagedUploadDescriptor
from hexaqueue_collateral.ports.service import CollateralServicePort
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
    can_transition_collateral,
)
from hexaqueue_core.domain.exceptions import (
    ChecksumMismatchError,
    HexaqueueError,
)
from hexaqueue_core.ports.security import SecurityQuarantinePort
from hexaqueue_core.ports.storage import PresignedStoragePort


class LocalCollateralServiceAdapter(CollateralServicePort):
    """Local filesystem implementation of CollateralServicePort with CAS caching."""

    def __init__(
        self,
        base_dir: str | Path | None = None,
        security_port: SecurityQuarantinePort | None = None,
        storage_port: PresignedStoragePort | None = None,
    ) -> None:
        """Initialize local collateral service with storage directories.

        Args:
            base_dir: Base directory for collateral storage (defaults to ~/.hexaqueue/collateral).
            security_port: Optional security scanner port (defaults to NoOp if None).
            storage_port: Optional presigned storage port for upload link vending.
        """
        self._base_dir = (
            Path(base_dir) if base_dir else Path.home() / ".hexaqueue" / "collateral"
        )
        self._staging_dir = self._base_dir / "staging"
        self._active_dir = self._base_dir / "active"
        self._quarantine_dir = self._base_dir / "quarantine"

        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._staging_dir.mkdir(exist_ok=True)
        self._active_dir.mkdir(exist_ok=True)
        self._quarantine_dir.mkdir(exist_ok=True)

        self._security_port = security_port
        self._storage_port = storage_port
        self._bundles: dict[str, CollateralBundle] = {}

    async def register(self, request: IngestionRequest) -> StagedUploadDescriptor:
        """Register a new collateral artifact and prepare its staging descriptor.

        Args:
            request: IngestionRequest specification.

        Returns:
            StagedUploadDescriptor with target upload paths and cache hit indicator.

        Raises:
            HexaqueueError: If path traversal is detected in filename.

        Notes/Architectural Intent:
            Checks for an existing approved bundle matching the SHA-256 digest in CAS.
            If present in active storage, returns an immediate cache hit without re-staging.
        """
        # CAS Cache Deduplication Lookup
        existing = await self.find_by_checksum(request.sha256_checksum)
        if existing is not None and existing.state == CollateralState.APPROVED:
            touched = existing.touch()
            self._bundles[touched.id] = touched
            return StagedUploadDescriptor(
                bundle=touched,
                upload_url=f"file://{touched.active_uri}",
                staging_path=str(touched.active_uri),
                is_cache_hit=True,
            )

        collateral_id = f"col-{uuid4().hex[:10]}"
        safe_filename = Path(request.filename).name
        dest_staging_path = (
            self._staging_dir / collateral_id / safe_filename
        ).resolve()
        if not str(dest_staging_path).startswith(str(self._staging_dir.resolve())):
            msg = f"Path traversal detected in collateral filename: {request.filename}"
            raise HexaqueueError(msg)

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

        if self._storage_port is not None:
            upload_url = await self._storage_port.generate_presigned_upload_url(
                key=f"collateral/{collateral_id}/{safe_filename}"
            )
        else:
            upload_url = f"file://{dest_staging_path}"

        return StagedUploadDescriptor(
            bundle=bundle,
            upload_url=upload_url,
            staging_path=str(dest_staging_path),
            is_cache_hit=False,
        )

    async def stage_file(
        self,
        collateral_id: str,
        source: bytes | BinaryIO | Path | str,
    ) -> CollateralBundle:
        """Stage file contents directly and verify integrity against registered checksum."""
        bundle = await self.get_bundle(collateral_id)
        if bundle.state == CollateralState.APPROVED:
            return bundle

        if not can_transition_collateral(bundle.state, CollateralState.UPLOADED):
            msg = f"Cannot stage file: illegal state transition from {bundle.state} to UPLOADED"
            raise HexaqueueError(msg)

        dest_path = Path(bundle.staging_uri)
        dest_path.parent.mkdir(exist_ok=True)

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
            dest_path.unlink()
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
        if bundle.state == CollateralState.APPROVED:
            return bundle

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
            next_state, reason = (
                CollateralState.QUARANTINED,
                "No quarantine scanner configured; failing closed.",
            )

        staged_path = Path(bundle.staging_uri)

        if next_state == CollateralState.APPROVED:
            # Promote to CAS active storage: active/<sha256>/<filename>
            active_target_dir = self._active_dir / bundle.sha256_checksum
            active_target_dir.mkdir(exist_ok=True)
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
            quarantine_target_dir.mkdir(exist_ok=True)
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

    async def find_by_checksum(self, sha256_checksum: str) -> CollateralBundle | None:
        """Search Content-Addressable Storage for an existing approved bundle by digest."""
        clean_sha = sha256_checksum.lower().strip()
        for bundle in self._bundles.values():
            if (
                bundle.sha256_checksum.lower() == clean_sha
                and bundle.state == CollateralState.APPROVED
                and bundle.active_uri is not None
                and Path(bundle.active_uri).exists()
            ):
                return bundle

        # Disk discovery in active CAS directory
        target_dir = self._active_dir / clean_sha
        if target_dir.is_dir():
            files = list(target_dir.iterdir())
            if files:
                active_file = files[0]
                collateral_id = f"cas-{clean_sha[:12]}"
                discovered = CollateralBundle(
                    id=collateral_id,
                    job_id="cas-discovered",
                    filename=active_file.name,
                    size_bytes=active_file.stat().st_size,
                    sha256_checksum=clean_sha,
                    kind=CollateralKind.BUNDLE,
                    tier=CollateralTier.TEMPORARY,
                    state=CollateralState.APPROVED,
                    staging_uri=str(active_file),
                    active_uri=str(active_file),
                )
                self._bundles[collateral_id] = discovered
                return discovered
        return None

    async def pin_bundle(self, collateral_id: str) -> CollateralBundle:
        """Pin a collateral bundle to declare active usage by a running job."""
        bundle = await self.get_bundle(collateral_id)
        pinned = bundle.pin()
        self._bundles[collateral_id] = pinned
        return pinned

    async def unpin_bundle(self, collateral_id: str) -> CollateralBundle:
        """Unpin a collateral bundle upon job termination, release, or cancellation."""
        bundle = await self.get_bundle(collateral_id)
        try:
            unpinned = bundle.unpin()
        except ValueError as exc:
            raise HexaqueueError(str(exc)) from exc
        self._bundles[collateral_id] = unpinned
        return unpinned

    async def evict_expired(
        self,
        max_age_seconds: int | None = None,
        high_watermark_bytes: int | None = None,
    ) -> list[str]:
        """Evict eligible unpinned temporary collateral bundles based on TTL and LRU thresholds."""
        now = datetime.now(UTC)
        evicted_ids: list[str] = []

        # Find eligible candidates: TEMPORARY tier and active_pin_count == 0
        eligible = [
            b
            for b in self._bundles.values()
            if b.tier == CollateralTier.TEMPORARY
            and b.active_pin_count == 0
            and b.state == CollateralState.APPROVED
        ]

        # 1. TTL-based eviction
        if max_age_seconds is not None:
            cutoff = now - timedelta(seconds=max_age_seconds)
            for b in list(eligible):
                if b.last_accessed_at < cutoff:
                    self._purge_bundle(b)
                    evicted_ids.append(b.id)
                    eligible.remove(b)

        # 2. High-watermark LRU eviction
        if high_watermark_bytes is not None:
            # Calculate current total storage of active temporary bundles
            total_bytes = sum(
                b.size_bytes
                for b in self._bundles.values()
                if b.tier == CollateralTier.TEMPORARY
            )
            if total_bytes > high_watermark_bytes:
                # Sort eligible candidates by last_accessed_at ascending (oldest first)
                eligible.sort(key=lambda b: b.last_accessed_at)
                for b in eligible:
                    if total_bytes <= high_watermark_bytes:
                        break
                    self._purge_bundle(b)
                    evicted_ids.append(b.id)
                    total_bytes -= b.size_bytes

        return evicted_ids

    def _purge_bundle(self, bundle: CollateralBundle) -> None:
        """Purge bundle files from disk and remove from memory registry."""
        if bundle.active_uri:
            active_path = Path(bundle.active_uri)
            if active_path.exists():
                active_path.unlink()
                # Remove parent hash directory if empty
                parent_dir = active_path.parent
                if parent_dir.is_dir() and not any(parent_dir.iterdir()):
                    parent_dir.rmdir()
        if bundle.id in self._bundles:
            del self._bundles[bundle.id]


__all__ = [
    "LocalCollateralServiceAdapter",
]
