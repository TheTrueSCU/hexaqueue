"""Unit tests verifying WorkspaceArchiverPort interface contracts."""

import inspect

from pytest_hexaqueue.ports.archiver import WorkspaceArchiverPort


def test_archiver_port_is_abstract() -> None:
    """Verify WorkspaceArchiverPort is an abstract ABC."""
    is_abs = inspect.isabstract(WorkspaceArchiverPort)
    assert is_abs is True


def test_archiver_port_defines_operations() -> None:
    """Verify expected abstract methods are declared on port."""
    methods = WorkspaceArchiverPort.__abstractmethods__
    has_archive = "archive_workspace" in methods
    assert has_archive is True
