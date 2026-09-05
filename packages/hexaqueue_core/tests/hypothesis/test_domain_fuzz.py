"""Property-based invariant fuzzing tests for Job, Run, and Collateral domain models."""

from hypothesis import given
from hypothesis import strategies as st

from hexaqueue_core.domain.collateral import CollateralBundle, CollateralState
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, RunState, compute_run_state
from hexaqueue_core.testing.synthetic import (
    collateral_bundle_strategy,
    job_spec_strategy,
    resource_requirements_strategy,
)


@given(resource_requirements_strategy())
def test_resource_requirements_invariants(res):
    """Resource requirements always satisfy non-negative bounds."""
    assert res.cpus >= 1
    assert res.ram_mb >= 128
    assert res.gpus >= 0
    assert res.scratch_mb >= 0
    assert res.walltime_seconds >= 10


@given(job_spec_strategy())
def test_job_spec_invariants(job: JobSpec):
    """JobSpec maintains structural invariants across randomized generations."""
    assert len(job.id.strip()) > 0
    assert len(job.command.strip()) > 0
    assert job.state in JobState


@given(st.lists(st.sampled_from(list(JobState)), min_size=1, max_size=50))
def test_run_roll_up_fuzz(job_states: list[JobState]):
    """RunState roll-up produces a valid RunState for any combination of job states."""
    run_state = compute_run_state(job_states)
    assert run_state in RunState

    # Fundamental Invariant: If ALL jobs are DONE, run MUST be DONE
    if all(s == JobState.DONE for s in job_states):
        assert run_state == RunState.DONE

    # Fundamental Invariant: If ANY job is active, run MUST be RUNNING
    if any(
        s
        in (JobState.PENDING, JobState.PROVISIONING, JobState.RUNNING, JobState.CLEANUP)
        for s in job_states
    ):
        assert run_state == RunState.RUNNING


@given(collateral_bundle_strategy())
def test_collateral_bundle_invariants(bundle: CollateralBundle):
    """CollateralBundle strictly satisfies security & quarantine invariants."""
    assert len(bundle.sha256_checksum) == 64
    assert bundle.size_bytes >= 0
    assert bundle.active_pin_count >= 0

    if bundle.state == CollateralState.APPROVED:
        assert bundle.active_uri is not None
    else:
        assert bundle.active_uri is None

    if bundle.state in (CollateralState.QUARANTINED, CollateralState.REJECTED):
        assert (
            bundle.quarantine_reason is not None and len(bundle.quarantine_reason) > 0
        )


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=20),
            st.integers(min_value=0, max_value=20),
        ),
        max_size=30,
    )
)
def test_dag_topological_sort_fuzz(edges: list[tuple[int, int]]):
    """DAG engine correctly identifies cycles vs acyclic orderings in random graphs."""
    from hexaqueue_core.domain.dag import DependencyCycleError, JobDagEngine

    engine = JobDagEngine()
    all_job_ids = set()

    for u, v in edges:
        u_str = f"job-{u}"
        v_str = f"job-{v}"
        all_job_ids.add(u_str)
        all_job_ids.add(v_str)
        if u != v:
            # child u depends on parent v
            engine.add_dependency(child_job_id=u_str, parent_job_id=v_str)

    try:
        sorted_order = engine.validate_and_topological_sort(all_job_ids)
        assert set(sorted_order) == all_job_ids
        assert len(sorted_order) == len(all_job_ids)

        # Invariant: Every parent must appear before its child in the sorted order
        position = {job_id: i for i, job_id in enumerate(sorted_order)}
        for u, v in edges:
            if u != v:
                u_str = f"job-{u}"
                v_str = f"job-{v}"
                assert position[v_str] < position[u_str]
    except DependencyCycleError:
        # A valid cyclic detection
        pass
