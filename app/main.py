from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.background import start_background_workers, stop_background_workers
from app.config import settings
from app.controllers import emulators, missions, system, users_sessions
from app.db.init_db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    workers = await start_background_workers()
    log.info(
        "emulator orchestrator started warm_pool_size=%s",
        settings.warm_pool_size,
    )
    yield
    await stop_background_workers(workers)


app = FastAPI(
    title="Mobile Agent — Emulator + Sessions + Missions",
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(system.router)
app.include_router(emulators.router)
app.include_router(users_sessions.router)
app.include_router(missions.router)
