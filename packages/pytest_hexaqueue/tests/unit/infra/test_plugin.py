"""Unit tests for pytest-hexaqueue plugin hooks and execution loop."""

import asyncio
import importlib
import sqlite3
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_hexaqueue.adapters.client import InMemoryTestDispatchClient
from pytest_hexaqueue.adapters.slicer import FileContiguousTestSlicer
from pytest_hexaqueue.domain.outcome import (
    SliceOutcomeReport,
    TestOutcomeItem,
)
from pytest_hexaqueue.domain.slice import TestSliceSpec
from pytest_hexaqueue.infra.plugin import (
    _CLIENT_KEY,
    _CONFIG_KEY,
    _HYBRID_COUNTS_KEY,
    _REPORTS_KEY,
    _SLICES_KEY,
    _get_slicer,
    _notify_session_reports,
    _resolve_plugin_config,
    _resolve_remote_slice_concurrency,
    _resolve_slice_counts,
    pytest_addoption,
    pytest_collection_finish,
    pytest_configure,
    pytest_runtestloop,
    pytest_terminal_summary,
)

from hexaqueue_core.domain.runner_config import (
    HexaqueueContainerConfig,
    HexaqueueProfileConfig,
)


def test_pytest_addoption() -> None:
    """Test registering CLI flags with pytest parser."""
    parser = MagicMock()
    group = MagicMock()
    parser.getgroup.return_value = group

    pytest_addoption(parser)

    parser.getgroup.assert_called_with(
        "hexaqueue", "Hexaqueue Distributed Test Execution"
    )
    # Check that key flags were registered
    dest_names = [call.kwargs.get("dest") for call in group.addoption.call_args_list]
    assert "hexaqueue_enabled" in dest_names
    assert "hexaqueue_slices" in dest_names
    assert "hexaqueue_server_url" in dest_names
    assert "hexaqueue_fallback" in dest_names
    assert "hexaqueue_api_token" in dest_names
    assert "hexaqueue_free_tier" in dest_names
    assert "hexaqueue_paid" in dest_names
    assert "hexaqueue_fallback" in dest_names
    assert "hexaqueue_container" in dest_names
    assert "hexaqueue_worker_image" in dest_names
    assert "hexaqueue_config_file" in dest_names
    assert "hexaqueue_profile" in dest_names

    # Check option strings for profile
    profile_calls = [
        call
        for call in group.addoption.call_args_list
        if call.kwargs.get("dest") == "hexaqueue_profile"
    ]
    assert len(profile_calls) == 1
    assert "--profile" in profile_calls[0].args
    assert "--hq-profile" in profile_calls[0].args


def test_pytest_configure() -> None:
    """Test marker configuration and profile resolution."""
    config = MagicMock()
    config.getoption.side_effect = lambda name, default=None: (
        False if name == "hexaqueue_enabled" else default
    )
    pytest_configure(config)
    config.addinivalue_line.assert_called_with(
        "markers",
        "hexaqueue: mark test for execution on Hexaqueue distributed cluster",
    )


def test_pytest_configure_when_enabled() -> None:
    """Test configuration loading when plugin is enabled."""
    config = MagicMock()
    config.stash = {}
    config.option = MagicMock(numprocesses=2, dist="load")

    def getoption(name: str, default: Any = None) -> Any:
        if name == "hexaqueue_enabled":
            return True
        if name == "hexaqueue_slices":
            return 8
        if name == "hexaqueue_profile":
            return "ci"
        return default

    config.getoption.side_effect = getoption
    pytest_configure(config)

    assert config.option.numprocesses == 0
    assert config.option.dist == "no"


def test_pytest_collection_finish_when_disabled() -> None:
    """Test collection finish hook when hexaqueue is not enabled does nothing."""
    session = MagicMock()
    session.config.getoption.return_value = False

    pytest_collection_finish(session)
    assert _SLICES_KEY not in session.config.stash


