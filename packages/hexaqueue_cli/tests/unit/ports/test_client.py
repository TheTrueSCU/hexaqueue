"""Tests for ClientPort interface."""

import inspect
from datetime import UTC, datetime

import pytest

from hexaqueue_cli.domain.models import ClusterStatsReport
from hexaqueue_cli.ports.client import ClientPort
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
    PriorityBreakdown,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, RunState
from hexaqueue_core.domain.suite import SuiteSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_worker.domain.pty import PtySessionInfo, PtySessionRequest
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


class DummyClient(ClientPort):
    """Concrete implementation for ClientPort tests."""

    async def submit_run(
        self,
        submission: RunSubmission,
        user_id: str = "default",
        elevate: bool = False,
    ) -> RunStatusReport:
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

    async def get_run_status(
        self,
        run_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> RunStatusReport:
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

    async def get_job(
        self,
        job_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> JobSpec:
        return JobSpec(id=job_id, run_id="r1", name="j1", command="echo 1")

    async def cancel_run(
        self, run_id: str, user_id: str = "default", elevate: bool = False
    ) -> RunStatusReport:
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

    async def get_logs(
        self,
        job_id: str,
        tail: int | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[LogChunk]:
        return [LogChunk(job_id=job_id, content="hello", offset=0)]

    async def get_log_download_url(
        self,
        job_id: str,
        expires_in_seconds: int = 900,
        user_id: str = "default",
        elevate: bool = False,
    ) -> str:
        return f"https://storage.example.com/download/logs/{job_id}/stdout.log"

    async def explain_job(
        self,
        job_id: str,
        requesting_user: str = "default",
        is_admin: bool = False,
    ) -> SchedulingDecisionReport:
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
    ) -> FairShareTreeReport:
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

    async def cancel_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        return JobSpec(id=job_id, run_id="r1", name="j1", command="echo 1")

    async def hold_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        return JobSpec(id=job_id, run_id="r1", name="j1", command="echo 1")

    async def release_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        return JobSpec(id=job_id, run_id="r1", name="j1", command="echo 1")

    async def list_jobs(
        self,
        run_id: str | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[JobSpec]:
        return [JobSpec(id="j1", run_id=run_id or "r1", name="j1", command="echo 1")]

    async def list_runs(
        self,
        limit: int = 100,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[RunStatusReport]:
        return [
            RunStatusReport(
                run_id="r1",
                state=RunState.DONE,
                total_jobs=1,
                completed_jobs=1,
                failed_jobs=0,
                running_jobs=0,
                pending_jobs=0,
                created_at=datetime.now(UTC),
            )
        ]

    async def stream_logs(
        self, job_id: str, follow: bool = False, tail: int | None = None
    ):
        yield LogChunk(job_id=job_id, content="hello", offset=0)

    async def get_cluster_stats(
        self, user_id: str = "default", elevate: bool = False
    ) -> ClusterStatsReport:
        return ClusterStatsReport()

    async def get_nodes(
        self, user_id: str = "default", elevate: bool = False
    ) -> list[NodeTelemetryPulse]:
        return [
            NodeTelemetryPulse(
                worker_id="w1",
                memory_total_mb=1024,
                memory_used_mb=256,
                scratch_total_mb=1024,
                scratch_used_mb=128,
            )
        ]

    async def create_pty_session(
        self, request: PtySessionRequest, job_owner: str = "default"
    ) -> PtySessionInfo:
        return PtySessionInfo(
            session_id=request.session_id,
            job_id=request.job_id,
            user_id=request.user_id,
            pid=1234,
        )

    async def submit_suite(
        self, suite: SuiteSpec, user_id: str = "default", elevate: bool = False
    ) -> RunStatusReport:
        return RunStatusReport(
            run_id=suite.id,
            state=RunState.DONE,
            total_jobs=1,
            completed_jobs=1,
            failed_jobs=0,
            running_jobs=0,
            pending_jobs=0,
            created_at=datetime.now(UTC),
        )

    def _dummy_bundle(
        self,
        collateral_id: str = "col-1",
        name: str = "bundle.tar.gz",
        tier: CollateralTier = CollateralTier.TEMPORARY,
        kind: CollateralKind = CollateralKind.BUNDLE,
        checksum: str = "0" * 64,
        size_bytes: int = 5,
    ) -> CollateralBundle:
        return CollateralBundle(
            id=collateral_id,
            job_id="global",
            filename=name,
            size_bytes=size_bytes,
            sha256_checksum=checksum if len(checksum) == 64 else checksum.zfill(64),
            tier=tier,
            kind=kind,
            state=CollateralState.REGISTERED,
            staging_uri=f"s3://staging/{name}",
        )

    async def register_collateral(
        self,
        name: str,
        size_bytes: int,
        checksum_sha256: str,
        tier: CollateralTier = CollateralTier.TEMPORARY,
        kind: CollateralKind = CollateralKind.BUNDLE,
        target_path: str = "",
        ttl_seconds: int | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        return self._dummy_bundle(
            name=name,
            tier=tier,
            kind=kind,
            checksum=checksum_sha256,
            size_bytes=size_bytes,
        )

    async def list_collateral(
        self,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[CollateralBundle]:
        return [self._dummy_bundle()]

    async def get_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        return self._dummy_bundle(collateral_id=collateral_id)

    async def promote_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        return self._dummy_bundle(
            collateral_id=collateral_id, tier=CollateralTier.PERMANENT
        )

    async def pin_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        return self._dummy_bundle(collateral_id=collateral_id)

    async def unpin_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        return self._dummy_bundle(collateral_id=collateral_id)

    async def delete_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> str:
        return collateral_id

    async def evict_expired_collateral(
        self,
        max_age_seconds: int | None = None,
        high_watermark_bytes: int | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[str]:
        return []

    async def create_bastion_session(
        self,
        node_id: str,
        session_id: str = "",
        user_id: str = "default",
        elevate: bool = False,
    ) -> PtySessionInfo:
        return PtySessionInfo(
            session_id=session_id or "bastion-1",
            job_id=f"bastion-{node_id}",
            user_id=user_id,
            pid=999,
        )


def test_client_port_instantiation() -> None:
    """Verify concrete subclass can be instantiated."""
    client = DummyClient()
    res = isinstance(client, ClientPort)
    assert res is True


@pytest.mark.asyncio
async def test_client_port_get_log_download_url() -> None:
    """Verify get_log_download_url returns valid storage link."""
    client = DummyClient()
    url = await client.get_log_download_url(job_id="job-999")
    assert "logs/job-999/stdout.log" in url


def test_client_port_is_abstract() -> None:
    """Verify that ClientPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(ClientPort)
    assert is_abs is True
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        ClientPort()  # ty: ignore[abstract-class-instantiation] # type: ignore[abstract]


def test_client_port_abstract_methods() -> None:
    """Verify abstract methods on ClientPort."""
    expected = {
        "cancel_job",
        "cancel_run",
        "create_bastion_session",
        "create_pty_session",
        "delete_collateral",
        "evict_expired_collateral",
        "explain_job",
        "get_cluster_stats",
        "get_collateral",
        "get_fairshare_tree",
        "get_job",
        "get_log_download_url",
        "get_logs",
        "get_nodes",
        "get_run_status",
        "hold_job",
        "list_collateral",
        "list_jobs",
        "list_runs",
        "pin_collateral",
        "promote_collateral",
        "register_collateral",
        "release_job",
        "stream_logs",
        "submit_run",
        "submit_suite",
        "unpin_collateral",
    }
    abstracts = ClientPort.__abstractmethods__
    assert abstracts == expected
