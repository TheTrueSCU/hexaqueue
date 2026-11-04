"""Git-based workspace archiver adapter for collateral code transport.

Notes/Architectural Intent:
    Leverages native git tracking to package workspaces into reproducible tar.gz
    collateral bundles. Collects both committed files and active uncommitted changes
    via `git ls-files`, automatically respecting repository .gitignore rules while
    strictly omitting internal VCS state (.git) and runtime secrets.
"""

import hashlib
import io
import subprocess
import tarfile
from pathlib import Path

from pytest_hexaqueue.ports.archiver import WorkspaceArchiverPort

GIT_SAFETY_EXCLUDES: frozenset[str] = frozenset(
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
        ".hypothesis",
        ".import_linter_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".ty_cache",
        ".venv",
        "__pycache__",
        "coverage.xml",
        "node_modules",
        "venv",
    }
)


class GitWorkspaceArchiver(WorkspaceArchiverPort):
    """Packages Git workspaces into deterministic compressed tar.gz collateral bundles.

    Notes/Architectural Intent:
        Uses `git ls-files` to determine tracked and untracked (non-ignored) files,
        guaranteeing that local uncommitted edits are included for test execution
        without bundling ignored artifacts or virtual environments.
    """

    def __init__(self, baseline_excludes: set[str] | None = None) -> None:
        """Initialize Git workspace archiver with safety exclusions.

        Args:
            baseline_excludes: Optional set of filenames or prefixes to exclude.
        """
        self._excludes = (
            set(baseline_excludes)
            if baseline_excludes is not None
            else set(GIT_SAFETY_EXCLUDES)
        )

    def _should_exclude(
        self, rel_path: Path, custom_excludes: set[str] | None = None
    ) -> bool:
        """Evaluate if a relative file path matches exclusion rules.

        Args:
            rel_path: Path relative to repository root.
            custom_excludes: Additional caller-specified exclusions.

        Returns:
            True if path should be skipped, False otherwise.
        """
        combined = self._excludes | (custom_excludes or set())
        for part in rel_path.parts:
            if part in combined:
                return True
            for rule in combined:
                if rule.endswith("*") and part.startswith(rule.rstrip("*")):
                    return True
        return False

    def archive_workspace(
        self,
        root_dir: Path,
        excludes: set[str] | None = None,
    ) -> tuple[bytes, str]:
        """Package a Git workspace directory tree into a compressed tar.gz archive.

        Args:
            root_dir: Root directory of the Git workspace.
            excludes: Optional set of directory and file name patterns to exclude.

        Returns:
            Tuple of (compressed_tar_bytes, sha256_hexdigest).

        Raises:
            FileNotFoundError: If root_dir does not exist or is not a directory.
            RuntimeError: If git command execution fails.
        """
        root = Path(root_dir).resolve()
        if not root.exists() or not root.is_dir():
            msg = f"Workspace root directory does not exist: {root}"
            raise FileNotFoundError(msg)

        custom = set(excludes) if excludes else set()

        try:
            cmd = [
                "git",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ]
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                check=True,
            )
            raw_entries = proc.stdout.split(b"\x00")
            rel_paths = [
                entry.decode("utf-8", errors="replace")
                for entry in raw_entries
                if entry.strip()
            ]
        except (subprocess.SubprocessError, OSError) as exc:
            msg = f"Failed to list git workspace files in '{root}': {exc}"
            raise RuntimeError(msg) from exc

        valid_entries: list[tuple[Path, str]] = []
        for rel_str in sorted(rel_paths):
            rel_path = Path(rel_str)
            if self._should_exclude(rel_path, custom):
                continue
            abs_path = root / rel_path
            if abs_path.is_file() and not abs_path.is_socket():
                valid_entries.append((abs_path, rel_str))

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for abs_path, arcname in valid_entries:
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
    "GIT_SAFETY_EXCLUDES",
    "GitWorkspaceArchiver",
]
