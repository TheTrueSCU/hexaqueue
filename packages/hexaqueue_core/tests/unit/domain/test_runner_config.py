"""Unit tests for Hexaqueue runner configuration loader and layered resolution."""

import tempfile
from pathlib import Path

from hexaqueue_core.domain.runner_config import (
    HexaqueueContainerConfig,
    HexaqueueProfileConfig,
    HexaqueueProjectConfig,
    discover_config_file,
    load_project_config,
    parse_bool,
    resolve_cost_preference,
    resolve_runner_config,
)


def test_default_project_config() -> None:
    """Verify built-in defaults for HexaqueueProjectConfig."""
    cfg = HexaqueueProjectConfig()
    assert cfg.server_url == "http://127.0.0.1:8000"
    assert cfg.slices == 4
    assert cfg.slicer == "round-robin"
    assert cfg.fallback is True
    assert cfg.free_tier is True
    assert cfg.mode == "subprocess"
    assert cfg.container.image == "hexaqueue-worker:latest"
    assert cfg.profiles == {}


def test_discover_config_file_explicit_and_missing() -> None:
    """Verify discovery with explicit paths and missing files."""
    with tempfile.NamedTemporaryFile(suffix=".yaml") as tmp:
        found = discover_config_file(explicit_path=tmp.name)
        assert found == Path(tmp.name).resolve()

    found_none = discover_config_file(explicit_path="/nonexistent/path/hexaqueue.yaml")
    assert found_none is None


def test_parse_toml_pyproject_config() -> None:
    """Verify loading [tool.hexaqueue] section from pyproject.toml."""
    toml_content = """
[tool.hexaqueue]
server_url = "http://10.0.0.5:8000"
slices = 8
mode = "container"
fallback = false

[tool.hexaqueue.container]
image = "my-custom-worker:v2"

[tool.hexaqueue.profiles.ci]
slices = 16
server_url = "https://ci-cluster.corp"
fallback = false

[tool.hexaqueue.profiles.free-tier]
free_tier = true
slices = 2
pool = "arm64-free"
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pyproj = Path(tmpdir) / "pyproject.toml"
        pyproj.write_text(toml_content, encoding="utf-8")

        cfg = load_project_config(explicit_path=pyproj)
        assert cfg.server_url == "http://10.0.0.5:8000"
        assert cfg.slices == 8
        assert cfg.mode == "container"
        assert cfg.fallback is False
        assert cfg.container.image == "my-custom-worker:v2"

        assert "ci" in cfg.profiles
        ci_prof = cfg.profiles["ci"]
        assert ci_prof.slices == 16
        assert ci_prof.server_url == "https://ci-cluster.corp"
        assert ci_prof.fallback is False

        assert "free-tier" in cfg.profiles
        free_prof = cfg.profiles["free-tier"]
        assert free_prof.free_tier is True
        assert free_prof.slices == 2
        assert free_prof.pool == "arm64-free"


def test_parse_yaml_config_file() -> None:
    """Verify loading configuration from a standalone hexaqueue.yaml file."""
    yaml_content = """
server_url: "http://192.168.1.100:8000"
slices: 6
slicer: "file"
free_tier: true

profiles:
  container:
    mode: "container"
    slices: 4
    container:
      image: "worker-img:1.0"
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_file = Path(tmpdir) / "hexaqueue.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        cfg = load_project_config(explicit_path=yaml_file)
        assert cfg.server_url == "http://192.168.1.100:8000"
        assert cfg.slices == 6
        assert cfg.slicer == "file"
        assert cfg.free_tier is True
        assert "container" in cfg.profiles
        assert cfg.profiles["container"].mode == "container"
        assert cfg.profiles["container"].container.image == "worker-img:1.0"


