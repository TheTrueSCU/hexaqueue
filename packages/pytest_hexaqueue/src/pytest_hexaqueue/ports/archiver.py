"""Port interface for workspace packaging and Content-Addressed Storage (CAS) archiving.

Notes/Architectural Intent:
    Defines the contract for creating reproducible, sanitized workspace archives
    for remote collateral staging and distributed execution across cluster workers.
"""

from abc import ABC, abstractmethod
from pathlib import Path


class WorkspaceArchiverPort(ABC):
    """Abstract port for packaging workspace code into compressed collateral bundles.

    Notes/Architectural Intent:
        Enforces reproducible, sanitized workspace snapshots by archiving source
        and test files while excluding runtime caches, virtual environments, and
        ephemeral artifacts.
    """

    @abstractmethod
    def archive_workspace(
        self,
        root_dir: Path,
        excludes: set[str] | None = None,
    ) -> tuple[bytes, str]:
        """Package a workspace directory tree into a compressed tar.gz archive.

        Args:
            root_dir: Root directory of the workspace under test.
            excludes: Optional set of directory and file name patterns to exclude.

        Returns:
            Tuple of (compressed_tar_bytes, sha256_hexdigest).

        Raises:
            FileNotFoundError: If root_dir does not exist or is not a directory.
        """


__all__ = [
    "WorkspaceArchiverPort",
]
