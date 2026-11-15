"""Adapters layer for Hexaqueue Web Dashboard."""

from hexaqueue_dashboard.adapters.auth import (
    DashboardAuthManager,
    create_auth_router,
)
from hexaqueue_dashboard.adapters.nicegui_ui import mount_dashboard_ui
from hexaqueue_dashboard.adapters.web import (
    create_dashboard_router,
    get_pipeline,
)

__all__ = [
    "create_auth_router",
    "create_dashboard_router",
    "DashboardAuthManager",
    "get_pipeline",
    "mount_dashboard_ui",
]
