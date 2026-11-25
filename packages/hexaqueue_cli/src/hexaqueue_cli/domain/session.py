"""In-process local session and state manager for developer CLI runs.

Notes/Architectural Intent:
    Provides a singleton context holding an in-process LocalSchedulerControllerAdapter,
    LocalSubprocessWorker, and InMemoryJobQueueAdapter for single-binary developer test runs.
"""

import os

from hexaqueue_core.adapters.logging.broadcast import (
    BroadcastLogStreamAdapter,
)
from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.adapters.storage.in_memory import InMemoryStorageVolumeAdapter
from hexaqueue_core.adapters.storage.presigned import InMemoryPresignedStorageAdapter
from hexaqueue_core.domain.config import ExecutionMode
from hexaqueue_core.domain.freetier import FreeTierGovernor
from hexaqueue_core.infra.notification import NotificationDispatcher
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline
from hexaqueue_worker.adapters.local import LocalSubprocessWorker
from hexaqueue_worker.adapters.pty import LocalPtyBridgeAdapter
from hexaqueue_worker.adapters.telemetry import LocalTelemetryCollector
from hexaqueue_worker.domain.models import WorkerConfig


class LocalCliSession:
    """Manages an active local in-process cluster session for hq commands."""

    def __init__(
        self,
        concurrency: int = 4,
        notification_dispatcher: NotificationDispatcher | None = None,
        mode: ExecutionMode | None = None,
        governor: FreeTierGovernor | None = None,
    ) -> None:
        self.queue = InMemoryJobQueueAdapter()
        self.storage = InMemoryStorageVolumeAdapter()
        self.log_stream = BroadcastLogStreamAdapter()
        self.telemetry = LocalTelemetryCollector()
        self.pty = LocalPtyBridgeAdapter()
        self.notification_dispatcher = (
            notification_dispatcher or NotificationDispatcher()
        )

        resolved_mode = mode or (
            ExecutionMode.FREE_TIER
            if os.environ.get("HQ_EXECUTION_MODE", "").upper() == "FREE_TIER"
            else ExecutionMode.DEVELOPMENT
        )
        self.controller = LocalSchedulerControllerAdapter(
            queue=self.queue,
            notification_dispatcher=self.notification_dispatcher,
            governor=governor,
            mode=resolved_mode,
        )
        self.presigned_storage = InMemoryPresignedStorageAdapter()
        self.pipeline = create_hexaqueue_execution_pipeline(
            controller=self.controller,
            storage_port=self.presigned_storage,
        )
        self.collateral_service = getattr(
            getattr(self.pipeline, "service", None), "collateral_service", None
        )
        if self.collateral_service is not None:
            self.controller._collateral_service = self.collateral_service
        self.worker = LocalSubprocessWorker(
            queue=self.queue,
            controller=self.controller,
            storage=self.storage,
            log_port=self.log_stream,
            config=WorkerConfig(concurrency=concurrency, poll_interval_seconds=0.01),
            presigned_storage=self.presigned_storage,
            collateral_service=self.collateral_service,
        )

    async def start(self) -> None:
        """Start worker in background."""
        await self.worker.start()

    async def stop(self) -> None:
        """Stop worker."""
        await self.worker.stop()


# Global default in-process session and controller URL override for CLI runs
_DEFAULT_SESSION: LocalCliSession | None = None
_ACTIVE_CONTROLLER_URL: str | None = None


def _normalize_url(url: str | None) -> str | None:
    """Strip whitespace and trailing slashes from an optional controller URL."""
    if url is None:
        return None
    cleaned = url.strip().rstrip("/")
    return cleaned or None


def get_active_controller_url() -> str | None:
    """Return the active controller URL configured via CLI callback, if any.

    Returns:
        Normalized active controller base URL string, or ``None`` for local mode.

    Notes/Architectural Intent:
        Supports propagation of a root ``hq --url ...`` flag down to subcommands
        without mutating process-wide environment variables.
    """
    return _ACTIVE_CONTROLLER_URL


def set_active_controller_url(url: str | None) -> None:
    """Set or clear the active controller URL override for CLI invocations.

    Args:
        url: Base controller URL string, or ``None`` / blank string to clear.

    Notes/Architectural Intent:
        Called on every root CLI invocation via ``@app.callback`` so explicit
        flag values and implicit defaults never leak across sequential runs.
    """
    global _ACTIVE_CONTROLLER_URL
    _ACTIVE_CONTROLLER_URL = _normalize_url(url)


def resolve_controller_url(explicit_url: str | None = None) -> str | None:
    """Resolve effective remote controller URL using CLI precedence rules.

    Args:
        explicit_url: Explicit ``--url`` / ``--controller-url`` option passed to
            a command or adapter.

    Returns:
        Normalized base controller URL string when remote mode is selected, or
        ``None`` when the CLI should operate against the in-process local session.

    Notes/Architectural Intent:
        Enforces strict configuration precedence:
        explicit flag > root callback ``_ACTIVE_CONTROLLER_URL`` >
        ``HEXAQUEUE_CONTROLLER_URL`` > ``HEXAQUEUE_URL`` > ``None`` (local).
    """
    for candidate in (
        explicit_url,
        _ACTIVE_CONTROLLER_URL,
        os.environ.get("HEXAQUEUE_CONTROLLER_URL"),
        os.environ.get("HEXAQUEUE_URL"),
    ):
        normalized = _normalize_url(candidate)
        if normalized is not None:
            return normalized
    return None


def get_default_session(
    mode: ExecutionMode | None = None,
    governor: FreeTierGovernor | None = None,
    notification_dispatcher: NotificationDispatcher | None = None,
) -> LocalCliSession:
    """Get or initialize the global in-process CLI session."""
    global _DEFAULT_SESSION
    if (
        _DEFAULT_SESSION is None
        or mode is not None
        or governor is not None
        or notification_dispatcher is not None
    ):
        _DEFAULT_SESSION = LocalCliSession(
            mode=mode,
            governor=governor,
            notification_dispatcher=notification_dispatcher,
        )
    return _DEFAULT_SESSION


def set_default_session(session: LocalCliSession | None) -> None:
    """Override or reset the global in-process CLI session."""
    global _DEFAULT_SESSION
    _DEFAULT_SESSION = session


__all__ = [
    "get_active_controller_url",
    "get_default_session",
    "LocalCliSession",
    "resolve_controller_url",
    "set_active_controller_url",
    "set_default_session",
]
