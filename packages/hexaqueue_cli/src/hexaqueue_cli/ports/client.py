"""Client port interface for CLI command dispatching.

Notes/Architectural Intent:
    Decouples CLI commands from transport (direct in-process vs gRPC/HTTP daemon).
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from hexaqueue_cli.domain.models import ClusterStatsReport
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralTier,
)
from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.suite import SuiteSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_worker.domain.pty import PtySessionInfo, PtySessionRequest
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


class ClientPort(ABC):
    """Abstract client interface for CLI commands."""

    @abstractmethod
    async def submit_run(self, submission: RunSubmission) -> RunStatusReport:
        """Submit a pipeline run."""

    @abstractmethod
    async def submit_suite(
        self,
        suite: SuiteSpec,
        user_id: str = "default",
        elevate: bool = False,
    ) -> RunStatusReport:
        """Submit a hierarchical suite pipeline run."""

    @abstractmethod
    async def get_run_status(self, run_id: str) -> RunStatusReport:
        """Get aggregate run status."""

    @abstractmethod
    async def get_job(self, job_id: str) -> JobSpec:
        """Get individual job status."""

    @abstractmethod
    async def list_jobs(self) -> list[JobSpec]:
        """List all registered jobs across runs."""

    @abstractmethod
    async def cancel_run(
        self, run_id: str, user_id: str = "default", elevate: bool = False
    ) -> RunStatusReport:
        """Cancel a pipeline run."""

    @abstractmethod
    async def cancel_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        """Cancel an individual job."""

    @abstractmethod
    async def hold_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        """Place an administrative hold on a job."""

    @abstractmethod
    async def release_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        """Release an administrative hold on a job."""

    @abstractmethod
    async def get_logs(self, job_id: str) -> list[LogChunk]:
        """Retrieve historical logs for a job."""

    @abstractmethod
    def stream_logs(
        self, job_id: str, follow: bool = False, tail: int | None = None
    ) -> AsyncIterator[LogChunk]:
        """Stream logs for a job with optional real-time tail follow."""

    @abstractmethod
    async def get_cluster_stats(self) -> ClusterStatsReport:
        """Retrieve high-level cluster state and backlog statistics."""

    @abstractmethod
    async def get_nodes(self) -> list[NodeTelemetryPulse]:
        """Retrieve telemetry pulses for registered compute worker nodes."""

    @abstractmethod
    async def explain_job(
        self,
        job_id: str,
        requesting_user: str = "default",
        is_admin: bool = False,
    ) -> SchedulingDecisionReport:
        """Retrieve diagnostic scheduling explanation for a given job."""

    @abstractmethod
    async def get_fairshare_tree(
        self,
        requesting_user: str = "default",
        is_admin: bool = False,
    ) -> FairShareTreeReport:
        """Retrieve hierarchical fair-share tree diagnostic report."""

    @abstractmethod
    async def create_pty_session(
        self, request: PtySessionRequest, job_owner: str = "default"
    ) -> PtySessionInfo:
        """Create an interactive terminal PTY session inside a running job."""

    @abstractmethod
    async def register_collateral(
        self,
        name: str,
        size_bytes: int,
        checksum_sha256: str,
        tier: CollateralTier = CollateralTier.TEMPORARY,
        kind: CollateralKind = CollateralKind.BUNDLE,
        target_path: str = "",
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Register and stage a collateral asset."""

    @abstractmethod
    async def create_bastion_session(
        self,
        node_id: str,
        session_id: str = "",
        user_id: str = "default",
        elevate: bool = False,
    ) -> PtySessionInfo:
        """Create an administrative bastion terminal session."""


__all__ = [
    "ClientPort",
]
