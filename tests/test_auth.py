from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.user import User

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/users/me"
PASSWORD = "SecurePass123"


async def register_user(
    client: AsyncClient,
    *,
    email: str = "user@example.com",
    password: str = PASSWORD,
) -> dict[str, object]:
    response = await client.post(REGISTER_URL, json={"email": email, "password": password})
    assert response.status_code == 201
    return response.json()["data"]


async def login_user(
    client: AsyncClient,
    *,
    email: str = "user@example.com",
    password: str = PASSWORD,
) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


async def test_register_normalizes_email_and_hashes_password(client: AsyncClient) -> None:
    data = await register_user(client, email="User@Example.COM")

    assert data["email"] == "user@example.com"
    assert "password" not in data
    assert "password_hash" not in data

    async with async_session_factory() as session:
        stored_user = (await session.execute(select(User))).scalar_one()
        assert stored_user.password_hash != PASSWORD
        assert stored_user.password_hash.startswith("$argon2")


async def test_register_rejects_duplicate_email_case_insensitively(client: AsyncClient) -> None:
    await register_user(client, email="user@example.com")

    response = await client.post(
        REGISTER_URL,
        json={"email": "USER@example.com", "password": PASSWORD},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


async def test_login_returns_access_token(client: AsyncClient) -> None:
    await register_user(client)

    response = await client.post(
        LOGIN_URL,
        json={"email": "USER@EXAMPLE.COM", "password": PASSWORD},
    )

    assert response.status_code == 200
    token_data = response.json()["data"]
    assert token_data["token_type"] == "bearer"
    assert token_data["expires_in"] == 1800
    assert isinstance(token_data["access_token"], str)


async def test_login_rejects_invalid_password(client: AsyncClient) -> None:
    await register_user(client)

    response = await client.post(
        LOGIN_URL,
        json={"email": "user@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_get_current_user(client: AsyncClient) -> None:
    registered_user = await register_user(client)
    token = await login_user(client)

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["data"]["id"] == registered_user["id"]
    assert response.json()["data"]["email"] == "user@example.com"


async def test_get_current_user_requires_token(client: AsyncClient) -> None:
    response = await client.get(ME_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_get_current_user_rejects_malformed_token(client: AsyncClient) -> None:
    response = await client.get(ME_URL, headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_get_current_user_rejects_expired_token(client: AsyncClient) -> None:
    user = await register_user(client)
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": user["id"],
            "type": "access",
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
