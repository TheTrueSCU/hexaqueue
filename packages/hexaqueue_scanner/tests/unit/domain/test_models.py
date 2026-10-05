"""Unit tests for scanner domain models."""

from hexaqueue_core.ports.security import SecurityScanResult
from hexaqueue_scanner.domain.models import CompositeScanReport


def test_composite_scan_report_clean() -> None:
    """Verify clean CompositeScanReport construction."""
    res1 = SecurityScanResult(
        is_clean=True,
        scanner_engine="ClamAV-daemon",
    )
    res2 = SecurityScanResult(
        is_clean=True,
        scanner_engine="YARA-engine",
    )
    report = CompositeScanReport(
        collateral_id="col-001",
        is_clean=True,
        duration_seconds=0.45,
        results=[res1, res2],
    )
    cid = report.collateral_id
    assert cid == "col-001"
    clean = report.is_clean
    assert clean is True
    dur = report.duration_seconds
    assert dur == 0.45
    cnt = len(report.results)
    assert cnt == 2
    reason = report.quarantine_reason
    assert reason is None


def test_composite_scan_report_threat() -> None:
    """Verify threat CompositeScanReport construction."""
    res1 = SecurityScanResult(
        is_clean=False,
        threat_name="Win.Trojan.Generic",
        scanner_engine="ClamAV-daemon",
    )
    report = CompositeScanReport(
        collateral_id="col-bad",
        is_clean=False,
        duration_seconds=1.2,
        results=[res1],
        quarantine_reason="Threat detected by ClamAV: Win.Trojan.Generic",
    )
    clean = report.is_clean
    assert clean is False
    reason = report.quarantine_reason
    assert reason == "Threat detected by ClamAV: Win.Trojan.Generic"
