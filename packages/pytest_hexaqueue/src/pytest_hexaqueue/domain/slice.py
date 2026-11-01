"""Domain models for distributed test item representation and slicing specifications.

Notes/Architectural Intent:
    Captures individual collected test items, partitioned execution slices,
    and distributed test session metadata without external framework dependencies.
"""

from pydantic import BaseModel, ConfigDict, Field


class TestItemInfo(BaseModel):
    """Metadata describing a single collected pytest item.

    Args:
        nodeid: Pytest node identifier (e.g., 'tests/unit/test_app.py::test_init').
        file_path: Relative filesystem path to the test module.
        line_number: Optional line number where the test is defined.
        markers: List of pytest marker tags.
        estimated_duration: Estimated execution time in seconds.
    """

    __test__ = False
    model_config = ConfigDict(frozen=True, extra="forbid")

    estimated_duration: float = Field(
        default=1.0, ge=0.0, description="Estimated duration in seconds"
    )
    file_path: str = Field(description="Relative path to test module")
    line_number: int | None = Field(
        default=None, description="Test definition line number"
    )
    markers: list[str] = Field(default_factory=list, description="Pytest marker tags")
    nodeid: str = Field(description="Unique pytest test node ID")


class TestSliceSpec(BaseModel):
    """Specification of an execution partition assigned to a cluster worker.

    Args:
        slice_id: Unique identifier for the slice (e.g., 'slice-0').
        slice_index: Zero-based index of this slice.
        total_slices: Total count of slices in the partitioned run.
        test_nodeids: Ordered list of test nodeids to execute in this slice.
        total_estimated_duration: Sum of estimated test durations in seconds.
    """

    __test__ = False
    model_config = ConfigDict(frozen=True, extra="forbid")

    slice_id: str = Field(description="Slice identifier")
    slice_index: int = Field(ge=0, description="Slice zero-based index")
    test_nodeids: list[str] = Field(
        default_factory=list, description="Assigned test node IDs"
    )
    total_estimated_duration: float = Field(
        default=0.0, ge=0.0, description="Summed estimated duration"
    )
    total_slices: int = Field(ge=1, description="Total number of slices")


class TestRunSession(BaseModel):
    """State and topology for a distributed pytest execution run.

    Args:
        session_id: Unique session identifier.
        total_items: Total count of collected tests across the suite.
        total_slices: Count of parallel slices generated.
        slices: Sequence of partitioned TestSliceSpec instances.
        server_url: Target Hexaqueue cluster controller API URL.
        pool: Target compute pool for runner placement.
        free_tier: Whether execution is governed under zero-cost Free-Tier Safety Mode.
        container: Whether to execute slices inside isolated OCI container sandboxes.
        container_image: Optional container image tag for worker runtime.
        coverage_sources: Sequence of source packages or paths for coverage collection.
    """

    __test__ = False
    model_config = ConfigDict(frozen=True, extra="forbid")

    container: bool = Field(
        default=False, description="Execute slices inside container worker runtime"
    )
    container_image: str | None = Field(
        default=None, description="Optional container image for worker runtime"
    )
    coverage_sources: list[str] = Field(
        default_factory=list,
        description="Target packages or paths for coverage collection",
    )
    free_tier: bool = Field(
        default=False, description="Enforce zero-cost Free-Tier limits"
    )
    pool: str = Field(default="default", description="Target instance pool")
    server_url: str = Field(
        default="http://127.0.0.1:8000", description="Hexaqueue controller URL"
    )
    session_id: str = Field(description="Unique test session UUID")
    slices: list[TestSliceSpec] = Field(
        default_factory=list, description="Partitioned test slices"
    )
    total_items: int = Field(ge=0, description="Total collected tests")
    total_slices: int = Field(ge=1, description="Number of slices")


__all__ = [
    "TestItemInfo",
    "TestRunSession",
    "TestSliceSpec",
]
