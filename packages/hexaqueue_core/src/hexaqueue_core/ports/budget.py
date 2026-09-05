"""Budget accounting and cost rate port interfaces.

Notes/Architectural Intent:
    Translates compute resource allocations to abstract HQ Credits, enforces
    two-phase pre-emptive budget reservations (ReserveBudget -> SettleBudget),
    and validates zero-cost guardrails under FREE_TIER mode.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.resources import ResourceRequirements


class CostRate(BaseModel):
    """Cost rate per compute resource unit.

    Args:
        cpu_hour_credits: HQ Credits billed per CPU-hour.
        gpu_hour_credits: HQ Credits billed per GPU-hour.
        ram_gb_hour_credits: HQ Credits billed per GB-RAM-hour.
        provider: Target CSP provider.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cpu_hour_credits: float = Field(ge=0.0, description="Credits per CPU-hour")
    gpu_hour_credits: float = Field(ge=0.0, description="Credits per GPU-hour")
    provider: CspProvider = Field(description="Associated CSP Provider")
    ram_gb_hour_credits: float = Field(ge=0.0, description="Credits per GB-RAM-hour")


class CostRateModelPort(ABC):
    """Abstract port interface for translating resource consumption to credits."""

    @abstractmethod
    def calculate_estimated_cost(
        self,
        requirements: ResourceRequirements,
        provider: CspProvider = CspProvider.LOCAL,
    ) -> float:
        """Estimate the maximum credits required for a given resource request.

        Args:
            requirements: Job resource requirements (CPU, RAM, GPU, Walltime).
            provider: Target CSP provider.

        Returns:
            Estimated total HQ Credits required for the job.
        """


class BudgetAccountingPort(ABC):
    """Abstract port interface for two-phase budget reservations and credit balance tracking."""

    @abstractmethod
    async def reserve_budget(
        self, tenant_id: str, job_id: str, estimated_credits: float
    ) -> str:
        """Place a pre-emptive budget hold for a job.

        Args:
            tenant_id: Tenant / project account identifier.
            job_id: Job identifier.
            estimated_credits: Maximum credits to hold.

        Returns:
            Reservation hold token ID.

        Raises:
            QuotaExceededError: If tenant balance is insufficient.
        """

    @abstractmethod
    async def settle_budget(
        self,
        reservation_id: str,
        actual_credits: float,
    ) -> None:
        """Settle an active budget hold against actual measured consumption.

        Args:
            reservation_id: Reservation hold token ID.
            actual_credits: Final credits consumed by the executed job.

        Raises:
            HexaqueueError: If reservation ID is invalid or already settled.
        """
