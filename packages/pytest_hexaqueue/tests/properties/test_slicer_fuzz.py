"""Property-based invariant fuzzing tests for pytest-hexaqueue test slicers and domain models.

Notes/Architectural Intent:
    Verifies algebraic and partition invariants across RoundRobinTestSlicer and
    FileContiguousTestSlicer using randomized Hypothesis test item inputs:
    - Partition completeness: union of all slice items equals original item set.
    - Partition disjointness: no test item is assigned to more than one slice.
    - Bounded slice count: exactly num_slices specs produced.
    - Structural validity: slice IDs and indices strictly within bounds.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pytest_hexaqueue.adapters.slicer import (
    FileContiguousTestSlicer,
    RoundRobinTestSlicer,
)
from pytest_hexaqueue.domain.slice import TestItemInfo, TestSliceSpec


@st.composite
def item_info_strategy(draw: st.DrawFn) -> TestItemInfo:
    """Generate synthetic TestItemInfo with randomized file path and nodeid."""
    idx = draw(st.integers(min_value=0, max_value=100000))
    duration = draw(
        st.floats(min_value=0.01, max_value=60.0, allow_nan=False, allow_infinity=False)
    )
    file_path = f"tests/unit/test_module_{idx % 20}.py"
    nodeid = f"{file_path}::test_case_{idx}"
    return TestItemInfo(
        nodeid=nodeid,
        file_path=file_path,
        estimated_duration=round(duration, 3),
    )


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(
    st.lists(
        item_info_strategy(), min_size=0, max_size=100, unique_by=lambda x: x.nodeid
    ),
    st.integers(min_value=1, max_value=16),
)
def test_round_robin_slicer_invariants(
    items: list[TestItemInfo], num_slices: int
) -> None:
    """Verify round-robin test slicer preserves completeness and disjointness invariants."""
    slicer = RoundRobinTestSlicer()
    slices: list[TestSliceSpec] = slicer.slice_items(items, num_slices=num_slices)

    slice_count = len(slices)
    assert slice_count == num_slices

    seen_nodeids: list[str] = []
    for s in slices:
        assert s.total_slices == num_slices
        assert 0 <= s.slice_index < num_slices
        seen_nodeids.extend(s.test_nodeids)

    # Invariant 1: Completeness - all input items are accounted for
    orig_nodeids = {i.nodeid for i in items}
    reconstructed_nodeids = set(seen_nodeids)
    assert reconstructed_nodeids == orig_nodeids

    # Invariant 2: Disjointness - zero duplicate assignments across slices
    seen_len = len(seen_nodeids)
    items_len = len(items)
    assert seen_len == items_len


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(
    st.lists(
        item_info_strategy(), min_size=0, max_size=100, unique_by=lambda x: x.nodeid
    ),
    st.integers(min_value=1, max_value=16),
)
def test_file_contiguous_slicer_invariants(
    items: list[TestItemInfo], num_slices: int
) -> None:
    """Verify file-contiguous test slicer preserves completeness and disjointness invariants."""
    slicer = FileContiguousTestSlicer()
    slices: list[TestSliceSpec] = slicer.slice_items(items, num_slices=num_slices)

    slice_count = len(slices)
    assert slice_count == num_slices

    seen_nodeids: list[str] = []
    for s in slices:
        assert s.total_slices == num_slices
        assert 0 <= s.slice_index < num_slices
        seen_nodeids.extend(s.test_nodeids)

    # Invariant 1: Completeness
    orig_nodeids = {i.nodeid for i in items}
    reconstructed_nodeids = set(seen_nodeids)
    assert reconstructed_nodeids == orig_nodeids

    # Invariant 2: Disjointness
    seen_len = len(seen_nodeids)
    items_len = len(items)
    assert seen_len == items_len
