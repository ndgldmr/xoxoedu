"""Business logic for authentication: registration, login, token rotation, and OAuth."""

import uuid
from datetime import UTC, date, datetime, timedelta

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
    UsernameAlreadyTaken,
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
from app.db.models.user import User
from app.modules.users.usernames import generate_unique_username


async def register(
    db: AsyncSession,
    email: str,
    username: str,
    password: str,
    display_name: str,
    date_of_birth: date,
    country: str,
    gender: str,
    avatar_url: str,
    social_links: dict | None,
) -> User:
    """Create a new student account and send an email-verification link.

    Args:
        db: Async database session.
        email: Desired email address; must be unique across all users.
        username: Desired mention handle; must be unique across all users.
        password: Plain-text password; stored as a bcrypt hash.
        display_name: Initial display name for the user's public profile.
        date_of_birth: Required onboarding date of birth.
        country: Signup country used for launch-market mapping.
        gender: Selected gender option.
        avatar_url: Uploaded avatar public URL.
        social_links: Optional social profile URLs.

    Returns:
        The newly created ``User`` ORM instance.

    Raises:
        EmailAlreadyRegistered: If an account with that email already exists.
        UsernameAlreadyTaken: If an account with that username already exists.
    """
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise EmailAlreadyRegistered()

    username = username.strip().lower()
    existing_username = await db.scalar(select(User).where(User.username == username))
    if existing_username:
        raise UsernameAlreadyTaken()

    user = User(
        email=email,
        username=username,
        password_hash=hash_password(password),
        role="student",
        email_verified=False,
        display_name=display_name,
        date_of_birth=date_of_birth,
        country=country,
        gender=gender,
        gender_self_describe=None,
        avatar_url=avatar_url,
        social_links=social_links,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_email_token(email, purpose="verify")
    from app.modules.auth.tasks import send_verification_email

    send_verification_email.delay(email, token)

    return user


async def is_username_available(
    db: AsyncSession,
    username: str,
    *,
    exclude_user_id: uuid.UUID | None = None,
) -> bool:
    """Return whether a normalized username is free to claim."""
    stmt = select(User).where(User.username == username)
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    existing = await db.scalar(stmt)
    return existing is None


async def verify_email(db: AsyncSession, token: str) -> None:
    """Mark a user's email as verified using a signed email token.

    Args:
        db: Async database session.
        token: Signed token from the verification email link.

    Raises:
        TokenExpired: If the token is older than 24 hours.
        TokenInvalid: If the token signature is invalid or no matching user exists.
    """
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
    """Authenticate a user and issue an access token plus a refresh-token cookie.

    Args:
        db: Async database session.
        email: The user's registered email address.
        password: The plain-text password to verify.
        response: Starlette ``Response`` object used to set the ``refresh_token`` cookie.

    Returns:
        A tuple of ``(access_token_string, user)``.

    Raises:
        InvalidCredentials: If the email is not found or the password is wrong.
        EmailNotVerified: If the account has not been email-verified yet.
    """
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
    """Rotate a refresh token and issue a new access token.

    Implements refresh-token rotation: the presented session is revoked and a
    new session is created.  If the presented token belongs to an already-revoked
    session, all sessions for that user are revoked (replay-attack mitigation).

    Args:
        db: Async database session.
        raw_refresh: The raw refresh token read from the ``refresh_token`` cookie.
        response: Starlette ``Response`` used to set the new ``refresh_token`` cookie.

    Returns:
        A new JWT access token string.

    Raises:
        TokenInvalid: If no session matches the token hash or the user no longer exists.
        RefreshTokenReplayed: If the token belongs to an already-revoked session.
        TokenExpired: If the session has passed its ``expires_at`` timestamp.
    """
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
    """Revoke the current refresh-token session and delete the cookie.

    Args:
        db: Async database session.
        raw_refresh: The raw refresh token from the ``refresh_token`` cookie.
        response: Starlette ``Response`` used to delete the cookie.
    """
    token_hash = hash_refresh_token(raw_refresh)
    session = await db.scalar(select(Session).where(Session.refresh_token_hash == token_hash))
    if session and not session.revoked_at:
        session.revoked_at = datetime.now(UTC)
        await db.commit()
    response.delete_cookie("refresh_token")


async def forgot_password(db: AsyncSession, email: str) -> None:
    """Send a password-reset email if the address belongs to a registered account.

    Intentionally silent when the email is not found to prevent user enumeration.

    Args:
        db: Async database session.
        email: The email address of the account to reset.
    """
    user = await db.scalar(select(User).where(User.email == email))
    if not user:
        return  # Silent — no email enumeration

    token = create_email_token(email, purpose="reset")
    from app.modules.auth.tasks import send_password_reset_email

    send_password_reset_email.delay(email, token)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    """Reset a user's password and revoke all active sessions.

    Args:
        db: Async database session.
        token: Signed password-reset token from the email link (valid for 1 hour).
        new_password: The new plain-text password to store as a bcrypt hash.

    Raises:
        TokenExpired: If the token is older than 1 hour.
        TokenInvalid: If the token signature is invalid or the user no longer exists.
    """
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
    """Link an OAuth identity to an application account, creating one if necessary.

    Looks up an existing ``OAuthAccount`` by provider and provider-side user ID.
    If none is found, the function checks for an existing user with the same email
    (linking accounts) or creates a brand-new student account.  In all cases the
    user's email is marked verified and a fresh refresh-token session is issued.

    Args:
        db: Async database session.
        provider: OAuth provider name (e.g. ``"google"``).
        provider_user_id: The user's unique ID on the provider's platform (``sub``).
        email: Verified email address returned by the provider.
        display_name: Optional display name from the provider's user-info payload.
        access_token_enc: Optional provider access token to store for future API calls.
        response: Starlette ``Response`` used to set the ``refresh_token`` cookie.

    Returns:
        A tuple of ``(access_token_string, user)``.

    Raises:
        TokenInvalid: If an ``OAuthAccount`` exists but the linked user row is missing.
    """
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
            user = User(
                email=email,
                username=await generate_unique_username(db, email=email, display_name=display_name),
                role="student",
                email_verified=True,
                display_name=display_name or email.split("@")[0],
            )
            db.add(user)
            await db.flush()  # Populate user.id before referencing it in OAuthAccount
        else:
            user.email_verified = True
            if not user.username:
                user.username = await generate_unique_username(
                    db,
                    email=user.email,
                    display_name=user.display_name,
                )

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
    """Attach a ``refresh_token`` HttpOnly cookie to the outgoing response.

    Cookie flags are environment-aware: ``Secure`` is set only in production.
    The path is scoped to ``/api/v1/auth`` so the browser never sends the token
    to other API routes.

    Args:
        response: Starlette ``Response`` to mutate.
        token: The raw (un-hashed) refresh token string.
    """
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
    """Re-send the email-verification link for an unverified account.

    Silently returns without sending if the email is not registered or the
    account is already verified, preventing user enumeration.

    Args:
        db: Async database session.
        email: The email address of the account to re-verify.
    """
    user = await db.scalar(select(User).where(User.email == email))
    if not user or user.email_verified:
        return  # Silent

    token = create_email_token(email, purpose="verify")
    from app.modules.auth.tasks import send_verification_email

    send_verification_email.delay(email, token)
