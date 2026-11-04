"""Unit tests for create_workspace_archiver factory."""

from pathlib import Path

from pytest_hexaqueue.adapters.archiver import create_workspace_archiver
from pytest_hexaqueue.adapters.generic_archiver import GenericWorkspaceArchiver
from pytest_hexaqueue.adapters.git_archiver import GitWorkspaceArchiver


def test_create_workspace_archiver_git(tmp_path: Path) -> None:
    """Verify factory returns GitWorkspaceArchiver when .git directory exists."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    archiver = create_workspace_archiver(tmp_path)
    is_git = isinstance(archiver, GitWorkspaceArchiver)
    assert is_git is True


def test_create_workspace_archiver_generic(tmp_path: Path) -> None:
    """Verify factory returns GenericWorkspaceArchiver when no .git directory exists."""
    archiver = create_workspace_archiver(tmp_path)
    is_generic = isinstance(archiver, GenericWorkspaceArchiver)
    assert is_generic is True
