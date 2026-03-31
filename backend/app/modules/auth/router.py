
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import ok
from app.db.session import get_db
from app.modules.auth import service
from app.modules.auth.oauth import google_get_token, google_redirect
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> dict:
    user = await service.register(db, body.email, body.password, body.display_name)
    return ok(UserOut.model_validate(user).model_dump())


@router.post("/resend-verification", status_code=202)
async def resend_verification(
    body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    await service.resend_verification(db, body.email)
    return ok({"message": "If that email exists and is unverified, a new link has been sent."})


@router.get("/verify-email/{token}")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)) -> dict:
    await service.verify_email(db, token)
    return ok({"message": "Email verified successfully."})


@router.post("/login")
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    access_token, user = await service.login(db, body.email, body.password, response)
    token_resp = TokenResponse(
        access_token=access_token,
        expires_in=15 * 60,
    )
    return ok({**token_resp.model_dump(), "user": UserOut.model_validate(user).model_dump()})


@router.post("/refresh")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    from app.core.exceptions import TokenInvalid

    raw = request.cookies.get("refresh_token")
    if not raw:
        raise TokenInvalid()
    access_token = await service.refresh_token(db, raw, response)
    return ok(TokenResponse(access_token=access_token, expires_in=15 * 60).model_dump())


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    raw = request.cookies.get("refresh_token")
    if raw:
        await service.logout(db, raw, response)


@router.post("/forgot-password", status_code=202)
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict:
    await service.forgot_password(db, body.email)
    return ok({"message": "If that email is registered, a reset link has been sent."})


@router.post("/reset-password/{token}")
async def reset_password(
    token: str, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    await service.reset_password(db, token, body.password)
    return ok({"message": "Password reset successfully."})


@router.get("/google")
async def google_login(request: Request) -> Response:
    return await google_redirect(request)


@router.get("/google/callback")
async def google_callback(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> dict:
    token = await google_get_token(request)
    userinfo = token.get("userinfo", {})

    access_token, user = await service.get_or_create_oauth_user(
        db=db,
        provider="google",
        provider_user_id=str(userinfo["sub"]),
        email=str(userinfo["email"]),
        display_name=userinfo.get("name"),
        access_token_enc=token.get("access_token"),
        response=response,
    )
    token_resp = TokenResponse(access_token=access_token, expires_in=15 * 60)
    return ok({**token_resp.model_dump(), "user": UserOut.model_validate(user).model_dump()})
