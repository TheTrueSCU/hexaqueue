"""Unit tests for hexaqueue_core.utils exports."""

from __future__ import annotations

import hexaqueue_core.utils as utils


def test_utils_exports() -> None:
    """Verify that utils exports required helpers."""
    assert hasattr(utils, "optional_dependency")
    assert hasattr(utils, "require_dependency")
