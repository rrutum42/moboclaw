from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import Settings
from app.models import CreateSnapshotRequest, CreateSnapshotResponse, EmulatorState, SnapshotRecord
from app.services.emulator_backend import EmulatorBackend
from app.services.emulator_lifecycle import destroy_emulator as teardown_emulator
from app.services.ids import new_snapshot_id
from app.services.qcow2_avd import (
    SESSION_USERDATA_QCOW2_NAME,
    branch_image_path,
    destroy_session_avd_tree,
    qemu_img_convert_flat_qcow2,
)
from app.services.qcow2_metadata import (
    QCOW2_FORMAT,
    QCOW2_FORMAT_FLAT,
    QCOW2_PARENT_SNAPSHOT_ID,
    QCOW2_USERDATA_PATH,
)
from app.store import InMemoryStore

log = logging.getLogger(__name__)


async def capture_snapshot(
    store: InMemoryStore,
    emulator_id: str,
    body: CreateSnapshotRequest,
    *,
    settings: Settings,
    backend: EmulatorBackend,
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

    parent = rec.current_snapshot_id
    sid = new_snapshot_id()

    if settings.backend != "sdk":
        await asyncio.sleep(0.3)
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
        return CreateSnapshotResponse(
            snapshot_id=sid,
            layer=body.layer,
            parent_snapshot_id=parent,
        )

    # SDK v1: offline qemu-img flatten to a qcow2 branch (no adb snapshot). Ends this emulator session.
    home = rec.qcow2_android_avd_home
    name = rec.qcow2_avd_name
    if not home or not name:
        async with rec.lock:
            rec.state = EmulatorState.RUNNING
        raise ValueError("SDK backend: emulator has no qcow2 session AVD; cannot capture branch")

    overlay = Path(home) / f"{name}.avd" / SESSION_USERDATA_QCOW2_NAME
    dest = branch_image_path(settings, sid)

    try:
        await backend.teardown(emulator_id, remove_session_files=False)
        log.info(
            "snapshot qcow2 convert start emulator_id=%s overlay=%s dest=%s",
            emulator_id,
            overlay,
            dest,
        )
        await qemu_img_convert_flat_qcow2(settings, source_chain=overlay, dest=dest)
        meta = {
            QCOW2_USERDATA_PATH: str(dest.resolve()),
            QCOW2_PARENT_SNAPSHOT_ID: parent,
            QCOW2_FORMAT: QCOW2_FORMAT_FLAT,
        }
        snap = SnapshotRecord(
            id=sid,
            layer=body.layer,
            parent_snapshot_id=parent,
            label=body.label,
            metadata=meta,
        )
        await store.add_snapshot(snap)
    finally:
        destroy_session_avd_tree(settings, emulator_id)
        await teardown_emulator(store, emulator_id, "snapshot_qcow2", quick=True)

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
