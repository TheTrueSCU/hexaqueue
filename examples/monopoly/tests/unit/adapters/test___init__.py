"""Test adapters package exports."""

import monopoly.adapters


def test_adapters_exports() -> None:
    """Verify adapters package __all__."""
    has_sim = hasattr(monopoly.adapters, "BatchSchedulerClusterSimulator")
    assert has_sim is True
