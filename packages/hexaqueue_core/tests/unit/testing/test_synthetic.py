"""Unit tests for synthetic data generation strategies."""

from hexaqueue_core.testing.synthetic import (
    collateral_bundle_strategy,
    job_spec_strategy,
    job_status_strategy,
    resource_requirements_strategy,
)


def test_synthetic_strategies_instantiation():
    """Verify composite Hypothesis strategies are defined and callable."""
    assert callable(resource_requirements_strategy)
    assert callable(job_status_strategy)
    assert callable(job_spec_strategy)
    assert callable(collateral_bundle_strategy)
