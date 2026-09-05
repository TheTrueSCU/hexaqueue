"""Tests for processor port."""

from data_pipeline.domain.models import DataRecord, SummaryResult
from data_pipeline.ports.processor import DataProcessorPort


class DummyProcessor(DataProcessorPort):
    def compute_summary(self, records: list[DataRecord]) -> SummaryResult:
        return SummaryResult(total=0.0, count=0, mean=0.0)

    def compute_squares(self, records: list[DataRecord]) -> list[float]:
        return []


def test_dummy_processor() -> None:
    proc = DummyProcessor()
    assert isinstance(proc, DataProcessorPort)
