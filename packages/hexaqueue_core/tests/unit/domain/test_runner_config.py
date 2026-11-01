"""Unit tests for Hexaqueue runner configuration loader and layered resolution."""

import tempfile
from pathlib import Path

from hexaqueue_core.domain.runner_config import (
    HexaqueueContainerConfig,
    HexaqueueProfileConfig,
    HexaqueueProjectConfig,
    discover_config_file,
    load_project_config,
    resolve_runner_config,
)


def test_default_project_config() -> None:
    """Verify built-in defaults for HexaqueueProjectConfig."""
    cfg = HexaqueueProjectConfig()
    assert cfg.server_url == "http://127.0.0.1:8000"
    assert cfg.slices == 4
    assert cfg.slicer == "round-robin"
    assert cfg.fallback is True
    assert cfg.free_tier is False
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
