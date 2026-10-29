"""Instance pool governor port interface.

Notes/Architectural Intent:
    Defines the abstract driven port for querying capacity, desired node counts,
    active spot allocations, and applying elastic scale-out/scale-in operations
    to CSP instance pools (AWS ASG, GCP MIG, Azure VMSS).
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from hexaqueue_core.domain.pool import (
    InstancePoolState,
    PoolScaleRequest,
    PoolScaleResult,
)


class InstancePoolGovernorPort(ABC):
    """Abstract port interface for governing Cloud Service Provider instance pools."""

    @abstractmethod
    async def get_pool_state(self, pool_id: str) -> InstancePoolState:
        """Query the real-time operational state of a specific instance pool.

        Args:
            pool_id: Unique pool identifier.

        Returns:
            Current InstancePoolState snapshot.

        Raises:
            HexaqueueError: If the pool cannot be located or queried.
        """

    @abstractmethod
    async def list_pools(self) -> Sequence[InstancePoolState]:
        """List all managed instance pools governed by this adapter.

        Returns:
            Sequence of InstancePoolState descriptors.

        Raises:
            HexaqueueError: If provider API fails.
        """

    @abstractmethod
    async def scale_pool(self, request: PoolScaleRequest) -> PoolScaleResult:
        """Apply a capacity scaling operation to an instance pool.

        Args:
            request: PoolScaleRequest specifying target capacity and reasoning.

        Returns:
            PoolScaleResult indicating success and applied node counts.

        Raises:
            HexaqueueError: If the resizing call encounters a fatal provider error.
        """
