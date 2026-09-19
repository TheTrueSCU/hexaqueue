"""Unit tests for scanner domain configuration models."""

import pytest

from hexaqueue_scanner.domain.config import (
    ClamAvConfig,
    CloudDeferenceConfig,
    ScannerConfig,
    YaraRuleConfig,
)


def test_clamav_config_defaults() -> None:
    """Verify default ClamAV configuration settings."""
    cfg = ClamAvConfig()
    sock = cfg.socket_path
    assert sock == "/var/run/clamav/clamd.ctl"
    host = cfg.host
    assert host is None
    port = cfg.port
    assert port is None
    timeout = cfg.timeout_seconds
    assert timeout == 30.0
    chunk = cfg.chunk_size_bytes
    assert chunk == 262144
    max_bytes = cfg.max_stream_bytes
    assert max_bytes == 104857600


def test_clamav_config_tcp_mode() -> None:
    """Verify ClamAV TCP connection configuration."""
    cfg = ClamAvConfig(socket_path=None, host="127.0.0.1", port=3310)
    host = cfg.host
    assert host == "127.0.0.1"
    port = cfg.port
    assert port == 3310
    sock = cfg.socket_path
    assert sock is None


def test_clamav_config_missing_endpoint() -> None:
    """Verify validation error when neither socket nor host is configured."""
    with pytest.raises(
        ValueError, match="Either socket_path or host must be specified"
    ):
        ClamAvConfig(socket_path=None, host=None)


def test_yara_rule_config() -> None:
    """Verify YARA rule configuration and defaults."""
    cfg = YaraRuleConfig(
        rule_paths=["/etc/yara/malware.yar"],
        inline_rules=["rule test { condition: true }"],
        timeout_seconds=15.0,
    )
    paths = cfg.rule_paths
    assert paths == ["/etc/yara/malware.yar"]
    rules = cfg.inline_rules
    assert rules == ["rule test { condition: true }"]
    timeout = cfg.timeout_seconds
    assert timeout == 15.0


def test_cloud_deference_config() -> None:
    """Verify Provider-Native Deference configuration defaults."""
    cfg = CloudDeferenceConfig()
    aws_on = cfg.aws_guardduty_enabled
    assert aws_on is True
    aws_tag = cfg.aws_tag_key
    assert aws_tag == "GuardDutyMalwareScanStatus"
    clean_vals = cfg.aws_clean_tag_values
    assert "NO_THREATS_FOUND" in clean_vals
    threat_vals = cfg.aws_threat_tag_values
    assert "THREATS_FOUND" in threat_vals

    azure_on = cfg.azure_defender_enabled
    assert azure_on is True
    azure_tag = cfg.azure_tag_key
    assert azure_tag == "Malware Scanning scan result"
    az_clean = cfg.azure_clean_tag_values
    assert "No threats found" in az_clean
    az_threat = cfg.azure_threat_tag_values
    assert "Malware found" in az_threat


def test_scanner_aggregate_config() -> None:
    """Verify aggregate ScannerConfig wiring."""
    cfg = ScannerConfig(quarantine_on_threat=False)
    quarantine = cfg.quarantine_on_threat
    assert quarantine is False
    clam = cfg.clamav
    assert clam is not None
    yara = cfg.yara
    assert yara is not None
    cloud = cfg.cloud
    assert cloud is not None
