"""Tests for SchedulerControllerPort interface."""

import inspect
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import (
    JobState,
    JobStatus,
    RunState,
    TerminalOutcome,
)
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.retry import DeadLetterRecord
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_server.domain.memento import (
    DagRewindReport,
    PlacementSimulationReport,
    SchedulerMemento,
)
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_server.domain.placement import PlacementDecision
from hexaqueue_server.ports.controller import SchedulerControllerPort


def test_scheduler_controller_port_is_abstract() -> None:
    """Verify SchedulerControllerPort is an abstract interface."""
    assert inspect.isabstract(SchedulerControllerPort)
    assert "submit_run" in SchedulerControllerPort.__abstractmethods__


@pytest.mark.asyncio
async def test_scheduler_controller_port_concrete_implementation() -> None:
    """Verify concrete subclass can implement all abstract methods."""

    class DummyController(SchedulerControllerPort):
        async def submit_run(self, submission: RunSubmission) -> RunStatusReport:
            return RunStatusReport(
                completed_jobs=0,
                created_at=datetime.now(UTC),
                failed_jobs=0,
                pending_jobs=len(submission.jobs),
                run_id=submission.run_spec.id,
                running_jobs=0,
                state=RunState.RUNNING,
                total_jobs=len(submission.jobs),
            )

        async def get_run_status(self, run_id: str) -> RunStatusReport:
            return RunStatusReport(
                completed_jobs=0,
                created_at=datetime.now(UTC),
                failed_jobs=0,
                pending_jobs=1,
                run_id=run_id,
                running_jobs=0,
                state=RunState.RUNNING,
                total_jobs=1,
            )

        async def get_job(self, job_id: str) -> JobSpec:
            return JobSpec(id=job_id, run_id="r1", name="j", command="echo")

        async def update_job_outcome(
            self,
            job_id: str,
            outcome: TerminalOutcome,
            reason: str | None = None,
            walltime_seconds: float | None = None,
            consumed_credits: float | None = None,
        ) -> None:
            pass

        async def cancel_run(self, run_id: str) -> RunStatusReport:
            return RunStatusReport(
                completed_jobs=0,
                created_at=datetime.now(UTC),
                failed_jobs=0,
                pending_jobs=0,
                run_id=run_id,
                running_jobs=0,
                state=RunState.DONE,
                total_jobs=1,
            )

        async def list_jobs(self) -> list[JobSpec]:
            return []

        async def cancel_job(self, job_id: str) -> JobSpec:
            return JobSpec(
                id=job_id,
                run_id="r1",
                name="j",
                command="echo",
                status=JobStatus(
                    state=JobState.DONE, outcome=TerminalOutcome.CANCELLED
                ),
            )

        async def hold_job(self, job_id: str) -> JobSpec:
            return JobSpec(
                id=job_id,
                run_id="r1",
                name="j",
                command="echo",
                status=JobStatus(state=JobState.BLOCKED),
            )

        async def release_job(self, job_id: str) -> JobSpec:
            return JobSpec(id=job_id, run_id="r1", name="j", command="echo")

        async def register_node(self, profile: ComputeNodeProfile) -> None:
            pass

        async def heartbeat_node(
            self,
            worker_id: str,
            active_job_ids: list[str] | None = None,
            cached_collateral_hashes: list[str] | None = None,
            pulse: NodeTelemetryPulse | None = None,
        ) -> ComputeNodeProfile:
            return ComputeNodeProfile(node_id=worker_id)

        async def list_nodes(self) -> list[ComputeNodeProfile]:
            return [ComputeNodeProfile(node_id="n1")]

        async def evaluate_node_failures(
            self,
            timeout_unhealthy_seconds: float = 15.0,
            timeout_dead_seconds: float = 30.0,
        ) -> list[ComputeNodeProfile]:
            return []

        async def list_dead_letters(self, limit: int = 50) -> list[DeadLetterRecord]:
            return []

        async def schedule_placement(
            self,
            job_id: str,
            collateral_hash_map: dict[str, str] | None = None,
        ) -> PlacementDecision:
            return PlacementDecision(reason="dummy", selected_node_id="n1")

        def create_memento(self) -> SchedulerMemento:
            return SchedulerMemento()

        def restore_memento(self, memento: SchedulerMemento) -> None:
            pass

        async def simulate_placement(
            self,
            candidate_jobs: Sequence[JobSpec],
            collateral_hash_map: dict[str, str] | None = None,
        ) -> PlacementSimulationReport:
            return PlacementSimulationReport(
                all_schedulable=True,
                items=[],
                required_ephemeral_bursts=0,
            )

        async def rewind_run(
            self,
            run_id: str,
            target_job_ids: Sequence[str],
        ) -> DagRewindReport:
            return DagRewindReport(
                run_id=run_id,
                rewound_job_ids=list(target_job_ids),
                re_enqueued_job_ids=list(target_job_ids),
                unaffected_job_ids=[],
            )

    controller = DummyController()
    nodes = await controller.list_nodes()
    node_count = len(nodes)
    assert node_count == 1
    placement = await controller.schedule_placement("j1")
    sel_id = placement.selected_node_id
    assert sel_id == "n1"
    mem = controller.create_memento()
    controller.restore_memento(mem)
    sim = await controller.simulate_placement([])
    sched = sim.all_schedulable
    assert sched is True
    rewind = await controller.rewind_run("r1", ["j1"])
    rewound_cnt = len(rewind.rewound_job_ids)
    assert rewound_cnt == 1
