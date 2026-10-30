"""Configuration models and role definitions for Hexaqueue Server.

Notes/Architectural Intent:
    Defines server deployment roles (all, gateway, worker-api, analytics, mcp, custom)
    and granular interface toggles, enabling distributed topologies where specific
    subsystems run on dedicated nodes without monolithic surface exposure.
    Supports declarative TOML configuration files, feature-flag driven interface gating,
    and fine-grained tool controls for Model Context Protocol (MCP) driving adapters.
"""

import os
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.exceptions import HexaqueueConfigError


def _parse_flag_bool(val: Any) -> bool | None:
    """Normalize raw flag value or environment string into boolean or None.

    Args:
        val: Any raw input value.

    Returns:
        Boolean if recognized, otherwise None.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        cleaned = val.strip().lower()
        if cleaned in ("1", "true", "yes", "on", "enabled"):
            return True
        if cleaned in ("0", "false", "no", "off", "disabled"):
            return False
    return None


def _lookup_flag(
    name: str,
    flags: dict[str, Any] | None,
    use_env: bool,
) -> bool | None:
    """Resolve a boolean feature flag from a dictionary or environment variable.

    Args:
        name: Interface field name.
        flags: Optional feature flags dictionary.
        use_env: Whether to inspect environment variables.

    Returns:
        Boolean override if found, otherwise None.
    """
    if flags:
        for cand in (
            name,
            f"interface_{name}",
            f"interfaces.{name}",
            f"feature_{name}",
        ):
            if cand in flags:
                matched = _parse_flag_bool(flags[cand])
                if matched is not None:
                    return matched
    if use_env:
        for env_key in (
            f"HQ_INTERFACE_{name.upper()}",
            f"HQ_FEATURE_{name.upper()}",
        ):
            if env_key in os.environ:
                parsed = _parse_flag_bool(os.environ[env_key])
                if parsed is not None:
                    return parsed
    return None


def _lookup_mcp_flag(
    flag_keys: tuple[str, ...],
    env_keys: tuple[str, ...],
    flags: dict[str, Any] | None,
    use_env: bool,
) -> bool | None:
    """Resolve an MCP-specific boolean flag from dictionary or environment.

    Args:
        flag_keys: Tuple of candidate dictionary keys.
        env_keys: Tuple of candidate environment variable keys.
        flags: Optional feature flags dictionary.
        use_env: Whether to inspect environment variables.

    Returns:
        Boolean override if found, otherwise None.
    """
    if flags:
        for key in flag_keys:
            if key in flags:
                matched = _parse_flag_bool(flags[key])
                if matched is not None:
                    return matched
    if use_env:
        for env_key in env_keys:
            if env_key in os.environ:
                matched = _parse_flag_bool(os.environ[env_key])
                if matched is not None:
                    return matched
    return None


class ServerRole(StrEnum):
    """Preset operational roles for Hexaqueue Server deployments.

    Notes/Architectural Intent:
        Allows operators to run purpose-built nodes (e.g. public ingress gateway,
        isolated internal worker coordinator, dedicated FinOps analytics engine,
        or dedicated MCP assistant host) with zero-config interface defaults.
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
    mcp: bool = Field(default=True, description="Enable MCP server adapter")
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
                    runs=False,
                    jobs=False,
                    nodes=False,
                    logs=False,
                    cluster=False,
                    collateral=False,
                    budget=False,
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

    def apply_feature_flags(
        self,
        flags: dict[str, Any] | None = None,
        use_env: bool = True,
    ) -> Self:
        """Apply feature flags and environment variable overrides to interfaces.

        Notes/Architectural Intent:
            Enables dynamic toggling of public interfaces (especially MCP, webhooks, runs)
            via feature flag platforms (Flagd, OpenFeature) or container environment variables
            (e.g., HQ_INTERFACE_MCP=false, HQ_FEATURE_MCP=true).

        Args:
            flags: Optional dictionary mapping feature flag keys to boolean/string values.
            use_env: Whether to inspect environment variables.

        Returns:
            An updated ServerInterfaceConfig instance reflecting evaluated flag overrides.
        """
        updates: dict[str, bool] = {}
        for name in (
            "budget",
            "cluster",
            "collateral",
            "jobs",
            "logs",
            "mcp",
            "nodes",
            "runs",
            "webhooks",
        ):
            val = _lookup_flag(name, flags, use_env)
            if val is not None:
                updates[name] = val

        if updates:
            return self.model_copy(update=updates)
        return self


