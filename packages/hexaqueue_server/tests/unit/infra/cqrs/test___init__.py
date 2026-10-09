"""Tests for infra.cqrs package exports."""

import hexaqueue_server.infra.cqrs as cqrs_pkg


def test_cqrs_package_exports() -> None:
    """Verify package public API exports."""
    all_exports = cqrs_pkg.__all__
    assert "create_hexaqueue_execution_pipeline" in all_exports
    assert "HexaqueueCqrsService" in all_exports
    assert "run_coro_sync" in all_exports
