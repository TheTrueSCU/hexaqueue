"""Tests for domain models."""

from datetime import UTC, datetime

import pytest

from hexaqueue_workflow.domain.models import (
    ArtifactReference,
    DistributedWorkflowConfig,
    WorkflowStepJobMapping,
)


def test_artifact_reference_creation_and_envelope() -> None:
    """Verify ArtifactReference creation, envelope conversion, and restoration."""
    now = datetime.now(UTC)
    ref = ArtifactReference(
        storage_uri="artifacts/run-1/step-a.bin",
        size_bytes=102400,
        content_hash="abc123sha",
        mime_type="application/json",
        staged_at=now,
    )
    assert ref.storage_uri == "artifacts/run-1/step-a.bin"
    assert ref.size_bytes == 102400
    assert ref.content_hash == "abc123sha"

    envelope = ref.to_envelope()
    is_env = ArtifactReference.is_artifact_envelope(envelope)
    assert is_env is True

    restored = ArtifactReference.from_envelope(envelope)
    assert restored.storage_uri == ref.storage_uri
    assert restored.size_bytes == ref.size_bytes
    assert restored.content_hash == ref.content_hash
    assert restored.mime_type == ref.mime_type


def test_artifact_reference_validation() -> None:
    """Verify validation checks on ArtifactReference."""
    with pytest.raises(ValueError, match="storage_uri cannot be empty"):
        ArtifactReference(storage_uri="   ", size_bytes=10)

    with pytest.raises(ValueError, match="not represent a valid artifact reference"):
        ArtifactReference.from_envelope({"random": "data"})

    is_env = ArtifactReference.is_artifact_envelope("not a dict")
    assert is_env is False


def test_workflow_step_job_mapping() -> None:
    """Verify WorkflowStepJobMapping defaults and invariants."""
    mapping = WorkflowStepJobMapping(
        step_name="compile",
        cpu_cores=4.0,
        memory_mb=2048,
        gpu_count=1,
        tags=["gpu-node"],
        command="compile --fast",
        args=["--debug"],
        env={"OPT": "1"},
    )
    assert mapping.step_name == "compile"
    assert mapping.cpu_cores == 4.0
    assert mapping.memory_mb == 2048
    assert mapping.gpu_count == 1
    assert mapping.tags == ["gpu-node"]
    assert mapping.command == "compile --fast"

    with pytest.raises(ValueError, match="step_name cannot be empty"):
        WorkflowStepJobMapping(step_name="  ")


def test_distributed_workflow_config_defaults() -> None:
    """Verify DistributedWorkflowConfig default configuration values."""
    config = DistributedWorkflowConfig()
    assert config.artifact_threshold_bytes == 65536
    assert config.default_cpu_cores == 1.0
    assert config.default_memory_mb == 512
    assert config.default_gpu_count == 0
    assert config.poll_interval_seconds == 0.05
    assert config.timeout_seconds == 300.0
    assert config.storage_prefix == "artifacts"
    assert len(config.step_mappings) == 0
    assert len(config.default_notifications) == 0


def test_workflow_models_notification_policies() -> None:
    """Verify notification policies configured on mappings and configs."""
    from hexaqueue_core.domain.notification import (
        NotificationPolicy,
        NotificationTrigger,
    )

    policy = NotificationPolicy(
        targets=["slack://channel"],
        triggers=NotificationTrigger.ERRORS,
    )
    mapping = WorkflowStepJobMapping(
        step_name="step-notify",
        notifications=[policy],
    )
    assert len(mapping.notifications) == 1
    assert mapping.notifications[0].targets == ["slack://channel"]

    config = DistributedWorkflowConfig(
        default_notifications=[policy],
    )
    assert len(config.default_notifications) == 1
    assert config.default_notifications[0].triggers == NotificationTrigger.ERRORS
