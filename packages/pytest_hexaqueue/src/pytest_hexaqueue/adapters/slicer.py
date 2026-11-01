"""Concrete test slicing adapters for distributing pytest items across execution slices.

Notes/Architectural Intent:
    Provides deterministic test partitioning algorithms: RoundRobinTestSlicer for
    uniform distribution and FileContiguousTestSlicer to preserve module fixture
    and setup locality.
"""

from collections import defaultdict

from pytest_hexaqueue.domain.slice import TestItemInfo, TestSliceSpec
from pytest_hexaqueue.ports.slicer import TestSlicerPort


class RoundRobinTestSlicer(TestSlicerPort):
    """Partitions test items evenly across slices using round-robin distribution.

    Notes/Architectural Intent:
        Guarantees that test counts per slice differ by at most 1, achieving
        near-optimal load balance for uniform duration test suites.
    """

    __test__ = False

    def slice_items(
        self, items: list[TestItemInfo], num_slices: int
    ) -> list[TestSliceSpec]:
        """Distribute test items cyclically across slices.

        Args:
            items: List of collected TestItemInfo instances.
            num_slices: Number of slices to generate.

        Returns:
            List of partitioned TestSliceSpec instances.

        Raises:
            ValueError: If num_slices is less than 1.
        """
        if num_slices < 1:
            msg = f"num_slices must be >= 1, got {num_slices}"
            raise ValueError(msg)

        nodeid_buckets: list[list[str]] = [[] for _ in range(num_slices)]
        duration_buckets: list[float] = [0.0 for _ in range(num_slices)]

        for i, item in enumerate(items):
            bucket_idx = i % num_slices
            nodeid_buckets[bucket_idx].append(item.nodeid)
            duration_buckets[bucket_idx] += item.estimated_duration

        return [
            TestSliceSpec(
                slice_id=f"slice-{idx}",
                slice_index=idx,
                test_nodeids=nodeid_buckets[idx],
                total_estimated_duration=round(duration_buckets[idx], 2),
                total_slices=num_slices,
            )
            for idx in range(num_slices)
        ]


class FileContiguousTestSlicer(TestSlicerPort):
    """Partitions test items grouping by test module to preserve fixture locality.

    Notes/Architectural Intent:
        Groups all test functions from the same test file into the same slice
        whenever possible, avoiding repeated module imports and costly module-scoped
        or session-scoped fixture initializations across multiple worker nodes.
    """

    __test__ = False

    def slice_items(
        self, items: list[TestItemInfo], num_slices: int
    ) -> list[TestSliceSpec]:
        """Group test items by file into balanced slices.

        Args:
            items: List of collected TestItemInfo instances.
            num_slices: Number of slices to generate.

        Returns:
            List of partitioned TestSliceSpec instances.

        Raises:
            ValueError: If num_slices is less than 1.
        """
        if num_slices < 1:
            msg = f"num_slices must be >= 1, got {num_slices}"
            raise ValueError(msg)

        # Group items by file path
        by_file: dict[str, list[TestItemInfo]] = defaultdict(list)
        for item in items:
            by_file[item.file_path].append(item)

        nodeid_buckets: list[list[str]] = [[] for _ in range(num_slices)]
        duration_buckets: list[float] = [0.0 for _ in range(num_slices)]

        # Greedy bin-packing of file groups by count/duration
        for _file_path, file_items in sorted(
            by_file.items(), key=lambda x: len(x[1]), reverse=True
        ):
            # Select bucket with minimal assigned duration
            min_idx = duration_buckets.index(min(duration_buckets))
            for item in file_items:
                nodeid_buckets[min_idx].append(item.nodeid)
                duration_buckets[min_idx] += item.estimated_duration

        return [
            TestSliceSpec(
                slice_id=f"slice-{idx}",
                slice_index=idx,
                test_nodeids=nodeid_buckets[idx],
                total_estimated_duration=round(duration_buckets[idx], 2),
                total_slices=num_slices,
            )
            for idx in range(num_slices)
        ]


__all__ = [
    "FileContiguousTestSlicer",
    "RoundRobinTestSlicer",
]
