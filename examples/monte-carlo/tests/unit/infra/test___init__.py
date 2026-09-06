"""Test infra exports."""

from monte_carlo.infra.builder import build_monte_carlo_programmatic_pipeline
from monte_carlo.infra.runner import load_monte_carlo_pipeline
from monte_carlo.infra.scripts import get_monte_carlo_script_path


def test_infra_exports() -> None:
    """Verify infra runners and builders are available."""
    assert build_monte_carlo_programmatic_pipeline is not None
    assert get_monte_carlo_script_path is not None
    assert load_monte_carlo_pipeline is not None
