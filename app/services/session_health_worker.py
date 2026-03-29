from __future__ import annotations

import asyncio
import logging

from app.db.engine import AsyncSessionLocal
from app.services.session_service import scan_stale_sessions_for_worker
from app.session_config import session_settings

log = logging.getLogger(__name__)


async def run_loop(shutdown: asyncio.Event) -> None:
    log.info(
        "session health worker started (tick=%ss)",
        session_settings.worker_tick_seconds,
    )
    try:
        while not shutdown.is_set():
            await asyncio.sleep(session_settings.worker_tick_seconds)
            async with AsyncSessionLocal() as db:
                try:
                    n = await scan_stale_sessions_for_worker(db)
                    await db.commit()
                    if n:
                        log.info(
                            "session health worker ran mock checks on %s session(s)",
                            n,
                        )
                except Exception:
                    log.exception("session health worker tick failed")
                    await db.rollback()
                    raise
    except asyncio.CancelledError:
        log.info("session health worker cancelled")
        raise
