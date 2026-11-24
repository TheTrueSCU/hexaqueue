"""FastAPI application factory and APIRouter assembly for Hexaqueue Server.

Notes/Architectural Intent:
    Composes individual domain sub-routers into a unified `/v1` prefix router and
    wires container dependencies with the CQRS ExecutionPipeline.
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from hexastack_core.infra.container import create_container
from hexastack_core.ports.container import ContainerPort
from hexastack_core.utils.context import get_correlation_id
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.domain.config import HealthConfig, HexastackFastApiConfig
from hexastack_fastapi.infra import create_fastapi_app

from hexaqueue_collateral.ports.service import CollateralServicePort
from hexaqueue_core.adapters.security.audit import InMemoryBoundaryAuditLoggerAdapter
from hexaqueue_core.adapters.security.spiffe import PolicySpiffeAuthorizerAdapter
from hexaqueue_core.domain.security import SpiffeAuthorizationPolicy
from hexaqueue_server.adapters.api.budget import create_budget_router
from hexaqueue_server.adapters.api.cluster import create_cluster_router
from hexaqueue_server.adapters.api.jobs import create_jobs_router
from hexaqueue_server.adapters.api.logs import create_logs_router
from hexaqueue_server.adapters.api.middleware import ZeroTrustBoundaryMiddleware
from hexaqueue_server.adapters.api.nodes import create_nodes_router
from hexaqueue_server.adapters.api.runs import create_runs_router
from hexaqueue_server.adapters.api.test_runs import create_test_runs_router
from hexaqueue_server.adapters.api.webhooks import create_webhooks_router
from hexaqueue_server.adapters.api.worker_pool import create_worker_pool_router
from hexaqueue_server.adapters.mcp import mount_mcp_server
from hexaqueue_server.domain.config import ServerConfig, ServerInterfaceConfig
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator
from hexaqueue_server.infra.bootstrap import bootstrap_server_container
from hexaqueue_server.ports.controller import SchedulerControllerPort
from hexaqueue_server.ports.storage import SchedulerStoragePort


def create_server_api_router(
    interfaces: ServerInterfaceConfig | None = None,
) -> APIRouter:
    """Construct the FastAPI APIRouter providing unified REST endpoints for Hexaqueue.

    Args:
        interfaces: Optional ServerInterfaceConfig selecting active interface routers.

    Returns:
        APIRouter with active /v1 endpoints bound to CQRS pipeline dispatch.
    """
    cfg = interfaces or ServerInterfaceConfig()
    router = APIRouter(prefix="/v1")
    if cfg.runs:
        router.include_router(create_runs_router())
        router.include_router(create_test_runs_router())
    if cfg.jobs:
        router.include_router(create_jobs_router())
    if cfg.logs:
        router.include_router(create_logs_router())
    if cfg.nodes:
        router.include_router(create_nodes_router())
    if cfg.cluster or cfg.collateral:
        router.include_router(create_cluster_router())
    if cfg.budget:
        router.include_router(create_budget_router())
    if cfg.webhooks:
        router.include_router(create_webhooks_router())
    if cfg.worker_pool:
        router.include_router(create_worker_pool_router())
    return router


def _register_health_routes(app: FastAPI, di: ContainerPort) -> None:
    """Register /health and capacity-aware /health/ready endpoints on app."""

    def _resolve_readiness() -> dict[str, Any]:
        coord = (
            di.resolve(SliceLeaseCoordinator) if SliceLeaseCoordinator in di else None
        )
        if coord is not None and hasattr(coord, "get_capacity_readiness"):
            return coord.get_capacity_readiness()
        return {
            "capacity_state": "READY",
            "ready": True,
            "active_workers": 0,
            "pending_slices": 0,
            "active_leases": 0,
            "pool_id": None,
            "pool_circuit": {
                "state": "CLOSED",
                "reason": None,
                "retry_after_seconds": 0.0,
                "trip_count": 0,
            },
        }

    @app.get("/health", summary="Cluster health check", tags=["Health"])
    def cluster_health() -> dict[str, Any]:
        total_cores = os.cpu_count() or 1
        provider = os.environ.get("HEXAQUEUE_CSP_PROVIDER", "LOCAL")
        cap = _resolve_readiness()
        return {
            "status": "ok",
            "cores": total_cores,
            "provider": provider,
            "active_workers": cap.get("active_workers", 0),
            "capacity_state": cap.get("capacity_state", "READY"),
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "correlation_id": get_correlation_id(),
        }

    @app.get(
        "/health/ready",
        summary="Capacity-aware cluster readiness check",
        tags=["Health"],
    )
    def cluster_readiness() -> JSONResponse:
        total_cores = os.cpu_count() or 1
        provider = os.environ.get("HEXAQUEUE_CSP_PROVIDER", "LOCAL")
        cap = _resolve_readiness()
        is_ready = bool(cap.get("ready", True))
        payload: dict[str, Any] = {
            "status": "ok" if is_ready else "degraded",
            "cores": total_cores,
            "provider": provider,
            **cap,
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "correlation_id": get_correlation_id(),
        }
        return JSONResponse(
            content=payload,
            status_code=200 if is_ready else 503,
        )


def create_server_app(
    pipeline: ExecutionPipeline | None = None,
    config: ServerConfig | None = None,
    container: ContainerPort | None = None,
) -> FastAPI:
    """Create a fully assembled FastAPI application for Hexaqueue Server.

    Args:
        pipeline: Optional preconfigured CQRS ExecutionPipeline instance.
        config: Optional ServerConfig instance specifying feature flags and interfaces.
        container: Optional preconfigured ContainerPort instance.

    Returns:
        Configured FastAPI application instance.
    """
    server_cfg = config or ServerConfig()
    effective_interfaces = server_cfg.interfaces.apply_feature_flags()
    effective_mcp = server_cfg.mcp.apply_feature_flags()
    server_cfg = server_cfg.model_copy(
        update={"interfaces": effective_interfaces, "mcp": effective_mcp}
    )

    if container is not None:
        di = container
        if pipeline is not None:
            effective_pipeline = pipeline
            di.add_instance(effective_pipeline, declared_class=ExecutionPipeline)
        else:
            effective_pipeline = (
                di.resolve(ExecutionPipeline) if ExecutionPipeline in di else None
            )
            if effective_pipeline is None:
                di = bootstrap_server_container(config=server_cfg, container=di)
                effective_pipeline = di.resolve(ExecutionPipeline)
    elif pipeline is not None:
        effective_pipeline = pipeline
        di = create_container()
        di.add_instance(effective_pipeline, declared_class=ExecutionPipeline)
    else:
        di = bootstrap_server_container(config=server_cfg)
        effective_pipeline = di.resolve(ExecutionPipeline)

    fastapi_cfg = HexastackFastApiConfig(health=HealthConfig(enable=False))
    app = create_fastapi_app(
        config=fastapi_cfg, container=di, pipeline=effective_pipeline
    )
    _register_health_routes(app, di)

    api_router = create_server_api_router(server_cfg.interfaces)
    app.include_router(api_router)
    app.include_router(api_router, prefix="/api")
    if server_cfg.interfaces.worker_pool:
        app.include_router(create_worker_pool_router())
    if server_cfg.interfaces.mcp and server_cfg.mcp.enabled:
        mount_mcp_server(app, effective_pipeline, config=server_cfg.mcp)
    app.state.server_config = server_cfg

    # Initialize zero-trust security state
    if not hasattr(app.state, "audit_logger"):
        app.state.audit_logger = InMemoryBoundaryAuditLoggerAdapter()

    if not hasattr(app.state, "spiffe_authorizer"):
        policy = SpiffeAuthorizationPolicy(
            allow_anonymous=server_cfg.security.allow_anonymous,
            allowed_trust_domains=set(server_cfg.security.trust_domains),
        )
        app.state.spiffe_authorizer = PolicySpiffeAuthorizerAdapter(policy)

    if not hasattr(app.state, "worker_semaphore"):
        total_cores = os.cpu_count() or 4
        app.state.worker_semaphore = asyncio.Semaphore(max(1, total_cores))

    app.add_middleware(ZeroTrustBoundaryMiddleware)
    _attach_server_lifespan(app, di)
    return app


def _attach_server_lifespan(app: FastAPI, di: ContainerPort) -> None:
    """Attach startup hydration and graceful shutdown storage flush to app."""
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _server_lifespan(fastapi_app: FastAPI) -> AsyncGenerator[None]:
        async with original_lifespan(fastapi_app):
            ctrl = (
                di.resolve(SchedulerControllerPort)
                if SchedulerControllerPort in di
                else None
            )
            hydrate_fn: Any = getattr(ctrl, "hydrate_from_storage", None)
            if callable(hydrate_fn):
                await hydrate_fn()
            collateral_svc = (
                di.resolve(CollateralServicePort)
                if CollateralServicePort in di
                else None
            )
            col_hydrate_fn: Any = getattr(collateral_svc, "hydrate_from_storage", None)
            if callable(col_hydrate_fn):
                await col_hydrate_fn()
            coordinator = (
                di.resolve(SliceLeaseCoordinator)
                if SliceLeaseCoordinator in di
                else None
            )
            if coordinator is not None and hasattr(coordinator, "start_reconciler"):
                coordinator.start_reconciler()
            try:
                yield
            finally:
                if coordinator is not None:
                    shutdown_fn: Any = getattr(coordinator, "shutdown", None)
                    if callable(shutdown_fn):
                        await shutdown_fn()
                    elif hasattr(coordinator, "stop_reconciler"):
                        await coordinator.stop_reconciler()
                scheduler_storage = (
                    di.resolve(SchedulerStoragePort)
                    if SchedulerStoragePort in di
                    else None
                )
                if scheduler_storage is not None:
                    await scheduler_storage.close()

    app.router.lifespan_context = _server_lifespan


__all__ = [
    "create_server_api_router",
    "create_server_app",
]
