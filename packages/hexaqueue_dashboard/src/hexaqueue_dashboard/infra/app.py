"""FastAPI application factory for Hexaqueue Web Dashboard console.

Notes/Architectural Intent:
    Assembles the dashboard application instance, registering CORS middlewares,
    lifespan orchestrators, and mounting the unified web dashboard router.
"""

from fastapi import FastAPI
from hexastack_cqrs.infra.pipeline import ExecutionPipeline

from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_dashboard.adapters.nicegui_ui import mount_dashboard_ui
from hexaqueue_dashboard.adapters.web import create_dashboard_router


def create_dashboard_app(
    pipeline: ExecutionPipeline,
    *,
    auth_manager: DashboardAuthManager | None = None,
    enable_ui: bool = True,
) -> FastAPI:
    """Create and assemble the Hexaqueue Web Dashboard application.

    Args:
        pipeline: Central CQRS ExecutionPipeline handling commands and queries.
        auth_manager: Optional DashboardAuthManager for JWT/RBAC verification.
        enable_ui: Whether to mount the NiceGUI reactive console at `/dashboard/ui`.

    Returns:
        Configured FastAPI application instance.

    Notes/Architectural Intent:
        The dashboard web application operates as a pure presentation layer,
        storing the shared ExecutionPipeline and DashboardAuthManager in
        application state for injection into route handlers and NiceGUI pages.
    """
    app = FastAPI(
        title="Hexaqueue Dashboard",
        description="Modern web interface, cluster visualizer, and operator console",
        version="0.11.0",
    )
    app.state.pipeline = pipeline
    app.state.auth_manager = auth_manager or DashboardAuthManager()
    router = create_dashboard_router(pipeline=pipeline)
    app.include_router(router)
    if enable_ui:
        mount_dashboard_ui(app, pipeline, auth_manager=app.state.auth_manager)
    return app


__all__ = [
    "create_dashboard_app",
]
