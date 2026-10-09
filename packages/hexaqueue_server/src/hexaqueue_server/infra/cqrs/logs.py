"""CQRS handlers for log retrieval, presigned upload tokens, and download URL vending.

Notes/Architectural Intent:
    Resolves differential log retention policies based on job outcome, vends direct
    presigned S3/GCS URLs for offloaded worker telemetry uploads, and protects logs
    from unauthorized cross-tenant inspection.
"""

from typing import Any

from hexaqueue_core.adapters.storage.presigned import InMemoryPresignedStorageAdapter
from hexaqueue_core.domain.cqrs import (
    GetJobLogDownloadUrlQuery,
    GetLogsQuery,
    NotifyLogUploadCompleteCommand,
    PresignedDownloadUrl,
    PresignedUploadToken,
    RequestLogUploadUrlCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.retention import LogRetentionPolicy
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.infra.cqrs.common import (
    BaseCqrsService,
    _extract_job_owner,
)


class LogsCqrsMixin(BaseCqrsService):
    """Mixin implementing CQRS command and query handlers for execution logs."""

    async def handle_get_logs(self, qry: GetLogsQuery) -> list[LogChunk]:
        """Handle GetLogsQuery.

        Args:
            qry: Query payload.

        Returns:
            List of LogChunk entries.

        Raises:
            PermissionDeniedError: If unauthorized cross-tenant log inspection is attempted.
        """
        if not qry.elevate:
            try:
                job = await self.controller.get_job(qry.job_id)
                owner = _extract_job_owner(job)
                if owner != qry.user_id:
                    msg = (
                        f"Permission denied: You are not the owner of job '{qry.job_id}' (owned by '{owner}'). "
                        "Explicit administrative elevation (--admin / elevate=true) is required."
                    )
                    raise PermissionDeniedError(msg)
            except PermissionDeniedError:
                raise
            except Exception as exc:
                msg = (
                    f"Permission denied: Job '{qry.job_id}' not found in active registry to verify ownership. "
                    "Explicit administrative elevation (--admin / elevate=true) is required."
                )
                raise PermissionDeniedError(msg) from exc

        chunks = self.log_store.get(qry.job_id, [])
        if qry.tail is not None:
            return chunks[-qry.tail :]
        return chunks

    async def handle_request_log_upload_url(
        self, cmd: RequestLogUploadUrlCommand
    ) -> PresignedUploadToken:
        """Handle RequestLogUploadUrlCommand.

        Args:
            cmd: Command payload with job_id, outcome, and size.

        Returns:
            PresignedUploadToken containing preauthenticated write URL and retention metadata.

        Raises:
            PermissionDeniedError: If unauthorized cross-tenant upload is requested.

        Notes/Architectural Intent:
            Resolves differential retention policy based on terminal outcome
            (SHORT_PASS for COMPLETED vs LONG_FAIL for failures) and generates
            a direct presigned upload URL bypassing server API saturation.
        """
        if not cmd.elevate:
            try:
                job = await self.controller.get_job(cmd.job_id)
                owner = _extract_job_owner(job)
                if owner != cmd.user_id:
                    msg = (
                        f"Permission denied: You are not the owner of job '{cmd.job_id}' (owned by '{owner}'). "
                        "Explicit administrative elevation (--admin / elevate=true) is required."
                    )
                    raise PermissionDeniedError(msg)
            except PermissionDeniedError:
                raise
            except Exception:
                pass

        storage_key = f"logs/{cmd.job_id}/stdout_stderr.log"
        policy = LogRetentionPolicy.for_outcome(cmd.outcome)
        upload_url = await self.storage_port.generate_presigned_upload_url(
            key=storage_key,
            content_type="text/plain",
            expires_in_seconds=cmd.expires_in_seconds,
        )
        return PresignedUploadToken(
            job_id=cmd.job_id,
            upload_url=upload_url,
            storage_key=storage_key,
            retention_policy=policy,
            expires_in_seconds=cmd.expires_in_seconds,
        )

    async def handle_notify_log_upload_complete(
        self, cmd: NotifyLogUploadCompleteCommand
    ) -> dict[str, Any]:
        """Handle NotifyLogUploadCompleteCommand.

        Args:
            cmd: Command payload with uploaded log key, checksum, and size.

        Returns:
            Dictionary recording log artifact status.
        """
        self.log_artifacts[cmd.job_id] = {
            "storage_key": cmd.storage_key,
            "sha256_checksum": cmd.sha256_checksum,
            "size_bytes": cmd.size_bytes,
        }
        if isinstance(
            self.storage_port, InMemoryPresignedStorageAdapter
        ) and not await self.storage_port.object_exists(cmd.storage_key):
            self.storage_port.put_object(
                key=cmd.storage_key,
                data=b"[Simulated uploaded logs]",
                metadata={"sha256": cmd.sha256_checksum or ""},
            )
        return {
            "status": "recorded",
            "job_id": cmd.job_id,
            "storage_key": cmd.storage_key,
        }

    async def handle_get_job_log_download_url(
        self, qry: GetJobLogDownloadUrlQuery
    ) -> PresignedDownloadUrl:
        """Handle GetJobLogDownloadUrlQuery.

        Args:
            qry: Query payload with job_id.

        Returns:
            PresignedDownloadUrl with preauthenticated read link.

        Raises:
            PermissionDeniedError: If unauthorized cross-tenant log inspection is attempted.

        Notes/Architectural Intent:
            Vends direct preauthenticated download URL so clients stream directly
            from cloud object storage bypassing server API.
        """
        if not qry.elevate:
            try:
                job = await self.controller.get_job(qry.job_id)
                owner = _extract_job_owner(job)
                if owner != qry.user_id:
                    msg = (
                        f"Permission denied: You are not the owner of job '{qry.job_id}' (owned by '{owner}'). "
                        "Explicit administrative elevation (--admin / elevate=true) is required."
                    )
                    raise PermissionDeniedError(msg)
            except PermissionDeniedError:
                raise
            except Exception as exc:
                msg = (
                    f"Permission denied: Job '{qry.job_id}' not found in active registry to verify ownership. "
                    "Explicit administrative elevation (--admin / elevate=true) is required."
                )
                raise PermissionDeniedError(msg) from exc

        artifact = self.log_artifacts.get(qry.job_id)
        storage_key = (
            artifact["storage_key"]
            if artifact
            else f"logs/{qry.job_id}/stdout_stderr.log"
        )
        if isinstance(
            self.storage_port, InMemoryPresignedStorageAdapter
        ) and not await self.storage_port.object_exists(storage_key):
            self.storage_port.put_object(
                key=storage_key,
                data=b"[Simulated log stream]",
            )
        download_url = await self.storage_port.generate_presigned_download_url(
            key=storage_key,
            expires_in_seconds=qry.expires_in_seconds,
        )
        return PresignedDownloadUrl(
            job_id=qry.job_id,
            download_url=download_url,
            storage_key=storage_key,
            expires_in_seconds=qry.expires_in_seconds,
        )


__all__ = [
    "LogsCqrsMixin",
]
