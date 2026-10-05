"""Local memory data processor adapter."""

from data_pipeline.domain.models import DataRecord, SummaryResult
from data_pipeline.ports.processor import DataProcessorPort


class LocalDataProcessorAdapter(DataProcessorPort):
    """In-memory data processor implementation."""

    def compute_summary(self, records: list[DataRecord]) -> SummaryResult:
        """Compute aggregate summary from records."""
        if not records:
            return SummaryResult(total=0.0, count=0, mean=0.0)
        total = sum(r.val for r in records)
        count = len(records)
        return SummaryResult(total=total, count=count, mean=total / count)

    def compute_squares(self, records: list[DataRecord]) -> list[float]:
        """Compute square features."""
        return [r.val**2 for r in records]


__all__ = [
    "LocalDataProcessorAdapter",
]
