import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import ok
from app.db.session import get_db
from app.dependencies import get_current_verified_user
from app.modules.auth.schemas import UserOut
from app.modules.users import service
from app.modules.users.schemas import SessionOut, UserUpdateIn

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(user=Depends(get_current_verified_user)) -> dict:
    return ok(UserOut.model_validate(user).model_dump())


@router.patch("/me")
async def update_me(
    body: UserUpdateIn,
    user=Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    updated = await service.update_me(db, user, body)
    return ok(UserOut.model_validate(updated).model_dump())


@router.get("/me/sessions")
async def list_sessions(
    user=Depends(get_current_verified_user), db: AsyncSession = Depends(get_db)
) -> dict:
    sessions = await service.list_sessions(db, user.id)
    return ok([SessionOut.model_validate(s).model_dump() for s in sessions])


@router.delete("/me/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: uuid.UUID,
    user=Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.revoke_session(db, user, session_id)
