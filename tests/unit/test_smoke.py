"""Smoke tests for workspace packages."""

import hexaqueue
import hexaqueue_cli
import hexaqueue_collateral
import hexaqueue_core
import hexaqueue_dashboard
import hexaqueue_github_runner
import hexaqueue_gitlab_runner
import hexaqueue_kueue
import hexaqueue_monitor
import hexaqueue_scanner
import hexaqueue_server
import hexaqueue_worker
import hexaqueue_workflow


def test_packages_importable():
    """Verify all workspace package entrypoints can be imported."""
    assert hexaqueue is not None
    assert hexaqueue_cli is not None
    assert hexaqueue_collateral is not None
    assert hexaqueue_core is not None
    assert hexaqueue_dashboard is not None
    assert hexaqueue_github_runner is not None
    assert hexaqueue_gitlab_runner is not None
    assert hexaqueue_kueue is not None
    assert hexaqueue_monitor is not None
    assert hexaqueue_scanner is not None
    assert hexaqueue_server is not None
    assert hexaqueue_worker is not None
    assert hexaqueue_workflow is not None
