"""Unit tests for TestItemInfo, TestSliceSpec, and TestRunSession models."""

from pytest_hexaqueue.domain.slice import (
    TestItemInfo,
    TestRunSession,
    TestSliceSpec,
)


def test_test_item_info_model() -> None:
    """Test TestItemInfo properties and defaults."""
    item = TestItemInfo(
        nodeid="tests/unit/test_auth.py::test_login",
        file_path="tests/unit/test_auth.py",
        line_number=42,
        markers=["unit", "slow"],
        estimated_duration=2.5,
    )
    assert item.nodeid == "tests/unit/test_auth.py::test_login"
    assert item.file_path == "tests/unit/test_auth.py"
    assert item.line_number == 42
    assert "slow" in item.markers
    assert item.estimated_duration == 2.5


def test_test_slice_spec_model() -> None:
    """Test TestSliceSpec initialization and properties."""
    slice_spec = TestSliceSpec(
        slice_id="slice-0",
        slice_index=0,
        total_slices=4,
        test_nodeids=["t1", "t2", "t3"],
        total_estimated_duration=3.0,
    )
    assert slice_spec.slice_id == "slice-0"
    assert slice_spec.slice_index == 0
    assert slice_spec.total_slices == 4
    assert len(slice_spec.test_nodeids) == 3
    assert slice_spec.total_estimated_duration == 3.0


def test_test_run_session_model() -> None:
    """Test TestRunSession properties."""
    session = TestRunSession(
        session_id="run-12345",
        total_items=10,
        total_slices=2,
        server_url="http://cluster.internal:8000",
        pool="ci-runners",
        free_tier=True,
    )
    assert session.session_id == "run-12345"
    assert session.total_items == 10
    assert session.total_slices == 2
    assert session.free_tier is True
    assert session.pool == "ci-runners"
