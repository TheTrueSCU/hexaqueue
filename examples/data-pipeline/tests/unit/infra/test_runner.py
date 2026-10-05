"""Tests for pipeline loader."""

from data_pipeline.infra.runner import load_etl_pipeline


def test_load_etl_pipeline() -> None:
    """Verify pipeline YAML loading and validation."""
    submission = load_etl_pipeline()
    assert submission.run_spec.id == "demo-etl-run"
    assert len(submission.jobs) == 4
    assert submission.dependencies["stage3-load-report"] == [
        "stage2-transform-a",
        "stage2-transform-b",
    ]
