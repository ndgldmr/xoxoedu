"""Application configuration loaded from environment variables and .env file."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object populated by pydantic-settings from the environment.

    All fields without defaults are required at startup. The JWT key fields
    accept ``\\n``-escaped newlines so they can be stored as single-line
    environment variables.

    Attributes:
        DATABASE_URL: Async SQLAlchemy connection string (asyncpg driver).
        DATABASE_URL_SYNC: Sync SQLAlchemy connection string (psycopg2 driver).
        REDIS_URL: Redis broker/backend URL for Celery.
        JWT_PRIVATE_KEY: RS256 private key for signing access tokens.
        JWT_PUBLIC_KEY: RS256 public key for verifying access tokens.
        JWT_ALGORITHM: JWT signing algorithm, defaults to ``RS256``.
        ACCESS_TOKEN_EXPIRE_MINUTES: Access-token TTL in minutes (default 15).
        REFRESH_TOKEN_EXPIRE_DAYS: Refresh-token TTL in days (default 30).
        SECRET_KEY: HMAC secret used for signed email tokens and session cookies.
        GOOGLE_CLIENT_ID: Google OAuth2 application client ID.
        GOOGLE_CLIENT_SECRET: Google OAuth2 application client secret.
        GOOGLE_REDIRECT_URI: Callback URI registered in Google Cloud Console.
        RESEND_API_KEY: API key for the Resend transactional email service.
        EMAIL_FROM: Sender address for all outbound email.
        FRONTEND_URL: Public URL of the frontend (used in email links).
        ENVIRONMENT: Deployment stage; ``"production"`` enables stricter settings.
        ALLOWED_ORIGINS: CORS allow-list for browser clients.
    """
    # Database
    DATABASE_URL: str
    DATABASE_URL_SYNC: str

    # Redis
    REDIS_URL: str

    # JWT
    JWT_PRIVATE_KEY: str
    JWT_PUBLIC_KEY: str
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Auth
    SECRET_KEY: str

    # Google OAuth2
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    # Resend
    RESEND_API_KEY: str
    EMAIL_FROM: str = "noreply@xoxoedu.com"

    # App
    FRONTEND_URL: str = "http://localhost:3000"
    ENVIRONMENT: str = "development"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    @field_validator("JWT_PRIVATE_KEY", "JWT_PUBLIC_KEY", mode="before")
    @classmethod
    def unescape_newlines(cls, v: str) -> str:
        """Expand ``\\n`` escape sequences so PEM keys stored as env vars work correctly.

        Args:
            v: Raw field value from the environment.

        Returns:
            The value with ``\\n`` replaced by real newline characters.
        """
        return v.replace("\\n", "\n")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
