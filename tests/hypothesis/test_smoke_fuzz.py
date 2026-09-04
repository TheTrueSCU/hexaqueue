"""Property-based fuzzing smoke tests."""

from hypothesis import given
from hypothesis import strategies as st


@given(st.text())
def test_hypothesis_smoke(text: str):
    """Basic hypothesis fuzzer invariant."""
    assert isinstance(text, str)
