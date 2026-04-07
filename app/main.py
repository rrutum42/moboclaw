from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastmcp import FastMCP
from starlette.responses import RedirectResponse
from fastmcp.utilities.lifespan import combine_lifespans

from app.background import start_background_workers, stop_background_workers
from app.config import settings
from app.controllers import emulators, missions, system, users_sessions
from app.db.init_db import init_db
from app.services.snapshot_persistence import hydrate_store_from_db
from app.store import store as orchestrator_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def moboclaw_lifespan(app: FastAPI):
    await init_db()
    await hydrate_store_from_db(orchestrator_store)
    workers = await start_background_workers()
    log.info(
        "emulator orchestrator started warm_pool_size=%s effective=%s warm_boot_read_only=%s",
        settings.warm_pool_size,
        settings.effective_warm_pool_size(),
        settings.warm_boot_read_only,
    )
    yield
    await stop_background_workers(workers)


api = FastAPI(
    title="Mobile Agent — Emulator + Sessions + Missions",
    version="0.3.0",
)

api.include_router(system.router)
api.include_router(emulators.router)
api.include_router(users_sessions.router)
api.include_router(missions.router)

mcp = FastMCP.from_fastapi(app=api, name="Moboclaw")
mcp_http = mcp.http_app(path="/")

app = FastAPI(
    lifespan=combine_lifespans(moboclaw_lifespan, mcp_http.lifespan),
)


@app.middleware("http")
async def log_all_requests_root(request: Request, call_next):
    """Log every HTTP request (REST + MCP); body logging skipped for size/safety."""
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


@app.api_route(
    "/mcp",
    methods=["GET", "POST", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def mcp_redirect_slash() -> RedirectResponse:
    """Cursor and some clients call `/mcp` without a trailing slash; the mount is `/mcp/`."""
    return RedirectResponse(url="/mcp/", status_code=307)


app.mount("/mcp/", mcp_http)
app.mount("/", api)
