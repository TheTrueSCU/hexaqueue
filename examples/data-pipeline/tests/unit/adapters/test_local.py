"""Tests for LocalDataProcessorAdapter."""

from data_pipeline.adapters.local import LocalDataProcessorAdapter
from data_pipeline.domain.models import DataRecord


def test_local_processor() -> None:
    """Verify local processor operations."""
    proc = LocalDataProcessorAdapter()
    records = [DataRecord(id=1, val=10.0), DataRecord(id=2, val=20.0)]

    summary = proc.compute_summary(records)
    assert summary.count == 2
    assert summary.total == 30.0
    assert summary.mean == 15.0

    empty_summary = proc.compute_summary([])
    assert empty_summary.count == 0

    squares = proc.compute_squares(records)
    assert squares == [100.0, 400.0]
