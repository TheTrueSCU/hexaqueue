"""Unified CQRS command and query contracts.

Notes/Architectural Intent:
    Serves as the Single Source of Truth for all state transitions and queries
    across Hexaqueue interfaces (CLI, REST OpenAPI, gRPC Protobufs, and Web Dashboard).
    Every capability in Hexaqueue is modeled as an immutable Command or Query
    adhering to Hexagonal boundaries and the Principle of Least Privilege:
    callers execute under their natural identity, requiring explicit elevation
    (`elevate=True`) when mutating or inspecting cross-tenant resources.
"""

from datetime import UTC, datetime

from hexastack_core.domain import Command, Query
from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.collateral import CollateralKind, CollateralTier
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.retention import LogRetentionPolicy
from hexaqueue_core.domain.retry import DeadLetterRecord
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.domain.suite import SuiteSpec


class SubmitRunCommand(Command):
    """Command to submit a directed acyclic graph (DAG) pipeline run.

    Args:
        run_spec: Root pipeline metadata and constraints.
        jobs: List of JobSpec definitions in this run.
        dependencies: Adjacency map of child_job_id -> list[parent_job_ids].
        user_id: Natural identity of submitting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dependencies: dict[str, list[str]] = Field(
        default_factory=dict, description="Job dependency mapping"
    )
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    jobs: list[JobSpec] = Field(min_length=1, description="List of jobs in pipeline")
    run_spec: RunSpec = Field(description="Pipeline run specification")
    user_id: str = Field(default="default", description="Submitting user identity")


class SubmitSuiteCommand(Command):
    """Command to compile and submit a hierarchical suite workload.

    Args:
        suite_spec: Hierarchical suite specification with matrix expansions.
        user_id: Natural identity of submitting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    suite_spec: SuiteSpec = Field(description="Hierarchical suite specification")
    user_id: str = Field(default="default", description="Submitting user identity")


class CancelRunCommand(Command):
    """Command to cancel an active or pending pipeline run.

    Args:
        run_id: Pipeline run identifier.
        user_id: Natural identity of requesting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    run_id: str = Field(description="Pipeline run identifier to cancel")
    user_id: str = Field(default="default", description="Requesting user identity")


class HoldJobCommand(Command):
    """Command to place an administrative hold on a job.

    Args:
        job_id: Unique job identifier.
        user_id: Natural identity of requesting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    job_id: str = Field(description="Job identifier to hold")
    user_id: str = Field(default="default", description="Requesting user identity")


class ReleaseJobCommand(Command):
    """Command to release an administrative hold on a job.

    Args:
        job_id: Unique job identifier.
        user_id: Natural identity of requesting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    job_id: str = Field(description="Job identifier to release")
    user_id: str = Field(default="default", description="Requesting user identity")


class CancelJobCommand(Command):
    """Command to terminate an individual job.

    Args:
        job_id: Unique job identifier.
        user_id: Natural identity of requesting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    job_id: str = Field(description="Job identifier to cancel")
    user_id: str = Field(default="default", description="Requesting user identity")


class RegisterCollateralCommand(Command):
    """Command to register and stage collateral assets for job execution.

    Args:
        name: Logical name of the collateral asset.
        version: Semantic or content version tag.
        checksum_sha256: Cryptographic SHA256 digest of payload.
        size_bytes: Payload length in bytes.
        tier: Retention and distribution tier.
        kind: Kind/type of collateral asset.
        target_path: Container destination path.
        user_id: Submitting user identity.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    checksum_sha256: str = Field(description="Expected SHA256 hex digest")
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    kind: CollateralKind = Field(
        default=CollateralKind.BUNDLE, description="Collateral artifact kind"
    )
    name: str = Field(description="Collateral asset name")
    size_bytes: int = Field(gt=0, description="Payload size in bytes")
    target_path: str = Field(default="", description="Target destination path")
    tier: CollateralTier = Field(
        default=CollateralTier.TEMPORARY, description="Collateral retention tier"
    )
    ttl_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Optional custom time-to-live in seconds for TEMPORARY collateral",
    )
    user_id: str = Field(default="default", description="Submitting user identity")
    version: str = Field(default="latest", description="Version string")


class PinCollateralCommand(Command):
    """Command to declare active execution pinning on a collateral bundle.

    Args:
        collateral_id: Target collateral bundle identifier.
        user_id: Submitting user identity.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    collateral_id: str = Field(description="Collateral bundle identifier")
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    user_id: str = Field(default="default", description="Submitting user identity")


