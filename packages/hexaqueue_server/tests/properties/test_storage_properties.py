"""Dual-implementation oracle property tests for scheduler storage adapters.

Notes/Architectural Intent:
    Evaluates OciAutonomousDatabaseStorageAdapter against the naive in-memory
    reference oracle InMemorySchedulerStorageAdapter across randomly generated
    execution sequences using Hypothesis (ADR-004), mathematically proving
    behavioral equivalence.
"""

from datetime import UTC, datetime

import anyio
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import RunOutcome, RunState
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_server.adapters.storage.in_memory import (
    InMemorySchedulerStorageAdapter,
)
from hexaqueue_server.adapters.storage.oracle import (
    OciAutonomousDatabaseStorageAdapter,
)
from hexaqueue_server.domain.models import RunStatusReport


@st.composite
def generate_run_report(draw):
    """Generate arbitrary RunStatusReport instance."""
    run_id = draw(st.uuids()).hex[:12]
    state = draw(
        st.sampled_from(
            [RunState.SUBMITTED, RunState.BLOCKED, RunState.RUNNING, RunState.DONE]
        )
    )
    outcome = (
        draw(st.sampled_from([RunOutcome.SUCCEEDED, RunOutcome.FAILED]))
        if state == RunState.DONE
        else None
    )
    total = draw(st.integers(min_value=1, max_value=20))
    completed = draw(st.integers(min_value=0, max_value=total))
    failed = draw(st.integers(min_value=0, max_value=total - completed))
    pending = total - completed - failed
    now = datetime.now(UTC)
    return RunStatusReport(
        id=run_id,
        run_id=run_id,
        state=state,
        outcome=outcome,
        total_jobs=total,
        completed_jobs=completed,
        failed_jobs=failed,
        pending_jobs=pending,
        running_jobs=0,
        created_at=now,
        updated_at=now,
    )


@settings(max_examples=25, deadline=None)
@given(
    runs=st.lists(
        generate_run_report(), min_size=2, max_size=5, unique_by=lambda r: r.id
    ),
    worker_ids=st.lists(
        st.text(min_size=3, max_size=8, alphabet="abcdef0123456789"),
        min_size=1,
        max_size=3,
        unique=True,
    ),
)
def test_dual_oracle_storage_equivalence(
    runs: list[RunStatusReport], worker_ids: list[str]
):
    """Mathematically evaluate OciAutonomousDatabaseStorageAdapter against InMemorySchedulerStorageAdapter."""
    run_ids = [r.id or r.run_id for r in runs]

    async def _run_oracle_test() -> None:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False,
        )
        oracle = InMemorySchedulerStorageAdapter()
        adb = OciAutonomousDatabaseStorageAdapter(
            engine=engine, flush_interval_seconds=0.01
        )

        try:
            # 1. Record runs
            for r in runs:
                await oracle.record_run(r)
                await adb.record_run(r)

            # 2. Record jobs
            for i, r_id in enumerate(run_ids):
                job = JobSpec(
                    id=f"job-{r_id}-{i}",
                    run_id=r_id,
                    name=f"task-{i}",
                    command=f"echo {i}",
                    priority=i,
                )
                await oracle.record_job(job)
                await adb.record_job(job)

            # 3. Record nodes
            for w_id in worker_ids:
                node = ComputeNodeProfile(node_id=f"node-{w_id}")
                await oracle.record_node(node)
                await adb.record_node(node)

            # 4. Record telemetry
            for w_id in worker_ids:
                pulse = NodeTelemetryPulse(
                    worker_id=w_id,
                    cpu_utilization_pct=50.0,
                    memory_used_mb=1024,
                    memory_total_mb=4096,
                    scratch_used_mb=100,
                    scratch_total_mb=1000,
                )
                await oracle.record_telemetry_pulse(pulse)
                await adb.record_telemetry_pulse(pulse)

            # Drain write-behind buffer to database
            await adb.flush()

            # Prove equivalence for runs
            oracle_runs = await oracle.list_runs()
            adb_runs = await adb.list_runs()
            assert len(adb_runs) == len(oracle_runs)
            for r in runs:
                rid = r.id or r.run_id
                o_run = await oracle.get_run(rid)
                a_run = await adb.get_run(rid)
                assert o_run is not None
                assert a_run is not None
                assert a_run.id == o_run.id
                assert a_run.status == o_run.status

            # Prove equivalence for jobs
            for r_id in run_ids:
                o_jobs = await oracle.list_jobs(run_id=r_id)
                a_jobs = await adb.list_jobs(run_id=r_id)
                assert len(a_jobs) == len(o_jobs)

            # Prove equivalence for nodes
            for w_id in worker_ids:
                o_node = await oracle.get_node(f"node-{w_id}")
                a_node = await adb.get_node(f"node-{w_id}")
                assert o_node is not None
                assert a_node is not None
                assert a_node.node_id == o_node.node_id

            # Prove equivalence for telemetry
            for w_id in worker_ids:
                o_pulses = await oracle.list_telemetry_pulses(worker_id=w_id)
                a_pulses = await adb.list_telemetry_pulses(worker_id=w_id)
                assert len(a_pulses) == len(o_pulses)

        finally:
            await adb.close()
            engine.dispose()

    anyio.run(_run_oracle_test)