def test_pytest_collection_finish_when_enabled() -> None:
    """Test collection finish partitions collected items."""
    session = MagicMock()
    stash_dict: dict[Any, Any] = {}
    session.config.stash = stash_dict

    def getoption(name: str, default: bool | int | str = False) -> bool | int | str:
        if name == "hexaqueue_enabled":
            return True
        if name == "hexaqueue_slices":
            return 2
        if name == "hexaqueue_slicer":
            return "round-robin"
        return default

    session.config.getoption.side_effect = getoption

    item1 = MagicMock(nodeid="t1", path="test_1.py")
    item1.iter_markers.return_value = []
    item2 = MagicMock(nodeid="t2", path="test_2.py")
    item2.iter_markers.return_value = []
    session.items = [item1, item2]

    pytest_collection_finish(session)
    assert _SLICES_KEY in session.config.stash
    slices = session.config.stash[_SLICES_KEY]
    assert len(slices) == 2


def test_pytest_runtestloop_when_disabled() -> None:
    """Test runtestloop returns None when plugin is disabled."""
    session = MagicMock()
    session.config.getoption.return_value = False

    res = pytest_runtestloop(session)
    assert res is None


def test_pytest_runtestloop_execution_success() -> None:
    """Test runtestloop dispatches to in-memory client and returns True."""
    session = MagicMock()
    stash_dict: dict[Any, Any] = {}
    session.config.stash = stash_dict

    def getoption(name: str, default: bool | int | str = False) -> bool | int | str:
        if name == "hexaqueue_enabled":
            return True
        if name == "hexaqueue_server_url":
            return "http://localhost:8000"
        if name == "hexaqueue_pool":
            return "default"
        if name == "hexaqueue_free_tier":
            return True
        if name == "hexaqueue_fallback":
            return True
        return default

    session.config.getoption.side_effect = getoption
    stash_dict[_SLICES_KEY] = [
        TestSliceSpec(slice_id="s0", slice_index=0, total_slices=1, test_nodeids=["t1"])
    ]
    session.items = [MagicMock(nodeid="t1")]

    # Inject mock in-memory client into stash
    mock_client = InMemoryTestDispatchClient(is_free_tier=True)
    stash_dict[_CLIENT_KEY] = mock_client

    res = pytest_runtestloop(session)
    assert res is True
    assert _REPORTS_KEY in stash_dict
    reports = stash_dict[_REPORTS_KEY]
    assert len(reports) == 1
    assert reports[0].is_free_tier is True


def test_pytest_runtestloop_fallback_on_unhealthy() -> None:
    """Test runtestloop falls back to local execution (returns None) when cluster is offline."""
    session = MagicMock()
    stash_dict: dict[Any, Any] = {}
    session.config.stash = stash_dict

    def getoption(name: str, default: bool | int | str = False) -> bool | int | str:
        if name == "hexaqueue_enabled":
            return True
        if name == "hexaqueue_server_url":
            return "http://localhost:8000"
        if name == "hexaqueue_pool":
            return "default"
        if name == "hexaqueue_free_tier":
            return False
        if name == "hexaqueue_fallback":
            return True  # Fallback allowed
        return default

    session.config.getoption.side_effect = getoption
    stash_dict[_SLICES_KEY] = [
        TestSliceSpec(slice_id="s0", slice_index=0, total_slices=1, test_nodeids=["t1"])
    ]
    session.items = [MagicMock(nodeid="t1")]

    # Unhealthy client triggers fallback
    mock_client = InMemoryTestDispatchClient(is_healthy=False)
    stash_dict[_CLIENT_KEY] = mock_client

    res = pytest_runtestloop(session)
    assert res is None  # Yields control back to local pytest execution


def test_pytest_terminal_summary() -> None:
    """Test terminal summary reporter output."""
    reporter = MagicMock()
    config = MagicMock()
    stash_dict: dict[Any, Any] = {}
    config.stash = stash_dict
    config.getoption.side_effect = lambda opt, default=False: (
        True if opt in ("hexaqueue_enabled", "hexaqueue_free_tier") else default
    )

    stash_dict[_REPORTS_KEY] = [
        SliceOutcomeReport(
            slice_id="slice-0",
            slice_index=0,
            worker_id="worker-oci-0",
            provider="OCI",
            is_free_tier=True,
            outcomes=[TestOutcomeItem(nodeid="t1", outcome="passed")],
            duration_seconds=0.45,
        )
    ]

    pytest_terminal_summary(reporter, exitstatus=0, config=config)
    reporter.section.assert_called_with("Hexaqueue Distributed Execution Summary")
    # Verify written lines
    written_lines = [call[0][0] for call in reporter.write_line.call_args_list]
    assert any("Verified $0.00 Multi-CSP Free-Tier" in line for line in written_lines)
    assert any(
        "slice-0 [OCI] -> Worker 'worker-oci-0'" in line for line in written_lines
    )


