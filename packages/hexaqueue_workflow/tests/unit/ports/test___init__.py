"""Tests for ports package exports."""

import hexaqueue_workflow.ports as ports_pkg


def test_ports_exports() -> None:
    """Verify all expected ports are exported."""
    expected = [
        "ArtifactStagingPort",
    ]
    exports = ports_pkg.__all__
    assert exports == sorted(expected)
