"""Oracle Cloud Infrastructure (OCI) compute instance pool adapter.

Notes/Architectural Intent:
    Implements InstancePoolGovernorPort for Oracle Cloud Infrastructure (OCI)
    Instance Pools and Compute Clusters. Specifically optimized for Always-Free
    Arm Ampere A1 and AMD E4 shapes ($0 spend ceiling) with dynamic horizontal
    scaling, compartment isolation, and real-time fault domain distribution.
"""

import os
import time
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

_TERMINAL_INSTANCE_STATES: frozenset[str] = frozenset(
    {"terminated", "terminating", "stopped", "stopping"}
)


def _resolve_capacity_cache_ttl(explicit_ttl: float | None) -> float:
    """Resolve OCI compute capacity-report cache TTL in seconds."""
    if explicit_ttl is not None:
        return max(0.0, float(explicit_ttl))
    raw = os.environ.get("HEXAQUEUE_OCI_CAPACITY_CACHE_TTL_SECONDS", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return 60.0


def _resolve_oci_max_pool_size(current_size: int) -> int:
    """Resolve OCI instance pool maximum capacity ceiling from env or default."""
    raw = os.environ.get("HEXAQUEUE_OCI_MAX_POOL_SIZE", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return max(10, current_size)


def _is_pool_stopped(pool: Any) -> bool:
    """Return True if an OCI instance pool response has lifecycle_state STOPPED."""
    raw_state = getattr(pool, "lifecycle_state", None)
    return isinstance(raw_state, str) and raw_state.upper() == "STOPPED"


def _extract_pool_shape_spec(
    instance_config: Any,
) -> tuple[str | None, float | None, float | None]:
    """Extract compute shape name, OCPUs, and memory GB from an OCI instance config."""
    inst_details = getattr(instance_config, "instance_details", None)
    launch = getattr(inst_details, "launch_details", None)
    if launch is None:
        return None, None, None
    shape = getattr(launch, "shape", None)
    shape_cfg = getattr(launch, "shape_config", None)
    raw_ocpus = getattr(shape_cfg, "ocpus", None) if shape_cfg is not None else None
    raw_mem = (
        getattr(shape_cfg, "memory_in_gbs", None) if shape_cfg is not None else None
    )
    ocpus = float(raw_ocpus) if raw_ocpus is not None else None
    memory_gbs = float(raw_mem) if raw_mem is not None else None
    return (str(shape) if shape else None), ocpus, memory_gbs


def _build_capacity_report_payload(
    compartment_id: str,
    availability_domain: str,
    shape: str,
    ocpus: float | None,
    memory_gbs: float | None,
    oci_mod: Any,
) -> Any:
    """Construct CreateComputeCapacityReportDetails SDK model or dict fallback."""
    models = getattr(getattr(oci_mod, "core", None), "models", None)
    avail_cls = getattr(models, "CreateCapacityReportShapeAvailabilityDetails", None)
    report_cls = getattr(models, "CreateComputeCapacityReportDetails", None)
    if callable(avail_cls) and callable(report_cls):
        shape_cfg_cls = getattr(models, "CapacityReportInstanceShapeConfig", None)
        shape_cfg = (
            shape_cfg_cls(ocpus=ocpus, memory_in_gbs=memory_gbs)
            if callable(shape_cfg_cls) and ocpus is not None and memory_gbs is not None
            else None
        )
        avail_req = avail_cls(
            instance_shape=shape,
            instance_shape_config=shape_cfg,
        )
        return report_cls(
            compartment_id=compartment_id,
            availability_domain=availability_domain,
            shape_availabilities=[avail_req],
        )
    return {
        "compartment_id": compartment_id,
        "availability_domain": availability_domain,
        "shape_availabilities": [
            {
                "instance_shape": shape,
                "ocpus": ocpus,
                "memory_in_gbs": memory_gbs,
            }
        ],
    }


def _ad_reports_available(
    compute_client: Any,
    compartment_id: str,
    availability_domain: str,
    shape: str,
    ocpus: float | None,
    memory_gbs: float | None,
    oci_mod: Any,
) -> bool | None:
    """Probe one OCI AD via CreateComputeCapacityReport; returns None on API error."""
    try:
        details = _build_capacity_report_payload(
            compartment_id=compartment_id,
            availability_domain=availability_domain,
            shape=shape,
            ocpus=ocpus,
            memory_gbs=memory_gbs,
            oci_mod=oci_mod,
        )
        resp = compute_client.create_compute_capacity_report(details)
        rep = getattr(resp, "data", resp)
        avail_list = getattr(rep, "shape_availabilities", None) or []
        return any(
            str(getattr(item, "availability_status", "")).upper() == "AVAILABLE"
            for item in avail_list
        )
    except Exception:
        return None


class OciInstancePoolAdapter(InstancePoolGovernorPort):
    """Adapter for governing Oracle Cloud Infrastructure (OCI) Instance Pools.

    Args:
        compute_management_client: Injected OCI ComputeManagementClient or mock.
        compartment_id: Target OCI compartment OCID.
        credentials: Optional OciCredentialsConfig for SDK configuration.
        compute_client: Optional OCI ComputeClient used for pre-flight capacity reports.
        capacity_cache_ttl_seconds: Optional cache TTL in seconds for capacity probes.

    Notes/Architectural Intent:
        Hermetically testable through client injection and in-memory mock pools
        without requiring live OCI tenancy credentials or network access.
    """

    def __init__(
        self,
        compute_management_client: Any = None,
        compartment_id: str = "ocid1.compartment.oc1..default",
        credentials: OciCredentialsConfig | None = None,
        compute_client: Any = None,
        capacity_cache_ttl_seconds: float | None = None,
    ) -> None:
        self._client = compute_management_client
        self._compute_client = compute_client
        self._compartment_id = compartment_id
        self._credentials = credentials
        self._local_pools: dict[str, InstancePoolState] = {}
        self._capacity_cache_ttl_seconds = _resolve_capacity_cache_ttl(
            capacity_cache_ttl_seconds
        )
        self._capacity_cache: dict[str, tuple[float, bool]] = {}

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
            Attempts to configure live OCI SDK ComputeManagementClient and ComputeClient
            if the oci package is installed and credentials are configured; otherwise
            falls back gracefully to hermetic simulation mode.
        """
        client = None
        compute_client = None
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
                    compute_client = oci_mod.core.ComputeClient(
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
                    compute_client = oci_mod.core.ComputeClient(config)
            except Exception:
                client = None
                compute_client = None

        target_compartment = (
            compartment_id
            or (credentials.tenancy_ocid if credentials else None)
            or "ocid1.compartment.oc1..default"
        )
        return cls(
            compute_management_client=client,
            compartment_id=target_compartment,
            credentials=credentials,
            compute_client=compute_client,
        )

    def _extract_probe_inputs(
        self, pool_id: str
    ) -> tuple[str, str, float | None, float | None, list[str]] | None:
        """Load pool placement ADs and instance shape spec needed for capacity probing."""
        pool_resp = self._client.get_instance_pool(instance_pool_id=pool_id)
        pool = getattr(pool_resp, "data", pool_resp)
        eff_comp = getattr(pool, "compartment_id", None) or self._compartment_id
        cfg_id = getattr(pool, "instance_configuration_id", None)
        if not cfg_id:
            return None
        cfg_resp = self._client.get_instance_configuration(
            instance_configuration_id=cfg_id
        )
        inst_cfg = getattr(cfg_resp, "data", cfg_resp)
        shape, ocpus, memory_gbs = _extract_pool_shape_spec(inst_cfg)
        placements = getattr(pool, "placement_configurations", None) or []
        ads = [
            str(ad)
            for p in placements
            if (ad := getattr(p, "availability_domain", None))
        ]
        if not shape or not ads:
            return None
        return eff_comp, shape, ocpus, memory_gbs, ads

    async def check_pool_capacity(self, pool_id: str) -> bool:
        """Probe OCI compute capacity across every AD configured on the instance pool.

        Args:
            pool_id: OCID of the OCI Instance Pool to evaluate.

        Returns:
            True when at least one placement AD reports ``AVAILABLE`` (or on API errors
            to fail open); False when probed ADs report capacity exhaustion.

        Notes/Architectural Intent:
            Caches definitive capacity probe verdicts for ``capacity_cache_ttl_seconds``
            to prevent redundant OCI Compute/ComputeManagement calls under bursts.
        """
        if self._client is None or self._compute_client is None:
            return True
        if self._capacity_cache_ttl_seconds > 0:
            cached = self._capacity_cache.get(pool_id)
            if (
                cached is not None
                and time.monotonic() - cached[0] < self._capacity_cache_ttl_seconds
            ):
                return cached[1]
        try:
            probe_inputs = self._extract_probe_inputs(pool_id)
            if probe_inputs is None:
                return True
            eff_comp, shape, ocpus, memory_gbs, ads = probe_inputs
        except Exception:
            return True

        oci_mod = optional_dependency("oci")
        probed_count = 0
        for ad in ads:
            verdict = _ad_reports_available(
                compute_client=self._compute_client,
                compartment_id=eff_comp,
                availability_domain=ad,
                shape=shape,
                ocpus=ocpus,
                memory_gbs=memory_gbs,
                oci_mod=oci_mod,
            )
            if verdict is True:
                if self._capacity_cache_ttl_seconds > 0:
                    self._capacity_cache[pool_id] = (time.monotonic(), True)
                return True
            if verdict is False:
                probed_count += 1
        if probed_count > 0:
            if self._capacity_cache_ttl_seconds > 0:
                self._capacity_cache[pool_id] = (time.monotonic(), False)
            return False
        return True

    def register_mock_pool(self, pool: InstancePoolState) -> None:
        """Register a pool in the in-memory store for hermetic testing or simulation.

        Args:
            pool: Initial InstancePoolState snapshot.
        """
        self._local_pools[pool.pool_id] = pool

    def _read_oci_pool_snapshot(self, pool_id: str) -> tuple[InstancePoolState, bool]:
        """Fetch current InstancePoolState and whether the OCI pool is STOPPED."""
        resp = self._client.get_instance_pool(instance_pool_id=pool_id)
        pool = resp.data
        eff_comp = getattr(pool, "compartment_id", None) or self._compartment_id
        instances_resp = self._client.list_instance_pool_instances(
            compartment_id=eff_comp,
            instance_pool_id=pool_id,
        )
        instances = instances_resp.data if hasattr(instances_resp, "data") else []

        def _inst_state(inst: Any) -> str:
            state = getattr(inst, "state", None)
            if isinstance(state, str) and state:
                return state.lower()
            lifecycle = getattr(inst, "lifecycle_state", None)
            return lifecycle.lower() if isinstance(lifecycle, str) else ""

        ready_count = sum(1 for inst in instances if _inst_state(inst) == "running")
        active_count = sum(
            1
            for inst in instances
            if _inst_state(inst) not in _TERMINAL_INSTANCE_STATES
        )
        stopped = _is_pool_stopped(pool)
        desired = 0 if stopped else int(pool.size)
        state = InstancePoolState(
            pool_id=pool_id,
            provider=CspProvider.OCI,
            min_nodes=0,
            max_nodes=_resolve_oci_max_pool_size(int(pool.size)),
            desired_nodes=desired,
            current_nodes=active_count,
            ready_nodes=ready_count,
            spot_nodes=0,
            capability_tags=frozenset(getattr(pool, "defined_tags", {}).keys()),
            updated_at=datetime.now(UTC),
        )
        return state, stopped

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
                state, _stopped = self._read_oci_pool_snapshot(pool_id)
                return state
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
                    stopped = _is_pool_stopped(p)
                    active_nodes = 0 if stopped else int(p.size)
                    results.append(
                        InstancePoolState(
                            pool_id=p.id,
                            provider=CspProvider.OCI,
                            min_nodes=0,
                            max_nodes=_resolve_oci_max_pool_size(int(p.size)),
                            desired_nodes=active_nodes,
                            current_nodes=active_nodes,
                            ready_nodes=active_nodes,
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
                current_state, pool_stopped = self._read_oci_pool_snapshot(
                    request.pool_id
                )
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
                started = False
                if (
                    request.target_nodes > 0
                    and pool_stopped
                    and hasattr(self._client, "start_instance_pool")
                ):
                    self._client.start_instance_pool(instance_pool_id=request.pool_id)
                    started = True
                action_label = "started and resized" if started else "resized"
                return PoolScaleResult(
                    pool_id=request.pool_id,
                    previous_nodes=prev_nodes,
                    target_nodes=request.target_nodes,
                    success=True,
                    message=f"OCI instance pool {action_label} to {request.target_nodes} instances",
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
