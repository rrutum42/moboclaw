from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import AsyncSessionLocal, engine
from app.db.orm import Snapshot as SnapshotRow
from app.db.sqlite_migrations import migrate_snapshots_table_sync
from app.models import SnapshotLayer, SnapshotRecord

log = logging.getLogger(__name__)

_schema_migrated = False


async def _ensure_sqlite_snapshots_schema() -> None:
    global _schema_migrated
    if _schema_migrated or engine.sync_engine.dialect.name != "sqlite":
        return
    async with engine.begin() as conn:
        await conn.run_sync(migrate_snapshots_table_sync)
    _schema_migrated = True


def _record_from_orm(row: SnapshotRow) -> SnapshotRecord:
    return SnapshotRecord(
        id=row.id,
        layer=SnapshotLayer(row.layer),
        parent_snapshot_id=row.parent_snapshot_id,
        label=row.label,
        created_at=row.created_at,
        metadata=dict(row.snapshot_metadata or {}),
    )


def _layer_value(layer: SnapshotLayer | str) -> str:
    if isinstance(layer, SnapshotLayer):
        return layer.value
    return str(layer)


def orm_row_from_record(rec: SnapshotRecord) -> SnapshotRow:
    return SnapshotRow(
        id=rec.id,
        layer=_layer_value(rec.layer),
        parent_snapshot_id=rec.parent_snapshot_id,
        label=rec.label,
        created_at=rec.created_at,
        snapshot_metadata=dict(rec.metadata or {}),
    )


async def persist_snapshot_record(rec: SnapshotRecord) -> None:
    await _ensure_sqlite_snapshots_schema()
    async with AsyncSessionLocal() as db:
        r = await db.get(SnapshotRow, rec.id)
        if r is None:
            db.add(orm_row_from_record(rec))
        else:
            r.layer = _layer_value(rec.layer)
            r.parent_snapshot_id = rec.parent_snapshot_id
            r.label = rec.label
            r.created_at = rec.created_at
            r.snapshot_metadata = dict(rec.metadata or {})
        await db.commit()


async def hydrate_store_from_db(store: object) -> int:
    """Load all snapshot rows into the in-memory orchestrator store."""
    from app.store import InMemoryStore

    if not isinstance(store, InMemoryStore):
        raise TypeError("store must be InMemoryStore")

    await _ensure_sqlite_snapshots_schema()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SnapshotRow))
        rows = list(result.scalars().all())
    n = 0
    for row in rows:
        rec = _record_from_orm(row)
        await store.add_snapshot(rec)
        n += 1
    log.info("hydrated %s snapshots from database into store", n)
    return n


async def snapshot_exists(db: AsyncSession, sid: str) -> bool:
    await _ensure_sqlite_snapshots_schema()
    r = await db.get(SnapshotRow, sid)
    return r is not None


async def ensure_snapshots_for_seed(records: list[SnapshotRecord]) -> None:
    """Insert reference snapshot rows if missing (FK targets for seeded sessions)."""
    await _ensure_sqlite_snapshots_schema()
    async with AsyncSessionLocal() as db:
        for rec in records:
            r = await db.get(SnapshotRow, rec.id)
            if r is None:
                db.add(orm_row_from_record(rec))
        await db.commit()
