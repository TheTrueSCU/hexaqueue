"""FastAPI application factory and APIRouter assembly for Hexaqueue Server.

Notes/Architectural Intent:
    Composes individual domain sub-routers into a unified `/v1` prefix router and
    wires container dependencies with the CQRS ExecutionPipeline.
"""

from fastapi import APIRouter, FastAPI
from hexastack_core.infra.container import create_container
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.infra import create_fastapi_app

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.adapters.security.audit import InMemoryBoundaryAuditLoggerAdapter
from hexaqueue_core.adapters.security.spiffe import PolicySpiffeAuthorizerAdapter
from hexaqueue_core.domain.security import SpiffeAuthorizationPolicy
from hexaqueue_monitor.adapters.ledger import InMemoryBudgetLedgerAdapter
from hexaqueue_monitor.adapters.local import LocalClusterMonitorAdapter
from hexaqueue_server.adapters.api.budget import create_budget_router
from hexaqueue_server.adapters.api.cluster import create_cluster_router
from hexaqueue_server.adapters.api.jobs import create_jobs_router
from hexaqueue_server.adapters.api.logs import create_logs_router
from hexaqueue_server.adapters.api.middleware import ZeroTrustBoundaryMiddleware
from hexaqueue_server.adapters.api.nodes import create_nodes_router
from hexaqueue_server.adapters.api.runs import create_runs_router
from hexaqueue_server.adapters.api.webhooks import create_webhooks_router
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.adapters.mcp import mount_mcp_server
from hexaqueue_server.domain.config import ServerConfig, ServerInterfaceConfig
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


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
    return router


def create_server_app(
    pipeline: ExecutionPipeline | None = None,
    config: ServerConfig | None = None,
) -> FastAPI:
    """Create a fully assembled FastAPI application for Hexaqueue Server.

    Args:
        pipeline: Optional preconfigured CQRS ExecutionPipeline instance.
        config: Optional ServerConfig instance specifying feature flags and interfaces.

    Returns:
        Configured FastAPI application instance.
    """
    server_cfg = config or ServerConfig()
    effective_interfaces = server_cfg.interfaces.apply_feature_flags()
    effective_mcp = server_cfg.mcp.apply_feature_flags()
    server_cfg = server_cfg.model_copy(
        update={"interfaces": effective_interfaces, "mcp": effective_mcp}
    )
    effective_pipeline = pipeline
    if effective_pipeline is None:
        queue = InMemoryJobQueueAdapter()
        budget_port = InMemoryBudgetLedgerAdapter()
        cluster_monitor = LocalClusterMonitorAdapter()
        controller = LocalSchedulerControllerAdapter(
            queue=queue,
            budget_port=budget_port,
            cluster_monitor=cluster_monitor,
        )
        effective_pipeline = create_hexaqueue_execution_pipeline(
            controller,
            budget_port=budget_port,
            cluster_monitor=cluster_monitor,
        )

    container = create_container()
    container.add_instance(effective_pipeline, declared_class=ExecutionPipeline)

    app = create_fastapi_app(container=container, pipeline=effective_pipeline)
    api_router = create_server_api_router(server_cfg.interfaces)
    app.include_router(api_router)
    app.include_router(api_router, prefix="/api")
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

    app.add_middleware(ZeroTrustBoundaryMiddleware)
    return app


__all__ = [
    "create_server_api_router",
    "create_server_app",
]
