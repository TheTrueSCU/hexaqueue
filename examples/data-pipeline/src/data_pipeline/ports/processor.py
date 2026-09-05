"""Port interface for data batch processing."""

from abc import ABC, abstractmethod

from data_pipeline.domain.models import DataRecord, SummaryResult


class DataProcessorPort(ABC):
    """Abstract processor interface for data operations."""

    @abstractmethod
    def compute_summary(self, records: list[DataRecord]) -> SummaryResult:
        """Compute aggregate summary from records."""

    @abstractmethod
    def compute_squares(self, records: list[DataRecord]) -> list[float]:
        """Compute square features."""


__all__ = [
    "DataProcessorPort",
]
