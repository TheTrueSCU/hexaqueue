"""Nox multi-version test orchestration matrix for Hexaqueue."""

from __future__ import annotations

import nox

nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True

PYTHON_VERSIONS = ["3.12", "3.13", "3.14", "3.15"]


@nox.session(python=PYTHON_VERSIONS, venv_backend="uv")
def tests(session: nox.Session) -> None:
    """Run unit and integration test suite across Python versions.

    Args:
        session: Nox session context configured with target Python runtime.
    """
    session.run_install(
        "uv",
        "sync",
        "--all-packages",
        "--all-extras",
        "--all-groups",
        f"--python={session.python}",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )
    session.run(
        "uv",
        "run",
        "hexaqual",
        "test",
        "run",
        "-U",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )


@nox.session(python=PYTHON_VERSIONS, venv_backend="uv")
def sanity(session: nox.Session) -> None:
    """Run scoped quality gates and architecture boundary checks across Python versions.

    Args:
        session: Nox session context configured with target Python runtime.
    """
    session.run_install(
        "uv",
        "sync",
        "--all-packages",
        "--all-extras",
        "--all-groups",
        f"--python={session.python}",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )
    session.run(
        "uv",
        "run",
        "hexaqual",
        "sanity",
        "-a",
        "--skip-tests",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )
