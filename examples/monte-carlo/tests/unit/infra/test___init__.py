"""Test infra exports."""

import monte_carlo.infra


def test_infra_exports() -> None:
    """Verify infra __all__."""
    assert hasattr(monte_carlo.infra, "load_monte_carlo_pipeline")