class UnpinCollateralCommand(Command):
    """Command to release active execution pinning on a collateral bundle.

    Args:
        collateral_id: Target collateral bundle identifier.
        user_id: Submitting user identity.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    collateral_id: str = Field(description="Collateral bundle identifier")
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    user_id: str = Field(default="default", description="Submitting user identity")


class EvictExpiredCollateralCommand(Command):
    """Command to trigger garbage collection eviction of expired temporary collateral.

    Args:
        max_age_seconds: Optional default TTL in seconds since last access.
        high_watermark_bytes: Optional storage capacity threshold in bytes.
        user_id: Submitting user identity.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    high_watermark_bytes: int | None = Field(
        default=None,
        ge=1,
        description="Optional storage budget high watermark in bytes",
    )
    max_age_seconds: int | None = Field(
        default=None, ge=1, description="Optional maximum age in seconds"
    )
    user_id: str = Field(default="default", description="Submitting user identity")


class GetCollateralBundleQuery(Query):
    """Query to retrieve metadata for a collateral bundle.

    Args:
        collateral_id: Target collateral bundle identifier.
        user_id: Requesting user identity.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    collateral_id: str = Field(description="Collateral bundle identifier")
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    user_id: str = Field(default="default", description="Requesting user identity")


class FindCollateralByChecksumQuery(Query):
    """Query to look up an approved collateral bundle by SHA-256 CAS digest.

    Args:
        sha256_checksum: Hexadecimal 64-character SHA-256 digest.
        user_id: Requesting user identity.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    sha256_checksum: str = Field(
        min_length=64, max_length=64, description="Hexadecimal SHA-256 checksum digest"
    )
    user_id: str = Field(default="default", description="Requesting user identity")


class GetCollateralDownloadUrlQuery(Query):
    """Query to vend a presigned or direct download URL for approved collateral.

    Args:
        collateral_id: Target collateral bundle identifier.
        user_id: Requesting user identity.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    collateral_id: str = Field(description="Collateral bundle identifier")
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    user_id: str = Field(default="default", description="Requesting user identity")


class CreatePtySessionCommand(Command):
    """Command to request an interactive pseudo-terminal session inside a running job.

    Args:
        job_id: Target job identifier.
        session_id: Unique interactive session identifier.
        command: Command vector to execute in PTY.
        user_id: Identity of requesting user.
        elevate: Explicit administrative privilege elevation flag.
        rows: Initial terminal rows.
        cols: Initial terminal columns.
        term_type: Emulated terminal capability string.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cols: int = Field(default=80, ge=1, le=1000, description="Terminal columns")
    command: list[str] = Field(
        default_factory=lambda: ["/bin/bash"],
        description="Command vector to spawn",
    )
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    job_id: str = Field(default="", description="Target running job identifier")
    rows: int = Field(default=24, ge=1, le=1000, description="Terminal rows")
    session_id: str = Field(
        default="", description="Unique interactive session identifier"
    )
    term_type: str = Field(
        default="xterm-256color", description="TERM environment string"
    )
    user_id: str = Field(default="default", description="Requesting user identity")


class CreateBastionSessionCommand(Command):
    """Command to launch a secure bastion shell session on a worker compute node.

    Args:
        node_id: Identifier of target compute node.
        session_id: Unique interactive session identifier.
        user_id: Identity of requesting operator.
        elevate: Explicit administrative privilege elevation flag.
        rows: Initial terminal rows.
        cols: Initial terminal columns.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cols: int = Field(default=80, ge=1, le=1000, description="Terminal columns")
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    node_id: str = Field(description="Target compute worker node identifier")
    rows: int = Field(default=24, ge=1, le=1000, description="Terminal rows")
    session_id: str = Field(description="Unique interactive session identifier")
    user_id: str = Field(default="default", description="Requesting user identity")


class SettleBudgetCommand(Command):
    """Command to settle consumption against project budget ledger.

    Args:
        project_id: Project identifier.
        amount_cents: Budget consumption amount in micro-units/cents.
        user_id: Identity of actor.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    actual_credits: float = Field(
        default=0.0, ge=0.0, description="Actual HQ credits consumed"
    )
    amount_cents: int = Field(default=0, ge=0, description="Settled consumption amount")
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    project_id: str = Field(default="", description="Project identifier")
    reservation_id: str = Field(default="", description="Reservation hold token ID")
    user_id: str = Field(default="default", description="Requesting user identity")


