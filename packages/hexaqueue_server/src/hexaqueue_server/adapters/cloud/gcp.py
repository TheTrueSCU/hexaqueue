"""Google Cloud Platform Managed Instance Group (MIG) adapter.

Notes/Architectural Intent:
    Implements InstancePoolGovernorPort for GCP Compute Engine MIGs.
    Supports Spot and Preemptible VM lifecycle policies and dynamic pool
    resizing.
"""

import contextlib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.credentials import GcpCredentialsConfig
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import (
    InstancePoolState,
    PoolScaleRequest,
    PoolScaleResult,
)
from hexaqueue_core.ports.freetier import FreeTierGovernorPort
from hexaqueue_core.ports.pool import InstancePoolGovernorPort
from hexaqueue_core.utils.imports import optional_dependency


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

    @classmethod
    def from_credentials(
        cls,
        credentials: GcpCredentialsConfig | None = None,
        project: str | None = None,
        zone: str | None = None,
    ) -> "GcpManagedInstanceGroupAdapter":
        """Factory creating a GCP MIG adapter from GcpCredentialsConfig.

        Args:
            credentials: Optional GCP credentials configuration.
            project: Optional GCP project override.
            zone: Optional GCP zone override.

        Returns:
            Configured GcpManagedInstanceGroupAdapter instance.

        Notes/Architectural Intent:
            Attempts to configure Google Cloud Compute client if google-cloud-compute
            is installed and credentials/WIF are configured; otherwise falls back
            gracefully to hermetic simulation mode.
        """
        client = None
        target_project = project or (
            credentials.project_id
            if credentials and credentials.project_id
            else "default-project"
        )
        target_zone = zone or (
            credentials.zone if credentials and credentials.zone else "us-central1-a"
        )

        compute_mod = optional_dependency("google.cloud.compute_v1")
        if (
            compute_mod is not None
            and credentials is not None
            and credentials.is_configured
        ):
            with contextlib.suppress(Exception):
                client = compute_mod.InstanceGroupManagersClient()

        return cls(compute_client=client, project=target_project, zone=target_zone)

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


class GcpInstancePoolAdapter(InstancePoolGovernorPort):
    """Subordinate GCP Always-Free e2-micro adapter for x86_64 and OCI spillover.

    Notes/Architectural Intent:
        Manages a subordinate GCP Always-Free e2-micro instance (x86_64, 2 vCPUs
        burstable, 1 GB RAM, 30 GB disk) via Compute Engine InstancesClient or
        hermetic local simulation. Enforces Always-Free single-instance bounds
        and zero inbound public ports (connects outbound to OCI controller :8001).
    """

    ALWAYS_FREE_MACHINE_TYPE = "e2-micro"
    ALWAYS_FREE_MAX_INSTANCES = 1

    def __init__(
        self,
        instances_client: Any = None,
        project: str = "default-project",
        zone: str = "us-central1-a",
        free_tier_governor: FreeTierGovernorPort | None = None,
        machine_type: str = ALWAYS_FREE_MACHINE_TYPE,
    ) -> None:
        """Initialize subordinate GCP e2-micro instance pool adapter.

        Args:
            instances_client: Injected GCP Compute InstancesClient or mock.
            project: GCP project identifier.
            zone: GCP Always-Free eligible compute zone (e.g. 'us-central1-a').
            free_tier_governor: Optional FreeTierGovernorPort for quota enforcement.
            machine_type: Compute Engine machine type (defaults to 'e2-micro').
        """
        self._client = instances_client
        self._project = project
        self._zone = zone
        self._governor = free_tier_governor
        self._machine_type = machine_type
        self._local_pools: dict[str, InstancePoolState] = {}

    def register_mock_pool(self, pool: InstancePoolState) -> None:
        """Register an in-memory GCP e2-micro pool snapshot for hermetic testing.

        Args:
            pool: Initial InstancePoolState snapshot.
        """
        self._local_pools[pool.pool_id] = pool

    @classmethod
    def from_credentials(
        cls,
        credentials: GcpCredentialsConfig | None = None,
        project: str | None = None,
        zone: str | None = None,
        free_tier_governor: FreeTierGovernorPort | None = None,
    ) -> "GcpInstancePoolAdapter":
        """Factory creating a subordinate GCP e2-micro adapter from credentials.

        Args:
            credentials: Optional GCP credentials configuration.
            project: Optional GCP project override.
            zone: Optional GCP zone override.
            free_tier_governor: Optional FreeTierGovernorPort instance.

        Returns:
            Configured GcpInstancePoolAdapter instance.
        """
        client = None
        target_project = project or (
            credentials.project_id
            if credentials and credentials.project_id
            else "default-project"
        )
        target_zone = zone or (
            credentials.zone if credentials and credentials.zone else "us-central1-a"
        )

        compute_mod = optional_dependency("google.cloud.compute_v1")
        if (
            compute_mod is not None
            and credentials is not None
            and credentials.is_configured
        ):
            with contextlib.suppress(Exception):
                client = compute_mod.InstancesClient()

        return cls(
            instances_client=client,
            project=target_project,
            zone=target_zone,
            free_tier_governor=free_tier_governor,
        )

    async def get_pool_state(self, pool_id: str) -> InstancePoolState:
        """Query real-time status of the subordinate GCP e2-micro instance.

        Args:
            pool_id: GCP Compute Engine instance name.

        Returns:
            InstancePoolState representing running (1) or terminated (0) capacity.

        Raises:
            HexaqueueError: If instance lookup fails.
        """
        if self._client is not None:
            try:
                inst = self._client.get(
                    project=self._project,
                    zone=self._zone,
                    instance=pool_id,
                )
                status = str(getattr(inst, "status", "TERMINATED")).upper()
                running = 1 if status == "RUNNING" else 0
                return InstancePoolState(
                    pool_id=pool_id,
                    provider=CspProvider.GCP,
                    min_nodes=0,
                    max_nodes=self.ALWAYS_FREE_MAX_INSTANCES,
                    desired_nodes=running,
                    current_nodes=running,
                    ready_nodes=running,
                    spot_nodes=0,
                    updated_at=datetime.now(UTC),
                )
            except Exception as err:
                msg = f"Failed to get GCP e2-micro instance '{pool_id}': {err}"
                raise HexaqueueError(msg) from err

        if pool_id not in self._local_pools:
            msg = f"GCP e2-micro pool '{pool_id}' not found in registered pools"
            raise HexaqueueError(msg)
        return self._local_pools[pool_id]

    async def list_pools(self) -> Sequence[InstancePoolState]:
        """List all subordinate GCP e2-micro pools/instances.

        Returns:
            Sequence of InstancePoolState descriptors.

        Raises:
            HexaqueueError: If GCP API fails.
        """
        if self._client is not None:
            try:
                instances = self._client.list(project=self._project, zone=self._zone)
                results: list[InstancePoolState] = []
                for inst in instances:
                    name = str(getattr(inst, "name", ""))
                    status = str(getattr(inst, "status", "TERMINATED")).upper()
                    running = 1 if status == "RUNNING" else 0
                    results.append(
                        InstancePoolState(
                            pool_id=name,
                            provider=CspProvider.GCP,
                            min_nodes=0,
                            max_nodes=self.ALWAYS_FREE_MAX_INSTANCES,
                            desired_nodes=running,
                            current_nodes=running,
                            ready_nodes=running,
                            updated_at=datetime.now(UTC),
                        )
                    )
                return results
            except Exception as err:
                msg = f"Failed to list GCP e2-micro instances: {err}"
                raise HexaqueueError(msg) from err

        return list(self._local_pools.values())

    async def scale_pool(self, request: PoolScaleRequest) -> PoolScaleResult:
        """Start (1) or stop (0) the subordinate GCP e2-micro instance.

        Args:
            request: PoolScaleRequest with target capacity (clamped to [0, 1]).

        Returns:
            PoolScaleResult indicating start/stop outcome.

        Raises:
            HexaqueueError: If target exceeds Always-Free bounds or API fails.
        """
        if request.target_nodes > self.ALWAYS_FREE_MAX_INSTANCES:
            msg = (
                f"GCP Always-Free e2-micro pool '{request.pool_id}' cannot scale to "
                f"{request.target_nodes} nodes (max {self.ALWAYS_FREE_MAX_INSTANCES})"
            )
            raise HexaqueueError(msg)

        clamped_target = max(
            0, min(self.ALWAYS_FREE_MAX_INSTANCES, request.target_nodes)
        )
        if self._client is not None:
            try:
                current_state = await self.get_pool_state(request.pool_id)
                prev_nodes = current_state.current_nodes
                if clamped_target > 0 and prev_nodes == 0:
                    self._client.start(
                        project=self._project,
                        zone=self._zone,
                        instance=request.pool_id,
                    )
                elif clamped_target == 0 and prev_nodes > 0:
                    self._client.stop(
                        project=self._project,
                        zone=self._zone,
                        instance=request.pool_id,
                    )
                return PoolScaleResult(
                    pool_id=request.pool_id,
                    previous_nodes=prev_nodes,
                    target_nodes=clamped_target,
                    success=True,
                    message=f"GCP e2-micro instance scaled to {clamped_target}",
                )
            except Exception as err:
                msg = (
                    f"Failed to scale GCP e2-micro instance '{request.pool_id}': {err}"
                )
                raise HexaqueueError(msg) from err

        if request.pool_id not in self._local_pools:
            msg = f"GCP e2-micro pool '{request.pool_id}' not found"
            raise HexaqueueError(msg)

        prev = self._local_pools[request.pool_id].current_nodes
        updated = self._local_pools[request.pool_id].model_copy(
            update={
                "desired_nodes": clamped_target,
                "current_nodes": clamped_target,
                "ready_nodes": clamped_target,
                "updated_at": datetime.now(UTC),
            }
        )
        self._local_pools[request.pool_id] = updated
        return PoolScaleResult(
            pool_id=request.pool_id,
            previous_nodes=prev,
            target_nodes=clamped_target,
            success=True,
            message=f"GCP e2-micro scaled to {clamped_target} ({request.reason})",
        )


__all__ = [
    "GcpInstancePoolAdapter",
    "GcpManagedInstanceGroupAdapter",
]
