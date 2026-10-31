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
    assert reason is not None
    assert "Win.Trojan.Generic" in reason


def test_scanner_metrics_calculation() -> None:
    """Verify ScannerMetrics properties and averages."""
    from hexaqueue_scanner.domain.models import ScannerMetrics

    metrics = ScannerMetrics(
        total_scans=10,
        approved_scans=8,
        quarantined_scans=1,
        rejected_scans=1,
        error_scans=0,
        total_duration_seconds=5.0,
    )
    total = metrics.total_scans
    assert total == 10
    approved = metrics.approved_scans
    assert approved == 8
    avg = metrics.average_duration_seconds
    assert avg == 0.5

    empty_metrics = ScannerMetrics()
    empty_avg = empty_metrics.average_duration_seconds
    assert empty_avg == 0.0
