"""Unit tests for signature-verified inbound webhook receivers."""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from hexaqueue_server.adapters.api.webhooks import GitLabWebhookVerifier


def test_gitlab_verifier_unit() -> None:
    """Verify GitLabWebhookVerifier header check and error handling."""
    verifier = GitLabWebhookVerifier()
    secret = "my-gitlab-token"

    # 1. Matching token
    res = verifier.verify(b"", {"X-Gitlab-Token": secret}, secret)
    assert res is True

    # 2. Missing token raises 401
    with pytest.raises(Exception, match="Missing required GitLab webhook token"):
        verifier.verify(b"", {}, secret)

    # 3. Invalid token raises 401
    with pytest.raises(Exception, match="Invalid GitLab webhook token"):
        verifier.verify(b"", {"X-Gitlab-Token": "wrong-token"}, secret)


def test_github_webhook_push_event(
    hermetic_api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify GitHub push webhook triggers SubmitRunCommand."""
    secret = "gh-secret-token"
    monkeypatch.setenv("HEXAQUEUE_WEBHOOK_SECRET_GITHUB", secret)

    payload = {
        "repository": {"name": "test-repo"},
        "after": "1234567890abcdef",
    }
    raw_body = json.dumps(payload).encode()
    signature = (
        "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    )

    headers = {
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": signature,
        "Content-Type": "application/json",
    }
    resp = hermetic_api_client.post(
        "/v1/webhooks/github", content=raw_body, headers=headers
    )
    status_code = resp.status_code
    assert status_code == 202
    data = resp.json()
    assert data["event"] == "push"
    assert data["dispatched_command"] == "SubmitRunCommand"
    assert "gh-test-repo-12345678" in data["resource_id"]


def test_github_webhook_invalid_signature(
    hermetic_api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify GitHub webhook with invalid signature is rejected with 401."""
    monkeypatch.setenv("HEXAQUEUE_WEBHOOK_SECRET_GITHUB", "correct-secret")
    raw_body = b'{"repository": {"name": "test-repo"}}'
    headers = {
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": "sha256=badsignature",
        "Content-Type": "application/json",
    }
    resp = hermetic_api_client.post(
        "/v1/webhooks/github", content=raw_body, headers=headers
    )
    status_code = resp.status_code
    assert status_code == 401


def test_github_webhook_artifact_collateral(
    hermetic_api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify GitHub release/package webhook registers collateral."""
    monkeypatch.delenv("HEXAQUEUE_WEBHOOK_SECRET_GITHUB", raising=False)
    payload = {
        "artifact_name": "app-bin",
        "version": "v1.2.3",
        "sha256": "a" * 64,
        "size_bytes": 4096,
    }
    raw_body = json.dumps(payload).encode()
    headers = {
        "X-GitHub-Event": "release",
        "Content-Type": "application/json",
    }
    resp = hermetic_api_client.post(
        "/v1/webhooks/github", content=raw_body, headers=headers
    )
    status_code = resp.status_code
    assert status_code == 202
    data = resp.json()
    assert data["event"] == "release"
    assert data["dispatched_command"] == "RegisterCollateralCommand"


def test_gitlab_webhook_pipeline_event(
    hermetic_api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify GitLab webhook verifies token and dispatches SubmitRunCommand."""
    secret = "gl-secret-token"
    monkeypatch.setenv("HEXAQUEUE_WEBHOOK_SECRET_GITLAB", secret)

    payload = {
        "project": {"name": "gl-project"},
        "checkout_sha": "abcdef1234567890",
    }
    raw_body = json.dumps(payload).encode()
    headers = {
        "X-Gitlab-Event": "Pipeline Hook",
        "X-Gitlab-Token": secret,
        "Content-Type": "application/json",
    }
    resp = hermetic_api_client.post(
        "/v1/webhooks/gitlab", content=raw_body, headers=headers
    )
    status_code = resp.status_code
    assert status_code == 202
    data = resp.json()
    assert data["event"] == "Pipeline Hook"
    assert data["dispatched_command"] == "SubmitRunCommand"
    assert "gl-gl-project-abcdef12" in data["resource_id"]


def test_registry_webhook_image_push(
    hermetic_api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify container registry push registers container image collateral."""
    secret = "registry-secret"
    monkeypatch.setenv("HEXAQUEUE_WEBHOOK_SECRET_REGISTRY", secret)

    payload = {
        "target": {
            "repository": "hexaqueue-worker",
            "tag": "v2.0.0",
            "digest": "sha256:" + "b" * 64,
            "size": 8192,
        }
    }
    raw_body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    headers = {
        "X-Registry-Signature": signature,
        "Content-Type": "application/json",
    }
    resp = hermetic_api_client.post(
        "/v1/webhooks/registry", content=raw_body, headers=headers
    )
    status_code = resp.status_code
    assert status_code == 202
    data = resp.json()
    assert data["event"] == "image_push"
    assert data["dispatched_command"] == "RegisterCollateralCommand"
