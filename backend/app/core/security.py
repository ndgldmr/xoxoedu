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
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str, role: str) -> str:
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
    try:
        return jwt.decode(token, settings.JWT_PUBLIC_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        from app.core.exceptions import TokenInvalid

        raise TokenInvalid() from e


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_email_token(email: str, purpose: str) -> str:
    s = URLSafeTimedSerializer(settings.SECRET_KEY, salt=purpose)
    return s.dumps(email)


def verify_email_token(token: str, purpose: str, max_age_seconds: int) -> str:
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
