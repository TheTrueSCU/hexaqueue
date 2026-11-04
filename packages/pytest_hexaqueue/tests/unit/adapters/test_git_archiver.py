"""Unit tests for GitWorkspaceArchiver adapter."""

import subprocess
import tarfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytest_hexaqueue.adapters.git_archiver import GitWorkspaceArchiver


def test_git_archiver_excludes_default_patterns() -> None:
    """Verify built-in exclusion check rejects volatile caches and venvs."""
    archiver = GitWorkspaceArchiver()
    assert archiver._should_exclude(Path(".git")) is True
    assert archiver._should_exclude(Path(".venv/lib/python3.12")) is True
    assert archiver._should_exclude(Path("__pycache__/foo.pyc")) is True
    assert archiver._should_exclude(Path("src/module.py")) is False


def test_git_archiver_archives_workspace_mocked(tmp_path: Path) -> None:
    """Verify archiving workspace using mocked git ls-files output."""
    (tmp_path / "hello.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Test", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = b"hello.py\x00README.md\x00"

    archiver = GitWorkspaceArchiver()
    with patch("subprocess.run", return_value=mock_proc):
        archive_bytes, sha256_digest = archiver.archive_workspace(tmp_path)

    has_bytes = len(archive_bytes) > 0
    has_sha = len(sha256_digest) == 64
    assert has_bytes is True
    assert has_sha is True

    # Validate tar.gz contents
    with tarfile.open(fileobj=BytesIO(archive_bytes), mode="r:gz") as tar:
        names = tar.getnames()
        assert "hello.py" in names
        assert "README.md" in names


def test_git_archiver_raises_on_git_failure(tmp_path: Path) -> None:
    """Verify RuntimeError is raised when git ls-files command fails."""
    archiver = GitWorkspaceArchiver()
    with (
        patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(128, ["git"], b"", b"fatal"),
        ),
        pytest.raises(RuntimeError, match="Failed to list git workspace files"),
    ):
        archiver.archive_workspace(tmp_path)
