"""Domain layer models and exceptions for hexaqueue_workflow.

Notes/Architectural Intent:
    Encapsulates core abstractions for mapping workflows into cluster jobs,
    handling out-of-band artifact metadata, and domain-level error conditions.
"""

from hexaqueue_workflow.domain.barrier import (
    BarrierPartition,
    BarrierResolutionSummary,
    BarrierState,
)
from hexaqueue_workflow.domain.exceptions import (
    ArtifactStagingError,
    HexaqueueWorkflowError,
    JobExecutionFailedError,
    StepMappingNotFoundError,
)
from hexaqueue_workflow.domain.models import (
    ArtifactReference,
    DistributedWorkflowConfig,
    WorkflowStepJobMapping,
)

__all__ = [
    "ArtifactReference",
    "ArtifactStagingError",
    "BarrierPartition",
    "BarrierResolutionSummary",
    "BarrierState",
    "DistributedWorkflowConfig",
    "HexaqueueWorkflowError",
    "JobExecutionFailedError",
    "StepMappingNotFoundError",
    "WorkflowStepJobMapping",
]
