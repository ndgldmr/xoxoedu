#!/usr/bin/env python3
"""Interactive .env setup script.

Reads an existing .env file and uses its values as prompt defaults, so
re-running the script does not overwrite anything unless you type a new value.

RSA keys and SECRET_KEY are only (re-)generated when they are absent from
the existing file.

Usage:
    uv run scripts/setup_env.py
"""
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENV_FILE = ROOT / ".env"


def _parse_env(path: Path) -> dict[str, str]:
    """Parse a .env file into a key → value dict.

    Lines that are blank or start with ``#`` are skipped.  Inline comments
    are not stripped — the raw value (including surrounding quotes) is kept
    so it can be written back verbatim.

    Args:
        path: Path to the ``.env`` file to parse.

    Returns:
        A dict mapping variable names to their raw string values.
    """
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def _generate_rsa_keypair() -> tuple[str, str]:
    """Generate an RSA-2048 keypair formatted for single-line .env storage.

    Returns:
        A ``(private_pem, public_pem)`` tuple with newlines escaped to
        ``\\n`` so each value fits on a single ``.env`` line.
    """
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


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    """Display an interactive prompt and return the user's input.

    Pressing Enter without typing anything returns *default* unchanged.
    When *secret* is ``True``, ``getpass`` is used so input is not echoed.

    Args:
        label: Human-readable prompt label.
        default: Value returned when the user submits an empty string.
        secret: When ``True``, hide the typed input.

    Returns:
        The trimmed user input, or *default* if the input was empty.
    """
    # Truncate long defaults (e.g. PEM keys) so they don't flood the terminal
    display_default = default
    if default and len(default) > 40:
        display_default = default[:20] + "…" + default[-8:]

    display = f"  {label}"
    if display_default:
        display += f" [{display_default}]"
    display += ": "

    if secret:
        import getpass
        value = getpass.getpass(display)
    else:
        value = input(display)

    return value.strip() or default


