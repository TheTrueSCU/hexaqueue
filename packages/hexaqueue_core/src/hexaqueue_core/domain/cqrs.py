"""Unified CQRS command and query contracts.

Notes/Architectural Intent:
    Serves as the Single Source of Truth for all state transitions and queries
    across Hexaqueue interfaces (CLI, REST OpenAPI, gRPC Protobufs, and Web Dashboard).
    Every capability in Hexaqueue is modeled as an immutable Command or Query
    adhering to Hexagonal boundaries and the Principle of Least Privilege:
    callers execute under their natural identity, requiring explicit elevation
    (`elevate=True`) when mutating or inspecting cross-tenant resources.
"""

from hexastack_core.domain import Command, Query
from pydantic import ConfigDict, Field

from hexaqueue_core.domain.collateral import CollateralKind, CollateralTier
from hexaqueue_core.domain.job import JobSpec
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
    user_id: str = Field(default="default", description="Submitting user identity")
    version: str = Field(default="latest", description="Version string")


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
    job_id: str = Field(description="Target running job identifier")
    rows: int = Field(default=24, ge=1, le=1000, description="Terminal rows")
    session_id: str = Field(description="Unique interactive session identifier")
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

    amount_cents: int = Field(ge=0, description="Settled consumption amount")
    elevate: bool = Field(
        default=False, description="Explicit administrative elevation flag"
    )
    project_id: str = Field(description="Project identifier")
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


__all__ = [
    "CancelJobCommand",
    "CancelRunCommand",
    "CreateBastionSessionCommand",
    "CreatePtySessionCommand",
    "ExplainJobQuery",
    "GetFairShareTreeQuery",
    "GetJobQuery",
    "GetLogsQuery",
    "GetNodesQuery",
    "GetQueueStatsQuery",
    "GetRunStatusQuery",
    "HoldJobCommand",
    "ListJobsQuery",
    "RegisterCollateralCommand",
    "ReleaseJobCommand",
    "SettleBudgetCommand",
    "StreamLogsQuery",
    "SubmitRunCommand",
    "SubmitSuiteCommand",
]
