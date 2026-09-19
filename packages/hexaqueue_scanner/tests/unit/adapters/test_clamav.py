"""Unit tests for ClamAvDaemonAdapter socket client."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hexaqueue_scanner.adapters.clamav import ClamAvDaemonAdapter
from hexaqueue_scanner.domain.config import ClamAvConfig


def _create_mock_streams(response_bytes: bytes) -> tuple[AsyncMock, MagicMock]:
    """Helper to create mock reader/writer streams."""
    mock_reader = AsyncMock()
    mock_reader.readuntil = AsyncMock(return_value=response_bytes)

    mock_writer = MagicMock()
    mock_writer.write = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    return mock_reader, mock_writer


@pytest.mark.asyncio
async def test_clamav_ping_success() -> None:
    """Verify ping returns True when clamd responds with PONG."""
    reader, writer = _create_mock_streams(b"PONG\x00")
    adapter = ClamAvDaemonAdapter()

    with patch("asyncio.open_unix_connection", return_value=(reader, writer)):
        healthy = await adapter.ping()

    assert healthy is True
    writer.write.assert_called_with(b"zPING\x00")


@pytest.mark.asyncio
async def test_clamav_ping_failure() -> None:
    """Verify ping returns False when connection raises an exception."""
    adapter = ClamAvDaemonAdapter()

    with patch(
        "asyncio.open_unix_connection", side_effect=ConnectionRefusedError("No daemon")
    ):
        healthy = await adapter.ping()

    assert healthy is False


@pytest.mark.asyncio
async def test_clamav_scan_file_clean(tmp_path: Path) -> None:
    """Verify clean file scan maps to is_clean=True and threat_name=None."""
    test_file = tmp_path / "clean.txt"
    test_file.write_text("Clean hello world data")

    reader, writer = _create_mock_streams(b"stream: OK\x00")
    adapter = ClamAvDaemonAdapter()

    with patch("asyncio.open_unix_connection", return_value=(reader, writer)):
        res = await adapter.scan_file(test_file)

    clean = res.is_clean
    assert clean is True
    engine = res.scanner_engine
    assert engine == "ClamAV-daemon"
    threat = res.threat_name
    assert threat is None


@pytest.mark.asyncio
async def test_clamav_scan_file_infected(tmp_path: Path) -> None:
    """Verify infected scan extracts threat name."""
    test_file = tmp_path / "eicar.com"
    test_file.write_bytes(b"bad-signature")

    reader, writer = _create_mock_streams(b"stream: Win.Trojan.Generic-12345 FOUND\x00")
    adapter = ClamAvDaemonAdapter()

    with patch("asyncio.open_unix_connection", return_value=(reader, writer)):
        res = await adapter.scan_file(test_file)

    clean = res.is_clean
    assert clean is False
    threat = res.threat_name
    assert threat == "Win.Trojan.Generic-12345"


@pytest.mark.asyncio
async def test_clamav_scan_missing_file() -> None:
    """Verify scanning non-existent file returns error result."""
    adapter = ClamAvDaemonAdapter()
    missing_path = Path("/tmp/non-existent-test-file-999.xyz")

    res = await adapter.scan_file(missing_path)
    clean = res.is_clean
    assert clean is False
    has_not_found = "FileNotFoundError" in (res.threat_name or "")
    assert has_not_found is True


@pytest.mark.asyncio
async def test_clamav_scan_connection_error(tmp_path: Path) -> None:
    """Verify socket connection failure reports DaemonConnectionError."""
    test_file = tmp_path / "data.bin"
    test_file.write_bytes(b"test")

    adapter = ClamAvDaemonAdapter()

    with patch(
        "asyncio.open_unix_connection",
        side_effect=FileNotFoundError("Socket not found"),
    ):
        res = await adapter.scan_file(test_file)

    clean = res.is_clean
    assert clean is False
    has_conn_err = "DaemonConnectionError" in (res.threat_name or "")
    assert has_conn_err is True


@pytest.mark.asyncio
async def test_clamav_scan_stream_size_exceeded(tmp_path: Path) -> None:
    """Verify stream size ceiling aborts transmission."""
    test_file = tmp_path / "large.bin"
    test_file.write_bytes(b"X" * 5000)

    cfg = ClamAvConfig(chunk_size_bytes=1024, max_stream_bytes=2048)
    reader, writer = _create_mock_streams(b"")
    adapter = ClamAvDaemonAdapter(config=cfg)

    with patch("asyncio.open_unix_connection", return_value=(reader, writer)):
        res = await adapter.scan_file(test_file)

    clean = res.is_clean
    assert clean is False
    has_exceeded = "StreamSizeExceeded" in (res.threat_name or "")
    assert has_exceeded is True


@pytest.mark.asyncio
async def test_clamav_scan_tcp_connection(tmp_path: Path) -> None:
    """Verify TCP socket connection branch."""
    test_file = tmp_path / "tcp.txt"
    test_file.write_text("tcp test")

    cfg = ClamAvConfig(socket_path=None, host="127.0.0.1", port=3310)
    reader, writer = _create_mock_streams(b"stream: OK\x00")
    adapter = ClamAvDaemonAdapter(config=cfg)

    with patch("asyncio.open_connection", return_value=(reader, writer)) as mock_tcp:
        res = await adapter.scan_file(test_file)

    tcp_called = mock_tcp.called
    assert tcp_called is True
    clean = res.is_clean
    assert clean is True


@pytest.mark.asyncio
async def test_clamav_scan_protocol_error(tmp_path: Path) -> None:
    """Verify unexpected daemon output reports ScanProtocolError."""
    test_file = tmp_path / "weird.txt"
    test_file.write_text("content")

    reader, writer = _create_mock_streams(b"stream: UNKNOWN_GARBAGE_ERROR\x00")
    adapter = ClamAvDaemonAdapter()

    with patch("asyncio.open_unix_connection", return_value=(reader, writer)):
        res = await adapter.scan_file(test_file)

    clean = res.is_clean
    assert clean is False
    has_proto = "ScanProtocolError" in (res.threat_name or "")
    assert has_proto is True


@pytest.mark.asyncio
async def test_clamav_open_connection_invalid_config(tmp_path: Path) -> None:
    """Verify open connection raises ValueError when no endpoint is configured."""
    test_file = tmp_path / "file.bin"
    test_file.write_bytes(b"data")

    adapter = ClamAvDaemonAdapter()
    # Force both endpoints to None via object dictionary
    object.__setattr__(adapter._config, "socket_path", None)
    object.__setattr__(adapter._config, "host", None)

    res = await adapter.scan_file(test_file)
    clean = res.is_clean
    assert clean is False
    has_daemon_err = "DaemonConnectionError" in (res.threat_name or "")
    assert has_daemon_err is True
