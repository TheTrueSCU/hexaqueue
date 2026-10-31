"""Scanner daemon infrastructure bootstrap and factory.

Notes/Architectural Intent:
    Provides factory functions for initializing and wiring the security worker
    daemon, malware scanning engines (ClamAV, YARA), task queues, and collateral services.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hexaqueue_scanner.adapters.clamav import ClamAvDaemonAdapter
from hexaqueue_scanner.adapters.composite import CompositeQuarantineScannerAdapter
from hexaqueue_scanner.adapters.daemon import EventHandler, ScannerDaemonAdapter
from hexaqueue_scanner.adapters.queue import InMemoryScanTaskQueueAdapter
from hexaqueue_scanner.adapters.yara import YaraRuleScannerAdapter
from hexaqueue_scanner.domain.config import ScannerConfig
from hexaqueue_scanner.ports.daemon import ScanTaskQueuePort
from hexaqueue_scanner.ports.engine import MalwareScannerEnginePort

if TYPE_CHECKING:
    from hexaqueue_collateral.ports.service import CollateralServicePort


def create_scanner_daemon(
    config: ScannerConfig | None = None,
    collateral_service: CollateralServicePort | None = None,
    task_queue: ScanTaskQueuePort | None = None,
    engines: list[MalwareScannerEnginePort] | None = None,
    event_handlers: list[EventHandler] | None = None,
    poll_interval_seconds: float = 0.5,
) -> ScannerDaemonAdapter:
    """Instantiate and wire a fully configured ScannerDaemonAdapter.

    Args:
        config: Optional ScannerConfig specifying engine parameters and timeouts.
        collateral_service: Optional CollateralServicePort for bundle promotion and quarantine.
        task_queue: Optional task queue port. If omitted, uses InMemoryScanTaskQueueAdapter.
        engines: Optional list of explicit scanner engines. If omitted, configured engines are wired.
        event_handlers: Optional list of event listener callbacks.
        poll_interval_seconds: Polling loop timeout in seconds.

    Returns:
        Configured ScannerDaemonAdapter ready to start.
    """
    cfg = config or ScannerConfig()
    active_engines = list(engines) if engines is not None else []

    if engines is None:
        # Default ClamAV engine if socket or host is specified
        if cfg.clamav.socket_path or cfg.clamav.host:
            active_engines.append(ClamAvDaemonAdapter(config=cfg.clamav))

        # Default YARA engine if rule paths or inline rules are provided
        if cfg.yara.rule_paths or cfg.yara.inline_rules:
            active_engines.append(YaraRuleScannerAdapter(config=cfg.yara))

    composite = CompositeQuarantineScannerAdapter(engines=active_engines, config=cfg)
    queue = task_queue or InMemoryScanTaskQueueAdapter()

    return ScannerDaemonAdapter(
        composite_scanner=composite,
        task_queue=queue,
        collateral_service=collateral_service,
        event_handlers=event_handlers,
        poll_interval_seconds=poll_interval_seconds,
    )


__all__ = [
    "create_scanner_daemon",
]
