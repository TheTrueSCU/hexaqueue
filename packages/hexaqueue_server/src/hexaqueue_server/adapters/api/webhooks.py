"""Cryptographic inbound webhook receivers for GitHub, GitLab, and container registries.

Notes/Architectural Intent:
    Verifies cryptographic signatures (HMAC SHA-256 or provider tokens) using hexastack-auth
    adapters, then translates inbound CI/CD event payloads into pure domain CQRS commands
    (such as SubmitRunCommand or RegisterCollateralCommand) dispatched via ExecutionPipeline.
"""

import hmac
import os
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from hexastack_auth.adapters.webhook import (
    GitHubWebhookVerifier,
    HmacSha256Verifier,
)
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline
from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.collateral import CollateralKind, CollateralTier
from hexaqueue_core.domain.cqrs import (
    RegisterCollateralCommand,
    SubmitRunCommand,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_server.adapters.api.common import _dispatch


class GitLabWebhookVerifier:
    """GitLab webhook token verifier checking the 'X-Gitlab-Token' header.

    Notes/Architectural Intent:
        Implements constant-time secret comparison against GitLab's secret token
        header as specified in GitLab Webhook security guidelines.
    """

    HEADER_NAME = "X-Gitlab-Token"

    def verify(
        self,
        payload: bytes,
        headers: Mapping[str, str],
        secret: str,
    ) -> bool:
        """Verify GitLab webhook token against expected secret.

        Args:
            payload: Raw request body bytes (unused for token matching).
            headers: HTTP request headers mapping.
            secret: Expected secret token configured for the webhook endpoint.

        Returns:
            True if token header matches expected secret in constant time.

        Raises:
            HTTPException: If the header is missing or does not match secret.
        """
        del payload
        token = headers.get(self.HEADER_NAME) or headers.get(self.HEADER_NAME.lower())
        if not token:
            msg = f"Missing required GitLab webhook token header '{self.HEADER_NAME}'"
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)

        if not hmac.compare_digest(token, secret):
            msg = "Invalid GitLab webhook token"
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)

        return True


