"""Domain models and discovery loaders for Hexaqueue runner configuration files.

Notes/Architectural Intent:
    Provides centralized resolution for project-level runner configurations
    defined in `[tool.hexaqueue]` within `pyproject.toml` or `hexaqueue.yaml`.
    Implements a 4-tier resolution hierarchy:
      1. Explicit CLI overrides (highest)
      2. Environment variables (.env / .env.local)
      3. Active named profile (--hq-profile / HEXAQUEUE_PROFILE)
      4. Configuration file ([tool.hexaqueue] / hexaqueue.yaml)
      5. Built-in defaults (lowest)
"""

from __future__ import annotations

import contextlib
import logging
import os
import tomllib
import warnings
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.utils.imports import optional_dependency

logger = logging.getLogger(__name__)


def parse_bool(val: Any, default: bool = False) -> bool:
    """Parse string or boolean value to boolean.

    Args:
        val: Input string, boolean, or None.
        default: Fallback boolean if val is None or empty.

    Returns:
        Converted boolean value.

    Notes/Architectural Intent:
        Centralizes Twelve-Factor environment variable and config boolean coercion,
        recognizing standard truthy ('1', 'true', 'yes', 'on') and falsy ('0', 'false', 'no', 'off') strings.
    """
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    str_val = str(val).strip().lower()
    if str_val in ("1", "true", "yes", "on"):
        return True
    if str_val in ("0", "false", "no", "off"):
        return False
    return default


def resolve_cost_preference(
    paid: Any = None,
    free_tier: Any = None,
    source: str = "configuration",
) -> bool | None:
    """Resolve conflict between paid and free flags, defaulting to free tier.

    Args:
        paid: Whether paid compute is explicitly requested.
        free_tier: Whether free tier is explicitly requested.
        source: Description of configuration source for warning message.

    Returns:
        Resolved boolean for free_tier (True for free, False for paid), or None if neither set.

    Notes/Architectural Intent:
        Enforces the Zero-Spend Invariant (ADR-003): when conflicting signals are received,
        Hexaqueue always defaults to the safe $0.00 spend ceiling.
    """
    has_paid = paid is not None
    has_free = free_tier is not None
    if not has_paid and not has_free:
        return None

    paid_bool = parse_bool(paid) if has_paid else False
    free_bool = parse_bool(free_tier) if has_free else False

    if has_paid and has_free and paid_bool and free_bool:
        logger.warning(
            "Conflict detected in %s: both paid and free tier are enabled. "
            "Defaulting to zero-cost free tier ($0.00 spend ceiling) for safety.",
            source,
        )
        warnings.warn(
            f"Conflict detected in {source}: both paid and free tier requested. "
            "Defaulting to zero-cost free tier ($0.00 spend ceiling) for safety.",
            UserWarning,
            stacklevel=3,
        )
        return True

    if has_paid and paid_bool:
        return False

    if has_free:
        return free_bool

    return not paid_bool


class HexaqueueContainerConfig(BaseModel):
    """Container runtime execution settings.

    Args:
        image: OCI container image tag.
        runtime: Target container runtime engine ('auto', 'docker', 'podman').
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    image: str = Field(
        default="hexaqueue-worker:latest", description="Worker container image"
    )
    runtime: str = Field(
        default="auto", description="Container engine: auto, docker, or podman"
    )


class HexaqueueProfileConfig(BaseModel):
    """Execution parameters for a specific profile or active run.

    Args:
        server_url: Cluster controller API URL.
        slices: Number of parallel slices.
        slicer: Partitioning strategy ('round-robin' or 'file').
        pool: Target compute instance pool.
        mode: Execution paradigm ('subprocess', 'container', 'csp', 'kueue').
        container: Container runtime configuration.
        free_tier: Enforce multi-CSP free tier limits.
        fallback: Allow in-process execution fallback when server is unreachable.
        api_token: Cluster authentication token.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    api_token: str | None = Field(
        default=None, description="Cluster authentication token"
    )
    container: HexaqueueContainerConfig = Field(
        default_factory=HexaqueueContainerConfig,
        description="Container runtime options",
    )
    fallback: bool = Field(
        default=True, description="Fall back to local execution if cluster offline"
    )
    free_tier: bool = Field(
        default=True,
        description="Enforce zero-cost free-tier guards ($0.00 spend ceiling)",
    )
    mode: str = Field(
        default="subprocess",
        description="Execution mode: subprocess, container, csp, kueue",
    )
    pool: str = Field(
        default="default", description="Compute pool for runner placement"
    )
    server_url: str = Field(
        default="http://127.0.0.1:8000", description="Hexaqueue server base URL"
    )
    slicer: str = Field(
        default="round-robin",
        description="Test partitioning algorithm: round-robin or file",
    )
    slices: int = Field(
        default=4, ge=1, description="Number of parallel execution partitions"
    )


