"""Test infra exports."""

from monte_carlo.infra.runner import load_monte_carlo_pipeline


def test_infra_exports() -> None:
    """Verify infra runners are available."""
    assert load_monte_carlo_pipeline is not None