class ReserveBudgetCommand(Command):
    """Command to place a pre-emptive budget hold for job execution.

    Args:
        tenant_id: Target tenant account identifier.
        job_id: Target job identifier.
        estimated_credits: Maximum credits to hold.
        user_id: Identity of requesting actor.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    estimated_credits: float = Field(
        ge=0.0, description="Estimated maximum credits to hold"
    )
    job_id: str = Field(description="Job identifier")
    tenant_id: str = Field(description="Tenant or project account identifier")
    user_id: str = Field(default="default", description="Requesting user identity")


class SettleSegmentCommand(Command):
    """Command to settle an incremental execution segment upon preemption.

    Args:
        reservation_id: Target reservation hold identifier.
        segment_credits: Credits consumed during this execution segment.
        user_id: Identity of requesting actor.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    reservation_id: str = Field(description="Target reservation hold identifier")
    segment_credits: float = Field(
        ge=0.0, description="Credits consumed during this execution segment"
    )
    user_id: str = Field(default="default", description="Requesting user identity")


class ReleaseBudgetCommand(Command):
    """Command to release an active budget hold in full without billing.

    Args:
        reservation_id: Target reservation hold identifier.
        user_id: Identity of requesting actor.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    reservation_id: str = Field(description="Target reservation hold identifier")
    user_id: str = Field(default="default", description="Requesting user identity")


class GetTenantBalanceQuery(Query):
    """Query to retrieve tenant credit balance and active hold details.

    Args:
        tenant_id: Target tenant account identifier.
        user_id: Identity of requesting actor.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    tenant_id: str = Field(description="Tenant account identifier")
    user_id: str = Field(default="default", description="Requesting user identity")


class GetClusterHealthQuery(Query):
    """Query to retrieve point-in-time cluster capacity and health report.

    Args:
        user_id: Identity of requesting actor.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    user_id: str = Field(default="default", description="Requesting user identity")


class GetRunStatusQuery(Query):
    """Query to retrieve execution status of a pipeline run.

    Args:
        run_id: Pipeline run identifier.
        user_id: Identity of requesting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    run_id: str = Field(description="Pipeline run identifier")
    user_id: str = Field(default="default", description="Requesting user identity")


class GetJobQuery(Query):
    """Query to inspect a single job specification and status.

    Args:
        job_id: Unique job identifier.
        user_id: Identity of requesting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    job_id: str = Field(description="Job identifier")
    user_id: str = Field(default="default", description="Requesting user identity")


class ListJobsQuery(Query):
    """Query to list registered jobs.

    Args:
        run_id: Optional run identifier filter.
        user_id: Identity of requesting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    run_id: str | None = Field(default=None, description="Optional run ID filter")
    user_id: str = Field(default="default", description="Requesting user identity")


class ExplainJobQuery(Query):
    """Query to retrieve diagnostic explainability reasoning for a job's placement.

    Args:
        job_id: Target job identifier.
        requesting_user: User identity querying explanation.
        is_admin: Whether administrative visibility is requested.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_admin: bool = Field(
        default=False, description="Explicit administrative visibility flag"
    )
    job_id: str = Field(description="Job identifier to diagnose")
    requesting_user: str = Field(
        default="default", description="Requesting user identity"
    )


class GetFairShareTreeQuery(Query):
    """Query to retrieve the hierarchical fair-share tree report.

    Args:
        requesting_user: Identity of requesting actor.
        is_admin: Whether administrative unmasked tree is requested.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_admin: bool = Field(
        default=False, description="Explicit administrative visibility flag"
    )
    requesting_user: str = Field(
        default="default", description="Requesting user identity"
    )


class ClusterStatsReport(BaseModel):
    """Aggregate cluster state, backlog, and worker capacity metrics.

    Args:
        active_workers: Count of active worker daemons.
        blocked_jobs: Count of blocked jobs.
        completed_jobs: Count of completed jobs.
        failed_jobs: Count of failed jobs.
        pending_jobs: Count of pending jobs.
        running_jobs: Count of running jobs.
        timestamp: Stats snapshot timestamp.
        total_jobs: Total jobs count.
        total_runs: Total runs count.

    Notes/Architectural Intent:
        Represents aggregate queue backlog and compute capacity snapshot returned
        by GetQueueStatsQuery.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_workers: int = Field(
        default=1, ge=0, description="Active worker daemons count"
    )
    blocked_jobs: int = Field(default=0, ge=0, description="Blocked jobs count")
    completed_jobs: int = Field(default=0, ge=0, description="Completed jobs count")
    failed_jobs: int = Field(default=0, ge=0, description="Failed jobs count")
    pending_jobs: int = Field(default=0, ge=0, description="Pending jobs count")
    running_jobs: int = Field(default=0, ge=0, description="Running jobs count")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Stats snapshot timestamp",
    )
    total_jobs: int = Field(default=0, ge=0, description="Total jobs count")
    total_runs: int = Field(default=0, ge=0, description="Total runs count")


class GetQueueStatsQuery(Query):
    """Query to retrieve aggregate cluster queue backlog and utilization statistics.

    Args:
        user_id: Identity of requesting actor.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    user_id: str = Field(default="default", description="Requesting user identity")


