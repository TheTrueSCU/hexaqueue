"""FastAPI application factory for Hexaqueue Web Dashboard console.

Notes/Architectural Intent:
    Assembles the dashboard application instance, registering CORS middlewares,
    lifespan orchestrators, and mounting the unified web dashboard router.
"""

import os

from fastapi import FastAPI
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from pydantic import SecretStr

from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_dashboard.adapters.nicegui_ui import mount_dashboard_ui
from hexaqueue_dashboard.adapters.remote_collateral import (
    HttpCollateralServiceAdapter,
)
from hexaqueue_dashboard.adapters.remote_controller import (
    HttpSchedulerControllerAdapter,
)
from hexaqueue_dashboard.adapters.web import create_dashboard_router
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


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
        version="0.12.2",
    )
    app.state.pipeline = pipeline
    app.state.auth_manager = auth_manager or DashboardAuthManager()
    router = create_dashboard_router(pipeline=pipeline)
    app.include_router(router)
    if enable_ui:
        mount_dashboard_ui(app, pipeline, auth_manager=app.state.auth_manager)
    return app


def create_standalone_dashboard_app(
    controller_url: str | None = None,
    *,
    auth_manager: DashboardAuthManager | None = None,
    enable_ui: bool = True,
) -> FastAPI:
    """Create a standalone dashboard FastAPI app backed by a remote HTTP controller.

    Args:
        controller_url: Base URL of the central hexaqueue-server process.
            Defaults to `HEXAQUEUE_CONTROLLER_URL` or `http://127.0.0.1:8000`.
        auth_manager: Optional DashboardAuthManager for JWT/RBAC verification.
        enable_ui: Whether to mount the NiceGUI reactive console at `/dashboard/ui`.

    Returns:
        Configured standalone FastAPI application instance suitable for uvicorn `--factory`.

    Notes/Architectural Intent:
        Decouples the dashboard lifecycle from the scheduler controller process so
        dashboard restarts or UI upgrades do not interrupt active worker leases.
    """
    resolved_url = controller_url or os.environ.get(
        "HEXAQUEUE_CONTROLLER_URL",
        "http://127.0.0.1:8000",
    )
    raw_admin_token = os.environ.get("HEXAQUEUE_ADMIN_TOKEN")
    admin_token = SecretStr(raw_admin_token) if raw_admin_token else None
    controller = HttpSchedulerControllerAdapter(
        base_url=resolved_url,
        admin_token=admin_token,
    )
    collateral_service = HttpCollateralServiceAdapter(
        base_url=resolved_url,
        admin_token=admin_token,
    )
    pipeline = create_hexaqueue_execution_pipeline(
        controller=controller,
        collateral_service=collateral_service,
    )
    app = create_dashboard_app(
        pipeline=pipeline,
        auth_manager=auth_manager,
        enable_ui=enable_ui,
    )
    app.state.controller = controller
    return app


__all__ = [
    "create_dashboard_app",
    "create_standalone_dashboard_app",
]
