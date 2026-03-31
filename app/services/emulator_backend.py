"""Pluggable emulator backends: mock (simulated) vs sdk (Android Emulator CLI + adb)."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import Settings
from app.services.android_sdk_emulator import (
    adb_health_ok,
    adb_wait_boot_completed,
    adb_wait_for_device,
    drain_emulator_stderr_to_log,
    kill_emulator,
    sdk_adb_path,
    sdk_emulator_path,
    start_emulator_process,
    _serial_for_console_port,
)
from app.services.qcow2_avd import (
    destroy_session_avd_tree,
    golden_userdata_path,
    prepare_session_avd_with_overlay,
)
from app.services.qcow2_metadata import QCOW2_USERDATA_PATH
from app.services.simulation import mock_health_probe, simulate_boot_seconds
from app.services.snapshots import BASE_SNAPSHOT_ID
from app.store import InMemoryStore

log = logging.getLogger(__name__)


class EmulatorBackend(ABC):
    @abstractmethod
    async def boot_warm(self, emulator_id: str) -> float:
        """Boot a warm-pool instance; returns wall-clock seconds."""

    @abstractmethod
    async def boot_provision(
        self,
        emulator_id: str,
        *,
        from_warm_pool: bool,
        snapshot_id: str,
    ) -> float:
        """Finish provisioning (restore snapshot, etc.); returns wall-clock seconds."""

    @abstractmethod
    async def teardown(self, emulator_id: str, *, remove_session_files: bool = True) -> None:
        """Stop/kill the underlying instance."""

    @abstractmethod
    async def health_probe(self, emulator_id: str) -> bool:
        """Return True if the instance is healthy."""

    async def shutdown_all(self) -> None:
        """Kill every managed emulator process (app shutdown). Default: no-op."""
        return


class MockEmulatorBackend(EmulatorBackend):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def boot_warm(self, emulator_id: str) -> float:
        return await simulate_boot_seconds(from_warm_pool=False, settings=self._settings)

    async def boot_provision(
        self,
        emulator_id: str,
        *,
        from_warm_pool: bool,
        snapshot_id: str,
    ) -> float:
        return await simulate_boot_seconds(from_warm_pool=from_warm_pool, settings=self._settings)

    async def teardown(self, emulator_id: str, *, remove_session_files: bool = True) -> None:
        await asyncio.sleep(0.01)

    async def health_probe(self, emulator_id: str) -> bool:
        return mock_health_probe(self._settings)


class _SdkRuntime:
    __slots__ = ("process", "console_port", "serial")

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        console_port: int,
        serial: str,
    ) -> None:
        self.process = process
        self.console_port = console_port
        self.serial = serial


class SdkEmulatorBackend(EmulatorBackend):
    def __init__(self, settings: Settings, store: InMemoryStore) -> None:
        self._settings = settings
        self._store = store
        self._next_port = settings.emulator_port_start
        self._runtime: dict[str, _SdkRuntime] = {}
        # Serialize qemu-img overlay creation to avoid races / partial files when warm_pool_size > 1.
        self._overlay_lock = asyncio.Lock()

    def _take_next_console_port(self) -> int:
        p = self._next_port
        self._next_port += 2
        return p

    def _userdata_backing_for_snapshot(self, snapshot_id: str) -> Path:
        if snapshot_id == BASE_SNAPSHOT_ID:
            return golden_userdata_path(self._settings)
        raise AssertionError("expected snapshot record for non-base")

    async def _start_cold(
        self,
        emulator_id: str,
        *,
        userdata_backing: Path,
        read_only_avd: bool,
    ) -> tuple[float, str]:
        """Start emulator with per-session qcow2 userdata overlay; register runtime and adb_serial."""
        adb = sdk_adb_path(self._settings)
        console_port = self._take_next_console_port()
        serial = _serial_for_console_port(console_port)
        t0 = time.perf_counter()

        rec = await self._store.get_emulator(emulator_id)
        if not rec:
            raise KeyError(emulator_id)

        android_avd_home: Path | None = None
        avd_name: str | None = None
        try:
            async with self._overlay_lock:
                android_avd_home, avd_name = await prepare_session_avd_with_overlay(
                    self._settings,
                    emulator_id=emulator_id,
                    userdata_backing=userdata_backing,
                )
            async with rec.lock:
                rec.qcow2_android_avd_home = str(android_avd_home)
                rec.qcow2_avd_name = avd_name

            log.info(
                "sdk emulator start id=%s avd=%s read_only=%s port=%s backing=%s",
                emulator_id,
                avd_name,
                read_only_avd,
                console_port,
                userdata_backing,
            )
            proc = await start_emulator_process(
                self._settings,
                console_port=console_port,
                read_only_avd=read_only_avd,
                android_avd_home=android_avd_home,
                avd_name=avd_name,
            )
            stderr_task = asyncio.create_task(drain_emulator_stderr_to_log(proc))
            timeout = self._settings.emulator_boot_completed_timeout_seconds
            try:
                await adb_wait_for_device(adb, serial, timeout, proc=proc)
                await adb_wait_boot_completed(adb, serial, self._settings, proc=proc)
            except Exception:
                await kill_emulator(adb, proc, serial)
                raise
            finally:
                stderr_task.cancel()
                try:
                    await stderr_task
                except asyncio.CancelledError:
                    pass
        except Exception:
            destroy_session_avd_tree(self._settings, emulator_id)
            async with rec.lock:
                rec.qcow2_android_avd_home = None
                rec.qcow2_avd_name = None
            raise

        elapsed = time.perf_counter() - t0
        self._runtime[emulator_id] = _SdkRuntime(proc, console_port, serial)
        async with rec.lock:
            rec.adb_serial = serial
        log.info(
            "sdk emulator up id=%s serial=%s avd=%s elapsed=%.2fs",
            emulator_id,
            serial,
            avd_name,
            elapsed,
        )
        return elapsed, serial

    async def boot_warm(self, emulator_id: str) -> float:
        backing = golden_userdata_path(self._settings)
        elapsed, _ = await self._start_cold(
            emulator_id,
            userdata_backing=backing,
            read_only_avd=self._settings.warm_boot_read_only,
        )
        return elapsed

    async def boot_provision(
        self,
        emulator_id: str,
        *,
        from_warm_pool: bool,
        snapshot_id: str,
    ) -> float:
        rec = await self._store.get_emulator(emulator_id)
        if not rec:
            raise KeyError(emulator_id)

        if from_warm_pool and snapshot_id == BASE_SNAPSHOT_ID:
            return 0.05

        if from_warm_pool:
            raise RuntimeError("warm pool can only satisfy BASE snapshot provisioning")

        snap = await self._store.get_snapshot(snapshot_id)
        if not snap:
            raise ValueError(f"unknown snapshot_id={snapshot_id}")

        if snapshot_id == BASE_SNAPSHOT_ID:
            backing = golden_userdata_path(self._settings)
        else:
            p = snap.metadata.get(QCOW2_USERDATA_PATH)
            if not p:
                raise ValueError(
                    f"SDK backend: snapshot must include metadata.{QCOW2_USERDATA_PATH} (flat qcow2 branch).",
                )
            backing = Path(p)
            if not backing.is_file():
                raise ValueError(f"qcow2_userdata_path not found: {backing}")

        elapsed, _ = await self._start_cold(
            emulator_id,
            userdata_backing=backing,
            read_only_avd=False,
        )
        return elapsed

    async def teardown(self, emulator_id: str, *, remove_session_files: bool = True) -> None:
        rt = self._runtime.pop(emulator_id, None)
        adb = sdk_adb_path(self._settings)
        if rt:
            await kill_emulator(adb, rt.process, rt.serial)
        else:
            rec = await self._store.get_emulator(emulator_id)
            serial = rec.adb_serial if rec else None
            await kill_emulator(adb, None, serial)
        if remove_session_files:
            destroy_session_avd_tree(self._settings, emulator_id)
            rec = await self._store.get_emulator(emulator_id)
            if rec:
                async with rec.lock:
                    rec.qcow2_android_avd_home = None
                    rec.qcow2_avd_name = None

    async def health_probe(self, emulator_id: str) -> bool:
        rec = await self._store.get_emulator(emulator_id)
        if not rec or not rec.adb_serial:
            return False
        adb = sdk_adb_path(self._settings)
        return await adb_health_ok(adb, rec.adb_serial)

    async def shutdown_all(self) -> None:
        adb = sdk_adb_path(self._settings)
        seen: set[str] = set()
        for _eid, rt in list(self._runtime.items()):
            await kill_emulator(adb, rt.process, rt.serial)
            seen.add(rt.serial)
        self._runtime.clear()
        for eid in await self._store.list_all_emulator_ids():
            rec = await self._store.get_emulator(eid)
            if rec and rec.adb_serial and rec.adb_serial not in seen:
                await kill_emulator(adb, None, rec.adb_serial)
                seen.add(rec.adb_serial)
        for eid in await self._store.list_all_emulator_ids():
            destroy_session_avd_tree(self._settings, eid)
        if seen:
            log.info("sdk shutdown_all: stopped %s emulator adb device(s)", len(seen))


def create_emulator_backend(settings: Settings, store: InMemoryStore) -> EmulatorBackend:
    if settings.backend == "sdk":
        try:
            sdk_root = settings.resolved_android_sdk_root()
        except RuntimeError as e:
            log.warning("emulator backend=sdk but SDK root not configured: %s", e)
            raise
        log.info(
            "emulator backend=sdk avd=%s sdk=%s emulator=%s",
            settings.avd_name,
            sdk_root,
            sdk_emulator_path(settings),
        )
        return SdkEmulatorBackend(settings, store)
    return MockEmulatorBackend(settings)
