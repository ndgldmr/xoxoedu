#!/usr/bin/env python3
"""
Interactive .env setup script.

Generates RSA keys and secret key automatically.
Prompts for credentials that must come from external services.

Usage:
    uv run scripts/setup_env.py
"""
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


def generate_rsa_keypair() -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem.replace("\n", "\\n"), public_pem.replace("\n", "\\n")


def prompt(label: str, default: str = "", secret: bool = False) -> str:
    display = f"  {label}"
    if default:
        display += f" [{default}]"
    display += ": "

    if secret:
        import getpass
        value = getpass.getpass(display)
    else:
        value = input(display)

    return value.strip() or default


def main() -> None:
    print("\nxoxo Education — Environment Setup\n" + "=" * 36)

    if ENV_FILE.exists():
        overwrite = input("\n.env already exists. Overwrite? [y/N]: ").strip().lower()
        if overwrite != "y":
            print("Aborted.")
            sys.exit(0)

    print("\nGenerating RSA keypair for JWT signing...")
    private_key, public_key = generate_rsa_keypair()
    print("  Done.")

    secret_key = secrets.token_hex(32)
    print("  Secret key generated.")

    print("\n--- Database (defaults work with docker compose up) ---")
    db_host = prompt("Postgres host", "localhost")
    db_port = prompt("Postgres port", "5432")
    db_name = prompt("Postgres database name", "xoxoedu")
    db_user = prompt("Postgres user", "postgres")
    db_pass = prompt("Postgres password", "postgres")

    print("\n--- Google OAuth2 ---")
    print("  Get these from console.cloud.google.com > APIs & Services > Credentials")
    google_client_id = prompt("GOOGLE_CLIENT_ID")
    google_client_secret = prompt("GOOGLE_CLIENT_SECRET", secret=True)
    google_redirect_uri = prompt(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback"
    )

    print("\n--- Resend (email) ---")
    print("  Get your API key from resend.com/api-keys")
    resend_api_key = prompt("RESEND_API_KEY", secret=True)
    email_from = prompt("EMAIL_FROM (must be a verified Resend domain)", "noreply@xoxoedu.com")

    print("\n--- App ---")
    frontend_url = prompt("FRONTEND_URL", "http://localhost:3000")

    database_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    database_url_sync = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

    env_content = f"""\
# Database
DATABASE_URL={database_url}
DATABASE_URL_SYNC={database_url_sync}

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_PRIVATE_KEY="{private_key}"
JWT_PUBLIC_KEY="{public_key}"
JWT_ALGORITHM=RS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=30

# Auth
SECRET_KEY={secret_key}

# Google OAuth2
GOOGLE_CLIENT_ID={google_client_id}
GOOGLE_CLIENT_SECRET={google_client_secret}
GOOGLE_REDIRECT_URI={google_redirect_uri}

# Resend (email)
RESEND_API_KEY={resend_api_key}
EMAIL_FROM={email_from}

# App
FRONTEND_URL={frontend_url}
ENVIRONMENT=development
ALLOWED_ORIGINS=["http://localhost:3000"]
"""

    ENV_FILE.write_text(env_content)
    print(f"\n.env written to {ENV_FILE}")
    print("\nNext steps:")
    print("  docker compose up db redis -d")
    print("  uv run alembic upgrade head")
    print("  uv run uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
