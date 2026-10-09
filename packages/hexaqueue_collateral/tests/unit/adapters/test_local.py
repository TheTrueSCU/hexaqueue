"""Unit tests for LocalCollateralServiceAdapter."""

import hashlib
import tempfile
from pathlib import Path

import pytest

from hexaqueue_collateral.adapters.local import LocalCollateralServiceAdapter
from hexaqueue_collateral.domain.models import IngestionRequest
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.domain.exceptions import (
    ChecksumMismatchError,
    HexaqueueError,
)
from hexaqueue_core.ports.security import SecurityQuarantinePort


class ThreatDetectingScanner(SecurityQuarantinePort):
    """Mock scanner returning QUARANTINED state for threat testing."""

    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Flag bundle as quarantined."""
        return CollateralState.QUARANTINED, "Eicar-Test-Signature detected"


class BenignScanner(SecurityQuarantinePort):
    """Mock scanner returning APPROVED state for clean testing."""

    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Flag bundle as approved."""
        return CollateralState.APPROVED, None


@pytest.mark.asyncio
async def test_local_collateral_end_to_end_promotion():
    """Verify complete lifecycle: register -> stage -> scan -> approved promotion."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(
            base_dir=tmpdir, security_port=BenignScanner()
        )

        content = b"print('Hello Machine Learning World')\n"
        sha256 = hashlib.sha256(content).hexdigest()

        # 1. Registration
        request = IngestionRequest(
            job_id="job-101",
            filename="script.py",
            size_bytes=len(content),
            sha256_checksum=sha256,
            kind=CollateralKind.BUNDLE,
            tier=CollateralTier.TEMPORARY,
        )
        descriptor = await service.register(request)
        bundle_id = descriptor.bundle.id
        assert descriptor.bundle.state == CollateralState.REGISTERED

        # 2. Staging with bytes
        uploaded_bundle = await service.stage_file(bundle_id, content)
        assert uploaded_bundle.state == CollateralState.UPLOADED
        assert Path(uploaded_bundle.staging_uri).exists()

        # Overwrite existing staging file cleanly (tests dest_path.unlink)
        uploaded_bundle_again = await service.stage_file(bundle_id, content)
        assert uploaded_bundle_again.state == CollateralState.UPLOADED

        # 3. Quarantine processing (clean) -> APPROVED
        approved_bundle = await service.process_quarantine(bundle_id)
        assert approved_bundle.state == CollateralState.APPROVED
        assert approved_bundle.active_uri is not None
        assert Path(approved_bundle.active_uri).exists()
        assert Path(approved_bundle.active_uri).parent.name == sha256
        assert Path(approved_bundle.active_uri).name == "script.py"
        assert Path(approved_bundle.active_uri).read_bytes() == content

        # Second promotion to existing active CAS directory (tests active_target_dir exist_ok=True)
        req2 = IngestionRequest(
            job_id="job-102",
            filename="script.py",
            size_bytes=len(content),
            sha256_checksum=sha256,
        )
        desc2 = await service.register(req2)
        await service.stage_file(desc2.bundle.id, content)
        approved2 = await service.process_quarantine(desc2.bundle.id)
        assert approved2.state == CollateralState.APPROVED


@pytest.mark.asyncio
async def test_local_collateral_staging_from_file_path():
    """Verify staging file from local source path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(base_dir=tmpdir)

        src_file = Path(tmpdir) / "source_data.csv"
        content = b"col1,col2\n1,2\n3,4\n"
        src_file.write_bytes(content)
        sha256 = hashlib.sha256(content).hexdigest()

        request = IngestionRequest(
            job_id="job-202",
            filename="data.csv",
            size_bytes=len(content),
            sha256_checksum=sha256,
        )
        descriptor = await service.register(request)
        uploaded = await service.stage_file(descriptor.bundle.id, src_file)
        assert uploaded.state == CollateralState.UPLOADED
        uploaded2 = await service.stage_file(descriptor.bundle.id, src_file)
        assert uploaded2.state == CollateralState.UPLOADED