def test_plugin_slicer_file() -> None:
    """Test slicer selection for file strategy."""
    file_slicer = _get_slicer("file")
    assert isinstance(file_slicer, FileContiguousTestSlicer)


def test_pytest_runtestloop_empty_slices() -> None:
    """Test runtestloop returns None when slices list is empty."""
    session = MagicMock()
    session.config.getoption.return_value = True
    session.config.stash = {_SLICES_KEY: []}

    res = pytest_runtestloop(session)
    assert res is None


def test_pytest_runtestloop_fallback_disabled_raises() -> None:
    """Test runtestloop raises ConnectionError when fallback is disabled and server is offline."""
    session = MagicMock()

    def getoption(name: str, default: bool | int | str = False) -> bool | int | str:
        if name == "hexaqueue_enabled":
            return True
        if name == "hexaqueue_server_url":
            return "http://localhost:8000"
        if name == "hexaqueue_pool":
            return "default"
        if name == "hexaqueue_free_tier":
            return False
        if name == "hexaqueue_fallback":
            return False  # Disallow fallback!
        return default

    session.config.getoption.side_effect = getoption
    mock_client = InMemoryTestDispatchClient(is_healthy=False)
    session.config.stash = {
        _SLICES_KEY: [
            TestSliceSpec(
                slice_id="s0", slice_index=0, total_slices=1, test_nodeids=["t1"]
            )
        ],
        _CLIENT_KEY: mock_client,
    }
    session.items = [MagicMock(nodeid="t1")]

    with pytest.raises(ConnectionError, match="offline and fallback is disabled"):
        pytest_runtestloop(session)


def test_pytest_terminal_summary_disabled_or_empty() -> None:
    """Test terminal summary does nothing when disabled or empty."""
    reporter = MagicMock()
    config = MagicMock()
    config.getoption.return_value = False
    config.stash = {}
    config._hexaqueue_reports = []

    pytest_terminal_summary(reporter, exitstatus=0, config=config)
    reporter.section.assert_not_called()

    # Enabled but no reports
    config.getoption.return_value = True
    reporter.reset_mock()
    pytest_terminal_summary(reporter, exitstatus=0, config=config)
    reporter.section.assert_not_called()


def test_pytest_terminal_summary_containerized() -> None:
    """Test terminal summary includes containerized topology label."""
    reporter = MagicMock()
    config = MagicMock()

    def getoption(name: str, default: bool | int | str = False) -> bool | int | str:
        if name == "hexaqueue_enabled":
            return True
        if name == "hexaqueue_container":
            return True
        if name == "hexaqueue_free_tier":
            return False
        return default

    config.getoption.side_effect = getoption
    report = SliceOutcomeReport(
        slice_id="slice-0",
        slice_index=0,
        worker_id="worker-container-0",
        provider="CONTAINER",
        is_free_tier=False,
        outcomes=[TestOutcomeItem(nodeid="t1", outcome="passed")],
        duration_seconds=1.23,
    )
    config.stash = {_REPORTS_KEY: [report]}

    pytest_terminal_summary(reporter, exitstatus=0, config=config)
    reporter.section.assert_called_with("Hexaqueue Distributed Execution Summary")
    # Verify that Containerized label was rendered
    written_lines = [call[0][0] for call in reporter.write_line.call_args_list]
    has_cont = any("Containerized" in line for line in written_lines)
    assert has_cont is True


def test_resolve_plugin_config_all_options() -> None:
    """Test _resolve_plugin_config when all CLI flags are explicitly provided."""
    config = MagicMock()
    options: dict[str, Any] = {
        "hexaqueue_config_file": None,
        "hexaqueue_server_url": "https://custom.server",
        "hexaqueue_api_token": "secret-token",
        "hexaqueue_slices": 6,
        "hexaqueue_pool": "special-pool",
        "hexaqueue_container": True,
        "hexaqueue_worker_image": "custom:v1",
        "hexaqueue_free_tier": True,
        "hexaqueue_fallback": False,
        "hexaqueue_slicer": "file",
        "hexaqueue_profile": "ci",
    }
    config.getoption.side_effect = lambda name, default=None: options.get(name, default)
    res = _resolve_plugin_config(config)
    assert res.server_url == "https://custom.server"
    assert res.api_token == "secret-token"
    assert res.slices == 6
    assert res.pool == "special-pool"
    assert res.mode == "container"
    assert res.container.image == "custom:v1"
    assert res.free_tier is True
    assert res.fallback is False
    assert res.slicer == "file"


