"""Unit tests for GitHubWebhookAdapter."""

import hashlib
import hmac
import json
from typing import Any

import pytest

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


def _sign(payload: bytes, secret: str) -> str:
    """Helper to compute sha256= signature."""
    mac = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


@pytest.mark.asyncio
async def test_process_webhook_queued_event() -> None:
    """Test full webhook processing flow for workflow_job.queued event."""
    client = InMemoryGitHubApiClient()
    autoscaler = DynamicGitHubRunnerAutoscaler(api_client=client)
    verifier = HmacSha256WebhookVerifier()
    secret = "test-secret"
    adapter = GitHubWebhookAdapter(
        verifier=verifier, autoscaler=autoscaler, secret=secret
    )

    payload_dict: dict[str, Any] = {
        "action": "queued",
        "workflow_job": {
            "id": 99991,
            "run_id": 88881,
            "head_sha": "abc1234",
            "name": "integration-test",
            "labels": ["self-hosted", "32-cores", "gpu-h100"],
        },
        "repository": {
            "id": 1,
            "name": "core-repo",
            "full_name": "org/core-repo",
            "owner": {"login": "org"},
        },
    }
    body_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = _sign(body_bytes, secret)
    headers = {
        "X-GitHub-Event": "workflow_job",
        "X-Hub-Signature-256": sig,
    }

    job_spec = await adapter.process_webhook(body_bytes, headers)
    assert job_spec is not None
    assert job_spec.id == "job-gh-99991"
    assert job_spec.resources.cpus == 32
    assert job_spec.resources.gpu_model == "h100"


@pytest.mark.asyncio
async def test_process_webhook_ignores_non_workflow_job_event() -> None:
    """Test webhook ignores push or pull_request events gracefully."""
    client = InMemoryGitHubApiClient()
    autoscaler = DynamicGitHubRunnerAutoscaler(api_client=client)
    verifier = HmacSha256WebhookVerifier()
    secret = "secret"
    adapter = GitHubWebhookAdapter(
        verifier=verifier, autoscaler=autoscaler, secret=secret
    )

    body = b'{"ref":"refs/heads/main"}'
    headers = {
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": _sign(body, secret),
    }

    res = await adapter.process_webhook(body, headers)
    assert res is None


@pytest.mark.asyncio
async def test_process_webhook_invalid_signature_raises() -> None:
    """Test invalid signature throws PermissionError."""
    client = InMemoryGitHubApiClient()
    autoscaler = DynamicGitHubRunnerAutoscaler(api_client=client)
    verifier = HmacSha256WebhookVerifier()
    adapter = GitHubWebhookAdapter(
        verifier=verifier, autoscaler=autoscaler, secret="real-secret"
    )

    body = b'{"action":"queued"}'
    headers = {
        "X-GitHub-Event": "workflow_job",
        "X-Hub-Signature-256": "sha256=fakefakefake",
    }

    with pytest.raises(PermissionError):
        await adapter.process_webhook(body, headers)


@pytest.mark.asyncio
async def test_process_webhook_malformed_json_raises() -> None:
    """Test malformed JSON payload throws ValueError."""
    client = InMemoryGitHubApiClient()
    autoscaler = DynamicGitHubRunnerAutoscaler(api_client=client)
    verifier = HmacSha256WebhookVerifier()
    secret = "secret"
    adapter = GitHubWebhookAdapter(
        verifier=verifier, autoscaler=autoscaler, secret=secret
    )

    body = b"not-valid-json"
    headers = {
        "X-GitHub-Event": "workflow_job",
        "X-Hub-Signature-256": _sign(body, secret),
    }

    with pytest.raises(ValueError, match="Failed to decode JSON"):
        await adapter.process_webhook(body, headers)
