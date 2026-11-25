"""Shared pytest fixtures for hermetic hexaqueue_cli test isolation.

Notes/Architectural Intent:
    Scrubs remote controller environment variables inherited from CI burst
    workers and redirects ``HOME`` to a per-test temporary directory so local
    CLI unit tests never leak job submissions to a live Hexaqueue controller or
    collide with persistent host collateral state under ``~/.hexaqueue``.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from hexaqueue_cli.domain.session import (
    set_active_controller_url,
    set_default_session,
)

_CONTROLLER_ENV_KEYS: tuple[str, ...] = (
    "HEXAQUEUE_CONTROLLER_URL",
    "HEXAQUEUE_URL",
    "HEXAQUEUE_ADMIN_TOKEN",
)


@pytest.fixture(autouse=True)
def isolate_cli_controller_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Clear controller URL/token env vars and isolate HOME around every CLI test.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        tmp_path: Per-test temporary directory used as isolated home directory.

    Yields:
        Control to the test body with isolated local CLI and filesystem state.

    Notes/Architectural Intent:
        Guarantees hermetic execution on distributed OCI workers (where
        ``HEXAQUEUE_CONTROLLER_URL`` is set in the host environment) and prevents
        ``LocalCollateralServiceAdapter`` from hydrating or mutating host
        ``~/.hexaqueue/collateral`` or ``~/.hexaqueue/dashboard-tunnel.sock``.
    """
    home_dir = tmp_path / "home"
    home_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    for key in _CONTROLLER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    set_active_controller_url(None)
    try:
        yield
    finally:
        set_active_controller_url(None)
        set_default_session(None)
