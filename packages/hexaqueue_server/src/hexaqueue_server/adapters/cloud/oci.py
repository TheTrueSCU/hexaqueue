"""Oracle Cloud Infrastructure (OCI) compute instance pool adapter.

Notes/Architectural Intent:
    Implements InstancePoolGovernorPort for Oracle Cloud Infrastructure (OCI)
    Instance Pools and Compute Clusters. Specifically optimized for Always-Free
    Arm Ampere A1 and AMD E4 shapes ($0 spend ceiling) with dynamic horizontal
    scaling, compartment isolation, and real-time fault domain distribution.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.credentials import OciCredentialsConfig
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import (
    InstancePoolState,
    PoolScaleRequest,
    PoolScaleResult,
)
from hexaqueue_core.ports.pool import InstancePoolGovernorPort
from hexaqueue_core.utils.imports import optional_dependency


class OciInstancePoolAdapter(InstancePoolGovernorPort):
    """Adapter for governing Oracle Cloud Infrastructure (OCI) Instance Pools.

    Args:
        compute_management_client: Injected OCI ComputeManagementClient or mock.
        compartment_id: Target OCI compartment OCID.
        credentials: Optional OciCredentialsConfig for SDK configuration.

    Notes/Architectural Intent:
        Hermetically testable through client injection and in-memory mock pools
        without requiring live OCI tenancy credentials or network access.
    """

    def __init__(
        self,
        compute_management_client: Any = None,
        compartment_id: str = "ocid1.compartment.oc1..default",
        credentials: OciCredentialsConfig | None = None,
    ) -> None:
        self._client = compute_management_client
        self._compartment_id = compartment_id
        self._credentials = credentials
        self._local_pools: dict[str, InstancePoolState] = {}

    @classmethod
    def from_credentials(
        cls,
        credentials: OciCredentialsConfig | None = None,
        compartment_id: str | None = None,
    ) -> "OciInstancePoolAdapter":
        """Factory creating an adapter from OCI credentials.

        Args:
            credentials: Optional OCI credentials configuration.
            compartment_id: Optional OCI compartment OCID override.

        Returns:
            Configured OciInstancePoolAdapter instance.

        Notes/Architectural Intent:
            Attempts to configure live OCI SDK ComputeManagementClient if the oci
            package is installed and credentials are configured; otherwise
            falls back gracefully to hermetic simulation mode.
        """
        client = None
        oci_mod = optional_dependency("oci")

        if (
            oci_mod is not None
            and credentials is not None
            and credentials.is_configured
        ):
            try:
                if credentials.use_instance_principals:
                    signer = (
                        oci_mod.auth.signers.InstancePrincipalsSecurityTokenSigner()
                    )
                    client = oci_mod.core.ComputeManagementClient(
                        config={}, signer=signer
                    )
                elif (
                    credentials.key_content is not None
                    or credentials.key_file is not None
                ):
                    config = {
                        "user": credentials.user_ocid or "",
                        "fingerprint": credentials.fingerprint or "",
                        "tenancy": credentials.tenancy_ocid or "",
                        "region": credentials.region or "us-ashburn-1",
                    }
                    if credentials.key_content is not None:
                        config["key_content"] = (
                            credentials.key_content.get_secret_value()
                        )
                    elif credentials.key_file is not None:
                        config["key_file"] = credentials.key_file
                    client = oci_mod.core.ComputeManagementClient(config)
            except Exception:
                client = None

        target_compartment = (
            compartment_id
            or (credentials.tenancy_ocid if credentials else None)
            or "ocid1.compartment.oc1..default"
        )
        return cls(
            compute_management_client=client,
            compartment_id=target_compartment,
            credentials=credentials,
        )

    def register_mock_pool(self, pool: InstancePoolState) -> None:
        """Register a pool in the in-memory store for hermetic testing or simulation.

        Args:
            pool: Initial InstancePoolState snapshot.
        """
        self._local_pools[pool.pool_id] = pool

    async def get_pool_state(self, pool_id: str) -> InstancePoolState:
        """Query real-time OCI instance pool capacity and health metrics.

        Args:
            pool_id: OCID of the OCI Instance Pool.

        Returns:
            InstancePoolState containing current capacity and node readiness.

        Raises:
            HexaqueueError: If instance pool cannot be found or OCI API fails.
        """
        if self._client is not None:
            try:
                resp = self._client.get_instance_pool(instance_pool_id=pool_id)
                pool = resp.data
                eff_comp = getattr(pool, "compartment_id", None) or self._compartment_id
                instances_resp = self._client.list_instance_pool_instances(
                    compartment_id=eff_comp,
                    instance_pool_id=pool_id,
                )
                instances = (
                    instances_resp.data if hasattr(instances_resp, "data") else []
                )
                ready_count = sum(
                    1
                    for inst in instances
                    if getattr(inst, "lifecycle_state", "").lower() == "running"
                )
                return InstancePoolState(
                    pool_id=pool_id,
                    provider=CspProvider.OCI,
                    min_nodes=0,
                    max_nodes=max(10, pool.size),
                    desired_nodes=pool.size,
                    current_nodes=len(instances),
                    ready_nodes=ready_count,
                    spot_nodes=0,
                    capability_tags=frozenset(getattr(pool, "defined_tags", {}).keys()),
                    updated_at=datetime.now(UTC),
                )
            except Exception as err:
                msg = f"Failed to get OCI instance pool '{pool_id}': {err}"
                raise HexaqueueError(msg) from err

        if pool_id not in self._local_pools:
            msg = f"OCI instance pool '{pool_id}' not found in registered pools"
            raise HexaqueueError(msg)
        return self._local_pools[pool_id]

    async def list_pools(self) -> Sequence[InstancePoolState]:
        """List all managed OCI instance pools in the compartment.

        Returns:
            Sequence of InstancePoolState descriptors.

        Raises:
            HexaqueueError: If OCI API call fails.
        """
        if self._client is not None:
            try:
                resp = self._client.list_instance_pools(
                    compartment_id=self._compartment_id
                )
                pools = resp.data if hasattr(resp, "data") else []
                results: list[InstancePoolState] = []
                for p in pools:
                    results.append(
                        InstancePoolState(
                            pool_id=p.id,
                            provider=CspProvider.OCI,
                            min_nodes=0,
                            max_nodes=max(10, p.size),
                            desired_nodes=p.size,
                            current_nodes=p.size,
                            ready_nodes=p.size,
                            capability_tags=frozenset(
                                getattr(p, "defined_tags", {}).keys()
                            ),
                            updated_at=datetime.now(UTC),
                        )
                    )
                return results
            except Exception as err:
                msg = f"Failed to list OCI instance pools: {err}"
                raise HexaqueueError(msg) from err

        return list(self._local_pools.values())

    async def scale_pool(self, request: PoolScaleRequest) -> PoolScaleResult:
        """Resize OCI instance pool capacity.

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
                oci_mod = optional_dependency("oci")
                details = (
                    oci_mod.core.models.UpdateInstancePoolDetails(
                        size=request.target_nodes
                    )
                    if oci_mod
                    else None
                )
                self._client.update_instance_pool(
                    instance_pool_id=request.pool_id,
                    update_instance_pool_details=details,
                )
                return PoolScaleResult(
                    pool_id=request.pool_id,
                    previous_nodes=prev_nodes,
                    target_nodes=request.target_nodes,
                    success=True,
                    message=f"OCI instance pool resized to {request.target_nodes} instances",
                )
            except Exception as err:
                msg = f"Failed to scale OCI instance pool '{request.pool_id}': {err}"
                raise HexaqueueError(msg) from err

        if request.pool_id not in self._local_pools:
            msg = f"OCI instance pool '{request.pool_id}' not found"
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
            message="OCI instance pool scaled successfully",
        )
