"""Cluster test slice lease coordinator and worker dispatch engine.

Notes/Architectural Intent:
    Orchestrates pull-based distributed test slice execution across scale-to-zero
    compute worker pools. Manages worker node registrations, time-bounded slice
    leases with automatic heartbeat-driven renewal, OCI Pre-Authenticated Request
    (PAR) URL vending for content-addressable storage (CAS) collateral and coverage,
    and automatic re-enqueueing on worker dropouts.
"""

import asyncio
import contextlib
import os
import time
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from hexastack_core.ports.logging import LoggingPort

from hexaqueue_core.domain.coordination import (
    CrossLoopAsyncCondition,
    CrossLoopAsyncLock,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lease import (
    SliceLease,
    SliceLeaseState,
    SliceOutcomeResponse,
    SliceReportPayload,
    SliceTaskDescriptor,
    TestOutcomeRecord,
    TestSliceDispatch,
    WorkerRegistration,
)
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_core.ports.storage import PresignedStoragePort

_CIRCUIT_RANK: dict[str, int] = {
    "CLOSED": 0,
    "HALF_OPEN": 1,
    "OPEN": 2,
}


def _merge_priority_circuits(
    pool_circuits: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return the healthiest circuit breaker summary across ordered fallback pools."""
    if not pool_circuits:
        return {
            "state": "CLOSED",
            "reason": None,
            "retry_after_seconds": 0.0,
            "trip_count": 0,
        }
    return min(
        pool_circuits.values(),
        key=lambda c: (
            _CIRCUIT_RANK.get(str(c.get("state", "CLOSED")).upper(), 0),
            float(c.get("retry_after_seconds", 0.0)),
        ),
    )


def _normalize_pool_ids(
    pool_id: str | None,
    pool_ids: Sequence[str] | None,
) -> list[str]:
    """Deduplicate ordered pool IDs while preserving explicit single-pool compatibility."""
    ordered: list[str] = []
    seen: set[str] = set()
    for candidate in [*(pool_ids or ()), *([pool_id] if pool_id else ())]:
        cleaned = str(candidate).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered


class SliceLeaseCoordinator:
    """Coordinates pull-based slice leasing and aggregation across cluster workers.

    Args:
        storage_port: Optional PresignedStoragePort for vending PAR upload and download links.
        collateral_service: Optional collateral service instance for download URL resolution.
        default_lease_ttl_seconds: Lease duration in seconds before reclamation watchdog triggers.

    Notes/Architectural Intent:
        Completely thread-safe and async-first using asyncio locks and conditions.
        Enables seamless scale-to-zero execution where workers pull slices, report coverage
        to cloud object storage via PARs, and terminate when queues drain.
    """

    def __init__(
        self,
        storage_port: PresignedStoragePort | None = None,
        collateral_service: Any = None,
        default_lease_ttl_seconds: int = 90,
        autoscaler: Any = None,
        pool_id: str | None = None,
        controller: Any = None,
        logger: LoggingPort | None = None,
        log_store: dict[str, list[LogChunk]] | None = None,
        pool_ids: Sequence[str] | None = None,
    ) -> None:
        self._storage_port = storage_port
        self._collateral_service = collateral_service
        self._default_ttl = default_lease_ttl_seconds
        self._autoscaler = autoscaler
        self._pool_ids: list[str] = _normalize_pool_ids(pool_id, pool_ids)
        self._pool_id: str | None = self._pool_ids[0] if self._pool_ids else None
        self._controller = controller
        self._logger = logger
        self._log_store = log_store
        self._reconciler_task: asyncio.Task[None] | None = None
        self._reconciler_stop = False
        self._reconcile_in_progress = False
        self._reconcile_pending = False

        self._lock = CrossLoopAsyncLock()
        self._condition = CrossLoopAsyncCondition(lock=self._lock)

        # Worker tracking
        self._registered_workers: dict[str, WorkerRegistration] = {}
        self._worker_last_seen: dict[str, datetime] = {}
        self._worker_telemetry: dict[str, dict[str, Any]] = {}

        # Queue tracking
        self._pending_tasks: deque[SliceTaskDescriptor] = deque()
        self._active_leases: dict[str, SliceLease] = {}
        self._cancelled_lease_ids: dict[str, float] = {}

        # Session completion tracking
        self._session_total_slices: dict[str, int] = {}
        self._session_reports: dict[str, list[SliceOutcomeResponse]] = {}
        self._session_events: dict[str, asyncio.Event] = {}
        self._session_leased_events: dict[str, asyncio.Event] = {}

    def set_controller(self, controller: Any) -> None:
        """Attach scheduler controller to coordinator for job lifecycle synchronizations.

        Args:
            controller: SchedulerControllerPort instance.
        """
        self._controller = controller

    @property
    def controller(self) -> Any:
        """Return the bound scheduler controller instance."""
        return self._controller

    @property
    def pending_count(self) -> int:
        """Return the number of unleased pending slice tasks."""
        return len(self._pending_tasks)

    @property
    def active_lease_count(self) -> int:
        """Return the number of currently leased slice tasks."""
        return len(self._active_leases)

    @property
    def active_worker_count(self) -> int:
        """Return the count of workers seen within the last 60 seconds."""
        cutoff = datetime.now(UTC) - timedelta(seconds=60)
        return sum(1 for ts in self._worker_last_seen.values() if ts >= cutoff)

    def list_active_workers(
        self, max_age_seconds: float = 60.0
    ) -> list[tuple[WorkerRegistration, int, datetime]]:
        """Return registered workers seen recently along with active lease counts.

        Args:
            max_age_seconds: Maximum age in seconds since last worker heartbeat.

        Returns:
            List of ``(WorkerRegistration, active_lease_count, last_seen)`` tuples.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
        lease_counts: dict[str, int] = {}
        for lease in self._active_leases.values():
            lease_counts[lease.worker_id] = lease_counts.get(lease.worker_id, 0) + 1

        workers: list[tuple[WorkerRegistration, int, datetime]] = []
        for worker_id, reg in self._registered_workers.items():
            last_seen = self._worker_last_seen.get(worker_id, reg.registered_at)
            if last_seen >= cutoff:
                workers.append((reg, lease_counts.get(worker_id, 0), last_seen))
        return workers

    @property
    def autoscaler(self) -> Any:
        """Return the attached instance pool autoscaler, if configured."""
        return self._autoscaler

    def _effective_pool_ids(self) -> list[str]:
        """Return ordered active pool IDs, honoring direct ``_pool_id`` overrides."""
        if self._pool_ids:
            if self._pool_id and self._pool_id not in self._pool_ids:
                return [self._pool_id, *self._pool_ids]
            return list(self._pool_ids)
        return [self._pool_id] if self._pool_id else []

    @property
    def has_autoscaler(self) -> bool:
        """Return whether an instance pool autoscaler is registered."""
        return self._autoscaler is not None and bool(self._effective_pool_ids())

    def get_capacity_readiness(self) -> dict[str, Any]:
        """Evaluate current worker and burst-pool capacity readiness.

        Returns:
            Dictionary containing ``capacity_state`` (``"READY"``, ``"SCALING"``,
            or ``"DEGRADED"``), ``ready`` boolean, ``active_workers``,
            ``pending_slices``, ``active_leases``, ``pool_id``, ``pool_ids``,
            ``pool_circuit``, ``pool_circuits``, and ``budget_strategy``.
        """
        active_workers = self.active_worker_count
        pending = self.pending_count
        active = self.active_lease_count
        pool_ids = self._effective_pool_ids()
        pool_circuits: dict[str, dict[str, Any]] = {}
        if self._autoscaler is not None and hasattr(
            self._autoscaler, "get_pool_circuit_status"
        ):
            for pid in pool_ids:
                pool_circuits[pid] = self._autoscaler.get_pool_circuit_status(pid)

        if (
            self._pool_id is not None
            and len(pool_circuits) == 1
            and self._pool_id in pool_circuits
        ):
            circuit_info = pool_circuits[self._pool_id]
        else:
            circuit_info = _merge_priority_circuits(pool_circuits)

        pacing = (
            getattr(self._autoscaler, "credit_pacing", None)
            if self._autoscaler is not None
            else None
        )
        budget_strategy = pacing.strategy.value if pacing is not None else None

        if active_workers > 0:
            capacity_state = "READY"
            is_ready = True
        elif circuit_info.get("state") == "OPEN":
            capacity_state = "DEGRADED"
            is_ready = False
        elif self.has_autoscaler:
            capacity_state = "SCALING" if pending > 0 else "READY"
            is_ready = True
        else:
            capacity_state = "DEGRADED" if pending > 0 else "READY"
            is_ready = pending == 0

        return {
            "capacity_state": capacity_state,
            "ready": is_ready,
            "active_workers": active_workers,
            "pending_slices": pending,
            "active_leases": active,
            "pool_id": self._pool_id,
            "pool_ids": pool_ids,
            "pool_circuit": circuit_info,
            "pool_circuits": pool_circuits,
            "budget_strategy": budget_strategy,
        }

    def _log_autoscaler_decision(
        self,
        decision: Any,
        pending: int,
        active: int,
    ) -> None:
        """Emit structured info log when an autoscaler decision takes an action."""
        if (
            self._logger is not None
            and decision is not None
            and getattr(decision, "action", "NOOP") != "NOOP"
        ):
            pid = getattr(decision, "pool_id", self._pool_id)
            self._logger.info(
                f"Autoscaler decision for pool {pid}",
                extra={
                    "pool_id": pid,
                    "action": decision.action,
                    "current_nodes": decision.current_nodes,
                    "target_nodes": decision.target_nodes,
                    "pending_jobs": pending,
                    "running_jobs": active,
                    "reason": decision.reason,
                },
            )

    def _any_pool_half_open(self) -> bool:
        """Return True if any configured burst pool circuit is in HALF_OPEN state."""
        if self._autoscaler is None or not hasattr(
            self._autoscaler, "get_pool_circuit_status"
        ):
            return False
        pool_ids = self._effective_pool_ids()
        return any(
            str(
                self._autoscaler.get_pool_circuit_status(pid).get("state", "CLOSED")
            ).upper()
            == "HALF_OPEN"
            for pid in pool_ids
        )

    def _needs_periodic_reconcile(self) -> bool:
        """Return True when pending backlog, active scale-up, or non-CLOSED circuits need checks."""
        if len(self._pending_tasks) > 0:
            return True
        if self._autoscaler is None:
            return False
        pool_ids = self._effective_pool_ids()
        has_work = getattr(self._autoscaler, "has_active_reconciliation_work", None)
        if callable(has_work):
            return bool(has_work(pool_ids))
        started_map = getattr(self._autoscaler, "_scale_up_started_at", {})
        if isinstance(started_map, dict) and any(
            pid in started_map for pid in pool_ids
        ):
            return True
        if hasattr(self._autoscaler, "get_pool_circuit_status"):
            return any(
                self._autoscaler.get_pool_circuit_status(pid).get("state") != "CLOSED"
                for pid in pool_ids
            )
        return False

    def start_reconciler(self, interval_seconds: float | None = None) -> None:
        """Start the background autoscaler reconciliation loop if not already running.

        Args:
            interval_seconds: Optional poll interval override in seconds (useful in tests).

        Notes/Architectural Intent:
            Periodically reconciles ``OPEN -> HALF_OPEN`` circuit recovery and stalled
            ``SCALING`` instance pools even when no new slices or webhooks arrive (#219).
        """
        if self._reconciler_task is not None and not self._reconciler_task.done():
            return
        if interval_seconds is not None:
            interval = max(0.01, float(interval_seconds))
        else:
            raw = os.environ.get(
                "HEXAQUEUE_AUTOSCALER_RECONCILE_INTERVAL_SECONDS", "30.0"
            ).strip()
            try:
                interval = max(1.0, float(raw))
            except ValueError:
                interval = 30.0
        self._reconciler_stop = False

        async def _reconcile_loop() -> None:
            while not self._reconciler_stop:
                try:
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break
                if self._reconciler_stop:
                    break
                if self.has_autoscaler and self._needs_periodic_reconcile():
                    await self._reconcile_autoscaler()

        self._reconciler_task = asyncio.create_task(_reconcile_loop())

    async def stop_reconciler(self) -> None:
        """Stop the background autoscaler reconciliation loop cleanly."""
        self._reconciler_stop = True
        task = self._reconciler_task
        self._reconciler_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def reconcile_capacity(self) -> None:
        """Trigger immediate autoscaler pool reconciliation for current backlog.

        Notes/Architectural Intent:
            Invoked by live control-plane endpoints (such as ``PUT /v1/budget/strategy``)
            after updating runtime pacing policies so burst-pool ceilings take effect
            immediately without waiting for the next queue enqueue or lease event.
        """
        await self._reconcile_autoscaler()

    def get_session_leased_event(self, session_id: str) -> asyncio.Event | None:
        """Return the event that triggers when the first slice of a session is leased."""
        return self._session_leased_events.get(session_id)

    def has_tracked_task(self, task_id: str) -> bool:
        """Return True if task_id matches any pending task or active lease.

        Args:
            task_id: Job, slice, or session identifier to check.

        Returns:
            True when the task is actively queued or leased in coordinator memory.

        Notes/Architectural Intent:
            Allows durable storage hydration to distinguish orphaned non-terminal
            records left behind by an ungraceful restart from live work in memory.
        """
        if any(
            t.slice_id == task_id or t.session_id == task_id
            for t in self._pending_tasks
        ):
            return True
        return any(
            lse.task.slice_id == task_id or lse.task.session_id == task_id
            for lse in self._active_leases.values()
        )

    async def shutdown(self, reason: str = "Controller shutting down") -> int:
        """Stop background reconcilers, evict queued/active slices, and flush cancellations.

        Args:
            reason: Human-readable cancellation reason persisted on drained jobs.

        Returns:
            Total count of pending tasks and active leases drained during shutdown.

        Notes/Architectural Intent:
            Stops the periodic reconciler loop, records evicted leases in the cancelled
            tombstone map so workers terminate child subprocesses on next heartbeat,
            unblocks waiting session callers, and flushes CANCELLED job outcomes to
            durable storage before closing database connections.
        """
        await self.stop_reconciler()
        pending_job_ids: list[str] = []
        active_job_ids: list[str] = []
        now_mono = time.monotonic()

        async with self._condition:
            pending_cnt = len(self._pending_tasks)
            for t in self._pending_tasks:
                if t.task_type == "job":
                    pending_job_ids.append(t.slice_id)
            self._pending_tasks.clear()

            active_cnt = len(self._active_leases)
            for l_id, lse in list(self._active_leases.items()):
                self._cancelled_lease_ids[l_id] = now_mono
                if lse.task.task_type == "job":
                    active_job_ids.append(lse.task.slice_id)
            self._active_leases.clear()

            for event in self._session_events.values():
                if not event.is_set():
                    event.set()
            for leased_event in self._session_leased_events.values():
                if not leased_event.is_set():
                    leased_event.set()

        if self._controller is not None:
            for jid in pending_job_ids:
                with contextlib.suppress(Exception):
                    await self._controller.update_job_outcome(
                        job_id=jid,
                        outcome=TerminalOutcome.CANCELLED,
                        reason=reason,
                        walltime_seconds=0.0,
                    )
            for jid in active_job_ids:
                with contextlib.suppress(Exception):
                    await self._controller.update_job_outcome(
                        job_id=jid,
                        outcome=TerminalOutcome.CANCELLED,
                        reason=reason,
                        walltime_seconds=1.0,
                    )

        return pending_cnt + active_cnt

    async def _reconcile_autoscaler(self) -> None:
        """Coalesce concurrent autoscaler reconciliation triggers into single-flight runs."""
        if self._reconcile_in_progress:
            self._reconcile_pending = True
            return
        self._reconcile_in_progress = True
        try:
            while True:
                self._reconcile_pending = False
                await self._run_reconcile_once()
                if not self._reconcile_pending:
                    break
        finally:
            self._reconcile_in_progress = False

    async def _run_reconcile_once(self) -> None:
        """Execute a single autoscaler reconciliation pass for pending slices and leases."""
        pool_ids = self._effective_pool_ids()
        if self._autoscaler is None or not pool_ids:
            return
        try:
            pending = len(self._pending_tasks)
            active = len(self._active_leases)
            if len(pool_ids) > 1 and hasattr(
                self._autoscaler, "reconcile_priority_pools"
            ):
                decisions = await self._autoscaler.reconcile_priority_pools(
                    pool_ids=pool_ids,
                    pending_jobs=pending,
                    running_jobs=active,
                )
                for decision in decisions:
                    self._log_autoscaler_decision(decision, pending, active)
                return

            primary_id = pool_ids[0]
            decision = await self._autoscaler.reconcile_pool(
                pool_id=primary_id,
                pending_jobs=pending,
                running_jobs=active,
            )
            self._log_autoscaler_decision(decision, pending, active)
        except Exception as err:
            if self._logger is not None:
                self._logger.error(
                    f"Autoscaler reconciliation failed for pool {self._pool_id}",
                    extra={"pool_id": self._pool_id, "pool_ids": pool_ids},
                    exc=err,
                )

    async def register_worker(self, reg: WorkerRegistration) -> None:
        """Register or update an active compute worker node.

        Args:
            reg: Worker registration metadata.
        """
        async with self._lock:
            self._registered_workers[reg.worker_id] = reg
            self._worker_last_seen[reg.worker_id] = datetime.now(UTC)

    def get_worker_telemetry(self, worker_id: str) -> dict[str, Any]:
        """Return latest reported host telemetry for a registered worker.

        Args:
            worker_id: Worker node identifier.

        Returns:
            Dictionary of latest CPU/RAM/scratch/load telemetry metrics (empty if none).
        """
        return dict(self._worker_telemetry.get(worker_id, {}))

    async def record_heartbeat(
        self,
        worker_id: str,
        active_lease_ids: list[str] | None = None,
        telemetry: dict[str, Any] | None = None,
    ) -> bool:
        """Record worker pulse and automatically renew active leases.

        Args:
            worker_id: Worker node identifier.
            active_lease_ids: List of lease IDs currently executing on this worker.
            telemetry: Optional live host telemetry metrics (CPU, RAM, scratch).

        Returns:
            True if worker is registered, False otherwise.
        """
        now = datetime.now(UTC)
        async with self._lock:
            if worker_id not in self._registered_workers:
                return False
            self._worker_last_seen[worker_id] = now
            if telemetry:
                self._worker_telemetry[worker_id] = dict(telemetry)
            if active_lease_ids:
                for l_id in active_lease_ids:
                    if l_id in self._active_leases:
                        lease = self._active_leases[l_id]
                        if lease.worker_id == worker_id:
                            self._active_leases[l_id] = lease.renew(self._default_ttl)
            return True

    async def _resolve_collateral_url(self, collateral_id: str | None) -> str | None:
        """Mint a fresh collateral download URL from the attached collateral service.

        Args:
            collateral_id: Optional CAS collateral bundle identifier.

        Returns:
            Download URL string if available, otherwise ``None``.

        Notes/Architectural Intent:
            Shared by enqueue and lease-grant paths so tasks waiting in queue
            beyond a PAR's TTL receive a fresh presigned URL upon worker lease.
        """
        if not collateral_id or self._collateral_service is None:
            return None
        get_url_fn = getattr(self._collateral_service, "get_download_url", None)
        if not callable(get_url_fn):
            return None
        try:
            url = await get_url_fn(collateral_id)
            return str(url) if url else None
        except Exception:
            return None

    async def enqueue_session_slices(
        self,
        session_id: str,
        slices: list[TestSliceDispatch],
        collateral_id: str | None = None,
        coverage_sources: list[str] | None = None,
        container: bool = False,
        container_image: str | None = None,
    ) -> asyncio.Event:
        """Enqueue partitioned test slices for worker pool execution.

        Args:
            session_id: Distributed test execution session ID.
            slices: List of TestSliceDispatch specifications.
            collateral_id: Optional CAS collateral bundle ID.
            coverage_sources: Optional list of packages/directories for coverage analysis.
            container: Whether slices require container isolation.
            container_image: Container image name if containerized.

        Returns:
            An asyncio.Event that triggers when all slices in this session complete.
        """
        # Resolve collateral download PAR once if available
        collateral_url = await self._resolve_collateral_url(collateral_id)

        tasks: list[SliceTaskDescriptor] = []
        total = len(slices)

        for s in slices:
            coverage_upload_url = None
            if coverage_sources and self._storage_port is not None:
                cov_key = f"coverage/{session_id}/{s.slice_id}.coverage"
                try:
                    coverage_upload_url = (
                        await self._storage_port.generate_presigned_upload_url(
                            key=cov_key,
                            expires_in_seconds=3600,
                        )
                    )
                except Exception:
                    coverage_upload_url = None

            descriptor = SliceTaskDescriptor(
                session_id=session_id,
                slice_id=s.slice_id,
                slice_index=s.slice_index,
                total_slices=total,
                test_nodeids=s.test_nodeids,
                collateral_id=collateral_id,
                collateral_download_url=collateral_url,
                coverage_upload_url=coverage_upload_url,
                coverage_sources=coverage_sources,
                container=container,
                container_image=container_image,
            )
            tasks.append(descriptor)

        completion_event = asyncio.Event()
        leased_event = asyncio.Event()

        async with self._condition:
            self._session_total_slices[session_id] = total
            self._session_reports[session_id] = []
            self._session_events[session_id] = completion_event
            self._session_leased_events[session_id] = leased_event
            for t in tasks:
                self._pending_tasks.append(t)
            self._condition.notify_all()

        if self.has_autoscaler:
            asyncio.create_task(self._reconcile_autoscaler())

        return completion_event

    async def enqueue_job(
        self,
        job: JobSpec,
        collateral_id: str | None = None,
    ) -> None:
        """Enqueue an individual JobSpec for cluster worker execution.

        Args:
            job: Candidate JobSpec to enqueue.
            collateral_id: Optional CAS collateral bundle ID transporting workspace code.

        Notes/Architectural Intent:
            Converts a DAG job specification into a pull-leasable task descriptor,
            vending presigned CAS collateral download links if available.
        """
        cid = collateral_id or (job.collateral_ids[0] if job.collateral_ids else None)
        collateral_url = await self._resolve_collateral_url(cid)

        cwd = None
        if "HEXAQUEUE_CWD" in job.env:
            cwd = job.env["HEXAQUEUE_CWD"]

        descriptor = SliceTaskDescriptor(
            session_id=job.run_id,
            slice_id=job.id,
            slice_index=0,
            total_slices=1,
            command=job.command,
            args=job.args,
            env=job.env,
            cwd=cwd,
            collateral_id=cid,
            collateral_download_url=collateral_url,
            container=job.container is not None,
            container_image=job.container.image if job.container else None,
            task_type="job",
        )

        async with self._condition:
            self._pending_tasks.append(descriptor)
            self._condition.notify_all()

        if self.has_autoscaler:
            asyncio.create_task(self._reconcile_autoscaler())

    async def cancel_task(self, task_id: str) -> bool:
        """Remove queued tasks and evict active leases matching task_id or session_id.

        Args:
            task_id: Task, slice, or session identifier to cancel.

        Returns:
            True if any pending task or active lease was cancelled, False otherwise.

        Notes/Architectural Intent:
            Evicts both queued pending tasks and in-flight active leases so expired
            leases cannot be reclaimed back into PENDING after user cancellation.
            Triggers autoscaler reconciliation when cancellation drains all work.
        """
        should_reconcile = False
        async with self._condition:
            retained: deque[SliceTaskDescriptor] = deque()
            removed = False
            for t in self._pending_tasks:
                if t.slice_id == task_id or t.session_id == task_id:
                    removed = True
                else:
                    retained.append(t)
            self._pending_tasks = retained

            now_mono = time.monotonic()
            expired_cancelled = [
                lid
                for lid, recorded_at in self._cancelled_lease_ids.items()
                if now_mono - recorded_at > 3600.0
            ]
            for lid in expired_cancelled:
                self._cancelled_lease_ids.pop(lid, None)

            evicted_lease_ids = [
                l_id
                for l_id, lse in self._active_leases.items()
                if lse.task.slice_id == task_id or lse.task.session_id == task_id
            ]
            for l_id in evicted_lease_ids:
                self._active_leases.pop(l_id, None)
                self._cancelled_lease_ids[l_id] = now_mono
                removed = True

            session_event = self._session_events.get(task_id)
            if session_event is not None and not session_event.is_set():
                session_event.set()

            should_reconcile = (
                removed
                and self.has_autoscaler
                and len(self._pending_tasks) == 0
                and len(self._active_leases) == 0
            )

        if should_reconcile:
            asyncio.create_task(self._reconcile_autoscaler())

        return removed

    def get_cancelled_lease_ids(self, active_lease_ids: list[str] | None) -> list[str]:
        """Return active worker lease IDs that have been cancelled by coordinator.

        Args:
            active_lease_ids: Optional list of lease IDs reported by a worker heartbeat.

        Returns:
            Subset of ``active_lease_ids`` present in the cancelled-lease tombstone map.

        Notes/Architectural Intent:
            Allows ``/worker/{worker_id}/heartbeat`` responses to push active lease
            cancellation signals to worker agents so orphaned subprocesses terminate
            promptly instead of running to completion after timeout or user cancel.
        """
        if not active_lease_ids:
            return []
        now_mono = time.monotonic()
        return [
            lid
            for lid in active_lease_ids
            if (recorded_at := self._cancelled_lease_ids.get(lid)) is not None
            and now_mono - recorded_at <= 3600.0
        ]

    async def lease_slice(
        self,
        worker_id: str,
        available_ocpus: int = 1,
        timeout_seconds: float = 0.0,
    ) -> SliceLease | None:
        """Lease a pending slice task to a requesting worker.

        Args:
            worker_id: Requesting worker node identifier.
            available_ocpus: Number of free OCPUs on the worker.
            timeout_seconds: Maximum seconds to wait for a slice to be enqueued.

        Returns:
            A SliceLease instance if a slice was granted, or None if queue is empty.
        """
        deadline = datetime.now(UTC) + timedelta(seconds=max(0.0, timeout_seconds))
        await self.reclaim_expired_leases()

        async with self._condition:
            while not self._pending_tasks:
                if timeout_seconds <= 0.0:
                    return None
                remaining = (deadline - datetime.now(UTC)).total_seconds()
                if remaining <= 0.0:
                    return None
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except TimeoutError:
                    return None

            task = self._pending_tasks.popleft()
            now = datetime.now(UTC)
            lease = SliceLease(
                task=task,
                worker_id=worker_id,
                state=SliceLeaseState.LEASED,
                leased_at=now,
                expires_at=now + timedelta(seconds=self._default_ttl),
                last_heartbeat_at=now,
            )
            self._active_leases[lease.lease_id] = lease
            self._worker_last_seen[worker_id] = now
            leased_ev = self._session_leased_events.get(task.session_id)
            if leased_ev is not None and not leased_ev.is_set():
                leased_ev.set()

        if task.collateral_id and self._collateral_service is not None:
            fresh_url = await self._resolve_collateral_url(task.collateral_id)
            if fresh_url:
                task = task.model_copy(update={"collateral_download_url": fresh_url})
                lease = lease.model_copy(update={"task": task})
                async with self._condition:
                    if lease.lease_id in self._active_leases:
                        self._active_leases[lease.lease_id] = lease

        if (
            task.task_type == "job"
            and self._controller is not None
            and hasattr(self._controller, "mark_job_running")
        ):
            with contextlib.suppress(Exception):
                await self._controller.mark_job_running(
                    job_id=task.slice_id,
                    worker_id=worker_id,
                )

        return lease

    @staticmethod
    def _format_failure_reason(report: SliceReportPayload) -> str | None:
        """Build a concise failure reason including stderr/stdout tail on non-zero exit."""
        reason = report.error_message
        if report.exit_code == 0:
            return reason
        if not reason:
            reason = f"Command failed with exit code {report.exit_code}"
        stdout_tail = report.stdout or (
            str(report.outcomes[0].get("stdout") or "") if report.outcomes else ""
        )
        stderr_tail = report.stderr or (
            str(report.outcomes[0].get("stderr") or "") if report.outcomes else ""
        )
        parts: list[str] = [reason]
        if stdout_tail.strip():
            parts.append(f"stdout: {stdout_tail.strip()[-800:]}")
        if stderr_tail.strip():
            parts.append(f"stderr: {stderr_tail.strip()[-400:]}")
        return "\n".join(parts)

    async def append_log_chunks(self, job_id: str, chunks: list[LogChunk]) -> int:
        """Append incremental log chunks for a job into the shared log store.

        Args:
            job_id: Target job identifier.
            chunks: Ordered list of LogChunk entries to append.

        Returns:
            Total number of stored chunks for ``job_id`` after appending.
        """
        if self._log_store is None or not chunks:
            return 0
        async with self._lock:
            buf = self._log_store.setdefault(job_id, [])
            buf.extend(chunks)
            if len(buf) > 2000:
                del buf[: len(buf) - 2000]
            return len(buf)

    def _populate_fallback_logs(self, report: SliceReportPayload) -> None:
        """Store terminal stdout/stderr chunks if no incremental logs were streamed."""
        if self._log_store is None or self._log_store.get(report.slice_id):
            return
        fallback_chunks: list[LogChunk] = []
        now_ts = datetime.now(UTC)
        if report.stdout:
            fallback_chunks.append(
                LogChunk(
                    job_id=report.slice_id,
                    stream="stdout",
                    content=report.stdout,
                    offset=0,
                    timestamp=now_ts,
                )
            )
        if report.stderr:
            fallback_chunks.append(
                LogChunk(
                    job_id=report.slice_id,
                    stream="stderr",
                    content=report.stderr,
                    offset=len(fallback_chunks),
                    timestamp=now_ts,
                )
            )
        if fallback_chunks:
            self._log_store[report.slice_id] = fallback_chunks

    async def report_slice_outcome(self, report: SliceReportPayload) -> bool:
        """Process worker slice outcome report and record completed telemetry.

        Args:
            report: SliceReportPayload sent by worker node.

        Returns:
            True if report was accepted, False if lease was missing or revoked.
        """
        async with self._lock:
            lease = self._active_leases.pop(report.lease_id, None)
            if lease is None:
                return False

            self._populate_fallback_logs(report)

            session_id = lease.task.session_id
            is_pass = report.exit_code == 0
            default_outcome = "passed" if is_pass else "failed"

            outcomes = [
                TestOutcomeRecord(
                    nodeid=o.get("nodeid", "unknown"),
                    outcome=o.get("outcome", default_outcome),
                    duration_seconds=float(
                        o.get("duration_seconds", o.get("duration", 0.0))
                    ),
                    stdout=o.get("stdout") or report.stdout,
                    stderr=o.get("stderr") or report.stderr,
                    longrepr=o.get("longrepr") or report.error_message,
                )
                for o in report.outcomes
            ]
            if not outcomes:
                outcomes = [
                    TestOutcomeRecord(
                        nodeid=nid,
                        outcome=default_outcome,
                        duration_seconds=report.duration_seconds,
                        stdout=report.stdout,
                        stderr=report.stderr,
                        longrepr=report.error_message,
                    )
                    for nid in lease.task.test_nodeids
                ]

            cov_data = report.coverage_data
            if cov_data is None and report.coverage_object_key:
                cov_data = {"coverage_object_key": report.coverage_object_key}

            outcome_resp = SliceOutcomeResponse(
                slice_id=report.slice_id,
                slice_index=lease.task.slice_index,
                worker_id=report.worker_id,
                provider="oci_worker_pool",
                is_free_tier=True,
                coverage_data=cov_data,
                outcomes=outcomes,
                duration_seconds=report.duration_seconds,
            )

            reports = self._session_reports.setdefault(session_id, [])
            reports.append(outcome_resp)

            total = self._session_total_slices.get(session_id, 0)
            if len(reports) >= total:
                event = self._session_events.get(session_id)
                if event is not None and not event.is_set():
                    event.set()
                if self.has_autoscaler and (
                    (len(self._pending_tasks) == 0 and len(self._active_leases) == 0)
                    or (len(self._pending_tasks) > 0 and self._any_pool_half_open())
                ):
                    asyncio.create_task(self._reconcile_autoscaler())

        if lease.task.task_type == "job" and self._controller is not None:
            terminal_outcome = (
                TerminalOutcome.COMPLETED
                if report.exit_code == 0
                else TerminalOutcome.FAILED
            )
            reason = self._format_failure_reason(report)
            with contextlib.suppress(Exception):
                await self._controller.update_job_outcome(
                    job_id=lease.task.slice_id,
                    outcome=terminal_outcome,
                    reason=reason,
                    walltime_seconds=report.duration_seconds,
                )

        return True

    async def reclaim_expired_leases(self) -> list[str]:
        """Scan active leases, reclaim any that timed out, and re-enqueue slices.

        Returns:
            List of reclaimed lease IDs.
        """
        reclaimed: list[str] = []
        reclaimed_job_ids: list[str] = []
        async with self._condition:
            now = datetime.now(UTC)
            expired_ids = [
                l_id
                for l_id, lse in self._active_leases.items()
                if now > lse.expires_at
            ]
            for l_id in expired_ids:
                lease = self._active_leases.pop(l_id)
                reclaimed.append(l_id)
                if lease.task.task_type == "job":
                    reclaimed_job_ids.append(lease.task.slice_id)
                # Re-enqueue at the front of the queue
                self._pending_tasks.appendleft(lease.task)
            if reclaimed:
                self._condition.notify_all()

        if (
            reclaimed_job_ids
            and self._controller is not None
            and hasattr(self._controller, "mark_job_pending")
        ):
            for job_id in reclaimed_job_ids:
                with contextlib.suppress(Exception):
                    await self._controller.mark_job_pending(
                        job_id=job_id,
                        reason="Lease expired; reclaimed for re-execution",
                    )

        return reclaimed

    async def get_session_reports(
        self,
        session_id: str,
    ) -> list[SliceOutcomeResponse]:
        """Retrieve collected outcome reports for a session.

        Args:
            session_id: Session identifier.

        Returns:
            List of completed SliceOutcomeResponse objects.
        """
        async with self._lock:
            return list(self._session_reports.get(session_id, []))


__all__ = [
    "SliceLeaseCoordinator",
]
