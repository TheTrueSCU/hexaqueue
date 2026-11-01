"""Unit tests for HexaqueueTestDispatchClient and InMemoryTestDispatchClient."""

import pytest
from pytest_hexaqueue.adapters.client import (
    HexaqueueTestDispatchClient,
    InMemoryTestDispatchClient,
)
from pytest_hexaqueue.domain.slice import TestRunSession, TestSliceSpec


@pytest.mark.asyncio
async def test_in_memory_client_lifecycle_and_multi_csp() -> None:
    """Test in-memory simulation client with free-tier multi-CSP simulation."""
    client = InMemoryTestDispatchClient(is_free_tier=True)
    assert await client.health_check() is True

    session = TestRunSession(
        session_id="session-test-01",
        total_items=4,
        total_slices=2,
        free_tier=True,
        slices=[
            TestSliceSpec(
                slice_id="s0", slice_index=0, total_slices=2, test_nodeids=["t1", "t2"]
            ),
            TestSliceSpec(
                slice_id="s1", slice_index=1, total_slices=2, test_nodeids=["t3", "t4"]
            ),
        ],
    )

    reports = await client.dispatch_run(session)
    assert len(reports) == 2
    assert reports[0].slice_id == "s0"
    assert reports[0].provider == "OCI"
    assert reports[0].is_free_tier is True
    assert reports[0].passed_count == 2
    assert reports[0].is_success is True

    assert reports[1].slice_id == "s1"
    assert reports[1].provider == "GCP"
    assert reports[1].is_free_tier is True
    assert reports[1].passed_count == 2


@pytest.mark.asyncio
async def test_in_memory_client_failure_injection() -> None:
    """Test in-memory client simulating test failures."""
    client = InMemoryTestDispatchClient(fail_nodeids={"t2"})
    session = TestRunSession(
        session_id="session-test-02",
        total_items=2,
        total_slices=1,
        slices=[
            TestSliceSpec(
                slice_id="s0", slice_index=0, total_slices=1, test_nodeids=["t1", "t2"]
            ),
        ],
    )
    reports = await client.dispatch_run(session)
    assert len(reports) == 1
    assert reports[0].passed_count == 1
    assert reports[0].failed_count == 1
    assert reports[0].is_success is False
    assert "AssertionError" in str(reports[0].outcomes[1].longrepr)


@pytest.mark.asyncio
async def test_in_memory_client_unhealthy() -> None:
    """Test in-memory client when unhealthy raises ConnectionError."""
    client = InMemoryTestDispatchClient(is_healthy=False)
    assert await client.health_check() is False

    session = TestRunSession(session_id="s1", total_items=1, total_slices=1)
    with pytest.raises(ConnectionError, match="unhealthy"):
        await client.dispatch_run(session)


@pytest.mark.asyncio
async def test_http_dispatch_client_offline() -> None:
    """Test that HTTP dispatch client reports offline when server is not running."""
    client = HexaqueueTestDispatchClient(
        server_url="http://127.0.0.1:59999", timeout_seconds=0.1
    )
    is_healthy = await client.health_check()
    assert is_healthy is False

    session = TestRunSession(session_id="s1", total_items=1, total_slices=1)
    with pytest.raises(ConnectionError, match="unreachable"):
        await client.dispatch_run(session)


@pytest.mark.asyncio
async def test_http_dispatch_client_success_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test HTTP dispatch client successful health check and run dispatch."""
    import httpx

    class MockAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def get(self, url: str) -> httpx.Response:
            return httpx.Response(200, json={"status": "healthy"})

        async def post(
            self, url: str, json: dict[str, object] | None = None
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "reports": [
                        {
                            "slice_id": "s0",
                            "slice_index": 0,
                            "worker_id": "w0",
                            "provider": "OCI",
                            "is_free_tier": True,
                            "outcomes": [],
                            "duration_seconds": 0.5,
                        }
                    ]
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = HexaqueueTestDispatchClient(server_url="http://mocked-hexaqueue:8000")
    assert await client.health_check() is True

    session = TestRunSession(
        session_id="s1",
        total_items=1,
        total_slices=1,
        slices=[
            TestSliceSpec(
                slice_id="s0", slice_index=0, total_slices=1, test_nodeids=["t1"]
            )
        ],
    )
    reports = await client.dispatch_run(session)
    assert len(reports) == 1
    assert reports[0].slice_id == "s0"
    assert reports[0].worker_id == "w0"
    assert reports[0].provider == "OCI"


@pytest.mark.asyncio
async def test_http_dispatch_client_error_response_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test HTTP dispatch client raises ConnectionError on 500 response."""
    import httpx

    class MockAsyncClient500:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient500":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def post(
            self, url: str, json: dict[str, object] | None = None
        ) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient500)

    client = HexaqueueTestDispatchClient(server_url="http://mocked-hexaqueue:8000")
    session = TestRunSession(session_id="s1", total_items=1, total_slices=1)
    with pytest.raises(ConnectionError, match="HTTP 500"):
        await client.dispatch_run(session)


@pytest.mark.asyncio
async def test_http_dispatch_client_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test HTTP dispatch client passes Authorization: Bearer token in headers."""
    import httpx

    captured_headers: list[dict[str, str]] = []

    class MockAsyncClientWithAuth:
        def __init__(self, *args: object, **kwargs: object) -> None:
            if "headers" in kwargs and isinstance(kwargs["headers"], dict):
                captured_headers.append(kwargs["headers"])

        async def __aenter__(self) -> "MockAsyncClientWithAuth":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def get(self, url: str) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok"})

        async def post(
            self, url: str, json: dict[str, object] | None = None
        ) -> httpx.Response:
            return httpx.Response(200, json={"reports": []})

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClientWithAuth)

    client = HexaqueueTestDispatchClient(
        server_url="http://mocked-hexaqueue:8000",
        api_token="test-secret-token",
    )
    is_healthy = await client.health_check()
    assert is_healthy is True

    session = TestRunSession(session_id="s1", total_items=1, total_slices=1)
    reports = await client.dispatch_run(session)
    assert len(reports) == 0

    assert len(captured_headers) == 2
    assert captured_headers[0].get("Authorization") == "Bearer test-secret-token"
    assert captured_headers[1].get("Authorization") == "Bearer test-secret-token"
