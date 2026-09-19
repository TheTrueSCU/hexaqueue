"""Tests for ClientPort interface."""

from datetime import UTC, datetime

from hexaqueue_cli.ports.client import ClientPort
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import RunState
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission


class DummyClient(ClientPort):
    """Concrete implementation for ClientPort tests."""

    async def submit_run(self, submission: RunSubmission) -> RunStatusReport:
        return RunStatusReport(
            run_id=submission.run_spec.id,
            state=RunState.SUBMITTED,
            total_jobs=1,
            completed_jobs=0,
            failed_jobs=0,
            running_jobs=0,
            pending_jobs=1,
            created_at=datetime.now(UTC),
        )

    async def get_run_status(self, run_id: str) -> RunStatusReport:
        return RunStatusReport(
            run_id=run_id,
            state=RunState.DONE,
            total_jobs=1,
            completed_jobs=1,
            failed_jobs=0,
            running_jobs=0,
            pending_jobs=0,
            created_at=datetime.now(UTC),
        )

    async def get_job(self, job_id: str) -> JobSpec:
        return JobSpec(id=job_id, run_id="r1", name="j1", command="echo 1")

    async def cancel_run(self, run_id: str) -> RunStatusReport:
        return RunStatusReport(
            run_id=run_id,
            state=RunState.DONE,
            total_jobs=1,
            completed_jobs=0,
            failed_jobs=0,
            running_jobs=0,
            pending_jobs=0,
            created_at=datetime.now(UTC),
        )

    async def get_logs(self, job_id: str) -> list[LogChunk]:
        return [LogChunk(job_id=job_id, content="hello", offset=0)]

    async def explain_job(
        self,
        job_id: str,
        requesting_user: str = "default",
        is_admin: bool = False,
    ):
        from hexaqueue_core.domain.explainability import (
            PriorityBreakdown,
            SchedulingDecisionReport,
        )
        from hexaqueue_core.domain.lifecycle import JobState

        bd = PriorityBreakdown(
            base_score=10.0,
            age_score=10.0,
            fairshare_score=10.0,
            preemption_bonus=0.0,
            total_priority=30.0,
            age_seconds=10.0,
            fairshare_factor=1.0,
            target_share=1.0,
            actual_usage=0.0,
        )
        return SchedulingDecisionReport(
            job_id=job_id,
            user=requesting_user,
            state=JobState.PENDING,
            queue_position=1,
            queue_total=1,
            priority_breakdown=bd,
            summary="Dummy ready",
        )

    async def get_fairshare_tree(
        self,
        requesting_user: str = "default",
        is_admin: bool = False,
    ):
        from hexaqueue_core.domain.explainability import (
            FairShareNodeReport,
            FairShareTreeReport,
        )

        node = FairShareNodeReport(
            id="root",
            shares=1.0,
            target_share=1.0,
            raw_usage=0.0,
            decayed_usage=0.0,
            fairshare_factor=1.0,
            children=[],
        )
        return FairShareTreeReport(
            root=node,
            half_life_seconds=86400.0,
            total_decayed_usage=0.0,
        )

    async def cancel_job(self, job_id: str) -> JobSpec:
        return JobSpec(id=job_id, run_id="r1", name="j1", command="echo 1")

    async def hold_job(self, job_id: str) -> JobSpec:
        return JobSpec(id=job_id, run_id="r1", name="j1", command="echo 1")

    async def release_job(self, job_id: str) -> JobSpec:
        return JobSpec(id=job_id, run_id="r1", name="j1", command="echo 1")

    async def list_jobs(self) -> list[JobSpec]:
        return [JobSpec(id="j1", run_id="r1", name="j1", command="echo 1")]

    async def stream_logs(
        self, job_id: str, follow: bool = False, tail: int | None = None
    ):
        yield LogChunk(job_id=job_id, content="hello", offset=0)

    async def get_cluster_stats(self):
        from hexaqueue_cli.domain.models import ClusterStatsReport

        return ClusterStatsReport()

    async def get_nodes(self):
        from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse

        return [
            NodeTelemetryPulse(
                worker_id="w1",
                memory_total_mb=1024,
                memory_used_mb=256,
                scratch_total_mb=1024,
                scratch_used_mb=128,
            )
        ]

    async def create_pty_session(self, request, job_owner: str = "default"):
        from hexaqueue_worker.domain.pty import PtySessionInfo

        return PtySessionInfo(
            session_id=request.session_id,
            job_id=request.job_id,
            user_id=request.user_id,
            pid=1234,
        )


def test_client_port_instantiation() -> None:
    """Verify concrete subclass can be instantiated."""
    client = DummyClient()
    res = isinstance(client, ClientPort)
    assert res is True
