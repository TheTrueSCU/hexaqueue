"""Tests for staging adapters package exports."""

import hexaqueue_workflow.adapters.staging as staging_pkg


def test_staging_exports() -> None:
    """Verify all expected staging adapters are exported."""
    expected = [
        "StoragePortArtifactStagingAdapter",
    ]
    exports = staging_pkg.__all__
    assert exports == sorted(expected)
