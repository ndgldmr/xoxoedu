from unittest.mock import patch

import pytest
from httpx import AsyncClient


def _register_payload(email: str, username: str, display_name: str) -> dict:
    return {
        "email": email,
        "username": username,
        "password": "securepass",
        "display_name": display_name,
        "date_of_birth": "2000-01-02",
        "country": "BR",
        "gender": "female",
        "avatar_url": "https://cdn.example.com/avatar.png",
        "social_links": {
            "linkedin": "https://www.linkedin.com/in/test-user",
        },
    }


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient) -> None:
    with patch("app.modules.auth.tasks.send_verification_email.delay") as mock_task:
        resp = await client.post(
            "/api/v1/auth/register",
            json=_register_payload("newuser@example.com", "newuser", "New"),
        )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["email"] == "newuser@example.com"
    assert data["username"] == "newuser"
    assert data["email_verified"] is False
    assert data["profile_complete"] is True
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient) -> None:
    with patch("app.modules.auth.tasks.send_verification_email.delay"):
        await client.post("/api/v1/auth/register", json=_register_payload("dup@example.com", "dup", "Dup"))
        resp = await client.post(
            "/api/v1/auth/register",
            json=_register_payload("dup@example.com", "dup_2", "Dup 2"),
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient) -> None:
    with patch("app.modules.auth.tasks.send_verification_email.delay"):
        await client.post(
            "/api/v1/auth/register",
            json=_register_payload("first-username@example.com", "taken_name", "First"),
        )
        resp = await client.post(
            "/api/v1/auth/register",
            json=_register_payload("second-username@example.com", "taken_name", "Second"),
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "USERNAME_ALREADY_TAKEN"


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={**_register_payload("a@b.com", "shortpass", "A"), "password": "short"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_blocked_before_verification(client: AsyncClient) -> None:
    with patch("app.modules.auth.tasks.send_verification_email.delay"):
        await client.post(
            "/api/v1/auth/register",
            json=_register_payload("unverified@example.com", "unverified", "U"),
        )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "unverified@example.com", "password": "securepass"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"


@pytest.mark.asyncio
async def test_username_availability_reports_taken_and_available(client: AsyncClient) -> None:
    with patch("app.modules.auth.tasks.send_verification_email.delay"):
        await client.post("/api/v1/auth/register", json=_register_payload("lookup@example.com", "lookup_name", "Lookup"))

    taken_resp = await client.get("/api/v1/auth/username-availability", params={"username": " lookup_name "})
    available_resp = await client.get("/api/v1/auth/username-availability", params={"username": "fresh_name"})

    assert taken_resp.status_code == 200
    assert taken_resp.json()["data"] == {"available": False, "username": "lookup_name"}
    assert available_resp.status_code == 200
    assert available_resp.json()["data"] == {"available": True, "username": "fresh_name"}


@pytest.mark.asyncio
async def test_register_options_returns_launch_countries(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/register-options")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "countries" in data
    assert {"code": "BR", "name": "Brazil"} in data["countries"]
    assert "other" in data["genders"]
    assert "self_describe" not in data["genders"]
    assert "linkedin" in data["social_link_keys"]


@pytest.mark.asyncio
async def test_avatar_upload_url_endpoint(client: AsyncClient) -> None:
    with patch("app.modules.auth.router.generate_presigned_put", return_value="https://upload.example.com/put"):
        with patch("app.modules.auth.router.get_public_url", return_value="https://cdn.example.com/avatar.png"):
            resp = await client.post(
                "/api/v1/auth/avatar/upload-url",
                json={
                    "file_name": "avatar.png",
                    "mime_type": "image/png",
                    "file_size": 1024,
                },
            )

    assert resp.status_code == 201
    assert resp.json()["data"] == {
        "upload_url": "https://upload.example.com/put",
        "public_url": "https://cdn.example.com/avatar.png",
    }
