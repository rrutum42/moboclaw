from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Awaitable, Callable

from app.config import Settings
from app.models import EmulatorState, HealthEvent, utcnow
from app.services.simulation import mock_health_probe
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
    ) -> None:
        self._store = store
        self._settings = settings
        self._history = health_history
        self._on_unhealthy = on_unhealthy

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

                ok = mock_health_probe(self._settings)
                self._history.append(
                    HealthEvent(
                        timestamp=utcnow(),
                        emulator_id=eid,
                        ok=ok,
                        detail="mock-probe",
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
