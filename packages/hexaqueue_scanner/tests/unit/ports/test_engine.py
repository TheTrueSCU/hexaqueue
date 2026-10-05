"""Unit tests for MalwareScannerEnginePort interface contract."""

from pathlib import Path

import pytest

from hexaqueue_core.ports.security import SecurityScanResult
from hexaqueue_scanner.ports.engine import MalwareScannerEnginePort


class DummyEngine(MalwareScannerEnginePort):
    """Concrete test implementation of MalwareScannerEnginePort."""

    def __init__(self, is_clean: bool = True, healthy: bool = True) -> None:
        self._is_clean = is_clean
        self._healthy = healthy

    async def scan_file(self, file_path: Path) -> SecurityScanResult:
        """Return dummy scan result."""
        return SecurityScanResult(
            is_clean=self._is_clean,
            threat_name=None if self._is_clean else "DummyThreat",
            scanner_engine="DummyEngine-v1",
        )

    async def ping(self) -> bool:
        """Return dummy health status."""
        return self._healthy


@pytest.mark.asyncio
async def test_dummy_engine_contract(tmp_path: Path) -> None:
    """Verify concrete engine contract fulfilling MalwareScannerEnginePort."""
    test_file = tmp_path / "sample.bin"
    test_file.write_bytes(b"sample content")

    clean_engine = DummyEngine(is_clean=True, healthy=True)
    res = await clean_engine.scan_file(test_file)
    clean = res.is_clean
    assert clean is True
    engine = res.scanner_engine
    assert engine == "DummyEngine-v1"
    threat = res.threat_name
    assert threat is None
    ping = await clean_engine.ping()
    assert ping is True

    dirty_engine = DummyEngine(is_clean=False, healthy=False)
    res_bad = await dirty_engine.scan_file(test_file)
    bad_clean = res_bad.is_clean
    assert bad_clean is False
    bad_threat = res_bad.threat_name
    assert bad_threat == "DummyThreat"
    bad_ping = await dirty_engine.ping()
    assert bad_ping is False
