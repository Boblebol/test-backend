import hashlib
import hmac

from app.modules.partner_webhooks.signatures import build_partner_signature, is_valid_partner_signature


def test_build_partner_signature_uses_hmac_sha256_hex_digest() -> None:
    raw_body = b'{"job_id":"j_123","status":"completed"}'
    secret = "shared-secret"

    signature = build_partner_signature(raw_body, secret)

    assert signature == hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def test_is_valid_partner_signature_compares_expected_signature() -> None:
    raw_body = b'{"job_id":"j_123","status":"completed"}'
    signature = build_partner_signature(raw_body, "shared-secret")

    assert is_valid_partner_signature(raw_body, signature, "shared-secret") is True
    assert is_valid_partner_signature(raw_body, "bad-signature", "shared-secret") is False
