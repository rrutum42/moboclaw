from __future__ import annotations

import logging

from app.models import SnapshotLayer, SnapshotRecord
from app.services.qcow2_metadata import AVD_BRANCH_KIND, AVD_BRANCH_KIND_GOLDEN
from app.store import InMemoryStore

log = logging.getLogger(__name__)

BASE_SNAPSHOT_ID = "snap-base-default"


async def seed_base_snapshot(store: InMemoryStore) -> str:
    if await store.get_snapshot(BASE_SNAPSHOT_ID):
        return BASE_SNAPSHOT_ID
    rec = SnapshotRecord(
        id=BASE_SNAPSHOT_ID,
        layer=SnapshotLayer.BASE,
        parent_snapshot_id=None,
        label="clean-android",
        metadata={
            "aosp": "mock-34",
            AVD_BRANCH_KIND: AVD_BRANCH_KIND_GOLDEN,
        },
    )
    await store.add_snapshot(rec)
    log.info("seeded base snapshot id=%s", BASE_SNAPSHOT_ID)
    return BASE_SNAPSHOT_ID
