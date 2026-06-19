from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.models import UserState
from app.modules.auth.repository import UserRepository
from app.modules.auth.tokens import TokenService, TokenValidationError


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[Session, Depends(get_db_session)],
) -> UserState:
    settings = get_settings()
    token_service = TokenService(
        secret=settings.jwt_secret,
        expires_minutes=settings.jwt_expires_minutes,
    )

    try:
        payload = token_service.decode_access_token(token)
    except TokenValidationError as exc:
        raise _unauthorized() from exc

    user = UserRepository(session).get(payload.user_id)
    if user is None or user.org_id != payload.org_id or user.email != payload.email:
        raise _unauthorized()

    return user


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
