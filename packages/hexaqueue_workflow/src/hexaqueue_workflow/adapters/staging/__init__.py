"""Staging adapters for hexaqueue_workflow.

Notes/Architectural Intent:
    Exposes concrete artifact staging adapters integrating external storage providers.
"""

from hexaqueue_workflow.adapters.staging.storage import (
    StoragePortArtifactStagingAdapter,
)

__all__ = [
    "StoragePortArtifactStagingAdapter",
]
