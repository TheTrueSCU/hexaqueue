"""Unit tests for CLI domain options."""

from hexaqueue_cli.domain.options import OutputFormat


def test_output_format_values() -> None:
    """Verify all supported OutputFormat enum members and values."""
    assert OutputFormat.AUTO == "auto"
    assert OutputFormat.JSON == "json"
    assert OutputFormat.MARKDOWN == "markdown"
    assert OutputFormat.PLAIN == "plain"
    assert OutputFormat.RICH == "rich"
    assert OutputFormat.TABLE == "table"


def test_output_format_str_behavior() -> None:
    """Verify OutputFormat string inheritance and hashing."""
    val = OutputFormat.JSON
    assert isinstance(val, str)
    assert val == "json"
    assert str(val) == "json"
