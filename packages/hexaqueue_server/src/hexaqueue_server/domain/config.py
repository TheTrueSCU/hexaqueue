"""Configuration models and role definitions for Hexaqueue Server.

Notes/Architectural Intent:
    Defines server deployment roles (all, gateway, worker-api, analytics, mcp, custom)
    and granular interface toggles, enabling distributed topologies where specific
    subsystems run on dedicated nodes without monolithic surface exposure.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServerRole(StrEnum):
    """Preset operational roles for Hexaqueue Server deployments.

    Notes/Architectural Intent:
        Allows operators to run purpose-built nodes (e.g. public ingress gateway,
        isolated internal worker coordinator, dedicated FinOps analytics engine)
        with zero-config interface defaults.
    """

    ALL = "all"
    GATEWAY = "gateway"
    WORKER_API = "worker-api"
    ANALYTICS = "analytics"
    MCP = "mcp"
    CUSTOM = "custom"


class ServerInterfaceConfig(BaseModel):
    """Granular toggle settings for Hexaqueue Server HTTP and RPC interfaces.

    Args:
        runs: Mount /v1/runs and /v1/suites endpoints.
        jobs: Mount /v1/jobs management endpoints (list, cancel, hold, explain).
        nodes: Mount /v1/nodes cluster compute worker registration & telemetry.
        logs: Mount /v1/jobs/{job_id}/logs streaming and presigned storage URLs.
        cluster: Mount /v1/cluster statistics and dead-letter queues.
        collateral: Mount /v1/collateral CAS ingestion and lifecycle endpoints.
        budget: Mount /v1/budget reservation, settlement, and balance endpoints.
        webhooks: Mount /v1/webhooks inbound CI/CD event receivers.
        mcp: Enable Model Context Protocol driving adapter.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    budget: bool = Field(default=True, description="Enable budget accounting endpoints")
    cluster: bool = Field(
        default=True, description="Enable cluster telemetry and DLQ endpoints"
    )
    collateral: bool = Field(
        default=True, description="Enable collateral management endpoints"
    )
    jobs: bool = Field(default=True, description="Enable job management endpoints")
    logs: bool = Field(default=True, description="Enable log streaming endpoints")
    mcp: bool = Field(default=False, description="Enable MCP server adapter")
    nodes: bool = Field(
        default=True, description="Enable worker node registration endpoints"
    )
    runs: bool = Field(default=True, description="Enable run and suite endpoints")
    webhooks: bool = Field(
        default=True, description="Enable inbound webhook receiver endpoints"
    )

    @classmethod
    def for_role(cls, role: ServerRole) -> Self:
        """Construct interface configuration reflecting a predefined server role.

        Args:
            role: ServerRole preset.

        Returns:
            ServerInterfaceConfig with appropriate interfaces enabled.
        """
        match role:
            case ServerRole.GATEWAY:
                return cls(
                    runs=True,
                    jobs=True,
                    nodes=False,
                    logs=False,
                    cluster=False,
                    collateral=True,
                    budget=False,
                    webhooks=True,
                    mcp=False,
                )
            case ServerRole.WORKER_API:
                return cls(
                    runs=False,
                    jobs=True,
                    nodes=True,
                    logs=True,
                    cluster=False,
                    collateral=True,
                    budget=False,
                    webhooks=False,
                    mcp=False,
                )
            case ServerRole.ANALYTICS:
                return cls(
                    runs=False,
                    jobs=False,
                    nodes=False,
                    logs=False,
                    cluster=True,
                    collateral=False,
                    budget=True,
                    webhooks=False,
                    mcp=False,
                )
            case ServerRole.MCP:
                return cls(
                    runs=True,
                    jobs=True,
                    nodes=True,
                    logs=True,
                    cluster=True,
                    collateral=True,
                    budget=True,
                    webhooks=False,
                    mcp=True,
                )
            case _:  # ALL and CUSTOM default to full enablement
                return cls(
                    runs=True,
                    jobs=True,
                    nodes=True,
                    logs=True,
                    cluster=True,
                    collateral=True,
                    budget=True,
                    webhooks=True,
                    mcp=True,
                )


class ServerConfig(BaseModel):
    """Server lifecycle and networking configuration model.

    Args:
        host: Listen host address.
        port: Listen port number.
        engine: ASGI server engine ('uvicorn' or 'granian').
        role: Operational node role preset.
        interfaces: Granular interface enablement settings.
        workers: Process concurrency worker count.
        reload: Auto-reload on source modification.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: str = Field(
        default="uvicorn",
        description="HTTP/ASGI server engine ('uvicorn' or 'granian')",
    )
    host: str = Field(default="0.0.0.0", description="Server listen host address")
    interfaces: ServerInterfaceConfig = Field(
        default_factory=ServerInterfaceConfig,
        description="Active interface enablement settings",
    )
    port: int = Field(default=8000, ge=1, le=65535, description="Server listen port")
    reload: bool = Field(default=False, description="Enable auto-reload on code change")
    role: ServerRole = Field(
        default=ServerRole.ALL, description="Deployment node role preset"
    )
    workers: int | None = Field(default=None, ge=1, description="Worker process count")

    @model_validator(mode="after")
    def apply_role_defaults(self) -> Self:
        """Apply role preset defaults if role is non-custom and interfaces was not customized."""
        if (
            self.role != ServerRole.CUSTOM
            and self.interfaces == ServerInterfaceConfig()
        ):
            object.__setattr__(
                self, "interfaces", ServerInterfaceConfig.for_role(self.role)
            )
        return self


__all__ = [
    "ServerConfig",
    "ServerInterfaceConfig",
    "ServerRole",
]
