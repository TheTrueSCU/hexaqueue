"""Shared NiceGUI UI fake elements for dashboard adapter unit tests."""

from __future__ import annotations

import pytest


class FakeUIElement:
    """Minimal fluent NiceGUI element stub for unit-testing view composition."""

    def __init__(self, value: str = "") -> None:
        self.value = value
        self.text = ""

    def __enter__(self) -> FakeUIElement:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def classes(self, *_args: object) -> FakeUIElement:
        return self

    def props(self, *_args: object) -> FakeUIElement:
        return self

    def tooltip(self, *_args: object) -> FakeUIElement:
        return self

    def add_slot(self, *_args: object, **_kwargs: object) -> None:
        return None

    def on(self, *_args: object, **_kwargs: object) -> FakeUIElement:
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


@pytest.fixture
def fake_el() -> type[FakeUIElement]:
    """Return the shared FakeUIElement stub class for NiceGUI unit tests."""
    return FakeUIElement
