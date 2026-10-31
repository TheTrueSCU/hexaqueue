"""Unit tests for scanner domain events."""

from hexaqueue_core.domain.collateral import CollateralState
from hexaqueue_scanner.domain.events import (
    CollateralApprovedEvent,
    CollateralQuarantinedEvent,
    CollateralRejectedEvent,
    SecurityScanCompletedEvent,
)


def test_security_scan_completed_event() -> None:
    """Verify SecurityScanCompletedEvent model validation."""
    event = SecurityScanCompletedEvent(
        collateral_id="col-001",
        state=CollateralState.APPROVED,
        is_clean=True,
        duration_seconds=0.12,
    )
    cid = event.collateral_id
    assert cid == "col-001"
    st = event.state
    assert st == CollateralState.APPROVED
    clean = event.is_clean
    assert clean is True
    dur = event.duration_seconds
    assert dur == 0.12


def test_collateral_approved_event() -> None:
    """Verify CollateralApprovedEvent fields."""
    event = CollateralApprovedEvent(
        collateral_id="col-002",
        sha256_checksum="a" * 64,
        active_uri="/var/hexaqueue/cas/active/file.tar",
        duration_seconds=0.5,
    )
    cid = event.collateral_id
    assert cid == "col-002"
    uri = event.active_uri
    assert uri == "/var/hexaqueue/cas/active/file.tar"
    sha = event.sha256_checksum
    assert len(sha) == 64


def test_collateral_quarantined_event() -> None:
    """Verify CollateralQuarantinedEvent fields."""
    event = CollateralQuarantinedEvent(
        collateral_id="col-bad",
        threat_name="Eicar-Test-Signature",
        scanner_engine="ClamAV",
        quarantine_uri="/var/hexaqueue/vault/quarantine/bad.bin",
    )
    cid = event.collateral_id
    assert cid == "col-bad"
    threat = event.threat_name
    assert threat == "Eicar-Test-Signature"
    engine = event.scanner_engine
    assert engine == "ClamAV"


def test_collateral_rejected_event() -> None:
    """Verify CollateralRejectedEvent fields."""
    event = CollateralRejectedEvent(
        collateral_id="col-corrupt",
        reason="Staged collateral file does not exist",
    )
    cid = event.collateral_id
    assert cid == "col-corrupt"
    reason = event.reason
    assert "does not exist" in reason
