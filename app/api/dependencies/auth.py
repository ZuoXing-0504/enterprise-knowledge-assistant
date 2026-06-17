from typing import Annotated

from fastapi import Depends, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies.database import SessionDependency
from app.core.exceptions import AppError
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    session: SessionDependency,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            code="not_authenticated",
            message="Authentication credentials were not provided",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token_payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise AppError(
            code="invalid_token",
            message="Access token is invalid or expired",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await UserRepository(session).get_by_id(token_payload.sub)
    if user is None:
        raise AppError(
            code="invalid_token",
            message="Access token is invalid or expired",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise AppError(
            code="inactive_user",
            message="User account is inactive",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
