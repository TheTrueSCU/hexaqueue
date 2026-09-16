"""Port interfaces for distributed workflow artifact staging.

Notes/Architectural Intent:
    Defines abstract contracts for intercepting large (>64KB) or multi-node step
    outputs, offloading them to remote/shared storage, and transparently resolving
    them back into memory for downstream consumer steps.
"""

from abc import ABC, abstractmethod
from typing import Any

from hexaqueue_workflow.domain.models import ArtifactReference


class ArtifactStagingPort(ABC):
    """Abstract contract for staging and retrieving distributed step payloads.

    Notes/Architectural Intent:
        Enables seamless switching between storage backends (S3, GCS, POSIX, in-memory)
        while maintaining consistent serialization and threshold enforcement rules.
    """

    @abstractmethod
    def stage_artifact(
        self, run_id: str, step_name: str, payload: Any
    ) -> ArtifactReference | Any:
        """Stage an intermediate step output payload if it exceeds the staging threshold.

        Args:
            run_id: Parent workflow execution run identifier.
            step_name: Executing step identifier producing this payload.
            payload: Raw output value returned by the step.

        Returns:
            ArtifactReference if staged, or original payload unchanged if below threshold.

        Raises:
            ArtifactStagingError: If serialization or persistence fails.
        """

    @abstractmethod
    def retrieve_artifact(self, payload: Any) -> Any:
        """Resolve a potentially staged artifact reference back into its original payload.

        Args:
            payload: ArtifactReference, envelope dictionary, or regular inline payload.

        Returns:
            Deserialized payload if staged, or original value if already inline.

        Raises:
            ArtifactStagingError: If artifact retrieval or deserialization fails.
        """

    @abstractmethod
    def should_stage(self, payload: Any) -> bool:
        """Determine whether a payload exceeds the size threshold for external staging.

        Args:
            payload: Candidate payload value to inspect.

        Returns:
            True if the payload requires staging, False otherwise.
        """


__all__ = [
    "ArtifactStagingPort",
]
