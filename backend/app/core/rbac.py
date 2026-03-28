from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import Depends

if TYPE_CHECKING:
    from app.db.models.user import User


class Role(StrEnum):
    STUDENT = "student"
    ADMIN = "admin"


def require_role(*roles: Role) -> "User":
    from app.dependencies import get_current_verified_user

    async def dependency(current_user: "User" = Depends(get_current_verified_user)) -> "User":
        from app.core.exceptions import Forbidden

        if current_user.role not in [r.value for r in roles]:
            raise Forbidden()
        return current_user

    return Depends(dependency)
