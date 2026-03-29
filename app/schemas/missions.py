from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MissionTarget(BaseModel):
    app_package: str = Field(..., min_length=1)
    goal: str = Field(..., min_length=1)


class CreateMissionRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    targets: list[MissionTarget] = Field(..., min_length=1)
    webhook_url: str | None = None


class MissionTaskOut(BaseModel):
    task_id: str
    sequence: int
    app_package: str
    goal: str
    state: str
    emulator_id: str | None = None
    error_message: str | None = None
    identity_gate_notified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MissionDetailResponse(BaseModel):
    mission_id: str
    user_id: str
    state: str
    webhook_url: str | None = None
    error_detail: str | None = None
    tasks: list[MissionTaskOut]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": False}


class CreateMissionResponse(BaseModel):
    mission_id: str
    user_id: str
    state: str
    tasks: list[MissionTaskOut]
    created_at: datetime
    updated_at: datetime


class ApproveMissionTaskResponse(BaseModel):
    mission_id: str
    task_id: str
    state: str
    message: str
