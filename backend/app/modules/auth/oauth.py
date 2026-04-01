"""Authlib-backed helpers for the Google OAuth 2.0 + OIDC flow."""

from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.config import settings

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile",
        "code_challenge_method": "S256",
    },
)


async def google_redirect(request: Request) -> RedirectResponse:
    """Build and return a redirect response to Google's OAuth consent screen.

    Uses PKCE (``S256`` code challenge) for added security on the authorization
    code flow.

    Args:
        request: The incoming Starlette request, used to store the OAuth state.

    Returns:
        A ``RedirectResponse`` pointing to Google's authorization endpoint.
    """
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)  # type: ignore[no-any-return]


async def google_get_token(request: Request) -> dict:
    """Exchange the authorization code for a token bundle including user-info.

    Args:
        request: The incoming callback request carrying the ``code`` and ``state``
            query parameters set by Google.

    Returns:
        A dict containing at minimum ``access_token`` and ``userinfo`` keys as
        populated by Authlib's ``authorize_access_token`` helper.
    """
    token: dict = await oauth.google.authorize_access_token(request)
    return token
