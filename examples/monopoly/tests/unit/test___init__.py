"""Test monopoly root package exports."""

import monopoly


def test_package_exports() -> None:
    """Verify package __all__ exports."""
    has_adapter = hasattr(monopoly, "BatchSchedulerClusterSimulator")
    assert has_adapter is True
    has_port = hasattr(monopoly, "ClusterSimulatorPort")
    assert has_port is True
    has_audit = hasattr(monopoly, "PreemptionAuditRecord")
    assert has_audit is True
    has_render = hasattr(monopoly, "render_monopoly_report")
    assert has_render is True
    has_run = hasattr(monopoly, "run_monopoly_simulation")
    assert has_run is True
    has_phase = hasattr(monopoly, "SimulationPhaseResult")
    assert has_phase is True
    has_workload = hasattr(monopoly, "TenantWorkload")
    assert has_workload is True
