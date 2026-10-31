"""FastAPI REST presentation adapters for Hexaqueue Server.

Notes/Architectural Intent:
    Exposes OpenAPI routes for all Hexaqueue capabilities with 100% surface parity
    to CLI and Web Dashboard. Implements the Principle of Least Privilege:
    callers act under their natural identity by default, with administrative
    elevation asserted explicitly via header (`X-Hexaqueue-Elevate: true`) or
    query parameter (`?elevate=true`).
"""

from hexaqueue_server.adapters.api.app import (
    create_server_api_router,
    create_server_app,
)
from hexaqueue_server.adapters.api.auth import get_auth_context
from hexaqueue_server.adapters.api.budget import create_budget_router
from hexaqueue_server.adapters.api.middleware import ZeroTrustBoundaryMiddleware
from hexaqueue_server.adapters.api.webhooks import (
    GitLabWebhookVerifier,
    WebhookReceiptResponse,
    create_webhooks_router,
)

__all__ = [
    "create_budget_router",
    "create_server_api_router",
    "create_server_app",
    "create_webhooks_router",
    "get_auth_context",
    "GitLabWebhookVerifier",
    "WebhookReceiptResponse",
    "ZeroTrustBoundaryMiddleware",
]
