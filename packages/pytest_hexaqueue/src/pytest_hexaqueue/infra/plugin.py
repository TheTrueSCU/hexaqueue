"""Pytest plugin hooks for Hexaqueue distributed test execution.

Notes/Architectural Intent:
    Intercepts pytest execution lifecycle (option registration, collection finish,
    test loop, and terminal reporting), slicing test suites and dispatching
    execution partitions across Hexaqueue cluster nodes or multi-CSP free-tier meshes.
"""

import asyncio
import base64
import contextlib
import os
import sqlite3
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

import pytest

from hexaqueue_core.domain.credentials import discover_and_merge_env

if TYPE_CHECKING:
    from pytest_hexaqueue.domain.outcome import SliceOutcomeReport
    from pytest_hexaqueue.domain.slice import TestRunSession, TestSliceSpec
    from pytest_hexaqueue.ports.client import HexaqueueTestDispatchPort

_SLICES_KEY: pytest.StashKey[list[Any]] = pytest.StashKey()
_REPORTS_KEY: pytest.StashKey[list[Any]] = pytest.StashKey()
_CLIENT_KEY: pytest.StashKey[Any] = pytest.StashKey()
_CONFIG_KEY: pytest.StashKey[Any] = pytest.StashKey()
_HYBRID_COUNTS_KEY: pytest.StashKey[tuple[int, int]] = pytest.StashKey()


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
    group.addoption(
        "--hq-local-slices",
        action="store",
        nargs="?",
        const="auto",
        default=None,
        dest="hexaqueue_local_slices",
        help="Number of slices to execute locally in parallel across workstation vCPUs, or 'auto' (0 to disable)",
    )
    group.addoption(
        "--hq-remote-slices",
        action="store",
        nargs="?",
        const="auto",
        default=None,
        dest="hexaqueue_remote_slices",
        help="Number of slices to dispatch remotely to Hexaqueue cluster controller, or 'auto' (0 to disable)",
    )
    group.addoption(
        "--hq-hybrid",
        action="store_true",
        default=None,
        dest="hexaqueue_hybrid",
        help="Enable hybrid local and remote test execution automatically partitioning slices",
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
    if config.getoption("hexaqueue_local_slices", default=None) is not None:
        cli_overrides["local_slices"] = config.getoption("hexaqueue_local_slices")
    if config.getoption("hexaqueue_remote_slices", default=None) is not None:
        cli_overrides["remote_slices"] = config.getoption("hexaqueue_remote_slices")

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

    for name in (
        "xdist",
        "dsession",
        "xdist.dsession",
        "xdist.plugin",
        "cacheprovider",
    ):
        plugin = config.pluginmanager.get_plugin(name)
        if plugin is not None:
            config.pluginmanager.unregister(plugin)

    config.stash[_CONFIG_KEY] = _resolve_plugin_config(config)


def _parse_slice_concurrency(val: Any) -> int | None:
    """Resolve slice concurrency width matching pytest-xdist and hexaqual semantics.

    Args:
        val: Concurrency specification ('auto', an integer, 0, or None).

    Returns:
        Effective concurrency integer (>= 0), or None if unassigned.

    Raises:
        None.

    Notes/Architectural Intent:
        Delegates 'auto' and positive integer resolution to hexaqual's canonical
        resolve_parallelism logic, reserving 2 CPU cores for OS/terminal responsiveness.
        Explicitly supports 0 to completely disable local execution (pure remote mode).
    """
    if val is None:
        return None
    if isinstance(val, bool):
        if val:
            val = "auto"
        else:
            return 0
    if isinstance(val, (int, float)):
        int_val = int(val)
        if int_val == 0:
            return 0
        try:
            from hexaqual.domain.governance import resolve_parallelism

            return resolve_parallelism(int_val)
        except (ImportError, ModuleNotFoundError, ValueError):
            total_cores = os.cpu_count() or 1
            return max(0, min(int_val, total_cores))

    cleaned = str(val).strip().casefold()
    if cleaned == "0":
        return 0

    try:
        from hexaqual.domain.governance import resolve_parallelism

        return resolve_parallelism(cleaned)
    except (ImportError, ModuleNotFoundError, ValueError):
        total_cores = os.cpu_count() or 1
        if cleaned in ("auto", ""):
            return max(1, total_cores - 2)
        try:
            return max(0, min(int(cleaned), total_cores))
        except (ValueError, TypeError):
            return max(1, total_cores - 2)


def _resolve_remote_slice_concurrency(val: Any, item_count: int = 0) -> int | None:
    """Resolve remote slice partition count matching distributed queue saturation semantics.

    Args:
        val: Concurrency specification ('auto', an integer, 0, or None).
        item_count: Total collected test items for dynamic workload scaling.

    Returns:
        Effective slice partition integer (>= 0), or None if unassigned.

    Raises:
        None.

    Notes/Architectural Intent:
        When 'auto' is specified, over-partitions test slices proportional to collected
        test items (targeting ~25-35 tests per slice, bounded between 4 and 32). This
        ensures the remote cluster controller's work-stealing queue remains continuously
        saturated, preventing worker vCPU cores from idling on slow-running test stragglers.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        val = "auto" if val else 0
    if isinstance(val, (int, float)):
        return max(0, int(val))

    cleaned = str(val).strip().casefold()
    if cleaned == "0":
        return 0
    if cleaned != "auto":
        try:
            return max(0, int(cleaned))
        except (ValueError, TypeError):
            return None

    if item_count <= 0:
        return 4
    if item_count < 4:
        return max(1, item_count)
    return max(4, min(32, item_count // 30))


def _get_slicer(strategy: str) -> Any:
    """Instantiate configured slicing adapter."""
    from pytest_hexaqueue.adapters.slicer import (
        FileContiguousTestSlicer,
        RoundRobinTestSlicer,
    )

    if strategy == "file":
        return FileContiguousTestSlicer()
    return RoundRobinTestSlicer()


def _resolve_slice_counts(
    config: pytest.Config, item_count: int = 0
) -> tuple[int, int, int]:
    """Calculate total, local, and remote slice allocations for hybrid or pure topologies.

    Args:
        config: Active pytest configuration.
        item_count: Total collected test items for dynamic remote saturation.

    Returns:
        Tuple of (total_slices, local_slices, remote_slices).

    Raises:
        None.

    Notes/Architectural Intent:
        Calculates slice partition sizes ensuring local workstation vCPUs and remote
        cloud workers can execute concurrently without resource under-utilization.
        Supports 'auto' via hexaqual.domain.governance.resolve_parallelism and 0 for
        pure remote dispatch.
    """
    resolved = config.stash.get(_CONFIG_KEY, None)
    profile_local = getattr(resolved, "local_slices", None) if resolved else None
    profile_remote = getattr(resolved, "remote_slices", None) if resolved else None

    local_opt = config.getoption("hexaqueue_local_slices", default=None)
    local_raw = local_opt if local_opt is not None else profile_local

    remote_opt = config.getoption("hexaqueue_remote_slices", default=None)
    remote_raw = remote_opt if remote_opt is not None else profile_remote

    hybrid_arg = config.getoption("hexaqueue_hybrid", default=None)
    slices_raw = config.getoption("hexaqueue_slices", default=None)

    local_arg = _parse_slice_concurrency(local_raw)
    remote_arg = _resolve_remote_slice_concurrency(remote_raw, item_count=item_count)
    try:
        slices_arg = int(slices_raw) if slices_raw is not None else None
    except (ValueError, TypeError):
        slices_arg = None

    default_total = resolved.slices if resolved and hasattr(resolved, "slices") else 4
    total_requested = slices_arg if slices_arg is not None else default_total

    if local_arg is not None and remote_arg is not None:
        local_cnt = max(0, local_arg)
        remote_cnt = max(0, remote_arg)
        total_cnt = max(1, local_cnt + remote_cnt)
        return total_cnt, local_cnt, remote_cnt

    if local_arg is not None:
        local_cnt = max(0, local_arg)
        total_cnt = max(local_cnt, total_requested)
        remote_cnt = total_cnt - local_cnt
        return total_cnt, local_cnt, remote_cnt

    if remote_arg is not None:
        remote_cnt = max(0, remote_arg)
        total_cnt = max(remote_cnt, total_requested)
        local_cnt = total_cnt - remote_cnt
        return total_cnt, local_cnt, remote_cnt

    if hybrid_arg:
        local_cnt = _parse_slice_concurrency("auto") or 2
        remote_cnt = (
            _resolve_remote_slice_concurrency("auto", item_count=item_count) or 4
        )
        total_cnt = max(total_requested, local_cnt + remote_cnt)
        return total_cnt, local_cnt, total_cnt - local_cnt

    # Standard remote-only execution
    total_cnt = max(1, total_requested)
    return total_cnt, 0, total_cnt


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
    slicer_name = (
        resolved.slicer
        if resolved and hasattr(resolved, "slicer")
        else (
            session.config.getoption("hexaqueue_slicer", default="round-robin")
            or "round-robin"
        )
    )
    slicer = _get_slicer(slicer_name)

    total_slices, local_slices, remote_slices = _resolve_slice_counts(
        session.config, item_count=len(session.items)
    )
    session.config.stash[_HYBRID_COUNTS_KEY] = (local_slices, remote_slices)

    slices = slicer.slice_items(items, total_slices)
    session.config.stash[_SLICES_KEY] = slices


def _build_test_report_item(
    out: Any,
    item: pytest.Item | None,
) -> pytest.TestReport:
    """Construct a pytest TestReport from a slice outcome item and session item.

    Args:
        out: TestOutcomeItem reporting execution outcome and captured streams.
        item: Optional matched pytest Item from collection.

    Returns:
        Configured pytest.TestReport instance.

    Raises:
        None.

    Notes/Architectural Intent:
        Preserves test location and keyword tags while materializing captured
        subprocess stdout and stderr onto longrepr on test failure.
    """
    location = item.location if item is not None else (out.nodeid, 0, out.nodeid)
    keywords = dict.fromkeys(item.keywords, 1) if item is not None else {}
    outcome_literal: Literal["passed", "failed", "skipped"] = (
        "passed"
        if out.outcome == "passed"
        else ("skipped" if out.outcome == "skipped" else "failed")
    )
    error_msg: str | None = None
    if outcome_literal == "failed":
        parts = [p for p in (out.stderr, out.stdout) if p]
        error_msg = "\n".join(parts) if parts else None

    return pytest.TestReport(
        nodeid=out.nodeid,
        location=location,
        keywords=keywords,
        outcome=outcome_literal,
        longrepr=out.longrepr or error_msg,
        when="call",
        duration=out.duration_seconds,
    )


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
            tr = _build_test_report_item(out, items_by_nodeid.get(out.nodeid))
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


def _extract_marker_relative_path(norm_raw: str) -> str | None:
    """Extract relative workspace path from standard Hexaqueue remote or container directories."""
    runs_marker = "/tmp/hexaqueue/runs/"
    runs_idx = norm_raw.find(runs_marker)
    if runs_idx != -1:
        after = norm_raw[runs_idx + len(runs_marker) :]
        slash_idx = after.find("/")
        if slash_idx != -1 and after[slash_idx + 1 :]:
            return after[slash_idx + 1 :]

    ws_marker = "/workspace/"
    ws_idx = norm_raw.find(ws_marker)
    if ws_idx != -1 and norm_raw[ws_idx + len(ws_marker) :]:
        return norm_raw[ws_idx + len(ws_marker) :]

    return None


def _remap_coverage_path(
    raw_path: str,
    local_root: Path,
    remote_root: str | None = None,
) -> str:
    """Remap a remote worker file path from a coverage database to the local workspace root."""
    norm_local = str(local_root).replace("\\", "/").rstrip("/")
    norm_raw = raw_path.replace("\\", "/")
    if norm_raw == norm_local or norm_raw.startswith(norm_local + "/"):
        return raw_path

    if remote_root:
        norm_remote = remote_root.replace("\\", "/").rstrip("/")
        if norm_remote and norm_raw.startswith(norm_remote + "/"):
            return str(local_root / norm_raw[len(norm_remote) + 1 :])

    marker_rel = _extract_marker_relative_path(norm_raw)
    if marker_rel:
        return str(local_root / marker_rel)

    parts = [p for p in norm_raw.split("/") if p]
    for i in range(1, len(parts)):
        candidate = local_root.joinpath(*parts[i:])
        if candidate.exists():
            return str(candidate)

    return raw_path


def _merge_duplicate_coverage_file_id(
    con: sqlite3.Connection, source_id: int, target_id: int
) -> None:
    """Merge coverage arcs and line bits when two file rows map to the same local path."""
    with contextlib.suppress(sqlite3.Error):
        con.execute(
            "INSERT OR IGNORE INTO arc (file_id, context_id, fromno, tono) "
            "SELECT ?, context_id, fromno, tono FROM arc WHERE file_id = ?",
            (target_id, source_id),
        )
        con.execute("DELETE FROM arc WHERE file_id = ?", (source_id,))
    with contextlib.suppress(sqlite3.Error):
        con.execute(
            "INSERT OR IGNORE INTO line_bits (file_id, context_id, numbits) "
            "SELECT ?, context_id, numbits FROM line_bits WHERE file_id = ?",
            (target_id, source_id),
        )
        con.execute("DELETE FROM line_bits WHERE file_id = ?", (source_id,))
    with contextlib.suppress(sqlite3.Error):
        con.execute("DELETE FROM tracer WHERE file_id = ?", (source_id,))
    con.execute("DELETE FROM file WHERE id = ?", (source_id,))


def _normalize_coverage_sqlite_paths(
    cov_path: Path,
    remote_root: str | None = None,
    local_root: Path | None = None,
) -> None:
    """Rewrite remote worker file paths in a coverage SQLite database to match the local workspace."""
    if not cov_path.is_file():
        return
    effective_local = (local_root or Path.cwd()).resolve()
    try:
        with contextlib.closing(sqlite3.connect(str(cov_path))) as con:
            rows = list(con.execute("SELECT id, path FROM file"))
            if not rows:
                return
            existing_paths: dict[str, int] = {str(p): int(fid) for fid, p in rows}
            mutated = False
            for fid_raw, path_raw in rows:
                fid = int(fid_raw)
                orig_path = str(path_raw)
                new_path = _remap_coverage_path(orig_path, effective_local, remote_root)
                if new_path == orig_path:
                    continue
                mutated = True
                existing_paths.pop(orig_path, None)
                target_id = existing_paths.get(new_path)
                if target_id is not None and target_id != fid:
                    _merge_duplicate_coverage_file_id(con, fid, target_id)
                else:
                    con.execute(
                        "UPDATE file SET path = ? WHERE id = ?", (new_path, fid)
                    )
                    existing_paths[new_path] = fid
            if mutated:
                con.commit()
    except Exception:
        return


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
        as `.coverage.hq.<slice_id>` and normalizing remote workspace file paths so
        pytest-cov can combine them seamlessly with local slice measurements.
    """
    for rep in reports:
        if rep.coverage_data and "sqlite_b64" in rep.coverage_data:
            cov_path = Path(f".coverage.hq.{rep.slice_id}")
            if rep.provider != "LOCAL" or not cov_path.exists():
                cov_bytes = base64.b64decode(rep.coverage_data["sqlite_b64"])
                cov_path.write_bytes(cov_bytes)
            _normalize_coverage_sqlite_paths(
                cov_path,
                remote_root=rep.coverage_data.get("workspace_root"),
            )


def _resolve_git_context() -> tuple[str | None, str | None]:
    """Resolve current Git commit hash and active ref or branch.

    Returns:
        Tuple of (git_commit_sha, git_ref).
    """
    git_commit = os.environ.get("GITHUB_SHA")
    git_ref = os.environ.get("GITHUB_REF")
    if not git_commit:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                git_commit = proc.stdout.strip()
        except Exception:
            pass
    if not git_ref:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                git_ref = proc.stdout.strip()
        except Exception:
            pass
    return git_commit, git_ref


async def _stage_workspace_collateral(
    client: "HexaqueueTestDispatchPort",
) -> str | None:
    """Stage local workspace files into cluster CAS collateral for remote workers."""
    try:
        from pytest_hexaqueue.adapters.archiver import create_workspace_archiver

        archiver = create_workspace_archiver(Path.cwd())
        archive_bytes, sha256 = archiver.archive_workspace(Path.cwd())
        return await client.upload_collateral_bundle(archive_bytes, sha256)
    except Exception:
        return None


def _normalize_cov_sources(
    raw_sources: list[str],
    root: Path | None = None,
) -> list[str]:
    """Convert workspace-internal absolute coverage paths to relative paths."""
    resolved_root = (root or Path.cwd()).resolve()
    normalized: list[str] = []
    for src in raw_sources:
        p = Path(src)
        if p.is_absolute():
            resolved_p = p.resolve()
            if resolved_p.is_relative_to(resolved_root):
                rel = resolved_p.relative_to(resolved_root)
                normalized.append("." if str(rel) == "." else str(rel))
                continue
        normalized.append(src)
    return normalized


def _build_tunnel_command(resolved: Any) -> list[str] | None:
    """Build foreground SSH port-forwarding command if a remote host is configured."""
    env = discover_and_merge_env()
    host = getattr(resolved, "host", None) or env.get("HEXAQUEUE_CLUSTER_HOST")
    if not host:
        return None
    user = (
        getattr(resolved, "ssh_user", None)
        or env.get("HEXAQUEUE_SSH_USER")
        or "hexaqueue-ci"
    )
    key = getattr(resolved, "ssh_key", None) or env.get("HEXAQUEUE_SSH_KEY")
    ssh_port = getattr(resolved, "ssh_port", None) or 22
    remote_port = getattr(resolved, "remote_port", None) or 8000
    server_url = getattr(resolved, "server_url", "http://127.0.0.1:8000")
    local_port = urlparse(server_url).port or 8000

    cmd = [
        "ssh",
        "-N",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=15",
        "-p",
        str(ssh_port),
        "-L",
        f"{local_port}:localhost:{remote_port}",
    ]
    if key:
        expanded = Path(key).expanduser()
        if expanded.is_file():
            cmd.extend(["-i", str(expanded)])
    cmd.append(f"{user}@{host}")
    return cmd


@contextlib.asynccontextmanager
async def _managed_ssh_tunnel(
    resolved: Any,
    client: "HexaqueueTestDispatchPort",
) -> Any:
    """Ensure cluster reachability, opening an ephemeral SSH tunnel when host is configured."""
    if await client.health_check():
        yield True
        return

    from pytest_hexaqueue.adapters.client import HexaqueueTestDispatchClient

    cmd = (
        _build_tunnel_command(resolved)
        if resolved is not None and isinstance(client, HexaqueueTestDispatchClient)
        else None
    )
    if not cmd:
        yield False
        return

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        healthy = False
        for _ in range(24):
            if proc.returncode is not None:
                break
            if await client.health_check():
                healthy = True
                break
            await asyncio.sleep(0.25)
        yield healthy
    except Exception:
        yield False
    finally:
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=2.0)


