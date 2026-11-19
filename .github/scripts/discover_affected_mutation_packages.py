"""Discover directly affected workspace packages for parallel mutation matrix jobs.

Notes/Architectural Intent:
    Inspects ``git diff --name-only`` against the PR base branch and emits a
    GitHub Actions matrix sorted in Longest-Processing-Time-first (LPT) order
    by total Python source lines so the heaviest package starts immediately.
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path


def _changed_files(base_ref: str) -> list[str]:
    """Return paths changed relative to ``origin/<base_ref>`` (or ``HEAD~1``)."""
    candidates = (
        [f"origin/{base_ref}...HEAD", "HEAD~1...HEAD"]
        if base_ref
        else ["HEAD~1...HEAD"]
    )
    for diff_range in candidates:
        res = subprocess.run(
            ["git", "diff", "--name-only", diff_range],  # noqa: S603, S607
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    return []


def _package_line_count(pkg_dir: Path) -> int:
    """Count Python source lines under ``pkg_dir/src`` for LPT ordering."""
    src_dir = pkg_dir / "src"
    if not src_dir.is_dir():
        return 0
    return sum(
        len(path.read_text(encoding="utf-8").splitlines())
        for path in src_dir.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def discover_affected_packages(
    base_ref: str,
    packages_root: Path = Path("packages"),
) -> list[str]:
    """Return affected package distribution names ordered largest-first (LPT).

    Args:
        base_ref: Git base branch name (e.g. ``main``).
        packages_root: Root directory containing workspace packages.

    Returns:
        List of affected package names sorted descending by source line count.
    """
    changed = _changed_files(base_ref)
    touched_dirs: set[str] = set()
    for rel_path in changed:
        parts = Path(rel_path).parts
        if (
            len(parts) >= 2
            and parts[0] == packages_root.name
            and (rel_path.endswith(".py") or parts[-1] == "pyproject.toml")
        ):
            touched_dirs.add(parts[1])

    sized: list[tuple[int, str]] = []
    for dir_name in sorted(touched_dirs):
        pkg_dir = packages_root / dir_name
        pyproject = pkg_dir / "pyproject.toml"
        if not pyproject.is_file():
            continue
        meta = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        dist_name = str(meta.get("project", {}).get("name", dir_name))
        sized.append((_package_line_count(pkg_dir), dist_name))

    sized.sort(key=lambda item: (-item[0], item[1]))
    return [name for _lines, name in sized]


def main() -> int:
    """Write ``matrix`` and ``has_affected`` outputs to ``$GITHUB_OUTPUT``."""
    base_ref = os.environ.get("GITHUB_BASE_REF", "main").strip()
    packages = discover_affected_packages(base_ref)
    matrix_json = json.dumps({"package": packages})
    has_affected = "true" if packages else "false"

    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    lines = [f"matrix={matrix_json}", f"has_affected={has_affected}"]
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