def test_pytest_collection_finish_with_resolved_config() -> None:
    """Test collection finish uses resolved configuration from stash."""
    session = MagicMock()
    stash_dict: dict[Any, Any] = {
        _CONFIG_KEY: HexaqueueProfileConfig(slices=3, slicer="file")
    }
    session.config.stash = stash_dict
    session.config.getoption.side_effect = lambda name, default=None: (
        True if name == "hexaqueue_enabled" else default
    )
    item1 = MagicMock(nodeid="t1", path="test_1.py")
    item1.iter_markers.return_value = []
    item2 = MagicMock(nodeid="t2", path="test_2.py")
    item2.iter_markers.return_value = []
    session.items = [item1, item2]

    pytest_collection_finish(session)
    assert _SLICES_KEY in session.config.stash
    slices = session.config.stash[_SLICES_KEY]
    assert len(slices) == 3


def test_pytest_runtestloop_with_resolved_config() -> None:
    """Test runtestloop uses resolved config from stash."""
    client = InMemoryTestDispatchClient()
    prof = HexaqueueProfileConfig(
        server_url="http://test-server:9000",
        api_token="test-token",
        slices=2,
        pool="ci-pool",
        mode="container",
        container=HexaqueueContainerConfig(image="worker:test"),
        free_tier=True,
        fallback=False,
    )
    session = MagicMock()
    session.config.getoption.side_effect = lambda name, default=None: (
        True if name == "hexaqueue_enabled" else default
    )
    session.config.stash = {
        _CLIENT_KEY: client,
        _CONFIG_KEY: prof,
        _SLICES_KEY: [
            TestSliceSpec(
                slice_id="s1", slice_index=0, total_slices=1, test_nodeids=["t1"]
            ),
        ],
    }
    session.items = [MagicMock(nodeid="t1")]

    result = pytest_runtestloop(session)
    assert result is True


def test_pytest_runtestloop_with_exception_and_fallback() -> None:
    """Test runtestloop catches exception and falls back to local execution when fallback is enabled."""
    client = AsyncMock()
    client.health_check.return_value = True
    client.dispatch_run.side_effect = RuntimeError("Dispatch exploded")

    session = MagicMock()
    session.config.getoption.side_effect = lambda name, default=None: (
        True if name == "hexaqueue_enabled" else default
    )
    prof = HexaqueueProfileConfig(fallback=True)
    session.config.stash = {
        _CLIENT_KEY: client,
        _CONFIG_KEY: prof,
        _SLICES_KEY: [
            TestSliceSpec(
                slice_id="s1", slice_index=0, total_slices=1, test_nodeids=["t1"]
            ),
        ],
    }
    session.items = [MagicMock(nodeid="t1")]

    res = pytest_runtestloop(session)
    assert res is None


def test_pytest_runtestloop_with_exception_and_no_fallback() -> None:
    """Test runtestloop re-raises exception when fallback is disabled."""
    client = AsyncMock()
    client.health_check.return_value = True
    client.dispatch_run.side_effect = RuntimeError("Dispatch exploded")

    session = MagicMock()
    session.config.getoption.side_effect = lambda name, default=None: (
        True if name == "hexaqueue_enabled" else default
    )
    prof = HexaqueueProfileConfig(fallback=False)
    session.config.stash = {
        _CLIENT_KEY: client,
        _CONFIG_KEY: prof,
        _SLICES_KEY: [
            TestSliceSpec(
                slice_id="s1", slice_index=0, total_slices=1, test_nodeids=["t1"]
            ),
        ],
    }
    session.items = [MagicMock(nodeid="t1")]

    with pytest.raises(RuntimeError, match="Dispatch exploded"):
        pytest_runtestloop(session)


