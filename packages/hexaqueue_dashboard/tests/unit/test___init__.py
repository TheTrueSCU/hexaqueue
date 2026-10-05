"""Test hexaqueue_dashboard package exports."""

import hexaqueue_dashboard


def test_hexaqueue_dashboard_package_exports() -> None:
    """Verify package can be imported and exports expected symbols."""
    assert hexaqueue_dashboard is not None
    assert callable(hexaqueue_dashboard.create_dashboard_app)
    assert callable(hexaqueue_dashboard.create_dashboard_router)
