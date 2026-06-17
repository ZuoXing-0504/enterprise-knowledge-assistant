from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def register(self, payload: RegisterRequest) -> User:
        email = str(payload.email).lower()
        if await self.users.get_by_email(email) is not None:
            raise AppError(
                code="email_already_registered",
                message="Email is already registered",
                status_code=status.HTTP_409_CONFLICT,
            )

        password_hash = await hash_password(payload.password)
        try:
            user = await self.users.create(email=email, password_hash=password_hash)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError(
                code="email_already_registered",
                message="Email is already registered",
                status_code=status.HTTP_409_CONFLICT,
            ) from exc
        return user

    async def login(self, payload: LoginRequest) -> TokenResponse:
        email = str(payload.email).lower()
        user = await self.users.get_by_email(email)
        if user is None or not await verify_password(payload.password, user.password_hash):
            raise AppError(
                code="invalid_credentials",
                message="Invalid email or password",
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            raise AppError(
                code="inactive_user",
                message="User account is inactive",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        access_token, expires_in = create_access_token(user.id)
        return TokenResponse(access_token=access_token, expires_in=expires_in)
