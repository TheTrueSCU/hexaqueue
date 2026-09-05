"""Pipeline runner helper for data pipeline tutorial."""

from pathlib import Path

from hexaqueue_cli.domain.parser import parse_run_spec_from_file
from hexaqueue_server.domain.models import RunSubmission


def load_etl_pipeline(file_path: str | Path | None = None) -> RunSubmission:
    """Load and parse the ETL DAG pipeline spec."""
    path = (
        Path(file_path)
        if file_path
        else Path(__file__).parent.parent.parent.parent
        / "pipelines"
        / "etl_workflow.yaml"
    )
    return parse_run_spec_from_file(path)


__all__ = [
    "load_etl_pipeline",
]
