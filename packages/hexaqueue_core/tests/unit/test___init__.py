"""Tests for hexaqueue_core root exports."""

import sys
from importlib.abc import InspectLoader

import hexaqueue_core


def test_hexaqueue_core_root_exports() -> None:
    """Verify core exports and trace pre-imported module definitions in isolated namespace."""
    for name, mod in list(sys.modules.items()):
        if mod is not None and (
            name == "hexaqueue_core" or name.startswith("hexaqueue_core.")
        ):
            loader = getattr(mod, "__loader__", None)
            if isinstance(loader, InspectLoader):
                code = loader.get_code(name)
                if code is not None:
                    exec(code, dict(mod.__dict__))  # noqa: S102
    assert hasattr(hexaqueue_core, "adapters")
    assert hasattr(hexaqueue_core, "domain")
    assert hasattr(hexaqueue_core, "infra")
    assert hasattr(hexaqueue_core, "ports")
    assert hasattr(hexaqueue_core, "testing")
    assert hasattr(hexaqueue_core, "utils")
