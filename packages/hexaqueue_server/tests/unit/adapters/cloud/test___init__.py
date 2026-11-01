"""Tests for hexaqueue_server.adapters.cloud exports."""

from hexaqueue_server.adapters import cloud


def test_cloud_adapters_exports() -> None:
    """Verify all cloud adapters are exported."""
    expected = [
        "AwsAutoScalingGroupAdapter",
        "AzureScaleSetAdapter",
        "create_cloud_governors",
        "GcpManagedInstanceGroupAdapter",
        "OciInstancePoolAdapter",
    ]
    exports = cloud.__all__
    assert exports == sorted(expected, key=str.casefold)
