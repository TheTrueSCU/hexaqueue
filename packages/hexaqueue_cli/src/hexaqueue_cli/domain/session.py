"""In-process local session and state manager for developer CLI runs.

Notes/Architectural Intent:
    Provides a singleton context holding an in-process LocalSchedulerControllerAdapter,
    LocalSubprocessWorker, and InMemoryJobQueueAdapter for single-binary developer test runs.
"""

import os

from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.adapters.storage.in_memory import InMemoryStorageVolumeAdapter
from hexaqueue_core.domain.config import ExecutionMode
from hexaqueue_core.domain.freetier import FreeTierGovernor
from hexaqueue_core.infra.notification import NotificationDispatcher
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_worker.adapters.local import LocalSubprocessWorker
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
        self.log_stream = InMemoryLogStreamAdapter()
        if notification_dispatcher is not None:
            self.notification_dispatcher = notification_dispatcher
        else:
            try:
                from hexastack_events.adapters.notifications.apprise import (
                    AppriseNotificationAdapter,
                )

                port = AppriseNotificationAdapter()
            except Exception:
                port = None
            self.notification_dispatcher = NotificationDispatcher(
                notification_port=port
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
        self.worker = LocalSubprocessWorker(
            queue=self.queue,
            controller=self.controller,
            storage=self.storage,
            log_port=self.log_stream,
            config=WorkerConfig(concurrency=concurrency, poll_interval_seconds=0.01),
        )

    async def start(self) -> None:
        """Start worker in background."""
        await self.worker.start()

    async def stop(self) -> None:
        """Stop worker."""
        await self.worker.stop()


# Global default in-process session for CLI runs
_DEFAULT_SESSION: LocalCliSession | None = None


def get_default_session(
    mode: ExecutionMode | None = None,
    governor: FreeTierGovernor | None = None,
) -> LocalCliSession:
    """Get or initialize the global in-process CLI session."""
    global _DEFAULT_SESSION
    if _DEFAULT_SESSION is None or mode is not None or governor is not None:
        _DEFAULT_SESSION = LocalCliSession(mode=mode, governor=governor)
    return _DEFAULT_SESSION


def set_default_session(session: LocalCliSession | None) -> None:
    """Override or reset the global in-process CLI session."""
    global _DEFAULT_SESSION
    _DEFAULT_SESSION = session


__all__ = [
    "get_default_session",
    "LocalCliSession",
    "set_default_session",
]
