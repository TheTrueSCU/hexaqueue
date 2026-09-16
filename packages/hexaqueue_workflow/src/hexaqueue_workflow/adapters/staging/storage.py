"""StoragePort-backed implementation of ArtifactStagingPort.

Notes/Architectural Intent:
    Connects hexastack_core.ports.storage.StoragePort to stage large or distributed
    intermediate step payloads (>64KB by default) to shared or remote storage
    (S3, GCS, POSIX scratch, or in-memory) and retrieve them transparently for
    downstream consumers.
"""

import hashlib
import json
import pickle
from typing import Any

from hexastack_core.ports.storage import StoragePort

from hexaqueue_workflow.domain.exceptions import ArtifactStagingError
from hexaqueue_workflow.domain.models import (
    ArtifactReference,
    DistributedWorkflowConfig,
)
from hexaqueue_workflow.ports.staging import ArtifactStagingPort


class StoragePortArtifactStagingAdapter(ArtifactStagingPort):
    """Artifact staging adapter integrating Hexastack StoragePort.

    Notes/Architectural Intent:
        Serializes payloads using JSON when possible and pickle as fallback, evaluates
        payload byte size against the configured threshold, and offloads qualifying
        artifacts to the configured StoragePort implementation.

    Args:
        storage: Concrete StoragePort implementation (e.g. LocalStorageAdapter, S3, Memory).
        config: Optional DistributedWorkflowConfig defining staging threshold and paths.
    """

    def __init__(
        self,
        storage: StoragePort,
        config: DistributedWorkflowConfig | None = None,
    ) -> None:
        """Initialize StoragePortArtifactStagingAdapter.

        Args:
            storage: Concrete StoragePort instance.
            config: Optional configuration overrides.
        """
        self._storage = storage
        self._config = config or DistributedWorkflowConfig()

    def should_stage(self, payload: Any) -> bool:
        """Determine whether a payload exceeds the configured byte threshold.

        Args:
            payload: Step output payload to evaluate.

        Returns:
            True if serialized payload size exceeds threshold, False otherwise.
        """
        if payload is None:
            return False
        try:
            raw_bytes, _ = self._serialize_payload(payload)
            return len(raw_bytes) >= self._config.artifact_threshold_bytes
        except Exception:
            return False

    def stage_artifact(
        self, run_id: str, step_name: str, payload: Any
    ) -> ArtifactReference | Any:
        """Stage an intermediate step output payload if it exceeds the staging threshold.

        Args:
            run_id: Parent workflow execution run identifier.
            step_name: Step producing the output payload.
            payload: Raw output value.

        Returns:
            ArtifactReference pointing to storage URI if staged, or original payload unchanged.

        Raises:
            ArtifactStagingError: If serialization or storage operations fail.
        """
        if payload is None:
            return None

        # Check if already staged
        if isinstance(payload, ArtifactReference):
            return payload
        if ArtifactReference.is_artifact_envelope(payload):
            return payload

        try:
            raw_bytes, mime_type = self._serialize_payload(payload)
        except Exception as e:
            msg = f"Failed to serialize payload for step '{step_name}': {e}"
            raise ArtifactStagingError(msg) from e

        if len(raw_bytes) < self._config.artifact_threshold_bytes:
            return payload

        storage_key = f"{self._config.storage_prefix}/{run_id}/{step_name}.payload"
        content_hash = hashlib.sha256(raw_bytes).hexdigest()

        try:
            canonical_uri = self._storage.put(storage_key, raw_bytes)
        except Exception as e:
            msg = f"Failed to persist artifact to storage at '{storage_key}': {e}"
            raise ArtifactStagingError(msg) from e

        return ArtifactReference(
            storage_uri=canonical_uri or storage_key,
            size_bytes=len(raw_bytes),
            content_hash=content_hash,
            mime_type=mime_type,
        )

    def retrieve_artifact(self, payload: Any) -> Any:
        """Resolve a staged artifact reference back into its deserialized payload.

        Args:
            payload: ArtifactReference, envelope dictionary, or inline payload.

        Returns:
            Deserialized payload if staged, or original value if already inline.

        Raises:
            ArtifactStagingError: If retrieving or deserializing the artifact fails.
        """
        if payload is None:
            return None

        ref: ArtifactReference | None = None
        if isinstance(payload, ArtifactReference):
            ref = payload
        elif ArtifactReference.is_artifact_envelope(payload):
            ref = ArtifactReference.from_envelope(payload)

        if ref is None:
            return payload

        try:
            raw_bytes = self._storage.get(ref.storage_uri)
        except Exception as e:
            msg = (
                f"Failed to retrieve artifact from storage URI '{ref.storage_uri}': {e}"
            )
            raise ArtifactStagingError(msg) from e

        if ref.content_hash:
            actual_hash = hashlib.sha256(raw_bytes).hexdigest()
            if actual_hash != ref.content_hash:
                msg = (
                    f"Integrity check failed for '{ref.storage_uri}': "
                    f"expected {ref.content_hash}, got {actual_hash}"
                )
                raise ArtifactStagingError(msg)

        try:
            return self._deserialize_payload(raw_bytes, ref.mime_type)
        except Exception as e:
            msg = (
                f"Failed to deserialize artifact payload from '{ref.storage_uri}': {e}"
            )
            raise ArtifactStagingError(msg) from e

    def _serialize_payload(self, payload: Any) -> tuple[bytes, str]:
        """Serialize payload into bytes and identify its MIME type descriptor."""
        try:
            json_str = json.dumps(payload, allow_nan=False)
            return json_str.encode("utf-8"), "application/json"
        except (TypeError, ValueError):
            return pickle.dumps(payload, protocol=5), "application/x-python-pickle"

    def _deserialize_payload(self, data: bytes, mime_type: str) -> Any:
        """Deserialize bytes based on the MIME type descriptor."""
        if mime_type == "application/json":
            return json.loads(data.decode("utf-8"))
        if mime_type == "application/x-python-pickle":
            return pickle.loads(data)  # noqa: S301
        try:
            return json.loads(data.decode("utf-8"))
        except Exception:
            return pickle.loads(data)  # noqa: S301


__all__ = [
    "StoragePortArtifactStagingAdapter",
]
