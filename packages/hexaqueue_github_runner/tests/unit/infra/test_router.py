"""Unit tests for FastAPI webhook routing infrastructure."""

import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from hexaqueue_github_runner.adapters.autoscaler import (
    DynamicGitHubRunnerAutoscaler,
)
from hexaqueue_github_runner.adapters.crypto import HmacSha256WebhookVerifier
from hexaqueue_github_runner.adapters.github_client import (
    InMemoryGitHubApiClient,
)
from hexaqueue_github_runner.adapters.webhook_adapter import (
    GitHubWebhookAdapter,
)
from hexaqueue_github_runner.infra.router import create_github_webhook_router


def _sign(payload: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


@pytest.mark.asyncio
async def test_fastapi_webhook_endpoint_success() -> None:
    """Test calling the FastAPI webhook endpoint with valid payload and signature."""
    client = InMemoryGitHubApiClient()
    autoscaler = DynamicGitHubRunnerAutoscaler(api_client=client)
    verifier = HmacSha256WebhookVerifier()
    secret = "secret-123"
    adapter = GitHubWebhookAdapter(
        verifier=verifier, autoscaler=autoscaler, secret=secret
    )

    app = FastAPI()
    router = create_github_webhook_router(adapter)
    app.include_router(router)

    payload_dict: dict[str, Any] = {
        "action": "queued",
        "workflow_job": {
            "id": 12345,
            "run_id": 67890,
            "head_sha": "commit-sha",
            "name": "unit-tests",
            "labels": ["self-hosted", "8-cores", "gpu-a100"],
        },
        "repository": {
            "id": 10,
            "name": "my-repo",
            "full_name": "org/my-repo",
            "owner": {"login": "org"},
        },
    }
    body_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = _sign(body_bytes, secret)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http_client:
        resp = await http_client.post(
            "/webhooks/github",
            content=body_bytes,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "scheduled"
        assert data["job_id"] == "job-gh-12345"


@pytest.mark.asyncio
async def test_fastapi_webhook_endpoint_unauthorized() -> None:
    """Test calling the FastAPI webhook endpoint with invalid signature returns 401."""
    client = InMemoryGitHubApiClient()
    autoscaler = DynamicGitHubRunnerAutoscaler(api_client=client)
    verifier = HmacSha256WebhookVerifier()
    secret = "secret-123"
    adapter = GitHubWebhookAdapter(
        verifier=verifier, autoscaler=autoscaler, secret=secret
    )

    app = FastAPI()
    router = create_github_webhook_router(adapter)
    app.include_router(router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http_client:
        resp = await http_client.post(
            "/webhooks/github",
            content=b'{"action":"queued"}',
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-Hub-Signature-256": "sha256=invalid",
            },
        )
        assert resp.status_code == 401
