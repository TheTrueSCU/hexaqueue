"""Unit tests for pytest-hexaqueue plugin hooks and execution loop."""

import importlib
import sys
from typing import Any
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
    _REPORTS_KEY,
    _SLICES_KEY,
    _get_slicer,
    _notify_session_reports,
    _resolve_plugin_config,
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


def test_plugin_module_reload_coverage() -> None:
    """Ensure top-level module definitions in plugin.py are tracked under test coverage."""
    mod = sys.modules[pytest_addoption.__module__]
    importlib.reload(mod)
    assert hasattr(mod, "pytest_addoption")


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
