"""Tests for security, zero-trust, envelope encryption, and audit port interfaces."""

import inspect

import pytest

from hexaqueue_core.ports.security import (
    BoundaryAuditLoggerPort,
    EnvelopeEncryptionPort,
    SecurityQuarantinePort,
    SecurityScanResult,
    SpiffeAuthorizerPort,
    WorkloadIdentityPort,
)


def test_security_ports_are_abstract() -> None:
    """Verify security ports are abstract interfaces."""
    assert inspect.isabstract(SecurityQuarantinePort)
    assert inspect.isabstract(WorkloadIdentityPort)
    assert inspect.isabstract(SpiffeAuthorizerPort)
    assert inspect.isabstract(EnvelopeEncryptionPort)
    assert inspect.isabstract(BoundaryAuditLoggerPort)


def test_security_scan_result_model() -> None:
    """Verify SecurityScanResult validation."""
    clean = SecurityScanResult(is_clean=True, scanner_engine="clamav-1.0")
    clean_val = clean.is_clean
    assert clean_val is True

    infected = SecurityScanResult(
        is_clean=False, threat_name="Trojan.Generic", scanner_engine="clamav-1.0"
    )
    infected_val = infected.is_clean
    assert infected_val is False
    threat = infected.threat_name
    assert threat == "Trojan.Generic"

    with pytest.raises(ValueError, match="threat_name must be provided"):
        SecurityScanResult(is_clean=False, scanner_engine="clamav-1.0")

    with pytest.raises(ValueError, match="scanner_engine cannot be empty"):
        SecurityScanResult(is_clean=True, scanner_engine="   ")


def test_security_quarantine_port_abstract_methods() -> None:
    """Verify abstract methods on SecurityQuarantinePort."""
    expected = {"scan_collateral"}
    abstracts = SecurityQuarantinePort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0


def test_workload_identity_port_abstract_methods() -> None:
    """Verify abstract methods on WorkloadIdentityPort."""
    expected = {"fetch_jwt_svid", "get_spiffe_id", "validate_jwt_svid"}
    abstracts = WorkloadIdentityPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0


def test_spiffe_authorizer_port_abstract_methods() -> None:
    """Verify abstract methods on SpiffeAuthorizerPort."""
    expected = {"authorize"}
    abstracts = SpiffeAuthorizerPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0


def test_envelope_encryption_port_abstract_methods() -> None:
    """Verify abstract methods on EnvelopeEncryptionPort."""
    expected = {"decrypt", "encrypt"}
    abstracts = EnvelopeEncryptionPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0


def test_boundary_audit_logger_port_abstract_methods() -> None:
    """Verify abstract methods on BoundaryAuditLoggerPort."""
    expected = {"get_recent_records", "log_access"}
    abstracts = BoundaryAuditLoggerPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0
