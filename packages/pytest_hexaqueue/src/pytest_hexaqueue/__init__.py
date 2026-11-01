"""pytest-hexaqueue - Distributed Test Slicing, Remote Execution, and Multi-CSP Free-Tier Runner Plugin."""

import importlib
from typing import Any

__all__ = [
    "adapters",
    "domain",
    "FileContiguousTestSlicer",
    "HexaqueueTestDispatchClient",
    "HexaqueueTestDispatchPort",
    "infra",
    "InMemoryTestDispatchClient",
    "ports",
    "RoundRobinTestSlicer",
    "SliceOutcomeReport",
    "TestItemInfo",
    "TestOutcomeItem",
    "TestRunSession",
    "TestSlicerPort",
    "TestSliceSpec",
    "WorkspaceDeltaBundle",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "FileContiguousTestSlicer": (
        "pytest_hexaqueue.adapters.slicer",
        "FileContiguousTestSlicer",
    ),
    "HexaqueueTestDispatchClient": (
        "pytest_hexaqueue.adapters.client",
        "HexaqueueTestDispatchClient",
    ),
    "HexaqueueTestDispatchPort": (
        "pytest_hexaqueue.ports.client",
        "HexaqueueTestDispatchPort",
    ),
    "InMemoryTestDispatchClient": (
        "pytest_hexaqueue.adapters.client",
        "InMemoryTestDispatchClient",
    ),
    "RoundRobinTestSlicer": (
        "pytest_hexaqueue.adapters.slicer",
        "RoundRobinTestSlicer",
    ),
    "SliceOutcomeReport": ("pytest_hexaqueue.domain.outcome", "SliceOutcomeReport"),
    "TestItemInfo": ("pytest_hexaqueue.domain.slice", "TestItemInfo"),
    "TestOutcomeItem": ("pytest_hexaqueue.domain.outcome", "TestOutcomeItem"),
    "TestRunSession": ("pytest_hexaqueue.domain.slice", "TestRunSession"),
    "TestSlicerPort": ("pytest_hexaqueue.ports.slicer", "TestSlicerPort"),
    "TestSliceSpec": ("pytest_hexaqueue.domain.slice", "TestSliceSpec"),
    "WorkspaceDeltaBundle": ("pytest_hexaqueue.domain.delta", "WorkspaceDeltaBundle"),
}


def __getattr__(name: str) -> Any:
    """Lazily load symbols upon attribute access."""
    if name in _EXPORTS:
        mod_name, attr_name = _EXPORTS[name]
        mod = importlib.import_module(mod_name)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val
    if name in ("adapters", "domain", "infra", "ports"):
        mod = importlib.import_module(f"pytest_hexaqueue.{name}")
        globals()[name] = mod
        return mod
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    """Return public export list including lazy symbols."""
    return sorted(set(list(globals().keys()) + __all__))
