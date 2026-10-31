"""Unit tests for in-memory boundary audit logger adapter."""

import pytest

from hexaqueue_core.adapters.security.audit import (
    InMemoryBoundaryAuditLoggerAdapter,
)
from hexaqueue_core.domain.security import BoundaryAuditRecord


@pytest.mark.asyncio
async def test_audit_logger_records_and_retrieves() -> None:
    """Verify log_access records items and get_recent_records retrieves them."""
    adapter = InMemoryBoundaryAuditLoggerAdapter(
        max_records=50, emit_structured_log=False
    )

    rec1 = BoundaryAuditRecord(
        action="POST",
        authorization_verdict="ALLOWED",
        caller_spiffe_id="spiffe://hexaqueue.org/worker/1",
        target_boundary="rest:jobs",
        target_resource_id="job-1",
    )
    rec2 = BoundaryAuditRecord(
        action="GET",
        authorization_verdict="DENIED",
        caller_spiffe_id="spiffe://untrusted.org/intruder",
        target_boundary="rest:admin",
        target_resource_id="admin-page",
    )

    await adapter.log_access(rec1)
    await adapter.log_access(rec2)

    records = await adapter.get_recent_records(limit=10)
    cnt = len(records)
    assert cnt == 2
    r1 = records[0]
    assert r1.target_resource_id == "job-1"
    r2 = records[1]
    assert r2.authorization_verdict == "DENIED"

    # Test limit scoping
    limited = await adapter.get_recent_records(limit=1)
    lcnt = len(limited)
    assert lcnt == 1
    assert limited[0].target_resource_id == "admin-page"
