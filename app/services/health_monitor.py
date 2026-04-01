from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Awaitable, Callable

from app.config import Settings
from app.models import EmulatorState, HealthEvent, utcnow
from app.services.emulator_backend import EmulatorBackend
from app.store import InMemoryStore

log = logging.getLogger(__name__)

OnUnhealthy = Callable[[str], Awaitable[None]]


class HealthMonitor:
    def __init__(
        self,
        store: InMemoryStore,
        settings: Settings,
        health_history: deque[HealthEvent],
        on_unhealthy: OnUnhealthy,
        backend: EmulatorBackend,
    ) -> None:
        self._store = store
        self._settings = settings
        self._history = health_history
        self._on_unhealthy = on_unhealthy
        self._backend = backend

    async def run_loop(self, shutdown: asyncio.Event) -> None:
        try:
            while not shutdown.is_set():
                await asyncio.sleep(self._settings.health_check_interval_seconds)
                await self._tick()
        except asyncio.CancelledError:
            raise

    async def _tick(self) -> None:
        for eid in await self._store.list_running_emulator_ids():
            try:
                rec = await self._store.get_emulator(eid)
                if not rec or rec.state != EmulatorState.RUNNING:
                    continue

                ok = await self._backend.health_probe(eid)
                detail = "sdk-adb" if self._settings.backend == "sdk" else "mock-probe"
                self._history.append(
                    HealthEvent(
                        timestamp=utcnow(),
                        emulator_id=eid,
                        ok=ok,
                        detail=detail,
                    )
                )

                failures_after = 0
                async with rec.lock:
                    if ok:
                        rec.health_ok = True
                        rec.consecutive_health_failures = 0
                    else:
                        rec.health_ok = False
                        rec.consecutive_health_failures += 1
                        rec.message = "health check failed (mock ANR/hang/boot flake)"
                    failures_after = rec.consecutive_health_failures

                if not ok and failures_after >= self._settings.max_health_failures_before_replace:
                    log.warning("replacing unhealthy emulator id=%s", eid)
                    await self._on_unhealthy(eid)
            except Exception:
                log.exception("health monitor tick failed for emulator_id=%s", eid)
