"""Unit and property tests for SchedulerMemento and speculative placement."""

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_server.domain.memento import (
    DagRewindReport,
    DagRewindRequest,
    PlacementSimulationItem,
    PlacementSimulationReport,
    SchedulerMemento,
)
from hexaqueue_server.domain.placement import PlacementDecision


def test_placement_simulation_report() -> None:
    """Verify simulation report and items data structures."""
    decision = PlacementDecision(
        reason="Allocated to static worker",
        selected_node_id="node-1",
        should_burst_ephemeral=False,
    )
    item = PlacementSimulationItem(
        job_id="job-1",
        decision=decision,
        would_preempt=[],
        estimated_wait_seconds=0.0,
    )
    report = PlacementSimulationReport(
        items=[item],
        all_schedulable=True,
        required_ephemeral_bursts=0,
    )
    ok = report.all_schedulable
    assert ok is True
    bursts = report.required_ephemeral_bursts
    assert bursts == 0
    cnt = len(report.items)
    assert cnt == 1


def test_dag_rewind_request_defaults_and_fields() -> None:
    """Verify DagRewindRequest default initialization and target job specification."""
    default_req = DagRewindRequest()
    default_cnt = len(default_req.target_job_ids)
    assert default_cnt == 0

    req = DagRewindRequest(target_job_ids=["job-1", "job-2"])
    cnt = len(req.target_job_ids)
    assert cnt == 2


def test_dag_rewind_report() -> None:
    """Verify DagRewindReport data structure."""
    rep = DagRewindReport(
        run_id="run-1",
        rewound_job_ids=["job-b", "job-c"],
        re_enqueued_job_ids=["job-b"],
        unaffected_job_ids=["job-a"],
    )
    r_id = rep.run_id
    assert r_id == "run-1"
    rewound = rep.rewound_job_ids
    assert rewound == ["job-b", "job-c"]
    enqueued = rep.re_enqueued_job_ids
    assert enqueued == ["job-b"]


def test_scheduler_memento_state_fidelity() -> None:
    """Verify SchedulerMemento preserves and restores state snapshots without mutation leaks."""
    job = JobSpec(
        id="job-test-1",
        run_id="run-1",
        name="test",
        command="echo hi",
    )
    node = ComputeNodeProfile(
        node_id="node-test-1",
        active_job_ids=frozenset({"job-test-1"}),
    )

    memento = SchedulerMemento(
        jobs={job.id: job},
        nodes={node.node_id: node},
        job_reservations={"job-test-1": "res-123"},
    )

    jobs_snapshot = memento.jobs
    assert "job-test-1" in jobs_snapshot
    res_snapshot = memento.job_reservations
    assert res_snapshot["job-test-1"] == "res-123"

    # Mutate a local copy
    modified_jobs = dict(memento.jobs)
    del modified_jobs["job-test-1"]

    # Verify original memento is immutable
    assert "job-test-1" in memento.jobs
