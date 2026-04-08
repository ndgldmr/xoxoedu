"""FastAPI router for certificate endpoints."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.certificates import service
from app.modules.certificates.schemas import (
    CertificateOut,
    CertificateRequestOut,
    VerifyResponse,
)

router = APIRouter(tags=["certificates"])


@router.post("/certificates/generate", status_code=201)
async def generate_certificate(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Manually trigger certificate generation for a completed course."""
    cert = await service.generate(db, current_user.id, course_id)
    return ok(CertificateOut.model_validate(cert).model_dump())


@router.get("/certificates")
async def list_certificates(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Return all certificates earned by the authenticated student."""
    certs = await service.list_certificates(db, current_user.id)
    return ok([c.model_dump() for c in certs])


@router.get("/verify/{token}")
async def verify_certificate(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Public certificate verification — no authentication required."""
    result = await service.verify(db, token)
    return ok(VerifyResponse.model_validate(result).model_dump())


@router.post("/certificate-requests", status_code=201)
async def create_certificate_request(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Submit a manual certificate review request."""
    req = await service.create_request(db, current_user.id, course_id)
    return ok(CertificateRequestOut.model_validate(req).model_dump())
