"""Pytest plugin hooks for Hexaqueue distributed test execution.

Notes/Architectural Intent:
    Intercepts pytest execution lifecycle (option registration, collection finish,
    test loop, and terminal reporting), slicing test suites and dispatching
    execution partitions across Hexaqueue cluster nodes or multi-CSP free-tier meshes.
"""

import asyncio
import base64
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pytest

if TYPE_CHECKING:
    from pytest_hexaqueue.domain.outcome import SliceOutcomeReport

_SLICES_KEY: pytest.StashKey[list[Any]] = pytest.StashKey()
_REPORTS_KEY: pytest.StashKey[list[Any]] = pytest.StashKey()
_CLIENT_KEY: pytest.StashKey[Any] = pytest.StashKey()
_CONFIG_KEY: pytest.StashKey[Any] = pytest.StashKey()


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
        "--hq-config",
        action="store",
        default=None,
        dest="hexaqueue_config_file",
        help="Path to Hexaqueue configuration file (pyproject.toml or hexaqueue.yaml)",
    )
    group.addoption(
        "--profile",
        "--hq-profile",
        action="store",
        default=os.environ.get("HEXAQUEUE_PROFILE"),
        dest="hexaqueue_profile",
        help="Active configuration profile to apply (e.g. 'ci', 'container', 'free-tier')",
    )
    group.addoption(
        "--hq-server",
        action="store",
        default=None,
        dest="hexaqueue_server_url",
        help="Hexaqueue cluster controller base URL (overrides config file / env)",
    )
    group.addoption(
        "--hq-token",
        action="store",
        default=None,
        dest="hexaqueue_api_token",
        help="Hexaqueue cluster authentication token (overrides config file / env)",
    )
    group.addoption(
        "--hq-slices",
        action="store",
        type=int,
        default=None,
        dest="hexaqueue_slices",
        help="Number of parallel execution slices to partition the suite into (overrides config file)",
    )
    group.addoption(
        "--hq-pool",
        action="store",
        default=None,
        dest="hexaqueue_pool",
        help="Target compute instance pool for runner placement (overrides config file)",
    )
    group.addoption(
        "--hq-paid",
        action="store_true",
        default=None,
        dest="hexaqueue_paid",
        help="Authorize paid cloud compute (disables zero-cost free-tier guardrails)",
    )
    group.addoption(
        "--hq-free-tier",
        action="store_true",
        default=None,
        dest="hexaqueue_free_tier",
        help="Enforce zero-cost Multi-CSP Free-Tier mesh execution ($0.00 spend ceiling, default: True)",
    )
    group.addoption(
        "--hq-fallback",
        action="store_true",
        default=None,
        dest="hexaqueue_fallback",
        help="Fall back to local in-process execution if cluster is unreachable",
    )
    group.addoption(
        "--no-hq-fallback",
        action="store_false",
        dest="hexaqueue_fallback",
        help="Disable local fallback and fail if cluster is unreachable",
    )
    group.addoption(
        "--hq-slicer",
        action="store",
        default=None,
        choices=["round-robin", "file"],
        dest="hexaqueue_slicer",
        help="Test partitioning algorithm: 'round-robin' or 'file'",
    )
    group.addoption(
        "--hq-container",
        action="store_true",
        default=None,
        dest="hexaqueue_container",
        help="Execute test slices inside isolated OCI container sandboxes (Docker / Podman)",
    )
    group.addoption(
        "--hq-image",
        action="store",
        default=None,
        dest="hexaqueue_worker_image",
        help="Container image tag used for containerized worker execution",
    )


def _is_hexaqueue_enabled(config: pytest.Config) -> bool:
    """Check if Hexaqueue execution is enabled via flag, profile, or env var.

    Args:
        config: Pytest configuration instance.

    Returns:
        True if Hexaqueue execution is enabled; False otherwise.

    Raises:
        None.

    Notes/Architectural Intent:
        Enables Hexaqueue either explicitly via --hexaqueue or implicitly when a named
        configuration profile is supplied (--hq-profile or HEXAQUEUE_PROFILE).
    """
    return bool(
        config.getoption("hexaqueue_enabled", default=False)
        or config.getoption("hexaqueue_profile", default=None)
    )


