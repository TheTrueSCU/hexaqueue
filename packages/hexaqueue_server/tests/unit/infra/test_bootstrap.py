"""Tests for ServerBootstrapper and bootstrap_server_container composition root."""

from unittest.mock import patch

import pytest
from hexastack_core.infra.container import create_container
from hexastack_cqrs.infra.pipeline import ExecutionPipeline

from hexaqueue_collateral.ports.service import CollateralServicePort
from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry
from hexaqueue_core.ports.storage import PresignedStoragePort
from hexaqueue_server.adapters.storage.in_memory import (
    InMemorySchedulerStorageAdapter,
)
from hexaqueue_server.adapters.storage.oracle import (
    OciAutonomousDatabaseStorageAdapter,
)
from hexaqueue_server.domain.config import ServerConfig
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator
from hexaqueue_server.infra.bootstrap import (
    ServerBootstrapper,
    bootstrap_server_container,
)
from hexaqueue_server.ports.storage import SchedulerStoragePort


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


def test_bootstrap_server_container_wires_scheduler_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify bootstrap_server_container registers SchedulerStoragePort into DI and controller."""
    monkeypatch.delenv("HEXAQUEUE_ORACLE_ADB_DSN", raising=False)
    monkeypatch.delenv("HEXAQUEUE_ORACLE_ADB_PASSWORD", raising=False)
    monkeypatch.delenv("HEXAQUEUE_DATABASE_URL", raising=False)

    di_mem = bootstrap_server_container()
    mem_storage = di_mem.resolve(SchedulerStoragePort)
    assert isinstance(mem_storage, InMemorySchedulerStorageAdapter)

    monkeypatch.setenv("HEXAQUEUE_DATABASE_URL", "sqlite:///:memory:")
    di_adb = bootstrap_server_container()
    adb_storage = di_adb.resolve(SchedulerStoragePort)
    assert isinstance(adb_storage, OciAutonomousDatabaseStorageAdapter)


def test_bootstrap_server_container_parses_multi_pool_ids() -> None:
    """Verify bootstrap parses comma-separated HEXAQUEUE_OCI_INSTANCE_POOL_IDS in order."""
    env_vars = {
        "HEXAQUEUE_CSP_PROVIDER": "OCI",
        "HEXAQUEUE_OCI_INSTANCE_POOL_IDS": "ocid1..a1, ocid1..a4 , ocid1..e5",
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
        readiness = coord.get_capacity_readiness()
        pool_ids = readiness["pool_ids"]
        primary_id = readiness["pool_id"]
        assert pool_ids == ["ocid1..a1", "ocid1..a4", "ocid1..e5"]
        assert primary_id == "ocid1..a1"
