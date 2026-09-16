"""Tests for engines adapters package exports."""

import hexaqueue_workflow.adapters.engines as engines_pkg


def test_engines_exports() -> None:
    """Verify all expected engine adapters are exported."""
    expected = [
        "HexaqueueDistributedEngine",
    ]
    exports = engines_pkg.__all__
    assert exports == sorted(expected)
