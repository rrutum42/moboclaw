from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.models import CreateSnapshotRequest, CreateSnapshotResponse, EmulatorState, SnapshotRecord

log = logging.getLogger(__name__)
from app.services.ids import new_snapshot_id
from app.store import InMemoryStore


async def capture_snapshot(
    store: InMemoryStore,
    emulator_id: str,
    body: CreateSnapshotRequest,
) -> CreateSnapshotResponse:
    rec = await store.get_emulator(emulator_id)
    if not rec:
        raise KeyError("emulator not found")
    async with rec.lock:
        if rec.state != EmulatorState.RUNNING:
            raise ValueError(f"emulator not RUNNING (state={rec.state})")
        rec.state = EmulatorState.SNAPSHOTTING

    await asyncio.sleep(0.3)

    parent = rec.current_snapshot_id
    sid = new_snapshot_id()
    meta: dict[str, Any] = {"mock_capture": True}
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
