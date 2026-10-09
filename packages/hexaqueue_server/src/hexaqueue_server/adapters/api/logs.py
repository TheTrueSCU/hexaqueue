"""Job execution log streaming and presigned storage URL REST endpoints.

Notes/Architectural Intent:
    Vends direct presigned upload and download URLs so clients and workers stream
    unbounded stdout/stderr payloads directly to/from cloud object storage (S3/GCS/Azure/MinIO)
    without saturating the central controller process.
"""

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline

from hexaqueue_core.domain.cqrs import (
    GetJobLogDownloadUrlQuery,
    GetLogsQuery,
    NotifyLogUploadCompleteCommand,
    PresignedDownloadUrl,
    PresignedUploadToken,
    RequestLogUploadUrlCommand,
)
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.adapters.api.auth import get_auth_context
from hexaqueue_server.adapters.api.common import _dispatch


def create_logs_router() -> APIRouter:
    """Construct APIRouter for log streaming and presigned storage operations.

    Returns:
        APIRouter with endpoints for log chunk retrieval and presigned tokens.
    """
    router = APIRouter()

    # 1. In-memory Log Chunks
    @router.get(
        "/jobs/{job_id}/logs",
        response_model=list[LogChunk],
        summary="Get job execution logs",
    )
    def get_logs(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        tail: Annotated[int | None, Query()] = None,
    ) -> list[LogChunk]:
        user_id, is_elevated = auth
        qry = GetLogsQuery(
            job_id=job_id, tail=tail, user_id=user_id, elevate=is_elevated
        )
        return _dispatch(pipeline, qry)

    # 2. Request Presigned Upload URL
    @router.post(
        "/jobs/{job_id}/logs/upload-url",
        response_model=PresignedUploadToken,
        summary="Request presigned log write endpoint",
    )
    def request_log_upload_url(
        job_id: str,
        cmd: RequestLogUploadUrlCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> PresignedUploadToken:
        """Request a presigned write URL to upload job execution logs.

        Args:
            job_id: Target job identifier.
            cmd: Upload URL request command parameters.
            pipeline: CQRS execution pipeline.
            auth: Caller authentication tuple.

        Returns:
            PresignedUploadToken with preauthenticated URL and lifecycle metadata.
        """
        user_id, is_elevated = auth
        effective_cmd = RequestLogUploadUrlCommand(
            job_id=job_id,
            outcome=cmd.outcome,
            size_bytes=cmd.size_bytes,
            expires_in_seconds=cmd.expires_in_seconds,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, effective_cmd)

    # 3. Notify Upload Complete
    @router.post(
        "/jobs/{job_id}/logs/complete",
        summary="Notify log upload completion",
    )
    def notify_log_upload_complete(
        job_id: str,
        cmd: NotifyLogUploadCompleteCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> dict[str, Any]:
        """Notify the server that a worker completed uploading job logs.

        Args:
            job_id: Finished job identifier.
            cmd: Completion notification command payload.
            pipeline: CQRS execution pipeline.
            auth: Caller authentication tuple.

        Returns:
            Dictionary recording log artifact status.
        """
        user_id, is_elevated = auth
        effective_cmd = NotifyLogUploadCompleteCommand(
            job_id=job_id,
            storage_key=cmd.storage_key,
            sha256_checksum=cmd.sha256_checksum,
            size_bytes=cmd.size_bytes,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, effective_cmd)

    # 4. Request Presigned Download URL
    @router.get(
        "/jobs/{job_id}/logs/download-url",
        response_model=PresignedDownloadUrl,
        summary="Get presigned direct log streaming URL",
    )
    def get_job_log_download_url(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        expires_in_seconds: Annotated[int, Query()] = 900,
    ) -> PresignedDownloadUrl:
        """Resolve a direct presigned download URL for client log streaming.

        Args:
            job_id: Target job identifier.
            pipeline: CQRS execution pipeline.
            auth: Caller authentication tuple.
            expires_in_seconds: Download link expiration window in seconds.

        Returns:
            PresignedDownloadUrl with preauthenticated read link.
        """
        user_id, is_elevated = auth
        qry = GetJobLogDownloadUrlQuery(
            job_id=job_id,
            expires_in_seconds=expires_in_seconds,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, qry)

    return router


__all__ = [
    "create_logs_router",
]
