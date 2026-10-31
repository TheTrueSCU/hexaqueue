"""Domain models and business logic for GitHub Actions runner autoscaling.

Notes/Architectural Intent:
    Pure business models, event contracts, JIT configurations, and label
    parsing rules with zero external framework dependencies.
"""

from hexaqueue_github_runner.domain.events import (
    GitHubRepository,
    GitHubWorkflowJob,
    GitHubWorkflowJobAction,
    GitHubWorkflowJobPayload,
)
from hexaqueue_github_runner.domain.jit import (
    GitHubAppCredentials,
    JitRunnerConfig,
)
from hexaqueue_github_runner.domain.labels import LabelTranslator
from hexaqueue_github_runner.domain.pool import (
    RunnerPoolState,
    WarmPoolConfig,
    WarmPoolRunner,
)
from hexaqueue_github_runner.domain.traceability import JobSummaryAnnotation

__all__ = [
    "GitHubAppCredentials",
    "GitHubRepository",
    "GitHubWorkflowJob",
    "GitHubWorkflowJobAction",
    "GitHubWorkflowJobPayload",
    "JitRunnerConfig",
    "JobSummaryAnnotation",
    "LabelTranslator",
    "RunnerPoolState",
    "WarmPoolConfig",
    "WarmPoolRunner",
]
