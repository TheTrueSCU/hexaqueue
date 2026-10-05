"""Cloud Service Provider (CSP) Free-Tier profiles, governor, and clamping engine.

Notes/Architectural Intent:
    Guarantees strict zero-cost infrastructure execution ($0.00 spend invariant)
    by clamping compute provisioning, memory allocations, GPU usage (strictly 0),
    storage volume ceilings, and region placements to perpetual 'Always Free'
    or trial tier quotas of OCI, GCP, AWS, Azure, and Local sandboxes.
"""

from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import FreeTierLimitExceededError
from hexaqueue_core.domain.job import JobSpec


class CspFreeTierProfile(BaseModel):
    """Declarative specification of a CSP's perpetual Always-Free quota limits.

    Args:
        provider: Target Cloud Service Provider identifier.
        name: Human-readable name of the free tier profile.
        max_cpus: Maximum total vCPUs permitted across the cluster.
        max_ram_mb: Maximum total RAM permitted across the cluster in MB.
        max_gpus: Maximum GPUs permitted (strictly 0 on all free tiers).
        max_storage_mb: Maximum total persistent storage permitted in MB.
        max_egress_gb: Monthly free egress bandwidth allowance in GB.
        allowed_regions: Explicit list of zero-cost regions (empty means all standard regions).
        allowed_instance_types: List of qualifying zero-cost machine types or shapes.
        storage_gc_watermark_ratio: Ratio of max_storage_mb at which aggressive GC is triggered.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: CspProvider = Field(description="Cloud Service Provider")
    name: str = Field(description="Human-readable profile title")
    max_cpus: int = Field(ge=1, description="Maximum total vCPUs allowed")
    max_ram_mb: int = Field(ge=128, description="Maximum total RAM in MB allowed")
    max_gpus: int = Field(
        default=0, ge=0, description="Maximum GPUs allowed (always 0)"
    )
    max_storage_mb: int = Field(ge=512, description="Maximum storage in MB")
    max_egress_gb: int = Field(
        default=10, ge=0, description="Monthly free egress in GB"
    )
    allowed_regions: list[str] = Field(
        default_factory=list, description="Eligible zero-cost regions"
    )
    allowed_instance_types: list[str] = Field(
        default_factory=list, description="Eligible free machine types"
    )
    storage_gc_watermark_ratio: float = Field(
        default=0.8, ge=0.1, le=1.0, description="Storage GC trigger threshold ratio"
    )

    @property
    def storage_gc_watermark_mb(self) -> int:
        """Storage watermark in MB triggering aggressive Content-Addressable Storage cleanup."""
        return int(self.max_storage_mb * self.storage_gc_watermark_ratio)

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Enforce free-tier profile architectural invariants."""
        if self.max_gpus > 0:
            msg = f"CSP Free-Tier profile '{self.name}' cannot allow GPUs (strictly 0 on free tiers)"
            raise ValueError(msg)
        return self


# Canonical CSP Always-Free Profiles
OCI_ALWAYS_FREE_PROFILE = CspFreeTierProfile(
    provider=CspProvider.OCI,
    name="Oracle Cloud (OCI) Always Free",
    max_cpus=4,  # 4 ARM Ampere A1 vCPUs (or 2 AMD x86)
    max_ram_mb=24576,  # 24 GB RAM
    max_gpus=0,
    max_storage_mb=204800,  # 200 GB Block Storage
    max_egress_gb=10000,  # 10 TB/mo free outbound
    allowed_regions=[],  # Home region
    allowed_instance_types=["VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"],
    storage_gc_watermark_ratio=0.8,
)

GCP_ALWAYS_FREE_PROFILE = CspFreeTierProfile(
    provider=CspProvider.GCP,
    name="Google Cloud (GCP) Always Free",
    max_cpus=2,  # 1x e2-micro (2 vCPUs burstable)
    max_ram_mb=1024,  # 1 GB RAM
    max_gpus=0,
    max_storage_mb=30720,  # 30 GB Persistent Disk + 5 GB GCS
    max_egress_gb=1,  # 1 GB/mo egress to worldwide destinations
    allowed_regions=["us-central1", "us-east1", "us-west1"],
    allowed_instance_types=["e2-micro"],
    storage_gc_watermark_ratio=0.8,
)

AWS_FREE_TIER_PROFILE = CspFreeTierProfile(
    provider=CspProvider.AWS,
    name="AWS Free Tier (12-Month & Always Free)",
    max_cpus=1,  # 1x t2.micro or t3.micro
    max_ram_mb=1024,  # 1 GB RAM
    max_gpus=0,
    max_storage_mb=30720,  # 30 GB EBS + 5 GB S3
    max_egress_gb=100,  # 100 GB/mo free outbound egress
    allowed_regions=[],
    allowed_instance_types=["t2.micro", "t3.micro"],
    storage_gc_watermark_ratio=0.8,
)

