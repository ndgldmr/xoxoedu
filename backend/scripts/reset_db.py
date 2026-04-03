#!/usr/bin/env python3
"""
Drop and recreate the database schema via Alembic migrations.

Usage:
    uv run scripts/reset_db.py
"""
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, cwd=BACKEND_DIR)
    if result.returncode != 0:
        sys.exit(result.returncode)


if __name__ == "__main__":
    print("[~] Downgrading to base...")
    run(["uv", "run", "alembic", "downgrade", "base"])
    print("[~] Upgrading to head...")
    run(["uv", "run", "alembic", "upgrade", "head"])
    print("[+] Database reset complete.")
