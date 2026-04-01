"""Pydantic schemas for admin-only request bodies."""

from pydantic import BaseModel

from app.core.rbac import Role


class RoleUpdateIn(BaseModel):
    """Payload for ``PATCH /admin/users/{user_id}/role``."""

    role: Role
