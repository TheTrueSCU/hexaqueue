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
    SuiteCompilationError,
    VariableInterpolationError,
)
from hexaqueue_core.domain.exceptions import (
    HexaqueueConfigError as BaseHexaqueueConfigError,
)
from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
    PendingReason,
    PendingReasonCode,
    PriorityBreakdown,
    SchedulerExplainabilityEngine,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.fairshare import (
    FairShareNode,
    FairShareTree,
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
from hexaqueue_core.domain.notification import (
    NotificationPolicy,
    NotificationTrigger,
    map_lifecycle_to_trigger,
)
from hexaqueue_core.domain.priority import (
    JobPriorityCalculator,
    PriorityWeights,
    RankedJob,
)
from hexaqueue_core.domain.redaction import (
    MultiTenantRedactionFilter,
)
from hexaqueue_core.domain.resources import (
    ResourceRequirements,
)
from hexaqueue_core.domain.run import (
    RunSpec,
)
from hexaqueue_core.domain.scheduling import (
    BatchSchedulerEngine,
    ConservativeBackfillScheduler,
    ControlledPreemptionEngine,
    PreemptionPolicy,
    ResourceSlotPool,
    SchedulingDecision,
)
from hexaqueue_core.domain.suite import (
    ContextResolver,
    MatrixExpansionEngine,
    ResolvedContext,
    SuiteCompilationResult,
    SuiteCompiler,
    SuiteContext,
    SuiteSpec,
    TaskSpec,
    TestSpec,
)

__all__ = [
    "BaseHexaqueueConfigError",
    "BatchSchedulerEngine",
    "can_transition_collateral",
    "can_transition_job",
    "ChecksumMismatchError",
    "CollateralBundle",
    "CollateralKind",
    "CollateralState",
    "CollateralTier",
    "compute_run_outcome",
    "compute_run_state",
    "ConservativeBackfillScheduler",
    "ContextResolver",
    "ControlledPreemptionEngine",
    "CspProvider",
    "DependencyCycleError",
    "DependencySpec",
    "ExecutionMode",
    "FairShareNode",
    "FairShareNodeReport",
    "FairShareTree",
    "FairShareTreeReport",
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
    "JobPriorityCalculator",
    "JobSpec",
    "JobState",
    "JobStateTransitionError",
    "JobStatus",
    "JobTemplateSpec",
    "map_lifecycle_to_trigger",
    "MatrixExpansionEngine",
    "MultiTenantRedactionFilter",
    "NotificationPolicy",
    "NotificationTrigger",
    "PendingReason",
    "PendingReasonCode",
    "PreemptionPolicy",
    "PriorityBreakdown",
    "PriorityWeights",
    "QuotaExceededError",
    "RankedJob",
    "ResolvedContext",
    "ResolvedJobCollection",
    "ResourceOverrideSpec",
    "ResourceRequirements",
    "ResourceSlotPool",
    "RunOutcome",
    "RunSpec",
    "RunState",
    "SchedulerExplainabilityEngine",
    "SchedulingDecision",
    "SchedulingDecisionReport",
    "SuiteCompilationError",
    "SuiteCompilationResult",
    "SuiteCompiler",
    "SuiteContext",
    "SuiteSpec",
    "TaskSpec",
    "TerminalOutcome",
    "TestSpec",
    "TriggerCondition",
    "VariableInterpolationError",
]
