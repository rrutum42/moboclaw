from __future__ import annotations

import asyncio
from collections import deque
from typing import Deque

from app.models import EmulatorState, SnapshotRecord


class EmulatorRecord:
    __slots__ = (
        "id",
        "state",
        "current_snapshot_id",
        "assigned",
        "pool_role",
        "last_boot_seconds",
        "health_ok",
        "consecutive_health_failures",
        "message",
        "adb_serial",
        "qcow2_android_avd_home",
        "qcow2_avd_name",
        "lock",
    )

    def __init__(self, eid: str) -> None:
        self.id = eid
        self.state = EmulatorState.CREATING
        self.current_snapshot_id: str | None = None
        self.assigned = False
        self.pool_role = "none"
        self.last_boot_seconds: float | None = None
        self.health_ok = True
        self.consecutive_health_failures = 0
        self.message: str | None = None
        self.adb_serial: str | None = None
        # SDK qcow2 session AVD (ANDROID_AVD_HOME + avd name for emulator -avd).
        self.qcow2_android_avd_home: str | None = None
        self.qcow2_avd_name: str | None = None
        self.lock = asyncio.Lock()


def new_emulator_record(eid: str) -> EmulatorRecord:
    return EmulatorRecord(eid)


class InMemoryStore:
    def __init__(self) -> None:
        self.emulators: dict[str, EmulatorRecord] = {}
        self.snapshots: dict[str, SnapshotRecord] = {}
        self.warm_idle_queue: Deque[str] = deque()
        self._lock = asyncio.Lock()

    async def add_emulator(self, rec: EmulatorRecord) -> None:
        async with self._lock:
            self.emulators[rec.id] = rec

    async def get_emulator(self, eid: str) -> EmulatorRecord | None:
        async with self._lock:
            return self.emulators.get(eid)

    async def remove_emulator(self, eid: str) -> None:
        async with self._lock:
            self.emulators.pop(eid, None)
            self._drop_from_warm_queue(eid)

    def _drop_from_warm_queue(self, eid: str) -> None:
        self.warm_idle_queue = deque(x for x in self.warm_idle_queue if x != eid)

    async def push_warm_idle(self, eid: str) -> None:
        async with self._lock:
            if eid not in self.warm_idle_queue:
                self.warm_idle_queue.append(eid)

    async def pop_warm_idle(self) -> str | None:
        async with self._lock:
            while self.warm_idle_queue:
                eid = self.warm_idle_queue.popleft()
                if eid in self.emulators:
                    return eid
            return None

    async def add_snapshot(self, rec: SnapshotRecord) -> None:
        async with self._lock:
            self.snapshots[rec.id] = rec

    async def get_snapshot(self, sid: str) -> SnapshotRecord | None:
        async with self._lock:
            return self.snapshots.get(sid)

    async def count_warm_idle_running(self) -> int:
        async with self._lock:
            return sum(
                1
                for r in self.emulators.values()
                if r.pool_role == "warm_idle" and r.state == EmulatorState.RUNNING
            )

    async def list_running_emulator_ids(self) -> list[str]:
        async with self._lock:
            return [eid for eid, r in self.emulators.items() if r.state == EmulatorState.RUNNING]

    async def list_all_emulator_ids(self) -> list[str]:
        async with self._lock:
            return list(self.emulators.keys())

    async def clear_emulators(self) -> None:
        async with self._lock:
            self.emulators.clear()
            self.warm_idle_queue.clear()


store = InMemoryStore()
