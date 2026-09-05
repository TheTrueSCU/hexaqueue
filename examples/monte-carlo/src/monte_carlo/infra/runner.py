"""Pipeline loader for Monte-Carlo simulation example."""

from pathlib import Path

from hexaqueue_cli.domain.parser import parse_run_spec_from_file
from hexaqueue_server.domain.models import RunSubmission


def load_monte_carlo_pipeline(file_path: str | Path | None = None) -> RunSubmission:
    """Load and parse the Monte-Carlo simulation workflow DAG spec."""
    path = (
        Path(file_path)
        if file_path
        else Path(__file__).parent.parent.parent.parent
        / "pipelines"
        / "monte_carlo_simulation.yaml"
    )
    return parse_run_spec_from_file(path)


__all__ = [
    "load_monte_carlo_pipeline",
]
