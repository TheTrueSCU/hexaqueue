"""Unit tests for pytest-hexaqueue plugin hooks and execution loop."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_hexaqueue.adapters.client import InMemoryTestDispatchClient
from pytest_hexaqueue.domain.outcome import (
    SliceOutcomeReport,
    TestOutcomeItem,
)
from pytest_hexaqueue.domain.slice import TestSliceSpec
from pytest_hexaqueue.infra.plugin import (
    _CLIENT_KEY,
    _REPORTS_KEY,
    _SLICES_KEY,
    pytest_addoption,
    pytest_collection_finish,
    pytest_configure,
    pytest_runtestloop,
    pytest_terminal_summary,
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
    assert "hexaqueue_api_token" in dest_names
    assert "hexaqueue_free_tier" in dest_names
    assert "hexaqueue_fallback" in dest_names


def test_pytest_configure() -> None:
    """Test marker configuration."""
    config = MagicMock()
    pytest_configure(config)
    config.addinivalue_line.assert_called_with(
        "markers",
        "hexaqueue: mark test for execution on Hexaqueue distributed cluster",
    )


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
    from pytest_hexaqueue.adapters.slicer import FileContiguousTestSlicer
    from pytest_hexaqueue.infra.plugin import _get_slicer

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