def test_notify_session_reports_with_failures() -> None:
    """Test _notify_session_reports sets exitstatus to TESTS_FAILED when failures are present."""
    session = MagicMock()
    session.testsfailed = 0
    session.items = []
    rep = SliceOutcomeReport(
        slice_id="s1",
        slice_index=0,
        worker_id="w1",
        provider="LOCAL",
        is_free_tier=False,
        outcomes=[
            TestOutcomeItem(nodeid="t1", outcome="failed", longrepr="AssertionError"),
        ],
        duration_seconds=0.5,
    )
    _notify_session_reports(session, [rep])
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert session.testsfailed == 1


def test_resolve_plugin_config_paid_overrides_free_tier() -> None:
    """Verify --hq-paid overrides default free-tier setting to False."""
    config = MagicMock()
    options: dict[str, Any] = {
        "hexaqueue_config_file": None,
        "hexaqueue_paid": True,
        "hexaqueue_free_tier": None,
    }
    config.getoption.side_effect = lambda name, default=None: options.get(name, default)
    res = _resolve_plugin_config(config)
    assert res.free_tier is False


def test_resolve_plugin_config_paid_and_free_conflict_defaults_to_free() -> None:
    """Verify conflict between --hq-paid and --hq-free-tier warns and defaults to free tier."""
    config = MagicMock()
    options: dict[str, Any] = {
        "hexaqueue_config_file": None,
        "hexaqueue_paid": True,
        "hexaqueue_free_tier": True,
    }
    config.getoption.side_effect = lambda name, default=None: options.get(name, default)
    with pytest.warns(UserWarning, match="both paid and free tier requested"):
        res = _resolve_plugin_config(config)
        assert res.free_tier is True


def test_resolve_slice_counts_combinations() -> None:
    """Verify _resolve_slice_counts for various combinations of flags."""
    config = MagicMock()
    config.stash.get.return_value = None

    # Both local and remote specified
    opts: dict[str, Any] = {
        "hexaqueue_local_slices": 2,
        "hexaqueue_remote_slices": 4,
        "hexaqueue_hybrid": None,
        "hexaqueue_slices": None,
    }
    config.getoption.side_effect = lambda name, default=None: opts.get(name, default)
    tot, loc, rem = _resolve_slice_counts(config)
    assert tot == 6
    assert loc == 2
    assert rem == 4

    # Local only specified
    opts = {
        "hexaqueue_local_slices": 2,
        "hexaqueue_remote_slices": None,
        "hexaqueue_hybrid": None,
        "hexaqueue_slices": 4,
    }
    tot, loc, rem = _resolve_slice_counts(config)
    assert tot == 4
    assert loc == 2
    assert rem == 2

    # Remote only specified
    opts = {
        "hexaqueue_local_slices": None,
        "hexaqueue_remote_slices": 4,
        "hexaqueue_hybrid": None,
        "hexaqueue_slices": 10,
    }
    tot, loc, rem = _resolve_slice_counts(config)
    assert tot == 10
    assert loc == 6
    assert rem == 4

    # Hybrid flag
    opts = {
        "hexaqueue_local_slices": None,
        "hexaqueue_remote_slices": None,
        "hexaqueue_hybrid": True,
        "hexaqueue_slices": None,
    }
    tot, loc, rem = _resolve_slice_counts(config)
    assert loc > 0
    assert rem == 4
    assert tot == loc + rem

    # Default
    opts = {
        "hexaqueue_local_slices": None,
        "hexaqueue_remote_slices": None,
        "hexaqueue_hybrid": False,
        "hexaqueue_slices": 6,
    }
    tot, loc, rem = _resolve_slice_counts(config)
    assert tot == 6
    assert loc == 0
    assert rem == 6

    # 'auto' local slices
    opts = {
        "hexaqueue_local_slices": "auto",
        "hexaqueue_remote_slices": 4,
        "hexaqueue_hybrid": None,
        "hexaqueue_slices": None,
    }
    tot, loc, rem = _resolve_slice_counts(config)
    assert loc > 0
    assert rem == 4
    assert tot == loc + rem

    # 0 local slices (pure remote)
    opts = {
        "hexaqueue_local_slices": 0,
        "hexaqueue_remote_slices": 6,
        "hexaqueue_hybrid": None,
        "hexaqueue_slices": None,
    }
    tot, loc, rem = _resolve_slice_counts(config)
    assert tot == 6
    assert loc == 0
    assert rem == 6

    # 'auto' remote slices with item_count
    opts = {
        "hexaqueue_local_slices": 0,
        "hexaqueue_remote_slices": "auto",
        "hexaqueue_hybrid": None,
        "hexaqueue_slices": None,
    }
    tot, loc, rem = _resolve_slice_counts(config, item_count=600)
    assert loc == 0
    assert rem == 20
    assert tot == 20


