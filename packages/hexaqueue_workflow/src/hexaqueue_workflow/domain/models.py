"""Domain models for distributed workflow execution and artifact staging.

Notes/Architectural Intent:
    Defines pure entities for mapping workflow DAG steps onto cluster jobs,
    tracking staged intermediate artifact references, and configuring
    distributed execution thresholds.
"""

from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.notification import NotificationPolicy


class ArtifactReference(BaseModel):
    """Metadata pointer for an intermediate step artifact stored in off-node storage.

    Notes/Architectural Intent:
        Enables passing large (>64KB) or multi-node step payloads across compute
        boundaries via StoragePort (e.g. S3, GCS, POSIX scratch) while keeping
        checkpoint records lightweight and serializable.

    Args:
        storage_uri: Canonical URI or path pointing to the staged payload.
        size_bytes: Size of the stored artifact in bytes.
        content_hash: Optional SHA256 hexadecimal digest for integrity validation.
        mime_type: Format or content serialization descriptor.
        staged_at: UTC timestamp when the artifact was persisted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    storage_uri: str = Field(description="Canonical storage URI or relative path")
    size_bytes: int = Field(ge=0, description="Size of staged payload in bytes")
    content_hash: str | None = Field(
        default=None, description="SHA256 checksum digest of payload"
    )
    mime_type: str = Field(
        default="application/octet-stream", description="Payload MIME type"
    )
    staged_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when payload was staged",
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate artifact reference invariants.

        Returns:
            Validated instance.

        Raises:
            ValueError: If storage_uri is empty.
        """
        if not self.storage_uri.strip():
            msg = "storage_uri cannot be empty"
            raise ValueError(msg)
        return self

    def to_envelope(self) -> dict[str, Any]:
        """Convert artifact reference into a serializable envelope dictionary.

        Returns:
            Dictionary containing standard artifact envelope keys.
        """
        return {
            "$artifact_ref": True,
            "storage_uri": self.storage_uri,
            "size_bytes": self.size_bytes,
            "content_hash": self.content_hash,
            "mime_type": self.mime_type,
            "staged_at": self.staged_at.isoformat(),
        }

    @classmethod
    def from_envelope(cls, data: dict[str, Any]) -> "ArtifactReference":
        """Reconstruct ArtifactReference from an envelope dictionary.

        Args:
            data: Dictionary containing artifact envelope fields.

        Returns:
            Reconstituted ArtifactReference instance.

        Raises:
            ValueError: If data is missing required artifact reference fields.
        """
        if not data.get("$artifact_ref"):
            msg = "Dictionary does not represent a valid artifact reference envelope"
            raise ValueError(msg)

        staged_at_val = data.get("staged_at")
        staged_at = (
            datetime.fromisoformat(staged_at_val)
            if isinstance(staged_at_val, str)
            else datetime.now(UTC)
        )

        return cls(
            storage_uri=data["storage_uri"],
            size_bytes=data["size_bytes"],
            content_hash=data.get("content_hash"),
            mime_type=data.get("mime_type", "application/octet-stream"),
            staged_at=staged_at,
        )

    @staticmethod
    def is_artifact_envelope(data: Any) -> bool:
        """Check whether an arbitrary object is an artifact reference envelope.

        Args:
            data: Any payload object or checkpoint value.

        Returns:
            True if data is a dictionary matching the artifact envelope structure.
        """
        return isinstance(data, dict) and data.get("$artifact_ref") is True


class WorkflowStepJobMapping(BaseModel):
    """Resource and compute mapping specification for an individual workflow step.

    Notes/Architectural Intent:
        Supplies scheduler controllers with compute constraints (CPU, RAM, GPU,
        affinity tags) when converting high-level workflow steps into JobSpecs.

    Args:
        step_name: Target step identifier within the workflow definition.
        cpu_cores: Allocated CPU core count (minimum 0.1).
        memory_mb: Allocated RAM capacity in megabytes (minimum 16).
        gpu_count: Allocated GPU count (default 0).
        tags: Node placement and affinity tags.
        command: Optional executable command override.
        args: Command arguments.
        env: Job-specific environment variable overrides.
        notifications: Explicit notification policies for this workflow step.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_name: str = Field(description="Step identifier matching WorkflowDefinition")
    cpu_cores: float = Field(default=1.0, ge=0.1, description="Allocated CPU cores")
    memory_mb: int = Field(default=512, ge=16, description="Allocated RAM in MB")
    gpu_count: int = Field(default=0, ge=0, description="Allocated GPUs")
    tags: list[str] = Field(
        default_factory=list, description="Worker placement affinity tags"
    )
    command: str | None = Field(
        default=None, description="Optional command executable override"
    )
    args: list[str] = Field(default_factory=list, description="Command arguments")
    env: dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    notifications: list[NotificationPolicy] = Field(
        default_factory=list, description="Notification policies for this step job"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate step job mapping invariants.

        Returns:
            Validated instance.

        Raises:
            ValueError: If step_name is empty.
        """
        if not self.step_name.strip():
            msg = "step_name cannot be empty"
            raise ValueError(msg)
        return self


class DistributedWorkflowConfig(BaseModel):
    """Configuration parameters for distributed workflow execution and artifact handling.

    Notes/Architectural Intent:
        Controls staging thresholds, polling intervals, and fallback resource
        allocations across distributed runs.

    Args:
        artifact_threshold_bytes: Payload size threshold above which outputs are staged to StoragePort.
        default_cpu_cores: Default CPU core allocation for steps without custom mappings.
        default_memory_mb: Default RAM allocation for steps without custom mappings.
        default_gpu_count: Default GPU allocation for steps without custom mappings.
        poll_interval_seconds: Job completion polling loop interval.
        timeout_seconds: Maximum execution time allowed before timing out a job run.
        storage_prefix: Base prefix or directory for artifact keys.
        step_mappings: Optional pre-configured step name to WorkflowStepJobMapping dictionary.
        default_notifications: Default notification policies applied to steps without custom mappings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_threshold_bytes: int = Field(
        default=65536, ge=1, description="Threshold in bytes for external staging"
    )
    default_cpu_cores: float = Field(
        default=1.0, ge=0.1, description="Default CPU core allocation"
    )
    default_memory_mb: int = Field(
        default=512, ge=16, description="Default RAM in megabytes"
    )
    default_gpu_count: int = Field(
        default=0, ge=0, description="Default GPU allocation"
    )
    poll_interval_seconds: float = Field(
        default=0.05, ge=0.001, description="Job status poll frequency in seconds"
    )
    timeout_seconds: float = Field(
        default=300.0, ge=1.0, description="Job completion timeout in seconds"
    )
    storage_prefix: str = Field(
        default="artifacts", description="Root storage path prefix"
    )
    step_mappings: dict[str, WorkflowStepJobMapping] = Field(
        default_factory=dict, description="Per-step compute resource configurations"
    )
    default_notifications: list[NotificationPolicy] = Field(
        default_factory=list,
        description="Default notification policies for workflow steps",
    )


__all__ = [
    "ArtifactReference",
    "DistributedWorkflowConfig",
    "WorkflowStepJobMapping",
]
