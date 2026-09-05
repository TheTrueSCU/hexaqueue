"""Tests for SecurityQuarantinePort and SecurityScanResult."""

import pytest

from hexaqueue_core.ports.security import SecurityQuarantinePort, SecurityScanResult


def test_security_quarantine_port_is_abstract() -> None:
    """Verify SecurityQuarantinePort cannot be instantiated directly."""
    with pytest.raises(TypeError):
        SecurityQuarantinePort()  # type: ignore[abstract]


def test_security_scan_result_model() -> None:
    """Verify SecurityScanResult validation."""
    clean = SecurityScanResult(is_clean=True, scanner_engine="clamav-1.0")
    assert clean.is_clean is True

    infected = SecurityScanResult(
        is_clean=False, threat_name="Trojan.Generic", scanner_engine="clamav-1.0"
    )
    assert infected.is_clean is False
    assert infected.threat_name == "Trojan.Generic"

    with pytest.raises(ValueError, match="threat_name must be provided"):
        SecurityScanResult(is_clean=False, scanner_engine="clamav-1.0")

    with pytest.raises(ValueError, match="scanner_engine cannot be empty"):
        SecurityScanResult(is_clean=True, scanner_engine="   ")
