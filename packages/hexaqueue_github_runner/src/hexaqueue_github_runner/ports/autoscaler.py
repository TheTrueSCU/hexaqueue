"""Abstract port interface for GitHub Actions runner autoscaler engine.

Notes/Architectural Intent:
    Orchestrates webhook lifecycle transitions (queued -> in_progress -> completed),
    translates hardware claims, provisions JIT tokens, and manages warm pools.
"""

from abc import ABC, abstractmethod
from typing import Any

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_github_runner.domain.events import GitHubWorkflowJobPayload
from hexaqueue_github_runner.domain.pool import WarmPoolConfig


class GitHubRunnerAutoscalerPort(ABC):
    """Abstract port for dynamic GitHub Actions runner autoscaling and pool management.

    Notes/Architectural Intent:
        Core driving port for translating workflow events into Hexaqueue jobs
        and orchestrating zero-trust teardown upon job completion.
    """

    @abstractmethod
    async def handle_workflow_job(
        self, payload: GitHubWorkflowJobPayload
    ) -> JobSpec | None:
        """Process an inbound workflow job event and scale runners accordingly.

        Args:
            payload: Parsed GitHub workflow job payload.

        Returns:
            Dispatched JobSpec if a runner was scheduled, or None if skipped/completed.

        Raises:
            Exception: If autoscaling or runner minting encounters an error.
        """

    @abstractmethod
    def register_warm_pool(self, config: WarmPoolConfig) -> None:
        """Register a warm pool configuration for pre-warmed static runners.

        Args:
            config: Pool configuration specifying capacity and labels.

        Raises:
            ValueError: If pool configuration is invalid or already exists.
        """

    @abstractmethod
    def get_active_runner_count(self) -> int:
        """Return the count of currently active or provisioned runners.

        Returns:
            Non-negative integer representing active runner instances.
        """

    @abstractmethod
    def get_warm_pool_status(self, pool_id: str) -> dict[str, Any]:
        """Query real-time metrics and capacity for a specific warm pool.

        Args:
            pool_id: Warm pool identifier.

        Returns:
            Dictionary containing idle, busy, and total runner metrics.

        Raises:
            KeyError: If pool_id is not found.
        """


__all__ = [
    "GitHubRunnerAutoscalerPort",
]
