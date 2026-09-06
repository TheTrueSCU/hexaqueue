"""Test domain exports."""

from monte_carlo.domain.models import (
    SimulationParameters,
    SmoothedSurface,
    TrajectorySample,
)


def test_domain_exports() -> None:
    """Verify domain models are available."""
    assert SimulationParameters is not None
    assert TrajectorySample is not None
    assert SmoothedSurface is not None
