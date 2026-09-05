"""Synthetic data generation and testing strategies for Hexaqueue.

Notes/Architectural Intent:
    Provides deterministic Hypothesis strategies and Faker helpers for
    reproducible property-based testing and state machine fuzzing.
"""

from hypothesis import strategies as st

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus, TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements


@st.composite
def resource_requirements_strategy(draw: st.DrawFn) -> ResourceRequirements:
    """Hypothesis strategy for generating valid ResourceRequirements."""
    cpus = draw(st.integers(min_value=1, max_value=128))
    ram_mb = draw(st.integers(min_value=128, max_value=512_000))
    gpus = draw(st.integers(min_value=0, max_value=8))
    gpu_model = (
        draw(st.sampled_from([None, "h100", "a100", "l4", "t4"])) if gpus > 0 else None
    )
    vram_mb = draw(st.integers(min_value=1024, max_value=80_000)) if gpus > 0 else None
    scratch_mb = draw(st.integers(min_value=0, max_value=1_000_000))
    walltime_seconds = draw(st.integers(min_value=10, max_value=86400))

    return ResourceRequirements(
        cpus=cpus,
        ram_mb=ram_mb,
        gpus=gpus,
        gpu_model=gpu_model,
        vram_mb=vram_mb,
        scratch_mb=scratch_mb,
        walltime_seconds=walltime_seconds,
    )


@st.composite
def job_status_strategy(draw: st.DrawFn) -> JobStatus:
    """Hypothesis strategy for generating valid JobStatus value objects."""
    state = draw(st.sampled_from(list(JobState)))
    if state == JobState.DONE:
        outcome = draw(st.sampled_from(list(TerminalOutcome)))
    else:
        outcome = None
    reason = draw(st.one_of(st.none(), st.text(max_size=50)))

    return JobStatus(state=state, outcome=outcome, reason=reason)


@st.composite
def job_spec_strategy(draw: st.DrawFn) -> JobSpec:
    """Hypothesis strategy for generating valid JobSpec instances."""
    id_val = draw(st.text(min_size=1, max_size=20).filter(lambda s: bool(s.strip())))
    run_id = draw(st.text(min_size=1, max_size=20).filter(lambda s: bool(s.strip())))
    name = draw(st.text(min_size=1, max_size=30))
    command = draw(st.text(min_size=1, max_size=20).filter(lambda s: bool(s.strip())))
    resources = draw(resource_requirements_strategy())
    status = draw(job_status_strategy())

    return JobSpec(
        id=id_val,
        run_id=run_id,
        name=name,
        command=command,
        resources=resources,
        status=status,
    )