@pytest.mark.asyncio
async def test_local_collateral_checksum_mismatch():
    """Verify corrupted upload raises ChecksumMismatchError and marks bundle REJECTED."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(base_dir=tmpdir)

        expected_sha = "0" * 64
        request = IngestionRequest(
            job_id="job-303",
            filename="corrupted.bin",
            size_bytes=10,
            sha256_checksum=expected_sha,
        )
        desc = await service.register(request)

        with pytest.raises(ChecksumMismatchError, match="Checksum mismatch"):
            await service.stage_file(desc.bundle.id, b"tampered content")

        bundle = await service.get_bundle(desc.bundle.id)
        assert bundle.state == CollateralState.REJECTED
        assert "SHA-256 checksum mismatch" in (bundle.quarantine_reason or "")


@pytest.mark.asyncio
async def test_local_collateral_quarantined_threat():
    """Verify threat detection isolates file to quarantine directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        scanner = ThreatDetectingScanner()
        service = LocalCollateralServiceAdapter(base_dir=tmpdir, security_port=scanner)

        content = (
            b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        )
        sha256 = hashlib.sha256(content).hexdigest()

        request = IngestionRequest(
            job_id="job-virus",
            filename="malware.com",
            size_bytes=len(content),
            sha256_checksum=sha256,
        )
        desc = await service.register(request)
        await service.stage_file(desc.bundle.id, content)

        # Pre-create quarantine directory to verify exist_ok=True resilience
        pre_existing_quarantine_dir = service._quarantine_dir / desc.bundle.id
        pre_existing_quarantine_dir.mkdir(exist_ok=True)

        quarantined = await service.process_quarantine(desc.bundle.id)
        assert quarantined.state == CollateralState.QUARANTINED
        assert "Eicar" in (quarantined.quarantine_reason or "")
        assert Path(quarantined.staging_uri).exists()
        assert Path(quarantined.staging_uri).parent.name == desc.bundle.id
        assert Path(quarantined.staging_uri).name == "malware.com"
        assert "quarantine" in quarantined.staging_uri


class RejectingScanner(SecurityQuarantinePort):
    """Mock scanner returning REJECTED state for policy rejection testing."""

    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Flag bundle as rejected by security policy."""
        return CollateralState.REJECTED, "Policy violation: forbidden binary format"


@pytest.mark.asyncio
async def test_local_collateral_staging_from_io_stream():
    """Verify staging file from an in-memory BinaryIO stream."""
    import io

    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(base_dir=tmpdir)

        content = b"streamed binary data payload"
        sha256 = hashlib.sha256(content).hexdigest()

        request = IngestionRequest(
            job_id="job-stream",
            filename="payload.bin",
            size_bytes=len(content),
            sha256_checksum=sha256,
        )
        desc = await service.register(request)
        stream = io.BytesIO(content)
        uploaded = await service.stage_file(desc.bundle.id, stream)
        assert uploaded.state == CollateralState.UPLOADED


@pytest.mark.asyncio
async def test_local_collateral_scan_rejected():
    """Verify policy rejection sets bundle to REJECTED."""
    with tempfile.TemporaryDirectory() as tmpdir:
        scanner = RejectingScanner()
        service = LocalCollateralServiceAdapter(base_dir=tmpdir, security_port=scanner)

        content = b"executable data"
        sha256 = hashlib.sha256(content).hexdigest()

        request = IngestionRequest(
            job_id="job-rej",
            filename="exec.bin",
            size_bytes=len(content),
            sha256_checksum=sha256,
        )
        desc = await service.register(request)
        await service.stage_file(desc.bundle.id, content)

        rejected = await service.process_quarantine(desc.bundle.id)
        assert rejected.state == CollateralState.REJECTED
        assert "Policy violation" in (rejected.quarantine_reason or "")


@pytest.mark.asyncio
async def test_local_collateral_not_found():
    """Verify HexaqueueError on unknown collateral ID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(base_dir=tmpdir)
        with pytest.raises(
            HexaqueueError, match="Collateral with id 'non-existent' not found"
        ):
            await service.get_bundle("non-existent")


