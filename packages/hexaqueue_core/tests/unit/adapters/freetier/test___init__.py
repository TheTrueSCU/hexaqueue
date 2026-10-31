"""Test freetier adapters package exports."""

import hexaqueue_core.adapters.freetier as freetier


def test_freetier_adapters_exports() -> None:
    """Verify freetier adapters exports."""
    exports = freetier.__all__
    assert "MultiCspFreeTierGovernor" in exports
    assert "NaiveFreeTierMeshOracle" in exports
