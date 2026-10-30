"""Server process runner and engine execution adapter.

Notes/Architectural Intent:
    Wraps hexastack-fastapi's run_server engine dispatcher (supporting 'uvicorn'
    and high-performance Rust 'granian' ASGI servers). Provides automatic fallback
    to uvicorn when granian is not available.
"""

from typing import Any

from hexastack_core.domain.exceptions import MissingDependencyError
from hexastack_fastapi.adapters.server import run_server

from hexaqueue_server.adapters.api.app import create_server_app
from hexaqueue_server.domain.config import ServerConfig


def run_hexaqueue_server(
    config: ServerConfig | None = None,
    *,
    fallback_to_uvicorn: bool = True,
    **extra_kwargs: Any,
) -> None:
    """Execute Hexaqueue Server using the configured ASGI engine.

    Args:
        config: Optional ServerConfig with host, port, engine, and role settings.
        fallback_to_uvicorn: If True, falls back to Uvicorn if Granian is requested
            but not installed.
        **extra_kwargs: Extra keyword arguments forwarded to run_server.

    Raises:
        MissingDependencyError: If the chosen engine is missing and fallback is False.
    """
    cfg = config or ServerConfig()
    app = create_server_app(config=cfg)

    engine_to_use = cfg.engine.lower().strip()
    try:
        run_server(
            app=app,
            engine=engine_to_use,
            host=cfg.host,
            port=cfg.port,
            reload=cfg.reload,
            workers=cfg.workers,
            **extra_kwargs,
        )
    except MissingDependencyError:
        if fallback_to_uvicorn and engine_to_use != "uvicorn":
            run_server(
                app=app,
                engine="uvicorn",
                host=cfg.host,
                port=cfg.port,
                reload=cfg.reload,
                workers=cfg.workers,
                **extra_kwargs,
            )
        else:
            raise


__all__ = [
    "run_hexaqueue_server",
]
