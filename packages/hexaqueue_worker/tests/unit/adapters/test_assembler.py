"""Unit tests for CliContainerImageAssemblerAdapter (Issue #101)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_worker.adapters.assembler import CliContainerImageAssemblerAdapter
from hexaqueue_worker.domain.assembler import (
    ImageArtifactMapping,
    ImageAssemblySpec,
)


def test_generate_containerfile_linux(tmp_path: Path) -> None:
    """Verify Containerfile rendering with Linux directives and chmod permissions."""
    adapter = CliContainerImageAssemblerAdapter()
    dummy_file = tmp_path / "test_bin"
    dummy_file.write_text("echo binary", encoding="utf-8")

    spec = ImageAssemblySpec(
        base_image="alpine:3.20",
        artifacts=[
            ImageArtifactMapping(
                source_path=str(dummy_file),
                target_path="/usr/local/bin/test_bin",
                executable=True,
            )
        ],
        install_commands=["apk update", "apk add curl"],
        env={"APP_ENV": "production"},
        workdir="/workspace",
    )

    ctx_dir = tmp_path / "build_ctx"
    content = adapter.generate_containerfile(spec, ctx_dir)

    has_from = "FROM alpine:3.20" in content
    assert has_from is True
    has_wd = "WORKDIR /workspace" in content
    assert has_wd is True
    has_env = 'ENV APP_ENV="production"' in content
    assert has_env is True
    has_copy = "COPY artifacts/0_test_bin /usr/local/bin/test_bin" in content
    assert has_copy is True
    has_chmod = "RUN chmod +x /usr/local/bin/test_bin" in content
    assert has_chmod is True
    has_cmd = "RUN apk add curl" in content
    assert has_cmd is True


def test_generate_containerfile_windows(tmp_path: Path) -> None:
    """Verify Containerfile rendering for Windows containers omits chmod."""
    adapter = CliContainerImageAssemblerAdapter()
    dummy_file = tmp_path / "tool.exe"
    dummy_file.write_text("binary", encoding="utf-8")

    spec = ImageAssemblySpec(
        base_image="mcr.microsoft.com/windows/servercore:ltsc2022",
        artifacts=[
            ImageArtifactMapping(
                source_path=str(dummy_file),
                target_path="C:\\app\\tool.exe",
                executable=True,
            )
        ],
        workdir="C:\\workspace",
    )

    ctx_dir = tmp_path / "build_ctx"
    content = adapter.generate_containerfile(spec, ctx_dir)

    has_from = "FROM mcr.microsoft.com/windows/servercore:ltsc2022" in content
    assert has_from is True
    has_copy = "COPY artifacts/0_tool.exe C:\\app\\tool.exe" in content
    assert has_copy is True
    assert "chmod" not in content


@pytest.mark.asyncio
async def test_has_image_inspect() -> None:
    """Verify has_image executes inspect and evaluates returncode."""
    adapter = CliContainerImageAssemblerAdapter()

    # Success case
    mock_proc_ok = MagicMock()
    mock_proc_ok.returncode = 0
    mock_proc_ok.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_ok):
        exists_true = await adapter.has_image("alpine:latest")
        assert exists_true is True

    # Missing case
    mock_proc_err = MagicMock()
    mock_proc_err.returncode = 1
    mock_proc_err.wait = AsyncMock(return_value=1)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_err):
        exists_false = await adapter.has_image("nonexistent:tag")
        assert exists_false is False


@pytest.mark.asyncio
async def test_remove_cached_image() -> None:
    """Verify remove_cached_image invokes rmi -f."""
    adapter = CliContainerImageAssemblerAdapter()
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await adapter.remove_cached_image("hq-cached:test")

    exec_called = mock_exec.called
    assert exec_called is True
    args = mock_exec.call_args[0]
    assert "rmi" in args
    assert "-f" in args
    assert "hq-cached:test" in args


@pytest.mark.asyncio
async def test_assemble_image_cache_hit() -> None:
    """Verify assemble_image serves existing image immediately from cache."""
    adapter = CliContainerImageAssemblerAdapter()
    spec = ImageAssemblySpec(base_image="alpine:latest")

    with patch.object(adapter, "has_image", return_value=True):
        res = await adapter.assemble_image(spec)

    cached = res.cached
    assert cached is True
    assert res.image_tag == spec.image_tag


@pytest.mark.asyncio
async def test_assemble_image_cache_miss_build_success() -> None:
    """Verify assemble_image builds image on cache miss."""
    adapter = CliContainerImageAssemblerAdapter()
    spec = ImageAssemblySpec(
        base_image="alpine:latest",
        install_commands=["apk update"],
    )

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(
        return_value=(b"Step 1/2 : FROM alpine\nSuccessfully built", b"")
    )
    mock_proc.returncode = 0

    with (
        patch.object(adapter, "has_image", return_value=False),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        res = await adapter.assemble_image(spec)

    cached = res.cached
    assert cached is False
    assert res.image_tag == spec.image_tag
    log_out = res.log_output
    assert "Successfully built" in str(log_out)


@pytest.mark.asyncio
async def test_assemble_image_build_failure() -> None:
    """Verify non-zero build exit code raises HexaqueueError."""
    adapter = CliContainerImageAssemblerAdapter()
    spec = ImageAssemblySpec(base_image="alpine:latest")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(
        return_value=(b"", b"Error: failed to fetch base image")
    )
    mock_proc.returncode = 1

    with (
        patch.object(adapter, "has_image", return_value=False),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        pytest.raises(HexaqueueError, match="Container image assembly failed"),
    ):
        await adapter.assemble_image(spec)


@pytest.mark.asyncio
async def test_assemble_image_timeout() -> None:
    """Verify build timeout raises HexaqueueError."""
    adapter = CliContainerImageAssemblerAdapter(timeout_seconds=1)
    spec = ImageAssemblySpec(base_image="alpine:latest")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=TimeoutError())

    with (
        patch.object(adapter, "has_image", return_value=False),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        pytest.raises(HexaqueueError, match="assembly timed out"),
    ):
        await adapter.assemble_image(spec)
