"""ExecutionPipeline builder wiring Hexaqueue CQRS command and query buses.

Notes/Architectural Intent:
    Serves as the Single Source of Truth for executing CQRS contracts across
    CLI, REST API, gRPC, and Web Dashboard. Registers all domain handlers
    against synchronous command and query registries.
"""

from hexastack_cqrs.adapters.buses.command.synchronous import SynchronousCommandBus
from hexastack_cqrs.adapters.buses.event.synchronous import SynchronousEventBus
from hexastack_cqrs.adapters.buses.query.synchronous import SynchronousQueryBus
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_cqrs.infra.registries.command import CommandRegistry
from hexastack_cqrs.infra.registries.handler import HandlerRegistry
from hexastack_cqrs.infra.registries.query import QueryRegistry

from hexaqueue_collateral.ports.service import CollateralServicePort
from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CancelRunCommand,
    CreateBastionSessionCommand,
    CreatePtySessionCommand,
    EvictExpiredCollateralCommand,
    ExplainJobQuery,
    FindCollateralByChecksumQuery,
    GetCollateralBundleQuery,
    GetCollateralDownloadUrlQuery,
    GetDeadLetterQueueQuery,
    GetFairShareTreeQuery,
    GetJobLogDownloadUrlQuery,
    GetJobQuery,
    GetLogsQuery,
    GetNodesQuery,
    GetQueueStatsQuery,
    GetRunStatusQuery,
    HeartbeatNodeCommand,
    HoldJobCommand,
    ListComputeNodesQuery,
    ListJobsQuery,
    NotifyLogUploadCompleteCommand,
    PinCollateralCommand,
    RegisterCollateralCommand,
    RegisterNodeCommand,
    ReleaseJobCommand,
    RequestLogUploadUrlCommand,
    SettleBudgetCommand,
    SubmitRunCommand,
    SubmitSuiteCommand,
    UnpinCollateralCommand,
)
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_core.ports.storage import PresignedStoragePort
from hexaqueue_server.infra.cqrs.common import run_coro_sync
from hexaqueue_server.infra.cqrs.service import HexaqueueCqrsService
from hexaqueue_server.ports.controller import SchedulerControllerPort
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


