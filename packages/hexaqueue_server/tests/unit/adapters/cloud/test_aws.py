"""Unit tests for AwsAutoScalingGroupAdapter."""

from unittest.mock import MagicMock

import pytest

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import InstancePoolState, PoolScaleRequest
from hexaqueue_server.adapters.cloud.aws import AwsAutoScalingGroupAdapter


@pytest.mark.asyncio
async def test_aws_asg_local_simulation() -> None:
    """Verify local pool registration, listing, and scaling."""
    adapter = AwsAutoScalingGroupAdapter()
    pool = InstancePoolState(
        pool_id="asg-test-local",
        provider=CspProvider.AWS,
        min_nodes=0,
        max_nodes=10,
        desired_nodes=1,
        current_nodes=1,
    )
    adapter.register_mock_pool(pool)

    pools = await adapter.list_pools()
    count = len(pools)
    assert count == 1

    state = await adapter.get_pool_state("asg-test-local")
    nodes = state.current_nodes
    assert nodes == 1

    scale_res = await adapter.scale_pool(
        PoolScaleRequest(pool_id="asg-test-local", target_nodes=5, reason="Surge")
    )
    ok = scale_res.success
    assert ok is True
    target = scale_res.target_nodes
    assert target == 5

    updated_state = await adapter.get_pool_state("asg-test-local")
    new_nodes = updated_state.current_nodes
    assert new_nodes == 5


@pytest.mark.asyncio
async def test_aws_asg_with_boto_client() -> None:
    """Verify AWS adapter interactions with injected boto3 client."""
    mock_boto = MagicMock()
    mock_boto.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {
                "AutoScalingGroupName": "asg-prod",
                "MinSize": 1,
                "MaxSize": 20,
                "DesiredCapacity": 3,
                "Instances": [
                    {
                        "InstanceId": "i-12345",
                        "LifecycleState": "InService",
                        "InstanceType": "c5.large",
                        "LaunchTemplate": {"LaunchTemplateId": "lt-123"},
                    }
                ],
                "Tags": [{"Key": "os:linux"}, {"Key": "role:worker"}],
            }
        ]
    }

    adapter = AwsAutoScalingGroupAdapter(boto_client=mock_boto)
    state = await adapter.get_pool_state("asg-prod")
    p_id = state.pool_id
    assert p_id == "asg-prod"
    curr = state.current_nodes
    assert curr == 1
    ready = state.ready_nodes
    assert ready == 1
    spot = state.spot_nodes
    assert spot == 1
    tags = state.capability_tags
    assert "os:linux" in tags

    res = await adapter.scale_pool(
        PoolScaleRequest(pool_id="asg-prod", target_nodes=4, reason="Burst")
    )
    ok = res.success
    assert ok is True
    mock_boto.set_desired_capacity.assert_called_once_with(
        AutoScalingGroupName="asg-prod",
        DesiredCapacity=4,
        HonorCooldown=False,
    )


@pytest.mark.asyncio
async def test_aws_asg_not_found() -> None:
    """Verify error when ASG is missing."""
    adapter = AwsAutoScalingGroupAdapter()
    with pytest.raises(HexaqueueError, match="not found"):
        await adapter.get_pool_state("nonexistent")