def test_local_collateral_default_base_dir() -> None:
    """Verify default base directory resolution and directory hierarchy."""
    service = LocalCollateralServiceAdapter(base_dir=None)
    assert service._base_dir == Path.home() / ".hexaqueue" / "collateral"
    assert service._staging_dir == service._base_dir / "staging"
    assert service._active_dir == service._base_dir / "active"
    assert service._quarantine_dir == service._base_dir / "quarantine"
    assert service._staging_dir.exists()
    assert service._active_dir.exists()
    assert service._quarantine_dir.exists()


def test_local_collateral_nested_and_reinitialize(tmp_path: Path) -> None:
    """Verify initialization creates missing nested parents and survives pre-existing directories."""
    nested_dir = tmp_path / "deep" / "nested" / "collateral"
    # 1. Missing parents must be created (parents=True)
    service1 = LocalCollateralServiceAdapter(base_dir=nested_dir)
    assert service1._staging_dir.exists()
    assert service1._active_dir.exists()
    assert service1._quarantine_dir.exists()

    # 2. Existing directories must not raise FileExistsError (exist_ok=True)
    service2 = LocalCollateralServiceAdapter(base_dir=nested_dir)
    assert service2._staging_dir.exists()


@pytest.mark.asyncio
async def test_local_collateral_no_scanner_fails_closed() -> None:
    """Verify that absent scanner fails closed and quarantines collateral."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(base_dir=tmpdir, security_port=None)
        content = b"print('Hello World')\n"
        sha256 = hashlib.sha256(content).hexdigest()
        req = IngestionRequest(
            job_id="job-999",
            filename="unscanned.py",
            size_bytes=len(content),
            sha256_checksum=sha256,
        )
        desc = await service.register(req)
        await service.stage_file(desc.bundle.id, content)
        quarantined = await service.process_quarantine(desc.bundle.id)
        assert quarantined.state == CollateralState.QUARANTINED
        reason = quarantined.quarantine_reason or ""
        assert "No quarantine scanner configured" in reason


@pytest.mark.asyncio
async def test_local_collateral_cas_deduplication_cache_hit():
    """Verify Content-Addressable Storage (CAS) deduplication returns immediate cache hit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(
            base_dir=tmpdir, security_port=BenignScanner()
        )
        content = b"def model_inference(): return 42\n"
        sha256 = hashlib.sha256(content).hexdigest()

        # Initial ingestion & approval
        req1 = IngestionRequest(
            job_id="job-first",
            filename="inference.py",
            size_bytes=len(content),
            sha256_checksum=sha256,
            tier=CollateralTier.TEMPORARY,
        )
        desc1 = await service.register(req1)
        assert desc1.is_cache_hit is False

        await service.stage_file(desc1.bundle.id, content)
        approved1 = await service.process_quarantine(desc1.bundle.id)
        assert approved1.state == CollateralState.APPROVED

        # Second registration with identical SHA-256
        req2 = IngestionRequest(
            job_id="job-second",
            filename="inference.py",
            size_bytes=len(content),
            sha256_checksum=sha256,
            tier=CollateralTier.TEMPORARY,
        )
        desc2 = await service.register(req2)
        assert desc2.is_cache_hit is True
        assert desc2.bundle.id == desc1.bundle.id
        assert desc2.bundle.state == CollateralState.APPROVED
        assert desc2.bundle.access_count >= 1

        # Direct stage and quarantine calls are idempotent on approved bundle
        staged_again = await service.stage_file(desc2.bundle.id, content)
        assert staged_again.state == CollateralState.APPROVED
        quarantined_again = await service.process_quarantine(desc2.bundle.id)
        assert quarantined_again.state == CollateralState.APPROVED


