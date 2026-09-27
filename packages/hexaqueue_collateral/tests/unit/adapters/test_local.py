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


@pytest.mark.asyncio
async def test_local_collateral_end_to_end_promotion():
    """Verify complete lifecycle: register -> stage -> scan -> approved promotion."""
    with tempfile.TemporaryDirectory() as tmpdir:
        service = LocalCollateralServiceAdapter(base_dir=tmpdir)

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
