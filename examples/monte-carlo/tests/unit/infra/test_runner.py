"""Tests for Monte-Carlo runner."""

from monte_carlo.infra.runner import load_monte_carlo_pipeline


def test_load_monte_carlo_pipeline() -> None:
    """Verify YAML pipeline loading and DAG dependencies."""
    submission = load_monte_carlo_pipeline()
    assert submission.run_spec.id == "monte-carlo-stochastic-sim"
    assert len(submission.jobs) == 4
    assert len(submission.dependencies["smooth-and-aggregate"]) == 3
