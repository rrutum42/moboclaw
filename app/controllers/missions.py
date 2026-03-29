from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

log = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.deps import get_db
from app.schemas.missions import (
    ApproveMissionTaskResponse,
    CreateMissionRequest,
    CreateMissionResponse,
    MissionDetailResponse,
)
from app.services import mission_service

router = APIRouter(tags=["missions"])


@router.post("/missions", response_model=CreateMissionResponse)
async def create_mission(
    body: CreateMissionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CreateMissionResponse:
    resp = await mission_service.create_mission(db, body)
    background_tasks.add_task(mission_service.safe_run_mission, resp.mission_id)
    return resp


@router.get("/missions/{mission_id}", response_model=MissionDetailResponse)
async def get_mission(
    mission_id: str,
    db: AsyncSession = Depends(get_db),
) -> MissionDetailResponse:
    m = await mission_service.get_mission(db, mission_id)
    if m is None:
        log.warning("get_mission 404 id=%s", mission_id)
        raise HTTPException(status_code=404, detail="mission not found")
    return m


@router.post(
    "/missions/{mission_id}/tasks/{task_id}/approve",
    response_model=ApproveMissionTaskResponse,
)
async def approve_mission_task(
    mission_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApproveMissionTaskResponse:
    return await mission_service.approve_identity_gate(db, mission_id, task_id)
