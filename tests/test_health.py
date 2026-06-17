from httpx import AsyncClient


async def test_health_check(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "test-request-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"
    assert response.json() == {
        "success": True,
        "data": {"status": "ok", "environment": "test", "version": "0.1.0"},
        "error": None,
        "request_id": "test-request-id",
    }


async def test_openapi_is_available(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Enterprise Knowledge Base Assistant"


async def test_not_found_uses_standard_error_response(client: AsyncClient) -> None:
    response = await client.get("/missing", headers={"X-Request-ID": "missing-request-id"})

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "data": None,
        "error": {"code": "http_error", "message": "Not Found", "details": None},
        "request_id": "missing-request-id",
    }
