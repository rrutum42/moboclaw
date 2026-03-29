from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException

log = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.deps import get_db
from app.schemas.sessions import (
    HealthHistoryResponse,
    SessionsListResponse,
    VerifySessionRequest,
    VerifySessionResponse,
)
from app.services import session_service

router = APIRouter(prefix="/users", tags=["sessions"])


@router.get("/{user_id}/sessions", response_model=SessionsListResponse)
async def list_user_sessions(
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> SessionsListResponse:
    return await session_service.list_sessions(db, user_id)


@router.post("/{user_id}/sessions/{app_package}/verify", response_model=VerifySessionResponse)
async def verify_user_session(
    user_id: str,
    app_package: str,
    db: AsyncSession = Depends(get_db),
    body: VerifySessionRequest | None = Body(None),
) -> VerifySessionResponse:
    return await session_service.verify_session(db, user_id, app_package, body)


@router.get("/{user_id}/sessions/{app_package}/health-history", response_model=HealthHistoryResponse)
async def session_health_history(
    user_id: str,
    app_package: str,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> HealthHistoryResponse:
    try:
        return await session_service.health_history(db, user_id, app_package, limit)
    except KeyError:
        log.warning(
            "health_history 404 user=%s app=%s",
            user_id,
            app_package,
        )
        raise HTTPException(status_code=404, detail="session not found") from None
