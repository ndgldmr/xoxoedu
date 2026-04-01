"""Cryptographic utilities: password hashing, JWT access tokens, refresh tokens, and signed email tokens."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from jose import JWTError, jwt

from app.config import settings

_BCRYPT_ROUNDS = 12


def hash_password(plain: str) -> str:
    """Hash a plain-text password using bcrypt with a freshly generated salt.

    Args:
        plain: The raw password string supplied by the user.

    Returns:
        A bcrypt digest string suitable for storage in the database.
    """
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a stored bcrypt hash.

    Args:
        plain: The raw password to check.
        hashed: The bcrypt hash previously returned by ``hash_password``.

    Returns:
        ``True`` if the password matches the hash, ``False`` otherwise.
    """
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str, role: str) -> str:
    """Create a signed RS256 JWT access token.

    The token contains ``sub`` (user ID), ``role``, ``iat`` (issued-at),
    ``exp`` (expiry), and ``jti`` (unique token ID) claims.

    Args:
        user_id: The user's UUID as a string, used as the ``sub`` claim.
        role: The user's role string (e.g. ``"student"`` or ``"admin"``).

    Returns:
        A compact JWS token string.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, object]:
    """Decode and verify a JWT access token, returning its claims.

    Args:
        token: The compact JWS token string to decode.

    Returns:
        The decoded JWT payload as a plain dictionary.

    Raises:
        TokenInvalid: If the token is malformed, has an invalid signature,
            or has expired (jose raises ``JWTError`` for all these cases).
    """
    try:
        return jwt.decode(token, settings.JWT_PUBLIC_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        from app.core.exceptions import TokenInvalid

        raise TokenInvalid() from e


def generate_refresh_token() -> str:
    """Generate a cryptographically secure random refresh token.

    Returns:
        A 64-byte URL-safe base64-encoded random string.
    """
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    """Return the SHA-256 hex digest of a refresh token for safe storage.

    The raw token is never persisted; only this digest is stored in the
    ``sessions`` table.

    Args:
        token: The raw URL-safe refresh token string.

    Returns:
        A 64-character lowercase hex string.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def create_email_token(email: str, purpose: str) -> str:
    """Create a time-limited, signed URL-safe token encoding an email address.

    Uses ``itsdangerous.URLSafeTimedSerializer`` with ``purpose`` as the salt
    so that a token issued for ``"verify"`` cannot be replayed for ``"reset"``.

    Args:
        email: The email address to encode into the token.
        purpose: A salt string that scopes the token (e.g. ``"verify"`` or ``"reset"``).

    Returns:
        A signed, URL-safe token string.
    """
    s = URLSafeTimedSerializer(settings.SECRET_KEY, salt=purpose)
    return s.dumps(email)


def verify_email_token(token: str, purpose: str, max_age_seconds: int) -> str:
    """Verify a signed email token and return the email it encodes.

    Args:
        token: The signed token string previously returned by ``create_email_token``.
        purpose: The salt that was used when creating the token.
        max_age_seconds: Maximum allowed age of the token in seconds.

    Returns:
        The email address encoded in the token.

    Raises:
        TokenExpired: If the token is valid but older than ``max_age_seconds``.
        TokenInvalid: If the token has an invalid signature or is malformed.
    """
    s = URLSafeTimedSerializer(settings.SECRET_KEY, salt=purpose)
    try:
        email: str = s.loads(token, max_age=max_age_seconds)
        return email
    except SignatureExpired as e:
        from app.core.exceptions import TokenExpired

        raise TokenExpired() from e
    except BadSignature as e:
        from app.core.exceptions import TokenInvalid

        raise TokenInvalid() from e
