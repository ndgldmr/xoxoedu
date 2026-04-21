import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import RegisterRequest
from app.modules.users.schemas import UserUpdateIn


def test_register_rejects_short_password() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="a@b.com",
            username="alice",
            password="short",
            display_name="Alice",
        )


def test_register_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="not-an-email",
            username="alice",
            password="validpassword",
            display_name="Alice",
        )


def test_register_rejects_empty_display_name() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="a@b.com",
            username="alice",
            password="validpassword",
            display_name="",
        )


def test_register_rejects_invalid_username_characters() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="a@b.com",
            username="alice-smith",
            password="validpassword",
            display_name="Alice",
        )


def test_register_normalizes_username_case() -> None:
    req = RegisterRequest(
        email="alice@example.com",
        username=" Alice_123 ",
        password="securepass",
        display_name="Alice",
    )
    assert req.username == "alice_123"


def test_register_valid() -> None:
    req = RegisterRequest(
        email="alice@example.com",
        username="alice",
        password="securepass",
        display_name="Alice",
    )
    assert req.email == "alice@example.com"


def test_user_update_partial_fields() -> None:
    update = UserUpdateIn(display_name="New Name")
    assert update.display_name == "New Name"
    assert update.bio is None
    assert update.headline is None


def test_user_update_all_none() -> None:
    update = UserUpdateIn()
    assert update.model_dump(exclude_none=True) == {}
