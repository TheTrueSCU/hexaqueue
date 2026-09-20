"""FastAPI application factory for Hexaqueue Web Dashboard console.

Notes/Architectural Intent:
    Assembles the dashboard application instance, registering CORS middlewares,
    lifespan orchestrators, and mounting the unified web dashboard router.
"""

from fastapi import FastAPI
from hexastack_cqrs.infra.pipeline import ExecutionPipeline

from hexaqueue_dashboard.adapters.web import create_dashboard_router


def create_dashboard_app(pipeline: ExecutionPipeline) -> FastAPI:
    """Create and assemble the Hexaqueue Web Dashboard application.

    Args:
        pipeline: Central CQRS ExecutionPipeline handling commands and queries.

    Returns:
        Configured FastAPI application instance.

    Notes/Architectural Intent:
        The dashboard web application operates as a pure presentation layer,
        storing the shared ExecutionPipeline in application state for injection
        into route handlers.
    """
    app = FastAPI(
        title="Hexaqueue Dashboard",
        description="Modern web interface, cluster visualizer, and operator console",
        version="0.4.0",
    )
    app.state.pipeline = pipeline
    router = create_dashboard_router(pipeline=pipeline)
    app.include_router(router)
    return app


__all__ = [
    "create_dashboard_app",
]
