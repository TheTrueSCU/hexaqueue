"""Shared pytest fixtures for hexaqueue_server unit tests.

Notes/Architectural Intent:
    Centralizes reusable in-memory governors, strict SDK stubs, and async
    coalescing doubles so unit tests stay concise without embedding mock classes.
"""

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from hexaqueue_core.domain.pool import (
    InstancePoolState,
    PoolScaleRequest,
    PoolScaleResult,
)
from hexaqueue_core.ports.pool import InstancePoolGovernorPort


class MultiPoolMockGovernor(InstancePoolGovernorPort):
    """Reusable in-memory multi-pool governor with call tracking and fault injection.

    Args:
        pools: Mutable map of pool ID to initial InstancePoolState.
        available_map: Map of pool ID to pre-flight capacity probe booleans.
        fail_pools: Optional map of pool ID to exception raised in ``get_pool_state``.

    Notes/Architectural Intent:
        Replaces inline test stub classes across autoscaler and coordinator unit
        tests while maintaining strict InstancePoolGovernorPort conformance.
    """

    def __init__(
        self,
        pools: dict[str, InstancePoolState],
        available_map: dict[str, bool],
        fail_pools: dict[str, Exception] | None = None,
    ) -> None:
        self.pools = pools
        self.available_map = available_map
        self.fail_pools = fail_pools or {}
        self.scale_calls: list[PoolScaleRequest] = []
        self.state_calls: dict[str, int] = {}

    async def get_pool_state(self, pool_id: str) -> InstancePoolState:
        """Return pool state snapshot and increment per-pool telemetry counter.

        Args:
            pool_id: Target pool identifier.

        Returns:
            Current InstancePoolState snapshot.

        Raises:
            Exception: Configured fault exception when ``pool_id`` is in ``fail_pools``.
        """
        self.state_calls[pool_id] = self.state_calls.get(pool_id, 0) + 1
        if pool_id in self.fail_pools:
            raise self.fail_pools[pool_id]
        return self.pools[pool_id]

    async def list_pools(self) -> list[InstancePoolState]:
        """Return all registered mock pool states."""
        return list(self.pools.values())

    async def scale_pool(self, request: PoolScaleRequest) -> PoolScaleResult:
        """Apply scaling target to in-memory pool state and record request."""
        self.scale_calls.append(request)
        prev = self.pools[request.pool_id].current_nodes
        self.pools[request.pool_id] = self.pools[request.pool_id].model_copy(
            update={
                "desired_nodes": request.target_nodes,
                "current_nodes": request.target_nodes,
                "ready_nodes": request.target_nodes,
            }
        )
        return PoolScaleResult(
            pool_id=request.pool_id,
            previous_nodes=prev,
            target_nodes=request.target_nodes,
            success=True,
            message="ok",
        )

    async def check_pool_capacity(self, pool_id: str) -> bool:
        """Return configured pre-flight host availability verdict."""
        return self.available_map.get(pool_id, True)


@pytest.fixture
def multi_pool_governor_factory() -> Callable[..., MultiPoolMockGovernor]:
    """Provide a factory fixture constructing MultiPoolMockGovernor instances.

    Returns:
        Callable constructing a configured MultiPoolMockGovernor.
    """

    def _build(
        pools: dict[str, InstancePoolState],
        available_map: dict[str, bool],
        fail_pools: dict[str, Exception] | None = None,
    ) -> MultiPoolMockGovernor:
        return MultiPoolMockGovernor(
            pools=pools,
            available_map=available_map,
            fail_pools=fail_pools,
        )

    return _build


@pytest.fixture
def strict_oci_capacity_sdk() -> SimpleNamespace:
    """Provide a strict OCI SDK stub exposing exact Compute capacity report models.

    Returns:
        SimpleNamespace mirroring ``oci.core.models`` without legacy typo classes.
    """

    def _shape_cfg(*, ocpus: float, memory_in_gbs: float) -> SimpleNamespace:
        return SimpleNamespace(ocpus=ocpus, memory_in_gbs=memory_in_gbs)

    def _shape_avail(
        *, instance_shape: str, instance_shape_config: Any
    ) -> SimpleNamespace:
        return SimpleNamespace(
            instance_shape=instance_shape,
            instance_shape_config=instance_shape_config,
        )

    def _report_details(
        *,
        compartment_id: str,
        availability_domain: str,
        shape_availabilities: list[Any],
    ) -> SimpleNamespace:
        return SimpleNamespace(
            compartment_id=compartment_id,
            availability_domain=availability_domain,
            shape_availabilities=shape_availabilities,
        )

    models = SimpleNamespace(
        CapacityReportInstanceShapeConfig=_shape_cfg,
        CreateCapacityReportShapeAvailabilityDetails=_shape_avail,
        CreateComputeCapacityReportDetails=_report_details,
    )
    return SimpleNamespace(core=SimpleNamespace(models=models))


@pytest.fixture
def coalescing_autoscaler() -> SimpleNamespace:
    """Provide an autoscaler double tracking concurrent reconciliation overlap.

    Returns:
        SimpleNamespace with ``autoscaler``, ``release_first``, and ``stats`` fields.
    """
    stats: dict[str, int] = {"in_flight": 0, "max_in_flight": 0, "call_count": 0}
    release_first = asyncio.Event()

    async def _reconcile_pool(
        pool_id: str,
        pending_jobs: int,
        running_jobs: int = 0,
    ) -> MagicMock:
        _ = (pool_id, pending_jobs, running_jobs)
        stats["in_flight"] += 1
        stats["max_in_flight"] = max(stats["max_in_flight"], stats["in_flight"])
        stats["call_count"] += 1
        if stats["call_count"] == 1:
            await release_first.wait()
        stats["in_flight"] -= 1
        return MagicMock(action="NOOP", target_nodes=0, reason="ok")

    autoscaler = MagicMock()
    autoscaler.reconcile_pool = AsyncMock(side_effect=_reconcile_pool)
    return SimpleNamespace(
        autoscaler=autoscaler,
        release_first=release_first,
        stats=stats,
    )
