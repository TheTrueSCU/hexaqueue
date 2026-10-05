"""Unit tests for CSP Free-Tier profiles, governor, and zero-cost clamping.

Notes/Architectural Intent:
    Verifies that the FreeTierGovernor strictly enforces zero-cost invariants:
    - GPU usage is strictly 0 (rejecting any job requesting >0 GPUs).
    - CPU and RAM per-job limits are strictly clamped.
    - Cloud region placement is restricted to CSP designated Always-Free regions.
    - Cluster concurrency headroom delays candidates when free caps are reached.
    - Burn meter accurately reports utilization against free-tier ceilings.
"""

import pytest

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import FreeTierLimitExceededError
from hexaqueue_core.domain.freetier import (
    AWS_FREE_TIER_PROFILE,
    AZURE_FREE_TIER_PROFILE,
    GCP_ALWAYS_FREE_PROFILE,
    LOCAL_FREE_TIER_PROFILE,
    OCI_ALWAYS_FREE_PROFILE,
    CspFreeTierProfile,
    FreeTierGovernor,
    get_free_tier_profile,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements


def test_canonical_profiles_and_invariants() -> None:
    """Verifies that canonical profiles satisfy Always-Free constraints."""
    # OCI: 4 ARM vCPUs, 24GB RAM, 200GB Block
    assert OCI_ALWAYS_FREE_PROFILE.max_cpus == 4
    assert OCI_ALWAYS_FREE_PROFILE.max_ram_mb == 24576
    assert OCI_ALWAYS_FREE_PROFILE.max_gpus == 0
    assert OCI_ALWAYS_FREE_PROFILE.max_storage_mb == 204800
    assert OCI_ALWAYS_FREE_PROFILE.storage_gc_watermark_mb == 163840

    # GCP: 2 vCPUs (e2-micro), 1GB RAM, 30GB disk, specific regions
    assert GCP_ALWAYS_FREE_PROFILE.max_cpus == 2
    assert GCP_ALWAYS_FREE_PROFILE.max_ram_mb == 1024
    assert GCP_ALWAYS_FREE_PROFILE.max_gpus == 0
    assert "us-central1" in GCP_ALWAYS_FREE_PROFILE.allowed_regions

    # AWS: 1 vCPU, 1GB RAM, 30GB EBS
    assert AWS_FREE_TIER_PROFILE.max_cpus == 1
    assert AWS_FREE_TIER_PROFILE.max_ram_mb == 1024

    # Azure: 1 vCPU, 1GB RAM, 30GB disk
    assert AZURE_FREE_TIER_PROFILE.max_cpus == 1
    assert AZURE_FREE_TIER_PROFILE.max_ram_mb == 1024

    # Profile cannot allow GPUs
    with pytest.raises(ValueError, match="cannot allow GPUs"):
        CspFreeTierProfile(
            provider=CspProvider.AWS,
            name="Illegal GPU Free Tier",
            max_cpus=2,
            max_ram_mb=1024,
            max_gpus=1,
            max_storage_mb=1024,
        )


def test_get_free_tier_profile_lookup() -> None:
    """Verifies profile lookup by enum and case-insensitive string."""
    oci_prof = get_free_tier_profile(CspProvider.OCI)
    assert oci_prof == OCI_ALWAYS_FREE_PROFILE

    gcp_prof = get_free_tier_profile("gcp")
    assert gcp_prof == GCP_ALWAYS_FREE_PROFILE

    unknown_prof = get_free_tier_profile("unknown_provider")
    assert unknown_prof == LOCAL_FREE_TIER_PROFILE


def test_governor_rejects_gpu_jobs() -> None:
    """Verifies that FreeTierGovernor strictly rejects any job requesting GPUs."""
    governor = FreeTierGovernor(GCP_ALWAYS_FREE_PROFILE)
    gpu_job = JobSpec(
        id="job_gpu",
        run_id="run_1",
        name="gpu_job",
        command="train.py",
        resources=ResourceRequirements(cpus=1, ram_mb=512, gpus=1),
    )

    with pytest.raises(FreeTierLimitExceededError, match="strictly allows 0 GPUs"):
        governor.validate_job_resource_request(gpu_job)


def test_governor_rejects_cpu_ram_exceeding_profile() -> None:
    """Verifies that FreeTierGovernor rejects jobs requesting CPUs or RAM exceeding limits."""
    governor = FreeTierGovernor(AWS_FREE_TIER_PROFILE)  # 1 CPU, 1024 MB RAM

    cpu_heavy = JobSpec(
        id="job_cpu",
        run_id="run_1",
        name="cpu_heavy",
        command="echo 1",
        resources=ResourceRequirements(cpus=2, ram_mb=512),
    )
    with pytest.raises(
        FreeTierLimitExceededError,
        match="exceeding .* free-tier maximum limit of 1 CPUs",
    ):
        governor.validate_job_resource_request(cpu_heavy)

    ram_heavy = JobSpec(
        id="job_ram",
        run_id="run_1",
        name="ram_heavy",
        command="echo 1",
        resources=ResourceRequirements(cpus=1, ram_mb=2048),
    )
    with pytest.raises(
        FreeTierLimitExceededError,
        match="exceeding .* free-tier maximum limit of 1024 MB",
    ):
        governor.validate_job_resource_request(ram_heavy)

    valid_job = JobSpec(
        id="job_valid",
        run_id="run_1",
        name="valid",
        command="echo 1",
        resources=ResourceRequirements(cpus=1, ram_mb=512),
    )
    # Does not raise
    governor.validate_job_resource_request(valid_job)


def test_governor_validates_region_placement() -> None:
    """Verifies that FreeTierGovernor restricts placement to allowed free regions."""
    governor = FreeTierGovernor(GCP_ALWAYS_FREE_PROFILE)

    # Allowed regions: us-central1, us-east1, us-west1
    governor.validate_region_placement("us-central1")
    governor.validate_region_placement("us-east1")

    with pytest.raises(
        FreeTierLimitExceededError, match="is not eligible for free-tier execution"
    ):
        governor.validate_region_placement("europe-west1")

    # None or unconstrained profile does not raise
    governor.validate_region_placement(None)
    aws_gov = FreeTierGovernor(AWS_FREE_TIER_PROFILE)
    aws_gov.validate_region_placement("us-east-1")


def test_governor_checks_cluster_headroom() -> None:
    """Verifies that cluster headroom check delays candidates when total allocations reach cap."""
    governor = FreeTierGovernor(OCI_ALWAYS_FREE_PROFILE)  # 4 CPUs, 24576 MB RAM

    job1 = JobSpec(
        id="j1",
        run_id="r1",
        name="j1",
        command="echo 1",
        resources=ResourceRequirements(cpus=2, ram_mb=8192),
    )
    job2 = JobSpec(
        id="j2",
        run_id="r1",
        name="j2",
        command="echo 2",
        resources=ResourceRequirements(cpus=2, ram_mb=8192),
    )

    candidate_fit = JobSpec(
        id="j_fit",
        run_id="r1",
        name="fit",
        command="echo fit",
        resources=ResourceRequirements(cpus=1, ram_mb=2048),
    )

    # With only job1 active, candidate fits (2+1 = 3 <= 4 CPUs)
    has_room = governor.check_cluster_headroom([job1], candidate_fit)
    assert has_room is True

    # With job1 + job2 active (4 CPUs total), candidate does not fit (4+1 = 5 > 4 CPUs)
    no_room = governor.check_cluster_headroom([job1, job2], candidate_fit)
    assert no_room is False


def test_governor_computes_burn_meter() -> None:
    """Verifies real-time burn meter calculations and throttling status."""
    governor = FreeTierGovernor(
        LOCAL_FREE_TIER_PROFILE
    )  # 2 CPUs, 2048 MB RAM, 5120 MB Storage

    job1 = JobSpec(
        id="j1",
        run_id="r1",
        name="j1",
        command="echo 1",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
    )

    burn = governor.compute_burn_meter([job1], allocated_storage_mb=2560)

    cpu_pct = burn.cpu_utilization_pct
    assert cpu_pct == 50.0

    ram_pct = burn.ram_utilization_pct
    assert ram_pct == 50.0

    storage_pct = burn.storage_utilization_pct
    assert storage_pct == 50.0

    assert burn.is_throttled is False

    # Fully saturated
    job2 = JobSpec(
        id="j2",
        run_id="r1",
        name="j2",
        command="echo 2",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
    )
    full_burn = governor.compute_burn_meter([job1, job2], allocated_storage_mb=5120)

    assert full_burn.cpu_utilization_pct == 100.0
    assert full_burn.ram_utilization_pct == 100.0
    assert full_burn.storage_utilization_pct == 100.0
    assert full_burn.is_throttled is True
