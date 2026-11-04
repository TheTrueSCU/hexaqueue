"""Generic filesystem workspace archiver adapter for non-Git environments.

Notes/Architectural Intent:
    Walks filesystem directories to package source trees into reproducible tar.gz
    collateral bundles. Parses .gitignore and .ignore when present via pathspec,
    falling back to universal safety rules for arbitrary non-VCS directories.
"""

import hashlib
import io
import os
import tarfile
from pathlib import Path

import pathspec

from pytest_hexaqueue.ports.archiver import WorkspaceArchiverPort

GENERIC_SAFETY_EXCLUDES: frozenset[str] = frozenset(
    {
        ".benchmarks",
        ".cache",
        ".codegraph",
        ".complexipy_cache",
        ".coverage",
        ".coverage.*",
        ".env",
        ".env.*",
        ".git",
        ".hg",
        ".hypothesis",
        ".import_linter_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".ty_cache",
        ".venv",
        "__pycache__",
        "coverage.xml",
        "env",
        "htmlcov",
        "node_modules",
        "venv",
    }
)


class GenericWorkspaceArchiver(WorkspaceArchiverPort):
    """Packages directory trees into deterministic compressed tar.gz collateral bundles.

    Notes/Architectural Intent:
        Agnostic archiver applicable to non-Git directories, container environments,
        and bare source extractions. Parses .gitignore and .ignore patterns dynamically.
    """

    def __init__(
        self,
        baseline_excludes: set[str] | None = None,
        respect_gitignore: bool = True,
    ) -> None:
        """Initialize generic workspace archiver.

        Args:
            baseline_excludes: Optional set of directory or file names to skip.
            respect_gitignore: Whether to parse and respect .gitignore / .ignore files.
        """
        self._excludes = (
            set(baseline_excludes)
            if baseline_excludes is not None
            else set(GENERIC_SAFETY_EXCLUDES)
        )
        self._respect_gitignore = respect_gitignore

    def _build_spec(self, root: Path, custom_excludes: set[str]) -> pathspec.PathSpec:
        """Compile pathspec matching patterns from baseline, custom, and ignore files.

        Args:
            root: Root directory of workspace.
            custom_excludes: Additional exclusion patterns.

        Returns:
            Compiled pathspec.PathSpec instance.
        """
        lines: list[str] = list(self._excludes | custom_excludes)
        if self._respect_gitignore:
            for ignore_fname in (".gitignore", ".ignore"):
                ignore_path = root / ignore_fname
                if ignore_path.is_file():
                    try:
                        content = ignore_path.read_text(
                            encoding="utf-8", errors="replace"
                        )
                        lines.extend(content.splitlines())
                    except OSError:
                        pass
        return pathspec.PathSpec.from_lines("gitignore", lines)

    def archive_workspace(
        self,
        root_dir: Path,
        excludes: set[str] | None = None,
    ) -> tuple[bytes, str]:
        """Package a workspace directory tree into a compressed tar.gz archive.

        Args:
            root_dir: Root directory of the workspace.
            excludes: Optional set of directory and file name patterns to exclude.

        Returns:
            Tuple of (compressed_tar_bytes, sha256_hexdigest).

        Raises:
            FileNotFoundError: If root_dir does not exist or is not a directory.
        """
        root = Path(root_dir).resolve()
        if not root.exists() or not root.is_dir():
            msg = f"Workspace root directory does not exist: {root}"
            raise FileNotFoundError(msg)

        custom = set(excludes) if excludes else set()
        spec = self._build_spec(root, custom)
        file_entries: list[tuple[Path, str]] = []

        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).relative_to(root)
            # Prune excluded directories in-place to prevent traversing deep cache trees
            dirnames[:] = [
                d
                for d in dirnames
                if not spec.match_file(str((rel_dir / d).as_posix()) + "/")
            ]

            for fname in filenames:
                rel_file = rel_dir / fname
                rel_posix = str(rel_file.as_posix())
                if not spec.match_file(rel_posix):
                    abs_file = Path(dirpath) / fname
                    if not abs_file.is_socket():
                        file_entries.append((abs_file, rel_posix))

        # Sort entries alphabetically for deterministic tar ordering
        file_entries.sort(key=lambda entry: entry[1])

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for abs_path, arcname in file_entries:
                try:
                    tarinfo = tar.gettarinfo(str(abs_path), arcname=arcname)
                    tarinfo.uid = 0
                    tarinfo.gid = 0
                    tarinfo.uname = ""
                    tarinfo.gname = ""
                    tarinfo.mtime = 0
                    if tarinfo.isreg():
                        with abs_path.open("rb") as f:
                            tar.addfile(tarinfo, f)
                    else:
                        tar.addfile(tarinfo)
                except (OSError, PermissionError):
                    continue

        archive_bytes = buffer.getvalue()
        sha256_digest = hashlib.sha256(archive_bytes).hexdigest()
        return archive_bytes, sha256_digest


__all__ = [
    "GENERIC_SAFETY_EXCLUDES",
    "GenericWorkspaceArchiver",
]
