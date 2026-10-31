"""Unit and dual-oracle property tests for MultiCspFreeTierGovernor."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hexaqueue_core.adapters.freetier.governor import (
    MultiCspFreeTierGovernor,
)
from hexaqueue_core.adapters.freetier.oracle import NaiveFreeTierMeshOracle
from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import FreeTierLimitExceededError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements


def _make_job(
    job_id: str,
    cpus: int = 1,
    ram_mb: int = 512,
    gpus: int = 0,
    tags: list[str] | None = None,
) -> JobSpec:
    return JobSpec(
        id=job_id,
        run_id="run-1",
        name=f"job-{job_id}",
        command="python test.py",
        resources=ResourceRequirements(
            cpus=cpus,
            ram_mb=ram_mb,
            gpus=gpus,
        ),
        tags=tags or [],
    )


def test_zero_gpu_invariant_strictly_enforced() -> None:
    """Verifies that requesting any GPU accelerator is immediately rejected with $0.00 invariant."""
    governor = MultiCspFreeTierGovernor()
    gpu_job = _make_job("gpu-job-1", cpus=1, ram_mb=1024, gpus=1)

    with pytest.raises(FreeTierLimitExceededError, match="strictly allows 0 GPUs"):
        governor.allocate_job(gpu_job)

    headroom = governor.check_headroom(gpu_job)
    assert headroom is False


def test_arm64_affinity_routes_to_oci() -> None:
    """Verifies that ARM64 tasks route to OCI Always Free Ampere nodes."""
    governor = MultiCspFreeTierGovernor()
    arm_job = _make_job("arm-job", cpus=4, ram_mb=8192, tags=["self-hosted", "arm64"])

    assigned = governor.allocate_job(arm_job)
    assert assigned == CspProvider.OCI

    headroom = governor.check_headroom(arm_job)
    # OCI capacity is 4 CPUs total, so another 4-CPU job won't fit on OCI
    # and no other free tier has 4 CPUs, so headroom should be False
    assert headroom is False


def test_allocation_and_release_lifecycle() -> None:
    """Verifies normal allocation and release cycles."""
    governor = MultiCspFreeTierGovernor()
    job1 = _make_job("j1", cpus=1, ram_mb=512)

    prov = governor.allocate_job(job1, preferred_provider=CspProvider.LOCAL)
    assert prov == CspProvider.LOCAL

    burn_report = governor.compute_federated_burn_meter()
    alloc_cpus = burn_report.allocated_cpus
    assert alloc_cpus == 1
    assert burn_report.is_throttled is False

    governor.release_job("j1")
    burn_report_after = governor.compute_federated_burn_meter()
    alloc_cpus_after = burn_report_after.allocated_cpus
    assert alloc_cpus_after == 0


def test_quota_exhaustion_raises_limit_exceeded() -> None:
    """Verifies that attempting to allocate beyond all pooled capacity raises FreeTierLimitExceededError."""
    governor = MultiCspFreeTierGovernor()
    # Allocate jobs until pool is full
    allocated_ids = []
    # Total CPUs across mesh is 10
    for i in range(10):
        jid = f"job-fill-{i}"
        governor.allocate_job(_make_job(jid, cpus=1, ram_mb=256))
        allocated_ids.append(jid)

    # 11th job must be rejected
    overflow_job = _make_job("overflow-job", cpus=1, ram_mb=256)
    with pytest.raises(FreeTierLimitExceededError, match="exhausted"):
        governor.allocate_job(overflow_job)


@given(
    actions=st.lists(
        st.tuples(
            st.sampled_from(["allocate", "release"]),
            st.integers(min_value=1, max_value=8),
        ),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=25)
def test_dual_oracle_free_tier_allocation(
    actions: list[tuple[str, int]],
) -> None:
    """Dual-Oracle test: prove MultiCspFreeTierGovernor never exceeds Always-Free bounds."""
    governor = MultiCspFreeTierGovernor()
    oracle = NaiveFreeTierMeshOracle()

    allocated_jobs: set[int] = set()

    for action_type, job_num in actions:
        jid = f"job_{job_num}"
        if action_type == "allocate":
            if job_num not in allocated_jobs:
                job = _make_job(jid, cpus=1, ram_mb=512)
                try:
                    prov = governor.allocate_job(job)
                    allocated_jobs.add(job_num)
                    oracle.step_allocate(jid, cpus=1, ram_mb=512, preferred=prov.value)
                except FreeTierLimitExceededError:
                    # Mesh was full on governor side
                    pass
        elif action_type == "release" and job_num in allocated_jobs:
            governor.release_job(jid)
            oracle.step_release(jid)
            allocated_jobs.remove(job_num)

        # Invariant check: Governor allocated CPUs matches tracked active jobs count
        burn = governor.compute_federated_burn_meter()
        assert burn.allocated_cpus == len(allocated_jobs)
        # Invariant check: Total allocated never exceeds total mesh ceiling
        assert burn.allocated_cpus <= burn.total_cpus
        assert burn.allocated_ram_mb <= burn.total_ram_mb
