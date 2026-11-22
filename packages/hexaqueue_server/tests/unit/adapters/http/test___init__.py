"""Unit tests for hexaqueue_server.adapters.http package exports."""

import hexaqueue_server.adapters.http as http_pkg
from hexaqueue_server.adapters.http import (
    HttpCollateralServiceAdapter,
    HttpSchedulerControllerAdapter,
)


def test_http_adapter_exports() -> None:
    """Verify public HTTP adapter exports and alphabetical __all__ sorting."""
    exported = list(http_pkg.__all__)
    assert exported == [
        "HttpCollateralServiceAdapter",
        "HttpSchedulerControllerAdapter",
    ]
    assert http_pkg.HttpCollateralServiceAdapter is HttpCollateralServiceAdapter
    assert http_pkg.HttpSchedulerControllerAdapter is HttpSchedulerControllerAdapter
