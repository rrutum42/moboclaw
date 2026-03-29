# Architecture

This document describes how the Moboclaw service is structured: entrypoint, layers, background work, and how missions interact with sessions and emulators.

## Process model

- **Runtime**: One **FastAPI** application (`app.main:app`) with an **async lifespan** that initializes the database and starts background workers.
- **Database**: **SQLAlchemy 2.x** async with **SQLite** (`aiosqlite`) for `users`, `user_sessions`, `session_health_history`, `missions`, and `mission_tasks`.
- **Part 1 state**: Mock emulators, snapshots, and health history for emulators live **in memory** inside `EmulatorService` (not in SQLite).

## Layered modules (MVC-style)


| Layer                                        | Role                                                                                                              |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| **Controllers** (`app/controllers/`)         | HTTP routes only: `system`, `emulators`, `users_sessions`, `missions`.                                            |
| **Services** (`app/services/`)               | Business logic: emulator orchestration, warm pool, session CRUD + verify, mission pipeline, simulation, webhooks. |
| **DB** (`app/db/`)                           | Engine, session dependency, ORM models, init/seed.                                                                |
| **Schemas** (`app/schemas/`)                 | Pydantic request/response models for sessions and missions.                                                       |
| **Models** (`app/models.py`, `app/store.py`) | Part 1 Pydantic types and in-memory structures.                                                                   |


## Background workers

Started in `app.background.start_background_workers()`:

1. **Emulator subsystem** — `emulator_service.start_background_tasks()` drives warm pool fill, health monitoring, and related async loops (see `health_monitor`, `warm_pool`, etc.).
2. **Session health worker** — `session_health_run_loop` polls on `SESSION_WORKER_TICK_SECONDS` and schedules tier-based health checks for hot/warm sessions.

On shutdown, the session worker task is cancelled and emulator background tasks are stopped.

## Mission execution pipeline

1. **Create** — `POST /missions` persists `Mission` + `MissionTask` rows and schedules `mission_service.safe_run_mission(mission_id)` via FastAPI `BackgroundTasks`.
2. **Group by app** — Targets are grouped by `app_package`. Each group runs as an **asyncio** task; groups run **concurrently** (`asyncio.gather`). Within a group, tasks run **in sequence** (ordered by `targets` list).
3. **Session gate** — For each task, the service loads `user_sessions` for `(user_id, app_package)`. Missing row or `health == expired` → task **failed** (no emulator).
4. **Emulator** — `EmulatorService` provisions a mock emulator (snapshot from session or Part 1 base), records `emulator_id` on the task, simulates execution (`MISSION_EXECUTE_SIM_SECONDS`).
5. **Identity gate** — With probability `MISSION_IDENTITY_GATE_PROBABILITY`, after simulated execution the task enters `identity_gate`. If `webhook_url` is set, an HTTP POST is sent (httpx, configurable timeouts). The task waits on an `asyncio.Event` until `POST .../approve` or until `MISSION_IDENTITY_GATE_TIMEOUT_SECONDS` elapses (failure).
6. **Teardown** — Emulator is destroyed so instances are not leaked.
7. **Mission state** — Derived from task states: any task `failed` → mission `failed`; all `done` → mission `done`; all `queued` → `queued`; else `running`.

## Identity gate coordination

Approve uses per `(mission_id, task_id)` in-memory `asyncio.Event` instances. This is correct for a **single process**. Multiple worker processes would need Redis, DB polling, or message bus for gate signaling.

## Configuration

Environment-driven settings are grouped in:

- `app/config.py` — `EMULATOR_`* (warm pool, boot times, health).
- `app/session_config.py` — `SESSION_*` (DB URL, tiers, worker tick, mock probability).
- `app/mission_config.py` — `MISSION_*` (gate probability, timeouts, webhook timeouts, simulation delay).

See the repository root `README.md` for variable tables.

## Extension points

- **Real emulators**: Implement provisioning/snapshot/destroy behind `EmulatorService` and keep route contracts stable.
- **Real session health**: Replace mock roll in `session_service` with OCR/VLM or device APIs; keep `re_auth_required` semantics if missions depend on it.
- **Durable mission queue**: Replace `BackgroundTasks` with Celery/RQ/SQS and an idempotent worker for crash recovery and horizontal scale.

## Related documents

- [DATA_MODEL.md](DATA_MODEL.md) — relational schema summary.
- [API.md](API.md) — HTTP reference.
- [ASSUMPTIONS_AND_LIMITATIONS.md](ASSUMPTIONS_AND_LIMITATIONS.md) — scope and limits.