class GetNodesQuery(Query):
    """Query to retrieve telemetry pulses and hardware status of compute worker nodes.

    Args:
        user_id: Identity of requesting actor.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    user_id: str = Field(default="default", description="Requesting user identity")


class ListComputeNodesQuery(Query):
    """Query to list registered compute worker node profiles.

    Args:
        user_id: Identity of requesting actor.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    user_id: str = Field(default="default", description="Requesting user identity")


class NodesReport(BaseModel):
    """Report summarizing active and registered compute worker nodes.

    Args:
        nodes: List of compute node profiles.
        total_nodes: Total count of registered nodes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: list[ComputeNodeProfile] = Field(
        default_factory=list, description="Registered compute node profiles"
    )
    total_nodes: int = Field(ge=0, description="Total node count")


class RegisterNodeCommand(Command):
    """Command to register a compute worker node with the central controller.

    Args:
        profile: Compute node profile including tier, capacity, and cached collateral.
        user_id: Identity of registering worker or orchestrator.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    profile: ComputeNodeProfile = Field(description="Worker node profile")
    user_id: str = Field(default="worker", description="Registering user or agent")


class HeartbeatNodeCommand(Command):
    """Command to emit a heartbeat pulse and synchronize active node state.

    Args:
        worker_id: Unique worker node identifier.
        active_job_ids: List of job identifiers currently in-flight on the node.
        cached_collateral_hashes: List of CAS SHA-256 hashes present in local disk cache.
        user_id: Identity of reporting worker.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_job_ids: list[str] = Field(
        default_factory=list, description="Active executing job identifiers"
    )
    cached_collateral_hashes: list[str] = Field(
        default_factory=list, description="Locally cached CAS hashes"
    )
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    user_id: str = Field(default="worker", description="Reporting worker identifier")
    worker_id: str = Field(description="Unique worker node identifier")


class GetDeadLetterQueueQuery(Query):
    """Query to inspect exhausted and dead-lettered job records.

    Args:
        limit: Maximum number of dead-letter records to retrieve.
        user_id: Identity of requesting user or operator.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    limit: int = Field(default=50, ge=1, description="Maximum records to return")
    user_id: str = Field(default="default", description="Requesting user identity")


class DeadLetterQueueReport(BaseModel):
    """Report detailing dead-lettered jobs and diagnostic root causes.

    Args:
        records: List of DeadLetterRecord entries.
        total_count: Total count of preserved dead-lettered records.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: list[DeadLetterRecord] = Field(
        default_factory=list, description="Diagnostic dead-letter records"
    )
    total_count: int = Field(ge=0, description="Total dead-lettered count")


class GetLogsQuery(Query):
    """Query to retrieve historical execution logs for a job.

    Args:
        job_id: Unique job identifier.
        tail: Optional count of trailing lines/chunks to fetch.
        user_id: Identity of requesting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    job_id: str = Field(description="Job identifier")
    tail: int | None = Field(default=None, ge=1, description="Tail chunk count")
    user_id: str = Field(default="default", description="Requesting user identity")


class StreamLogsQuery(Query):
    """Query to stream execution logs in real-time.

    Args:
        job_id: Unique job identifier.
        follow: Whether to hold connection open for live logs.
        tail: Optional historical lines count.
        user_id: Identity of requesting user.
        elevate: Explicit administrative privilege elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    follow: bool = Field(default=False, description="Live follow streaming flag")
    job_id: str = Field(description="Job identifier")
    tail: int | None = Field(default=None, ge=1, description="Tail chunk count")
    user_id: str = Field(default="default", description="Requesting user identity")


class RequestLogUploadUrlCommand(Command):
    """Command from worker to request a presigned write URL for job logs.

    Args:
        job_id: Unique job identifier.
        outcome: TerminalOutcome of the job execution.
        size_bytes: Estimated size in bytes of compressed log payload.
        expires_in_seconds: Expiration TTL for presigned upload URL.
        user_id: Identity of submitting worker or user.
        elevate: Explicit administrative elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    expires_in_seconds: int = Field(
        default=300, ge=30, le=3600, description="Upload URL expiration TTL"
    )
    job_id: str = Field(description="Job identifier")
    outcome: TerminalOutcome = Field(description="Terminal execution outcome")
    size_bytes: int = Field(default=0, ge=0, description="Estimated log payload bytes")
    user_id: str = Field(default="default", description="Requesting user identity")


