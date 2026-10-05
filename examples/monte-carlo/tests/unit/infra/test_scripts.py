"""Tests for Monte-Carlo infra scripts."""

from pathlib import Path

from monte_carlo.infra.scripts import get_monte_carlo_script_path


def test_get_monte_carlo_script_path() -> None:
    """Verify collateral script path resolution."""
    script_path = get_monte_carlo_script_path()
    assert isinstance(script_path, Path)
    assert script_path.name == "cli.py"
    assert script_path.is_file()
