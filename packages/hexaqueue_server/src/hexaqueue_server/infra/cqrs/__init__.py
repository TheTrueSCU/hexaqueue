"""CQRS command and query infrastructure package for Hexaqueue Server.

Notes/Architectural Intent:
    Re-exports the consolidated HexaqueueCqrsService, the ExecutionPipeline factory,
    and the synchronous coroutine runner for backward compatibility and clean public API.
"""

from hexaqueue_server.infra.cqrs.common import run_coro_sync
from hexaqueue_server.infra.cqrs.pipeline import create_hexaqueue_execution_pipeline
from hexaqueue_server.infra.cqrs.service import HexaqueueCqrsService

__all__ = [
    "create_hexaqueue_execution_pipeline",
    "HexaqueueCqrsService",
    "run_coro_sync",
]