AZURE_FREE_TIER_PROFILE = CspFreeTierProfile(
    provider=CspProvider.AZURE,
    name="Microsoft Azure Free Tier",
    max_cpus=1,  # 1x B1s
    max_ram_mb=1024,  # 1 GB RAM
    max_gpus=0,
    max_storage_mb=30720,  # 30 GB Managed Disk + 5 GB Blob
    max_egress_gb=15,  # 15 GB/mo free outbound egress
    allowed_regions=[],
    allowed_instance_types=["Standard_B1s"],
    storage_gc_watermark_ratio=0.8,
)

LOCAL_FREE_TIER_PROFILE = CspFreeTierProfile(
    provider=CspProvider.LOCAL,
    name="Local Container / Developer Sandbox",
    max_cpus=2,
    max_ram_mb=2048,
    max_gpus=0,
    max_storage_mb=5120,
    max_egress_gb=0,
    allowed_regions=[],
    allowed_instance_types=["local-container"],
    storage_gc_watermark_ratio=0.8,
)

_CSP_PROFILE_REGISTRY: dict[CspProvider, CspFreeTierProfile] = {
    CspProvider.AWS: AWS_FREE_TIER_PROFILE,
    CspProvider.AZURE: AZURE_FREE_TIER_PROFILE,
    CspProvider.GCP: GCP_ALWAYS_FREE_PROFILE,
    CspProvider.LOCAL: LOCAL_FREE_TIER_PROFILE,
    CspProvider.OCI: OCI_ALWAYS_FREE_PROFILE,
    CspProvider.ONPREM: LOCAL_FREE_TIER_PROFILE,
}


def get_free_tier_profile(provider: CspProvider | str) -> CspFreeTierProfile:
    """Retrieve the canonical FreeTierProfile for a given CSP.

    Args:
        provider: CspProvider enum or string key.

    Returns:
        Matching CspFreeTierProfile instance.
    """
    if isinstance(provider, str):
        try:
            prov_enum = CspProvider(provider.upper())
        except ValueError:
            return LOCAL_FREE_TIER_PROFILE
    else:
        prov_enum = provider

    return _CSP_PROFILE_REGISTRY.get(prov_enum, LOCAL_FREE_TIER_PROFILE)


