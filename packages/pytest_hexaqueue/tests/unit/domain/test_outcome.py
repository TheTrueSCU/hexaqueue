"""Unit tests for TestOutcomeItem and SliceOutcomeReport."""

from pytest_hexaqueue.domain.outcome import (
    SliceOutcomeReport,
    TestOutcomeItem,
)


def test_test_outcome_item() -> None:
    """Test TestOutcomeItem creation and properties."""
    item = TestOutcomeItem(
        nodeid="tests/unit/test_math.py::test_add",
        outcome="passed",
        duration_seconds=0.015,
        stdout="Calculated sum = 4",
    )
    assert item.nodeid == "tests/unit/test_math.py::test_add"
    assert item.outcome == "passed"
    assert item.duration_seconds == 0.015
    assert item.stdout == "Calculated sum = 4"
    assert item.stderr is None


def test_slice_outcome_report_counts_and_success() -> None:
    """Test SliceOutcomeReport aggregations and success determination."""
    report = SliceOutcomeReport(
        slice_id="slice-0",
        slice_index=0,
        worker_id="worker-oci-0",
        provider="OCI",
        is_free_tier=True,
        outcomes=[
            TestOutcomeItem(nodeid="t1", outcome="passed", duration_seconds=0.1),
            TestOutcomeItem(nodeid="t2", outcome="passed", duration_seconds=0.2),
            TestOutcomeItem(nodeid="t3", outcome="skipped", duration_seconds=0.0),
        ],
        duration_seconds=0.3,
    )
    assert report.slice_id == "slice-0"
    assert report.passed_count == 2
    assert report.failed_count == 0
    assert report.skipped_count == 1
    assert report.is_success is True
    assert report.is_free_tier is True
    assert report.provider == "OCI"


def test_slice_outcome_report_failure() -> None:
    """Test SliceOutcomeReport with failures."""
    report = SliceOutcomeReport(
        slice_id="slice-1",
        slice_index=1,
        outcomes=[
            TestOutcomeItem(nodeid="t1", outcome="passed"),
            TestOutcomeItem(nodeid="t2", outcome="failed", longrepr="assert 1 == 2"),
        ],
    )
    assert report.failed_count == 1
    assert report.passed_count == 1
    assert report.is_success is False
