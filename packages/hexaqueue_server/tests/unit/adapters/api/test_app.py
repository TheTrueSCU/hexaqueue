"""Tests for create_server_api_router and create_server_app factory."""

from fastapi import FastAPI

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_server.adapters.api.app import (
    create_server_app,
)
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


def test_create_server_api_router_mounts_all_subrouters() -> None:
    """Verify router assembly mounts all core endpoint paths under /v1 and /api/v1."""
    app = create_server_app()
    paths = set(app.openapi()["paths"].keys())

    assert "/v1/runs" in paths
    assert "/v1/jobs" in paths
    assert "/v1/nodes" in paths
    assert "/v1/nodes/profiles" in paths
    assert "/v1/stats" in paths
    assert "/v1/dlq" in paths
    assert "/v1/fairshare" in paths

    # Dual prefix compatibility for Hexastack adapters
    assert "/api/v1/runs" in paths
    assert "/api/v1/jobs" in paths
    assert "/api/v1/nodes" in paths
    assert "/api/v1/stats" in paths


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


def test_create_server_app_role_based_filtering() -> None:
    """Verify application factory mounts only role-specified interfaces."""
    from hexaqueue_server.domain.config import ServerConfig, ServerRole

    gateway_app = create_server_app(config=ServerConfig(role=ServerRole.GATEWAY))
    paths = set(gateway_app.openapi()["paths"].keys())
    assert "/v1/webhooks/github" in paths
    assert "/v1/runs" in paths
    assert "/v1/nodes" not in paths
    assert "/v1/budget/balance" not in paths

    worker_app = create_server_app(config=ServerConfig(role=ServerRole.WORKER_API))
    worker_paths = set(worker_app.openapi()["paths"].keys())
    assert "/v1/nodes" in worker_paths
    assert "/v1/jobs/{job_id}/logs" in worker_paths
    assert "/v1/webhooks/github" not in worker_paths
    assert "/v1/runs" not in worker_paths

    mcp_app = create_server_app(config=ServerConfig(role=ServerRole.MCP))
    mcp_routes = [getattr(route, "path", "") for route in mcp_app.routes]
    res_mcp_mounted = any(path.startswith("/mcp") for path in mcp_routes)
    assert res_mcp_mounted is True

    all_app = create_server_app(config=ServerConfig(role=ServerRole.ALL))
    all_routes = [getattr(route, "path", "") for route in all_app.routes]
    res_all_mcp_mounted = any(path.startswith("/mcp") for path in all_routes)
    assert res_all_mcp_mounted is True


def test_create_server_app_feature_flag_disables_mcp() -> None:
    """Verify feature flag disables MCP adapter even when role enables it."""
    import os

    from hexaqueue_server.domain.config import ServerConfig, ServerRole

    os.environ["HQ_INTERFACE_MCP"] = "false"
    try:
        app = create_server_app(config=ServerConfig(role=ServerRole.ALL))
        routes = [getattr(route, "path", "") for route in app.routes]
        res_mcp_mounted = any(path.startswith("/mcp") for path in routes)
        assert res_mcp_mounted is False
    finally:
        os.environ.pop("HQ_INTERFACE_MCP", None)


def test_create_server_app_dedicated_mcp_node() -> None:
    """Verify dedicated MCP node mounts MCP SSE routes with minimal REST surface."""
    from hexaqueue_server.domain.config import ServerConfig, ServerRole

    app = create_server_app(config=ServerConfig(role=ServerRole.MCP))
    routes = [getattr(route, "path", "") for route in app.routes]
    assert any(path.startswith("/mcp") for path in routes)

    openapi_paths = set(app.openapi()["paths"].keys())
    assert "/v1/runs" not in openapi_paths
    assert "/v1/nodes" not in openapi_paths
    assert "/v1/webhooks/github" not in openapi_paths
