"""Abstract port interface for test suite slicing and partitioning algorithms.

Notes/Architectural Intent:
    Defines the contract for partitioning collected pytest items into balanced
    execution slices, allowing interchangeable strategies (round-robin, contiguous file,
    duration bin-packing).
"""

from abc import ABC, abstractmethod

from pytest_hexaqueue.domain.slice import TestItemInfo, TestSliceSpec


class TestSlicerPort(ABC):
    """Abstract port for test slicing and partition algorithms."""

    __test__ = False

    @abstractmethod
    def slice_items(
        self, items: list[TestItemInfo], num_slices: int
    ) -> list[TestSliceSpec]:
        """Partition collected test items into target number of execution slices.

        Args:
            items: List of collected TestItemInfo instances.
            num_slices: Number of execution slices to generate.

        Returns:
            List of TestSliceSpec instances.

        Raises:
            ValueError: If num_slices is less than 1.
        """


__all__ = [
    "TestSlicerPort",
]
