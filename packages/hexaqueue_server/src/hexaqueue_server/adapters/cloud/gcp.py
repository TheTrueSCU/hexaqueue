"""Google Cloud Platform Managed Instance Group (MIG) adapter.

Notes/Architectural Intent:
    Implements InstancePoolGovernorPort for GCP Compute Engine MIGs.
    Supports Spot and Preemptible VM lifecycle policies and dynamic pool
    resizing.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import (
    InstancePoolState,
    PoolScaleRequest,
    PoolScaleResult,
)
from hexaqueue_core.ports.pool import InstancePoolGovernorPort


class GcpManagedInstanceGroupAdapter(InstancePoolGovernorPort):
    """Adapter for governing GCP Managed Instance Groups (MIGs)."""

    def __init__(
        self,
        compute_client: Any = None,
        project: str = "default-project",
        zone: str = "us-central1-a",
    ) -> None:
        """Initialize GCP MIG adapter.

        Args:
            compute_client: Injected GCP compute client or mock.
            project: GCP project identifier.
            zone: Default GCP compute zone.

        Notes/Architectural Intent:
            Hermetically testable through client injection without external Google Cloud dependencies.
        """
        self._client = compute_client
        self._project = project
        self._zone = zone
        self._local_pools: dict[str, InstancePoolState] = {}

    def register_mock_pool(self, pool: InstancePoolState) -> None:
        """Register a pool in the in-memory store for hermetic testing.

        Args:
            pool: Initial InstancePoolState snapshot.
        """
        self._local_pools[pool.pool_id] = pool

    async def get_pool_state(self, pool_id: str) -> InstancePoolState:
        """Query real-time MIG capacity and instance count.

        Args:
            pool_id: Name of the Managed Instance Group.

        Returns:
            InstancePoolState containing current capacity.

        Raises:
            HexaqueueError: If MIG cannot be found.
        """
        if self._client is not None:
            try:
                mig = self._client.get(
                    project=self._project,
                    zone=self._zone,
                    instance_group_manager=pool_id,
                )
                target_size = getattr(mig, "target_size", 0)
                current_size = getattr(mig, "current_actions", {})
                none_count = getattr(current_size, "none", target_size)
                return InstancePoolState(
                    pool_id=pool_id,
                    provider=CspProvider.GCP,
                    min_nodes=0,
                    max_nodes=100,
                    desired_nodes=target_size,
                    current_nodes=target_size,
                    ready_nodes=none_count,
                    spot_nodes=target_size,
                    updated_at=datetime.now(UTC),
                )
            except Exception as err:
                msg = f"Failed to get GCP MIG '{pool_id}': {err}"
                raise HexaqueueError(msg) from err

        if pool_id not in self._local_pools:
            msg = f"GCP MIG '{pool_id}' not found in registered pools"
            raise HexaqueueError(msg)
        return self._local_pools[pool_id]

    async def list_pools(self) -> Sequence[InstancePoolState]:
        """List all managed GCP MIGs.

        Returns:
            Sequence of InstancePoolState descriptors.

        Raises:
            HexaqueueError: If GCP API fails.
        """
        if self._client is not None:
            try:
                migs = self._client.list(project=self._project, zone=self._zone)
                results: list[InstancePoolState] = []
                for mig in migs:
                    name = getattr(mig, "name", "")
                    size = getattr(mig, "target_size", 0)
                    results.append(
                        InstancePoolState(
                            pool_id=name,
                            provider=CspProvider.GCP,
                            min_nodes=0,
                            max_nodes=100,
                            desired_nodes=size,
                            current_nodes=size,
                            ready_nodes=size,
                            updated_at=datetime.now(UTC),
                        )
                    )
                return results
            except Exception as err:
                msg = f"Failed to list GCP MIGs: {err}"
                raise HexaqueueError(msg) from err

        return list(self._local_pools.values())

    async def scale_pool(self, request: PoolScaleRequest) -> PoolScaleResult:
        """Resize GCP MIG target size.

        Args:
            request: PoolScaleRequest with target capacity and scaling reason.

        Returns:
            PoolScaleResult indicating resize outcome.

        Raises:
            HexaqueueError: If resize operation fails.
        """
        prev_nodes = 0
        if self._client is not None:
            try:
                current_state = await self.get_pool_state(request.pool_id)
                prev_nodes = current_state.current_nodes
                self._client.resize(
                    project=self._project,
                    zone=self._zone,
                    instance_group_manager=request.pool_id,
                    size=request.target_nodes,
                )
                return PoolScaleResult(
                    pool_id=request.pool_id,
                    previous_nodes=prev_nodes,
                    target_nodes=request.target_nodes,
                    success=True,
                    message=f"GCP MIG resized to {request.target_nodes}",
                )
            except Exception as err:
                msg = f"Failed to resize GCP MIG '{request.pool_id}': {err}"
                raise HexaqueueError(msg) from err

        if request.pool_id not in self._local_pools:
            msg = f"GCP MIG '{request.pool_id}' not found"
            raise HexaqueueError(msg)

        prev = self._local_pools[request.pool_id].current_nodes
        updated = self._local_pools[request.pool_id].model_copy(
            update={
                "desired_nodes": request.target_nodes,
                "current_nodes": request.target_nodes,
                "ready_nodes": request.target_nodes,
                "updated_at": datetime.now(UTC),
            }
        )
        self._local_pools[request.pool_id] = updated
        return PoolScaleResult(
            pool_id=request.pool_id,
            previous_nodes=prev,
            target_nodes=request.target_nodes,
            success=True,
            message="GCP MIG resized successfully",
        )
