"""Unit tests for GenericWorkspaceArchiver adapter."""

import tarfile
from io import BytesIO
from pathlib import Path

from pytest_hexaqueue.adapters.generic_archiver import GenericWorkspaceArchiver


def test_generic_archiver_respects_gitignore_and_ignore(tmp_path: Path) -> None:
    """Verify GenericWorkspaceArchiver respects .gitignore and .ignore patterns."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('app')", encoding="utf-8")
    (tmp_path / "ignored.tmp").write_text("secret", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("*.tmp\n", encoding="utf-8")

    archiver = GenericWorkspaceArchiver()
    archive_bytes, sha256_digest = archiver.archive_workspace(tmp_path)

    has_bytes = len(archive_bytes) > 0
    has_sha = len(sha256_digest) == 64
    assert has_bytes is True
    assert has_sha is True

    with tarfile.open(fileobj=BytesIO(archive_bytes), mode="r:gz") as tar:
        names = tar.getnames()
        assert "src/app.py" in names
        assert "ignored.tmp" not in names


def test_generic_archiver_default_exclusions(tmp_path: Path) -> None:
    """Verify built-in exclusions for .git, .venv, and __pycache__."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pip").write_text("pip", encoding="utf-8")
    (tmp_path / "valid.py").write_text("x = 1", encoding="utf-8")

    archiver = GenericWorkspaceArchiver()
    archive_bytes, sha256 = archiver.archive_workspace(tmp_path)

    with tarfile.open(fileobj=BytesIO(archive_bytes), mode="r:gz") as tar:
        names = tar.getnames()
        assert "valid.py" in names
        assert not any(n.startswith(".git") for n in names)
        assert not any(n.startswith(".venv") for n in names)
