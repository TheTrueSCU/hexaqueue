"""Unit tests for bootstrapper port models and contracts."""

from hexaqueue_core.ports.bootstrap import BootstrapperPort


def test_bootstrapper_port_methods():
    """Verify BootstrapperPort requires configure and register_config lifecycle hooks."""
    assert hasattr(BootstrapperPort, "register_config")
    assert hasattr(BootstrapperPort, "configure")
