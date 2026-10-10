"""FastAPI application factory and APIRouter assembly for Hexaqueue Server.

Notes/Architectural Intent:
    Composes individual domain sub-routers into a unified `/v1` prefix router and
    wires container dependencies with the CQRS ExecutionPipeline.
"""

from fastapi import APIRouter, FastAPI
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.infra import create_fastapi_app
from rodi import Container

from hexaqueue_server.adapters.api.budget import create_budget_router
from hexaqueue_server.adapters.api.cluster import create_cluster_router
from hexaqueue_server.adapters.api.jobs import create_jobs_router
from hexaqueue_server.adapters.api.logs import create_logs_router
from hexaqueue_server.adapters.api.nodes import create_nodes_router
from hexaqueue_server.adapters.api.runs import create_runs_router
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


def create_server_api_router() -> APIRouter:
    """Construct the FastAPI APIRouter providing unified REST endpoints for Hexaqueue.

    Returns:
        APIRouter with all /v1 endpoints bound to CQRS pipeline dispatch.
    """
    router = APIRouter(prefix="/v1")
    router.include_router(create_runs_router())
    router.include_router(create_jobs_router())
    router.include_router(create_logs_router())
    router.include_router(create_nodes_router())
    router.include_router(create_cluster_router())
    router.include_router(create_budget_router())
    return router


def create_server_app(
    pipeline: ExecutionPipeline | None = None,
) -> FastAPI:
    """Create a fully assembled FastAPI application for Hexaqueue Server.

    Args:
        pipeline: Optional pre-configured ExecutionPipeline.

    Returns:
        Configured FastAPI application instance.
    """
    effective_pipeline = pipeline
    if effective_pipeline is None:
        from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
        from hexaqueue_monitor.adapters.ledger import InMemoryBudgetLedgerAdapter
        from hexaqueue_monitor.adapters.local import LocalClusterMonitorAdapter

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

    container = Container()
    container.register(ExecutionPipeline, instance=effective_pipeline)

    app = create_fastapi_app(container=container, pipeline=effective_pipeline)
    api_router = create_server_api_router()
    app.include_router(api_router)
    return app


__all__ = [
    "create_server_api_router",
    "create_server_app",
]
