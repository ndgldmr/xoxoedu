
import pytest
from freezegun import freeze_time

from app.core.security import (
    create_access_token,
    create_email_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_email_token,
    verify_password,
)


def test_hash_password_and_verify() -> None:
    hashed = hash_password("mysecretpassword")
    assert verify_password("mysecretpassword", hashed) is True


def test_wrong_password_fails() -> None:
    hashed = hash_password("correct")
    assert verify_password("wrong", hashed) is False


def test_create_and_decode_access_token() -> None:
    token = create_access_token("user-id-123", "student")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-id-123"
    assert payload["role"] == "student"


def test_access_token_contains_jti() -> None:
    token = create_access_token("user-id-123", "student")
    payload = decode_access_token(token)
    assert "jti" in payload


def test_expired_access_token_raises() -> None:
    from app.core.exceptions import TokenInvalid

    with freeze_time("2020-01-01"):
        token = create_access_token("user-id-123", "student")

    # Token issued in 2020, decode in 2026 — definitely expired
    with pytest.raises(TokenInvalid):
        decode_access_token(token)


def test_tampered_token_raises() -> None:
    from app.core.exceptions import TokenInvalid

    token = create_access_token("user-id-123", "student")
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(TokenInvalid):
        decode_access_token(tampered)


def test_generate_refresh_token_is_unique() -> None:
    tokens = {generate_refresh_token() for _ in range(100)}
    assert len(tokens) == 100


def test_hash_refresh_token_is_deterministic() -> None:
    token = generate_refresh_token()
    assert hash_refresh_token(token) == hash_refresh_token(token)


def test_hash_refresh_token_different_inputs() -> None:
    t1 = generate_refresh_token()
    t2 = generate_refresh_token()
    assert hash_refresh_token(t1) != hash_refresh_token(t2)


def test_email_token_round_trip() -> None:
    token = create_email_token("user@example.com", purpose="verify")
    email = verify_email_token(token, purpose="verify", max_age_seconds=86400)
    assert email == "user@example.com"


def test_email_token_wrong_purpose_raises() -> None:
    from app.core.exceptions import TokenInvalid

    token = create_email_token("user@example.com", purpose="verify")
    with pytest.raises(TokenInvalid):
        verify_email_token(token, purpose="reset", max_age_seconds=86400)


def test_email_token_expired_raises() -> None:
    from app.core.exceptions import TokenExpired

    with freeze_time("2020-01-01 00:00:00"):
        token = create_email_token("user@example.com", purpose="verify")

    with freeze_time("2020-01-03 00:00:01"), pytest.raises(TokenExpired):  # 2 days + 1s later
        verify_email_token(token, purpose="verify", max_age_seconds=86400)
