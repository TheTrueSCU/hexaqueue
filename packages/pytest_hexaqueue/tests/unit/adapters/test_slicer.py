"""Unit and property tests for slicing adapters."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pytest_hexaqueue.adapters.slicer import (
    FileContiguousTestSlicer,
    RoundRobinTestSlicer,
)
from pytest_hexaqueue.domain.slice import TestItemInfo


def test_round_robin_slicer_basic() -> None:
    """Test round-robin partitioning with exact division."""
    items = [
        TestItemInfo(nodeid=f"t{i}", file_path=f"test_{i}.py", estimated_duration=1.0)
        for i in range(10)
    ]
    slicer = RoundRobinTestSlicer()
    slices = slicer.slice_items(items, num_slices=2)

    assert len(slices) == 2
    assert len(slices[0].test_nodeids) == 5
    assert len(slices[1].test_nodeids) == 5
    assert slices[0].test_nodeids == ["t0", "t2", "t4", "t6", "t8"]
    assert slices[1].test_nodeids == ["t1", "t3", "t5", "t7", "t9"]


def test_round_robin_slicer_invalid_slices() -> None:
    """Test slicing with invalid slice count."""
    slicer = RoundRobinTestSlicer()
    with pytest.raises(ValueError, match="num_slices must be >= 1"):
        slicer.slice_items([], num_slices=0)


def test_file_contiguous_slicer() -> None:
    """Test file-contiguous grouping partitions files cleanly."""
    items = [
        TestItemInfo(nodeid="fileA::t1", file_path="test_a.py", estimated_duration=1.0),
        TestItemInfo(nodeid="fileA::t2", file_path="test_a.py", estimated_duration=1.0),
        TestItemInfo(nodeid="fileB::t1", file_path="test_b.py", estimated_duration=1.0),
        TestItemInfo(nodeid="fileB::t2", file_path="test_b.py", estimated_duration=1.0),
    ]
    slicer = FileContiguousTestSlicer()
    slices = slicer.slice_items(items, num_slices=2)

    assert len(slices) == 2
    # Both items from fileA should be together
    assert slices[0].test_nodeids == ["fileA::t1", "fileA::t2"]
    assert slices[1].test_nodeids == ["fileB::t1", "fileB::t2"]


def test_file_contiguous_slicer_invalid_slices() -> None:
    """Test file contiguous slicer with invalid slice count."""
    slicer = FileContiguousTestSlicer()
    with pytest.raises(ValueError, match="num_slices must be >= 1"):
        slicer.slice_items([], num_slices=-1)


@given(
    num_items=st.integers(min_value=0, max_value=50),
    num_slices=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=30)
def test_round_robin_preserves_item_count_property(
    num_items: int, num_slices: int
) -> None:
    """Property test: sum of tests across slices strictly equals collected count."""
    items = [
        TestItemInfo(nodeid=f"test_{i}", file_path="test_f.py")
        for i in range(num_items)
    ]
    slicer = RoundRobinTestSlicer()
    slices = slicer.slice_items(items, num_slices=num_slices)

    assert len(slices) == num_slices
    total_assigned = sum(len(s.test_nodeids) for s in slices)
    assert total_assigned == num_items
