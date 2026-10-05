"""Domain entities and value objects for the 100-slot monopoly scenario.

Notes/Architectural Intent:
    Represents tenants, workloads, preemption audit records, and simulation
    state transitions in a shared multi-tenant compute cluster.
"""

from pydantic import BaseModel, ConfigDict, Field


class TenantWorkload(BaseModel):
    """Specification of a tenant's batch or interactive workload.

    Args:
        tenant_id: Unique tenant identifier.
        shares: Target fair-share entitlement weight.
        job_count: Number of jobs submitted by this tenant.
        checkpointable: Whether jobs can be checkpointed and safely preempted.
        walltime_seconds: Expected execution walltime per job.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1, description="Tenant identifier")
    shares: float = Field(
        default=1.0, gt=0.0, description="Fair-share entitlement shares"
    )
    job_count: int = Field(gt=0, description="Total jobs submitted")
    checkpointable: bool = Field(
        default=False, description="Whether jobs support checkpointing"
    )
    walltime_seconds: float = Field(
        default=100.0, gt=0.0, description="Job walltime in seconds"
    )


class PreemptionAuditRecord(BaseModel):
    """Audit record capturing a controlled preemption event.

    Args:
        preempted_job_id: ID of the preempted victim job.
        victim_tenant: Tenant owning the preempted job.
        starved_tenant: Starved tenant allocated to the freed slot.
        reason: Scheduling reason explaining the preemption decision.
        timestamp: Epoch timestamp when preemption occurred.
        compensation_bonus: Priority compensation bonus granted to the victim.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    preempted_job_id: str = Field(description="Victim job ID")
    victim_tenant: str = Field(description="Victim tenant ID")
    starved_tenant: str = Field(description="Starved tenant ID")
    reason: str = Field(description="Explanation of preemption")
    timestamp: float = Field(ge=0.0, description="Preemption timestamp")
    compensation_bonus: float = Field(ge=0.0, description="Granted compensation bonus")


class SimulationPhaseResult(BaseModel):
    """Snapshot of cluster slot allocation and queue state during a simulation phase.

    Args:
        phase_name: Name of the simulation phase.
        elapsed_seconds: Simulation time elapsed in seconds.
        used_slots: Total allocated cluster slots.
        available_slots: Total idle cluster slots.
        slots_tenant_a: Slots allocated to tenant A.
        slots_tenant_b: Slots allocated to tenant B.
        pending_jobs_count: Count of jobs waiting in pending state.
        preempted_jobs_count: Count of jobs preempted in this phase.
        notes: High-level architectural notes on the scheduling state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_name: str = Field(description="Simulation phase name")
    elapsed_seconds: float = Field(ge=0.0, description="Elapsed simulation seconds")
    used_slots: int = Field(ge=0, description="Currently allocated slots")
    available_slots: int = Field(ge=0, description="Currently idle slots")
    slots_tenant_a: int = Field(ge=0, description="Slots held by Tenant A")
    slots_tenant_b: int = Field(ge=0, description="Slots held by Tenant B")
    pending_jobs_count: int = Field(ge=0, description="Number of waiting jobs")
    preempted_jobs_count: int = Field(ge=0, description="Preemptions in this phase")
    notes: str = Field(description="Scheduling notes")


__all__ = [
    "PreemptionAuditRecord",
    "SimulationPhaseResult",
    "TenantWorkload",
]
