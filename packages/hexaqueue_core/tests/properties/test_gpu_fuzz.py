"""Property-based fuzz tests for GPU allocation invariants and CUDA masking."""

from hypothesis import given
from hypothesis import strategies as st

from hexaqueue_core.domain.gpu import GpuAllocation


@given(
    job_id=st.text(
        alphabet=st.characters(categories=["Lu", "Ll", "Nd"]), min_size=1, max_size=32
    ),
    device_indices=st.lists(
        st.integers(min_value=0, max_value=64), unique=True, min_size=0, max_size=8
    ),
)
def test_fuzz_gpu_allocation_cuda_visible_devices_invariants(
    job_id: str, device_indices: list[int]
) -> None:
    """Property test verifying CUDA_VISIBLE_DEVICES string representation invariants."""
    alloc = GpuAllocation(job_id=job_id, device_indices=device_indices)
    env_str = alloc.cuda_visible_devices_env

    if not device_indices:
        assert env_str == ""
    else:
        parsed_indices = [int(x) for x in env_str.split(",")]
        expected_sorted = sorted(device_indices)
        assert parsed_indices == expected_sorted
        # Ensure strictly ascending order without duplicates
        for i in range(len(parsed_indices) - 1):
            is_less = parsed_indices[i] < parsed_indices[i + 1]
            assert is_less is True
