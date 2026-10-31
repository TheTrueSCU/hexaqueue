"""Test hexaqueue package exports and namespace bindings."""

import hexaqueue


def test_hexaqueue_package_exports() -> None:
    """Verify package can be imported and subpackages are accessible."""
    assert hexaqueue is not None
    assert "github_runner" in hexaqueue.__all__
    assert hasattr(hexaqueue, "github_runner")
    assert dir(hexaqueue) is not None
