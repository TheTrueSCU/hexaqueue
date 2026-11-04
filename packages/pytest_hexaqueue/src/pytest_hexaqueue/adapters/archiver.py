"""Factory for workspace archiver selection.

Notes/Architectural Intent:
    Inspects target workspace topology and vends the optimal archiver adapter:
    GitWorkspaceArchiver for Git repositories, falling back to GenericWorkspaceArchiver
    for bare directories and non-VCS environments.
"""

from pathlib import Path

from pytest_hexaqueue.adapters.generic_archiver import GenericWorkspaceArchiver
from pytest_hexaqueue.adapters.git_archiver import GitWorkspaceArchiver
from pytest_hexaqueue.ports.archiver import WorkspaceArchiverPort


def create_workspace_archiver(root_dir: Path | None = None) -> WorkspaceArchiverPort:
    """Instantiate appropriate workspace archiver based on directory characteristics.

    Args:
        root_dir: Optional root path to inspect (defaults to current working directory).

    Returns:
        Configured WorkspaceArchiverPort instance (GitWorkspaceArchiver or GenericWorkspaceArchiver).
    """
    target = Path(root_dir).resolve() if root_dir is not None else Path.cwd().resolve()
    git_dir = target / ".git"
    if git_dir.exists():
        return GitWorkspaceArchiver()
    return GenericWorkspaceArchiver()


__all__ = [
    "create_workspace_archiver",
]
