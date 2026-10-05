"""Unit tests for CollateralServicePort interface."""

from hexaqueue_collateral.ports.service import CollateralServicePort


def test_collateral_service_port_is_abstract():
    """Verify CollateralServicePort defines expected abstract operations."""
    assert hasattr(CollateralServicePort, "register")
    assert hasattr(CollateralServicePort, "stage_file")
    assert hasattr(CollateralServicePort, "process_quarantine")
    assert hasattr(CollateralServicePort, "get_bundle")
