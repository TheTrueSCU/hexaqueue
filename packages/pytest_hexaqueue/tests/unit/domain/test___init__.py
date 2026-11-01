"""Tests for domain package exports."""

import pytest_hexaqueue.domain as domain


def test_domain_exports() -> None:
    """Verify domain package exports."""
    exports = dir(domain)
    assert "TestItemInfo" in exports
    assert "TestSliceSpec" in exports
    assert "SliceOutcomeReport" in exports
    assert "TestOutcomeItem" in exports
    assert "WorkspaceDeltaBundle" in exports
