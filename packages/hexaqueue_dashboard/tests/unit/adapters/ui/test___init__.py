"""Smoke test for hexaqueue_dashboard.adapters.ui package exports."""

from hexaqueue_dashboard.adapters import ui as dashboard_ui


def test_ui_package_exports() -> None:
    """Verify key modular UI helpers are exported."""
    assert hasattr(dashboard_ui, "render_login_panel")
    assert hasattr(dashboard_ui, "render_jobs_section")
    assert hasattr(dashboard_ui, "render_runs_section")
    assert hasattr(dashboard_ui, "open_job_inspection_drawer")
    assert hasattr(dashboard_ui, "resolve_run_display_status")
