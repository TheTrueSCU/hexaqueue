"""Abstract port interface for GitHub REST API operations.

Notes/Architectural Intent:
    Decouples domain autoscaling logic from GitHub REST client networking,
    enabling hermetic testing via in-memory doubles.
"""

from abc import ABC, abstractmethod

from hexaqueue_github_runner.domain.jit import JitRunnerConfig
from hexaqueue_github_runner.domain.traceability import JobSummaryAnnotation


class GitHubApiClientPort(ABC):
    """Abstract port for GitHub Actions REST API communications.

    Notes/Architectural Intent:
        Defines contracts for minting GitHub App installation tokens,
        requesting JIT runner configuration blobs, and publishing annotations.
    """

    @abstractmethod
    async def generate_installation_token(self, installation_id: int) -> str:
        """Mint a short-lived GitHub App installation access token.

        Args:
            installation_id: GitHub App installation identifier.

        Returns:
            Bearer access token string for GitHub API requests.

        Raises:
            Exception: If GitHub API rejects the request or credentials fail.
        """

    @abstractmethod
    async def generate_jit_runner_config(
        self,
        owner: str,
        repo: str,
        runner_name: str,
        labels: list[str],
        runner_group_id: int | None = None,
    ) -> JitRunnerConfig:
        """Request a single-use Just-In-Time (JIT) runner configuration.

        Args:
            owner: Repository owner username or organization.
            repo: Repository name.
            runner_name: Name of the ephemeral runner being registered.
            labels: List of runner labels to register with GitHub.
            runner_group_id: Optional runner group ID for enterprise runners.

        Returns:
            JitRunnerConfig containing the encoded JIT blob and runner ID.

        Raises:
            Exception: If runner generation fails on the GitHub API side.
        """

    @abstractmethod
    async def post_workflow_job_annotation(
        self,
        owner: str,
        repo: str,
        check_run_id: int,
        annotation: JobSummaryAnnotation,
    ) -> None:
        """Publish an execution report and credit burn summary to the Check Run.

        Args:
            owner: Repository owner username or organization.
            repo: Repository name.
            check_run_id: Associated GitHub Check Run ID or workflow job ID.
            annotation: Structured execution performance and credit burn data.

        Raises:
            Exception: If GitHub API rejects the check run update.
        """


__all__ = [
    "GitHubApiClientPort",
]
