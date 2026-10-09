"""Unit tests for pipeline run and test suite CQRS handlers."""

from typing import Any

import pytest

from hexaqueue_core.domain.cqrs import (
    CancelRunCommand,
    GetRunStatusQuery,
    SubmitRunCommand,
    SubmitSuiteCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.domain.suite import SuiteSpec, TaskSpec


def test_submit_run_and_status(hermetic_cqrs_pipeline: tuple[Any, Any]) -> None:
    """Verify submitting a run via CQRS and querying its status."""
    _, pipeline = hermetic_cqrs_pipeline
    run_spec = RunSpec(id="run-100", name="Test Pipeline")
    job = JobSpec(
        id="job-101",
        run_id="run-100",
        name="task-a",
        command="echo task-a",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
        tags=["owner:alice"],
    )
    cmd = SubmitRunCommand(
        run_spec=run_spec,
        jobs=[job],
        user_id="alice",
        elevate=False,
    )
    report = pipeline.execute(cmd)
    run_id = report.run_id
    total_jobs = report.total_jobs
    assert run_id == "run-100"
    assert total_jobs == 1

    qry = GetRunStatusQuery(run_id="run-100", user_id="alice")
    status_report = pipeline.execute(qry)
    status_run_id = status_report.run_id
    status_total_jobs = status_report.total_jobs
    assert status_run_id == "run-100"
    assert status_total_jobs == 1


def test_submit_suite_command(hermetic_cqrs_pipeline: tuple[Any, Any]) -> None:
    """Verify submitting a hierarchical suite workload via CQRS."""
    _, pipeline = hermetic_cqrs_pipeline
    suite = SuiteSpec(
        id="suite-alpha",
        name="Alpha Suite",
        tasks=[TaskSpec(id="task-1", command="echo matrix")],
    )
    cmd = SubmitSuiteCommand(suite_spec=suite, user_id="bob", elevate=False)
    report = pipeline.execute(cmd)
    run_id = report.run_id
    total_jobs = report.total_jobs
    assert run_id == "suite-alpha"
    assert total_jobs == 1

    # Suite without explicit name falls back to suite ID
    suite_unnamed = SuiteSpec(
        id="suite-beta",
        name=None,
        tasks=[TaskSpec(id="task-2", command="echo beta")],
    )
    cmd2 = SubmitSuiteCommand(suite_spec=suite_unnamed, user_id="bob", elevate=False)
    report2 = pipeline.execute(cmd2)
    run_id2 = report2.run_id
    total_jobs2 = report2.total_jobs
    assert run_id2 == "suite-beta"
    assert total_jobs2 == 1


def test_cancel_run_and_status_permissions(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify cross-tenant run cancellation and status querying requires elevation."""
    _, pipeline = hermetic_cqrs_pipeline
    run_spec = RunSpec(id="run-secure-1", name="Secure Pipeline")
    job = JobSpec(
        id="job-sec-1",
        run_id="run-secure-1",
        name="secure-job",
        command="sleep 100",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
        tags=["owner:alice"],
    )
    pipeline.execute(SubmitRunCommand(run_spec=run_spec, jobs=[job], user_id="alice"))

    # Status check by non-owner without elevate -> rejected
    with pytest.raises(PermissionDeniedError) as exc_info:
        pipeline.execute(
            GetRunStatusQuery(run_id="run-secure-1", user_id="charlie", elevate=False)
        )
    err_str = str(exc_info.value)
    assert "Permission denied: You do not have access to run 'run-secure-1'" in err_str

    # Cancel run by non-owner without elevate -> rejected
    with pytest.raises(PermissionDeniedError):
        pipeline.execute(
            CancelRunCommand(run_id="run-secure-1", user_id="charlie", elevate=False)
        )

    # Cancel run with elevate=True -> succeeds
    rep = pipeline.execute(
        CancelRunCommand(run_id="run-secure-1", user_id="charlie", elevate=True)
    )
    assert rep.run_id == "run-secure-1"
