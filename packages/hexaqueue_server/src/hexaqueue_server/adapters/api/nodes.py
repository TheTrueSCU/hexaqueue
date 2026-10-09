"""Compute worker node registration, telemetry, heartbeat pulse, and bastion shell REST endpoints.

Notes/Architectural Intent:
    Handles compute worker heartbeat tracking, hardware telemetry aggregation,
    Content-Addressable Storage (CAS) warm cache indexing, and secure bastion terminal access.
"""

from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    status,
)
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline

from hexaqueue_core.domain.cqrs import (
    CreateBastionSessionCommand,
    GetNodesQuery,
    HeartbeatNodeCommand,
    ListComputeNodesQuery,
    NodesReport,
    RegisterNodeCommand,
)
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_server.adapters.api.auth import get_auth_context
from hexaqueue_server.adapters.api.common import _dispatch
from hexaqueue_worker.domain.pty import PtySessionInfo
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


def create_nodes_router() -> APIRouter:
    """Construct APIRouter for compute node telemetry, registration, and health monitoring.

    Returns:
        APIRouter with endpoints for worker node registration, heartbeat, and SSH.
    """
    router = APIRouter()

    # 1. Nodes Telemetry Pulses
    @router.get(
        "/nodes",
        response_model=list[NodeTelemetryPulse],
        summary="Get registered compute worker nodes",
    )
    def get_nodes(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> list[NodeTelemetryPulse]:
        user_id, is_elevated = auth
        qry = GetNodesQuery(user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 2. Node Bastion SSH Terminal
    @router.post(
        "/nodes/{node_id}/ssh",
        response_model=PtySessionInfo,
        summary="Launch secure bastion shell on node",
    )
    def create_bastion_ssh(
        node_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> PtySessionInfo:
        user_id, is_elevated = auth
        cmd = CreateBastionSessionCommand(
            node_id=node_id,
            session_id=f"bastion-{uuid4().hex[:8]}",
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, cmd)

    # 3. Register Compute Worker Node
    @router.post(
        "/nodes/register",
        status_code=status.HTTP_201_CREATED,
        summary="Register compute worker node with central controller",
    )
    def register_node(
        cmd: RegisterNodeCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> dict[str, str]:
        user_id, is_elevated = auth
        effective_cmd = RegisterNodeCommand(
            profile=cmd.profile,
            user_id=user_id,
            elevate=is_elevated,
        )
        _dispatch(pipeline, effective_cmd)
        return {"status": "REGISTERED", "node_id": cmd.profile.node_id}

    # 4. Worker Heartbeat Pulse
    @router.post(
        "/nodes/heartbeat",
        response_model=ComputeNodeProfile,
        summary="Record heartbeat pulse from compute worker node",
    )
    def heartbeat_node(
        cmd: HeartbeatNodeCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> ComputeNodeProfile:
        user_id, is_elevated = auth
        effective_cmd = HeartbeatNodeCommand(
            worker_id=cmd.worker_id,
            active_job_ids=cmd.active_job_ids,
            cached_collateral_hashes=cmd.cached_collateral_hashes,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, effective_cmd)

    # 5. List Compute Node Profiles
    @router.get(
        "/nodes/profiles",
        response_model=NodesReport,
        summary="List all registered compute worker node profiles",
    )
    def list_compute_nodes(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> NodesReport:
        user_id, is_elevated = auth
        qry = ListComputeNodesQuery(user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    return router


__all__ = [
    "create_nodes_router",
]
