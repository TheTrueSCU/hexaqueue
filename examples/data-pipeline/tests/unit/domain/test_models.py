"""Tests for domain models."""

import pytest

from data_pipeline.domain.models import DataRecord, SummaryResult


def test_data_record() -> None:
    """Verify DataRecord instantiation and validation."""
    record = DataRecord(id=1, val=10.5)
    assert record.id == 1
    assert record.val == 10.5

    with pytest.raises(ValueError):
        DataRecord(id=0, val=5.0)


def test_summary_result() -> None:
    """Verify SummaryResult validation."""
    res = SummaryResult(count=2, total=20.0, mean=10.0)
    assert res.count == 2
    assert res.mean == 10.0

    with pytest.raises(ValueError, match="does not match"):
        SummaryResult(count=2, total=20.0, mean=5.0)