class PresignedUploadToken(BaseModel):
    """Presigned upload token and retention metadata returned to worker.

    Args:
        job_id: Unique job identifier.
        upload_url: Preauthenticated write endpoint (e.g. S3 PUT URL).
        storage_key: Cloud object storage destination key.
        retention_policy: Differential retention policy and tags applied.
        expires_in_seconds: Validity TTL for presigned upload link.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    expires_in_seconds: int = Field(description="Upload URL validity in seconds")
    job_id: str = Field(description="Job identifier")
    retention_policy: LogRetentionPolicy = Field(
        description="Applied differential retention policy"
    )
    storage_key: str = Field(description="Cloud storage object key")
    upload_url: str = Field(description="Direct presigned PUT endpoint")


class NotifyLogUploadCompleteCommand(Command):
    """Command notifying the server that worker finished uploading log payload.

    Args:
        job_id: Unique job identifier.
        storage_key: Cloud object storage key where logs were stored.
        sha256_checksum: Optional SHA-256 digest of uploaded log payload.
        size_bytes: Actual size in bytes of uploaded log payload.
        user_id: Identity of submitting worker or user.
        elevate: Explicit administrative elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    job_id: str = Field(description="Job identifier")
    sha256_checksum: str | None = Field(
        default=None, description="Hexadecimal SHA-256 digest"
    )
    size_bytes: int = Field(default=0, ge=0, description="Payload size in bytes")
    storage_key: str = Field(description="Cloud storage destination key")
    user_id: str = Field(default="default", description="Requesting user identity")


class GetJobLogDownloadUrlQuery(Query):
    """Query to resolve a direct presigned read URL for client log streaming.

    Args:
        job_id: Unique job identifier.
        expires_in_seconds: Download URL expiration TTL in seconds.
        user_id: Identity of requesting user.
        elevate: Explicit administrative elevation flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    expires_in_seconds: int = Field(
        default=900, ge=30, le=86400, description="Download URL expiration TTL"
    )
    job_id: str = Field(description="Job identifier")
    user_id: str = Field(default="default", description="Requesting user identity")


class PresignedDownloadUrl(BaseModel):
    """Preauthenticated download URL descriptor returned to client.

    Args:
        job_id: Unique job identifier.
        download_url: Preauthenticated direct read URL (e.g. S3 GET URL).
        storage_key: Cloud object storage destination key.
        expires_in_seconds: Validity TTL for presigned download link.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    download_url: str = Field(description="Direct presigned GET endpoint")
    expires_in_seconds: int = Field(description="Download URL validity in seconds")
    job_id: str = Field(description="Job identifier")
    storage_key: str = Field(description="Cloud storage object key")


__all__ = [
    "CancelJobCommand",
    "CancelRunCommand",
    "ClusterStatsReport",
    "CreateBastionSessionCommand",
    "CreatePtySessionCommand",
    "DeadLetterQueueReport",
    "EvictExpiredCollateralCommand",
    "ExplainJobQuery",
    "FindCollateralByChecksumQuery",
    "GetClusterHealthQuery",
    "GetCollateralBundleQuery",
    "GetCollateralDownloadUrlQuery",
    "GetDeadLetterQueueQuery",
    "GetFairShareTreeQuery",
    "GetJobLogDownloadUrlQuery",
    "GetJobQuery",
    "GetLogsQuery",
    "GetNodesQuery",
    "GetQueueStatsQuery",
    "GetRunStatusQuery",
    "GetTenantBalanceQuery",
    "HeartbeatNodeCommand",
    "HoldJobCommand",
    "ListComputeNodesQuery",
    "ListJobsQuery",
    "NodesReport",
    "NotifyLogUploadCompleteCommand",
    "PinCollateralCommand",
    "PresignedDownloadUrl",
    "PresignedUploadToken",
    "RegisterCollateralCommand",
    "RegisterNodeCommand",
    "ReleaseBudgetCommand",
    "ReleaseJobCommand",
    "RequestLogUploadUrlCommand",
    "ReserveBudgetCommand",
    "SettleBudgetCommand",
    "SettleSegmentCommand",
    "StreamLogsQuery",
    "SubmitRunCommand",
    "SubmitSuiteCommand",
    "UnpinCollateralCommand",
]