@pytest.mark.asyncio
async def test_local_collateral_pin_and_unpin_lifecycle():
    """Verify active job reference pinning and unpinning mechanics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(
            base_dir=tmpdir, security_port=BenignScanner()
        )
        content = b"binary payload\n"
        sha256 = hashlib.sha256(content).hexdigest()

        req = IngestionRequest(
            job_id="job-pin-test",
            filename="binary.bin",
            size_bytes=len(content),
            sha256_checksum=sha256,
        )
        desc = await service.register(req)
        await service.stage_file(desc.bundle.id, content)
        bundle = await service.process_quarantine(desc.bundle.id)

        pin_initial = bundle.active_pin_count
        assert pin_initial == 0

        # Pin for job 1
        pinned1 = await service.pin_bundle(bundle.id)
        assert pinned1.active_pin_count == 1

        # Pin for job 2 (concurrent reference)
        pinned2 = await service.pin_bundle(bundle.id)
        assert pinned2.active_pin_count == 2

        # Job 1 finishes -> unpin
        unpinned1 = await service.unpin_bundle(bundle.id)
        assert unpinned1.active_pin_count == 1

        # Job 2 finishes -> unpin
        unpinned2 = await service.unpin_bundle(bundle.id)
        assert unpinned2.active_pin_count == 0

        # Unpinning beyond zero must fail
        with pytest.raises(HexaqueueError, match="active_pin_count is already 0"):
            await service.unpin_bundle(bundle.id)


@pytest.mark.asyncio
async def test_local_collateral_eviction_ttl_and_pin_protection():
    """Verify TTL cache eviction purges expired bundles while protecting pinned and permanent ones."""
    from datetime import UTC, datetime, timedelta

    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(
            base_dir=tmpdir, security_port=BenignScanner()
        )

        # 1. Ephemeral unpinned bundle (eligible for TTL eviction)
        content_a = b"temporary unpinned\n"
        sha_a = hashlib.sha256(content_a).hexdigest()
        desc_a = await service.register(
            IngestionRequest(
                job_id="job-a",
                filename="temp_a.bin",
                size_bytes=len(content_a),
                sha256_checksum=sha_a,
                tier=CollateralTier.TEMPORARY,
            )
        )
        await service.stage_file(desc_a.bundle.id, content_a)
        await service.process_quarantine(desc_a.bundle.id)

        # 2. Ephemeral pinned bundle (protected by active pin)
        content_b = b"temporary pinned\n"
        sha_b = hashlib.sha256(content_b).hexdigest()
        desc_b = await service.register(
            IngestionRequest(
                job_id="job-b",
                filename="temp_b.bin",
                size_bytes=len(content_b),
                sha256_checksum=sha_b,
                tier=CollateralTier.TEMPORARY,
            )
        )
        await service.stage_file(desc_b.bundle.id, content_b)
        await service.process_quarantine(desc_b.bundle.id)
        await service.pin_bundle(desc_b.bundle.id)

        # 3. Permanent bundle (exempt from GC)
        content_c = b"permanent golden image\n"
        sha_c = hashlib.sha256(content_c).hexdigest()
        desc_c = await service.register(
            IngestionRequest(
                job_id="job-c",
                filename="perm_c.bin",
                size_bytes=len(content_c),
                sha256_checksum=sha_c,
                tier=CollateralTier.PERMANENT,
            )
        )
        await service.stage_file(desc_c.bundle.id, content_c)
        await service.process_quarantine(desc_c.bundle.id)

        # Artificially age all bundles to 100 seconds in the past
        past_time = datetime.now(UTC) - timedelta(seconds=100)
        service._bundles[desc_a.bundle.id] = service._bundles[
            desc_a.bundle.id
        ].model_copy(update={"last_accessed_at": past_time})
        service._bundles[desc_b.bundle.id] = service._bundles[
            desc_b.bundle.id
        ].model_copy(update={"last_accessed_at": past_time})
        service._bundles[desc_c.bundle.id] = service._bundles[
            desc_c.bundle.id
        ].model_copy(update={"last_accessed_at": past_time})

        # Evict with max_age_seconds=60
        evicted = await service.evict_expired(max_age_seconds=60)

        # Only bundle A must be evicted
        assert desc_a.bundle.id in evicted
        assert desc_b.bundle.id not in evicted
        assert desc_c.bundle.id not in evicted

        # Active path for bundle A must be deleted
        assert not Path(service._active_dir / sha_a / "temp_a.bin").exists()
        # Active paths for B and C must still exist
        assert Path(service._active_dir / sha_b / "temp_b.bin").exists()
        assert Path(service._active_dir / sha_c / "perm_c.bin").exists()


@pytest.mark.asyncio
async def test_local_collateral_eviction_high_watermark_lru():
    """Verify high-watermark LRU eviction reclaims oldest unpinned temporary bundles first."""
    from datetime import UTC, datetime, timedelta

    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(
            base_dir=tmpdir, security_port=BenignScanner()
        )

        async def create_bundle(name: str, size: int, age_seconds: int) -> str:
            content = b"x" * size
            sha = hashlib.sha256(content).hexdigest()
            desc = await service.register(
                IngestionRequest(
                    job_id=f"job-{name}",
                    filename=f"{name}.bin",
                    size_bytes=size,
                    sha256_checksum=sha,
                    tier=CollateralTier.TEMPORARY,
                )
            )
            await service.stage_file(desc.bundle.id, content)
            await service.process_quarantine(desc.bundle.id)
            bundle_time = datetime.now(UTC) - timedelta(seconds=age_seconds)
            service._bundles[desc.bundle.id] = service._bundles[
                desc.bundle.id
            ].model_copy(update={"last_accessed_at": bundle_time})
            return desc.bundle.id

        # Bundle 1: 1000 bytes, 30s old (oldest)
        id1 = await create_bundle("bundle1", 1000, 30)
        # Bundle 2: 2000 bytes, 20s old (middle)
        id2 = await create_bundle("bundle2", 2000, 20)
        # Bundle 3: 3000 bytes, 10s old (newest)
        id3 = await create_bundle("bundle3", 3000, 10)

        # Total size = 6000 bytes. High watermark = 3500 bytes.
        # Should evict bundle1 (1000b -> 5000b) then bundle2 (2000b -> 3000b <= 3500b).
        evicted = await service.evict_expired(high_watermark_bytes=3500)

        assert id1 in evicted
        assert id2 in evicted
        assert id3 not in evicted
        assert id3 in service._bundles


@pytest.mark.asyncio
async def test_local_collateral_with_presigned_storage() -> None:
    """Verify LocalCollateralServiceAdapter vends presigned upload URLs when configured."""
    from hexaqueue_core.adapters.storage.presigned import (
        InMemoryPresignedStorageAdapter,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_port = InMemoryPresignedStorageAdapter(
            endpoint_url="https://s3.example.com"
        )
        service = LocalCollateralServiceAdapter(
            base_dir=tmpdir,
            storage_port=storage_port,
        )

        content = b"presigned payload data"
        sha256 = hashlib.sha256(content).hexdigest()

        request = IngestionRequest(
            job_id="job-presigned-1",
            filename="artifact.tar.gz",
            size_bytes=len(content),
            sha256_checksum=sha256,
        )
        desc = await service.register(request)
        url = desc.upload_url
        is_hit = desc.is_cache_hit

        assert is_hit is False
        assert url.startswith("https://s3.example.com/upload/collateral/")
        assert "artifact.tar.gz" in url