async def _dispatch_slices_loop(
    slices: list["TestSliceSpec"],
    local_count: int,
    remote_count: int,
    local_runner: Any,
    client: "HexaqueueTestDispatchPort",
    run_session: "TestRunSession",
    cov_sources: list[str],
    server_url: str,
    allow_fallback: bool,
    resolved_config: Any = None,
) -> list["SliceOutcomeReport"] | None:
    """Execute local, remote, or hybrid slices and aggregate outcomes."""
    from pytest_hexaqueue.domain.slice import TestRunSession

    local_slices = slices[:local_count]
    remote_slices = slices[local_count:]

    # Case 1: Pure local execution
    if remote_count == 0:
        local_reports = await asyncio.gather(
            *[local_runner.execute_slice(s, cov_sources) for s in local_slices]
        )
        return list(local_reports)

    async with _managed_ssh_tunnel(resolved_config, client) as is_healthy:
        if not is_healthy:
            if allow_fallback:
                if local_count > 0:
                    fallback_reports = await asyncio.gather(
                        *[local_runner.execute_slice(s, cov_sources) for s in slices]
                    )
                    return list(fallback_reports)
                return None
            msg = f"Hexaqueue cluster at '{server_url}' is offline and fallback is disabled"
            raise ConnectionError(msg)

        # Stage workspace under test as CAS collateral for remote workers
        collateral_id = await _stage_workspace_collateral(client)

        effective_run_session = (
            run_session.model_copy(update={"collateral_id": collateral_id})
            if collateral_id is not None
            else run_session
        )

        # Case 2: Pure remote execution
        if local_count == 0:
            return await client.dispatch_run(effective_run_session)

        # Case 3: Hybrid execution (concurrent local + remote)
        remote_run_session = TestRunSession(
            session_id=str(uuid.uuid4()),
            collateral_id=collateral_id,
            total_items=sum(len(s.test_nodeids) for s in remote_slices),
            total_slices=len(remote_slices),
            slices=remote_slices,
            server_url=server_url,
            pool=run_session.pool,
            free_tier=run_session.free_tier,
            container=run_session.container,
            container_image=run_session.container_image,
            coverage_sources=cov_sources,
            git_commit=run_session.git_commit,
            git_ref=run_session.git_ref,
        )
        local_task = asyncio.gather(
            *[local_runner.execute_slice(s, cov_sources) for s in local_slices]
        )
        remote_task = client.dispatch_run(remote_run_session)

        local_results, remote_results = await asyncio.gather(local_task, remote_task)
        combined = list(local_results) + list(remote_results)
        combined.sort(key=lambda r: r.slice_index)
        return combined


