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


def migrate_user_sessions_scheduling_sync(sync_conn) -> None:
    """Add jittered scheduling + optional metadata TTL columns (create_all skips ALTER)."""
    insp = inspect(sync_conn)
    if not insp.has_table("user_sessions"):
        return
    cols = {c["name"] for c in insp.get_columns("user_sessions")}
    if "next_check_at" not in cols:
        sync_conn.execute(text("ALTER TABLE user_sessions ADD COLUMN next_check_at DATETIME"))
        log.info("migrated user_sessions: added next_check_at")
    if "session_expires_at" not in cols:
        sync_conn.execute(text("ALTER TABLE user_sessions ADD COLUMN session_expires_at DATETIME"))
        log.info("migrated user_sessions: added session_expires_at")


def migrate_mission_tasks_sync(sync_conn) -> None:
    insp = inspect(sync_conn)
    if not insp.has_table("mission_tasks"):
        return
    cols = {c["name"] for c in insp.get_columns("mission_tasks")}
    if "re_auth_login_method" not in cols:
        sync_conn.execute(
            text("ALTER TABLE mission_tasks ADD COLUMN re_auth_login_method VARCHAR(32)")
        )
        log.info("migrated mission_tasks: added re_auth_login_method")
