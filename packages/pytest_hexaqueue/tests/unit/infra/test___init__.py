"""Tests for infra package exports."""

import importlib

import pytest_hexaqueue.infra as infra


def test_infra_exports() -> None:
    """Verify infra exports."""
    reloaded = importlib.reload(infra)
    exports = dir(reloaded)
    assert "pytest_addoption" in exports
    assert "pytest_collection_finish" in exports
    assert "pytest_configure" in exports
    assert "pytest_runtestloop" in exports
    assert "pytest_terminal_summary" in exports
