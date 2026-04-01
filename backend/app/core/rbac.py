"""Role-based access control helpers for FastAPI dependency injection."""

from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import Depends

if TYPE_CHECKING:
    from app.db.models.user import User


class Role(StrEnum):
    """Enumeration of valid user roles stored in the ``users.role`` column."""

    STUDENT = "student"
    ADMIN = "admin"


def require_role(*roles: Role) -> "User":
    """Return a FastAPI ``Depends`` that enforces role membership.

    The returned dependency first validates the Bearer token via
    ``get_current_verified_user``, then checks that the user's role is among
    the ones passed to this factory.  FastAPI deduplicates identical
    dependencies within a single request, so calling ``require_role(Role.ADMIN)``
    both in router-level ``dependencies=`` and as a parameter of an individual
    route handler is safe and free.

    Args:
        *roles: One or more ``Role`` values the caller must have.

    Returns:
        A ``Depends`` object that resolves to the authenticated ``User`` if
        they hold an allowed role.

    Raises:
        Forbidden: If the authenticated user's role is not in *roles*.
    """
    from app.dependencies import get_current_verified_user

    async def dependency(current_user: "User" = Depends(get_current_verified_user)) -> "User":
        """Validate the current user's role against the allowed set.

        Args:
            current_user: The authenticated, email-verified user.

        Returns:
            The user if their role is permitted.

        Raises:
            Forbidden: If the user's role is not in the allowed set.
        """
        from app.core.exceptions import Forbidden

        if current_user.role not in [r.value for r in roles]:
            raise Forbidden()
        return current_user

    return Depends(dependency)
