"""Unit tests for subpackage discovery and registration utilities.

Notes/Architectural Intent:
    Ensures robust handling of subpackage discovery, namespace registration,
    directory listing, and clear error guidance for uninstalled extras.
"""

from unittest.mock import MagicMock, patch

import pytest

from hexaqueue.subpackages import (
    ALL_SUBPACKAGES,
    discover_and_register_subpackages,
    get_subpackage_dir,
    handle_missing_subpackage,
)


def test_discover_and_register_subpackages_success() -> None:
    """Verify subpackages are successfully discovered and registered in namespace."""
    target_globals: dict[str, object] = {}
    mock_module = MagicMock()

    with (
        patch("importlib.util.find_spec", return_value=MagicMock()),
        patch("importlib.import_module", return_value=mock_module),
    ):
        installed = discover_and_register_subpackages(
            target_globals, ["core", "github_runner"]
        )

        assert len(installed) == 2
        assert "core" in installed
        assert "github_runner" in installed

        core_bound = target_globals.get("core")
        assert core_bound is mock_module


def test_discover_and_register_subpackages_not_found_or_error() -> None:
    """Verify missing or failing subpackages are safely skipped."""
    target_globals: dict[str, object] = {}

    with (
        patch("importlib.util.find_spec", side_effect=[None, MagicMock()]),
        patch(
            "importlib.import_module",
            side_effect=ImportError("broken dependency"),
        ),
    ):
        installed = discover_and_register_subpackages(
            target_globals, ["missing", "broken"]
        )

        assert len(installed) == 0


def test_get_subpackage_dir() -> None:
    """Verify __dir__ calculation merges globals and installed shorthands."""
    target_globals = {"__name__": "hexaqueue", "__doc__": "..."}
    installed = ["core", "server", "github_runner"]

    dir_listing = get_subpackage_dir(target_globals, installed)

    assert "__name__" in dir_listing
    assert "__doc__" in dir_listing
    assert "core" in dir_listing
    assert "github_runner" in dir_listing
    assert dir_listing == sorted(dir_listing)


def test_handle_missing_subpackage_known() -> None:
    """Verify helpful error guidance is provided for known ecosystem subpackages."""
    with pytest.raises(
        AttributeError, match="Subpackage 'github_runner' is part of the Hexaqueue"
    ):
        handle_missing_subpackage("github_runner", ALL_SUBPACKAGES)


def test_handle_missing_subpackage_unknown() -> None:
    """Verify standard AttributeError for completely unknown attributes."""
    with pytest.raises(
        AttributeError, match="module 'hexaqueue' has no attribute 'nonexistent'"
    ):
        handle_missing_subpackage("nonexistent", ALL_SUBPACKAGES)
