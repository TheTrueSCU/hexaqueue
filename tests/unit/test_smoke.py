"""Smoke tests for workspace packages."""

import hexaqueue
import hexaqueue_cli
import hexaqueue_collateral
import hexaqueue_core
import hexaqueue_dashboard
import hexaqueue_monitor
import hexaqueue_scanner
import hexaqueue_server
import hexaqueue_worker


def test_packages_importable():
    """Verify all workspace package entrypoints can be imported."""
    assert hexaqueue is not None
    assert hexaqueue_cli is not None
    assert hexaqueue_collateral is not None
    assert hexaqueue_core is not None
    assert hexaqueue_dashboard is not None
    assert hexaqueue_monitor is not None
    assert hexaqueue_scanner is not None
    assert hexaqueue_server is not None
    assert hexaqueue_worker is not None
