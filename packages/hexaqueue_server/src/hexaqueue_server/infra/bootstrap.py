"""Bootstrap lifecycle handler and dependency injection composition root for hexaqueue-server.

Notes/Architectural Intent:
    Serves as the centralized Composition Root for Hexaqueue Server, wiring
    domain ports, cloud storage and instance pool governors, the CQRS execution
    pipeline, and the SliceLeaseCoordinator into the Hexastack ContainerPort DI container.
"""

import os

from hexastack_core.infra.container import create_container
from hexastack_core.ports.container import ContainerPort
from hexastack_cqrs.infra.pipeline import ExecutionPipeline

from hexaqueue_collateral.adapters.local import LocalCollateralServiceAdapter
from hexaqueue_collateral.ports.service import CollateralServicePort
from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.adapters.security.noop import NoOpSecurityQuarantineAdapter
from hexaqueue_core.adapters.storage.oci import OciPresignedStorageAdapter
from hexaqueue_core.adapters.storage.presigned import InMemoryPresignedStorageAdapter
from hexaqueue_core.domain.credentials import OciCredentialsConfig
from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry
from hexaqueue_core.ports.bootstrap import BootstrapperPort
from hexaqueue_core.ports.storage import PresignedStoragePort
from hexaqueue_monitor.adapters.ledger import InMemoryBudgetLedgerAdapter
from hexaqueue_monitor.adapters.local import LocalClusterMonitorAdapter
from hexaqueue_server.adapters.cloud.oci import OciInstancePoolAdapter
from hexaqueue_server.adapters.local import (
    LocalSchedulerControllerAdapter,
)
from hexaqueue_server.domain.autoscaler import BudgetAwareInstancePoolAutoscaler
from hexaqueue_server.domain.config import ServerConfig
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator
from hexaqueue_server.infra.cqrs.pipeline import (
    create_hexaqueue_execution_pipeline,
)


def _resolve_storage_port(
    di: ContainerPort, provider: str, pool_id: str | None
) -> PresignedStoragePort:
    """Resolve or construct PresignedStoragePort implementation."""
    storage_port = (
        di.resolve(PresignedStoragePort) if PresignedStoragePort in di else None
    )
    if storage_port is not None:
        return storage_port

    if provider == "OCI" or pool_id:
        creds = OciCredentialsConfig(use_instance_principals=True)
        bucket = os.environ.get("HEXAQUEUE_COLLATERAL_BUCKET") or "hexaqueue-collateral"
        storage_port = OciPresignedStorageAdapter.from_credentials(
            credentials=creds,
            bucket_name=bucket,
        )
    else:
        storage_port = InMemoryPresignedStorageAdapter()
    di.add_instance(storage_port, declared_class=PresignedStoragePort)
    return storage_port


def _resolve_coordinator(
    di: ContainerPort,
    storage_port: PresignedStoragePort,
    collateral_service: CollateralServicePort,
    provider: str,
    pool_id: str | None,
) -> SliceLeaseCoordinator:
    """Resolve or construct SliceLeaseCoordinator implementation."""
    coordinator = (
        di.resolve(SliceLeaseCoordinator) if SliceLeaseCoordinator in di else None
    )
    if coordinator is not None:
        return coordinator

    autoscaler: BudgetAwareInstancePoolAutoscaler | None = None
    if pool_id and provider == "OCI":
        creds = OciCredentialsConfig(use_instance_principals=True)
        gov = OciInstancePoolAdapter.from_credentials(credentials=creds)
        autoscaler = BudgetAwareInstancePoolAutoscaler(governors={pool_id: gov})

    coordinator = SliceLeaseCoordinator(
        storage_port=storage_port,
        collateral_service=collateral_service,
        autoscaler=autoscaler,
        pool_id=pool_id,
    )
    di.add_instance(coordinator, declared_class=SliceLeaseCoordinator)
    return coordinator


