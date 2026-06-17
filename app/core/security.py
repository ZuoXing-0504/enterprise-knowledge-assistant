from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from anyio import to_thread
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.auth import TokenPayload

password_hasher = PasswordHash.recommended()


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(password_hasher.hash, password)


async def verify_password(password: str, password_hash: str) -> bool:
    return await to_thread.run_sync(password_hasher.verify, password, password_hash)


def create_access_token(subject: UUID) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.access_token_expire_minutes * 60
    issued_at = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": "access",
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=expires_in),
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_in


def decode_access_token(token: str) -> TokenPayload:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "type", "iat", "exp"]},
        )
        return TokenPayload.model_validate(payload)
    except (InvalidTokenError, ValidationError) as exc:
        raise ValueError("Invalid access token") from exc
