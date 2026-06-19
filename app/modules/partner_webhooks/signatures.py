import hashlib
import hmac


def build_partner_signature(raw_body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def is_valid_partner_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    expected = build_partner_signature(raw_body, secret)
    return hmac.compare_digest(signature, expected)
