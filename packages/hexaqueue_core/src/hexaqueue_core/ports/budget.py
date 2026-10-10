"""Budget accounting and cost rate port interfaces.

Notes/Architectural Intent:
    Translates compute resource allocations to abstract HQ Credits, enforces
    two-phase pre-emptive budget reservations (ReserveBudget -> SettleBudget),
    and validates zero-cost guardrails under FREE_TIER mode.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.budget import TenantAccount
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

    @abstractmethod
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
            provider: Target cloud provider.

        Returns:
            Calculated total credits rounded to 4 decimal places.
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
        tenant_id: str | None = None,
    ) -> None:
        """Settle an active budget hold against actual measured consumption.

        Args:
            reservation_id: Reservation hold token ID.
            actual_credits: Final credits consumed by the executed job.
            tenant_id: Optional tenant identifier to enforce reservation ownership.

        Raises:
            HexaqueueError: If reservation ID is invalid, already settled, or tenant mismatch.
        """

    @abstractmethod
    async def settle_segment(
        self,
        reservation_id: str,
        segment_credits: float,
        tenant_id: str | None = None,
    ) -> float:
        """Settle an incremental execution segment (e.g. upon preemption).

        Args:
            reservation_id: Reservation hold token ID.
            segment_credits: Credits consumed during this execution segment.
            tenant_id: Optional tenant identifier to enforce reservation ownership.

        Returns:
            Cumulative credits settled so far on this reservation.

        Raises:
            HexaqueueError: If reservation ID is invalid, already settled, or tenant mismatch.
        """

    @abstractmethod
    async def release_budget(
        self,
        reservation_id: str,
        tenant_id: str | None = None,
    ) -> None:
        """Release an active budget hold in full without billing.

        Args:
            reservation_id: Reservation hold token ID.
            tenant_id: Optional tenant identifier to enforce reservation ownership.

        Raises:
            HexaqueueError: If reservation ID is invalid, already settled, or tenant mismatch.
        """

    @abstractmethod
    async def get_account(self, tenant_id: str) -> TenantAccount:
        """Retrieve tenant credit balance and active hold details.

        Args:
            tenant_id: Tenant or project account identifier.

        Returns:
            TenantAccount domain entity with balance and hold metrics.
        """
