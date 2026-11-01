"""Unit tests for WorkspaceDeltaBundle."""

from pytest_hexaqueue.domain.delta import WorkspaceDeltaBundle


def test_workspace_delta_bundle() -> None:
    """Test WorkspaceDeltaBundle fields and calculations."""
    bundle = WorkspaceDeltaBundle(
        bundle_id="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        git_commit="deadbeefcafebabe1234567890abcdef12345678",
        file_hashes={
            "src/app.py": "hash1",
            "tests/test_app.py": "hash2",
        },
        total_files=2,
        total_bytes=4096,
    )
    assert bundle.bundle_id.startswith("a1b2c3d4")
    assert bundle.git_commit is not None
    assert bundle.git_commit.startswith("deadbeef")
    assert len(bundle.file_hashes) == 2
    assert bundle.total_files == 2
    assert bundle.total_bytes == 4096
