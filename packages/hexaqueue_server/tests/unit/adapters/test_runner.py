"""Unit tests for run_hexaqueue_server runner adapter."""

from unittest.mock import patch

import pytest
from hexastack_core.domain.exceptions import MissingDependencyError

from hexaqueue_server.adapters.runner import run_hexaqueue_server
from hexaqueue_server.domain.config import ServerConfig


def test_run_hexaqueue_server_default_uvicorn() -> None:
    """Verify run_hexaqueue_server executes uvicorn by default."""
    with patch("hexaqueue_server.adapters.runner.run_server") as mock_run:
        run_hexaqueue_server()
        assert mock_run.called
        kwargs = mock_run.call_args.kwargs
        assert kwargs["engine"] == "uvicorn"
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 8000


def test_run_hexaqueue_server_granian_engine() -> None:
    """Verify run_hexaqueue_server passes granian engine when requested."""
    cfg = ServerConfig(engine="granian", port=9000)
    with patch("hexaqueue_server.adapters.runner.run_server") as mock_run:
        run_hexaqueue_server(config=cfg)
        assert mock_run.called
        kwargs = mock_run.call_args.kwargs
        assert kwargs["engine"] == "granian"
        assert kwargs["port"] == 9000


def test_run_hexaqueue_server_fallback_to_uvicorn() -> None:
    """Verify run_hexaqueue_server gracefully falls back to uvicorn if granian is missing."""
    cfg = ServerConfig(engine="granian")
    calls: list[str] = []

    def fake_run_server(*args: object, **kwargs: object) -> None:
        eng = kwargs.get("engine")
        calls.append(str(eng))
        if eng == "granian":
            raise MissingDependencyError("granian not installed")

    with patch(
        "hexaqueue_server.adapters.runner.run_server", side_effect=fake_run_server
    ):
        run_hexaqueue_server(config=cfg, fallback_to_uvicorn=True)
        assert calls == ["granian", "uvicorn"]


def test_run_hexaqueue_server_no_fallback_raises() -> None:
    """Verify run_hexaqueue_server raises MissingDependencyError if fallback is disabled."""
    cfg = ServerConfig(engine="granian")

    with (
        patch(
            "hexaqueue_server.adapters.runner.run_server",
            side_effect=MissingDependencyError("granian missing"),
        ),
        pytest.raises(MissingDependencyError, match="granian missing"),
    ):
        run_hexaqueue_server(config=cfg, fallback_to_uvicorn=False)