class FreeTierBurnReport(BaseModel):
    """Real-time cluster resource utilization report under Free-Tier Safety Mode.

    Args:
        provider: Active Cloud Service Provider.
        profile_name: Name of the active free-tier profile.
        active_jobs_count: Number of currently executing or pending jobs.
        allocated_cpus: Total CPUs currently allocated to active jobs.
        allocated_ram_mb: Total RAM in MB currently allocated to active jobs.
        allocated_storage_mb: Total persistent storage in MB currently allocated.
        cpu_ceiling: Hard limit on CPUs under free tier.
        ram_ceiling_mb: Hard limit on RAM in MB under free tier.
        storage_ceiling_mb: Hard limit on persistent storage in MB under free tier.
        cpu_utilization_pct: Percentage of free-tier CPU quota consumed.
        ram_utilization_pct: Percentage of free-tier RAM quota consumed.
        storage_utilization_pct: Percentage of free-tier storage quota consumed.
        is_throttled: True if cluster headroom is exhausted and candidates must wait.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_jobs_count: int = Field(ge=0)
    allocated_cpus: int = Field(ge=0)
    allocated_ram_mb: int = Field(ge=0)
    allocated_storage_mb: int = Field(ge=0)
    cpu_ceiling: int = Field(ge=1)
    cpu_utilization_pct: float = Field(ge=0.0)
    is_throttled: bool
    profile_name: str
    provider: CspProvider
    ram_ceiling_mb: int = Field(ge=128)
    ram_utilization_pct: float = Field(ge=0.0)
    storage_ceiling_mb: int = Field(ge=512)
    storage_utilization_pct: float = Field(ge=0.0)


class FreeTierGovernor:
    """Zero-cost governance and quota clamping interceptor.

    Notes/Architectural Intent:
        Intercepts job submission, placement, and provisioning requests to
        guarantee zero accidental cloud expenditure by rejecting jobs exceeding
        single-job caps and delaying candidates when cluster concurrency limits
        are reached.
    """

    def __init__(self, profile: CspFreeTierProfile = LOCAL_FREE_TIER_PROFILE) -> None:
        """Initialize governor with a specific CSP free-tier profile.

        Args:
            profile: Active CspFreeTierProfile specification (defaults to LOCAL_FREE_TIER_PROFILE).
        """
        self._profile = profile

    @property
    def profile(self) -> CspFreeTierProfile:
        """Retrieve active CSP profile."""
        return self._profile

    def validate_job_resource_request(self, job: JobSpec) -> None:
        """Validate that a job's resource requirements do not exceed free-tier caps.

        Args:
            job: Candidate JobSpec to evaluate.

        Raises:
            FreeTierLimitExceededError: If the job requests resources exceeding free tier limits.
        """
        res = job.resources
        if res.gpus > 0:
            msg = (
                f"Job '{job.id}' requested {res.gpus} GPUs, but {self._profile.name} "
                f"strictly allows 0 GPUs (Zero-Cost Invariant)"
            )
            raise FreeTierLimitExceededError(msg)

        if res.cpus > self._profile.max_cpus:
            msg = (
                f"Job '{job.id}' requested {res.cpus} CPUs, exceeding {self._profile.name} "
                f"free-tier maximum limit of {self._profile.max_cpus} CPUs"
            )
            raise FreeTierLimitExceededError(msg)

        if res.ram_mb > self._profile.max_ram_mb:
            msg = (
                f"Job '{job.id}' requested {res.ram_mb} MB RAM, exceeding {self._profile.name} "
                f"free-tier maximum limit of {self._profile.max_ram_mb} MB"
            )
            raise FreeTierLimitExceededError(msg)

    def validate_region_placement(self, region: str | None) -> None:
        """Validate that target deployment region is eligible for zero-cost execution.

        Args:
            region: Target cloud region string, or None.

        Raises:
            FreeTierLimitExceededError: If target region is outside CSP's Always-Free boundary.
        """
        if not region or not self._profile.allowed_regions:
            return

        if region not in self._profile.allowed_regions:
            msg = (
                f"Region '{region}' is not eligible for free-tier execution on {self._profile.name}. "
                f"Allowed free regions: {', '.join(self._profile.allowed_regions)}"
            )
            raise FreeTierLimitExceededError(msg)

    def check_cluster_headroom(
        self, active_jobs: Sequence[JobSpec], candidate: JobSpec
    ) -> bool:
        """Check whether cluster has sufficient free-tier capacity to schedule candidate.

        Args:
            active_jobs: Sequence of currently executing jobs holding resource slots.
            candidate: Candidate JobSpec awaiting dispatch.

        Returns:
            True if candidate can be dispatched without exceeding free tier caps, False otherwise.
        """
        allocated_cpus = sum(j.resources.cpus for j in active_jobs)
        allocated_ram = sum(j.resources.ram_mb for j in active_jobs)

        new_cpus = allocated_cpus + candidate.resources.cpus
        new_ram = allocated_ram + candidate.resources.ram_mb

        return (new_cpus <= self._profile.max_cpus) and (
            new_ram <= self._profile.max_ram_mb
        )

    def compute_burn_meter(
        self, active_jobs: Sequence[JobSpec], allocated_storage_mb: int = 0
    ) -> FreeTierBurnReport:
        """Compute real-time burn meter and quota utilization metrics.

        Args:
            active_jobs: Sequence of currently executing or pending jobs holding allocations.
            allocated_storage_mb: Current storage usage in MB.

        Returns:
            FreeTierBurnReport snapshot.
        """
        allocated_cpus = sum(j.resources.cpus for j in active_jobs)
        allocated_ram = sum(j.resources.ram_mb for j in active_jobs)

        cpu_pct = round(
            min(100.0, (allocated_cpus / self._profile.max_cpus) * 100.0), 2
        )
        ram_pct = round(
            min(100.0, (allocated_ram / self._profile.max_ram_mb) * 100.0), 2
        )
        storage_pct = round(
            min(100.0, (allocated_storage_mb / self._profile.max_storage_mb) * 100.0), 2
        )

        is_throttled = (
            allocated_cpus >= self._profile.max_cpus
            or allocated_ram >= self._profile.max_ram_mb
            or allocated_storage_mb >= self._profile.max_storage_mb
        )

        return FreeTierBurnReport(
            provider=self._profile.provider,
            profile_name=self._profile.name,
            active_jobs_count=len(active_jobs),
            allocated_cpus=allocated_cpus,
            allocated_ram_mb=allocated_ram,
            allocated_storage_mb=allocated_storage_mb,
            cpu_ceiling=self._profile.max_cpus,
            ram_ceiling_mb=self._profile.max_ram_mb,
            storage_ceiling_mb=self._profile.max_storage_mb,
            cpu_utilization_pct=cpu_pct,
            ram_utilization_pct=ram_pct,
            storage_utilization_pct=storage_pct,
            is_throttled=is_throttled,
        )


__all__ = [
    "AWS_FREE_TIER_PROFILE",
    "AZURE_FREE_TIER_PROFILE",
    "CspFreeTierProfile",
    "FreeTierBurnReport",
    "FreeTierGovernor",
    "GCP_ALWAYS_FREE_PROFILE",
    "get_free_tier_profile",
    "LOCAL_FREE_TIER_PROFILE",
    "OCI_ALWAYS_FREE_PROFILE",
]
