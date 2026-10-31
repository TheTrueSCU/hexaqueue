"""Infrastructure integrations for GitHub Actions runner autoscaler.

Notes/Architectural Intent:
    Framework-level router builders and application integration utilities.
"""

from hexaqueue_github_runner.infra.router import (
    WebhookActionResponse,
    create_github_webhook_router,
)

__all__ = [
    "create_github_webhook_router",
    "WebhookActionResponse",
]
