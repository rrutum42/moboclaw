from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class VerifySessionRequest(BaseModel):
    login_method: Literal["otp", "sso", "password"] | None = None
    snapshot_id: str | None = None


class SessionEntry(BaseModel):
    session_id: int
    app_package: str
    snapshot_id: str | None
    health: str
    last_verified_at: datetime | None
    last_access_at: datetime | None
    login_method: str
    tier: str
    re_auth_required: bool


class SessionsListResponse(BaseModel):
    user_id: str
    sessions: list[SessionEntry]


class VerifySessionResponse(BaseModel):
    session_id: int
    observed: str
    health: str
    tier: str
    re_auth_required: bool


class HealthHistoryItem(BaseModel):
    checked_at: datetime
    observed: str
    detail: str | None


class HealthHistoryResponse(BaseModel):
    user_id: str
    app_package: str
    events: list[HealthHistoryItem]