@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop(session: pytest.Session) -> bool | None:
    """Execute distributed test loop dispatching slices across cluster workers."""
    if not _is_hexaqueue_enabled(session.config):
        return None
    if getattr(session.config.option, "collectonly", False) is True:
        return True

    from pytest_hexaqueue.adapters.client import HexaqueueTestDispatchClient
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

    local_count, remote_count = session.config.stash.get(
        _HYBRID_COUNTS_KEY, (0, len(slices))
    )
    from pytest_hexaqueue.adapters.local_runner import LocalSliceRunner

    local_runner = LocalSliceRunner(concurrency=max(1, local_count))

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
        cov_sources = _normalize_cov_sources([str(s) for s in opt_cov])

    active_commit, active_ref = _resolve_git_context()

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
        git_commit=active_commit,
        git_ref=active_ref,
    )

    resolved_cfg = session.config.stash.get(_CONFIG_KEY, None)
    try:
        reports = asyncio.run(
            _dispatch_slices_loop(
                slices=slices,
                local_count=local_count,
                remote_count=remote_count,
                local_runner=local_runner,
                client=client,
                run_session=run_session,
                cov_sources=cov_sources,
                server_url=server_url,
                allow_fallback=allow_fallback,
                resolved_config=resolved_cfg,
            )
        )
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

    local_count = sum(1 for r in reports if r.provider == "LOCAL")
    remote_count = len(reports) - local_count
    if local_count > 0 and remote_count > 0:
        topology_label = (
            f"Topology: {len(reports)} Hybrid Slices ({local_count} Local Workstation + "
            f"{remote_count} Remote Cluster){profile_label}{container_label}{tier_label}"
        )
    elif local_count > 0 and remote_count == 0:
        topology_label = f"Topology: {len(reports)} Local Slices{profile_label}{container_label}{tier_label}"
    else:
        topology_label = f"Topology: {len(reports)} Remote Slices{profile_label}{container_label}{tier_label}"

    terminalreporter.write_line(topology_label)
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
