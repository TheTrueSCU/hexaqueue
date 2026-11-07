"""Cluster test slice lease coordinator and worker dispatch engine.

Notes/Architectural Intent:
    Orchestrates pull-based distributed test slice execution across scale-to-zero
    compute worker pools. Manages worker node registrations, time-bounded slice
    leases with automatic heartbeat-driven renewal, OCI Pre-Authenticated Request
    (PAR) URL vending for content-addressable storage (CAS) collateral and coverage,
    and automatic re-enqueueing on worker dropouts.
"""

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

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
from hexaqueue_core.ports.storage import PresignedStoragePort


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
    ) -> None:
        self._storage_port = storage_port
        self._collateral_service = collateral_service
        self._default_ttl = default_lease_ttl_seconds

        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(lock=self._lock)

        # Worker tracking
        self._registered_workers: dict[str, WorkerRegistration] = {}
        self._worker_last_seen: dict[str, datetime] = {}

        # Queue tracking
        self._pending_tasks: deque[SliceTaskDescriptor] = deque()
        self._active_leases: dict[str, SliceLease] = {}

        # Session completion tracking
        self._session_total_slices: dict[str, int] = {}
        self._session_reports: dict[str, list[SliceOutcomeResponse]] = {}
        self._session_events: dict[str, asyncio.Event] = {}

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

    async def register_worker(self, reg: WorkerRegistration) -> None:
        """Register or update an active compute worker node.

        Args:
            reg: Worker registration metadata.
        """
        async with self._lock:
            self._registered_workers[reg.worker_id] = reg
            self._worker_last_seen[reg.worker_id] = datetime.now(UTC)

    async def record_heartbeat(
        self,
        worker_id: str,
        active_lease_ids: list[str] | None = None,
    ) -> bool:
        """Record worker pulse and automatically renew active leases.

        Args:
            worker_id: Worker node identifier.
            active_lease_ids: List of lease IDs currently executing on this worker.

        Returns:
            True if worker is registered, False otherwise.
        """
        now = datetime.now(UTC)
        async with self._lock:
            if worker_id not in self._registered_workers:
                return False
            self._worker_last_seen[worker_id] = now
            if active_lease_ids:
                for l_id in active_lease_ids:
                    if l_id in self._active_leases:
                        lease = self._active_leases[l_id]
                        if lease.worker_id == worker_id:
                            self._active_leases[l_id] = lease.renew(self._default_ttl)
            return True

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
        collateral_url = None
        if collateral_id and self._collateral_service is not None:
            get_url_fn = getattr(self._collateral_service, "get_download_url", None)
            if callable(get_url_fn):
                try:
                    collateral_url = await get_url_fn(collateral_id)
                except Exception:
                    collateral_url = None

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

        async with self._condition:
            self._session_total_slices[session_id] = total
            self._session_reports[session_id] = []
            self._session_events[session_id] = completion_event
            for t in tasks:
                self._pending_tasks.append(t)
            self._condition.notify_all()

        return completion_event

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
            return lease

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

            return True

    async def reclaim_expired_leases(self) -> list[str]:
        """Scan active leases, reclaim any that timed out, and re-enqueue slices.

        Returns:
            List of reclaimed lease IDs.
        """
        reclaimed: list[str] = []
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
                # Re-enqueue at the front of the queue
                self._pending_tasks.appendleft(lease.task)
            if reclaimed:
                self._condition.notify_all()
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
