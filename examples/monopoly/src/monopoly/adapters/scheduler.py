"""Batch scheduler cluster simulation adapter.

Notes/Architectural Intent:
    Wraps Hexaqueue's BatchSchedulerEngine, ResourceSlotPool, FairShareTree,
    and ControlledPreemptionEngine to simulate multi-tenant monopoly resolution.
"""

from datetime import UTC, datetime, timedelta

from hexaqueue_core.domain.fairshare import FairShareNode, FairShareTree
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.scheduling import (
    BatchSchedulerEngine,
    ControlledPreemptionEngine,
    PreemptionPolicy,
    ResourceSlotPool,
)

from monopoly.domain.models import (
    PreemptionAuditRecord,
    SimulationPhaseResult,
    TenantWorkload,
)
from monopoly.ports.simulator import ClusterSimulatorPort


class BatchSchedulerClusterSimulator(ClusterSimulatorPort):
    """Concrete cluster simulator powered by Hexaqueue scheduling engines.

    Args:
        total_slots: Total slot capacity of the cluster pool.
        grace_period_seconds: Grace period duration before preemption is authorized.
        starvation_deficit_threshold: Fair-share starvation deficit required to preempt.
        preemption_bonus: Priority bonus granted to preempted victim tasks.
    """

    def __init__(
        self,
        total_slots: int = 100,
        grace_period_seconds: float = 30.0,
        starvation_deficit_threshold: float = 0.4,
        preemption_bonus: float = 5000.0,
    ) -> None:
        self.total_slots = total_slots
        self.grace_period_seconds = grace_period_seconds
        self.starvation_deficit_threshold = starvation_deficit_threshold
        self.preemption_bonus = preemption_bonus

        self.pool = ResourceSlotPool(total_slots=total_slots)
        self.fs_tree = FairShareTree(root_id="cluster")
        self.preemption_policy = PreemptionPolicy(
            grace_period_seconds=grace_period_seconds,
            starvation_deficit_threshold=starvation_deficit_threshold,
            preemption_bonus=preemption_bonus,
        )
        self.scheduler = BatchSchedulerEngine(
            pool=self.pool,
            fairshare_tree=self.fs_tree,
            preemption_engine=ControlledPreemptionEngine(policy=self.preemption_policy),
        )

        self._t0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
        self._t0_secs = self._t0.timestamp()

        self._running_jobs_a: list[JobSpec] = []
        self._pending_jobs_b: list[JobSpec] = []
        self._audit_log: list[PreemptionAuditRecord] = []
        self._tenant_a: TenantWorkload | None = None
        self._tenant_b: TenantWorkload | None = None

    def initialize_cluster(self, total_slots: int = 100) -> None:
        """Initialize or reset the cluster resource pool with specified slot capacity.

        Args:
            total_slots: Total slot capacity of the cluster.
        """
        self.total_slots = total_slots
        self.pool = ResourceSlotPool(total_slots=total_slots)
        self.fs_tree = FairShareTree(root_id="cluster")
        self.scheduler = BatchSchedulerEngine(
            pool=self.pool,
            fairshare_tree=self.fs_tree,
            preemption_engine=ControlledPreemptionEngine(policy=self.preemption_policy),
        )
        self._running_jobs_a.clear()
        self._pending_jobs_b.clear()
        self._audit_log.clear()

    def setup_tenants(self, tenant_a: TenantWorkload, tenant_b: TenantWorkload) -> None:
        """Configure fair-share tree and tenants for the simulation.

        Args:
            tenant_a: Workload and entitlement spec for Tenant A.
            tenant_b: Workload and entitlement spec for Tenant B.
        """
        self._tenant_a = tenant_a
        self._tenant_b = tenant_b
        self.fs_tree.add_node(
            FairShareNode(
                id=tenant_a.tenant_id, parent_id="cluster", shares=tenant_a.shares
            )
        )
        self.fs_tree.add_node(
            FairShareNode(
                id=tenant_b.tenant_id, parent_id="cluster", shares=tenant_b.shares
            )
        )

    def run_monopoly_phase(self) -> SimulationPhaseResult:
        """Execute Phase 1: Tenant A occupies all 100 cluster slots.

        Returns:
            Snapshot of cluster allocation and queue state.
        """
        if self._tenant_a is None:
            self._tenant_a = TenantWorkload(
                tenant_id="team_alpha",
                shares=1.0,
                job_count=self.total_slots,
                checkpointable=True,
            )
            self.fs_tree.add_node(
                FairShareNode(id="team_alpha", parent_id="cluster", shares=1.0)
            )

        self._running_jobs_a.clear()
        for i in range(self.total_slots):
            job_a = JobSpec(
                id=f"alpha-job-{i:03d}",
                run_id="run-alpha",
                name=f"alpha-task-{i}",
                command="sleep 1000",
                user=self._tenant_a.tenant_id,
                checkpointable=(i % 2 == 0),
                created_at=self._t0 - timedelta(seconds=100),
            )
            self.pool.allocate(job_a)
            self._running_jobs_a.append(job_a)
            self.scheduler.record_job_start(job_a.id, self._t0_secs - float(i))

        # Record historical cluster usage by Team Alpha
        self.fs_tree.record_usage(
            self._tenant_a.tenant_id, 500.0, timestamp=self._t0_secs
        )

        return SimulationPhaseResult(
            phase_name="Phase 1: 100-Slot Monopoly Established",
            elapsed_seconds=0.0,
            used_slots=self.pool.used_slots,
            available_slots=self.pool.available_slots,
            slots_tenant_a=len(self._running_jobs_a),
            slots_tenant_b=0,
            pending_jobs_count=0,
            preempted_jobs_count=0,
            notes=f"{self._tenant_a.tenant_id} occupies 100% of cluster slots.",
        )

    def run_starvation_phase(
        self, elapsed_seconds: float = 10.0
    ) -> SimulationPhaseResult:
        """Execute Phase 2: Tenant B submits urgent jobs during grace period.

        Args:
            elapsed_seconds: Wait time elapsed (< grace period).

        Returns:
            Snapshot showing Tenant B jobs waiting safely without thrashing.
        """
        if self._tenant_b is None:
            self._tenant_b = TenantWorkload(
                tenant_id="team_beta", shares=1.0, job_count=1
            )
            self.fs_tree.add_node(
                FairShareNode(id="team_beta", parent_id="cluster", shares=1.0)
            )

        job_b = JobSpec(
            id="beta-job-001",
            run_id="run-beta",
            name="beta-urgent-task",
            command="python compute.py",
            user=self._tenant_b.tenant_id,
            created_at=self._t0,
        )
        self._pending_jobs_b = [job_b]

        decision = self.scheduler.schedule_cycle(
            pending_jobs=self._pending_jobs_b,
            running_jobs=self._running_jobs_a,
            current_timestamp=self._t0_secs + elapsed_seconds,
        )

        return SimulationPhaseResult(
            phase_name="Phase 2: Starvation & Grace Period Active",
            elapsed_seconds=elapsed_seconds,
            used_slots=self.pool.used_slots,
            available_slots=self.pool.available_slots,
            slots_tenant_a=len(self._running_jobs_a),
            slots_tenant_b=0,
            pending_jobs_count=len(decision.remains_pending),
            preempted_jobs_count=len(decision.preempted_jobs),
            notes=(
                f"Wait time {elapsed_seconds}s < grace period {self.grace_period_seconds}s. "
                "No preemption triggered to protect against queue thrashing."
            ),
        )

    def run_preemption_phase(
        self, elapsed_seconds: float = 35.0
    ) -> SimulationPhaseResult:
        """Execute Phase 3: Grace period expires and controlled preemption triggers.

        Args:
            elapsed_seconds: Wait time elapsed (> grace period).

        Returns:
            Snapshot showing preemption of Tenant A victim and allocation of Tenant B.
        """
        decision = self.scheduler.schedule_cycle(
            pending_jobs=self._pending_jobs_b,
            running_jobs=self._running_jobs_a,
            current_timestamp=self._t0_secs + elapsed_seconds,
        )

        for preempted_id, reason in decision.preempted_jobs:
            victim_tenant = self._tenant_a.tenant_id if self._tenant_a else "team_alpha"
            starved_tenant = self._tenant_b.tenant_id if self._tenant_b else "team_beta"
            self._audit_log.append(
                PreemptionAuditRecord(
                    preempted_job_id=preempted_id,
                    victim_tenant=victim_tenant,
                    starved_tenant=starved_tenant,
                    reason=reason,
                    timestamp=self._t0_secs + elapsed_seconds,
                    compensation_bonus=self.preemption_bonus,
                )
            )
            # Remove victim from running jobs
            self._running_jobs_a = [
                j for j in self._running_jobs_a if j.id != preempted_id
            ]

        slots_b = len(decision.to_run)
        slots_a = len(self._running_jobs_a)

        return SimulationPhaseResult(
            phase_name="Phase 3: Controlled Preemption Authorized",
            elapsed_seconds=elapsed_seconds,
            used_slots=self.pool.used_slots,
            available_slots=self.pool.available_slots,
            slots_tenant_a=slots_a,
            slots_tenant_b=slots_b,
            pending_jobs_count=len(decision.remains_pending),
            preempted_jobs_count=len(decision.preempted_jobs),
            notes=(
                f"Wait time {elapsed_seconds}s > grace period {self.grace_period_seconds}s. "
                f"Preempted {len(decision.preempted_jobs)} checkpointable task(s) with compensation bonus."
            ),
        )

    def get_audit_log(self) -> list[PreemptionAuditRecord]:
        """Retrieve historical preemption audit records.

        Returns:
            List of recorded preemption events.
        """
        return list(self._audit_log)


__all__ = [
    "BatchSchedulerClusterSimulator",
]
