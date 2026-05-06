"""FastAPI router for authentication endpoints: registration, login, token management, and OAuth."""

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import ok
from app.core.storage import generate_presigned_put, get_public_url
from app.db.session import get_db
from app.modules.auth import service
from app.modules.auth.oauth import google_get_token, google_redirect
from app.modules.auth.schemas import (
    AvatarUploadOut,
    AvatarUploadRequestIn,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    RegisterOptionsOut,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
    UsernameAvailabilityOut,
    UsernameAvailabilityQuery,
    build_register_options,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Register a new student account and dispatch an email-verification link."""
    social_links = (
        body.social_links.model_dump(mode="json", exclude_none=True)
        if body.social_links is not None
        else None
    )
    user = await service.register(
        db,
        body.email,
        body.username,
        body.password,
        body.display_name,
        body.date_of_birth,
        body.country,
        body.gender,
        body.avatar_url,
        social_links,
    )
    return ok(UserOut.model_validate(user).model_dump())


@router.get("/register-options")
async def get_register_options() -> dict:
    """Return backend-owned WC-03 registration reference data."""
    data: RegisterOptionsOut = build_register_options()
    return ok(data.model_dump())


@router.get("/username-availability")
async def username_availability(
    query: Annotated[UsernameAvailabilityQuery, Depends()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return whether a candidate username is available."""
    available = await service.is_username_available(db, query.username)
    return ok(UsernameAvailabilityOut(available=available, username=query.username).model_dump())


@router.post("/avatar/upload-url", status_code=201)
async def request_avatar_upload(body: AvatarUploadRequestIn) -> dict:
    """Return a presigned PUT URL and public URL for a registration avatar."""
    ext = os.path.splitext(body.file_name)[-1].lstrip(".")
    key = f"avatars/{uuid.uuid4()}.{ext}" if ext else f"avatars/{uuid.uuid4()}"
    upload_url = generate_presigned_put(key, body.mime_type)
    public_url = get_public_url(key)
    return ok(AvatarUploadOut(upload_url=upload_url, public_url=public_url).model_dump())


@router.post("/resend-verification", status_code=202)
async def resend_verification(
    body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Re-send the email-verification link for an unverified account."""
    await service.resend_verification(db, body.email)
    return ok({"message": "If that email exists and is unverified, a new link has been sent."})


@router.get("/verify-email/{token}")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Mark the email address associated with a signed token as verified."""
    await service.verify_email(db, token)
    return ok({"message": "Email verified successfully."})


@router.post("/login")
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """Authenticate with email and password, returning tokens and user data."""
    access_token, user = await service.login(db, body.email, body.password, response)
    token_resp = TokenResponse(
        access_token=access_token,
        expires_in=15 * 60,
    )
    return ok({**token_resp.model_dump(), "user": UserOut.model_validate(user).model_dump()})


@router.post("/refresh")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """Rotate the refresh-token cookie and issue a new short-lived access token."""
    from app.core.exceptions import TokenInvalid

    raw = request.cookies.get("refresh_token")
    if not raw:
        raise TokenInvalid()
    access_token = await service.refresh_token(db, raw, response)
    return ok(TokenResponse(access_token=access_token, expires_in=15 * 60).model_dump())


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    """Revoke the current refresh-token session and delete the cookie."""
    raw = request.cookies.get("refresh_token")
    if raw:
        await service.logout(db, raw, response)


@router.post("/forgot-password", status_code=202)
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Dispatch a password-reset email if the address belongs to a registered account."""
    await service.forgot_password(db, body.email)
    return ok({"message": "If that email is registered, a reset link has been sent."})


@router.post("/reset-password/{token}")
async def reset_password(
    token: str, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Apply a new password using a signed, 1-hour reset token and revoke all sessions."""
    await service.reset_password(db, token, body.password)
    return ok({"message": "Password reset successfully."})


@router.get("/google")
async def google_login(request: Request) -> Response:
    """Redirect the browser to Google's OAuth consent screen."""
    return await google_redirect(request)


@router.get("/google/callback")
async def google_callback(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    """Handle the Google OAuth callback, set session cookie, and redirect to frontend."""
    try:
        token = await google_get_token(request)
        userinfo = token.get("userinfo", {})

        _access_token, _user = await service.get_or_create_oauth_user(
            db=db,
            provider="google",
            provider_user_id=str(userinfo["sub"]),
            email=str(userinfo["email"]),
            display_name=userinfo.get("name"),
            access_token_enc=token.get("access_token"),
            response=response,
        )
    except Exception:
        return RedirectResponse(url="/login?oauth=error", status_code=302)

    redirect = RedirectResponse(url="/login?oauth=success", status_code=302)
    # Forward any Set-Cookie headers placed on the injected response (e.g. refresh_token).
    for header_value in response.headers.getlist("set-cookie"):
        redirect.headers.append("set-cookie", header_value)
    return redirect
