from app.domain.models import LoginResult, UserState
from app.modules.auth.passwords import verify_password


class InvalidCredentials(ValueError):
    pass


class AuthService:
    def __init__(self, *, users, tokens):
        self.users = users
        self.tokens = tokens

    def login(self, email: str, password: str) -> LoginResult:
        normalized_email = email.strip().lower()
        user = self.users.get_credentials_by_email(normalized_email)

        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentials("invalid email or password")

        access_token = self.tokens.create_access_token(
            user_id=user.id,
            org_id=user.org_id,
            email=user.email,
        )
        return LoginResult(
            access_token=access_token,
            token_type="bearer",
            user=UserState(
                id=user.id,
                org_id=user.org_id,
                email=user.email,
                created_at=user.created_at,
            ),
        )
