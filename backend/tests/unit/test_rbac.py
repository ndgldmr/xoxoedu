import uuid

import pytest

from app.core.exceptions import Forbidden
from app.core.rbac import Role
from app.db.models.user import User


def _make_user(role: str) -> User:
    u = User()
    u.id = uuid.uuid4()
    u.role = role
    u.email_verified = True
    return u


@pytest.mark.asyncio
async def test_require_role_admin_allows_admin() -> None:
    from app.core.rbac import require_role

    user = _make_user("admin")
    # Extract the inner dependency function
    dep = require_role(Role.ADMIN)
    inner = dep.dependency
    result = await inner(current_user=user)
    assert result is user


@pytest.mark.asyncio
async def test_require_role_admin_rejects_student() -> None:
    from app.core.rbac import require_role

    user = _make_user("student")
    dep = require_role(Role.ADMIN)
    inner = dep.dependency
    with pytest.raises(Forbidden):
        await inner(current_user=user)


@pytest.mark.asyncio
async def test_require_role_multiple_allows_both() -> None:
    from app.core.rbac import require_role

    dep = require_role(Role.STUDENT, Role.ADMIN)
    inner = dep.dependency

    student = _make_user("student")
    admin = _make_user("admin")

    assert await inner(current_user=student) is student
    assert await inner(current_user=admin) is admin