def test_resolve_runner_config_layers() -> None:
    """Verify four-tier precedence: default -> profile -> env -> CLI overrides."""
    base_cfg = HexaqueueProjectConfig(
        server_url="http://base:8000",
        slices=2,
        mode="subprocess",
        profiles={
            "ci": HexaqueueProfileConfig(
                server_url="http://ci:8000",
                slices=8,
                mode="container",
                container=HexaqueueContainerConfig(image="ci-worker:latest"),
            ),
        },
    )

    # 1. Base resolution
    res_base = resolve_runner_config(project_config=base_cfg, env={})
    assert res_base.server_url == "http://base:8000"
    assert res_base.slices == 2
    assert res_base.mode == "subprocess"

    # 2. Profile overlay
    res_prof = resolve_runner_config(project_config=base_cfg, profile="ci", env={})
    assert res_prof.server_url == "http://ci:8000"
    assert res_prof.slices == 8
    assert res_prof.mode == "container"
    assert res_prof.container.image == "ci-worker:latest"

    # 3. Environment overlay overrides profile
    env_overlay = {
        "HEXAQUEUE_SLICES": "12",
        "HEXAQUEUE_API_TOKEN": "secret-env-token",
        "HEXAQUEUE_WORKER_IMAGE": "override-image:v3",
    }
    res_env = resolve_runner_config(
        project_config=base_cfg, profile="ci", env=env_overlay
    )
    assert res_env.slices == 12
    assert res_env.api_token == "secret-env-token"
    assert res_env.container.image == "override-image:v3"

    # 4. CLI overrides override everything
    cli_overrides = {
        "slices": 16,
        "container": True,
        "worker_image": "cli-image:v4",
    }
    res_cli = resolve_runner_config(
        project_config=base_cfg,
        profile="ci",
        env=env_overlay,
        cli_overrides=cli_overrides,
    )
    assert res_cli.slices == 16
    assert res_cli.mode == "container"
    assert res_cli.container.image == "cli-image:v4"


def test_named_profile_falls_back_to_project_defaults() -> None:
    """Verify named profile inherits unspecified fields from [tool.hexaqueue] base defaults."""
    base_cfg = HexaqueueProjectConfig(
        server_url="http://custom-cluster:9999",
        slices=14,
        fallback=False,
        profiles={
            "minimal": HexaqueueProfileConfig.model_validate({"mode": "container"}),
        },
    )
    resolved = resolve_runner_config(project_config=base_cfg, profile="minimal", env={})
    is_server = resolved.server_url == "http://custom-cluster:9999"
    is_slices = resolved.slices == 14
    is_fallback = resolved.fallback is False
    is_mode = resolved.mode == "container"
    assert is_server is True
    assert is_slices is True
    assert is_fallback is True
    assert is_mode is True


def test_parse_bool() -> None:
    """Verify boolean parsing handles truthy, falsy, None, and fallbacks."""
    for truthy in ("1", "true", "True", "YES", "yes", "on", "ON", True):
        assert parse_bool(truthy) is True

    for falsy in ("0", "false", "FALSE", "no", "NO", "off", "OFF", False):
        assert parse_bool(falsy) is False

    assert parse_bool(None, default=True) is True
    assert parse_bool(None, default=False) is False
    assert parse_bool("unknown-value", default=True) is True


def test_resolve_cost_preference_clean() -> None:
    """Verify resolve_cost_preference for non-conflicting states."""
    assert resolve_cost_preference(paid=None, free_tier=None) is None
    assert resolve_cost_preference(paid=True, free_tier=None) is False
    assert resolve_cost_preference(paid=None, free_tier=True) is True
    assert resolve_cost_preference(paid=False, free_tier=None) is True
    assert resolve_cost_preference(paid=None, free_tier=False) is False


def test_resolve_cost_preference_conflict_defaults_to_free() -> None:
    """Verify conflict between paid and free triggers warning and defaults to free tier."""
    import pytest

    with pytest.warns(UserWarning, match="both paid and free tier requested"):
        res = resolve_cost_preference(
            paid=True, free_tier=True, source="test environment"
        )
        assert res is True