class HexaqueueProjectConfig(BaseModel):
    """Project-level Hexaqueue configuration holding default settings and named profiles.

    Args:
        server_url: Default cluster controller API URL.
        slices: Default parallel slice count.
        slicer: Default partitioning algorithm.
        pool: Default compute pool.
        mode: Default execution mode.
        container: Default container runtime settings.
        free_tier: Default free-tier enforcement.
        fallback: Default fallback behavior.
        api_token: Default cluster token.
        profiles: Dictionary mapping profile names to HexaqueueProfileConfig instances.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    api_token: str | None = Field(default=None)
    container: HexaqueueContainerConfig = Field(
        default_factory=HexaqueueContainerConfig
    )
    fallback: bool = Field(default=True)
    free_tier: bool = Field(
        default=True,
        description="Default zero-cost free-tier guards ($0.00 spend ceiling)",
    )
    mode: str = Field(default="subprocess")
    pool: str = Field(default="default")
    profiles: dict[str, HexaqueueProfileConfig] = Field(default_factory=dict)
    server_url: str = Field(default="http://127.0.0.1:8000")
    slicer: str = Field(default="round-robin")
    slices: int = Field(default=4, ge=1)


def _parse_toml_config(path: Path) -> dict[str, Any]:
    """Parse [tool.hexaqueue] section from a pyproject.toml file."""
    try:
        content = path.read_text(encoding="utf-8")
        data = tomllib.loads(content)
        tool_section = data.get("tool", {})
        return tool_section.get("hexaqueue", {})
    except Exception:
        return {}


def _parse_yaml_config(path: Path) -> dict[str, Any]:
    """Parse hexaqueue.yaml configuration file using PyYAML when available."""
    yaml_mod = optional_dependency("yaml")
    if yaml_mod is not None:
        with contextlib.suppress(Exception):
            content = path.read_text(encoding="utf-8")
            loaded = yaml_mod.safe_load(content)
            if isinstance(loaded, dict):
                return loaded
    return {}


def discover_config_file(
    explicit_path: Path | str | None = None,
    cwd: Path | None = None,
) -> Path | None:
    """Locate Hexaqueue configuration file by explicit path or ascending tree discovery.

    Args:
        explicit_path: Optional direct file path to verify and use.
        cwd: Directory to begin ascending search from (defaults to Path.cwd()).

    Returns:
        Path to discovered configuration file or None.
    """
    if explicit_path is not None:
        p = Path(explicit_path).resolve()
        return p if p.is_file() else None

    root = (cwd or Path.cwd()).resolve()
    candidates = [root, *root.parents]

    for d in candidates:
        for yaml_name in (
            "hexaqueue.yaml",
            "hexaqueue.yml",
            ".hexaqueue.yaml",
            ".hexaqueue.yml",
        ):
            target = d / yaml_name
            if target.is_file():
                return target

        pyproject = d / "pyproject.toml"
        if pyproject.is_file():
            with contextlib.suppress(Exception):
                raw = pyproject.read_text(encoding="utf-8")
                if "[tool.hexaqueue]" in raw:
                    return pyproject

    return None


def load_project_config(
    explicit_path: Path | str | None = None,
    cwd: Path | None = None,
) -> HexaqueueProjectConfig:
    """Load and validate HexaqueueProjectConfig from configuration file or defaults.

    Args:
        explicit_path: Optional explicit configuration path.
        cwd: Directory to start file discovery from.

    Returns:
        HexaqueueProjectConfig instance populated from file or built-in defaults.
    """
    path = discover_config_file(explicit_path=explicit_path, cwd=cwd)
    if path is None:
        return HexaqueueProjectConfig()

    raw_data: dict[str, Any] = {}
    if path.suffix.lower() == ".toml":
        raw_data = _parse_toml_config(path)
    elif path.suffix.lower() in (".yaml", ".yml"):
        raw_data = _parse_yaml_config(path)

    # Normalize profile sub-dicts into HexaqueueProfileConfig if present
    profiles_raw = raw_data.get("profiles", {})
    profiles: dict[str, HexaqueueProfileConfig] = {}
    for prof_name, prof_dict in profiles_raw.items():
        if isinstance(prof_dict, dict):
            with contextlib.suppress(Exception):
                profiles[prof_name] = HexaqueueProfileConfig.model_validate(prof_dict)

    base_args = {k: v for k, v in raw_data.items() if k != "profiles"}
    with contextlib.suppress(Exception):
        return HexaqueueProjectConfig.model_validate(
            {**base_args, "profiles": profiles}
        )

    return HexaqueueProjectConfig()


def _apply_profile(
    values: dict[str, Any], cfg: HexaqueueProjectConfig, target_profile: str | None
) -> None:
    """Overlay active profile configuration onto values dict."""
    if not (target_profile and target_profile in cfg.profiles):
        return
    prof_data = cfg.profiles[target_profile]
    fields = (
        "server_url",
        "slices",
        "slicer",
        "pool",
        "mode",
        "free_tier",
        "fallback",
        "api_token",
    )
    for f in fields:
        val = getattr(prof_data, f)
        if val is not None:
            values[f] = val
    if prof_data.container:
        values["container"] = prof_data.container.model_copy()


def _apply_env_overrides(values: dict[str, Any], env: dict[str, str]) -> None:
    """Overlay environment variables onto values dict."""
    if "HEXAQUEUE_SERVER_URL" in env:
        values["server_url"] = env["HEXAQUEUE_SERVER_URL"]
    if "HEXAQUEUE_API_TOKEN" in env:
        values["api_token"] = env["HEXAQUEUE_API_TOKEN"]
    if "HEXAQUEUE_SLICES" in env:
        with contextlib.suppress(ValueError):
            values["slices"] = int(env["HEXAQUEUE_SLICES"])
    if "HEXAQUEUE_SLICER" in env:
        values["slicer"] = env["HEXAQUEUE_SLICER"]
    if "HEXAQUEUE_POOL" in env:
        values["pool"] = env["HEXAQUEUE_POOL"]
    if "HEXAQUEUE_MODE" in env:
        values["mode"] = env["HEXAQUEUE_MODE"]
    if "HEXAQUEUE_FALLBACK" in env:
        values["fallback"] = parse_bool(env["HEXAQUEUE_FALLBACK"], default=True)

    paid_env = env.get("HEXAQUEUE_PAID")
    free_env = env.get("HEXAQUEUE_FREE_TIER", env.get("HEXAQUEUE_FREE"))
    cost_override = resolve_cost_preference(
        paid=paid_env, free_tier=free_env, source="environment variables"
    )
    if cost_override is not None:
        values["free_tier"] = cost_override

    if "HEXAQUEUE_WORKER_IMAGE" in env:
        values["container"] = HexaqueueContainerConfig(
            image=env["HEXAQUEUE_WORKER_IMAGE"],
            runtime=values["container"].runtime,
        )


def _apply_cli_overrides(values: dict[str, Any], overrides: dict[str, Any]) -> None:
    """Overlay explicit CLI option overrides onto values dict."""
    for str_key in ("server_url", "api_token", "slicer", "pool", "mode"):
        if str_key in overrides:
            values[str_key] = overrides[str_key]
    if "slices" in overrides:
        values["slices"] = int(overrides["slices"])
    if "fallback" in overrides:
        values["fallback"] = parse_bool(overrides["fallback"], default=True)

    cost_override = resolve_cost_preference(
        paid=overrides.get("paid"),
        free_tier=overrides.get("free_tier"),
        source="CLI options",
    )
    if cost_override is not None:
        values["free_tier"] = cost_override

    if "container" in overrides and parse_bool(overrides["container"]):
        values["mode"] = "container"
    if "worker_image" in overrides:
        values["container"] = HexaqueueContainerConfig(
            image=overrides["worker_image"],
            runtime=values["container"].runtime,
        )


def resolve_runner_config(
    project_config: HexaqueueProjectConfig | None = None,
    profile: str | None = None,
    env: dict[str, str] | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> HexaqueueProfileConfig:
    """Resolve layered runner configuration across defaults, file, profile, env, and CLI.

    Args:
        project_config: Base HexaqueueProjectConfig loaded from disk.
        profile: Active profile name to overlay (e.g., 'ci', 'container', 'free-tier').
        env: Environment variable dictionary (defaults to os.environ).
        cli_overrides: Explicit non-None CLI option overrides.

    Returns:
        Fully resolved HexaqueueProfileConfig.

    Notes/Architectural Intent:
        Follows Twelve-Factor and ADR-001/ADR-003 principles: clean separation between
        static config files, active environment profiles, and dynamic invocation overrides.
        Guarantees zero-spend by default (free_tier=True) to prevent accidental cloud budget spend.
    """
    cfg = project_config or HexaqueueProjectConfig()
    active_env = env if env is not None else dict(os.environ)
    overrides = {k: v for k, v in (cli_overrides or {}).items() if v is not None}

    # 1. Start with base project config
    values: dict[str, Any] = {
        "api_token": cfg.api_token,
        "container": cfg.container.model_copy(),
        "fallback": cfg.fallback,
        "free_tier": cfg.free_tier,
        "mode": cfg.mode,
        "pool": cfg.pool,
        "server_url": cfg.server_url,
        "slicer": cfg.slicer,
        "slices": cfg.slices,
    }

    # 2. Overlay active profile if matched
    target_profile = profile or active_env.get("HEXAQUEUE_PROFILE")
    _apply_profile(values, cfg, target_profile)

    # 3. Overlay environment variables
    _apply_env_overrides(values, active_env)

    # 4. Overlay CLI overrides
    _apply_cli_overrides(values, overrides)

    return HexaqueueProfileConfig.model_validate(values)


__all__ = [
    "discover_config_file",
    "HexaqueueContainerConfig",
    "HexaqueueProfileConfig",
    "HexaqueueProjectConfig",
    "load_project_config",
    "parse_bool",
    "resolve_cost_preference",
    "resolve_runner_config",
]
