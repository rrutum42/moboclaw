from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

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


@app.middleware("http")
async def log_all_requests(request: Request, call_next):
    """Log every HTTP request with duration and status (body logging skipped for size/safety)."""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    t0 = time.perf_counter()
    client = getattr(request.client, "host", "?") if request.client else "?"
    log.info(
        "http request start id=%s %s %s client=%s",
        rid,
        request.method,
        request.url.path,
        client,
    )
    try:
        response = await call_next(request)
    except Exception:
        elapsed = time.perf_counter() - t0
        log.exception(
            "http request error id=%s %s %s after %.3fs",
            rid,
            request.method,
            request.url.path,
            elapsed,
        )
        raise
    elapsed = time.perf_counter() - t0
    log.info(
        "http request done id=%s %s %s status=%s %.3fs",
        rid,
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    response.headers["X-Request-ID"] = rid
    return response


app.include_router(system.router)
app.include_router(emulators.router)
app.include_router(users_sessions.router)
app.include_router(missions.router)
