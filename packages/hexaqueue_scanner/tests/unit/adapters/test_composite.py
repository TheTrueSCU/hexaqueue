"""Unit tests for CompositeQuarantineScannerAdapter."""

from pathlib import Path

import pytest

from hexaqueue_core.domain.collateral import CollateralBundle, CollateralState
from hexaqueue_core.ports.security import SecurityScanResult
from hexaqueue_scanner.adapters.composite import CompositeQuarantineScannerAdapter
from hexaqueue_scanner.domain.config import ScannerConfig
from hexaqueue_scanner.ports.engine import MalwareScannerEnginePort


class MockEngine(MalwareScannerEnginePort):
    """Configurable mock malware engine for composite testing."""

    def __init__(
        self,
        name: str,
        is_clean: bool = True,
        threat_name: str | None = None,
    ) -> None:
        self._name = name
        self._is_clean = is_clean
        self._threat_name = threat_name

    async def scan_file(self, file_path: Path) -> SecurityScanResult:
        """Return configured scan result."""
        return SecurityScanResult(
            is_clean=self._is_clean,
            scanner_engine=self._name,
            threat_name=self._threat_name,
        )

    async def ping(self) -> bool:
        """Return healthy."""
        return True


def _make_bundle(staging_path: Path) -> CollateralBundle:
    """Helper to create CollateralBundle for local path."""
    return CollateralBundle(
        id="col-local-1",
        job_id="job-1",
        filename=staging_path.name,
        size_bytes=staging_path.stat().st_size if staging_path.exists() else 100,
        sha256_checksum="f" * 64,
        staging_uri=f"file://{staging_path.absolute()}",
    )


@pytest.mark.asyncio
async def test_composite_all_clean(tmp_path: Path) -> None:
    """Verify all engines reporting clean maps to APPROVED."""
    f = tmp_path / "app.tar.gz"
    f.write_text("clean data")
    bundle = _make_bundle(f)

    e1 = MockEngine("Engine-1", is_clean=True)
    e2 = MockEngine("Engine-2", is_clean=True)
    adapter = CompositeQuarantineScannerAdapter(engines=[e1, e2])

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.APPROVED
    assert reason is None


@pytest.mark.asyncio
async def test_composite_threat_quarantined(tmp_path: Path) -> None:
    """Verify threat detected triggers QUARANTINED state."""
    f = tmp_path / "malicious.zip"
    f.write_text("malware content")
    bundle = _make_bundle(f)

    e1 = MockEngine("ClamAV", is_clean=False, threat_name="Trojan.Dropper")
    e2 = MockEngine("YARA", is_clean=True)
    adapter = CompositeQuarantineScannerAdapter(engines=[e1, e2])

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.QUARANTINED
    assert reason is not None
    has_engine = "ClamAV" in reason
    assert has_engine is True
    has_trojan = "Trojan.Dropper" in reason
    assert has_trojan is True


@pytest.mark.asyncio
async def test_composite_threat_rejected_policy(tmp_path: Path) -> None:
    """Verify quarantine_on_threat=False maps threat to REJECTED."""
    f = tmp_path / "bad.bin"
    f.write_text("bad")
    bundle = _make_bundle(f)

    cfg = ScannerConfig(quarantine_on_threat=False)
    e1 = MockEngine("PolicyScanner", is_clean=False, threat_name="DisallowedExecutable")
    adapter = CompositeQuarantineScannerAdapter(engines=[e1], config=cfg)

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.REJECTED
    assert reason is not None
    has_reason = "DisallowedExecutable" in reason
    assert has_reason is True


@pytest.mark.asyncio
async def test_composite_missing_staged_file() -> None:
    """Verify missing file returns REJECTED."""
    missing = Path("/tmp/nonexistent-bundle-file-xyz.tar")
    bundle = CollateralBundle(
        id="col-missing",
        job_id="job-1",
        filename="missing.tar",
        size_bytes=0,
        sha256_checksum="0" * 64,
        staging_uri=str(missing),
    )
    adapter = CompositeQuarantineScannerAdapter()

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.REJECTED
    assert reason is not None
    has_not_exist = "does not exist" in reason
    assert has_not_exist is True


@pytest.mark.asyncio
async def test_composite_generate_report(tmp_path: Path) -> None:
    """Verify detailed CompositeScanReport generation."""
    f = tmp_path / "pkg.whl"
    f.write_text("wheel binary")
    bundle = _make_bundle(f)

    e1 = MockEngine("EngineA", is_clean=True)
    e2 = MockEngine("EngineB", is_clean=False, threat_name="HighEntropyPayload")
    adapter = CompositeQuarantineScannerAdapter(engines=[e1, e2])

    report = await adapter.generate_report(bundle)
    cid = report.collateral_id
    assert cid == bundle.id
    clean = report.is_clean
    assert clean is False
    res_count = len(report.results)
    assert res_count == 2
    reason = report.quarantine_reason
    assert reason is not None
    has_entropy = "HighEntropyPayload" in reason
    assert has_entropy is True
    dur = report.duration_seconds
    assert dur >= 0.0


@pytest.mark.asyncio
async def test_composite_generate_report_missing_file() -> None:
    """Verify generate_report handles missing file gracefully."""
    bundle = CollateralBundle(
        id="col-lost",
        job_id="job-1",
        filename="lost.bin",
        size_bytes=0,
        sha256_checksum="1" * 64,
        staging_uri="/tmp/lost-file-never-created.bin",
    )
    adapter = CompositeQuarantineScannerAdapter()

    report = await adapter.generate_report(bundle)
    clean = report.is_clean
    assert clean is False
    reason = report.quarantine_reason
    assert reason is not None
    has_missing = "Staged file missing" in reason
    assert has_missing is True
