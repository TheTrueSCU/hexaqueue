"""Test domain exports."""

import monte_carlo.domain


def test_domain_exports() -> None:
    """Verify domain __all__."""
    assert hasattr(monte_carlo.domain, "SimulationParameters")
    assert hasattr(monte_carlo.domain, "TrajectorySample")
    assert hasattr(monte_carlo.domain, "SmoothedSurface")
