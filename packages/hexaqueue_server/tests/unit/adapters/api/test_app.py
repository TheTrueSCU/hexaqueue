"""Tests for create_server_api_router and create_server_app factory."""

from fastapi import FastAPI

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_server.adapters.api.app import (
    create_server_app,
)
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


def test_create_server_api_router_mounts_all_subrouters() -> None:
    """Verify router assembly mounts all core endpoint paths under /v1."""
    app = create_server_app()
    paths = set(app.openapi()["paths"].keys())

    assert "/v1/runs" in paths
    assert "/v1/jobs" in paths
    assert "/v1/nodes" in paths
    assert "/v1/nodes/profiles" in paths
    assert "/v1/stats" in paths
    assert "/v1/dlq" in paths
    assert "/v1/fairshare" in paths


def test_create_server_app_default_and_custom_pipeline() -> None:
    """Verify application factory initializes with default or custom pipeline."""
    # Default construction
    app_default = create_server_app()
    assert isinstance(app_default, FastAPI)

    # Custom pipeline construction
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller)
    app_custom = create_server_app(pipeline=pipeline)
    assert isinstance(app_custom, FastAPI)