def _resolve_pipeline(
    di: ContainerPort,
    coordinator: SliceLeaseCoordinator,
    storage_port: PresignedStoragePort,
    collateral_service: CollateralServicePort,
) -> ExecutionPipeline:
    """Resolve or construct ExecutionPipeline and wire coordinator controller."""
    pipeline = di.resolve(ExecutionPipeline) if ExecutionPipeline in di else None
    if pipeline is not None:
        if coordinator.controller is None:
            ctrl = getattr(pipeline, "controller", None) or getattr(
                getattr(pipeline, "service", None), "controller", None
            )
            if ctrl is not None:
                coordinator.set_controller(ctrl)
                if hasattr(ctrl, "set_lease_coordinator"):
                    ctrl.set_lease_coordinator(coordinator)
        return pipeline

    queue = InMemoryJobQueueAdapter()
    budget_port = InMemoryBudgetLedgerAdapter()
    cluster_monitor = LocalClusterMonitorAdapter()
    controller = LocalSchedulerControllerAdapter(
        queue=queue,
        budget_port=budget_port,
        cluster_monitor=cluster_monitor,
        lease_coordinator=coordinator,
    )
    coordinator.set_controller(controller)

    pipeline = create_hexaqueue_execution_pipeline(
        controller=controller,
        budget_port=budget_port,
        cluster_monitor=cluster_monitor,
        storage_port=storage_port,
        collateral_service=collateral_service,
    )
    di.add_instance(pipeline, declared_class=ExecutionPipeline)
    return pipeline


def bootstrap_server_container(
    config: ServerConfig | None = None,
    container: ContainerPort | None = None,
) -> ContainerPort:
    """Bootstrap and register all server domain services and ports into the DI container.

    Args:
        config: Optional ServerConfig instance.
        container: Optional pre-existing ContainerPort container.

    Returns:
        Populated ContainerPort instance with registered services.

    Notes/Architectural Intent:
        Acts as the authoritative Composition Root for the Hexaqueue Server. Resolves
        cloud infrastructure adapters (OCI Object Storage, A1 Instance Pool autoscalers)
        when CSP is configured, or cleanly provides in-memory hermetic equivalents.
    """
    server_cfg = config or ServerConfig()
    di = container or create_container()

    provider = os.environ.get("HEXAQUEUE_CSP_PROVIDER", "LOCAL").upper()
    pool_id = os.environ.get("HEXAQUEUE_OCI_INSTANCE_POOL_ID") or os.environ.get(
        "HEXAQUEUE_INSTANCE_POOL_ID"
    )

    storage_port = _resolve_storage_port(di, provider, pool_id)

    collateral_service = (
        di.resolve(CollateralServicePort) if CollateralServicePort in di else None
    )
    if collateral_service is None:
        collateral_service = LocalCollateralServiceAdapter(
            security_port=NoOpSecurityQuarantineAdapter(),
            storage_port=storage_port,
        )
        di.add_instance(collateral_service, declared_class=CollateralServicePort)

    coordinator = _resolve_coordinator(
        di, storage_port, collateral_service, provider, pool_id
    )
    _resolve_pipeline(di, coordinator, storage_port, collateral_service)

    if ServerConfig not in di:
        di.add_instance(server_cfg, declared_class=ServerConfig)

    return di

    if ServerConfig not in di:
        di.add_instance(server_cfg, declared_class=ServerConfig)

    return di


class ServerBootstrapper(BootstrapperPort):
    """Bootstrapper for hexaqueue-server services and registries."""

    name: str = "server"
    order: int = 30

    def register_config(self, registry: HexaqueueConfigRegistry) -> None:
        """Register server configuration models."""
        registry.register(ServerConfig)

    def configure(self, context: HexaqueueBootstrapContext) -> None:
        """Configure server services in application DI container."""
        cfg: ServerConfig | None = None
        if ServerConfig in context.container:
            try:
                cfg = context.container.resolve(ServerConfig)
            except Exception:
                cfg = None
        bootstrap_server_container(config=cfg, container=context.container)


__all__ = [
    "bootstrap_server_container",
    "ServerBootstrapper",
]
