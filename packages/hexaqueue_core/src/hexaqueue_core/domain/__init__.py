"""Domain entities and value objects for Hexaqueue Core."""

from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
    can_transition_collateral,
)
from hexaqueue_core.domain.config import (
    CspProvider,
    ExecutionMode,
    FreeTierProfileConfig,
    HexaqueueConfig,
    HexaqueueConfigError,
    HexaqueueCoreConfig,
)
from hexaqueue_core.domain.dag import (
    DependencyCycleError,
    DependencySpec,
    JobDagEngine,
    TriggerCondition,
    is_dependency_blocked,
    is_dependency_satisfied,
)
from hexaqueue_core.domain.exceptions import (
    ChecksumMismatchError,
    FreeTierLimitExceededError,
    HexaqueueError,
    JobStateTransitionError,
    QuotaExceededError,
)
from hexaqueue_core.domain.exceptions import (
    HexaqueueConfigError as BaseHexaqueueConfigError,
)
from hexaqueue_core.domain.group import (
    GroupExpansionEngine,
    JobGroupSpec,
    JobTemplateSpec,
    ResolvedJobCollection,
    ResourceOverrideSpec,
)
from hexaqueue_core.domain.job import (
    JobSpec,
)
from hexaqueue_core.domain.lifecycle import (
    JobState,
    JobStatus,
    RunOutcome,
    RunState,
    TerminalOutcome,
    can_transition_job,
    compute_run_outcome,
    compute_run_state,
)
from hexaqueue_core.domain.resources import (
    ResourceRequirements,
)
from hexaqueue_core.domain.run import (
    RunSpec,
)

__all__ = [
    "BaseHexaqueueConfigError",
    "can_transition_collateral",
    "can_transition_job",
    "ChecksumMismatchError",
    "CollateralBundle",
    "CollateralKind",
    "CollateralState",
    "CollateralTier",
    "compute_run_outcome",
    "compute_run_state",
    "CspProvider",
    "DependencyCycleError",
    "DependencySpec",
    "ExecutionMode",
    "FreeTierLimitExceededError",
    "FreeTierProfileConfig",
    "GroupExpansionEngine",
    "HexaqueueConfig",
    "HexaqueueConfigError",
    "HexaqueueCoreConfig",
    "HexaqueueError",
    "is_dependency_blocked",
    "is_dependency_satisfied",
    "JobDagEngine",
    "JobGroupSpec",
    "JobSpec",
    "JobState",
    "JobStateTransitionError",
    "JobStatus",
    "JobTemplateSpec",
    "QuotaExceededError",
    "ResolvedJobCollection",
    "ResourceOverrideSpec",
    "ResourceRequirements",
    "RunOutcome",
    "RunSpec",
    "RunState",
    "TerminalOutcome",
    "TriggerCondition",
]
