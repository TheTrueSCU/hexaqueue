"""Domain exceptions for hexaqueue_workflow.

Notes/Architectural Intent:
    Domain exceptions represent invariant violations, execution failures,
    and staging faults occurring within the workflow orchestration and
    distributed execution boundaries.
"""


class HexaqueueWorkflowError(Exception):
    """Base exception for all hexaqueue-workflow domain errors.

    Notes/Architectural Intent:
        Inherited by all specialized workflow and staging exceptions to allow
        callers to catch any package-level error deterministically.
    """


class ArtifactStagingError(HexaqueueWorkflowError):
    """Raised when serializing, storing, or retrieving a staged artifact fails.

    Notes/Architectural Intent:
        Prevents corrupt or missing intermediate step payloads from silently
        propagating to downstream dependent steps.
    """


class JobExecutionFailedError(HexaqueueWorkflowError):
    """Raised when a distributed step job fails or terminates abnormally.

    Notes/Architectural Intent:
        Wraps child job failures reported by the scheduler controller, carrying
        the failed job_id and terminal outcome reason.
    """

    def __init__(self, job_id: str, reason: str | None = None) -> None:
        """Initialize JobExecutionFailedError.

        Args:
            job_id: Identifier of the failing job.
            reason: Optional failure description or error log.
        """
        self.job_id = job_id
        self.reason = reason
        msg = f"Job '{job_id}' execution failed: {reason or 'unknown reason'}"
        super().__init__(msg)


class StepMappingNotFoundError(HexaqueueWorkflowError):
    """Raised when resource mapping for a requested step is missing.

    Notes/Architectural Intent:
        Signaled when strict validation requires explicit step job mappings
        and an unmapped step is encountered.
    """


__all__ = [
    "ArtifactStagingError",
    "HexaqueueWorkflowError",
    "JobExecutionFailedError",
    "StepMappingNotFoundError",
]
