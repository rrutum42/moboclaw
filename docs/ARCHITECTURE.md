# Architecture

This document describes how the Moboclaw service is structured: entrypoint, layers, background work, and how missions interact with sessions and emulators.

## Process model

| Concern | Implementation |
|---------|----------------|
| **HTTP** | FastAPI (`app.main:app`), async lifespan: DB init → background workers. |
| **SQLite** | SQLAlchemy 2 async + `aiosqlite`: users, sessions, missions, tasks, health history. |
| **Part 1** | Emulators + snapshot **catalog** + warm queue: **in-memory** (`EmulatorService` / `InMemoryStore`). Not replicated across processes. |

## Code layout (MVC-style)

| Layer | Location | Role |
|-------|----------|------|
| Controllers | `app/controllers/` | Routes: `system`, `emulators`, `users_sessions`, `missions`. |
| Services | `app/services/` | Orchestration, warm pool, sessions, missions, SDK adapters. |
| DB | `app/db/` | Engine, deps, ORM, `init_db`, seed. |
| Schemas | `app/schemas/` | Pydantic API models (sessions, missions). |
| Part 1 models | `app/models.py`, `app/store.py` | Pydantic + in-memory emulator/snapshot state. |

## Background workers

Started from `app.background.start_background_workers()`:

1. **Emulator subsystem** — `emulator_service.start_background_tasks()`: warm pool fill, emulator health loop (`health_monitor`, `warm_pool`, …).
2. **Session health worker** — `session_health_run_loop`: polls every `SESSION_WORKER_TICK_SECONDS`, tier-based checks for hot/warm sessions.

Shutdown: cancel session worker task; stop emulator background tasks.

## Mission pipeline (summary)

1. **Create** — `POST /missions` persists mission + tasks; schedules `mission_service.safe_run_mission` via `BackgroundTasks`.
2. **Group by app** — Targets grouped by `app_package`. Each group = one asyncio task; groups run **concurrently** (`asyncio.gather`). Inside a group, tasks run **in order** of the `targets` list.
3. **Session gate** — Load `user_sessions` for `(user_id, app_package)`. Missing row or `health == expired` → task **failed** (no emulator).
4. **Emulator** — `EmulatorService.provision` using session `snapshot_id` or Part 1 base; task stores `emulator_id`; simulated work (`MISSION_EXECUTE_SIM_SECONDS`).
5. **Identity gate** — With probability `MISSION_IDENTITY_GATE_PROBABILITY`, task pauses in `identity_gate`; optional webhook POST; wait for `POST .../approve` or timeout.
6. **Teardown** — Destroy emulator.
7. **Mission state** — Derived from task states (any failed → mission failed; all done → done; etc.).

Details: parallel chains and gate behavior in code (`app/services/mission_service.py`).

## Identity gate (single process)

Approve uses in-memory `asyncio.Event` per `(mission_id, task_id)`. **Single replica only**; multiple workers would need Redis/DB/messages for coordination.

## Configuration

| Module | Prefix | Contents |
|--------|--------|----------|
| `app/config.py` | `EMULATOR_*` | Backend, AVD, warm pool, health, SDK paths. |
| `app/session_config.py` | `SESSION_*` | DB URL, tiers, worker tick, mock probability. |
| `app/mission_config.py` | `MISSION_*` | Gate probability, timeouts, webhook timeouts, sim delay. |

Full tables: root **`README.md`**.

## Extension points

- **Real device farm** — Keep route contracts; swap provisioning/snapshot/teardown behind `EmulatorService`.
- **Real session health** — Replace mock roll in `session_service` with device/vision signals; keep `re_auth_required` if missions depend on it.
- **Durable mission queue** — Replace `BackgroundTasks` with a queue worker for crash recovery and horizontal scale.

## Related docs

- [DATA_MODEL.md](DATA_MODEL.md) — SQLite tables.
- [API.md](API.md) — HTTP reference.
- [ASSUMPTIONS_AND_LIMITATIONS.md](ASSUMPTIONS_AND_LIMITATIONS.md) — Scope and limits.
