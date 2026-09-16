"""Port interfaces for hexaqueue_workflow.

Notes/Architectural Intent:
    Declares abstract port interfaces defining inbound and outbound boundaries
    for distributed step execution and artifact staging.
"""

from hexaqueue_workflow.ports.staging import ArtifactStagingPort

__all__ = [
    "ArtifactStagingPort",
]
