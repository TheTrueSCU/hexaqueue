"""Multi-CSP Free-Tier Mesh Governor and placement engine.

Notes/Architectural Intent:
    Orchestrates zero-cost compute execution across heterogeneous Always-Free
    cloud tiers (OCI, GCP, AWS, Azure, Local), pooling capacity while strictly
    enforcing individual provider spending and resource limits ($0.00 invariant).
"""

import threading
from collections.abc import Sequence

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import FreeTierLimitExceededError
from hexaqueue_core.domain.freetier import (
    DEFAULT_FEDERATED_FREE_TIER_MESH,
    CspFreeTierProfile,
    FederatedBurnReport,
    FederatedFreeTierMesh,
    FreeTierBurnReport,
    MultiCspPlacementCandidate,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.ports.freetier import FederatedFreeTierGovernorPort


class MultiCspFreeTierGovernor(FederatedFreeTierGovernorPort):
    """Thread-safe multi-cloud free-tier governor and placement arbitrator.

    Args:
        mesh: FederatedFreeTierMesh containing registered Always-Free profiles.

    Notes/Architectural Intent:
        Guarantees that aggregate compute claims burst across providers without
        ever violating any single provider's perpetual Always-Free boundaries.
    """

    def __init__(
        self, mesh: FederatedFreeTierMesh = DEFAULT_FEDERATED_FREE_TIER_MESH
    ) -> None:
        self._mesh = mesh
        self._lock = threading.Lock()
        self._allocations: dict[CspProvider, dict[str, JobSpec]] = {
            prov: {} for prov in self._mesh.profiles
        }
        self._allocated_storage_mb: dict[CspProvider, int] = dict.fromkeys(
            self._mesh.profiles, 0
        )

    @property
    def mesh(self) -> FederatedFreeTierMesh:
        """Retrieve active federated free-tier mesh."""
        return self._mesh

    def allocate_job(
        self, job: JobSpec, preferred_provider: CspProvider | None = None
    ) -> CspProvider:
        """Reserve free-tier capacity for a job on an eligible CSP.

        Args:
            job: Candidate JobSpec requesting compute slots.
            preferred_provider: Optional preferred CSP.

        Returns:
            Assigned CspProvider where the job has been allocated.

        Raises:
            FreeTierLimitExceededError: If the job requests GPUs or exceeds all free caps.
        """
        if job.resources.gpus > 0:
            msg = (
                f"Job '{job.id}' requested {job.resources.gpus} GPUs, but Free-Tier "
                "mesh strictly allows 0 GPUs (Zero-Cost Invariant)"
            )
            raise FreeTierLimitExceededError(msg)

        with self._lock:
            candidate = self._evaluate_placement_unlocked(job, preferred_provider)
            if not candidate.is_eligible:
                raise FreeTierLimitExceededError(candidate.reason)

            prov = candidate.provider
            self._allocations[prov][job.id] = job
            return prov

    def release_job(self, job_id: str) -> None:
        """Release allocated free-tier capacity held by a job.

        Args:
            job_id: Unique job identifier to deallocate.
        """
        with self._lock:
            for prov_allocs in self._allocations.values():
                if job_id in prov_allocs:
                    del prov_allocs[job_id]
                    return

    def find_eligible_provider(
        self, job: JobSpec, preferred_provider: CspProvider | None = None
    ) -> MultiCspPlacementCandidate:
        """Evaluate provider candidates to find the best-fit free-tier provider.

        Args:
            job: Candidate JobSpec to evaluate.
            preferred_provider: Optional preferred CSP.

        Returns:
            MultiCspPlacementCandidate containing placement verdict and metrics.
        """
        with self._lock:
            return self._evaluate_placement_unlocked(job, preferred_provider)

    def check_headroom(self, job: JobSpec) -> bool:
        """Check whether any participating CSP in the mesh has available headroom.

        Args:
            job: Candidate JobSpec awaiting dispatch.

        Returns:
            True if at least one CSP can host the job without exceeding free caps.
        """
        candidate = self.find_eligible_provider(job)
        return candidate.is_eligible

    def compute_federated_burn_meter(self) -> FederatedBurnReport:
        """Compute real-time multi-CSP aggregated burn meter and quota utilization.

        Returns:
            FederatedBurnReport snapshot aggregating all participating CSPs.
        """
        with self._lock:
            provider_burns: dict[CspProvider, FreeTierBurnReport] = {}
            total_allocated_cpus = 0
            total_allocated_ram = 0
            total_allocated_storage = 0

            for prov, profile in self._mesh.profiles.items():
                active_jobs = list(self._allocations[prov].values())
                storage_mb = self._allocated_storage_mb.get(prov, 0)

                burn = self._compute_single_burn(profile, active_jobs, storage_mb)
                provider_burns[prov] = burn

                total_allocated_cpus += burn.allocated_cpus
                total_allocated_ram += burn.allocated_ram_mb
                total_allocated_storage += burn.allocated_storage_mb

            all_throttled = (
                all(b.is_throttled for b in provider_burns.values())
                if provider_burns
                else False
            )

            return FederatedBurnReport(
                allocated_cpus=total_allocated_cpus,
                allocated_ram_mb=total_allocated_ram,
                allocated_storage_mb=total_allocated_storage,
                is_throttled=all_throttled,
                provider_burns=provider_burns,
                total_cpus=self._mesh.total_cpus,
                total_ram_mb=self._mesh.total_ram_mb,
                total_storage_mb=self._mesh.total_storage_mb,
            )

    def _evaluate_placement_unlocked(
        self, job: JobSpec, preferred: CspProvider | None = None
    ) -> MultiCspPlacementCandidate:
        """Internal unlocked placement evaluator."""
        if job.resources.gpus > 0:
            return MultiCspPlacementCandidate(
                available_cpus=0,
                available_ram_mb=0,
                is_eligible=False,
                profile_name="None",
                provider=CspProvider.LOCAL,
                reason="GPUs strictly disallowed on Free-Tier",
            )

        providers_order = self._determine_provider_order(job, preferred)

        for prov in providers_order:
            if prov not in self._mesh.profiles:
                continue
            profile = self._mesh.profiles[prov]
            active_jobs = self._allocations[prov].values()

            alloc_cpus = sum(j.resources.cpus for j in active_jobs)
            alloc_ram = sum(j.resources.ram_mb for j in active_jobs)

            avail_cpus = profile.max_cpus - alloc_cpus
            avail_ram = profile.max_ram_mb - alloc_ram

            # Check if job fits in single-job limit
            if (
                job.resources.cpus > profile.max_cpus
                or job.resources.ram_mb > profile.max_ram_mb
            ):
                continue

            # Check if job fits in current available headroom
            if job.resources.cpus <= avail_cpus and job.resources.ram_mb <= avail_ram:
                return MultiCspPlacementCandidate(
                    available_cpus=avail_cpus,
                    available_ram_mb=avail_ram,
                    is_eligible=True,
                    profile_name=profile.name,
                    provider=prov,
                    reason=f"Eligible for {profile.name}",
                )

        return MultiCspPlacementCandidate(
            available_cpus=0,
            available_ram_mb=0,
            is_eligible=False,
            profile_name="All",
            provider=CspProvider.LOCAL,
            reason="All participating Free-Tier providers exhausted",
        )

    def _determine_provider_order(
        self, job: JobSpec, preferred: CspProvider | None
    ) -> list[CspProvider]:
        """Determine priority evaluation order for placement."""
        order: list[CspProvider] = []
        if preferred and preferred in self._mesh.profiles:
            order.append(preferred)

        # Affinity heuristics: ARM64 or high memory claims prefer OCI
        tags_lower = [t.lower() for t in job.tags]
        is_arm = "arm64" in tags_lower or "aarch64" in tags_lower
        high_ram = job.resources.ram_mb > 2048

        priority_order = (
            [
                CspProvider.OCI,
                CspProvider.LOCAL,
                CspProvider.GCP,
                CspProvider.AWS,
                CspProvider.AZURE,
            ]
            if (is_arm or high_ram)
            else [
                CspProvider.LOCAL,
                CspProvider.GCP,
                CspProvider.AWS,
                CspProvider.AZURE,
                CspProvider.OCI,
            ]
        )

        for p in priority_order:
            if p not in order and p in self._mesh.profiles:
                order.append(p)
        return order

    def _compute_single_burn(
        self,
        profile: CspFreeTierProfile,
        active_jobs: Sequence[JobSpec],
        storage_mb: int,
    ) -> FreeTierBurnReport:
        """Compute FreeTierBurnReport for a single provider."""
        allocated_cpus = sum(j.resources.cpus for j in active_jobs)
        allocated_ram = sum(j.resources.ram_mb for j in active_jobs)

        cpu_pct = round(min(100.0, (allocated_cpus / profile.max_cpus) * 100.0), 2)
        ram_pct = round(min(100.0, (allocated_ram / profile.max_ram_mb) * 100.0), 2)
        storage_pct = round(
            min(100.0, (storage_mb / profile.max_storage_mb) * 100.0), 2
        )

        is_throttled = (
            allocated_cpus >= profile.max_cpus
            or allocated_ram >= profile.max_ram_mb
            or storage_mb >= profile.max_storage_mb
        )

        return FreeTierBurnReport(
            provider=profile.provider,
            profile_name=profile.name,
            active_jobs_count=len(active_jobs),
            allocated_cpus=allocated_cpus,
            allocated_ram_mb=allocated_ram,
            allocated_storage_mb=storage_mb,
            cpu_ceiling=profile.max_cpus,
            ram_ceiling_mb=profile.max_ram_mb,
            storage_ceiling_mb=profile.max_storage_mb,
            cpu_utilization_pct=cpu_pct,
            ram_utilization_pct=ram_pct,
            storage_utilization_pct=storage_pct,
            is_throttled=is_throttled,
        )


__all__ = [
    "MultiCspFreeTierGovernor",
]
