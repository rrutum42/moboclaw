from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

log = logging.getLogger(__name__)

from app.config import Settings, settings as default_settings
from app.models import (
    CreateSnapshotRequest,
    CreateSnapshotResponse,
    EmulatorState,
    EmulatorStatusResponse,
    HealthEvent,
    ProvisionEmulatorResponse,
)
from app.services.emulator_backend import EmulatorBackend, create_emulator_backend
from app.services.emulator_lifecycle import destroy_emulator as teardown_emulator
from app.services.health_monitor import HealthMonitor
from app.services.ids import new_emulator_id
from app.services.snapshot_capture import capture_snapshot
from app.services.snapshots import BASE_SNAPSHOT_ID, seed_base_snapshot
from app.services.warm_pool import WarmPool
from app.store import InMemoryStore, new_emulator_record, store as default_store


class EmulatorService:
    def __init__(
        self,
        store: InMemoryStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.store = store if store is not None else default_store
        self.settings = settings if settings is not None else default_settings
        self._backend: EmulatorBackend = create_emulator_backend(self.settings, self.store)
        self._replenish_lock = asyncio.Lock()
        self._shutdown = asyncio.Event()
        self.health_history: deque[HealthEvent] = deque(maxlen=500)
        self.warm_pool = WarmPool(self.store, self.settings, self._replenish_lock, self._backend)
        self._health_monitor = HealthMonitor(
            self.store,
            self.settings,
            self.health_history,
            self._replace_unhealthy_emulator,
            self._backend,
        )
        self._initial_warm_task: asyncio.Task[Any] | None = None
        self._replenish_task: asyncio.Task[Any] | None = None
        self._health_task: asyncio.Task[Any] | None = None

    async def start_background_tasks(self) -> None:
        await seed_base_snapshot(self.store)
        log.info(
            "emulator background tasks starting (warm_pool_size=%s)",
            self.settings.warm_pool_size,
        )
        self._shutdown.clear()
        self._initial_warm_task = asyncio.create_task(
            self.warm_pool.ensure_full(),
            name="warm-pool-initial-fill",
        )
        self._replenish_task = asyncio.create_task(
            self.warm_pool.run_replenish_loop(self._shutdown),
            name="warm-pool-replenish",
        )
        self._health_task = asyncio.create_task(
            self._health_monitor.run_loop(self._shutdown),
            name="emulator-health",
        )

    async def stop_background_tasks(self) -> None:
        log.info("emulator background tasks stopping")
        self._shutdown.set()
        for t in (self._initial_warm_task, self._replenish_task, self._health_task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._initial_warm_task = None
        self._replenish_task = None
        self._health_task = None
        await self._cleanup_emulators_on_shutdown()

    async def _cleanup_emulators_on_shutdown(self) -> None:
        """Stop real emulator processes and drop in-memory emulator rows so nothing is left after exit."""
        try:
            await self._backend.shutdown_all()
        except Exception:
            log.exception("emulator backend shutdown_all failed")
        try:
            await self.store.clear_emulators()
        except Exception:
            log.exception("clear emulators on shutdown failed")

    async def _replace_unhealthy_emulator(self, emulator_id: str) -> None:
        await self.destroy_emulator(emulator_id, reason="auto_replace_unhealthy")

    def _schedule_replenish(self) -> None:
        asyncio.create_task(self.warm_pool.ensure_full())

    async def _drain_warm_idle_no_replenish(self) -> None:
        """Stop other warm_pool instances so a single cold boot can load a named snapshot.

        Multiple same-AVD emulator processes can block on disk locks; adb never lists the
        new device and POST /emulators appears to hang until the boot timeout.
        """
        ids = await self.store.list_all_emulator_ids()
        for eid in list(ids):
            rec = await self.store.get_emulator(eid)
            if not rec or rec.pool_role != "warm_idle":
                continue
            # pool_role stays warm_idle during POST .../snapshot while state is SNAPSHOTTING;
            # never tear down an emulator mid-snapshot or mid-boot.
            if rec.state != EmulatorState.RUNNING:
                log.info(
                    "snapshot restore: skip warm_idle id=%s state=%s (busy)",
                    eid,
                    rec.state,
                )
                continue
            log.info(
                "snapshot restore: stopping warm_idle id=%s (exclusive AVD for snapshot cold boot)",
                eid,
            )
            await self._backend.teardown(eid)
            await teardown_emulator(
                self.store,
                eid,
                "snapshot_restore_exclusive_avd",
                quick=self.settings.backend == "sdk",
            )

    async def provision(self, snapshot_id: str | None) -> ProvisionEmulatorResponse:
        target = snapshot_id or BASE_SNAPSHOT_ID
        snap = await self.store.get_snapshot(target)
        if not snap:
            raise ValueError(f"unknown snapshot_id={target}")
        if (
            self.settings.backend == "sdk"
            and target != BASE_SNAPSHOT_ID
            and not snap.metadata.get("sdk_snapshot_name")
        ):
            raise ValueError(
                "SDK backend: snapshot must be created on-device (POST .../snapshot); "
                "missing metadata.sdk_snapshot_name",
            )

        need_exclusive_avd = (
            self.settings.backend == "sdk" and target != BASE_SNAPSHOT_ID
        )

        async def _do() -> ProvisionEmulatorResponse:
            log.info(
                "provision step: target=%s need_exclusive_avd=%s",
                target,
                need_exclusive_avd,
            )
            # Warm pool instances boot with -no-snapshot-load. Restoring a named snapshot
            # via adb on a *different* running instance than the one that saved it is unreliable
            # with read-only/multi-instance AVDs. Non-base snapshots must cold-boot with
            # -snapshot <name> so the image is loaded from the shared AVD snapshot store.
            warm_id = (
                await self.store.pop_warm_idle() if target == BASE_SNAPSHOT_ID else None
            )
            from_warm = warm_id is not None
            if from_warm:
                rec = await self.store.get_emulator(warm_id)
            else:
                eid = new_emulator_id()
                rec = new_emulator_record(eid)
                await self.store.add_emulator(rec)

            assert rec is not None
            eid = rec.id

            async with rec.lock:
                rec.state = EmulatorState.STARTING
                rec.pool_role = "provisioned"
                rec.assigned = True

            log.info(
                "provision boot_provision start id=%s snapshot=%s from_warm=%s",
                eid,
                target,
                from_warm,
            )
            try:
                boot = await self._backend.boot_provision(
                    eid,
                    from_warm_pool=from_warm,
                    snapshot_id=target,
                )
            except Exception:
                log.exception(
                    "provision boot_provision failed id=%s snapshot=%s",
                    eid,
                    target,
                )
                await self._backend.teardown(eid)
                await self.store.remove_emulator(eid)
                raise
            log.info(
                "provisioned emulator id=%s snapshot=%s from_warm_pool=%s boot=%.2fs",
                eid,
                target,
                from_warm,
                boot,
            )

            async with rec.lock:
                rec.state = EmulatorState.RUNNING
                rec.current_snapshot_id = target
                rec.last_boot_seconds = boot
                rec.health_ok = True
                rec.consecutive_health_failures = 0
                rec.message = None

            return ProvisionEmulatorResponse(
                id=eid,
                state=rec.state,
                restored_snapshot_id=target,
                boot_seconds=boot,
            )

        try:
            if need_exclusive_avd:
                log.info(
                    "snapshot restore: acquiring replenish lock and draining warm pool for %s",
                    target,
                )
                async with self._replenish_lock:
                    await self._drain_warm_idle_no_replenish()
                    delay = self.settings.emulator_avd_settle_delay_seconds
                    if self.settings.backend == "sdk" and delay > 0:
                        log.info(
                            "snapshot restore: AVD settle delay %.1fs before cold boot",
                            delay,
                        )
                        await asyncio.sleep(delay)
                    return await _do()
            return await _do()
        finally:
            # Refill warm pool after success or failure (failure used to leave zero emulators).
            self._schedule_replenish()

    async def create_snapshot(
        self,
        emulator_id: str,
        body: CreateSnapshotRequest,
    ) -> CreateSnapshotResponse:
        return await capture_snapshot(self.store, emulator_id, body)

    async def list_emulators(self, *, running_only: bool = False) -> list[EmulatorStatusResponse]:
        if running_only:
            ids = await self.store.list_running_emulator_ids()
        else:
            ids = await self.store.list_all_emulator_ids()
        out: list[EmulatorStatusResponse] = []
        for eid in ids:
            try:
                out.append(await self.status(eid))
            except KeyError:
                continue
        return out

    async def status(self, emulator_id: str) -> EmulatorStatusResponse:
        rec = await self.store.get_emulator(emulator_id)
        if not rec:
            raise KeyError("emulator not found")
        async with rec.lock:
            return EmulatorStatusResponse(
                id=rec.id,
                state=rec.state,
                current_snapshot_id=rec.current_snapshot_id,
                assigned=rec.assigned,
                pool_role=rec.pool_role,
                last_boot_seconds=rec.last_boot_seconds,
                health_ok=rec.health_ok,
                consecutive_health_failures=rec.consecutive_health_failures,
                message=rec.message,
                adb_serial=rec.adb_serial,
            )

    async def destroy_emulator(self, emulator_id: str, reason: str = "user_delete") -> None:
        log.info("destroy emulator id=%s reason=%s", emulator_id, reason)
        await self._backend.teardown(emulator_id)
        await teardown_emulator(
            self.store,
            emulator_id,
            reason,
            quick=self.settings.backend == "sdk",
        )
        self._schedule_replenish()


emulator_service = EmulatorService()
