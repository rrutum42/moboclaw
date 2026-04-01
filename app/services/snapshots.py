from __future__ import annotations

import logging

from app.models import SnapshotLayer, SnapshotRecord
from app.services.qcow2_metadata import AVD_BRANCH_KIND, AVD_BRANCH_KIND_GOLDEN
from app.services.snapshot_persistence import persist_snapshot_record
from app.store import InMemoryStore

log = logging.getLogger(__name__)

BASE_SNAPSHOT_ID = "snap-base-default"
SEED_TRAVEL_SNAPSHOT_ID = "snap-seed-travel"


def base_snapshot_record() -> SnapshotRecord:
    return SnapshotRecord(
        id=BASE_SNAPSHOT_ID,
        layer=SnapshotLayer.BASE,
        parent_snapshot_id=None,
        label="clean-android",
        metadata={
            "aosp": "mock-34",
            AVD_BRANCH_KIND: AVD_BRANCH_KIND_GOLDEN,
        },
    )


def travel_seed_snapshot_record() -> SnapshotRecord:
    return SnapshotRecord(
        id=SEED_TRAVEL_SNAPSHOT_ID,
        layer=SnapshotLayer.SESSION,
        parent_snapshot_id=BASE_SNAPSHOT_ID,
        label="seed-travel",
        metadata={"mock": True},
    )


async def seed_base_snapshot(store: InMemoryStore) -> str:
    if await store.get_snapshot(BASE_SNAPSHOT_ID):
        return BASE_SNAPSHOT_ID
    rec = base_snapshot_record()
    await store.add_snapshot(rec)
    await persist_snapshot_record(rec)
    log.info("seeded base snapshot id=%s", BASE_SNAPSHOT_ID)
    return BASE_SNAPSHOT_ID
