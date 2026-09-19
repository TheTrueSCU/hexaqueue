"""Adapters layer for Hexaqueue Web Dashboard."""

from hexaqueue_dashboard.adapters.web import (
    create_dashboard_router,
    get_pipeline,
)

__all__ = [
    "create_dashboard_router",
    "get_pipeline",
]
