import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import RegisterRequest
from app.modules.users.schemas import UserUpdateIn


def _register_payload() -> dict:
    return {
        "email": "alice@example.com",
        "username": "alice",
        "password": "securepass",
        "display_name": "Alice",
        "date_of_birth": "2000-01-02",
        "country": "BR",
        "gender": "female",
        "avatar_url": "https://cdn.example.com/avatar.png",
    }


def test_register_rejects_short_password() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(**{**_register_payload(), "password": "short"})


def test_register_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(**{**_register_payload(), "email": "not-an-email"})


def test_register_rejects_empty_display_name() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(**{**_register_payload(), "display_name": ""})


def test_register_rejects_invalid_username_characters() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(**{**_register_payload(), "username": "alice-smith"})


def test_register_normalizes_username_case() -> None:
    req = RegisterRequest(**{**_register_payload(), "username": " Alice_123 "})
    assert req.username == "alice_123"


def test_register_valid() -> None:
    req = RegisterRequest(**_register_payload())
    assert req.email == "alice@example.com"


def test_register_rejects_future_date_of_birth() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(**{**_register_payload(), "date_of_birth": "2999-01-01"})


def test_register_rejects_legacy_self_describe_gender() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(**{**_register_payload(), "gender": "self_describe"})


def test_register_accepts_other_gender() -> None:
    req = RegisterRequest(**{**_register_payload(), "gender": "other"})
    assert req.gender == "other"


def test_register_rejects_unsupported_country() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(**{**_register_payload(), "country": "US"})


def test_user_update_partial_fields() -> None:
    update = UserUpdateIn(display_name="New Name")
    assert update.display_name == "New Name"
    assert update.bio is None
    assert update.headline is None


def test_user_update_all_none() -> None:
    update = UserUpdateIn()
    assert update.model_dump(exclude_none=True) == {}


def test_user_update_normalizes_username_and_country() -> None:
    update = UserUpdateIn(username=" Test_User ", country="br")
    assert update.username == "test_user"
    assert update.country == "BR"