class McpToolConfig(BaseModel):
    """Granular tool enablement toggles for Hexaqueue MCP driving adapter.

    Notes/Architectural Intent:
        Allows operators to customize the exact tool surface exposed to LLM agents
        (e.g., exposing read-only query tools while disabling execution mutations).

    Args:
        get_cluster_nodes: Enable 'hq_get_cluster_nodes' tool.
        get_run_status: Enable 'hq_get_run_status' tool.
        lease_task: Enable 'hq_lease_task' tool.
        list_jobs: Enable 'hq_list_jobs' tool.
        stream_logs: Enable 'hq_stream_logs' tool.
        submit_run: Enable 'hq_submit_run' tool.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    get_cluster_nodes: bool = Field(
        default=True, description="Enable cluster node inspection tool"
    )
    get_run_status: bool = Field(
        default=True, description="Enable run status query tool"
    )
    lease_task: bool = Field(
        default=True, description="Enable worker task leasing tool"
    )
    list_jobs: bool = Field(default=True, description="Enable job list and filter tool")
    stream_logs: bool = Field(default=True, description="Enable log streaming tool")
    submit_run: bool = Field(
        default=True, description="Enable workflow run submission tool"
    )

    @classmethod
    def read_only(cls) -> Self:
        """Construct read-only tool configuration disabling mutations."""
        return cls(
            get_cluster_nodes=True,
            get_run_status=True,
            lease_task=False,
            list_jobs=True,
            stream_logs=True,
            submit_run=False,
        )


class McpConfig(BaseModel):
    """Model Context Protocol (MCP) server driving adapter configuration.

    Notes/Architectural Intent:
        Configures SSE transport paths, Bearer authentication, and per-tool enablement
        for the FastMCP driving adapter across server and stdio contexts.

    Args:
        auth_token: Optional Bearer authentication secret.
        enabled: Global toggle for MCP server integration.
        path_prefix: URL path prefix for SSE / HTTP endpoints.
        read_only: Enforce read-only tool mode (disables submit_run and lease_task).
        sse_path: Path suffix for SSE event stream.
        tools: Granular per-tool enablement settings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    auth_token: str | None = Field(
        default=None, description="Optional bearer token for MCP endpoints"
    )
    enabled: bool = Field(default=True, description="Enable MCP server adapter")
    path_prefix: str = Field(
        default="/mcp", description="Mount prefix for MCP SSE endpoints"
    )
    read_only: bool = Field(
        default=False, description="Restrict MCP tools to read-only queries"
    )
    sse_path: str = Field(
        default="/sse", description="Path suffix for Server-Sent Events"
    )
    tools: McpToolConfig = Field(
        default_factory=McpToolConfig, description="Tool enablement configuration"
    )

    @model_validator(mode="after")
    def apply_read_only_constraints(self) -> Self:
        """Enforce read-only tool restrictions when read_only is True."""
        if self.read_only:
            object.__setattr__(
                self,
                "tools",
                self.tools.model_copy(
                    update={"lease_task": False, "submit_run": False}
                ),
            )
        return self

    def apply_feature_flags(
        self,
        flags: dict[str, Any] | None = None,
        use_env: bool = True,
    ) -> Self:
        """Apply feature flags and environment variable overrides to MCP settings.

        Args:
            flags: Optional dictionary mapping feature flag keys to values.
            use_env: Whether to inspect environment variables.

        Returns:
            An updated McpConfig instance reflecting evaluated flag overrides.
        """
        updates: dict[str, Any] = {}

        matched_enabled = _lookup_mcp_flag(
            ("mcp", "mcp.enabled", "feature_mcp", "interface_mcp"),
            ("HQ_MCP_ENABLED", "HQ_INTERFACE_MCP", "HQ_FEATURE_MCP"),
            flags,
            use_env,
        )
        if matched_enabled is not None:
            updates["enabled"] = matched_enabled

        matched_ro = _lookup_mcp_flag(
            ("mcp.read_only", "mcp_read_only", "feature_mcp_read_only"),
            ("HQ_MCP_READ_ONLY",),
            flags,
            use_env,
        )
        if matched_ro is not None:
            updates["read_only"] = matched_ro

        if use_env and "HQ_MCP_AUTH_TOKEN" in os.environ:
            updates["auth_token"] = os.environ["HQ_MCP_AUTH_TOKEN"]

        res = self.model_copy(update=updates) if updates else self
        if res.read_only:
            res = res.model_copy(
                update={
                    "tools": res.tools.model_copy(
                        update={"lease_task": False, "submit_run": False}
                    )
                }
            )
        return res


class ServerConfig(BaseModel):
    """Server lifecycle and networking configuration model.

    Args:
        host: Listen host address.
        port: Listen port number.
        engine: ASGI server engine ('uvicorn' or 'granian').
        role: Operational node role preset.
        interfaces: Granular interface enablement settings.
        mcp: Model Context Protocol driving adapter configuration.
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
    mcp: McpConfig = Field(
        default_factory=McpConfig,
        description="Model Context Protocol (MCP) adapter configuration",
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

    @classmethod
    def load_from_toml(
        cls,
        path: str | Path,
        role_override: ServerRole | None = None,
        apply_env: bool = True,
    ) -> Self:
        """Load ServerConfig from a TOML configuration file.

        Notes/Architectural Intent:
            Parses TOML documents with [server], [server.interfaces], and [server.mcp] tables,
            applying role defaults and environment/feature-flag overrides.

        Args:
            path: Path to TOML configuration file.
            role_override: Optional ServerRole overriding the role specified in the file.
            apply_env: Whether to apply environment variable / feature flag overrides.

        Returns:
            Validated ServerConfig instance.

        Raises:
            HexaqueueConfigError: If file is missing or syntax is invalid.
        """
        file_path = Path(path)
        if not file_path.exists():
            msg = f"Configuration file not found at '{file_path}'"
            raise HexaqueueConfigError(msg)

        try:
            with file_path.open("rb") as f:
                raw_data = tomllib.load(f)

            server_data = raw_data.get("server", raw_data)

            # Build config
            cfg = cls.model_validate(server_data)
            if role_override is not None:
                cfg = cfg.model_copy(
                    update={
                        "role": role_override,
                        "interfaces": ServerInterfaceConfig.for_role(role_override),
                    }
                )
            if apply_env:
                iface = cfg.interfaces.apply_feature_flags(use_env=True)
                mcp_cfg = cfg.mcp.apply_feature_flags(use_env=True)
                cfg = cfg.model_copy(update={"interfaces": iface, "mcp": mcp_cfg})
            return cfg
        except Exception as err:
            raise HexaqueueConfigError(
                f"Failed to load server configuration: {err}"
            ) from err


__all__ = [
    "McpConfig",
    "McpToolConfig",
    "ServerConfig",
    "ServerInterfaceConfig",
    "ServerRole",
]
