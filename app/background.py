from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.services.emulator_service import emulator_service

log = logging.getLogger(__name__)
from app.services.session_health_worker import run_loop as session_health_run_loop


@dataclass
class BackgroundWorkers:
    session_shutdown: asyncio.Event
    session_health_task: asyncio.Task[None]


async def start_background_workers() -> BackgroundWorkers:
    log.info("starting background workers (emulator pool + session health)")
    await emulator_service.start_background_tasks()
    shutdown = asyncio.Event()
    session_task = asyncio.create_task(
        session_health_run_loop(shutdown),
        name="session-health-worker",
    )
    return BackgroundWorkers(session_shutdown=shutdown, session_health_task=session_task)


async def stop_background_workers(workers: BackgroundWorkers | None) -> None:
    if workers is None:
        return
    log.info("stopping background workers")
    workers.session_shutdown.set()
    workers.session_health_task.cancel()
    try:
        await workers.session_health_task
    except asyncio.CancelledError:
        pass
    await emulator_service.stop_background_tasks()
