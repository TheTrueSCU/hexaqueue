"""Test infra package exports."""

import monopoly.infra


def test_infra_exports() -> None:
    """Verify infra package __all__."""
    has_render = hasattr(monopoly.infra, "render_monopoly_report")
    assert has_render is True
    has_run = hasattr(monopoly.infra, "run_monopoly_simulation")
    assert has_run is True
