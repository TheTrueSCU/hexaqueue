"""Hexaqueue GitHub Runner - Dynamic Self-Hosted GitHub Actions Autoscaler.

Notes/Architectural Intent:
    Root package export for GitHub Actions runner autoscaler, JIT manager,
    cryptographic webhook verifier, and hardware resource translation.
"""

from hexaqueue_github_runner.adapters.autoscaler import (
    DynamicGitHubRunnerAutoscaler,
    NaiveAutoscalerOracle,
)
from hexaqueue_github_runner.adapters.crypto import HmacSha256WebhookVerifier
from hexaqueue_github_runner.adapters.github_client import (
    GitHubApiClient,
    InMemoryGitHubApiClient,
    create_github_app_jwt,
)
from hexaqueue_github_runner.adapters.webhook_adapter import (
    GitHubWebhookAdapter,
)
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
from hexaqueue_github_runner.infra.router import (
    WebhookActionResponse,
    create_github_webhook_router,
)
from hexaqueue_github_runner.ports.autoscaler import (
    GitHubRunnerAutoscalerPort,
)
from hexaqueue_github_runner.ports.client import GitHubApiClientPort
from hexaqueue_github_runner.ports.verifier import WebhookVerifierPort

__all__ = [
    "create_github_app_jwt",
    "create_github_webhook_router",
    "DynamicGitHubRunnerAutoscaler",
    "GitHubApiClient",
    "GitHubApiClientPort",
    "GitHubAppCredentials",
    "GitHubRepository",
    "GitHubRunnerAutoscalerPort",
    "GitHubWebhookAdapter",
    "GitHubWorkflowJob",
    "GitHubWorkflowJobAction",
    "GitHubWorkflowJobPayload",
    "HmacSha256WebhookVerifier",
    "InMemoryGitHubApiClient",
    "JitRunnerConfig",
    "JobSummaryAnnotation",
    "LabelTranslator",
    "NaiveAutoscalerOracle",
    "RunnerPoolState",
    "WarmPoolConfig",
    "WarmPoolRunner",
    "WebhookActionResponse",
    "WebhookVerifierPort",
]
