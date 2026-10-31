"""In-memory and structured boundary audit logger adapter.

Notes/Architectural Intent:
    Implements BoundaryAuditLoggerPort for zero-trust boundary tracking.
    Captures access events in-memory for testing/diagnostics and emits structured
    JSON lines via Python logging for SIEM ingestion.
"""

from __future__ import annotations

import collections
import logging

from hexaqueue_core.domain.security import BoundaryAuditRecord
from hexaqueue_core.ports.security import BoundaryAuditLoggerPort

audit_logger = logging.getLogger("hexaqueue.audit")


class InMemoryBoundaryAuditLoggerAdapter(BoundaryAuditLoggerPort):
    """In-memory boundary access logger and SIEM structured emitter.

    Args:
        max_records: Maximum count of recent audit records retained in memory.
        emit_structured_log: Whether to output structured JSON to the 'hexaqueue.audit' logger.
    """

    def __init__(
        self,
        max_records: int = 1000,
        emit_structured_log: bool = True,
    ) -> None:
        self._records: collections.deque[BoundaryAuditRecord] = collections.deque(
            maxlen=max_records
        )
        self._emit_structured_log = emit_structured_log

    async def log_access(self, record: BoundaryAuditRecord) -> None:
        """Record an immutable access event for security audit and SIEM forwarding.

        Args:
            record: BoundaryAuditRecord instance.
        """
        self._records.append(record)
        if self._emit_structured_log:
            audit_logger.info(record.to_siem_json())

    async def get_recent_records(self, limit: int = 100) -> list[BoundaryAuditRecord]:
        """Retrieve recent audit access records ordered chronologically.

        Args:
            limit: Maximum count of records to return.

        Returns:
            List of BoundaryAuditRecord items.
        """
        recs = list(self._records)
        return recs[-limit:] if limit > 0 else recs


__all__ = [
    "InMemoryBoundaryAuditLoggerAdapter",
]
