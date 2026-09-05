"""Unit tests for budget port models and contracts."""

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.ports.budget import CostRate


def test_cost_rate_valid():
    """Verify CostRate creation."""
    rate = CostRate(
        cpu_hour_credits=0.05,
        ram_gb_hour_credits=0.01,
        gpu_hour_credits=1.25,
        provider=CspProvider.AWS,
    )
    assert rate.cpu_hour_credits == 0.05
    assert rate.provider == CspProvider.AWS
