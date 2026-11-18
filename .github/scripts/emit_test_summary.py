"""Emit JUnit XML test execution summary to ``$GITHUB_STEP_SUMMARY``.

Notes/Architectural Intent:
    Invoked by ``.github/workflows/ci.yml`` after pytest completes using only
    the Python standard library.
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    """Parse ``junit.xml`` and append test metrics to ``$GITHUB_STEP_SUMMARY``.

    Returns:
        Exit code ``0`` on completion (or non-fatal warning on parse error).
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        sys.stderr.write("GITHUB_STEP_SUMMARY is not set; skipping test summary.\n")
        return 0

    junit_path = Path(os.environ.get("JUNIT_XML_PATH", "junit.xml"))
    if not junit_path.exists():
        sys.stderr.write(
            f"JUnit XML not found at {junit_path}; skipping test summary.\n"
        )
        return 0

    try:
        tree = ET.parse(junit_path)  # noqa: S314
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Error parsing {junit_path}: {exc}\n")
        return 0

    root = tree.getroot()
    suites = list(root) if root.tag == "testsuites" else [root]
    tests = sum(int(s.attrib.get("tests", 0)) for s in suites)
    failures = sum(int(s.attrib.get("failures", 0)) for s in suites)
    errors = sum(int(s.attrib.get("errors", 0)) for s in suites)
    skipped = sum(int(s.attrib.get("skipped", 0)) for s in suites)
    duration = sum(float(s.attrib.get("time", 0.0)) for s in suites)
    passed = tests - failures - errors - skipped

    cluster_ready = os.environ.get("CLUSTER_READY") == "true"
    cluster_host = os.environ.get("CLUSTER_HOST", "").strip()
    py_ver = os.environ.get("PYTHON_VERSION", "").strip()
    engine_str = (
        f"⚡ Hexaqueue Cloud Fleet (`{cluster_host}` via Zero-Trust SSH Tunnel)"
        if cluster_ready
        else "🖥️ Local Runner (In-Process xdist)"
    )

    lines = [
        f"### 🧪 Test Execution Summary (Python {py_ver})",
        "",
        f"- **Execution Engine**: {engine_str}",
        f"- **Total Tests**: `{tests}`",
        (
            f"- **Results**: ✅ `{passed}` passed, ❌ `{failures}` failed, "
            f"⚠️ `{errors}` errors, ⏭️ `{skipped}` skipped"
        ),
        f"- **Aggregated Suite Duration**: `{duration:.2f}s`",
        "",
    ]

    target = Path(summary_path)
    with target.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    sys.stdout.write(
        f"Appended test summary to {summary_path} ({target.stat().st_size} bytes)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
