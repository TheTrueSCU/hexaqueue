"""Pytest plugin hooks for Hexaqueue distributed test execution.

Notes/Architectural Intent:
    Intercepts pytest execution lifecycle (option registration, collection finish,
    test loop, and terminal reporting), slicing test suites and dispatching
    execution partitions across Hexaqueue cluster nodes or multi-CSP free-tier meshes.
"""

import asyncio
import os
import uuid
from typing import Any

import pytest

_SLICES_KEY: pytest.StashKey[list[Any]] = pytest.StashKey()
_REPORTS_KEY: pytest.StashKey[list[Any]] = pytest.StashKey()
_CLIENT_KEY: pytest.StashKey[Any] = pytest.StashKey()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register command-line options and configuration flags for pytest-hexaqueue."""
    group = parser.getgroup("hexaqueue", "Hexaqueue Distributed Test Execution")
    group.addoption(
        "--hexaqueue",
        action="store_true",
        default=False,
        dest="hexaqueue_enabled",
        help="Enable distributed test execution across Hexaqueue cluster workers",
    )
    group.addoption(
        "--hq-server",
        action="store",
        default=os.environ.get("HEXAQUEUE_SERVER_URL", "http://127.0.0.1:8000"),
        dest="hexaqueue_server_url",
        help="Hexaqueue cluster controller base URL",
    )
    group.addoption(
        "--hq-slices",
        action="store",
        type=int,
        default=int(os.environ.get("HEXAQUEUE_SLICES", "4")),
        dest="hexaqueue_slices",
        help="Number of parallel execution slices to partition the suite into",
    )
    group.addoption(
        "--hq-pool",
        action="store",
        default="default",
        dest="hexaqueue_pool",
        help="Target compute instance pool for runner placement",
    )
    group.addoption(
        "--hq-free-tier",
        action="store_true",
        default=False,
        dest="hexaqueue_free_tier",
        help="Enforce zero-cost Multi-CSP Free-Tier mesh execution ($0.00 spend)",
    )
    group.addoption(
        "--hq-fallback",
        action="store_true",
        default=True,
        dest="hexaqueue_fallback",
        help="Fall back to local in-process execution if cluster is unreachable",
    )
    group.addoption(
        "--hq-slicer",
        action="store",
        default="round-robin",
        choices=["round-robin", "file"],
        dest="hexaqueue_slicer",
        help="Test partitioning algorithm: 'round-robin' or 'file'",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers and initialize plugin configuration."""
    config.addinivalue_line(
        "markers",
        "hexaqueue: mark test for execution on Hexaqueue distributed cluster",
    )


def _get_slicer(strategy: str) -> Any:
    """Instantiate configured slicing adapter."""
    from pytest_hexaqueue.adapters.slicer import (
        FileContiguousTestSlicer,
        RoundRobinTestSlicer,
    )

    if strategy == "file":
        return FileContiguousTestSlicer()
    return RoundRobinTestSlicer()


def pytest_collection_finish(session: pytest.Session) -> None:
    """Intercept test collection, extract item metadata, and partition into slices."""
    if not session.config.getoption("hexaqueue_enabled", default=False):
        return

    from pytest_hexaqueue.domain.slice import TestItemInfo

    items: list[TestItemInfo] = []
    for item in session.items:
        markers = [m.name for m in item.iter_markers()]
        items.append(
            TestItemInfo(
                nodeid=item.nodeid,
                file_path=str(item.fspath if hasattr(item, "fspath") else item.path),
                markers=markers,
            )
        )

    num_slices = max(1, session.config.getoption("hexaqueue_slices", default=4))
    slicer_name = session.config.getoption("hexaqueue_slicer", default="round-robin")
    slicer = _get_slicer(slicer_name)

    slices = slicer.slice_items(items, num_slices)
    session.config.stash[_SLICES_KEY] = slices


def pytest_runtestloop(session: pytest.Session) -> bool | None:
    """Execute distributed test loop dispatching slices across cluster workers."""
    if not session.config.getoption("hexaqueue_enabled", default=False):
        return None

    from pytest_hexaqueue.adapters.client import HexaqueueTestDispatchClient
    from pytest_hexaqueue.domain.outcome import SliceOutcomeReport
    from pytest_hexaqueue.domain.slice import (
        TestRunSession,
        TestSliceSpec,
    )
    from pytest_hexaqueue.ports.client import HexaqueueTestDispatchPort

    slices_val = session.config.stash.get(
        _SLICES_KEY, getattr(session.config, "_hexaqueue_slices", None)
    )
    if not slices_val or not isinstance(slices_val, list):
        return None
    slices: list[TestSliceSpec] = slices_val

    server_url = session.config.getoption("hexaqueue_server_url")
    pool = session.config.getoption("hexaqueue_pool")
    free_tier = session.config.getoption("hexaqueue_free_tier", default=False)
    allow_fallback = session.config.getoption("hexaqueue_fallback", default=True)

    client: HexaqueueTestDispatchPort = session.config.stash.get(
        _CLIENT_KEY,
        getattr(
            session.config,
            "_hexaqueue_client",
            HexaqueueTestDispatchClient(server_url=server_url),
        ),
    )

    run_session = TestRunSession(
        session_id=str(uuid.uuid4()),
        total_items=len(session.items),
        total_slices=len(slices),
        slices=slices,
        server_url=server_url,
        pool=pool,
        free_tier=free_tier,
    )

    async def _execute() -> list[SliceOutcomeReport] | None:
        is_healthy = await client.health_check()
        if not is_healthy:
            if allow_fallback:
                return None
            msg = f"Hexaqueue cluster at '{server_url}' is offline and fallback is disabled"
            raise ConnectionError(msg)
        return await client.dispatch_run(run_session)

    try:
        reports = asyncio.run(_execute())
    except Exception as exc:
        if allow_fallback:
            return None
        raise exc

    if reports is None:
        # Fall back to standard local execution
        return None

    session.config.stash[_REPORTS_KEY] = reports
    return True


def pytest_terminal_summary(
    terminalreporter: Any,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    """Format and print distributed execution telemetry summary."""
    if not config.getoption("hexaqueue_enabled", default=False):
        return

    from pytest_hexaqueue.domain.outcome import SliceOutcomeReport

    reports_val = config.stash.get(
        _REPORTS_KEY, getattr(config, "_hexaqueue_reports", None)
    )
    if not reports_val or not isinstance(reports_val, list):
        return
    reports: list[SliceOutcomeReport] = reports_val

    terminalreporter.section("Hexaqueue Distributed Execution Summary")
    free_tier = config.getoption("hexaqueue_free_tier", default=False)
    tier_label = " (Verified $0.00 Multi-CSP Free-Tier)" if free_tier else ""

    terminalreporter.write_line(f"Topology: {len(reports)} Remote Slices{tier_label}")
    for rep in reports:
        prov_label = f" [{rep.provider}]" if rep.provider else ""
        terminalreporter.write_line(
            f"  • {rep.slice_id}{prov_label} -> Worker '{rep.worker_id}': "
            f"{rep.passed_count} passed, {rep.failed_count} failed "
            f"({rep.duration_seconds:.2f}s)"
        )


__all__ = [
    "pytest_addoption",
    "pytest_collection_finish",
    "pytest_configure",
    "pytest_runtestloop",
    "pytest_terminal_summary",
]
