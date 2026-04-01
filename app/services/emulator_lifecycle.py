from __future__ import annotations

import asyncio
import logging

from app.models import EmulatorState
from app.store import InMemoryStore

log = logging.getLogger(__name__)


async def destroy_emulator(
    store: InMemoryStore,
    emulator_id: str,
    reason: str,
    *,
    quick: bool = False,
) -> None:
    rec = await store.get_emulator(emulator_id)
    if not rec:
        log.warning("destroy_emulator: no such emulator id=%s", emulator_id)
        raise KeyError("emulator not found")
    async with rec.lock:
        rec.state = EmulatorState.STOPPING
    if not quick:
        await asyncio.sleep(0.15)
    async with rec.lock:
        rec.state = EmulatorState.STOPPED
    if not quick:
        await asyncio.sleep(0.05)
    async with rec.lock:
        rec.state = EmulatorState.DESTROYED
        rec.message = reason
    await store.remove_emulator(emulator_id)
    log.info("emulator removed from store id=%s reason=%s", emulator_id, reason)
