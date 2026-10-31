"""FastAPI HTTP routing infrastructure for GitHub webhooks.

Notes/Architectural Intent:
    Provides pluggable FastAPI APIRouter exposing the webhook endpoint for
    consumption by hexaqueue-server or standalone runner services.
"""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_github_runner.adapters.webhook_adapter import (
    GitHubWebhookAdapter,
)


class WebhookActionResponse(BaseModel):
    """Response payload for received GitHub webhook delivery.

    Args:
        status: Delivery outcome status.
        job_id: Hexaqueue job ID scheduled, if any.
        event: Handled GitHub event name.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: str = Field(default="workflow_job", description="Received event")
    job_id: str | None = Field(default=None, description="Dispatched job ID")
    status: str = Field(default="accepted", description="Processing verdict")


def create_github_webhook_router(
    adapter: GitHubWebhookAdapter,
    secret_getter: Callable[[], str] | None = None,
) -> APIRouter:
    """Construct an APIRouter configured for GitHub webhook ingress.

    Args:
        adapter: Configured GitHubWebhookAdapter instance.
        secret_getter: Optional callable returning dynamic webhook secret.

    Returns:
        Configured FastAPI APIRouter.
    """
    router = APIRouter(prefix="/webhooks/github", tags=["github-runner"])

    @router.post("", response_model=WebhookActionResponse)
    async def handle_github_webhook(request: Request) -> Any:
        """Handle incoming GitHub Actions webhook HTTP request."""
        body = await request.body()
        headers = dict(request.headers)

        if secret_getter:
            adapter.secret = secret_getter()

        try:
            job_spec = await adapter.process_webhook(body, headers)
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        job_id = job_spec.id if job_spec else None
        return WebhookActionResponse(
            event=headers.get("x-github-event", "workflow_job"),
            job_id=job_id,
            status="scheduled" if job_id else "ignored",
        )

    return router


__all__ = [
    "create_github_webhook_router",
    "WebhookActionResponse",
]
