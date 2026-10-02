"""End-to-end integration tests running Hexaqual test and mutation suites on a local Hexaqueue cluster.

Notes/Architectural Intent:
    Verifies full lifecycle interoperability between Hexaqual's HexaqueueClusterRunnerAdapter
    and Hexaqueue's v0.1.0 local-only cluster (LocalCliSession, LocalSchedulerControllerAdapter,
    LocalSubprocessWorker, and FastAPI REST/SSE endpoints). Mathematically proves that
    distributed job execution, SSE status streaming, and worker process execution complete
    cleanly with exit code 0.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from hexaqueue_cli.domain.session import LocalCliSession
from hexaqueue_server.adapters.api import create_server_app
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


@pytest.mark.asyncio
async def test_hexaqual_executes_pytest_on_local_cluster() -> None:
    """Verify Hexaqual execute_pytest dispatches to local Hexaqueue cluster and succeeds."""
    pytest.importorskip(
        "hexaqual.adapters.runners.hexaqueue_cluster",
        reason="HexaqueueClusterRunnerAdapter requires hexaqual with cluster runner support",
    )
    from hexaqual.adapters.runners.hexaqueue_cluster import (
        HexaqueueClusterRunnerAdapter,
    )

    session = LocalCliSession(concurrency=2)
    await session.start()
    try:
        pipeline = create_hexaqueue_execution_pipeline(session.controller)
        app = create_server_app(pipeline=pipeline)
        with TestClient(app, base_url="http://testcluster") as client:
            adapter = HexaqueueClusterRunnerAdapter(
                cluster_url="http://testcluster",
                http_client=client,
                poll_interval=0.05,
            )
            # Run targeted fast unit test in worker
            exit_code = await asyncio.to_thread(
                adapter.execute_pytest,
                test_nodes=[
                    "packages/hexaqueue_core/tests/unit/domain/test_lifecycle.py"
                ],
                extra_args=["-o", "addopts="],
                cwd=Path(),
            )
            assert exit_code == 0

            # Inspect job status on cluster
            jobs_resp = client.get("/v1/jobs")
            status_code = jobs_resp.status_code
            assert status_code == 200
            jobs = jobs_resp.json()
            num_jobs = len(jobs)
            assert num_jobs == 1
            state = jobs[0]["status"]["state"]
            assert state == "DONE"
            outcome = jobs[0]["status"]["outcome"]
            assert outcome == "COMPLETED"
    finally:
        await session.stop()


@pytest.mark.asyncio
async def test_hexaqual_executes_mutation_testing_on_local_cluster() -> None:
    """Verify Hexaqual run_mutation_testing runs pytest-gremlins on local cluster and succeeds."""
    pytest.importorskip(
        "hexaqual.adapters.runners.hexaqueue_cluster",
        reason="HexaqueueClusterRunnerAdapter requires hexaqual with cluster runner support",
    )
    from hexaqual.adapters.runners.hexaqueue_cluster import (
        HexaqueueClusterRunnerAdapter,
    )
    from hexaqual.domain.testing import MutationEngine

    session = LocalCliSession(concurrency=2)
    await session.start()
    try:
        pipeline = create_hexaqueue_execution_pipeline(session.controller)
        app = create_server_app(pipeline=pipeline)
        with TestClient(app, base_url="http://testcluster") as client:
            adapter = HexaqueueClusterRunnerAdapter(
                cluster_url="http://testcluster",
                http_client=client,
                poll_interval=0.05,
            )
            exit_code = await asyncio.to_thread(
                adapter.run_mutation_testing,
                package_dir=Path("packages/hexaqueue_scanner"),
                engine=MutationEngine.GREMLINS,
                workers=2,
                numprocesses=2,
                batch_size=5,
            )
            assert exit_code == 0

            jobs_resp = client.get("/v1/jobs")
            status_code = jobs_resp.status_code
            assert status_code == 200
            jobs = jobs_resp.json()
            num_jobs = len(jobs)
            assert num_jobs >= 1
            state = jobs[0]["status"]["state"]
            assert state == "DONE"
            outcome = jobs[0]["status"]["outcome"]
            assert outcome == "COMPLETED"
    finally:
        await session.stop()
