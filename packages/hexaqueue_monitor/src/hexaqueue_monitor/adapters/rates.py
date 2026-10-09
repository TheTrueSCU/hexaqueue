"""Multi-provider normalized cost rate model adapter.

Notes/Architectural Intent:
    Translates compute resource requirements and actual execution telemetry
    into abstract HQ credits across diverse cloud service providers (AWS, GCP, Azure, OCI)
    and zero-cost local environments.
"""

from typing import Final

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.budget import CostRate, CostRateModelPort

DEFAULT_PROVIDER_RATES: Final[dict[CspProvider, CostRate]] = {
    CspProvider.AWS: CostRate(
        cpu_hour_credits=0.04,
        gpu_hour_credits=1.25,
        ram_gb_hour_credits=0.005,
        provider=CspProvider.AWS,
    ),
    CspProvider.GCP: CostRate(
        cpu_hour_credits=0.038,
        gpu_hour_credits=1.20,
        ram_gb_hour_credits=0.0048,
        provider=CspProvider.GCP,
    ),
    CspProvider.AZURE: CostRate(
        cpu_hour_credits=0.042,
        gpu_hour_credits=1.30,
        ram_gb_hour_credits=0.0052,
        provider=CspProvider.AZURE,
    ),
    CspProvider.OCI: CostRate(
        cpu_hour_credits=0.035,
        gpu_hour_credits=1.15,
        ram_gb_hour_credits=0.0045,
        provider=CspProvider.OCI,
    ),
    CspProvider.LOCAL: CostRate(
        cpu_hour_credits=0.0,
        gpu_hour_credits=0.0,
        ram_gb_hour_credits=0.0,
        provider=CspProvider.LOCAL,
    ),
}


class NormalizedCostRateModelAdapter(CostRateModelPort):
    """Normalized cost rate model adapter translating compute usage to abstract credits.

    Args:
        custom_rates: Optional custom CostRate overrides per provider.
    """

    def __init__(self, custom_rates: dict[CspProvider, CostRate] | None = None) -> None:
        self._rates: dict[CspProvider, CostRate] = dict(DEFAULT_PROVIDER_RATES)
        if custom_rates:
            self._rates.update(custom_rates)

    def get_rate(self, provider: CspProvider) -> CostRate:
        """Resolve cost rate for the specified CSP provider.

        Args:
            provider: Target CSP provider.

        Returns:
            CostRate for resource consumption.
        """
        return self._rates.get(provider, self._rates[CspProvider.LOCAL])

    def calculate_estimated_cost(
        self,
        requirements: ResourceRequirements,
        provider: CspProvider = CspProvider.LOCAL,
    ) -> float:
        """Estimate maximum credits required for a resource specification.

        Args:
            requirements: Job resource specifications including walltime.
            provider: Target cloud provider.

        Returns:
            Estimated total credits rounded to 4 decimal places.
        """
        rate = self.get_rate(provider)
        hours = max(1.0, requirements.walltime_seconds) / 3600.0
        ram_gb = requirements.ram_mb / 1024.0

        cpu_cost = requirements.cpus * rate.cpu_hour_credits * hours
        ram_cost = ram_gb * rate.ram_gb_hour_credits * hours
        gpu_cost = requirements.gpus * rate.gpu_hour_credits * hours

        return round(cpu_cost + ram_cost + gpu_cost, 4)

    def calculate_actual_cost(
        self,
        walltime_seconds: float,
        cpus: int = 1,
        ram_mb: int = 1024,
        gpus: int = 0,
        provider: CspProvider = CspProvider.LOCAL,
    ) -> float:
        """Calculate exact credit consumption based on measured execution walltime.

        Args:
            walltime_seconds: Elapsed execution duration in seconds.
            cpus: Assigned CPU core count.
            ram_mb: Consumed RAM in megabytes.
            gpus: Assigned GPU accelerator count.
            provider: Execution cloud provider.

        Returns:
            Actual consumed credits rounded to 4 decimal places.
        """
        rate = self.get_rate(provider)
        hours = max(0.0, walltime_seconds) / 3600.0
        ram_gb = ram_mb / 1024.0

        cpu_cost = cpus * rate.cpu_hour_credits * hours
        ram_cost = ram_gb * rate.ram_gb_hour_credits * hours
        gpu_cost = gpus * rate.gpu_hour_credits * hours

        return round(cpu_cost + ram_cost + gpu_cost, 4)


__all__ = [
    "DEFAULT_PROVIDER_RATES",
    "NormalizedCostRateModelAdapter",
]
