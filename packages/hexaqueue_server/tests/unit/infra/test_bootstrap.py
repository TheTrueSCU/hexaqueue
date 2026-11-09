"""Tests for ServerBootstrapper and bootstrap_server_container composition root."""

from unittest.mock import patch

from hexastack_core.infra.container import create_container
from hexastack_cqrs.infra.pipeline import ExecutionPipeline

from hexaqueue_collateral.ports.service import CollateralServicePort
from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry
from hexaqueue_core.ports.storage import PresignedStoragePort
from hexaqueue_server.domain.config import ServerConfig
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator
from hexaqueue_server.infra.bootstrap import (
    ServerBootstrapper,
    bootstrap_server_container,
)


def test_server_bootstrapper() -> None:
    """Verify ServerBootstrapper initialization and interface methods."""
    bootstrapper = ServerBootstrapper()
    name = bootstrapper.name
    assert name == "server"
    order = bootstrapper.order
    assert order == 30

    registry = HexaqueueConfigRegistry()
    bootstrapper.register_config(registry)
    all_configs = registry.all
    assert "ServerConfig" in all_configs

    context = HexaqueueBootstrapContext(
        container=create_container(),
        config=None,
        config_registry=registry,
    )
    bootstrapper.configure(context)
    has_pipeline = ExecutionPipeline in context.container
    assert has_pipeline is True


def test_bootstrap_server_container_default() -> None:
    """Verify bootstrap_server_container wires local/mock components when CSP is unconfigured."""
    di = bootstrap_server_container()

    has_storage = PresignedStoragePort in di
    assert has_storage is True
    has_collateral = CollateralServicePort in di
    assert has_collateral is True
    has_coord = SliceLeaseCoordinator in di
    assert has_coord is True
    has_pipeline = ExecutionPipeline in di
    assert has_pipeline is True
    has_cfg = ServerConfig in di
    assert has_cfg is True

    coord = di.resolve(SliceLeaseCoordinator)
    autoscaler_active = coord.has_autoscaler
    assert autoscaler_active is False


def test_bootstrap_server_container_oci_configured() -> None:
    """Verify bootstrap_server_container configures OCI adapters when env is set."""
    env_vars = {
        "HEXAQUEUE_CSP_PROVIDER": "OCI",
        "HEXAQUEUE_OCI_INSTANCE_POOL_ID": "ocid1.instancepool.oc1.phx..mock",
        "HEXAQUEUE_COLLATERAL_BUCKET": "mock-bucket",
    }
    with (
        patch.dict("os.environ", env_vars, clear=False),
        patch(
            "hexaqueue_core.adapters.storage.oci.optional_dependency", return_value=None
        ),
        patch(
            "hexaqueue_server.adapters.cloud.oci.optional_dependency", return_value=None
        ),
    ):
        di = bootstrap_server_container()
        coord = di.resolve(SliceLeaseCoordinator)
        autoscaler_active = coord.has_autoscaler
        assert autoscaler_active is True
