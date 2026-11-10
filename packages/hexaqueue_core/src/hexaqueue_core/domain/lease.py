"""Worker slice lease, task descriptor, and heartbeat domain models.

Notes/Architectural Intent:
    Defines protocol models for pull-based distributed test slice execution across
    scale-to-zero compute worker pools. Workers long-poll the coordinator to lease
    slices, pull content-addressable storage (CAS) collateral via time-bounded
    Pre-Authenticated Requests (PARs), execute isolated test runs, and upload
    coverage artifacts directly to object storage.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SliceLeaseState(StrEnum):
    """Lifecycle state of a test slice lease.

    Progression:
        PENDING -> LEASED -> COMPLETED | FAILED | EXPIRED
        EXPIRED -> PENDING (re-enqueued for another worker)
    """

    PENDING = "PENDING"
    LEASED = "LEASED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class WorkerRegistration(BaseModel):
    """Metadata describing a registered compute worker node.

    Args:
        worker_id: Unique identifier of the worker daemon.
        hostname: Optional network hostname.
        ip_address: Optional private IP address inside cluster VCN.
        ocpus: Hardware OCPU or vCPU allocation count.
        memory_mb: Allocatable RAM in megabytes.
        labels: String key-value tags (e.g. pool, shape, provider).
        registered_at: Registration timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hostname: str | None = Field(default=None, description="Worker hostname")
    ip_address: str | None = Field(
        default=None, description="Private IP address on cluster VCN"
    )
    labels: dict[str, str] = Field(
        default_factory=dict, description="Worker capability tags"
    )
    memory_mb: int = Field(default=6144, ge=512, description="Allocatable RAM in MB")
    ocpus: int = Field(default=1, ge=1, description="Allocatable OCPUs or vCPUs")
    registered_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Registration timestamp in UTC",
    )
    worker_id: str = Field(description="Unique worker identifier")

    @model_validator(mode="after")
    def validate_worker_id(self) -> Self:
        """Validate non-empty worker_id."""
        if not self.worker_id.strip():
            msg = "worker_id cannot be blank"
            raise ValueError(msg)
        return self


class SliceTaskDescriptor(BaseModel):
    """Immutable specification of a single test slice or batch task enqueued for worker execution.

    Args:
        session_id: Overall distributed test execution session or run identifier.
        slice_id: Unique slice or job identifier within the session.
        slice_index: Zero-indexed position of this slice.
        total_slices: Total slice count across the test session or run.
        test_nodeids: Optional list of individual pytest nodeids assigned to this slice.
        command: Optional executable command or entrypoint for arbitrary batch task.
        args: Optional command-line arguments for arbitrary batch task.
        env: Optional task-specific environment variables.
        cwd: Optional working directory relative to workspace root.
        task_type: Task classification ('test' for pytest slice, 'job' for arbitrary command).
        collateral_id: Optional CAS collateral bundle ID transporting workspace code.
        collateral_download_url: Optional Pre-Authenticated Request GET URL for workspace tarball.
        coverage_upload_url: Optional Pre-Authenticated Request PUT URL for .coverage artifact.
        coverage_sources: List of source directories or packages to measure coverage against.
        container: Whether this slice requires rootless container isolation.
        container_image: Container image name if container execution is requested.
        created_at: Creation timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    args: list[str] = Field(
        default_factory=list, description="Command arguments for arbitrary batch tasks"
    )
    collateral_download_url: str | None = Field(
        default=None,
        description="Presigned PAR download URL for workspace archive",
    )
    collateral_id: str | None = Field(
        default=None, description="CAS collateral bundle ID"
    )
    command: str | None = Field(
        default=None, description="Executable command for arbitrary batch tasks"
    )
    container: bool = Field(
        default=False, description="Require containerized execution"
    )
    container_image: str | None = Field(
        default=None, description="Container image name"
    )
    coverage_sources: list[str] | None = Field(
        default=None, description="Target packages or source paths for coverage"
    )
    coverage_upload_url: str | None = Field(
        default=None, description="Presigned PAR upload URL for coverage file"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Task enqueued timestamp in UTC",
    )
    cwd: str | None = Field(
        default=None,
        description="Optional working directory relative to workspace root",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables for arbitrary batch tasks",
    )
    session_id: str = Field(description="Parent test session or run identifier")
    slice_id: str = Field(description="Unique test slice or job identifier")
    slice_index: int = Field(default=0, ge=0, description="Slice zero-index")
    task_type: str = Field(
        default="test", description="Task classification ('test' or 'job')"
    )
    test_nodeids: list[str] = Field(
        default_factory=list,
        description="List of pytest nodeids to execute in this slice",
    )
    total_slices: int = Field(
        default=1, ge=1, description="Total slices in session or run"
    )


class SliceLease(BaseModel):
    """Active lease contract binding a slice to a specific worker.

    Args:
        lease_id: Unique lease identifier.
        task: The underlying SliceTaskDescriptor.
        worker_id: Assigned worker node identifier.
        state: Current lease lifecycle state.
        leased_at: Timestamp in UTC when lease was granted.
        expires_at: Expiration deadline in UTC after which lease is revoked.
        last_heartbeat_at: Most recent worker heartbeat timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    expires_at: datetime = Field(description="Lease expiration deadline in UTC")
    last_heartbeat_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Most recent heartbeat in UTC",
    )
    lease_id: str = Field(
        default_factory=lambda: f"lse-{uuid4().hex[:10]}",
        description="Unique lease ID",
    )
    leased_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Lease grant timestamp in UTC",
    )
    state: SliceLeaseState = Field(
        default=SliceLeaseState.LEASED, description="Lease lifecycle state"
    )
    task: SliceTaskDescriptor = Field(description="Enqueued slice task payload")
    worker_id: str = Field(description="Bound worker identifier")

    @property
    def is_expired(self) -> bool:
        """Evaluate whether this lease has passed its expiration deadline."""
        return datetime.now(UTC) > self.expires_at

    def renew(self, extension_seconds: int = 60) -> "SliceLease":
        """Extend lease expiration deadline upon receiving worker heartbeat.

        Args:
            extension_seconds: Number of seconds to extend the lease.

        Returns:
            Updated SliceLease instance with renewed expiration.
        """
        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "expires_at": now + timedelta(seconds=extension_seconds),
                "last_heartbeat_at": now,
            }
        )


