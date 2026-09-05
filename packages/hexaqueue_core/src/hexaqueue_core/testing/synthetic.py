"""Synthetic data generation and testing strategies for Hexaqueue.

Notes/Architectural Intent:
    Provides deterministic Hypothesis strategies and Faker helpers for
    reproducible property-based testing and state machine fuzzing.
"""

from hypothesis import strategies as st

from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
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


@st.composite
def collateral_bundle_strategy(draw: st.DrawFn) -> CollateralBundle:
    """Hypothesis strategy for generating valid CollateralBundle instances."""
    id_val = draw(st.text(min_size=1, max_size=20).filter(lambda s: bool(s.strip())))
    job_id = draw(st.text(min_size=1, max_size=20).filter(lambda s: bool(s.strip())))
    filename = draw(st.text(min_size=1, max_size=30).filter(lambda s: bool(s.strip())))
    size_bytes = draw(st.integers(min_value=0, max_value=10_000_000_000))
    sha256 = draw(st.text(alphabet="0123456789abcdef", min_size=64, max_size=64))
    kind = draw(st.sampled_from(list(CollateralKind)))
    tier = draw(st.sampled_from(list(CollateralTier)))
    state = draw(st.sampled_from(list(CollateralState)))
    staging_uri = f"s3://quarantine/{id_val}/{filename}"

    if state == CollateralState.APPROVED:
        active_uri = f"s3://clean/{sha256}/{filename}"
        quarantine_reason = None
    elif state in (CollateralState.QUARANTINED, CollateralState.REJECTED):
        active_uri = None
        quarantine_reason = draw(st.text(min_size=1, max_size=40))
    else:
        active_uri = None
        quarantine_reason = None

    pin_count = draw(st.integers(min_value=0, max_value=100))

    return CollateralBundle(
        id=id_val,
        job_id=job_id,
        filename=filename,
        size_bytes=size_bytes,
        sha256_checksum=sha256,
        kind=kind,
        tier=tier,
        state=state,
        staging_uri=staging_uri,
        active_uri=active_uri,
        quarantine_reason=quarantine_reason,
        active_pin_count=pin_count,
    )
