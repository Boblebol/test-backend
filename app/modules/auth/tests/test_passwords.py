from app.modules.auth.passwords import hash_password, verify_password


def test_hash_password_does_not_store_plain_text() -> None:
    password_hash = hash_password("primmo-demo")

    assert password_hash != "primmo-demo"
    assert password_hash.startswith("pbkdf2_sha256$")


def test_verify_password_checks_password_against_hash() -> None:
    password_hash = hash_password("primmo-demo")

    assert verify_password("primmo-demo", password_hash) is True
    assert verify_password("wrong-password", password_hash) is False