class WebhookReceiptResponse(BaseModel):
    """Response payload returned upon successful webhook receipt and command dispatch.

    Args:
        event: Recognized event name or action.
        dispatched_command: Name of the dispatched CQRS command type.
        resource_id: Identifier of the generated run or registered collateral bundle.
        status: Status indicator string.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dispatched_command: str = Field(description="Dispatched CQRS command type name")
    event: str = Field(description="Event name or action type")
    resource_id: str = Field(
        description="Identifier of created run or registered collateral"
    )
    status: str = Field(default="accepted", description="Processing status")


def _get_secret(env_var: str, default: str = "") -> str:
    """Retrieve webhook secret from environment variable."""
    return os.environ.get(env_var, default)


def _build_github_run_command(
    data: dict[str, Any], event_type: str
) -> SubmitRunCommand:
    """Build a SubmitRunCommand from GitHub push or workflow event payload."""
    repo_raw = data.get("repository")
    repo_name = (
        repo_raw.get("name", "github-repo")
        if isinstance(repo_raw, dict)
        else "github-repo"
    )
    workflow_raw = data.get("workflow_run")
    head_sha = (
        data.get("after")
        or (workflow_raw.get("head_sha") if isinstance(workflow_raw, dict) else None)
        or "head"
    )
    run_id = f"gh-{repo_name}-{head_sha[:8]}"
    job_id = f"job-{run_id}-test"

    return SubmitRunCommand(
        run_spec=RunSpec(
            id=run_id,
            name=f"github-{repo_name}-{event_type}",
            tags=[f"repo:{repo_name}", f"sha:{head_sha}", "source:github"],
        ),
        jobs=[
            JobSpec(
                id=job_id,
                run_id=run_id,
                name=f"ci-{repo_name}",
                command=f"git checkout {head_sha} && pytest",
                tags=["source:github"],
            )
        ],
        dependencies={},
        user_id="github-actions",
    )


def _build_github_collateral_command(
    data: dict[str, Any], event_type: str
) -> RegisterCollateralCommand:
    """Build a RegisterCollateralCommand from GitHub artifact or release event payload."""
    artifact_name = data.get("artifact_name") or f"{event_type}-artifact"
    sha256 = data.get("sha256") or "0" * 64
    size_bytes = int(data.get("size_bytes", 1024))
    return RegisterCollateralCommand(
        name=artifact_name,
        version=data.get("version", "latest"),
        checksum_sha256=sha256,
        size_bytes=size_bytes,
        kind=CollateralKind.BUNDLE,
        tier=CollateralTier.TEMPORARY,
        user_id="github-actions",
    )


def _build_gitlab_run_command(data: dict[str, Any]) -> SubmitRunCommand:
    """Build a SubmitRunCommand from GitLab pipeline event payload."""
    project_raw = data.get("project")
    project_name = (
        project_raw.get("name", "gitlab-repo")
        if isinstance(project_raw, dict)
        else "gitlab-repo"
    )
    checkout_sha = data.get("checkout_sha") or "head"
    run_id = f"gl-{project_name}-{checkout_sha[:8]}"
    job_id = f"job-{run_id}-test"

    return SubmitRunCommand(
        run_spec=RunSpec(
            id=run_id,
            name=f"gitlab-{project_name}",
            tags=[f"repo:{project_name}", f"sha:{checkout_sha}", "source:gitlab"],
        ),
        jobs=[
            JobSpec(
                id=job_id,
                run_id=run_id,
                name=f"ci-{project_name}",
                command=f"git checkout {checkout_sha} && make test",
                tags=["source:gitlab"],
            )
        ],
        dependencies={},
        user_id="gitlab-ci",
    )


def _build_registry_collateral_command(
    data: dict[str, Any],
) -> RegisterCollateralCommand:
    """Build a RegisterCollateralCommand from container registry push event."""
    target_raw = data.get("target")
    target = target_raw if isinstance(target_raw, dict) else {}
    repo = target.get("repository", "app")
    tag = target.get("tag", "latest")
    digest = target.get("digest", "") or data.get("digest", "")
    clean_sha = digest.split(":")[-1] if ":" in digest else (digest or "0" * 64)
    clean_sha = clean_sha.lower().strip().zfill(64)[:64]
    size_bytes = int(target.get("size", data.get("size_bytes", 2048)))

    return RegisterCollateralCommand(
        name=f"{repo}:{tag}",
        version=tag,
        checksum_sha256=clean_sha,
        size_bytes=size_bytes,
        kind=CollateralKind.CONTAINER_IMAGE,
        tier=CollateralTier.PERMANENT,
        user_id="container-registry",
    )


async def _handle_github_event(
    request: Request,
    pipeline: ExecutionPipeline,
    verifier: GitHubWebhookVerifier,
) -> WebhookReceiptResponse:
    """Verify GitHub webhook signature and process event."""
    raw_body = await request.body()
    secret = _get_secret("HEXAQUEUE_WEBHOOK_SECRET_GITHUB")
    if secret:
        try:
            verifier.verify(raw_body, request.headers, secret)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"GitHub webhook signature verification failed: {exc}",
            ) from exc

    event_type = request.headers.get("X-GitHub-Event", "push")
    data = await request.json() if raw_body else {}

    if event_type in ("push", "workflow_run", "workflow_job"):
        cmd = _build_github_run_command(data, event_type)
        _dispatch(pipeline, cmd)
        return WebhookReceiptResponse(
            event=event_type,
            dispatched_command="SubmitRunCommand",
            resource_id=cmd.run_spec.id,
        )

    col_cmd = _build_github_collateral_command(data, event_type)
    col_res = _dispatch(pipeline, col_cmd)
    res_id = getattr(col_res, "id", col_cmd.name)
    return WebhookReceiptResponse(
        event=event_type,
        dispatched_command="RegisterCollateralCommand",
        resource_id=res_id,
    )


async def _handle_gitlab_event(
    request: Request,
    pipeline: ExecutionPipeline,
    verifier: GitLabWebhookVerifier,
) -> WebhookReceiptResponse:
    """Verify GitLab webhook token and process event."""
    raw_body = await request.body()
    secret = _get_secret("HEXAQUEUE_WEBHOOK_SECRET_GITLAB")
    if secret:
        verifier.verify(raw_body, request.headers, secret)

    event_type = request.headers.get("X-Gitlab-Event", "Pipeline Hook")
    data = await request.json() if raw_body else {}

    cmd = _build_gitlab_run_command(data)
    _dispatch(pipeline, cmd)
    return WebhookReceiptResponse(
        event=event_type,
        dispatched_command="SubmitRunCommand",
        resource_id=cmd.run_spec.id,
    )


async def _handle_registry_event(
    request: Request,
    pipeline: ExecutionPipeline,
    verifier: HmacSha256Verifier,
) -> WebhookReceiptResponse:
    """Verify registry webhook signature and process event."""
    raw_body = await request.body()
    secret = _get_secret("HEXAQUEUE_WEBHOOK_SECRET_REGISTRY")
    if secret:
        try:
            verifier.verify(raw_body, request.headers, secret)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Registry webhook signature verification failed: {exc}",
            ) from exc

    data = await request.json() if raw_body else {}
    col_cmd = _build_registry_collateral_command(data)
    col_res = _dispatch(pipeline, col_cmd)
    res_id = getattr(col_res, "id", col_cmd.name)
    return WebhookReceiptResponse(
        event="image_push",
        dispatched_command="RegisterCollateralCommand",
        resource_id=res_id,
    )


def create_webhooks_router() -> APIRouter:
    """Construct APIRouter providing signature-verified inbound webhook receivers.

    Returns:
        APIRouter with endpoints for GitHub, GitLab, and container registry webhooks.
    """
    router = APIRouter(prefix="/webhooks", tags=["webhooks"])
    github_verifier = GitHubWebhookVerifier()
    gitlab_verifier = GitLabWebhookVerifier()
    registry_verifier = HmacSha256Verifier(header_name="X-Registry-Signature")

    @router.post(
        "/github",
        response_model=WebhookReceiptResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Receive and verify GitHub webhook event",
    )
    async def receive_github_webhook(
        request: Request,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
    ) -> WebhookReceiptResponse:
        return await _handle_github_event(request, pipeline, github_verifier)

    @router.post(
        "/gitlab",
        response_model=WebhookReceiptResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Receive and verify GitLab webhook event",
    )
    async def receive_gitlab_webhook(
        request: Request,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
    ) -> WebhookReceiptResponse:
        return await _handle_gitlab_event(request, pipeline, gitlab_verifier)

    @router.post(
        "/registry",
        response_model=WebhookReceiptResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Receive container registry push webhook event",
    )
    async def receive_registry_webhook(
        request: Request,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
    ) -> WebhookReceiptResponse:
        return await _handle_registry_event(request, pipeline, registry_verifier)

    return router


__all__ = [
    "create_webhooks_router",
    "GitLabWebhookVerifier",
    "WebhookReceiptResponse",
]