def main() -> None:
    """Run the interactive environment setup wizard and write a ``.env`` file.

    Reads any existing ``.env`` and uses its values as defaults.  Only fields
    that are absent (or explicitly overwritten by the user) are changed.
    RSA keys and ``SECRET_KEY`` are generated only when not already present.
    """
    print("\nxoxo Education — Environment Setup\n" + "=" * 36)

    # Load existing values so they become prompt defaults
    existing: dict[str, str] = {}
    if ENV_FILE.exists():
        existing = _parse_env(ENV_FILE)
        print(f"\nFound existing .env at {ENV_FILE}")
        print("  Press Enter at any prompt to keep the current value.\n")
    else:
        print("\nNo .env found — creating a new one.\n")

    # ── JWT keys ───────────────────────────────────────────────────────────────
    private_key = existing.get("JWT_PRIVATE_KEY", "").strip('"')
    public_key = existing.get("JWT_PUBLIC_KEY", "").strip('"')

    if private_key and public_key:
        print("JWT RSA keypair: already present — keeping existing keys.")
    else:
        print("Generating RSA-2048 keypair for JWT signing...")
        private_key, public_key = _generate_rsa_keypair()
        print("  Done.")

    # ── Secret key ─────────────────────────────────────────────────────────────
    secret_key = existing.get("SECRET_KEY", "")
    if secret_key:
        print("SECRET_KEY: already present — keeping existing value.")
    else:
        secret_key = secrets.token_hex(32)
        print("SECRET_KEY generated.")

    # ── Database ───────────────────────────────────────────────────────────────
    print("\n--- Database (defaults work with docker compose up) ---")

    # Parse host/port/name/user/pass from existing DATABASE_URL if present
    _existing_url = existing.get("DATABASE_URL", "")
    _db_defaults = {"host": "localhost", "port": "5432", "name": "xoxoedu",
                    "user": "postgres", "pass": "postgres"}
    if _existing_url:
        # postgresql+asyncpg://user:pass@host:port/name
        try:
            import re
            m = re.match(
                r"postgresql(?:\+asyncpg)?://([^:]+):([^@]+)@([^:]+):(\d+)/(\S+)",
                _existing_url,
            )
            if m:
                _db_defaults = {
                    "user": m.group(1), "pass": m.group(2),
                    "host": m.group(3), "port": m.group(4), "name": m.group(5),
                }
        except Exception:
            pass

    db_host = _prompt("Postgres host", _db_defaults["host"])
    db_port = _prompt("Postgres port", _db_defaults["port"])
    db_name = _prompt("Postgres database name", _db_defaults["name"])
    db_user = _prompt("Postgres user", _db_defaults["user"])
    db_pass = _prompt("Postgres password", _db_defaults["pass"], secret=True)

    # ── Google OAuth2 ──────────────────────────────────────────────────────────
    print("\n--- Google OAuth2 ---")
    print("  Get these from console.cloud.google.com > APIs & Services > Credentials")
    google_client_id = _prompt(
        "GOOGLE_CLIENT_ID", existing.get("GOOGLE_CLIENT_ID", "")
    )
    google_client_secret = _prompt(
        "GOOGLE_CLIENT_SECRET", existing.get("GOOGLE_CLIENT_SECRET", ""), secret=True
    )
    google_redirect_uri = _prompt(
        "GOOGLE_REDIRECT_URI",
        existing.get(
            "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback"
        ),
    )

    # ── Resend ─────────────────────────────────────────────────────────────────
    print("\n--- Resend (email) ---")
    print("  Get your API key from resend.com/api-keys")
    resend_api_key = _prompt(
        "RESEND_API_KEY", existing.get("RESEND_API_KEY", ""), secret=True
    )
    email_from = _prompt(
        "EMAIL_FROM (must be a verified Resend domain)",
        existing.get("EMAIL_FROM", "noreply@xoxoedu.com"),
    )

    # ── Object storage (R2 / MinIO) ────────────────────────────────────────────
    print("\n--- Object storage (Cloudflare R2 in production, MinIO locally) ---")
    print("  Local dev:  leave R2_ENDPOINT_URL as http://localhost:9000 and use")
    print("              minioadmin credentials — docker compose starts MinIO for you.")
    print("  Production: clear R2_ENDPOINT_URL and fill in your R2 credentials.")
    print("              Create an API token at dash.cloudflare.com > R2 > Manage R2 API Tokens")
    r2_endpoint_url = _prompt(
        "R2_ENDPOINT_URL (blank = derive from R2_ACCOUNT_ID for Cloudflare R2)",
        existing.get("R2_ENDPOINT_URL", "http://localhost:9000"),
    )
    r2_account_id = _prompt(
        "R2_ACCOUNT_ID (leave blank for local MinIO)", existing.get("R2_ACCOUNT_ID", "")
    )
    r2_access_key_id = _prompt(
        "R2_ACCESS_KEY_ID", existing.get("R2_ACCESS_KEY_ID", "minioadmin"), secret=True
    )
    r2_secret_access_key = _prompt(
        "R2_SECRET_ACCESS_KEY", existing.get("R2_SECRET_ACCESS_KEY", "minioadmin"), secret=True
    )
    r2_bucket = _prompt(
        "R2_BUCKET", existing.get("R2_BUCKET", "xoxoedu-uploads")
    )
    r2_public_url = _prompt(
        "R2_PUBLIC_URL (local: http://localhost:9000/xoxoedu-uploads, prod: https://assets.xoxoedu.com)",
        existing.get("R2_PUBLIC_URL", "http://localhost:9000/xoxoedu-uploads"),
    )

    # ── App ────────────────────────────────────────────────────────────────────
    print("\n--- App ---")
    frontend_url = _prompt(
        "FRONTEND_URL", existing.get("FRONTEND_URL", "http://localhost:3000")
    )

    # ── Build DATABASE_URL ─────────────────────────────────────────────────────
    database_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    database_url_sync = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

    # ── Write .env ─────────────────────────────────────────────────────────────
    env_content = f"""\
# Database
DATABASE_URL={database_url}
DATABASE_URL_SYNC={database_url_sync}

# Redis
REDIS_URL={existing.get("REDIS_URL", "redis://localhost:6379/0")}

# JWT — generated by scripts/setup_env.py
# Store PEM keys with literal \\n (not actual newlines)
JWT_PRIVATE_KEY="{private_key}"
JWT_PUBLIC_KEY="{public_key}"
JWT_ALGORITHM=RS256
ACCESS_TOKEN_EXPIRE_MINUTES={existing.get("ACCESS_TOKEN_EXPIRE_MINUTES", "15")}
REFRESH_TOKEN_EXPIRE_DAYS={existing.get("REFRESH_TOKEN_EXPIRE_DAYS", "30")}

# Auth — 32-byte hex string
SECRET_KEY={secret_key}

# Google OAuth2
GOOGLE_CLIENT_ID={google_client_id}
GOOGLE_CLIENT_SECRET={google_client_secret}
GOOGLE_REDIRECT_URI={google_redirect_uri}

# Resend (email)
RESEND_API_KEY={resend_api_key}
EMAIL_FROM={email_from}

# Object storage (S3-compatible — MinIO locally, Cloudflare R2 in production)
# Local dev: R2_ENDPOINT_URL=http://localhost:9000, credentials=minioadmin/minioadmin
# Production: clear R2_ENDPOINT_URL; endpoint is derived from R2_ACCOUNT_ID
R2_ENDPOINT_URL={r2_endpoint_url}
R2_ACCOUNT_ID={r2_account_id}
R2_ACCESS_KEY_ID={r2_access_key_id}
R2_SECRET_ACCESS_KEY={r2_secret_access_key}
R2_BUCKET={r2_bucket}
# Optional: custom public domain bound to the bucket (e.g. https://assets.xoxoedu.com)
R2_PUBLIC_URL={r2_public_url}

# App
FRONTEND_URL={frontend_url}
ENVIRONMENT={existing.get("ENVIRONMENT", "development")}
ALLOWED_ORIGINS={existing.get("ALLOWED_ORIGINS", '["http://localhost:3000"]')}
"""

    ENV_FILE.write_text(env_content)
    print(f"\n.env written to {ENV_FILE}")
    print("\nNext steps:")
    print("  docker compose up db redis minio -d")
    print("  uv run alembic upgrade head")
    print("  uv run uvicorn app.main:app --reload")
    print("  MinIO console: http://localhost:9001  (minioadmin / minioadmin)")


if __name__ == "__main__":
    main()
