from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.config import settings
from app.core.exceptions import (
    EmailAlreadyRegistered,
    EmailNotVerified,
    InvalidCredentials,
    RefreshTokenReplayed,
    TokenExpired,
    TokenInvalid,
)
from app.core.security import (
    create_access_token,
    create_email_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_email_token,
    verify_password,
)
from app.db.models.oauth_account import OAuthAccount
from app.db.models.session import Session
from app.db.models.user import User, UserProfile


async def register(db: AsyncSession, email: str, password: str, display_name: str) -> User:
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise EmailAlreadyRegistered()

    user = User(
        email=email,
        password_hash=hash_password(password),
        role="student",
        email_verified=False,
    )
    db.add(user)
    await db.flush()

    profile = UserProfile(user_id=user.id, display_name=display_name)
    db.add(profile)
    await db.commit()
    await db.refresh(user)

    token = create_email_token(email, purpose="verify")
    from app.modules.auth.tasks import send_verification_email

    send_verification_email.delay(email, token)

    return user


async def verify_email(db: AsyncSession, token: str) -> None:
    try:
        email = verify_email_token(token, purpose="verify", max_age_seconds=86400)
    except TokenExpired:
        raise
    except TokenInvalid:
        raise

    user = await db.scalar(select(User).where(User.email == email))
    if not user:
        raise TokenInvalid()

    if user.email_verified:
        return

    user.email_verified = True
    await db.commit()


async def login(
    db: AsyncSession, email: str, password: str, response: Response
) -> tuple[str, User]:
    user = await db.scalar(select(User).where(User.email == email))
    if not user or not user.password_hash:
        raise InvalidCredentials()

    if not verify_password(password, user.password_hash):
        raise InvalidCredentials()

    if not user.email_verified:
        raise EmailNotVerified()

    access_token = create_access_token(str(user.id), user.role)
    raw_refresh = generate_refresh_token()

    session = Session(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(raw_refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    await db.commit()

    _set_refresh_cookie(response, raw_refresh)
    return access_token, user


async def refresh_token(
    db: AsyncSession, raw_refresh: str, response: Response
) -> str:
    token_hash = hash_refresh_token(raw_refresh)
    session = await db.scalar(select(Session).where(Session.refresh_token_hash == token_hash))

    if not session:
        raise TokenInvalid()

    if session.revoked_at is not None:
        # Replay detected — revoke all sessions for this user
        await db.execute(
            update(Session)
            .where(Session.user_id == session.user_id)
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
        raise RefreshTokenReplayed()

    if session.expires_at < datetime.now(UTC):
        raise TokenExpired()

    # Rotate: revoke old, create new
    session.revoked_at = datetime.now(UTC)

    user = await db.get(User, session.user_id)
    if not user:
        raise TokenInvalid()

    new_raw = generate_refresh_token()
    new_session = Session(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(new_raw),
        expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(new_session)
    await db.commit()

    _set_refresh_cookie(response, new_raw)
    return create_access_token(str(user.id), user.role)


async def logout(db: AsyncSession, raw_refresh: str, response: Response) -> None:
    token_hash = hash_refresh_token(raw_refresh)
    session = await db.scalar(select(Session).where(Session.refresh_token_hash == token_hash))
    if session and not session.revoked_at:
        session.revoked_at = datetime.now(UTC)
        await db.commit()
    response.delete_cookie("refresh_token")


async def forgot_password(db: AsyncSession, email: str) -> None:
    user = await db.scalar(select(User).where(User.email == email))
    if not user:
        return  # Silent — no email enumeration

    token = create_email_token(email, purpose="reset")
    from app.modules.auth.tasks import send_password_reset_email

    send_password_reset_email.delay(email, token)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    email = verify_email_token(token, purpose="reset", max_age_seconds=3600)

    user = await db.scalar(select(User).where(User.email == email))
    if not user:
        raise TokenInvalid()

    user.password_hash = hash_password(new_password)

    # Revoke all sessions
    await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def get_or_create_oauth_user(
    db: AsyncSession,
    provider: str,
    provider_user_id: str,
    email: str,
    display_name: str | None,
    access_token_enc: str | None,
    response: Response,
) -> tuple[str, User]:
    # Check for existing OAuth account
    oauth_account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )

    if oauth_account:
        user = await db.get(User, oauth_account.user_id)
        if not user:
            raise TokenInvalid()
    else:
        # Check for existing user by email
        user = await db.scalar(select(User).where(User.email == email))
        if not user:
            user = User(email=email, role="student", email_verified=True)
            db.add(user)
            await db.flush()
            profile = UserProfile(
                user_id=user.id, display_name=display_name or email.split("@")[0]
            )
            db.add(profile)
        else:
            user.email_verified = True

        oauth_account = OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            access_token_enc=access_token_enc,
        )
        db.add(oauth_account)
        await db.commit()
        await db.refresh(user)

    access_token = create_access_token(str(user.id), user.role)
    raw_refresh = generate_refresh_token()
    session = Session(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(raw_refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    await db.commit()

    _set_refresh_cookie(response, raw_refresh)
    return access_token, user


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/v1/auth",
    )


async def resend_verification(db: AsyncSession, email: str) -> None:
    user = await db.scalar(select(User).where(User.email == email))
    if not user or user.email_verified:
        return  # Silent

    token = create_email_token(email, purpose="verify")
    from app.modules.auth.tasks import send_verification_email

    send_verification_email.delay(email, token)
