from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.models import EmulatorState
from app.services.ids import new_emulator_id
from app.services.simulation import simulate_boot_seconds
from app.services.snapshots import BASE_SNAPSHOT_ID
from app.store import InMemoryStore, new_emulator_record

log = logging.getLogger(__name__)


class WarmPool:
    def __init__(
        self,
        store: InMemoryStore,
        settings: Settings,
        replenish_lock: asyncio.Lock,
    ) -> None:
        self._store = store
        self._settings = settings
        self._replenish_lock = replenish_lock

    async def warm_idle_count(self) -> int:
        return await self._store.count_warm_idle_running()

    async def ensure_full(self) -> None:
        async with self._replenish_lock:
            while await self.warm_idle_count() < self._settings.warm_pool_size:
                await self._spawn_one()

    async def _spawn_one(self) -> str | None:
        eid = new_emulator_id()
        rec = new_emulator_record(eid)
        rec.state = EmulatorState.STARTING
        rec.pool_role = "warm_idle"
        await self._store.add_emulator(rec)
        async with rec.lock:
            rec.state = EmulatorState.STARTING
        boot = await simulate_boot_seconds(from_warm_pool=False, settings=self._settings)
        async with rec.lock:
            if rec.state == EmulatorState.DESTROYED:
                return None
            rec.state = EmulatorState.RUNNING
            rec.current_snapshot_id = BASE_SNAPSHOT_ID
            rec.last_boot_seconds = boot
            rec.health_ok = True
            rec.consecutive_health_failures = 0
            rec.message = None
        await self._store.push_warm_idle(eid)
        log.info("warm emulator ready id=%s boot=%.2fs", eid, boot)
        return eid

    async def run_replenish_loop(self, shutdown: asyncio.Event) -> None:
        try:
            while not shutdown.is_set():
                await asyncio.sleep(1.0)
                try:
                    await self.ensure_full()
                except Exception:
                    log.exception("warm pool replenish failed")
        except asyncio.CancelledError:
            raise
