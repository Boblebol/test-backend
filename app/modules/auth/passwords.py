import base64
import hashlib
import secrets


ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 260_000
SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    password_hash = _pbkdf2(password, salt, ITERATIONS)
    return "$".join(
        [
            ALGORITHM,
            str(ITERATIONS),
            _b64encode(salt),
            _b64encode(password_hash),
        ]
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, expected_hash = encoded_hash.split("$", maxsplit=3)
    except ValueError:
        return False

    if algorithm != ALGORITHM:
        return False

    salt = _b64decode(encoded_salt)
    actual_hash = _pbkdf2(password, salt, int(iterations))
    return secrets.compare_digest(_b64encode(actual_hash), expected_hash)


def _pbkdf2(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))
