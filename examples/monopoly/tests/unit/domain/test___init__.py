"""Test domain package exports."""

import monopoly.domain


def test_domain_exports() -> None:
    """Verify domain package __all__."""
    has_audit = hasattr(monopoly.domain, "PreemptionAuditRecord")
    assert has_audit is True
    has_phase = hasattr(monopoly.domain, "SimulationPhaseResult")
    assert has_phase is True
    has_workload = hasattr(monopoly.domain, "TenantWorkload")
    assert has_workload is True
