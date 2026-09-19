"""Malware scanning engine port interface.

Notes/Architectural Intent:
    Defines abstract contract for individual software-managed antivirus and
    rule evaluation engines (e.g. ClamAV daemon, YARA rule compiler).
"""

from abc import ABC, abstractmethod
from pathlib import Path

from hexaqueue_core.ports.security import SecurityScanResult


class MalwareScannerEnginePort(ABC):
    """Abstract port interface for individual malware scanning engines."""

    @abstractmethod
    async def scan_file(self, file_path: Path) -> SecurityScanResult:
        """Inspect a file on disk for malicious signatures or rule matches.

        Args:
            file_path: Local filesystem Path of the file to inspect.

        Returns:
            SecurityScanResult containing cleanliness status, scanner engine, and threat name.
        """

    @abstractmethod
    async def ping(self) -> bool:
        """Verify scanner engine responsiveness and daemon health.

        Returns:
            True if engine is healthy and accepting scan requests, False otherwise.
        """


__all__ = [
    "MalwareScannerEnginePort",
]
