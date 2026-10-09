"""Shared pytest fixtures for api presentation unit tests."""

import asyncio
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.adapters.api.app import create_server_app
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


@pytest.fixture
def hermetic_api_client() -> Generator[TestClient]:
    """Hermetic fixture providing a clean FastAPI TestClient."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    seed_job = JobSpec(
        id="job-api-1",
        run_id="run-api-seed",
        name="task-api",
        command="echo seed",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
        tags=["owner:alice"],
    )
    run_spec = RunSpec(id="run-api-seed", name="seed-run", tags=["owner:alice"])
    asyncio.run(
        controller.submit_run(RunSubmission(run_spec=run_spec, jobs=[seed_job]))
    )
    log_store: dict[str, list[LogChunk]] = {
        "job-api-1": [
            LogChunk(
                job_id="job-api-1",
                stream="stdout",
                content="Job starting\n",
                offset=0,
            ),
            LogChunk(
                job_id="job-api-1",
                stream="stdout",
                content="Job finished\n",
                offset=1,
            ),
        ]
    }
    pipeline = create_hexaqueue_execution_pipeline(
        controller=controller, log_store=log_store
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN", "1")
    app = create_server_app(pipeline=pipeline)
    with TestClient(app) as client:
        yield client
    monkeypatch.undo()
