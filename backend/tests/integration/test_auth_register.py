from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient) -> None:
    with patch("app.modules.auth.tasks.send_verification_email.delay") as mock_task:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "username": "newuser",
                "password": "securepass",
                "display_name": "New",
            },
        )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["email"] == "newuser@example.com"
    assert data["username"] == "newuser"
    assert data["email_verified"] is False
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient) -> None:
    with patch("app.modules.auth.tasks.send_verification_email.delay"):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "dup@example.com",
                "username": "dup",
                "password": "securepass",
                "display_name": "Dup",
            },
        )
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "dup@example.com",
                "username": "dup_2",
                "password": "securepass",
                "display_name": "Dup 2",
            },
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient) -> None:
    with patch("app.modules.auth.tasks.send_verification_email.delay"):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "first-username@example.com",
                "username": "taken_name",
                "password": "securepass",
                "display_name": "First",
            },
        )
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "second-username@example.com",
                "username": "taken_name",
                "password": "securepass",
                "display_name": "Second",
            },
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "USERNAME_ALREADY_TAKEN"


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "a@b.com",
            "username": "shortpass",
            "password": "short",
            "display_name": "A",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_blocked_before_verification(client: AsyncClient) -> None:
    with patch("app.modules.auth.tasks.send_verification_email.delay"):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "unverified@example.com",
                "username": "unverified",
                "password": "securepass",
                "display_name": "U",
            },
        )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "unverified@example.com", "password": "securepass"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"
