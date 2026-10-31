"""Adapters for GitHub Actions runner autoscaler.

Notes/Architectural Intent:
    Concrete implementations of GitHub API client, cryptographic HMAC
    verification, autoscaling coordinator, and HTTP webhook ingestion.
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

__all__ = [
    "create_github_app_jwt",
    "DynamicGitHubRunnerAutoscaler",
    "GitHubApiClient",
    "GitHubWebhookAdapter",
    "HmacSha256WebhookVerifier",
    "InMemoryGitHubApiClient",
    "NaiveAutoscalerOracle",
]
