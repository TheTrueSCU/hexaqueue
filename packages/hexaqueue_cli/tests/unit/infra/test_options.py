"""Unit tests for CLI infra format options and resolution."""

from unittest.mock import patch

from hexaqueue_cli.domain.options import OutputFormat
from hexaqueue_cli.infra.options import format_option, resolve_format


def test_format_option_factory() -> None:
    """Verify format_option constructs a Typer OptionInfo with expected flags."""
    opt = format_option(default="table", help_text="Test format")
    assert opt.default == "table"
    assert opt.param_decls == ("-f", "--format")
    assert opt.help == "Test format"


def test_resolve_format_explicit_strings() -> None:
    """Explicit formats pass through unchanged in lowercase."""
    res_json = resolve_format("JSON")
    assert res_json == "json"

    res_table = resolve_format("Table")
    assert res_table == "table"

    res_markdown = resolve_format("Markdown")
    assert res_markdown == "markdown"

    res_plain = resolve_format("PLAIN")
    assert res_plain == "plain"


def test_resolve_format_enum() -> None:
    """OutputFormat enum resolves to its string value."""
    res = resolve_format(OutputFormat.MARKDOWN)
    assert res == "markdown"


def test_resolve_format_auto_pipe_detection() -> None:
    """Auto format detects pipe vs TTY streams."""
    with patch("sys.stdout.isatty", return_value=True):
        res_tty = resolve_format("auto", default_tty="table", default_pipe="json")
        assert res_tty == "table"

    with patch("sys.stdout.isatty", return_value=False):
        res_pipe = resolve_format("auto", default_tty="table", default_pipe="json")
        assert res_pipe == "json"

    with patch("sys.stdout.isatty", return_value=False):
        res_enum_pipe = resolve_format(
            OutputFormat.AUTO, default_tty="rich", default_pipe="plain"
        )
        assert res_enum_pipe == "plain"
