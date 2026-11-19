"""Shared NiceGUI UI fake elements for dashboard adapter unit tests."""

from __future__ import annotations

import pytest


class FakeUIElement:
    """Minimal fluent NiceGUI element stub for unit-testing view composition."""

    def __init__(self, value: str = "", **kwargs: object) -> None:
        self.value = value
        self.text = ""
        self.kwargs: dict[str, object] = dict(kwargs)
        self.slots: dict[str, str] = {}
        self.handlers: dict[str, object] = {}

    def __enter__(self) -> FakeUIElement:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def classes(self, *_args: object) -> FakeUIElement:
        return self

    def props(self, *_args: object) -> FakeUIElement:
        return self

    def style(self, *_args: object) -> FakeUIElement:
        return self

    def tooltip(self, *_args: object) -> FakeUIElement:
        return self

    def add_slot(self, name: str = "", template: str = "", **_kwargs: object) -> None:
        if name:
            self.slots[name] = template

    def on(
        self, event: str = "", handler: object = None, **_kwargs: object
    ) -> FakeUIElement:
        if event and handler is not None:
            self.handlers[event] = handler
        return self

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def expand(self, *_args: object, **_kwargs: object) -> FakeUIElement:
        return self

    def clear(self) -> None:
        return None

    def set_visibility(self, *_args: object, **_kwargs: object) -> FakeUIElement:
        return self

    def update(self) -> None:
        return None


class FakeUITable(FakeUIElement):
    """Standard NiceGUI ``ui.table`` stub capturing columns, rows, slots, and events."""

    def __init__(
        self,
        value: str = "",
        *,
        columns: list[dict[str, object]] | None = None,
        rows: list[dict[str, object]] | None = None,
        row_key: str = "id",
        pagination: dict[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(value=value, **kwargs)
        self.columns: list[dict[str, object]] = list(columns or [])
        self.rows: list[dict[str, object]] = list(rows or [])
        self.row_key = row_key
        self.pagination: dict[str, object] = dict(pagination or {})
        self.updated_count = 0

    def update(self) -> None:
        self.updated_count += 1


@pytest.fixture
def fake_el() -> type[FakeUIElement]:
    """Return the shared FakeUIElement stub class for NiceGUI unit tests."""
    return FakeUIElement


@pytest.fixture
def fake_table() -> type[FakeUITable]:
    """Return the shared FakeUITable stub class for NiceGUI table unit tests."""
    return FakeUITable
