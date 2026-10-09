"""Common synchronization utilities, permission validators, and base service for CQRS.

Notes/Architectural Intent:
    Provides thread-safe coroutine execution bridging synchronous CQRS buses to
    asynchronous controllers, tenancy-aware job ownership extraction, and base
    service state declarations.
"""

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any, cast

from hexaqueue_collateral.ports.service import CollateralServicePort
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.ports.budget import BudgetAccountingPort
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_core.ports.storage import PresignedStoragePort
from hexaqueue_monitor.ports.monitor import ClusterMonitorPort
from hexaqueue_server.ports.controller import SchedulerControllerPort
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


def run_coro_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Execute an asynchronous coroutine synchronously, handling running loops safely.

    Args:
        coro: The coroutine to execute.

    Returns:
        The evaluated result of the coroutine.

    Notes/Architectural Intent:
        Prevents 'Event loop is already running' deadlocks by executing on a dedicated
        worker thread when called from within an active asyncio loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if not loop.is_running():
        return loop.run_until_complete(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return cast("T", pool.submit(asyncio.run, coro).result())


def _extract_job_owner(job: JobSpec) -> str:
    """Extract owner identity from job tags or environment variables.

    Args:
        job: Target job specification.

    Returns:
        Resolved owner identity string.
    """
    for tag in job.tags:
        if tag.startswith("owner:"):
            return tag.split(":", 1)[1]
    if getattr(job, "user", "default") != "default":
        return job.user
    return job.env.get("HEXAQUEUE_OWNER", "default")


def _check_job_mutation_permission(
    job: JobSpec, user_id: str, elevate: bool, action_name: str
) -> None:
    """Verify that the user is authorized to mutate a target job.

    Args:
        job: Target job specification.
        user_id: Identity of the actor requesting mutation.
        elevate: Whether explicit administrative elevation was asserted.
        action_name: Human-readable action for error message.

    Raises:
        PermissionDeniedError: If unauthorized cross-tenant mutation is attempted.
    """
    owner = _extract_job_owner(job)
    if owner != user_id and not elevate:
        msg = (
            f"Permission denied: You are not the owner of job '{job.id}' (owned by '{owner}'). "
            f"To {action_name} this job, explicit administrative elevation (--admin / elevate=true) is required."
        )
        raise PermissionDeniedError(msg)


class BaseCqrsService:
    """Base class declaring shared state and dependencies for domain CQRS mixins.

    Notes/Architectural Intent:
        Establishes explicit type annotations for controller, storage port, and
        telemetry registries inherited by modular domain handlers.
    """

    budget_port: BudgetAccountingPort
    cluster_monitor: ClusterMonitorPort
    collateral_service: CollateralServicePort
    controller: SchedulerControllerPort
    log_artifacts: dict[str, dict[str, Any]]
    log_store: dict[str, list[LogChunk]]
    nodes: list[NodeTelemetryPulse]
    storage_port: PresignedStoragePort


__all__ = [
    "_check_job_mutation_permission",
    "_extract_job_owner",
    "BaseCqrsService",
    "run_coro_sync",
]
