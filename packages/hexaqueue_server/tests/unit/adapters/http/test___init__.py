"""Unit tests for hexaqueue_server.adapters.http package exports."""

from hexaqueue_server.adapters import http as http_pkg


def test_http_adapter_exports() -> None:
    """Verify public HTTP adapter exports and alphabetical __all__ sorting."""
    exported = list(http_pkg.__all__)
    assert exported == [
        "HttpCollateralServiceAdapter",
        "HttpSchedulerControllerAdapter",
    ]
    has_collateral = hasattr(http_pkg, "HttpCollateralServiceAdapter")
    has_controller = hasattr(http_pkg, "HttpSchedulerControllerAdapter")
    collateral_name = http_pkg.HttpCollateralServiceAdapter.__name__
    controller_name = http_pkg.HttpSchedulerControllerAdapter.__name__
    assert has_collateral is True
    assert has_controller is True
    assert collateral_name == "HttpCollateralServiceAdapter"
    assert controller_name == "HttpSchedulerControllerAdapter"
