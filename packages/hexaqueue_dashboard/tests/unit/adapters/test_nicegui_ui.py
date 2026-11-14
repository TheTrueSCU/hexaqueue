"""Unit tests for NiceGUI dashboard UI mounting."""

from __future__ import annotations

from fastapi import FastAPI
from nicegui import app as nicegui_app

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_dashboard.adapters.nicegui_ui import mount_dashboard_ui
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


def test_mount_dashboard_ui_registers_nicegui_and_auth_manager() -> None:
    """Verify mount_dashboard_ui attaches auth_manager and NiceGUI routes."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    app = FastAPI()
    manager = DashboardAuthManager(jwt_secret="test-secret-for-nicegui-mount-32bytes")

    mount_dashboard_ui(app, pipeline, auth_manager=manager, mount_path="/dashboard/ui")

    bound_manager = getattr(app.state, "auth_manager", None)
    assert bound_manager is manager
    route_paths = {getattr(r, "path", "") for r in nicegui_app.routes}
    has_ui_route = "/dashboard/ui" in route_paths
    assert has_ui_route is True
