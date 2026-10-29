"""AWS EC2 Auto Scaling Group adapter.

Notes/Architectural Intent:
    Implements InstancePoolGovernorPort for AWS Auto Scaling Groups (ASGs).
    Supports EC2 Fleet mixed instances with spot allocation strategies
    (price-capacity-optimized) and dynamic desired capacity scaling.
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


class AwsAutoScalingGroupAdapter(InstancePoolGovernorPort):
    """Adapter for governing AWS EC2 Auto Scaling Groups."""

    def __init__(
        self,
        boto_client: Any = None,
        default_spot_allocation_strategy: str = "price-capacity-optimized",
    ) -> None:
        """Initialize AWS ASG adapter with optional boto3 client.

        Args:
            boto_client: Injected AWS boto3 autoscaling client or mock.
            default_spot_allocation_strategy: EC2 Fleet spot allocation strategy.

        Notes/Architectural Intent:
            Accepts an optional client to permit dependency injection and hermetic
            testing without requiring AWS credentials or network access.
        """
        self._client = boto_client
        self._strategy = default_spot_allocation_strategy
        self._local_pools: dict[str, InstancePoolState] = {}

    def register_mock_pool(self, pool: InstancePoolState) -> None:
        """Register a pool in the in-memory store for hermetic testing or simulation.

        Args:
            pool: Initial InstancePoolState snapshot.
        """
        self._local_pools[pool.pool_id] = pool

    async def get_pool_state(self, pool_id: str) -> InstancePoolState:
        """Query real-time ASG capacity and spot metrics.

        Args:
            pool_id: Name or ARN of the Auto Scaling Group.

        Returns:
            InstancePoolState containing current capacity and spot allocations.

        Raises:
            HexaqueueError: If ASG cannot be found.
        """
        if self._client is not None:
            try:
                response = self._client.describe_auto_scaling_groups(
                    AutoScalingGroupNames=[pool_id]
                )
                groups = response.get("AutoScalingGroups", [])
                if not groups:
                    msg = f"AWS ASG '{pool_id}' not found"
                    raise HexaqueueError(msg)
                asg = groups[0]
                instances = asg.get("Instances", [])
                spot_count = sum(
                    1
                    for inst in instances
                    if inst.get("LifecycleState") == "InService"
                    and inst.get("InstanceType") is not None
                    and inst.get("LaunchTemplate", {}).get("LaunchTemplateId")
                    is not None
                )
                ready_count = sum(
                    1 for inst in instances if inst.get("LifecycleState") == "InService"
                )
                return InstancePoolState(
                    pool_id=pool_id,
                    provider=CspProvider.AWS,
                    min_nodes=asg.get("MinSize", 0),
                    max_nodes=asg.get("MaxSize", 10),
                    desired_nodes=asg.get("DesiredCapacity", 0),
                    current_nodes=len(instances),
                    ready_nodes=ready_count,
                    spot_nodes=spot_count,
                    capability_tags=frozenset(
                        tag.get("Key") for tag in asg.get("Tags", [])
                    ),
                    updated_at=datetime.now(UTC),
                )
            except Exception as err:
                if isinstance(err, HexaqueueError):
                    raise
                msg = f"Failed to describe AWS ASG '{pool_id}': {err}"
                raise HexaqueueError(msg) from err

        if pool_id not in self._local_pools:
            msg = f"AWS ASG '{pool_id}' not found in registered pools"
            raise HexaqueueError(msg)
        return self._local_pools[pool_id]

    async def list_pools(self) -> Sequence[InstancePoolState]:
        """List all managed AWS ASGs.

        Returns:
            Sequence of InstancePoolState descriptors.

        Raises:
            HexaqueueError: If AWS API fails.
        """
        if self._client is not None:
            try:
                response = self._client.describe_auto_scaling_groups()
                results: list[InstancePoolState] = []
                for asg in response.get("AutoScalingGroups", []):
                    name = asg.get("AutoScalingGroupName", "")
                    instances = asg.get("Instances", [])
                    ready = sum(
                        1
                        for inst in instances
                        if inst.get("LifecycleState") == "InService"
                    )
                    results.append(
                        InstancePoolState(
                            pool_id=name,
                            provider=CspProvider.AWS,
                            min_nodes=asg.get("MinSize", 0),
                            max_nodes=asg.get("MaxSize", 10),
                            desired_nodes=asg.get("DesiredCapacity", 0),
                            current_nodes=len(instances),
                            ready_nodes=ready,
                            capability_tags=frozenset(
                                tag.get("Key") for tag in asg.get("Tags", [])
                            ),
                            updated_at=datetime.now(UTC),
                        )
                    )
                return results
            except Exception as err:
                msg = f"Failed to list AWS ASGs: {err}"
                raise HexaqueueError(msg) from err

        return list(self._local_pools.values())

    async def scale_pool(self, request: PoolScaleRequest) -> PoolScaleResult:
        """Resize AWS ASG desired capacity.

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
                self._client.set_desired_capacity(
                    AutoScalingGroupName=request.pool_id,
                    DesiredCapacity=request.target_nodes,
                    HonorCooldown=False,
                )
                return PoolScaleResult(
                    pool_id=request.pool_id,
                    previous_nodes=prev_nodes,
                    target_nodes=request.target_nodes,
                    success=True,
                    message=f"AWS ASG desired capacity set to {request.target_nodes} ({self._strategy})",
                )
            except Exception as err:
                msg = f"Failed to scale AWS ASG '{request.pool_id}': {err}"
                raise HexaqueueError(msg) from err

        if request.pool_id not in self._local_pools:
            msg = f"AWS ASG '{request.pool_id}' not found"
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
            message="AWS ASG scaled successfully",
        )