def create_hexaqueue_execution_pipeline(
    controller: SchedulerControllerPort,
    log_store: dict[str, list[LogChunk]] | None = None,
    nodes: list[NodeTelemetryPulse] | None = None,
    storage_port: PresignedStoragePort | None = None,
    collateral_service: CollateralServicePort | None = None,
) -> ExecutionPipeline:
    """Construct an ExecutionPipeline with all Hexaqueue CQRS command and query handlers.

    Args:
        controller: Central scheduler controller instance.
        log_store: Optional in-memory dictionary for historical job log chunks.
        nodes: Optional list of registered worker node telemetry pulses.
        storage_port: Optional presigned storage port for log artifacts.
        collateral_service: Optional collateral service instance.

    Returns:
        Configured and populated ExecutionPipeline ready for synchronous dispatch.

    Notes/Architectural Intent:
        Wires unified command and query registries with HexaqueueCqrsService, ensuring
        hermetic execution and parity across all driving interfaces.
    """
    service = HexaqueueCqrsService(
        controller=controller,
        log_store=log_store,
        nodes=nodes,
        storage_port=storage_port,
        collateral_service=collateral_service,
    )
    handler_reg = HandlerRegistry()
    command_reg = CommandRegistry()
    query_reg = QueryRegistry()

    # Commands
    command_reg.register(SubmitRunCommand)
    handler_reg.register(
        SubmitRunCommand,
        lambda cmd: run_coro_sync(service.handle_submit_run(cmd)),
    )

    command_reg.register(SubmitSuiteCommand)
    handler_reg.register(
        SubmitSuiteCommand,
        lambda cmd: run_coro_sync(service.handle_submit_suite(cmd)),
    )

    command_reg.register(CancelRunCommand)
    handler_reg.register(
        CancelRunCommand,
        lambda cmd: run_coro_sync(service.handle_cancel_run(cmd)),
    )

    command_reg.register(HoldJobCommand)
    handler_reg.register(
        HoldJobCommand,
        lambda cmd: run_coro_sync(service.handle_hold_job(cmd)),
    )

    command_reg.register(ReleaseJobCommand)
    handler_reg.register(
        ReleaseJobCommand,
        lambda cmd: run_coro_sync(service.handle_release_job(cmd)),
    )

    command_reg.register(CancelJobCommand)
    handler_reg.register(
        CancelJobCommand,
        lambda cmd: run_coro_sync(service.handle_cancel_job(cmd)),
    )

    command_reg.register(RegisterCollateralCommand)
    handler_reg.register(
        RegisterCollateralCommand,
        lambda cmd: run_coro_sync(service.handle_register_collateral(cmd)),
    )

    command_reg.register(PinCollateralCommand)
    handler_reg.register(
        PinCollateralCommand,
        lambda cmd: run_coro_sync(service.handle_pin_collateral(cmd)),
    )

    command_reg.register(UnpinCollateralCommand)
    handler_reg.register(
        UnpinCollateralCommand,
        lambda cmd: run_coro_sync(service.handle_unpin_collateral(cmd)),
    )

    command_reg.register(EvictExpiredCollateralCommand)
    handler_reg.register(
        EvictExpiredCollateralCommand,
        lambda cmd: run_coro_sync(service.handle_evict_expired_collateral(cmd)),
    )

    command_reg.register(CreatePtySessionCommand)
    handler_reg.register(
        CreatePtySessionCommand,
        lambda cmd: run_coro_sync(service.handle_create_pty_session(cmd)),
    )

    command_reg.register(CreateBastionSessionCommand)
    handler_reg.register(
        CreateBastionSessionCommand,
        lambda cmd: run_coro_sync(service.handle_create_bastion_session(cmd)),
    )

    command_reg.register(SettleBudgetCommand)
    handler_reg.register(
        SettleBudgetCommand,
        lambda cmd: run_coro_sync(service.handle_settle_budget(cmd)),
    )

    command_reg.register(RequestLogUploadUrlCommand)
    handler_reg.register(
        RequestLogUploadUrlCommand,
        lambda cmd: run_coro_sync(service.handle_request_log_upload_url(cmd)),
    )

    command_reg.register(NotifyLogUploadCompleteCommand)
    handler_reg.register(
        NotifyLogUploadCompleteCommand,
        lambda cmd: run_coro_sync(service.handle_notify_log_upload_complete(cmd)),
    )

    command_reg.register(RegisterNodeCommand)
    handler_reg.register(
        RegisterNodeCommand,
        lambda cmd: run_coro_sync(service.handle_register_node(cmd)),
    )

    command_reg.register(HeartbeatNodeCommand)
    handler_reg.register(
        HeartbeatNodeCommand,
        lambda cmd: run_coro_sync(service.handle_heartbeat_node(cmd)),
    )

    # Queries
    query_reg.register(GetRunStatusQuery)
    handler_reg.register(
        GetRunStatusQuery,
        lambda qry: run_coro_sync(service.handle_get_run_status(qry)),
    )

    query_reg.register(GetJobQuery)
    handler_reg.register(
        GetJobQuery,
        lambda qry: run_coro_sync(service.handle_get_job(qry)),
    )

    query_reg.register(ListJobsQuery)
    handler_reg.register(
        ListJobsQuery,
        lambda qry: run_coro_sync(service.handle_list_jobs(qry)),
    )

    query_reg.register(ExplainJobQuery)
    handler_reg.register(
        ExplainJobQuery,
        lambda qry: run_coro_sync(service.handle_explain_job(qry)),
    )

    query_reg.register(GetFairShareTreeQuery)
    handler_reg.register(
        GetFairShareTreeQuery,
        lambda qry: run_coro_sync(service.handle_get_fairshare_tree(qry)),
    )

    query_reg.register(GetQueueStatsQuery)
    handler_reg.register(
        GetQueueStatsQuery,
        lambda qry: run_coro_sync(service.handle_get_queue_stats(qry)),
    )

    query_reg.register(GetNodesQuery)
    handler_reg.register(
        GetNodesQuery,
        lambda qry: run_coro_sync(service.handle_get_nodes(qry)),
    )

    query_reg.register(GetLogsQuery)
    handler_reg.register(
        GetLogsQuery,
        lambda qry: run_coro_sync(service.handle_get_logs(qry)),
    )

    query_reg.register(GetJobLogDownloadUrlQuery)
    handler_reg.register(
        GetJobLogDownloadUrlQuery,
        lambda qry: run_coro_sync(service.handle_get_job_log_download_url(qry)),
    )

    query_reg.register(GetDeadLetterQueueQuery)
    handler_reg.register(
        GetDeadLetterQueueQuery,
        lambda qry: run_coro_sync(service.handle_get_dead_letters(qry)),
    )

    query_reg.register(ListComputeNodesQuery)
    handler_reg.register(
        ListComputeNodesQuery,
        lambda qry: run_coro_sync(service.handle_list_compute_nodes(qry)),
    )

    query_reg.register(GetCollateralBundleQuery)
    handler_reg.register(
        GetCollateralBundleQuery,
        lambda qry: run_coro_sync(service.handle_get_collateral_bundle(qry)),
    )

    query_reg.register(FindCollateralByChecksumQuery)
    handler_reg.register(
        FindCollateralByChecksumQuery,
        lambda qry: run_coro_sync(service.handle_find_collateral_by_checksum(qry)),
    )

    query_reg.register(GetCollateralDownloadUrlQuery)
    handler_reg.register(
        GetCollateralDownloadUrlQuery,
        lambda qry: run_coro_sync(service.handle_get_collateral_download_url(qry)),
    )

    return ExecutionPipeline(
        command_bus=SynchronousCommandBus(handler_registry=handler_reg),
        query_bus=SynchronousQueryBus(handler_registry=handler_reg),
        event_bus=SynchronousEventBus(),
        command_registry=command_reg,
        query_registry=query_reg,
        handler_registry=handler_reg,
    )


__all__ = [
    "create_hexaqueue_execution_pipeline",
]