def test_resolve_slice_counts_from_profile() -> None:
    """Verify _resolve_slice_counts extracts local_slices and remote_slices from active profile."""
    config = MagicMock()
    prof = HexaqueueProfileConfig(
        local_slices=2,
        remote_slices="auto",
    )
    config.stash.get.return_value = prof
    config.getoption.side_effect = lambda name, default=None: None

    tot, loc, rem = _resolve_slice_counts(config, item_count=120)
    assert loc == 2
    assert rem == 4
    assert tot == 6


def test_resolve_remote_slice_concurrency_variants() -> None:
    """Verify _resolve_remote_slice_concurrency handles all type permutations and bounds."""
    # None and empty
    assert _resolve_remote_slice_concurrency(None) is None
    assert _resolve_remote_slice_concurrency(0) == 0
    assert _resolve_remote_slice_concurrency("0") == 0
    assert _resolve_remote_slice_concurrency(False) == 0

    # Numeric integers
    assert _resolve_remote_slice_concurrency(8) == 8
    assert _resolve_remote_slice_concurrency("12") == 12

    # Boolean True -> auto
    assert _resolve_remote_slice_concurrency(True, item_count=90) == 4

    # 'auto' with variable item counts
    assert _resolve_remote_slice_concurrency("auto", item_count=0) == 4
    assert _resolve_remote_slice_concurrency("auto", item_count=2) == 2
    assert _resolve_remote_slice_concurrency("auto", item_count=120) == 4
    assert _resolve_remote_slice_concurrency("auto", item_count=300) == 10
    assert _resolve_remote_slice_concurrency("auto", item_count=1200) == 32

    # Invalid string fallback
    assert _resolve_remote_slice_concurrency("invalid-string") is None


def test_pytest_runtestloop_hybrid_execution() -> None:
    """Verify pytest_runtestloop executes local and remote slices concurrently in hybrid mode."""
    session = MagicMock()
    session.config = MagicMock()
    session.config.getoption.side_effect = lambda name, default=None: {
        "hexaqueue_enabled": True,
        "hexaqueue_profile": None,
        "hexaqueue_fallback": True,
        "hexaqueue_paid": False,
        "hexaqueue_server_url": "http://127.0.0.1:8000",
        "hexaqueue_api_token": None,
        "hexaqueue_pool": "default",
        "hexaqueue_container": False,
        "hexaqueue_worker_image": None,
    }.get(name, default)

    client = InMemoryTestDispatchClient(is_healthy=True)
    prof = HexaqueueProfileConfig(
        server_url="http://127.0.0.1:8000",
        api_token=None,
        pool="default",
        free_tier=True,
        fallback=True,
        mode="subprocess",
        slices=2,
    )

    s1 = TestSliceSpec(
        slice_id="s-local",
        slice_index=0,
        total_slices=2,
        test_nodeids=[],
    )
    s2 = TestSliceSpec(
        slice_id="s-remote",
        slice_index=1,
        total_slices=2,
        test_nodeids=[],
    )

    stash_dict: dict[Any, Any] = {
        _CLIENT_KEY: client,
        _CONFIG_KEY: prof,
        _SLICES_KEY: [s1, s2],
        _HYBRID_COUNTS_KEY: (1, 1),
    }
    session.config.stash = stash_dict
    session.items = []
    session.testsfailed = 0

    res = pytest_runtestloop(session)
    assert res is True
    reports: list[SliceOutcomeReport] = cast(
        "list[SliceOutcomeReport]", session.config.stash[_REPORTS_KEY]
    )
    assert len(reports) == 2
    assert reports[0].provider == "LOCAL"
    assert reports[1].slice_id == "s-remote"


