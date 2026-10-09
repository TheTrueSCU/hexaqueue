"""Unit tests for CQRS common utilities and base declarations."""

import asyncio

import pytest

from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_server.infra.cqrs.common import (
    BaseCqrsService,
    _check_job_mutation_permission,
    _extract_job_owner,
    run_coro_sync,
)


def test_run_coro_sync_standard() -> None:
    """Verify run_coro_sync executes async coroutines when no loop is active."""

    async def _async_add(a: int, b: int) -> int:
        return a + b

    val = run_coro_sync(_async_add(3, 4))
    assert val == 7


@pytest.mark.asyncio
async def test_run_coro_sync_inside_running_loop() -> None:
    """Verify run_coro_sync executes safely via ThreadPoolExecutor when called within a running loop."""

    async def _nested_async(msg: str) -> str:
        await asyncio.sleep(0.01)
        return f"echo: {msg}"

    res = run_coro_sync(_nested_async("hello"))
    assert res == "echo: hello"


def test_extract_job_owner() -> None:
    """Verify owner extraction precedence across tags, user, and environment."""
    job_tags = JobSpec(
        id="job-tag",
        run_id="run-1",
        name="task-tags",
        command="true",
        resources=ResourceRequirements(cpus=1, ram_mb=512),
        tags=["cluster:prod", "owner:carol"],
    )
    owner_tags = _extract_job_owner(job_tags)
    assert owner_tags == "carol"

    job_user = JobSpec(
        id="job-u",
        run_id="run-1",
        name="task-user",
        command="true",
        resources=ResourceRequirements(cpus=1, ram_mb=512),
        user="dave",
    )
    owner_user = _extract_job_owner(job_user)
    assert owner_user == "dave"

    job_env = JobSpec(
        id="job-e",
        run_id="run-1",
        name="task-env",
        command="true",
        resources=ResourceRequirements(cpus=1, ram_mb=512),
        env={"HEXAQUEUE_OWNER": "eve"},
    )
    owner_env = _extract_job_owner(job_env)
    assert owner_env == "eve"

    job_default = JobSpec(
        id="job-d",
        run_id="run-1",
        name="task-default",
        command="true",
        resources=ResourceRequirements(cpus=1, ram_mb=512),
    )
    owner_default = _extract_job_owner(job_default)
    assert owner_default == "default"


def test_check_job_mutation_permission() -> None:
    """Verify tenancy permission enforcement for job mutations."""
    job = JobSpec(
        id="job-perm",
        run_id="run-1",
        name="task-perm",
        command="true",
        resources=ResourceRequirements(cpus=1, ram_mb=512),
        tags=["owner:frank"],
    )

    # Owner matches -> succeeds
    _check_job_mutation_permission(
        job, user_id="frank", elevate=False, action_name="mutate"
    )

    # Non-owner with elevate=True -> succeeds
    _check_job_mutation_permission(
        job, user_id="grace", elevate=True, action_name="mutate"
    )

    # Non-owner with elevate=False -> raises PermissionDeniedError
    with pytest.raises(PermissionDeniedError) as exc_info:
        _check_job_mutation_permission(
            job, user_id="grace", elevate=False, action_name="cancel"
        )
    err_msg = str(exc_info.value)
    assert "Permission denied: You are not the owner of job 'job-perm'" in err_msg


def test_base_cqrs_service_type_annotations() -> None:
    """Verify BaseCqrsService attributes are declared."""
    annotations = BaseCqrsService.__annotations__
    assert "controller" in annotations
    assert "log_store" in annotations
    assert "nodes" in annotations
    assert "storage_port" in annotations
    assert "log_artifacts" in annotations
