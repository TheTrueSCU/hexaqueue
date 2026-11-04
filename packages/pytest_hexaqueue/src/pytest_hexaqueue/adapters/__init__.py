"""Adapter implementations for pytest-hexaqueue."""

from pytest_hexaqueue.adapters.archiver import create_workspace_archiver
from pytest_hexaqueue.adapters.client import (
    HexaqueueTestDispatchClient,
    InMemoryTestDispatchClient,
)
from pytest_hexaqueue.adapters.generic_archiver import GenericWorkspaceArchiver
from pytest_hexaqueue.adapters.git_archiver import GitWorkspaceArchiver
from pytest_hexaqueue.adapters.local_runner import LocalSliceRunner
from pytest_hexaqueue.adapters.slicer import (
    FileContiguousTestSlicer,
    RoundRobinTestSlicer,
)

__all__ = [
    "create_workspace_archiver",
    "FileContiguousTestSlicer",
    "GenericWorkspaceArchiver",
    "GitWorkspaceArchiver",
    "HexaqueueTestDispatchClient",
    "InMemoryTestDispatchClient",
    "LocalSliceRunner",
    "RoundRobinTestSlicer",
]
