"""Unit tests for CollateralServicePort interface."""

import inspect

import pytest

from hexaqueue_collateral.ports.service import CollateralServicePort


def test_collateral_service_port_operations_defined() -> None:
    """Verify CollateralServicePort defines expected abstract operations."""
    assert hasattr(CollateralServicePort, "register")
    assert hasattr(CollateralServicePort, "stage_file")
    assert hasattr(CollateralServicePort, "process_quarantine")
    assert hasattr(CollateralServicePort, "get_bundle")
    assert hasattr(CollateralServicePort, "find_by_checksum")
    assert hasattr(CollateralServicePort, "get_download_url")
    assert hasattr(CollateralServicePort, "pin_bundle")
    assert hasattr(CollateralServicePort, "unpin_bundle")
    assert hasattr(CollateralServicePort, "evict_expired")


def test_collateral_service_port_is_abstract() -> None:
    """Verify that CollateralServicePort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(CollateralServicePort)
    assert is_abs is True
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        CollateralServicePort()  # ty: ignore[call-non-callable] # type: ignore[abstract]


def test_collateral_service_port_abstract_methods() -> None:
    """Verify abstract methods on CollateralServicePort."""
    expected = {
        "evict_expired",
        "find_by_checksum",
        "get_bundle",
        "get_download_url",
        "pin_bundle",
        "process_quarantine",
        "register",
        "stage_file",
        "unpin_bundle",
    }
    abstracts = CollateralServicePort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0