def test_pytest_runtestloop_hybrid_fallback_on_unhealthy() -> None:
    """Verify hybrid mode falls back to executing all slices locally if remote cluster is unhealthy."""
    session = MagicMock()
    session.config = MagicMock()
    session.config.getoption.side_effect = lambda name, default=None: {
        "hexaqueue_enabled": True,
        "hexaqueue_profile": None,
        "hexaqueue_fallback": True,
        "hexaqueue_paid": False,
        "hexaqueue_server_url": "http://127.0.0.1:8000",
        "hexaqueue_api_token": None,
        "hexaqueue_pool": "default",
        "hexaqueue_container": False,
        "hexaqueue_worker_image": None,
    }.get(name, default)

    client = InMemoryTestDispatchClient(is_healthy=False)
    prof = HexaqueueProfileConfig(
        server_url="http://127.0.0.1:8000",
        api_token=None,
        pool="default",
        free_tier=True,
        fallback=True,
        mode="subprocess",
        slices=2,
    )

    s1 = TestSliceSpec(
        slice_id="s-local",
        slice_index=0,
        total_slices=2,
        test_nodeids=[],
    )
    s2 = TestSliceSpec(
        slice_id="s-remote",
        slice_index=1,
        total_slices=2,
        test_nodeids=[],
    )

    stash_dict_unhealthy: dict[Any, Any] = {
        _CLIENT_KEY: client,
        _CONFIG_KEY: prof,
        _SLICES_KEY: [s1, s2],
        _HYBRID_COUNTS_KEY: (1, 1),
    }
    session.config.stash = stash_dict_unhealthy
    session.items = []
    session.testsfailed = 0

    res = pytest_runtestloop(session)
    assert res is True
    reports: list[SliceOutcomeReport] = cast(
        "list[SliceOutcomeReport]", session.config.stash[_REPORTS_KEY]
    )
    assert len(reports) == 2
    # All slices ran locally via fallback
    assert reports[0].provider == "LOCAL"
    assert reports[1].provider == "LOCAL"


def test_pytest_terminal_summary_hybrid() -> None:
    """Verify terminal summary displays hybrid topology accurately."""
    reporter = MagicMock()
    config = MagicMock()
    config.getoption.side_effect = lambda name, default=None: {
        "hexaqueue_enabled": True,
        "hexaqueue_profile": None,
        "hexaqueue_paid": False,
        "hexaqueue_container": False,
    }.get(name, default)

    rep1 = SliceOutcomeReport(
        slice_id="s-loc",
        slice_index=0,
        worker_id="worker-local-0",
        provider="LOCAL",
        is_free_tier=True,
        outcomes=[],
        duration_seconds=0.1,
    )
    rep2 = SliceOutcomeReport(
        slice_id="s-rem",
        slice_index=1,
        worker_id="worker-oci-1",
        provider="OCI",
        is_free_tier=True,
        outcomes=[],
        duration_seconds=0.2,
    )

    config.stash = {
        _CONFIG_KEY: None,
        _REPORTS_KEY: [rep1, rep2],
    }

    pytest_terminal_summary(reporter, 0, config)
    written_lines = [call.args[0] for call in reporter.write_line.call_args_list]
    assert any(
        "Hybrid Slices (1 Local Workstation + 1 Remote Cluster)" in line
        for line in written_lines
    )


