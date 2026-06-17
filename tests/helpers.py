from httpx import AsyncClient

DEFAULT_PASSWORD = "SecurePass123"


async def create_authenticated_user(
    client: AsyncClient,
    *,
    email: str,
    password: str = DEFAULT_PASSWORD,
) -> tuple[dict[str, object], dict[str, str]]:
    register_response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert register_response.status_code == 201

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_response.status_code == 200
    token = login_response.json()["data"]["access_token"]
    return register_response.json()["data"], {"Authorization": f"Bearer {token}"}


async def create_knowledge_base(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "Test Knowledge Base",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()["data"]
