from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.modules.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.models import UserState
from app.modules.auth.repository import UserRepository
from app.modules.auth.service import AuthService, InvalidCredentials
from app.modules.auth.tokens import TokenService


router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    email: str = Field(description="User email.")
    password: str = Field(description="User password.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "alpha@example.com",
                "password": "primmo-demo",
            }
        }
    }


class LoginResponse(BaseModel):
    access_token: str = Field(description="JWT bearer token.")
    token_type: str = Field(description="Token type, always `bearer`.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "access_token": "<jwt>",
                "token_type": "bearer",
            }
        }
    }


class CurrentUserResponse(BaseModel):
    id: UUID
    org_id: UUID
    email: str


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login",
    description="Authenticate a seeded demo user and return a JWT bearer token.",
)
def login(
    body: LoginRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> LoginResponse:
    settings = get_settings()
    service = AuthService(
        users=UserRepository(session),
        tokens=TokenService(
            secret=settings.jwt_secret,
            expires_minutes=settings.jwt_expires_minutes,
        ),
    )

    try:
        result = service.login(body.email, body.password)
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        ) from exc

    return LoginResponse(
        access_token=result.access_token,
        token_type=result.token_type,
    )


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Get current user",
    description="Return the identity and organization carried by the bearer token.",
)
def me(current_user: Annotated[UserState, Depends(get_current_user)]) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=current_user.id,
        org_id=current_user.org_id,
        email=current_user.email,
    )