class SliceReportPayload(BaseModel):
    """Execution outcome reported by a worker upon slice completion.

    Args:
        lease_id: Bound lease identifier.
        slice_id: Slice identifier.
        worker_id: Reporting worker identifier.
        exit_code: Subprocess exit code (0 for pass, non-zero for failure).
        duration_seconds: Wall-clock execution time in seconds.
        outcomes: Dictionary or list of granular test outcome records.
        coverage_object_key: Object Storage key where .coverage was uploaded via PAR.
        coverage_data: Optional inline coverage dictionary fallback.
        stdout: Truncated standard output on failure.
        stderr: Truncated standard error on failure.
        error_message: Optional high-level crash explanation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    coverage_data: dict[str, Any] | None = Field(
        default=None, description="Inline coverage dictionary"
    )
    coverage_object_key: str | None = Field(
        default=None, description="Object storage key for uploaded coverage artifact"
    )
    duration_seconds: float = Field(
        default=0.0, ge=0.0, description="Slice wall-clock duration in seconds"
    )
    error_message: str | None = Field(
        default=None, description="High-level error explanation if crashed"
    )
    exit_code: int = Field(default=0, description="Process exit code")
    lease_id: str = Field(description="Associated lease identifier")
    outcomes: list[dict[str, Any]] = Field(
        default_factory=list, description="Granular test outcome records"
    )
    slice_id: str = Field(description="Slice identifier")
    stderr: str | None = Field(default=None, description="Captured stderr on failure")
    stdout: str | None = Field(default=None, description="Captured stdout on failure")
    worker_id: str = Field(description="Reporting worker identifier")


class TestOutcomeRecord(BaseModel):
    """Execution outcome of a single test item within a slice.

    Args:
        nodeid: Test item identifier (e.g. tests/test_foo.py::test_bar).
        outcome: Outcome status ('passed', 'failed', 'skipped').
        duration_seconds: Test duration in seconds.
        longrepr: Extended traceback / failure explanation.
        stdout: Captured standard output.
        stderr: Captured standard error.
    """

    __test__ = False
    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_seconds: float = Field(default=0.0, ge=0.0)
    longrepr: str | None = None
    nodeid: str
    outcome: str
    stderr: str | None = None
    stdout: str | None = None


class SliceOutcomeResponse(BaseModel):
    """Aggregate execution report for a completed test slice.

    Args:
        slice_id: Slice identifier.
        slice_index: Zero-indexed position of this slice.
        worker_id: Worker node identifier.
        provider: Provider identifier (e.g. 'LOCAL', 'oci_worker_pool').
        is_free_tier: Whether execution was performed within free tier limits.
        coverage_data: Coverage dictionary or uploaded artifact reference.
        outcomes: List of individual TestOutcomeRecord objects.
        duration_seconds: Total slice execution duration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    coverage_data: dict[str, Any] | None = None
    duration_seconds: float = Field(default=0.0, ge=0.0)
    is_free_tier: bool = True
    outcomes: list[TestOutcomeRecord] = Field(default_factory=list)
    provider: str = "LOCAL"
    slice_id: str
    slice_index: int
    worker_id: str


class TestSliceDispatch(BaseModel):
    """Specification of an execution partition assigned to a cluster worker.

    Args:
        slice_id: Unique slice identifier.
        slice_index: Zero-indexed position of this slice.
        total_slices: Total slice count across the test session.
        test_nodeids: List of individual pytest nodeids assigned to this slice.
        total_estimated_duration: Estimated execution duration in seconds.
    """

    __test__ = False
    model_config = ConfigDict(extra="ignore")

    slice_id: str
    slice_index: int
    total_slices: int
    test_nodeids: list[str] = Field(default_factory=list)
    total_estimated_duration: float = 0.0


__all__ = [
    "SliceLease",
    "SliceLeaseState",
    "SliceOutcomeResponse",
    "SliceReportPayload",
    "SliceTaskDescriptor",
    "TestOutcomeRecord",
    "TestSliceDispatch",
    "WorkerRegistration",
]
