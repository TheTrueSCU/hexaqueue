"""Unit tests for NormalizedCostRateModelAdapter across cloud providers."""

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_monitor.adapters.rates import (
    DEFAULT_PROVIDER_RATES,
    NormalizedCostRateModelAdapter,
)


def test_normalized_cost_rates_local_zero_cost() -> None:
    """Verify local provider evaluates to 0.0 credits."""
    model = NormalizedCostRateModelAdapter()
    req = ResourceRequirements(cpus=8, ram_mb=16384, gpus=2, walltime_seconds=3600)
    cost = model.calculate_estimated_cost(req, provider=CspProvider.LOCAL)
    assert cost == 0.0

    actual = model.calculate_actual_cost(
        walltime_seconds=3600, cpus=8, ram_mb=16384, gpus=2, provider=CspProvider.LOCAL
    )
    assert actual == 0.0


def test_normalized_cost_rates_aws_calculation() -> None:
    """Verify AWS provider rates calculation."""
    model = NormalizedCostRateModelAdapter()
    req = ResourceRequirements(cpus=2, ram_mb=4096, gpus=1, walltime_seconds=3600)
    # AWS rates: CPU=0.04/hr, RAM=0.005/GB-hr, GPU=1.25/hr
    # Cost = 2*0.04*1 + 4*0.005*1 + 1*1.25*1 = 0.08 + 0.02 + 1.25 = 1.35
    cost = model.calculate_estimated_cost(req, provider=CspProvider.AWS)
    assert cost == 1.35

    actual = model.calculate_actual_cost(
        walltime_seconds=1800, cpus=2, ram_mb=4096, gpus=1, provider=CspProvider.AWS
    )
    assert actual == 0.675


def test_custom_rate_overrides() -> None:
    """Verify custom provider rate overrides."""
    rate = DEFAULT_PROVIDER_RATES[CspProvider.AWS].model_copy(
        update={"cpu_hour_credits": 0.10}
    )
    model = NormalizedCostRateModelAdapter(custom_rates={CspProvider.AWS: rate})
    req = ResourceRequirements(cpus=1, ram_mb=1024, gpus=0, walltime_seconds=3600)
    cost = model.calculate_estimated_cost(req, provider=CspProvider.AWS)
    # 1 * 0.10 + 1 * 0.005 = 0.105
    assert cost == 0.105


__all__ = [
    "test_custom_rate_overrides",
    "test_normalized_cost_rates_aws_calculation",
    "test_normalized_cost_rates_local_zero_cost",
]
