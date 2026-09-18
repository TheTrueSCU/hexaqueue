"""Property-based invariant and fuzz testing for FreeTierGovernor.

Notes/Architectural Intent:
    Verifies that the FreeTierGovernor strictly guarantees zero-cost bounds across
    arbitrary randomized job requests and cluster allocation state vectors.
"""

from hypothesis import given
from hypothesis import strategies as st

from hexaqueue_core.domain.exceptions import FreeTierLimitExceededError
from hexaqueue_core.domain.freetier import (
    LOCAL_FREE_TIER_PROFILE,
    OCI_ALWAYS_FREE_PROFILE,
    FreeTierGovernor,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements

# Strategy for generating randomized resource requirements
resource_req_strategy = st.builds(
    ResourceRequirements,
    cpus=st.integers(min_value=1, max_value=16),
    ram_mb=st.integers(min_value=128, max_value=65536),
    gpus=st.integers(min_value=0, max_value=8),
)


@given(resource_req_strategy)
def test_governor_job_validation_invariants(resources: ResourceRequirements) -> None:
    """Governor strictly rejects any job exceeding profile and permits all within bounds."""
    profile = OCI_ALWAYS_FREE_PROFILE  # 4 CPUs, 24576 MB RAM, 0 GPUs
    governor = FreeTierGovernor(profile)

    job = JobSpec(
        id="fuzz_job",
        run_id="run_fuzz",
        name="fuzz_job",
        command="echo fuzz",
        resources=resources,
    )

    should_exceed = (
        resources.gpus > 0
        or resources.cpus > profile.max_cpus
        or resources.ram_mb > profile.max_ram_mb
    )

    if should_exceed:
        try:
            governor.validate_job_resource_request(job)
            msg = f"Expected FreeTierLimitExceededError for {resources}"
            raise AssertionError(msg)
        except FreeTierLimitExceededError:
            pass
    else:
        # Must not raise
        governor.validate_job_resource_request(job)


@given(
    st.lists(
        st.builds(
            JobSpec,
            id=st.text(
                min_size=1,
                max_size=10,
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
            ),
            run_id=st.just("run_fuzz"),
            name=st.just("test"),
            command=st.just("echo 1"),
            resources=st.builds(
                ResourceRequirements,
                cpus=st.integers(min_value=1, max_value=2),
                ram_mb=st.integers(min_value=128, max_value=1024),
                gpus=st.just(0),
            ),
        ),
        max_size=5,
        unique_by=lambda j: j.id,
    ),
    st.integers(min_value=0, max_value=10000),
)
def test_governor_burn_meter_bounded(jobs: list[JobSpec], storage_mb: int) -> None:
    """Burn meter percentages are strictly non-negative and capped at 100.0%."""
    governor = FreeTierGovernor(LOCAL_FREE_TIER_PROFILE)
    burn = governor.compute_burn_meter(jobs, allocated_storage_mb=storage_mb)

    assert 0.0 <= burn.cpu_utilization_pct <= 100.0
    assert 0.0 <= burn.ram_utilization_pct <= 100.0
    assert 0.0 <= burn.storage_utilization_pct <= 100.0
