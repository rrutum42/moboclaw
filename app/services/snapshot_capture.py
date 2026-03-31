from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings
from app.models import CreateSnapshotRequest, CreateSnapshotResponse, EmulatorState, SnapshotRecord
from app.services.android_sdk_emulator import adb_snapshot_save, sanitize_avd_snapshot_name, sdk_adb_path
from app.services.ids import new_snapshot_id
from app.store import InMemoryStore

log = logging.getLogger(__name__)


async def capture_snapshot(
    store: InMemoryStore,
    emulator_id: str,
    body: CreateSnapshotRequest,
) -> CreateSnapshotResponse:
    log.info(
        "snapshot capture request emulator_id=%s layer=%s backend=%s",
        emulator_id,
        body.layer,
        settings.backend,
    )
    rec = await store.get_emulator(emulator_id)
    if not rec:
        raise KeyError("emulator not found")
    async with rec.lock:
        if rec.state != EmulatorState.RUNNING:
            raise ValueError(f"emulator not RUNNING (state={rec.state})")
        rec.state = EmulatorState.SNAPSHOTTING

    if settings.backend != "sdk":
        await asyncio.sleep(0.3)

    parent = rec.current_snapshot_id
    sid = new_snapshot_id()
    if settings.backend == "sdk":
        serial = rec.adb_serial
        if not serial:
            async with rec.lock:
                rec.state = EmulatorState.RUNNING
            raise ValueError("SDK backend: emulator has no adb serial; cannot snapshot")
        snap_name = sanitize_avd_snapshot_name(f"sn_{sid.replace('-', '')}")
        log.info(
            "snapshot capture adb save start emulator_id=%s serial=%s snap_name=%s",
            emulator_id,
            serial,
            snap_name,
        )
        await adb_snapshot_save(sdk_adb_path(settings), serial, snap_name)
        meta = {"sdk_snapshot": True, "sdk_snapshot_name": snap_name}
    else:
        meta = {"mock_capture": True}
    snap = SnapshotRecord(
        id=sid,
        layer=body.layer,
        parent_snapshot_id=parent,
        label=body.label,
        metadata=meta,
    )
    await store.add_snapshot(snap)

    async with rec.lock:
        rec.state = EmulatorState.RUNNING
        rec.current_snapshot_id = sid

    log.info(
        "snapshot captured id=%s emulator=%s layer=%s parent=%s",
        sid,
        emulator_id,
        body.layer,
        parent,
    )
    return CreateSnapshotResponse(
        snapshot_id=sid,
        layer=body.layer,
        parent_snapshot_id=parent,
    )
