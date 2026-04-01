from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.db import orm  # noqa: F401
from app.db.base import Base
from app.db.engine import engine
from app.db.seed import seed_dummy_sessions_if_empty, seed_reference_snapshots
from app.db.sqlite_migrations import migrate_snapshots_table_sync
from app.session_config import session_settings

log = logging.getLogger(__name__)


async def init_db() -> None:
    delay = session_settings.db_connect_retry_delay_seconds
    for attempt in range(session_settings.db_connect_retries):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                if engine.dialect.name == "sqlite":
                    await conn.run_sync(migrate_snapshots_table_sync)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            log.info("database ready")
            await seed_reference_snapshots()
            await seed_dummy_sessions_if_empty()
            return
        except Exception as e:
            log.warning(
                "database not ready (%s/%s): %s",
                attempt + 1,
                session_settings.db_connect_retries,
                e,
            )
            await asyncio.sleep(delay)
    log.error("database unavailable after %s attempts", session_settings.db_connect_retries)
    raise RuntimeError("could not connect to database")
