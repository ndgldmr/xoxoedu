from pydantic import BaseModel

from app.core.rbac import Role


class RoleUpdateIn(BaseModel):
    role: Role
