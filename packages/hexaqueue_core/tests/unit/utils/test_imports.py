"""Unit tests for require_dependency and optional_dependency utilities."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from hexastack_core.domain.exceptions import (
    MissingDependencyError as HexastackMissingDependencyError,
)

from hexaqueue_core.domain.exceptions import HexaqueueError, MissingDependencyError
from hexaqueue_core.utils.imports import optional_dependency, require_dependency


def test_require_dependency_installed_module() -> None:
    """Test successful import of an installed module."""
    mod = require_dependency("json", extra="core", package="hexaqueue-core")
    assert mod is not None
    assert hasattr(mod, "dumps")


def test_require_dependency_missing_module() -> None:
    """Test that importing a missing module raises an informative MissingDependencyError."""
    with (
        patch(
            "importlib.import_module",
            side_effect=ImportError("No module named 'nonexistent_lib'"),
        ),
        pytest.raises(
            MissingDependencyError,
            match=r"Optional dependency 'nonexistent_lib' is required\. Install with: pip install hexaqueue-scanner\[yara\]",
        ) as exc_info,
    ):
        require_dependency(
            "nonexistent_lib",
            extra="yara",
            package="hexaqueue-scanner",
        )

    err = exc_info.value
    assert isinstance(err, HexaqueueError)
    assert isinstance(err, HexastackMissingDependencyError)
    assert isinstance(err, ImportError)
    assert err.__cause__ is not None


def test_require_dependency_missing_module_with_feature_name() -> None:
    """Test that feature_name is included in the error message when provided."""
    with (
        patch(
            "importlib.import_module",
            side_effect=ImportError("No module named 'fake_lib'"),
        ),
        pytest.raises(
            MissingDependencyError,
            match=r"Optional dependency 'fake_lib' is required for YARA Scanner Engine\. Install with: pip install hexaqueue-scanner\[yara\]",
        ),
    ):
        require_dependency(
            "fake_lib",
            extra="yara",
            package="hexaqueue-scanner",
            feature_name="YARA Scanner Engine",
        )


def test_optional_dependency_installed_module() -> None:
    """Test optional_dependency returns module when installed."""
    mod = optional_dependency("json")
    assert mod is not None
    assert hasattr(mod, "loads")


def test_optional_dependency_missing_module_default() -> None:
    """Test optional_dependency returns None or default when module is missing."""
    with patch(
        "importlib.import_module",
        side_effect=ModuleNotFoundError("No module named 'nonexistent_pkg'"),
    ):
        res_none = optional_dependency("nonexistent_pkg")
        assert res_none is None

        sentinel = object()
        res_default = optional_dependency("nonexistent_pkg", default=sentinel)
        assert res_default is sentinel
