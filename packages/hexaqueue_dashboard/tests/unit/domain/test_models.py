"""Unit tests for Hexaqueue Web Dashboard domain models."""

from hexaqueue_core.domain.collateral import CollateralKind, CollateralTier
from hexaqueue_dashboard.domain.models import (
    DashboardBastionRequest,
    DashboardCollateralRequest,
    DashboardJobAction,
    DashboardOverviewReport,
    DashboardUserSession,
)


def test_dashboard_user_session_defaults() -> None:
    """Verify default session construction and elevation flag."""
    session = DashboardUserSession()
    user_id = session.user_id
    is_admin = session.is_admin
    elevated = session.elevated
    assert user_id == "default"
    assert is_admin is False
    assert elevated is False

    admin_session = DashboardUserSession(user_id="alice", is_admin=True, elevated=True)
    assert admin_session.user_id == "alice"
    assert admin_session.is_admin is True
    assert admin_session.elevated is True


def test_dashboard_job_action_model() -> None:
    """Verify job action serialization and elevation flag."""
    action = DashboardJobAction(
        action="hold", reason="Investigating spike", elevate=True
    )
    assert action.action == "hold"
    assert action.reason == "Investigating spike"
    assert action.elevate is True


def test_dashboard_collateral_request_model() -> None:
    """Verify collateral request defaults and attributes."""
    req = DashboardCollateralRequest(
        name="model.bin",
        size_bytes=2048,
        checksum_sha256="a" * 64,
        tier=CollateralTier.PERMANENT,
        kind=CollateralKind.TEST_BINARY,
    )
    assert req.name == "model.bin"
    assert req.size_bytes == 2048
    assert req.checksum_sha256 == "a" * 64
    assert req.tier == CollateralTier.PERMANENT
    assert req.kind == CollateralKind.TEST_BINARY


def test_dashboard_bastion_and_overview_models() -> None:
    """Verify bastion request and cluster overview summary report."""
    bastion = DashboardBastionRequest(node_id="worker-01", elevate=True)
    assert bastion.node_id == "worker-01"
    assert bastion.elevate is True

    overview = DashboardOverviewReport(
        total_jobs=10,
        running_jobs=4,
        pending_jobs=6,
        active_workers=2,
    )
    assert overview.total_jobs == 10
    assert overview.running_jobs == 4
    assert overview.pending_jobs == 6
    assert overview.active_workers == 2
