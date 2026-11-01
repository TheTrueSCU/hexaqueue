"""Domain models for distributed test execution outcomes, reports, and coverage.

Notes/Architectural Intent:
    Encapsulates granular test outcomes, terminal slice reports, and execution
    telemetry streamed back from remote cluster workers or local fallbacks.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TestOutcomeItem(BaseModel):
    """Execution outcome of a single test item.

    Args:
        nodeid: Pytest test node identifier.
        outcome: Terminal verdict ('passed', 'failed', 'skipped', 'xfail', 'xpass').
        duration_seconds: Test execution duration in seconds.
        longrepr: Optional formatted traceback or skip/failure message.
        stdout: Standard output captured during test execution.
        stderr: Standard error captured during test execution.
    """

    __test__ = False
    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_seconds: float = Field(
        default=0.0, ge=0.0, description="Duration in seconds"
    )
    longrepr: str | None = Field(
        default=None, description="Traceback or explanation message"
    )
    nodeid: str = Field(description="Pytest node ID")
    outcome: str = Field(description="Outcome verdict")
    stderr: str | None = Field(default=None, description="Captured stderr")
    stdout: str | None = Field(default=None, description="Captured stdout")


class SliceOutcomeReport(BaseModel):
    """Aggregate execution report for a completed test slice.

    Args:
        slice_id: Slice identifier.
        slice_index: Zero-based slice index.
        worker_id: Worker instance identifier hosting the execution.
        provider: Hosting Cloud Service Provider or platform name.
        is_free_tier: Whether the slice executed under Free-Tier Safety Mode.
        outcomes: Detailed per-test outcome records.
        duration_seconds: Total walltime execution duration in seconds.
        coverage_data: Optional serialized coverage data mapping.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    coverage_data: dict[str, Any] | None = Field(
        default=None, description="Serialized coverage line mappings"
    )
    duration_seconds: float = Field(
        default=0.0, ge=0.0, description="Slice walltime in seconds"
    )
    is_free_tier: bool = Field(
        default=False, description="Executed under zero-cost Free-Tier"
    )
    outcomes: list[TestOutcomeItem] = Field(
        default_factory=list, description="Per-test outcome records"
    )
    provider: str | None = Field(
        default=None, description="Host cloud service provider or pool"
    )
    slice_id: str = Field(description="Slice identifier")
    slice_index: int = Field(ge=0, description="Slice index")
    worker_id: str | None = Field(
        default=None, description="Executing worker identifier"
    )

    @property
    def passed_count(self) -> int:
        """Count of passed tests."""
        return sum(1 for o in self.outcomes if o.outcome == "passed")

    @property
    def failed_count(self) -> int:
        """Count of failed tests."""
        return sum(1 for o in self.outcomes if o.outcome == "failed")

    @property
    def skipped_count(self) -> int:
        """Count of skipped tests."""
        return sum(1 for o in self.outcomes if o.outcome == "skipped")

    @property
    def is_success(self) -> bool:
        """Check if all tests passed or were skipped."""
        return self.failed_count == 0


__all__ = [
    "SliceOutcomeReport",
    "TestOutcomeItem",
]
