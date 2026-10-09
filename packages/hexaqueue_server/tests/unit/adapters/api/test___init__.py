"""Tests for hexaqueue_server.adapters.api package exports."""

from hexaqueue_server.adapters.api import (
    create_server_api_router,
    create_server_app,
    get_auth_context,
)


def test_api_package_exports() -> None:
    """Verify api package exports required public symbols."""
    assert callable(create_server_api_router)
    assert callable(create_server_app)
    assert callable(get_auth_context)
