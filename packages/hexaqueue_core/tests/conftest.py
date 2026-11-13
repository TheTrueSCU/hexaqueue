"""Pytest configuration for hexaqueue_core test suite.

Notes/Architectural Intent:
    Reloads pre-imported hexaqueue_core modules in strict AST topological
    dependency order after pytest-cov initializes coverage in pytest_sessionstart
    and prior to test collection, ensuring top-level definitions (Pydantic models,
    Enums, ABCs) imported early by the pytest-hexaqueue plugin are measured by
    coverage without class identity mismatches.
"""

import ast
import graphlib
import importlib
import sys
from pathlib import Path

import pytest


@pytest.hookimpl(trylast=True)
def pytest_sessionstart(session: pytest.Session) -> None:
    """Reload pre-imported hexaqueue_core modules in topological dependency order."""
    loaded = {
        name
        for name, mod in list(sys.modules.items())
        if mod is not None
        and (name == "hexaqueue_core" or name.startswith("hexaqueue_core."))
    }
    if not loaded:
        return

    core_mod = sys.modules.get("hexaqueue_core")
    if core_mod is None or not getattr(core_mod, "__file__", None):
        return

    src_root = Path(str(core_mod.__file__)).resolve().parent.parent
    deps: dict[str, set[str]] = {}
    for p in src_root.rglob("*.py"):
        rel = p.relative_to(src_root).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mod_name = ".".join(parts)
        if mod_name not in loaded:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        mod_deps: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("hexaqueue_core")
            ):
                mod_deps.add(node.module)
                for alias in node.names:
                    mod_deps.add(f"{node.module}.{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("hexaqueue_core"):
                        mod_deps.add(alias.name)
        deps[mod_name] = mod_deps

    for m in list(deps):
        deps[m] = {d for d in deps[m] if d in deps and d != m}

    sorter = graphlib.TopologicalSorter(deps)
    for name in sorter.static_order():
        mod = sys.modules.get(name)
        if mod is not None:
            importlib.reload(mod)