def _resolve_plugin_config(config: pytest.Config) -> Any:
    """Load configuration file, apply active profile and CLI overrides."""
    from hexaqueue_core.domain.runner_config import (
        load_project_config,
        resolve_runner_config,
    )

    explicit_cfg = config.getoption("hexaqueue_config_file", default=None)
    project_cfg = load_project_config(explicit_path=explicit_cfg)

    cli_overrides: dict[str, Any] = {}
    if config.getoption("hexaqueue_server_url", default=None) is not None:
        cli_overrides["server_url"] = config.getoption("hexaqueue_server_url")
    if config.getoption("hexaqueue_api_token", default=None) is not None:
        cli_overrides["api_token"] = config.getoption("hexaqueue_api_token")
    if config.getoption("hexaqueue_slices", default=None) is not None:
        cli_overrides["slices"] = config.getoption("hexaqueue_slices")
    if config.getoption("hexaqueue_pool", default=None) is not None:
        cli_overrides["pool"] = config.getoption("hexaqueue_pool")
    if config.getoption("hexaqueue_container", default=None) is True:
        cli_overrides["container"] = True
    if config.getoption("hexaqueue_worker_image", default=None) is not None:
        cli_overrides["worker_image"] = config.getoption("hexaqueue_worker_image")
    if config.getoption("hexaqueue_paid", default=None) is not None:
        cli_overrides["paid"] = config.getoption("hexaqueue_paid")
    if config.getoption("hexaqueue_free_tier", default=None) is not None:
        cli_overrides["free_tier"] = config.getoption("hexaqueue_free_tier")
    if config.getoption("hexaqueue_fallback", default=None) is not None:
        cli_overrides["fallback"] = config.getoption("hexaqueue_fallback")
    if config.getoption("hexaqueue_slicer", default=None) is not None:
        cli_overrides["slicer"] = config.getoption("hexaqueue_slicer")

    profile = config.getoption("hexaqueue_profile", default=None)
    return resolve_runner_config(
        project_config=project_cfg,
        profile=profile,
        cli_overrides=cli_overrides,
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers and initialize plugin configuration."""
    config.addinivalue_line(
        "markers",
        "hexaqueue: mark test for execution on Hexaqueue distributed cluster",
    )
    if not _is_hexaqueue_enabled(config):
        return

    # When Hexaqueue handles distributed slice orchestration, disable
    # pytest-xdist local worker loops to prevent runner conflict.
    if hasattr(config.option, "numprocesses"):
        config.option.numprocesses = 0
    if hasattr(config.option, "dist"):
        config.option.dist = "no"

    config.stash[_CONFIG_KEY] = _resolve_plugin_config(config)


def _get_slicer(strategy: str) -> Any:
    """Instantiate configured slicing adapter."""
    from pytest_hexaqueue.adapters.slicer import (
        FileContiguousTestSlicer,
        RoundRobinTestSlicer,
    )

    if strategy == "file":
        return FileContiguousTestSlicer()
    return RoundRobinTestSlicer()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_finish(session: pytest.Session) -> None:
    """Intercept test collection, extract item metadata, and partition into slices."""
    if not _is_hexaqueue_enabled(session.config):
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

    resolved = session.config.stash.get(_CONFIG_KEY, None)
    if resolved is not None:
        num_slices = max(1, resolved.slices)
        slicer_name = resolved.slicer
    else:
        num_slices = max(
            1,
            session.config.getoption("hexaqueue_slices", default=4) or 4,
        )
        slicer_name = (
            session.config.getoption("hexaqueue_slicer", default="round-robin")
            or "round-robin"
        )
    slicer = _get_slicer(slicer_name)

    slices = slicer.slice_items(items, num_slices)
    session.config.stash[_SLICES_KEY] = slices


def _notify_session_reports(
    session: pytest.Session, reports: list["SliceOutcomeReport"]
) -> None:
    """Propagate distributed slice outcomes to pytest session and terminal reporters."""
    total_failed = sum(r.failed_count for r in reports)
    session.testsfailed = getattr(session, "testsfailed", 0) + total_failed
    if total_failed > 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    else:
        session.exitstatus = pytest.ExitCode.OK

    items_by_nodeid = {item.nodeid: item for item in session.items}
    for rep in reports:
        for out in rep.outcomes:
            item = items_by_nodeid.get(out.nodeid)
            location = (
                item.location if item is not None else (out.nodeid, 0, out.nodeid)
            )
            keywords = dict.fromkeys(item.keywords, 1) if item is not None else {}
            outcome_literal: Literal["passed", "failed", "skipped"] = (
                "passed"
                if out.outcome == "passed"
                else ("skipped" if out.outcome == "skipped" else "failed")
            )
            tr = pytest.TestReport(
                nodeid=out.nodeid,
                location=location,
                keywords=keywords,
                outcome=outcome_literal,
                longrepr=out.longrepr
                or (out.stderr if outcome_literal == "failed" else None),
                when="call",
                duration=out.duration_seconds,
            )
            session.config.hook.pytest_runtest_logreport(report=tr)


def _resolve_session_params(
    session: pytest.Session,
) -> tuple[str, str | None, str, bool, bool, bool, str | None]:
    """Resolve cluster URL, authentication token, pool, tier, and container execution options.

    Args:
        session: Active pytest test session.

    Returns:
        Tuple of (server_url, api_token, pool, free_tier, allow_fallback, is_container, worker_image).

    Raises:
        None.

    Notes/Architectural Intent:
        Centralizes profile extraction from stash with fallback to command-line options
        while enforcing zero-cost free-tier defaults.
    """
    resolved = session.config.stash.get(_CONFIG_KEY, None)
    if resolved is not None:
        return (
            resolved.server_url,
            resolved.api_token,
            resolved.pool,
            resolved.free_tier,
            resolved.fallback,
            resolved.mode == "container",
            resolved.container.image,
        )
    server_url = (
        session.config.getoption(
            "hexaqueue_server_url", default="http://127.0.0.1:8000"
        )
        or "http://127.0.0.1:8000"
    )
    api_token = session.config.getoption("hexaqueue_api_token", default=None)
    pool = session.config.getoption("hexaqueue_pool", default="default") or "default"
    free_tier = not bool(session.config.getoption("hexaqueue_paid", default=False))
    opt_fallback = session.config.getoption("hexaqueue_fallback", default=True)
    allow_fallback = True if opt_fallback is None else bool(opt_fallback)
    is_container = bool(session.config.getoption("hexaqueue_container", default=False))
    worker_image = session.config.getoption("hexaqueue_worker_image", default=None)
    return (
        server_url,
        api_token,
        pool,
        free_tier,
        allow_fallback,
        is_container,
        worker_image,
    )


def _unpack_slice_coverage(reports: list["SliceOutcomeReport"]) -> None:
    """Materialize serialized SQLite coverage payloads from remote worker slices onto disk.

    Args:
        reports: List of slice execution outcome reports.

    Returns:
        None.

    Raises:
        None.

    Notes/Architectural Intent:
        Enables distributed coverage aggregation by writing worker coverage sqlite databases
        as `.coverage.hq.<slice_id>` so pytest-cov can combine them automatically.
    """
    for rep in reports:
        if rep.coverage_data and "sqlite_b64" in rep.coverage_data:
            cov_path = Path(f".coverage.hq.{rep.slice_id}")
            if not cov_path.exists():
                cov_bytes = base64.b64decode(rep.coverage_data["sqlite_b64"])
                cov_path.write_bytes(cov_bytes)


@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop(session: pytest.Session) -> bool | None:
    """Execute distributed test loop dispatching slices across cluster workers."""
    if not _is_hexaqueue_enabled(session.config):
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

    (
        server_url,
        api_token,
        pool,
        free_tier,
        allow_fallback,
        is_container,
        worker_image,
    ) = _resolve_session_params(session)

    client: HexaqueueTestDispatchPort = session.config.stash.get(
        _CLIENT_KEY,
        getattr(
            session.config,
            "_hexaqueue_client",
            HexaqueueTestDispatchClient(server_url=server_url, api_token=api_token),
        ),
    )

    cov_sources: list[str] = []
    opt_cov = getattr(session.config.option, "cov_source", None)
    if opt_cov:
        cov_sources = [str(s) for s in opt_cov]

    run_session = TestRunSession(
        session_id=str(uuid.uuid4()),
        total_items=len(session.items),
        total_slices=len(slices),
        slices=slices,
        server_url=server_url,
        pool=pool,
        free_tier=free_tier,
        container=is_container,
        container_image=worker_image,
        coverage_sources=cov_sources,
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
    if cov_sources:
        _unpack_slice_coverage(reports)

    _notify_session_reports(session, reports)
    return True


def pytest_terminal_summary(
    terminalreporter: Any,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    """Format and print distributed execution telemetry summary."""
    if not _is_hexaqueue_enabled(config):
        return

    from pytest_hexaqueue.domain.outcome import SliceOutcomeReport

    reports_val = config.stash.get(
        _REPORTS_KEY, getattr(config, "_hexaqueue_reports", None)
    )
    if not reports_val or not isinstance(reports_val, list):
        return
    reports: list[SliceOutcomeReport] = reports_val

    terminalreporter.section("Hexaqueue Distributed Execution Summary")
    resolved = config.stash.get(_CONFIG_KEY, None)
    free_tier = (
        resolved.free_tier
        if resolved
        else not bool(config.getoption("hexaqueue_paid", default=False))
    )
    is_container = (
        (resolved.mode == "container")
        if resolved
        else config.getoption("hexaqueue_container", default=False)
    )
    profile_name = config.getoption("hexaqueue_profile", default=None)
    profile_label = f" [Profile: {profile_name}]" if profile_name else ""
    container_label = " (Containerized)" if is_container else ""
    tier_label = " (Verified $0.00 Multi-CSP Free-Tier)" if free_tier else ""

    terminalreporter.write_line(
        f"Topology: {len(reports)} Remote Slices{profile_label}{container_label}{tier_label}"
    )
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
