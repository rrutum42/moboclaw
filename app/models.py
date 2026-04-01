from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EmulatorState(str, Enum):
    CREATING = "CREATING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SNAPSHOTTING = "SNAPSHOTTING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    DESTROYED = "DESTROYED"


class SnapshotLayer(str, Enum):
    BASE = "base"
    APP = "app"
    SESSION = "session"


class EmulatorStatusResponse(BaseModel):
    id: str
    state: EmulatorState
    current_snapshot_id: str | None = None
    assigned: bool = False
    pool_role: str = "none"
    last_boot_seconds: float | None = None
    health_ok: bool = True
    consecutive_health_failures: int = 0
    message: str | None = None
    # Set when EMULATOR_BACKEND=sdk (adb serial, e.g. emulator-5554).
    adb_serial: str | None = None


class ProvisionEmulatorRequest(BaseModel):
    snapshot_id: str | None = None


class ProvisionEmulatorResponse(BaseModel):
    id: str
    state: EmulatorState
    restored_snapshot_id: str | None
    boot_seconds: float


class CreateSnapshotRequest(BaseModel):
    layer: SnapshotLayer
    label: str | None = None


class CreateSnapshotResponse(BaseModel):
    snapshot_id: str
    layer: SnapshotLayer
    parent_snapshot_id: str | None


class SnapshotRecord(BaseModel):
    id: str
    layer: SnapshotLayer
    parent_snapshot_id: str | None
    label: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    # SDK: `avd_clone_path`, `session_avd_name`, `session_android_avd_home`, `avd_parent_snapshot_id`.
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthEvent(BaseModel):
    timestamp: datetime
    emulator_id: str
    ok: bool
    detail: str
