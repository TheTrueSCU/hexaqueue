"""Azure Virtual Machine Scale Set (VMSS) adapter.

Notes/Architectural Intent:
    Implements InstancePoolGovernorPort for Azure VMSS instances.
    Supports Azure Spot priority instances, eviction policies,
    and elastic capacity scaling.
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


class AzureScaleSetAdapter(InstancePoolGovernorPort):
    """Adapter for governing Azure Virtual Machine Scale Sets (VMSS)."""

    def __init__(
        self,
        azure_client: Any = None,
        resource_group: str = "default-rg",
    ) -> None:
        """Initialize Azure Scale Set adapter.

        Args:
            azure_client: Injected Azure compute management client or mock.
            resource_group: Target Azure resource group name.

        Notes/Architectural Intent:
            Hermetically testable through client injection without live Azure subscriptions.
        """
        self._client = azure_client
        self._resource_group = resource_group
        self._local_pools: dict[str, InstancePoolState] = {}

    def register_mock_pool(self, pool: InstancePoolState) -> None:
        """Register a pool in the in-memory store for hermetic testing.

        Args:
            pool: Initial InstancePoolState snapshot.
        """
        self._local_pools[pool.pool_id] = pool

    async def get_pool_state(self, pool_id: str) -> InstancePoolState:
        """Query real-time VMSS capacity and configuration.

        Args:
            pool_id: Name of the Virtual Machine Scale Set.

        Returns:
            InstancePoolState containing current capacity.

        Raises:
            HexaqueueError: If VMSS cannot be found.
        """
        if self._client is not None:
            try:
                vmss = self._client.virtual_machine_scale_sets.get(
                    resource_group_name=self._resource_group,
                    vm_scale_set_name=pool_id,
                )
                sku = getattr(vmss, "sku", None)
                capacity = getattr(sku, "capacity", 0) if sku else 0
                return InstancePoolState(
                    pool_id=pool_id,
                    provider=CspProvider.AZURE,
                    min_nodes=0,
                    max_nodes=100,
                    desired_nodes=capacity,
                    current_nodes=capacity,
                    ready_nodes=capacity,
                    spot_nodes=capacity,
                    updated_at=datetime.now(UTC),
                )
            except Exception as err:
                msg = f"Failed to get Azure VMSS '{pool_id}': {err}"
                raise HexaqueueError(msg) from err

        if pool_id not in self._local_pools:
            msg = f"Azure VMSS '{pool_id}' not found in registered pools"
            raise HexaqueueError(msg)
        return self._local_pools[pool_id]

    async def list_pools(self) -> Sequence[InstancePoolState]:
        """List all managed Azure VMSS pools.

        Returns:
            Sequence of InstancePoolState descriptors.

        Raises:
            HexaqueueError: If Azure API fails.
        """
        if self._client is not None:
            try:
                vmsses = self._client.virtual_machine_scale_sets.list(
                    resource_group_name=self._resource_group
                )
                results: list[InstancePoolState] = []
                for vmss in vmsses:
                    name = getattr(vmss, "name", "")
                    sku = getattr(vmss, "sku", None)
                    cap = getattr(sku, "capacity", 0) if sku else 0
                    results.append(
                        InstancePoolState(
                            pool_id=name,
                            provider=CspProvider.AZURE,
                            min_nodes=0,
                            max_nodes=100,
                            desired_nodes=cap,
                            current_nodes=cap,
                            ready_nodes=cap,
                            updated_at=datetime.now(UTC),
                        )
                    )
                return results
            except Exception as err:
                msg = f"Failed to list Azure VMSS pools: {err}"
                raise HexaqueueError(msg) from err

        return list(self._local_pools.values())

    async def scale_pool(self, request: PoolScaleRequest) -> PoolScaleResult:
        """Resize Azure VMSS capacity.

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
                # Create SKU update payload
                sku_patch = {"sku": {"capacity": request.target_nodes}}
                self._client.virtual_machine_scale_sets.begin_update(
                    resource_group_name=self._resource_group,
                    vm_scale_set_name=request.pool_id,
                    parameters=sku_patch,
                )
                return PoolScaleResult(
                    pool_id=request.pool_id,
                    previous_nodes=prev_nodes,
                    target_nodes=request.target_nodes,
                    success=True,
                    message=f"Azure VMSS capacity scaled to {request.target_nodes}",
                )
            except Exception as err:
                msg = f"Failed to scale Azure VMSS '{request.pool_id}': {err}"
                raise HexaqueueError(msg) from err

        if request.pool_id not in self._local_pools:
            msg = f"Azure VMSS '{request.pool_id}' not found"
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
            message="Azure VMSS scaled successfully",
        )
