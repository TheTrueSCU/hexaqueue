"""Collateral execution scripts for Monte-Carlo simulation pipelines."""

from pathlib import Path


def get_monte_carlo_script_path() -> Path:
    """Return the absolute Path to the common Monte-Carlo collateral runner script."""
    return Path(__file__).parent.parent / "cli.py"


__all__ = [
    "get_monte_carlo_script_path",
]
