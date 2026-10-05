"""YARA rule evaluation malware and static signature adapter.

Notes/Architectural Intent:
    Implements MalwareScannerEnginePort using compiled YARA rule matching.
    Provides automated fallback to pure-Python heuristic pattern evaluation when
    the native C-based yara-python engine is not installed in the execution environment.
"""

import re
from pathlib import Path
from typing import Any

from hexaqueue_core.ports.security import SecurityScanResult
from hexaqueue_scanner.domain.config import YaraRuleConfig
from hexaqueue_scanner.ports.engine import MalwareScannerEnginePort

# Built-in heuristic signature database for pure-Python fallback evaluation
_BUILTIN_PATTERNS: list[tuple[str, bytes]] = [
    (
        "Standard.EICAR.TestFile",
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*",
    ),
    (
        "Exploit.ReverseShell.DevTcp",
        b"/dev/tcp/",
    ),
    (
        "Exploit.ReverseShell.NetcatExec",
        b"nc -e /bin/sh",
    ),
    (
        "Exploit.Webshell.PhpEvalBase64",
        b"eval(base64_decode(",
    ),
]


class YaraRuleScannerAdapter(MalwareScannerEnginePort):
    """YARA static signature rule evaluation adapter.

    Args:
        config: YaraRuleConfig detailing rule file paths and inline rule strings.
    """

    def __init__(self, config: YaraRuleConfig | None = None) -> None:
        self._config = config or YaraRuleConfig()
        self._compiled_yara_rules: Any | None = None
        self._initialize_rules()

    def _initialize_rules(self) -> None:
        """Attempt to compile rules with yara-python if available."""
        try:
            import importlib

            yara = importlib.import_module("yara")

            sources: dict[str, str] = {}
            for idx, inline in enumerate(self._config.inline_rules):
                sources[f"inline_{idx}"] = inline
            filepaths = {
                f"file_{idx}": path for idx, path in enumerate(self._config.rule_paths)
            }
            if sources or filepaths:
                self._compiled_yara_rules = yara.compile(
                    sources=sources if sources else None,
                    filepaths=filepaths if filepaths else None,
                )
        except (ImportError, Exception):
            self._compiled_yara_rules = None

    async def ping(self) -> bool:
        """Check availability and readiness of the YARA evaluation engine.

        Returns:
            True indicating the scanner engine is initialized.
        """
        return True

    def _scan_native_yara(self, file_path: Path) -> SecurityScanResult | None:
        """Evaluate with native yara engine if compiled."""
        if self._compiled_yara_rules is None:
            return None

        try:
            matches = self._compiled_yara_rules.match(
                filepath=str(file_path),
                timeout=int(self._config.timeout_seconds),
            )
            if matches:
                rule_name = matches[0].rule
                return SecurityScanResult(
                    is_clean=False,
                    scanner_engine="YARA-native",
                    threat_name=f"YaraRuleMatch: {rule_name}",
                )
            return SecurityScanResult(
                is_clean=True,
                scanner_engine="YARA-native",
                threat_name=None,
            )
        except Exception as e:
            return SecurityScanResult(
                is_clean=False,
                scanner_engine="YARA-native",
                threat_name=f"YaraEvaluationError: {e}",
            )

    def _scan_heuristic_fallback(self, content: bytes) -> SecurityScanResult:
        """Evaluate file content using built-in heuristic patterns and inline rules."""
        engine_name = "YARA-heuristic-fallback"

        # 1. Built-in patterns
        for threat_id, pattern in _BUILTIN_PATTERNS:
            if pattern in content:
                return SecurityScanResult(
                    is_clean=False,
                    scanner_engine=engine_name,
                    threat_name=threat_id,
                )

        # 2. Inline regex patterns from config if any
        for inline in self._config.inline_rules:
            # Extract quoted string literal tokens inside rule body if present
            regex_matches = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', inline)
            for raw_pattern in regex_matches:
                if raw_pattern.encode("utf-8") in content:
                    return SecurityScanResult(
                        is_clean=False,
                        scanner_engine=engine_name,
                        threat_name=f"InlinePatternMatch: {raw_pattern}",
                    )

        return SecurityScanResult(
            is_clean=True,
            scanner_engine=engine_name,
            threat_name=None,
        )

    async def scan_file(self, file_path: Path) -> SecurityScanResult:
        """Scan a file for signature matches using native YARA or heuristic fallback.

        Args:
            file_path: Local filesystem Path of the file to inspect.

        Returns:
            SecurityScanResult detailing match findings.
        """
        if not file_path.is_file():
            return SecurityScanResult(
                is_clean=False,
                scanner_engine="YARA-engine",
                threat_name=f"FileNotFoundError: {file_path}",
            )

        # 1. Try native YARA compilation
        native_res = self._scan_native_yara(file_path)
        if native_res is not None:
            return native_res

        # 2. Pure-Python heuristic fallback
        try:
            content = file_path.read_bytes()
            return self._scan_heuristic_fallback(content)
        except Exception as e:
            return SecurityScanResult(
                is_clean=False,
                scanner_engine="YARA-heuristic-fallback",
                threat_name=f"FileReadError: {e}",
            )


__all__ = [
    "YaraRuleScannerAdapter",
]
