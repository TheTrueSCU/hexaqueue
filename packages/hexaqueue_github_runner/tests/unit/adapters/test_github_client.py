"""Unit tests for GitHub REST API clients and JWT token generation."""

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from hexaqueue_github_runner.adapters.github_client import (
    GitHubApiClient,
    InMemoryGitHubApiClient,
    create_github_app_jwt,
)
from hexaqueue_github_runner.domain.jit import GitHubAppCredentials
from hexaqueue_github_runner.domain.traceability import JobSummaryAnnotation


@pytest.fixture
def rsa_private_key_pem() -> str:
    """Generate a temporary RSA private key for testing JWT generation."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def test_create_github_app_jwt(rsa_private_key_pem: str) -> None:
    """Test generating signed RS256 JWT for GitHub App."""
    jwt_str = create_github_app_jwt("123456", rsa_private_key_pem)
    parts = jwt_str.split(".")
    assert len(parts) == 3


@pytest.mark.asyncio
async def test_in_memory_github_client() -> None:
    """Test operations on InMemoryGitHubApiClient."""
    client = InMemoryGitHubApiClient()

    token = await client.generate_installation_token(42)
    assert token.startswith("ghs_")

    jit_config = await client.generate_jit_runner_config(
        owner="org",
        repo="repo",
        runner_name="runner-1",
        labels=["self-hosted", "gpu-h100"],
    )
    assert jit_config.runner_name == "runner-1"
    assert jit_config.single_use is True

    annotation = JobSummaryAnnotation(
        job_id="job-1",
        run_id="run-1",
        workflow_job_id=101,
        execution_seconds=12.0,
        credit_burn=0.05,
    )
    await client.post_workflow_job_annotation("org", "repo", 101, annotation)
    assert len(client.annotations) == 1
    assert client.annotations[0]["check_run_id"] == 101


@pytest.mark.asyncio
async def test_github_api_client_with_mock_transport(
    rsa_private_key_pem: str,
) -> None:
    """Test GitHubApiClient using an httpx MockTransport."""

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "access_tokens" in url_str:
            return httpx.Response(201, json={"token": "ghs_mock_token_123"})
        if "generate-jitconfig" in url_str:
            return httpx.Response(
                201,
                json={
                    "runner": {"id": 888},
                    "encoded_jit_config": "bW9ja19qaXRfY29uZmln",
                },
            )
        if "check-runs" in url_str:
            return httpx.Response(200, json={"id": 101, "status": "completed"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        creds = GitHubAppCredentials(
            app_id="app-1",
            installation_id=42,
            private_key_pem=rsa_private_key_pem,
        )
        api = GitHubApiClient(credentials=creds, client=mock_client)

        token = await api.generate_installation_token(42)
        assert token == "ghs_mock_token_123"

        jit_cfg = await api.generate_jit_runner_config(
            "org", "repo", "runner-x", ["self-hosted"]
        )
        assert jit_cfg.runner_id == 888
        assert jit_cfg.encoded_jit_config == "bW9ja19qaXRfY29uZmln"

        annotation = JobSummaryAnnotation(
            job_id="j1",
            run_id="r1",
            workflow_job_id=101,
            execution_seconds=10.0,
            credit_burn=0.01,
        )
        await api.post_workflow_job_annotation("org", "repo", 101, annotation)


@pytest.mark.asyncio
async def test_github_api_client_missing_credentials_raises() -> None:
    """Test calling token generation without credentials raises RuntimeError."""
    api = GitHubApiClient(credentials=None)
    with pytest.raises(RuntimeError, match="without configured GitHubAppCredentials"):
        await api.generate_installation_token(123)
