"""Scanner daemon adapter implementing background inspection loop.

Notes/Architectural Intent:
    Orchestrates continuous background queue consumption, multi-engine malware
    evaluation, promotion from staging to active CAS storage, quarantine vault
    isolation, metric accounting, and event publishing.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from hexaqueue_core.domain.collateral import CollateralState
from hexaqueue_scanner.adapters.composite import CompositeQuarantineScannerAdapter
from hexaqueue_scanner.domain.events import (
    CollateralApprovedEvent,
    CollateralQuarantinedEvent,
    CollateralRejectedEvent,
    SecurityScanCompletedEvent,
)
from hexaqueue_scanner.domain.models import CompositeScanReport, ScannerMetrics
from hexaqueue_scanner.ports.daemon import ScannerDaemonPort, ScanTaskQueuePort

if TYPE_CHECKING:
    from hexaqueue_collateral.ports.service import CollateralServicePort

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], Awaitable[None] | None]


class ScannerDaemonAdapter(ScannerDaemonPort):
    """Background security worker daemon adapter.

    Args:
        composite_scanner: CompositeQuarantineScannerAdapter orchestrating scan engines.
        task_queue: ScanTaskQueuePort supplying pending scan tasks.
        collateral_service: Optional CollateralServicePort for bundle metadata and storage transitions.
        event_handlers: Optional list of event callbacks to invoke on scan outcomes.
        poll_interval_seconds: Timeout for queue polling loops in seconds.
    """

    def __init__(
        self,
        composite_scanner: CompositeQuarantineScannerAdapter,
        task_queue: ScanTaskQueuePort,
        collateral_service: CollateralServicePort | None = None,
        event_handlers: list[EventHandler] | None = None,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._composite_scanner = composite_scanner
        self._task_queue = task_queue
        self._collateral_service = collateral_service
        self._event_handlers: list[EventHandler] = list(event_handlers or [])
        self._poll_interval = poll_interval_seconds

        self._worker_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

        # Operational metrics counters
        self._total_scans = 0
        self._approved_scans = 0
        self._quarantined_scans = 0
        self._rejected_scans = 0
        self._error_scans = 0
        self._total_duration_seconds = 0.0

    def add_event_handler(self, handler: EventHandler) -> None:
        """Register an event handler callback.

        Args:
            handler: Callable accepting an event instance.
        """
        self._event_handlers.append(handler)

    async def _emit_event(self, event: Any) -> None:
        """Dispatch an event to all registered event handlers."""
        for handler in self._event_handlers:
            try:
                res = handler(event)
                if inspect.isawaitable(res):
                    await res
            except Exception:
                logger.exception("Error executing security event handler for %s", event)

    async def start(self) -> None:
        """Start the background scanner worker loop."""
        if self._worker_task is not None and not self._worker_task.done():
            logger.warning("Scanner daemon is already running.")
            return

        self._stop_event.clear()
        self._worker_task = asyncio.create_task(
            self._worker_loop(), name="scanner-daemon-worker"
        )
        logger.info("Scanner daemon started successfully.")

    async def stop(self) -> None:
        """Gracefully stop the background scanner worker loop."""
        if self._worker_task is None:
            return

        self._stop_event.set()
        try:
            await asyncio.wait_for(self._worker_task, timeout=5.0)
        except TimeoutError:
            logger.warning("Scanner worker loop timed out during shutdown; canceling.")
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
        finally:
            self._worker_task = None
            logger.info("Scanner daemon stopped.")

    def is_running(self) -> bool:
        """Check whether the background scanner loop is currently running.

        Returns:
            True if daemon loop is active, False otherwise.
        """
        return self._worker_task is not None and not self._worker_task.done()

    def get_metrics(self) -> ScannerMetrics:
        """Retrieve current real-time scanner operational metrics.

        Returns:
            ScannerMetrics snapshot.
        """
        return ScannerMetrics(
            approved_scans=self._approved_scans,
            error_scans=self._error_scans,
            quarantined_scans=self._quarantined_scans,
            rejected_scans=self._rejected_scans,
            total_duration_seconds=self._total_duration_seconds,
            total_scans=self._total_scans,
        )

    async def process_bundle(self, collateral_id: str) -> CompositeScanReport:
        """Process, scan, and orchestrate promotion or quarantine for a collateral bundle.

        Args:
            collateral_id: Identifier of the collateral bundle to scan.

        Returns:
            CompositeScanReport detailing the outcome of the security inspection.

        Raises:
            Exception: Re-raises critical exceptions while recording error metrics.
        """
        start_time = time.monotonic()
        self._total_scans += 1

        try:
            if self._collateral_service is not None:
                bundle = await self._collateral_service.get_bundle(collateral_id)
                report = await self._composite_scanner.generate_report(bundle)
                duration = time.monotonic() - start_time
                self._total_duration_seconds += duration

                if report.is_clean:
                    # Clean - promote to active storage
                    updated_bundle = await self._collateral_service.process_quarantine(
                        collateral_id
                    )
                    self._approved_scans += 1
                    await self._emit_event(
                        CollateralApprovedEvent(
                            active_uri=updated_bundle.active_uri
                            or updated_bundle.staging_uri,
                            collateral_id=collateral_id,
                            duration_seconds=duration,
                            sha256_checksum=updated_bundle.sha256_checksum,
                        )
                    )
                    await self._emit_event(
                        SecurityScanCompletedEvent(
                            collateral_id=collateral_id,
                            duration_seconds=duration,
                            is_clean=True,
                            state=CollateralState.APPROVED,
                        )
                    )
                    return report

                # Threat detected or validation rejected
                quarantine_reason = report.quarantine_reason or "Threat detected"
                has_threat_findings = any(not r.is_clean for r in report.results)

                if not has_threat_findings:
                    # Missing file, corrupt bundle, or configuration failure
                    self._rejected_scans += 1
                    await self._emit_event(
                        CollateralRejectedEvent(
                            collateral_id=collateral_id,
                            reason=quarantine_reason,
                        )
                    )
                    await self._emit_event(
                        SecurityScanCompletedEvent(
                            collateral_id=collateral_id,
                            duration_seconds=duration,
                            is_clean=False,
                            state=CollateralState.REJECTED,
                        )
                    )
                    return report

                # Threat confirmed by one or more engines - isolate in quarantine vault
                updated_bundle = await self._collateral_service.process_quarantine(
                    collateral_id
                )
                self._quarantined_scans += 1
                threat_name = "Unknown"
                scanner_engine = "composite"
                for res in report.results:
                    if not res.is_clean:
                        threat_name = res.threat_name or "Unknown"
                        scanner_engine = res.scanner_engine
                        break

                quarantine_uri = (
                    updated_bundle.staging_uri
                    if isinstance(getattr(updated_bundle, "staging_uri", None), str)
                    else f"quarantine://{collateral_id}"
                )

                await self._emit_event(
                    CollateralQuarantinedEvent(
                        collateral_id=collateral_id,
                        quarantine_uri=quarantine_uri,
                        scanner_engine=scanner_engine,
                        threat_name=threat_name,
                    )
                )
                await self._emit_event(
                    SecurityScanCompletedEvent(
                        collateral_id=collateral_id,
                        duration_seconds=duration,
                        is_clean=False,
                        state=CollateralState.QUARANTINED,
                    )
                )
                return report

            # Standalone fallback mode when no collateral service is wired
            duration = time.monotonic() - start_time
            self._total_duration_seconds += duration
            self._error_scans += 1
            msg = f"Cannot process collateral {collateral_id}: CollateralServicePort not configured"
            logger.error(msg)
            await self._emit_event(
                CollateralRejectedEvent(
                    collateral_id=collateral_id,
                    reason=msg,
                )
            )
            return CompositeScanReport(
                collateral_id=collateral_id,
                duration_seconds=duration,
                is_clean=False,
                quarantine_reason=msg,
            )

        except Exception as exc:
            duration = time.monotonic() - start_time
            self._total_duration_seconds += duration
            self._error_scans += 1
            logger.exception("Error processing collateral bundle %s", collateral_id)
            await self._emit_event(
                CollateralRejectedEvent(
                    collateral_id=collateral_id,
                    reason=f"Scan exception: {exc}",
                )
            )
            raise

    async def _worker_loop(self) -> None:
        """Internal background loop polling tasks and dispatching scans."""
        while not self._stop_event.is_set():
            try:
                collateral_id = await self._task_queue.get_next_task(
                    timeout_seconds=self._poll_interval
                )
                if collateral_id is not None:
                    logger.info("Scanner worker picked up task for %s", collateral_id)
                    await self.process_bundle(collateral_id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in scanner worker loop")
                await asyncio.sleep(self._poll_interval)


__all__ = [
    "ScannerDaemonAdapter",
]