def test_normalize_coverage_sqlite_paths_and_remapping(tmp_path: Path) -> None:
    """Verify remote worker file paths in SQLite coverage DB are normalized and deduplicated."""
    from pytest_hexaqueue.infra.plugin import (
        _normalize_coverage_sqlite_paths,
        _remap_coverage_path,
    )

    pkg_file = tmp_path / "packages" / "demo_pkg" / "src" / "demo.py"
    pkg_file.parent.mkdir(parents=True)
    pkg_file.write_text("x = 1\n", encoding="utf-8")

    p_already_local = _remap_coverage_path(str(pkg_file), tmp_path)
    assert p_already_local == str(pkg_file)

    p_remote_root = _remap_coverage_path(
        "/opt/remote/work/packages/demo_pkg/src/demo.py",
        tmp_path,
        remote_root="/opt/remote/work",
    )
    assert p_remote_root == str(pkg_file)

    p_hq_runs = _remap_coverage_path(
        "/tmp/hexaqueue/runs/sess-999/packages/demo_pkg/src/demo.py",
        tmp_path,
    )
    assert p_hq_runs == str(pkg_file)

    p_workspace = _remap_coverage_path(
        "/workspace/packages/demo_pkg/src/demo.py",
        tmp_path,
    )
    assert p_workspace == str(pkg_file)

    p_suffix = _remap_coverage_path(
        "/custom/worker/dir/packages/demo_pkg/src/demo.py",
        tmp_path,
    )
    assert p_suffix == str(pkg_file)

    cov_db = tmp_path / ".coverage.hq.slice-norm"
    con = sqlite3.connect(str(cov_db))
    con.execute("CREATE TABLE file (id integer primary key, path text unique)")
    con.execute(
        "CREATE TABLE arc (file_id integer, context_id integer, fromno integer, tono integer, unique(file_id, context_id, fromno, tono))"
    )
    con.execute(
        "CREATE TABLE line_bits (file_id integer, context_id integer, numbits blob, unique(file_id, context_id))"
    )
    con.execute("CREATE TABLE tracer (file_id integer primary key, tracer text)")
    con.execute(
        "INSERT INTO file (id, path) VALUES (1, ?), (2, ?)",
        (
            str(pkg_file),
            "/tmp/hexaqueue/runs/sess-999/packages/demo_pkg/src/demo.py",
        ),
    )
    con.execute(
        "INSERT INTO arc (file_id, context_id, fromno, tono) VALUES (1, 1, 1, 2), (2, 1, 2, 3)"
    )
    con.commit()
    con.close()

    _normalize_coverage_sqlite_paths(cov_db, local_root=tmp_path)

    con_check = sqlite3.connect(str(cov_db))
    files = list(con_check.execute("SELECT id, path FROM file"))
    arcs = list(
        con_check.execute("SELECT file_id, fromno, tono FROM arc ORDER BY fromno")
    )
    con_check.close()

    assert files == [(1, str(pkg_file))]
    assert arcs == [(1, 1, 2), (1, 2, 3)]


def test_normalize_cov_sources_and_managed_ssh_tunnel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify workspace-relative coverage source normalization and managed SSH tunnel lifecycle."""
    from pytest_hexaqueue.adapters.client import HexaqueueTestDispatchClient
    from pytest_hexaqueue.infra.plugin import (
        _build_tunnel_command,
        _managed_ssh_tunnel,
        _normalize_cov_sources,
    )

    pkg_src = tmp_path / "packages" / "demo_pkg" / "src"
    pkg_src.mkdir(parents=True)

    normalized = _normalize_cov_sources(
        [str(pkg_src), str(tmp_path), "packages/other/src", "/outside/workspace/src"],
        root=tmp_path,
    )
    assert normalized == [
        "packages/demo_pkg/src",
        ".",
        "packages/other/src",
        "/outside/workspace/src",
    ]

    key_file = tmp_path / "id_ed25519"
    key_file.write_text("dummy-key", encoding="utf-8")
    monkeypatch.setattr(
        "hexaqueue_core.domain.credentials.discover_and_merge_env", dict
    )

    prof_no_host = HexaqueueProfileConfig(host=None)
    assert _build_tunnel_command(prof_no_host) is None

    prof_host = HexaqueueProfileConfig(
        host="129.146.115.79",
        ssh_user="hexaqueue-ci",
        ssh_key=str(key_file),
        ssh_port=2222,
        remote_port=8000,
        server_url="http://127.0.0.1:8000",
    )
    cmd = _build_tunnel_command(prof_host)
    assert cmd is not None
    assert "hexaqueue-ci@129.146.115.79" in cmd
    assert str(key_file) in cmd

    class _FakeProc:
        returncode: int | None = None

        def terminate(self) -> None:
            self.returncode = 0

        async def wait(self) -> int:
            return 0

    fake_proc = _FakeProc()

    async def _fake_exec(*args: Any, **kwargs: Any) -> _FakeProc:
        return fake_proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_exec)

    http_client = HexaqueueTestDispatchClient(server_url="http://127.0.0.1:8000")
    health_states = iter([False, False, True])

    async def _fake_health() -> bool:
        return next(health_states)

    monkeypatch.setattr(http_client, "health_check", _fake_health)

    async def _run_tunnel() -> bool:
        async with _managed_ssh_tunnel(prof_host, http_client) as ok:
            return bool(ok)

    tunnel_ok = asyncio.run(_run_tunnel())
    assert tunnel_ok is True
    assert fake_proc.returncode == 0


def test_plugin_module_reload_coverage() -> None:
    """Ensure top-level module definitions in plugin.py are tracked under test coverage."""
    mod = sys.modules[pytest_addoption.__module__]
    importlib.reload(mod)
    assert hasattr(mod, "pytest_addoption")