def test_resolve_runner_config_cost_env_and_cli() -> None:
    """Verify cost preference resolution across env variables and CLI overrides."""
    import pytest

    base = HexaqueueProjectConfig()
    assert base.free_tier is True

    # 1. Authorize paid via env
    res_paid_env = resolve_runner_config(
        project_config=base, env={"HEXAQUEUE_PAID": "1"}
    )
    assert res_paid_env.free_tier is False

    # 2. Conflict in env triggers warning and defaults to free
    with pytest.warns(UserWarning, match="both paid and free tier requested"):
        res_conflict_env = resolve_runner_config(
            project_config=base,
            env={"HEXAQUEUE_PAID": "1", "HEXAQUEUE_FREE_TIER": "1"},
        )
        assert res_conflict_env.free_tier is True

    # 3. CLI override unlocks paid
    res_cli_paid = resolve_runner_config(
        project_config=base,
        env={"HEXAQUEUE_FREE_TIER": "1"},
        cli_overrides={"paid": True},
    )
    assert res_cli_paid.free_tier is False

    # 4. CLI conflict triggers warning and defaults to free
    with pytest.warns(UserWarning, match="both paid and free tier requested"):
        res_cli_conflict = resolve_runner_config(
            project_config=base,
            cli_overrides={"paid": True, "free_tier": True},
        )
        assert res_cli_conflict.free_tier is True


def test_resolve_runner_config_local_and_remote_slices() -> None:
    """Verify local_slices and remote_slices resolve across profile, env, and CLI."""
    profile_cfg = HexaqueueProfileConfig(
        local_slices=2,
        remote_slices="auto",
    )
    base = HexaqueueProjectConfig(
        profiles={"ci": profile_cfg},
    )

    # 1. Profile resolution
    resolved_profile = resolve_runner_config(project_config=base, profile="ci")
    assert resolved_profile.local_slices == 2
    assert resolved_profile.remote_slices == "auto"

    # 2. Env override
    resolved_env = resolve_runner_config(
        project_config=base,
        profile="ci",
        env={"HEXAQUEUE_LOCAL_SLICES": "4", "HEXAQUEUE_REMOTE_SLICES": "16"},
    )
    assert resolved_env.local_slices == "4"
    assert resolved_env.remote_slices == "16"

    # 3. CLI override takes highest precedence
    resolved_cli = resolve_runner_config(
        project_config=base,
        profile="ci",
        cli_overrides={"local_slices": 0, "remote_slices": 8},
    )
    assert resolved_cli.local_slices == 0
    assert resolved_cli.remote_slices == 8


def test_resolve_runner_config_cluster_ssh_options() -> None:
    """Verify cluster host and SSH connection options resolve across profile, env, and CLI."""
    profile_cfg = HexaqueueProfileConfig(
        host="10.0.0.1",
        ssh_user="opc",
        ssh_key="/id_rsa",
        ssh_port=2222,
        remote_port=8080,
    )
    base = HexaqueueProjectConfig(
        profiles={"oci": profile_cfg},
    )

    # 1. Profile resolution
    resolved_profile = resolve_runner_config(project_config=base, profile="oci")
    assert resolved_profile.host == "10.0.0.1"
    assert resolved_profile.ssh_user == "opc"
    assert resolved_profile.ssh_key == "/id_rsa"
    assert resolved_profile.ssh_port == 2222
    assert resolved_profile.remote_port == 8080

    # 2. Env override (HEXAQUEUE_CLUSTER_HOST and HEXAQUEUE_SSH_*)
    resolved_env = resolve_runner_config(
        project_config=base,
        profile="oci",
        env={
            "HEXAQUEUE_CLUSTER_HOST": "129.146.115.79",
            "HEXAQUEUE_SSH_USER": "hexaqueue-ci",
            "HEXAQUEUE_SSH_KEY": "/root/.ssh/id",
            "HEXAQUEUE_SSH_PORT": "22",
            "HEXAQUEUE_REMOTE_PORT": "8000",
        },
    )
    assert resolved_env.host == "129.146.115.79"
    assert resolved_env.ssh_user == "hexaqueue-ci"
    assert resolved_env.ssh_key == "/root/.ssh/id"
    assert resolved_env.ssh_port == 22
    assert resolved_env.remote_port == 8000

    # 3. CLI overrides
    resolved_cli = resolve_runner_config(
        project_config=base,
        profile="oci",
        cli_overrides={
            "host": "custom.cluster.internal",
            "ssh_port": 2200,
        },
    )
    assert resolved_cli.host == "custom.cluster.internal"
    assert resolved_cli.ssh_port == 2200
