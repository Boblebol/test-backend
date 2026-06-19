from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt


class TokenValidationError(ValueError):
    pass


@dataclass(frozen=True)
class TokenPayload:
    user_id: UUID
    org_id: UUID
    email: str


class TokenService:
    def __init__(self, *, secret: str, expires_minutes: int):
        self.secret = secret
        self.expires_minutes = expires_minutes

    def create_access_token(
        self,
        *,
        user_id: UUID,
        org_id: UUID,
        email: str,
        now: datetime | None = None,
    ) -> str:
        now = now or datetime.now(UTC)
        payload = {
            "sub": str(user_id),
            "org_id": str(org_id),
            "email": email,
            "exp": now + timedelta(minutes=self.expires_minutes),
        }
        return jwt.encode(payload, self.secret, algorithm="HS256")

    def decode_access_token(self, token: str) -> TokenPayload:
        try:
            payload = jwt.decode(token, self.secret, algorithms=["HS256"])
            return TokenPayload(
                user_id=UUID(payload["sub"]),
                org_id=UUID(payload["org_id"]),
                email=payload["email"],
            )
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise TokenValidationError("invalid access token") from exc
