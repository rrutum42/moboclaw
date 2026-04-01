"""Lightweight SQLite schema fixes (create_all does not ALTER existing tables)."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

log = logging.getLogger(__name__)


def migrate_snapshots_table_sync(sync_conn) -> None:
    insp = inspect(sync_conn)
    if not insp.has_table("snapshots"):
        return
    cols = {c["name"] for c in insp.get_columns("snapshots")}
    if "snapshot_metadata" not in cols:
        sync_conn.execute(text("ALTER TABLE snapshots ADD COLUMN snapshot_metadata JSON"))
        log.info("migrated snapshots: added snapshot_metadata")
        cols.add("snapshot_metadata")

    # Older drafts used a NOT NULL column named `metadata`. ORM uses `snapshot_metadata`.
    # If both exist, inserts only fill snapshot_metadata and SQLite errors on `metadata`.
    if "metadata" in cols:
        try:
            sync_conn.execute(
                text(
                    "UPDATE snapshots SET snapshot_metadata = metadata "
                    "WHERE snapshot_metadata IS NULL AND metadata IS NOT NULL"
                )
            )
        except Exception as e:
            log.warning("snapshots metadata copy skipped: %s", e)
        try:
            sync_conn.execute(text("ALTER TABLE snapshots DROP COLUMN metadata"))
            log.info("migrated snapshots: dropped legacy metadata column")
        except Exception as e:
            log.warning(
                "could not DROP COLUMN metadata (SQLite 3.35+ required or delete sessions.db): %s",
                e,
            )
