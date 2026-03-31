from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.models import EmulatorState
from app.services.emulator_backend import EmulatorBackend
from app.services.ids import new_emulator_id
from app.services.snapshots import BASE_SNAPSHOT_ID
from app.store import InMemoryStore, new_emulator_record

log = logging.getLogger(__name__)


class WarmPool:
    def __init__(
        self,
        store: InMemoryStore,
        settings: Settings,
        replenish_lock: asyncio.Lock,
        backend: EmulatorBackend,
    ) -> None:
        self._store = store
        self._settings = settings
        self._replenish_lock = replenish_lock
        self._backend = backend

    async def warm_idle_count(self) -> int:
        return await self._store.count_warm_idle_running()

    async def ensure_full(self) -> None:
        """Fill the warm pool. Lock is held only for count checks — not during boot (slow).

        Long boots used to run under the same lock as snapshot provisioning, which blocked
        POST /emulators (named snapshot) until every warm spawn finished.
        """
        while True:
            async with self._replenish_lock:
                if await self.warm_idle_count() >= self._settings.warm_pool_size:
                    return
            try:
                await self._spawn_one()
            except Exception:
                log.exception("warm pool spawn failed")
                return

    async def _spawn_one(self) -> str | None:
        eid = new_emulator_id()
        rec = new_emulator_record(eid)
        rec.state = EmulatorState.STARTING
        rec.pool_role = "warm_idle"
        await self._store.add_emulator(rec)
        async with rec.lock:
            rec.state = EmulatorState.STARTING
        try:
            boot = await self._backend.boot_warm(eid)
        except Exception:
            await self._store.remove_emulator(eid)
            raise
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
