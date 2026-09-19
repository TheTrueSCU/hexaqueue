"""ClamAV daemon malware inspection adapter.

Notes/Architectural Intent:
    Implements MalwareScannerEnginePort by communicating directly with the ClamAV
    daemon (clamd) over a local UNIX domain socket or TCP connection using the
    standard zINSTREAM binary protocol. Avoids third-party C library bindings and
    operates entirely via native asyncio streams.
"""

import asyncio
import struct
from pathlib import Path

from hexaqueue_core.ports.security import SecurityScanResult
from hexaqueue_scanner.domain.config import ClamAvConfig
from hexaqueue_scanner.ports.engine import MalwareScannerEnginePort


class ClamAvDaemonAdapter(MalwareScannerEnginePort):
    """ClamAV daemon socket adapter implementing MalwareScannerEnginePort.

    Args:
        config: ClamAvConfig detailing socket path or TCP host/port and chunk sizes.
    """

    def __init__(self, config: ClamAvConfig | None = None) -> None:
        self._config = config or ClamAvConfig()

    async def _open_connection(
        self,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Establish stream connection to clamd via UNIX socket or TCP."""
        if self._config.socket_path is not None:
            return await asyncio.wait_for(
                asyncio.open_unix_connection(self._config.socket_path),
                timeout=self._config.timeout_seconds,
            )
        if self._config.host is not None:
            port = self._config.port or 3310
            return await asyncio.wait_for(
                asyncio.open_connection(self._config.host, port),
                timeout=self._config.timeout_seconds,
            )
        msg = "No valid ClamAV connection target specified in configuration"
        raise ValueError(msg)

    async def ping(self) -> bool:
        """Ping clamd daemon to verify health and availability.

        Returns:
            True if clamd responded with PONG within timeout, False otherwise.
        """
        try:
            reader, writer = await self._open_connection()
            try:
                writer.write(b"zPING\x00")
                await writer.drain()
                resp = await asyncio.wait_for(
                    reader.readuntil(b"\x00"),
                    timeout=self._config.timeout_seconds,
                )
                return b"PONG" in resp
            finally:
                writer.close()
                await writer.wait_closed()
        except Exception:
            return False

    async def scan_file(self, file_path: Path) -> SecurityScanResult:
        """Stream file contents to clamd via zINSTREAM and parse verdict.

        Args:
            file_path: Local filesystem Path of the file to inspect.

        Returns:
            SecurityScanResult summarizing ClamAV scan findings.
        """
        engine_name = "ClamAV-daemon"
        if not file_path.is_file():
            return SecurityScanResult(
                is_clean=False,
                scanner_engine=engine_name,
                threat_name=f"FileNotFoundError: {file_path}",
            )

        try:
            reader, writer = await self._open_connection()
        except Exception as e:
            return SecurityScanResult(
                is_clean=False,
                scanner_engine=engine_name,
                threat_name=f"DaemonConnectionError: {e}",
            )

        try:
            writer.write(b"zINSTREAM\x00")
            await writer.drain()

            total_streamed = 0
            with file_path.open("rb") as f:
                while True:
                    chunk = f.read(self._config.chunk_size_bytes)
                    if not chunk:
                        break
                    total_streamed += len(chunk)
                    if total_streamed > self._config.max_stream_bytes:
                        writer.write(b"\x00\x00\x00\x00")
                        await writer.drain()
                        return SecurityScanResult(
                            is_clean=False,
                            scanner_engine=engine_name,
                            threat_name=f"StreamSizeExceeded: > {self._config.max_stream_bytes} bytes",
                        )

                    header = struct.pack(">I", len(chunk))
                    writer.write(header + chunk)
                    await writer.drain()

            # End of stream chunk marker (length 0)
            writer.write(b"\x00\x00\x00\x00")
            await writer.drain()

            raw_resp = await asyncio.wait_for(
                reader.readuntil(b"\x00"),
                timeout=self._config.timeout_seconds,
            )
            response_text = (
                raw_resp.decode("utf-8", errors="replace").strip().rstrip("\x00")
            )

            if "stream: OK" in response_text:
                return SecurityScanResult(
                    is_clean=True,
                    scanner_engine=engine_name,
                    threat_name=None,
                )

            if "FOUND" in response_text:
                parts = response_text.split(":")
                threat = (
                    parts[1].replace("FOUND", "").strip()
                    if len(parts) > 1
                    else "UnknownVirus"
                )
                return SecurityScanResult(
                    is_clean=False,
                    scanner_engine=engine_name,
                    threat_name=threat,
                )

            return SecurityScanResult(
                is_clean=False,
                scanner_engine=engine_name,
                threat_name=f"ScanProtocolError: {response_text}",
            )
        except Exception as e:
            return SecurityScanResult(
                is_clean=False,
                scanner_engine=engine_name,
                threat_name=f"ScanExecutionError: {e}",
            )
        finally:
            writer.close()
            await writer.wait_closed()


__all__ = [
    "ClamAvDaemonAdapter",
]
