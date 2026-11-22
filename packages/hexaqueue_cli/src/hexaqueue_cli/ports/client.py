"""Client port interface for interacting with the scheduler backend."""

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
    """Abstract client interface for CLI commands.

    Notes/Architectural Intent:
        Defines the hexagonal driving port connecting Typer CLI subcommands to
        local in-process CQRS execution or remote ``hexaqueue-server`` REST APIs.
    """

    @abstractmethod
    async def submit_run(
        self,
        submission: RunSubmission,
        user_id: str = "default",
        elevate: bool = False,
    ) -> RunStatusReport:
        """Submit a pipeline run.

        Args:
            submission: Validated RunSubmission payload.
            user_id: Submitting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            Initial RunStatusReport for the submitted run.
        """

    @abstractmethod
    async def submit_suite(
        self,
        suite: SuiteSpec,
        user_id: str = "default",
        elevate: bool = False,
    ) -> RunStatusReport:
        """Submit a hierarchical suite pipeline run.

        Args:
            suite: Hierarchical SuiteSpec payload.
            user_id: Submitting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            Initial RunStatusReport for the compiled suite run.
        """

    @abstractmethod
    async def get_run_status(
        self,
        run_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> RunStatusReport:
        """Get aggregate run status.

        Args:
            run_id: Pipeline run identifier.
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            Current RunStatusReport snapshot.
        """

    @abstractmethod
    async def get_job(
        self,
        job_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> JobSpec:
        """Get individual job status.

        Args:
            job_id: Job identifier.
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            Current JobSpec metadata and status.
        """

    @abstractmethod
    async def list_jobs(
        self,
        run_id: str | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[JobSpec]:
        """List registered jobs across runs or filtered by run identifier.

        Args:
            run_id: Optional run identifier filter.
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            List of authorized JobSpec instances.
        """

    @abstractmethod
    async def list_runs(
        self,
        limit: int = 100,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[RunStatusReport]:
        """List registered pipeline runs visible to the requesting user.

        Args:
            limit: Maximum number of runs to return.
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            List of authorized RunStatusReport instances.
        """

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
    async def get_logs(
        self,
        job_id: str,
        tail: int | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[LogChunk]:
        """Retrieve historical logs for a job.

        Args:
            job_id: Target job identifier.
            tail: Optional trailing chunk limit.
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            List of LogChunk records.
        """

    @abstractmethod
    async def get_log_download_url(
        self,
        job_id: str,
        expires_in_seconds: int = 900,
        user_id: str = "default",
        elevate: bool = False,
    ) -> str:
        """Retrieve presigned direct download URL for job execution logs.

        Args:
            job_id: Target job identifier.
            expires_in_seconds: Presigned download link expiration TTL in seconds.
            user_id: Identity of requesting user.
            elevate: Explicit administrative privilege elevation flag.

        Returns:
            Preauthenticated direct object storage download URL.
        """

    @abstractmethod
    def stream_logs(
        self, job_id: str, follow: bool = False, tail: int | None = None
    ) -> AsyncIterator[LogChunk]:
        """Stream logs for a job with optional real-time tail follow."""

    @abstractmethod
    async def get_cluster_stats(
        self, user_id: str = "default", elevate: bool = False
    ) -> ClusterStatsReport:
        """Retrieve high-level cluster state and backlog statistics.

        Args:
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            Aggregate ClusterStatsReport snapshot.
        """

    @abstractmethod
    async def get_nodes(
        self, user_id: str = "default", elevate: bool = False
    ) -> list[NodeTelemetryPulse]:
        """Retrieve telemetry pulses for registered compute worker nodes.

        Args:
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            List of NodeTelemetryPulse metrics.
        """

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
        ttl_seconds: int | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Register and stage a collateral bundle into CAS storage."""

    @abstractmethod
    async def list_collateral(
        self,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[CollateralBundle]:
        """List collateral bundles visible to the requesting user.

        Args:
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            List of authorized CollateralBundle records.
        """

    @abstractmethod
    async def get_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Retrieve metadata for a single collateral bundle.

        Args:
            collateral_id: Collateral bundle identifier.
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            CollateralBundle metadata record.
        """

    @abstractmethod
    async def promote_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Promote a TEMPORARY collateral bundle to the PERMANENT tier.

        Args:
            collateral_id: Collateral bundle identifier.
            user_id: Requesting user identity.
            elevate: Explicit administrative elevation flag.

        Returns:
            Updated CollateralBundle with PERMANENT tier.
        """

    @abstractmethod
    async def pin_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Pin a collateral bundle to prevent eviction during execution.

        Args:
            collateral_id: Collateral bundle identifier.
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            Updated CollateralBundle with incremented active_pin_count.
        """

    @abstractmethod
    async def unpin_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Unpin a collateral bundle to allow garbage collection eligibility.

        Args:
            collateral_id: Collateral bundle identifier.
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            Updated CollateralBundle with decremented active_pin_count.
        """

    @abstractmethod
    async def delete_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> str:
        """Delete an unused collateral bundle from CAS storage.

        Args:
            collateral_id: Collateral bundle identifier.
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            Deleted collateral bundle identifier.
        """

    @abstractmethod
    async def evict_expired_collateral(
        self,
        max_age_seconds: int | None = None,
        high_watermark_bytes: int | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[str]:
        """Trigger garbage collection eviction for expired temporary collateral.

        Args:
            max_age_seconds: Optional maximum age in seconds before eviction.
            high_watermark_bytes: Optional storage ceiling in bytes.
            user_id: Requesting user identity.
            elevate: Administrative privilege elevation flag.

        Returns:
            List of evicted collateral bundle identifiers.
        """

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
