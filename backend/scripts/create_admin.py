#!/usr/bin/env python3
"""
Create the first admin user.

Usage:
    uv run scripts/create_admin.py admin@example.com secretpassword
"""
import asyncio
import sys
from pathlib import Path

# Ensure the backend package is importable when run from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main(email: str, password: str) -> None:
    """Create a new admin user or promote an existing user to the admin role.

    If a user with *email* already exists and is already an admin, the script
    exits without making any changes.  If the user exists but has a different
    role, their role is updated to ``"admin"``.  Otherwise, a brand-new
    email-verified admin account is created with a bcrypt-hashed password and
    a default display name derived from the email address.

    Args:
        email: Email address of the admin account to create or promote.
        password: Plain-text password to store as a bcrypt hash (only used when
            creating a new account; ignored when promoting an existing user).
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.core.security import hash_password
    from app.db.models.user import User

    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing:
            if existing.role == "admin":
                print(f"[!] {email} is already an admin.")
            else:
                existing.role = "admin"
                await db.commit()
                print(f"[+] Promoted existing user {email} to admin.")
            await engine.dispose()
            return

        user = User(
            email=email,
            password_hash=hash_password(password),
            role="admin",
            email_verified=True,
            display_name=email.split("@")[0],
        )
        db.add(user)
        await db.commit()
        print(f"[+] Admin user created: {email}")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: uv run scripts/create_admin.py <email> <password>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
