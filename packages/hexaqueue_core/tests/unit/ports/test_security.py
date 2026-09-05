"""Unit tests for security port models and contracts."""

import pytest
from hexaqueue_core.ports.security import SecurityScanResult


def test_security_scan_result_valid():
    """Verify clean SecurityScanResult creation."""
    res = SecurityScanResult(
        is_clean=True,
        scanner_engine="MockScanner-1.0",
    )
    assert res.is_clean is True
    assert res.threat_name is None


def test_security_scan_result_infected():
    """Verify infected scan result requires threat_name."""
    res = SecurityScanResult(
        is_clean=False,
        threat_name="Eicar-Test-Signature",
        scanner_engine="ClamAV-1.4.0",
    )
    assert res.is_clean is False
    assert res.threat_name == "Eicar-Test-Signature"

    with pytest.raises(ValueError, match="threat_name must be provided when artifact is not clean"):
        SecurityScanResult(
            is_clean=False,
            threat_name=None,
            scanner_engine="ClamAV",
        )
