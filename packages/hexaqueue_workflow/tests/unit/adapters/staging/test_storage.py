from typing import Any

import pytest
from hexastack_core.adapters.storage.in_memory import InMemoryStorage

from hexaqueue_workflow.adapters.staging.storage import (
    StoragePortArtifactStagingAdapter,
)
from hexaqueue_workflow.domain.exceptions import ArtifactStagingError
from hexaqueue_workflow.domain.models import (
    ArtifactReference,
    DistributedWorkflowConfig,
)


def test_staging_below_threshold() -> None:
    """Verify payloads below threshold are not staged and returned inline."""
    storage = InMemoryStorage()
    config = DistributedWorkflowConfig(artifact_threshold_bytes=1000)
    adapter = StoragePortArtifactStagingAdapter(storage=storage, config=config)

    small_payload = {"key": "value"}
    should = adapter.should_stage(small_payload)
    assert should is False

    res = adapter.stage_artifact("run-1", "step-1", small_payload)
    assert res == small_payload

    retrieved = adapter.retrieve_artifact(res)
    assert retrieved == small_payload


def test_staging_above_threshold_json() -> None:
    """Verify large JSON payloads are staged to storage and restored."""
    storage = InMemoryStorage()
    config = DistributedWorkflowConfig(artifact_threshold_bytes=50)
    adapter = StoragePortArtifactStagingAdapter(storage=storage, config=config)

    large_payload = {"numbers": list(range(100))}
    should = adapter.should_stage(large_payload)
    assert should is True

    res = adapter.stage_artifact("run-1", "step-large", large_payload)
    assert isinstance(res, ArtifactReference)
    assert res.size_bytes >= 50
    assert res.mime_type == "application/json"
    assert "artifacts/run-1/step-large.payload" in res.storage_uri

    # Test idempotency if already staged
    res_again = adapter.stage_artifact("run-1", "step-large", res)
    assert res_again == res

    # Retrieve from reference
    retrieved = adapter.retrieve_artifact(res)
    assert retrieved == large_payload

    # Retrieve from envelope dictionary
    envelope = res.to_envelope()
    retrieved_from_env = adapter.retrieve_artifact(envelope)
    assert retrieved_from_env == large_payload


def test_staging_complex_python_object_pickle() -> None:
    """Verify non-JSON serializable objects fall back to pickle serialization."""
    storage = InMemoryStorage()
    config = DistributedWorkflowConfig(artifact_threshold_bytes=10)
    adapter = StoragePortArtifactStagingAdapter(storage=storage, config=config)

    # set is not JSON serializable
    complex_payload = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
    res = adapter.stage_artifact("run-2", "step-pickle", complex_payload)
    assert isinstance(res, ArtifactReference)
    assert res.mime_type == "application/x-python-pickle"

    retrieved = adapter.retrieve_artifact(res)
    assert retrieved == complex_payload


def test_staging_none_and_primitives() -> None:
    """Verify handling of None and primitives."""
    storage = InMemoryStorage()
    adapter = StoragePortArtifactStagingAdapter(storage=storage)

    res_none = adapter.stage_artifact("run-1", "step-none", None)
    assert res_none is None

    ret_none = adapter.retrieve_artifact(None)
    assert ret_none is None

    should_none = adapter.should_stage(None)
    assert should_none is False


def test_integrity_check_failure() -> None:
    """Verify ArtifactStagingError is raised if content hash mismatches."""
    storage = InMemoryStorage()
    config = DistributedWorkflowConfig(artifact_threshold_bytes=10)
    adapter = StoragePortArtifactStagingAdapter(storage=storage, config=config)

    payload = {"data": "secure-data"}
    res = adapter.stage_artifact("run-3", "step-tamper", payload)
    assert isinstance(res, ArtifactReference)

    tampered_ref = ArtifactReference(
        storage_uri=res.storage_uri,
        size_bytes=res.size_bytes,
        content_hash="corrupted-hash-1234",
        mime_type=res.mime_type,
    )

    with pytest.raises(ArtifactStagingError, match="Integrity check failed"):
        adapter.retrieve_artifact(tampered_ref)


def test_storage_get_failure() -> None:
    """Verify ArtifactStagingError when storage retrieval fails."""
    storage = InMemoryStorage()
    adapter = StoragePortArtifactStagingAdapter(storage=storage)

    missing_ref = ArtifactReference(
        storage_uri="artifacts/non-existent.bin",
        size_bytes=100,
    )
    with pytest.raises(ArtifactStagingError, match="Failed to retrieve artifact"):
        adapter.retrieve_artifact(missing_ref)


def test_stage_artifact_already_envelope() -> None:
    """Verify passing an envelope dictionary returns it immediately."""
    storage = InMemoryStorage()
    adapter = StoragePortArtifactStagingAdapter(storage=storage)
    envelope = {"$artifact_ref": True, "storage_uri": "some/path", "size_bytes": 100}
    res = adapter.stage_artifact("run-1", "step-1", envelope)
    assert res == envelope


def test_stage_artifact_serialization_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ArtifactStagingError is raised when serialization fails."""
    storage = InMemoryStorage()
    config = DistributedWorkflowConfig(artifact_threshold_bytes=10)
    adapter = StoragePortArtifactStagingAdapter(storage=storage, config=config)

    def failing_serializer(payload: Any) -> tuple[bytes, str]:
        raise ValueError("Cannot serialize object")

    monkeypatch.setattr(adapter, "_serialize_payload", failing_serializer)

    with pytest.raises(ArtifactStagingError, match="Failed to serialize payload"):
        adapter.stage_artifact("run-1", "step-fail", {"data": "test"})

    should = adapter.should_stage({"data": "test"})
    assert should is False


def test_stage_artifact_storage_put_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ArtifactStagingError is raised when storage.put fails."""
    storage = InMemoryStorage()
    config = DistributedWorkflowConfig(artifact_threshold_bytes=10)
    adapter = StoragePortArtifactStagingAdapter(storage=storage, config=config)

    def failing_put(path: str, data: Any) -> str:
        raise OSError("Disk full or permission denied")

    monkeypatch.setattr(storage, "put", failing_put)

    with pytest.raises(ArtifactStagingError, match="Failed to persist artifact"):
        adapter.stage_artifact("run-1", "step-put-fail", {"data": "lots of data here"})


def test_retrieve_artifact_deserialization_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify ArtifactStagingError when deserializing raw bytes fails."""
    storage = InMemoryStorage()
    config = DistributedWorkflowConfig(artifact_threshold_bytes=10)
    adapter = StoragePortArtifactStagingAdapter(storage=storage, config=config)

    res = adapter.stage_artifact("run-1", "step-deser", {"hello": "world"})
    assert isinstance(res, ArtifactReference)

    def failing_deserializer(data: bytes, mime_type: str) -> Any:
        raise ValueError("Invalid format")

    monkeypatch.setattr(adapter, "_deserialize_payload", failing_deserializer)

    with pytest.raises(
        ArtifactStagingError, match="Failed to deserialize artifact payload"
    ):
        adapter.retrieve_artifact(res)


def test_deserialize_payload_fallbacks() -> None:
    """Verify fallback paths in _deserialize_payload."""
    storage = InMemoryStorage()
    adapter = StoragePortArtifactStagingAdapter(storage=storage)

    # Unknown MIME type with JSON-compatible payload
    json_bytes = b'{"fallback": true}'
    decoded = adapter._deserialize_payload(json_bytes, "application/unknown")
    assert decoded == {"fallback": True}
