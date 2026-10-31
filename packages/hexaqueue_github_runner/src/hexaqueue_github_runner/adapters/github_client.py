"""Concrete GitHub REST API clients and in-memory test doubles.

Notes/Architectural Intent:
    Provides production HTTP client using httpx with RSA RS256 JWT generation
    for GitHub App authentication, along with an in-memory double for testing.
"""

import base64
import json
import secrets
import time
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from hexaqueue_github_runner.domain.jit import (
    GitHubAppCredentials,
    JitRunnerConfig,
)
from hexaqueue_github_runner.domain.traceability import JobSummaryAnnotation
from hexaqueue_github_runner.ports.client import GitHubApiClientPort


def _base64url_encode(data: bytes) -> str:
    """Encode bytes into base64url string without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def create_github_app_jwt(
    app_id: str, private_key_pem: str, expiration_seconds: int = 600
) -> str:
    """Generate a signed RS256 JWT for GitHub App authentication.

    Args:
        app_id: GitHub App identifier.
        private_key_pem: PEM formatted RSA private key.
        expiration_seconds: JWT lifetime in seconds (max 600s per GitHub spec).

    Returns:
        Signed JWT string.

    Raises:
        ValueError: If private key is invalid.
    """
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iat": now - 60,  # 60s clock drift allowance
        "exp": now + expiration_seconds,
        "iss": app_id,
    }

    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    signing_input = (
        f"{_base64url_encode(header_bytes)}.{_base64url_encode(payload_bytes)}".encode(
            "ascii"
        )
    )

    private_key = load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    if not isinstance(private_key, rsa.RSAPrivateKey):
        msg = "GitHub App private key must be an RSA private key"
        raise ValueError(msg)

    signature = private_key.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )

    return f"{signing_input.decode('ascii')}.{_base64url_encode(signature)}"


class InMemoryGitHubApiClient(GitHubApiClientPort):
    """Hermetic in-memory test double for GitHub REST API interactions.

    Notes/Architectural Intent:
        Facilitates unit testing, offline execution, and dual-oracle testing
        without invoking external GitHub endpoints.
    """

    def __init__(self) -> None:
        self.installation_tokens: dict[int, str] = {}
        self.jit_configs: dict[str, JitRunnerConfig] = {}
        self.annotations: list[dict[str, Any]] = []
        self._next_runner_id: int = 1000

    async def generate_installation_token(self, installation_id: int) -> str:
        """Mint a dummy installation access token."""
        token = f"ghs_{secrets.token_hex(16)}"
        self.installation_tokens[installation_id] = token
        return token

    async def generate_jit_runner_config(
        self,
        owner: str,
        repo: str,
        runner_name: str,
        labels: list[str],
        runner_group_id: int | None = None,
    ) -> JitRunnerConfig:
        """Create an in-memory JIT runner config."""
        del runner_group_id
        runner_id = self._next_runner_id
        self._next_runner_id += 1

        dummy_payload = {
            "runner_id": runner_id,
            "runner_name": runner_name,
            "repo": f"{owner}/{repo}",
            "token": secrets.token_urlsafe(32),
        }
        encoded = base64.b64encode(json.dumps(dummy_payload).encode("utf-8")).decode(
            "ascii"
        )

        config = JitRunnerConfig(
            runner_id=runner_id,
            runner_name=runner_name,
            encoded_jit_config=encoded,
            os="linux",
            labels=labels,
            single_use=True,
        )
        self.jit_configs[runner_name] = config
        return config

    async def post_workflow_job_annotation(
        self,
        owner: str,
        repo: str,
        check_run_id: int,
        annotation: JobSummaryAnnotation,
    ) -> None:
        """Record an in-memory workflow job annotation."""
        self.annotations.append(
            {
                "owner": owner,
                "repo": repo,
                "check_run_id": check_run_id,
                "annotation": annotation,
            }
        )


class GitHubApiClient(GitHubApiClientPort):
    """Production asynchronous GitHub REST API client using httpx.

    Args:
        credentials: Optional GitHub App authentication credentials.
        base_url: GitHub API endpoint (defaults to 'https://api.github.com').
        client: Optional custom httpx.AsyncClient.
    """

    def __init__(
        self,
        credentials: GitHubAppCredentials | None = None,
        base_url: str = "https://api.github.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient()

    async def generate_installation_token(self, installation_id: int) -> str:
        """Mint a short-lived GitHub App installation token.

        Args:
            installation_id: Target installation ID.

        Returns:
            Access token string.

        Raises:
            RuntimeError: If credentials are missing or API request fails.
        """
        if not self.credentials:
            msg = "Cannot generate installation token without configured GitHubAppCredentials"
            raise RuntimeError(msg)

        jwt = create_github_app_jwt(
            self.credentials.app_id, self.credentials.private_key_pem
        )
        url = f"{self.base_url}/app/installations/{installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        resp = await self._client.post(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return str(data["token"])

    async def generate_jit_runner_config(
        self,
        owner: str,
        repo: str,
        runner_name: str,
        labels: list[str],
        runner_group_id: int | None = None,
    ) -> JitRunnerConfig:
        """Request single-use JIT runner configuration from GitHub API.

        Args:
            owner: Repository owner.
            repo: Repository name.
            runner_name: Unique runner name.
            labels: Runner labels.
            runner_group_id: Optional runner group ID.

        Returns:
            JitRunnerConfig with encoded config blob.

        Raises:
            RuntimeError: If API call fails.
        """
        token = ""
        if self.credentials:
            token = await self.generate_installation_token(
                self.credentials.installation_id
            )

        url = f"{self.base_url}/repos/{owner}/{repo}/actions/runners/generate-jitconfig"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body: dict[str, Any] = {
            "name": runner_name,
            "runner_group_id": runner_group_id or 1,
            "labels": labels,
            "work_folder": "_work",
        }

        resp = await self._client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

        runner_raw = data.get("runner", {})
        runner_id = int(runner_raw.get("id", 0))
        encoded_config = str(data["encoded_jit_config"])

        return JitRunnerConfig(
            runner_id=runner_id,
            runner_name=runner_name,
            encoded_jit_config=encoded_config,
            os="linux",
            labels=labels,
            single_use=True,
        )

    async def post_workflow_job_annotation(
        self,
        owner: str,
        repo: str,
        check_run_id: int,
        annotation: JobSummaryAnnotation,
    ) -> None:
        """Publish execution summary annotation to GitHub Check Run.

        Args:
            owner: Repository owner.
            repo: Repository name.
            check_run_id: Check Run ID.
            annotation: Structured execution report.

        Raises:
            RuntimeError: If API request fails.
        """
        token = ""
        if self.credentials:
            token = await self.generate_installation_token(
                self.credentials.installation_id
            )

        url = f"{self.base_url}/repos/{owner}/{repo}/check-runs/{check_run_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        markdown_text = annotation.to_markdown_summary()
        body = {
            "output": {
                "title": f"Hexaqueue Execution: {annotation.job_id}",
                "summary": f"Duration: {annotation.execution_seconds:.2f}s | Credits: {annotation.credit_burn:.4f} HQ",
                "text": markdown_text,
            }
        }

        resp = await self._client.patch(url, headers=headers, json=body)
        resp.raise_for_status()


__all__ = [
    "create_github_app_jwt",
    "GitHubApiClient",
    "InMemoryGitHubApiClient",
]
