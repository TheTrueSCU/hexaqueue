"""Execution runtime port interfaces for process and container isolation.

Notes/Architectural Intent:
    Defines the contract for executing job commands across diverse runtime substrates:
    - Software-managed: Local POSIX subprocesses, Linux Cgroups v2, Rootless Podman/Apptainer.
    - Native Deference: Direct dispatch to AWS Batch, GCP Batch, or Kubernetes Jobs.
"""

from abc import ABC, abstractmethod
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.storage import VolumeAllocation


class ProcessExecutionResult(BaseModel):
    """Result of an executed compute workload.

    Args:
        exit_code: POSIX process exit code (0 for success, non-zero for failure).
        outcome: Standardized TerminalOutcome corresponding to execution.
        error_message: Optional error message or stderr snippet.
        walltime_seconds: Measured wall-clock execution duration in seconds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    error_message: str | None = Field(
        default=None, description="Detailed failure or error message"
    )
    exit_code: int = Field(description="Process exit code")
    outcome: TerminalOutcome = Field(description="Normalized terminal outcome")
    walltime_seconds: float = Field(
        ge=0.0, description="Elapsed execution walltime in seconds"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate result invariants."""
        if self.exit_code == 0 and self.outcome != TerminalOutcome.COMPLETED:
            msg = (
                f"exit_code 0 must map to TerminalOutcome.COMPLETED, got {self.outcome}"
            )
            raise ValueError(msg)
        return self


class ExecutionRuntimePort(ABC):
    """Abstract port interface for process and container execution."""

    @abstractmethod
    async def execute(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        """Execute a compute job within the designated runtime environment.

        Args:
            job: The complete JobSpec definition to execute.
            scratch_volume: Optional scratch storage allocation for the job workspace.
            environment: Optional environment variables to inject into the process.

        Returns:
            ProcessExecutionResult summarizing exit code, walltime, and outcome.

        Raises:
            HexaqueueError: If runtime setup or execution fails critically.
        """

    @abstractmethod
    async def terminate(self, job_id: str, grace_period_seconds: int = 15) -> None:
        """Gracefully interrupt or forcibly terminate a running job.

        Args:
            job_id: The job identifier to terminate.
            grace_period_seconds: Seconds to wait after SIGTERM/SIGUSR1 before SIGKILL.
        """
