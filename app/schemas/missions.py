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
    re_auth_login_method: str | None = Field(
        default=None,
        description="When state is re_auth_required, login method from the user session (verify).",
    )
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
    re_auth_app_package: str | None = Field(
        default=None,
        description="When state is re_auth_required, app that needs re-login (first such task).",
    )
    re_auth_login_method: str | None = Field(
        default=None,
        description="When state is re_auth_required, login method from that app's UserSession.",
    )
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
