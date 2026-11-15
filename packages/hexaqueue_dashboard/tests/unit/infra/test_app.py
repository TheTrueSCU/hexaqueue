"""Unit tests for Hexaqueue Web Dashboard application factory."""

import pytest
from fastapi.testclient import TestClient

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_dashboard.adapters.remote_controller import (
    HttpSchedulerControllerAdapter,
)
from hexaqueue_dashboard.infra.app import (
    create_dashboard_app,
    create_standalone_dashboard_app,
)
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


def test_create_dashboard_app_structure() -> None:
    """Verify application factory attaches pipeline and mounts router."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    app = create_dashboard_app(pipeline=pipeline)

    assert app.title == "Hexaqueue Dashboard"
    assert app.state.pipeline is pipeline

    with TestClient(app) as client:
        resp = client.get("/dashboard/stats")
        assert resp.status_code == 200


def test_create_standalone_dashboard_app_wires_remote_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify standalone factory configures HttpSchedulerControllerAdapter from env."""
    monkeypatch.setenv("HEXAQUEUE_CONTROLLER_URL", "http://127.0.0.1:8123")
    monkeypatch.setenv("HEXAQUEUE_ADMIN_TOKEN", "standalone-token")

    app = create_standalone_dashboard_app(enable_ui=False)

    assert app.title == "Hexaqueue Dashboard"
    assert isinstance(app.state.controller, HttpSchedulerControllerAdapter)
    assert app.state.pipeline is not None
