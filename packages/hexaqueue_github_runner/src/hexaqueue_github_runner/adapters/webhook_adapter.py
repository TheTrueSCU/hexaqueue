"""GitHub Actions inbound webhook adapter.

Notes/Architectural Intent:
    Receives raw HTTP payload bytes and headers, verifies cryptographic HMAC
    signatures, deserializes workflow_job events, and forwards to the autoscaler.
"""

import json
from collections.abc import Mapping
from typing import Any

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_github_runner.domain.events import (
    GitHubRepository,
    GitHubWorkflowJob,
    GitHubWorkflowJobAction,
    GitHubWorkflowJobPayload,
)
from hexaqueue_github_runner.ports.autoscaler import (
    GitHubRunnerAutoscalerPort,
)
from hexaqueue_github_runner.ports.verifier import WebhookVerifierPort


class GitHubWebhookAdapter:
    """Driving adapter processing GitHub webhook deliveries for runner autoscaling.

    Args:
        verifier: WebhookVerifierPort for HMAC signature validation.
        autoscaler: GitHubRunnerAutoscalerPort for dispatching runner jobs.
        secret: Configured GitHub webhook secret token.

    Notes/Architectural Intent:
        Separates transport HTTP ingestion from autoscaling domain decisions.
    """

    def __init__(
        self,
        verifier: WebhookVerifierPort,
        autoscaler: GitHubRunnerAutoscalerPort,
        secret: str,
    ) -> None:
        self.verifier = verifier
        self.autoscaler = autoscaler
        self.secret = secret

    async def process_webhook(
        self,
        payload_bytes: bytes,
        headers: Mapping[str, str],
    ) -> JobSpec | None:
        """Process inbound webhook delivery, verify signature, and trigger autoscaler.

        Args:
            payload_bytes: Raw HTTP request body bytes.
            headers: HTTP request headers mapping.

        Returns:
            Dispatched JobSpec if runner was scheduled, or None if skipped/completed.

        Raises:
            ValueError: If event or payload format is invalid.
            PermissionError: If signature verification fails.
        """
        # Header lookup case-insensitively
        sig_header = headers.get("X-Hub-Signature-256") or headers.get(
            "x-hub-signature-256"
        )
        self.verifier.verify_signature(payload_bytes, sig_header, self.secret)

        event_type = headers.get("X-GitHub-Event") or headers.get("x-github-event")
        if event_type != "workflow_job":
            # Silently acknowledge and ignore non-workflow_job events
            return None

        try:
            raw_data = json.loads(payload_bytes.decode("utf-8"))
        except Exception as exc:
            msg = f"Failed to decode JSON webhook payload: {exc}"
            raise ValueError(msg) from exc

        payload = self._parse_payload(raw_data)
        return await self.autoscaler.handle_workflow_job(payload)

    def _parse_payload(self, data: dict[str, Any]) -> GitHubWorkflowJobPayload:
        """Deserialize raw JSON dict into typed GitHubWorkflowJobPayload."""
        action_str = str(data.get("action", ""))
        try:
            action = GitHubWorkflowJobAction(action_str)
        except ValueError:
            action = GitHubWorkflowJobAction.WAITING

        wf_raw = data.get("workflow_job", {})
        repo_raw = data.get("repository", {})

        repo = GitHubRepository(
            id=int(repo_raw.get("id", 0)),
            name=str(repo_raw.get("name", "unknown")),
            full_name=str(repo_raw.get("full_name", "unknown/unknown")),
            owner=str(
                repo_raw.get("owner", {}).get("login", "")
                if isinstance(repo_raw.get("owner"), dict)
                else repo_raw.get("owner", "")
            ),
            private=bool(repo_raw.get("private", True)),
            html_url=repo_raw.get("html_url"),
        )

        wf_job = GitHubWorkflowJob(
            id=int(wf_raw.get("id", 0)),
            run_id=int(wf_raw.get("run_id", 0)),
            workflow_name=wf_raw.get("workflow_name"),
            head_branch=wf_raw.get("head_branch"),
            head_sha=str(wf_raw.get("head_sha", "unknown")),
            status=str(wf_raw.get("status", "queued")),
            conclusion=wf_raw.get("conclusion"),
            name=str(wf_raw.get("name", "job")),
            labels=list(wf_raw.get("labels", [])),
            runner_id=wf_raw.get("runner_id"),
            runner_name=wf_raw.get("runner_name"),
            runner_group_id=wf_raw.get("runner_group_id"),
            runner_group_name=wf_raw.get("runner_group_name"),
        )

        installation_id = (
            int(data["installation"]["id"])
            if "installation" in data
            and isinstance(data["installation"], dict)
            and "id" in data["installation"]
            else None
        )

        sender_login = (
            str(data["sender"]["login"])
            if "sender" in data
            and isinstance(data["sender"], dict)
            and "login" in data["sender"]
            else None
        )

        return GitHubWorkflowJobPayload(
            action=action,
            workflow_job=wf_job,
            repository=repo,
            installation_id=installation_id,
            sender_login=sender_login,
        )


__all__ = [
    "GitHubWebhookAdapter",
]
