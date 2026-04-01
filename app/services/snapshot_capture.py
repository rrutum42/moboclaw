from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from app.config import Settings
from app.models import CreateSnapshotRequest, CreateSnapshotResponse, EmulatorState, SnapshotRecord
from app.services.android_sdk_emulator import adb_shell_sync, sdk_adb_path
from app.services.emulator_backend import EmulatorBackend
from app.services.emulator_lifecycle import destroy_emulator as teardown_emulator
from app.services.ids import new_snapshot_id
from app.services.qcow2_avd import (
    branch_snapshot_dir,
    destroy_session_avd_tree,
    flatten_userdata_qcow2_overlay_into_raw,
)
from app.services.qcow2_metadata import (
    AVD_CLONE_PATH,
    AVD_PARENT_SNAPSHOT_ID,
    SESSION_ANDROID_AVD_HOME,
    SESSION_AVD_NAME,
)
from app.store import InMemoryStore

log = logging.getLogger(__name__)


def _copy_session_tree_to_branch(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, symlinks=True)


def _prepare_session_tree_for_branch_snapshot(home_path: Path, avd_name: str, settings: Settings) -> None:
    avd_dir = home_path / f"{avd_name}.avd"
    if avd_dir.is_dir():
        flatten_userdata_qcow2_overlay_into_raw(avd_dir, settings)


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

    home = rec.qcow2_android_avd_home
    name = rec.qcow2_avd_name
    if not home or not name:
        async with rec.lock:
            rec.state = EmulatorState.RUNNING
        raise ValueError("SDK backend: emulator has no session AVD; cannot capture snapshot")

    home_path = Path(home)
    dest = branch_snapshot_dir(settings, sid)

    try:
        if rec.adb_serial:
            synced = await adb_shell_sync(sdk_adb_path(settings), rec.adb_serial)
            if synced:
                await asyncio.sleep(0.4)
        await backend.teardown(emulator_id, remove_session_files=False)
        log.info(
            "snapshot avd clone capture emulator_id=%s src=%s dest=%s",
            emulator_id,
            home_path,
            dest,
        )
        await asyncio.to_thread(_prepare_session_tree_for_branch_snapshot, home_path, name, settings)
        await asyncio.to_thread(_copy_session_tree_to_branch, home_path, dest)
        meta = {
            AVD_CLONE_PATH: str(dest.resolve()),
            SESSION_AVD_NAME: name,
            SESSION_ANDROID_AVD_HOME: str(home_path.resolve()),
            AVD_PARENT_SNAPSHOT_ID: parent,
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
        await teardown_emulator(store, emulator_id, "snapshot_avd_clone", quick=True)

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
