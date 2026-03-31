# Mobile Agent Infrastructure

This repo implements the take-home in parts. **Part 1 (emulator orchestration)**, **Part 2 (session lifecycle)**, and **Part 3 (mission pipeline)** run in the same FastAPI app under `app/`.

## Part 1: Emulator orchestration (prototype)

The default backend is **mock** (simulated delays, no real devices). Set **`EMULATOR_BACKEND=sdk`** to run **real Android Emulator** processes using the same **Android SDK** layout as the CLI (`$ANDROID_HOME/emulator/emulator` and `$ANDROID_HOME/platform-tools/adb`). The warm pool starts one process per slot (see `EMULATOR_WARM_POOL_SIZE`); each instance uses **`-read-only`** so multiple concurrent emulators can share one AVD image. **Docker Compose** does not include the Android SDK—use **mock** in containers, or run **`sdk` on the host** where Studio / `sdkmanager` / `avdmanager` are installed.

### Code layout (`app/`) — MVC-style

| Layer | Module | Responsibility |
|-------|--------|----------------|
| **Entry** | `main.py` | FastAPI app, lifespan, routers. |
| **Controller** | `controllers/system.py`, `emulators.py`, `users_sessions.py`, `missions.py` | HTTP routes. |
| **Service** | `emulator_service`, `warm_pool`, `health_monitor`, `emulator_backend`, `android_sdk_emulator`, `snapshot_capture`, `emulator_lifecycle`, `snapshots`, `simulation`, `ids` | Part 1 emulator orchestration. |
| | `session_service`, `session_health_worker` | Part 2 sessions + tiered health worker. |
| | `mission_service` | Part 3 missions (scheduler, identity gate, webhooks). |
| **DB** | `db/engine.py`, `db/orm.py`, `db/init_db.py`, `db/deps.py` | Async SQLAlchemy + **SQLite** (`aiosqlite`). |
| **Schemas** | `schemas/sessions.py`, `schemas/missions.py` | Part 2 / Part 3 API models. |
| **Model** | `models.py`, `store.py` | Part 1 Pydantic + in-memory emulators. |
| **Config** | `config.py`, `session_config.py`, `mission_config.py` | `EMULATOR_*`, `SESSION_*`, and `MISSION_*`. |

### Run with Docker Compose

From this directory:

Compose runs the **API** on **8082** and persists the SQLite file on a **volume** at `/app/data/sessions.db` in the container.

```bash
docker compose up --build
```

Detached (recommended):

```bash
docker compose up -d --build
```

**Host port:** the URL uses the **left** side of `ports:` in `docker-compose.yml`. This repo maps **`8082:8080`**, so the API is at **`http://localhost:8082`** (inside the container Uvicorn still listens on **8080**).

The **warm pool** fills in the background (three cold boots ≈ 25s). **`/healthz` and session APIs respond as soon as the process starts**; `POST /emulators` uses the warm pool when ready, otherwise it **cold-boots** until the pool is full.

Check:

```bash
curl -sS http://127.0.0.1:8082/healthz
```

Expected: `{"status":"ok"}`.

OpenAPI UI: `http://localhost:8082/docs`

#### Docker Compose with **real** Android emulators (`EMULATOR_BACKEND=sdk`)

The default Compose file uses the **mock** emulator backend. To run **Linux** Android Emulator binaries **inside** the container (suitable for CI or Docker Desktop), use the second Compose file and **`Dockerfile.sdk`**:

```bash
docker compose -f docker-compose.yml -f docker-compose.sdk.yml up --build
```

The first image build downloads the Android command-line tools, emulator, platform, and a system image (large download; often 10+ minutes). The service sets **`EMULATOR_WARM_POOL_SIZE=1`** by default in `docker-compose.sdk.yml` because each slot is a full VM. **`shm_size: 2gb`** is set for the emulator.

On **Linux** hosts, you can uncomment **`devices: /dev/kvm`** in `docker-compose.sdk.yml` for hardware acceleration. **Docker Desktop for Mac** does not expose `/dev/kvm`; emulators use software rendering and are slower. You cannot mount a **macOS** host `~/Library/Android/sdk` into a Linux container and run those binaries—the image installs a **Linux** SDK at **`/opt/android-sdk`**.

### Run locally (without Docker)

From this directory (`moboclaw/`):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Use another port if **8080** is already taken (e.g. Java on your machine), e.g. `--port 8081`.

Part 2 uses **SQLite** by default (`./sessions.db` next to the app, or `/app/data/sessions.db` in Docker). Override with `SESSION_DATABASE_URL` if needed.

### Environment variables — sessions (prefix `SESSION_`)

| Variable | Default | Role |
|----------|---------|------|
| `SESSION_DATABASE_URL` | `sqlite+aiosqlite:///./sessions.db` | Async SQLAlchemy URL. Docker uses `sqlite+aiosqlite:////app/data/sessions.db`. |
| `SESSION_SEED_DUMMY_ON_EMPTY` | `false` | If `true`, inserts demo users/sessions when the DB has no rows in `users` (Compose sets this to `true`). |
| `SESSION_TIER_HOT_ACCESS_SECONDS` | `86400` | Recency window for **hot** tier. |
| `SESSION_TIER_WARM_ACCESS_SECONDS` | `604800` | Upper bound for **warm** tier. |
| `SESSION_HOT_CHECK_INTERVAL_SECONDS` | `86400` | Auto check interval for **hot** sessions. |
| `SESSION_WARM_CHECK_INTERVAL_SECONDS` | `604800` | Auto interval for **warm** (**cold** only via `verify`). |
| `SESSION_WORKER_TICK_SECONDS` | `30` | Session worker poll interval. |
| `SESSION_MOCK_LOGGED_IN_PROBABILITY` | `0.8` | Mock vision: P(logged-in). |

### Environment variables (prefix `EMULATOR_`)

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND` | `mock` | `mock` = simulated delays; **`sdk`** = real `emulator` + `adb` (requires `ANDROID_HOME` / `ANDROID_SDK_ROOT`). |
| `EMULATOR_ANDROID_SDK_ROOT` | _(unset)_ | Optional SDK root override; if unset, **`ANDROID_SDK_ROOT`** or **`ANDROID_HOME`** is used. |
| `AVD_NAME` | `Pixel_6_API_34` | AVD name as shown by `emulator -list-avds` / **Device Manager**. |
| `EMULATOR_EMULATOR_BINARY` / `EMULATOR_ADB_BINARY` | _(unset)_ | Override paths to `emulator` and `adb` if not under the default SDK layout. |
| `EMULATOR_EMULATOR_EXTRA_ARGS` | _(see `config.py`)_ | Extra CLI args for each emulator (quoted list: `-no-window -no-audio` …). |
| `EMULATOR_EMULATOR_PORT_START` | `5554` | First **console** port; additional instances use +2, +4, … (`emulator-5554`, …). |
| `EMULATOR_EMULATOR_BOOT_COMPLETED_TIMEOUT_SECONDS` | `420` | Max wait for `sys.boot_completed=1` after `adb` sees the serial. |
| `WARM_POOL_SIZE` | `3` | Target count of **warm idle** emulators (base snapshot, ready to assign). |
| `RESTORE_FROM_SNAPSHOT_SECONDS` | `2.5` | **Mock only:** simulated boot when assigning from the warm pool. |
| `COLD_BOOT_SECONDS` | `8` | **Mock only:** simulated cold boot when the pool is empty. |
| `HEALTH_CHECK_INTERVAL_SECONDS` | `3` | Background health loop interval. |
| `MOCK_UNHEALTHY_PROBABILITY` | `0.05` | **Mock only:** chance a probe fails. With **`sdk`**, health uses **`adb shell getprop sys.boot_completed`**. |
| `MAX_HEALTH_FAILURES_BEFORE_REPLACE` | `2` | Consecutive failures before **auto-replace** (destroy + replenish warm pool). |

**SDK prerequisites (host):** install **Android SDK Command-line Tools**, **platform-tools**, **emulator**, and a **system image**; create an AVD (e.g. `avdmanager create avd` or Android Studio).

On **macOS**, you can install the usual CLI pieces and create a default AVD with Homebrew via:

```bash
./scripts/install_android_emulator_prereqs_mac.sh
```

(Requires [Homebrew](https://brew.sh); installs Temurin JDK if needed, the Android command-line tools cask, copies **cmdline-tools** into **`ANDROID_HOME`**—a symlink to Homebrew’s tree breaks **`avdmanager`**—then runs `sdkmanager` and creates an AVD named `Pixel_6_API_34` unless you override `AVD_NAME` / `API_LEVEL`.)

Then run the API with the SDK backend, for example:

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"   # macOS typical path
export EMULATOR_BACKEND=sdk
export EMULATOR_AVD_NAME=Your_Avd_Name
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### Layered snapshots

With **`EMULATOR_BACKEND=sdk`**, `POST /emulators/{id}/snapshot` runs **`adb emu avd snapshot save`** and stores the AVD snapshot name in **`metadata.sdk_snapshot_name`**. Provisioning from that snapshot uses **`adb emu avd snapshot load`** (warm) or **`-snapshot`** on a cold boot. Snapshots created in **mock** mode cannot be restored on **sdk** until you capture them again on a device.

In **mock** mode, the same API is simulated:

1. **Base** — seeded `snap-base-default` (“clean Android”) on startup.
2. **App** — `POST /emulators/{id}/snapshot` with `layer: "app"`.
3. **Session** — same endpoint with `layer: "session"` (per-user login state in a real system).

Each snapshot stores `parent_snapshot_id` so the chain base → app → session is explicit.

### API

#### `POST /emulators`

Provision an emulator **restored from** a snapshot (defaults to base).

**Request (optional body):**

```json
{
  "snapshot_id": "snap-base-default"
}
```

**Response:**

```json
{
  "id": "emu-…",
  "state": "RUNNING",
  "restored_snapshot_id": "snap-base-default",
  "boot_seconds": 2.51
}
```

#### `GET /emulators/{id}/status`

**Response:**

```json
{
  "id": "emu-…",
  "state": "RUNNING",
  "current_snapshot_id": "snap-…",
  "assigned": true,
  "pool_role": "provisioned",
  "last_boot_seconds": 2.51,
  "health_ok": true,
  "consecutive_health_failures": 0,
  "message": null
}
```

#### `POST /emulators/{id}/snapshot`

**Request:**

```json
{
  "layer": "app",
  "label": "optional"
}
```

`layer` is one of `base`, `app`, `session`.

**Response:**

```json
{
  "snapshot_id": "snap-…",
  "layer": "app",
  "parent_snapshot_id": "snap-base-default"
}
```

#### `DELETE /emulators/{id}`

Tears down the emulator (204 No Content).

#### `GET /healthz`

Service liveness.

#### `GET /internal/health-events` (debug)

Recent mock health probe events for demos.

---

## Part 2: Session lifecycle (SQLite)

- **Data model (tables, SQL DDL, ORM relationships):** [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md).
- **Model:** `users`, `user_sessions` (auto-increment integer `id` returned as `session_id`, snapshot ref, health `alive|expired|unknown`, login method `otp|sso|password`, tier `hot|warm|cold`), `session_health_history`.
- **Tiering:** `last_access_at` drives tier: within `SESSION_TIER_HOT_ACCESS_SECONDS` → hot; within `SESSION_TIER_WARM_ACCESS_SECONDS` → warm; else cold. Cold tiers are **not** auto-checked by the worker; use `verify`.
- **Mock health:** each verify / scheduled check rolls **80%** logged-in / **20%** expired (`SESSION_MOCK_LOGGED_IN_PROBABILITY`).
- **`re_auth_required`:** `true` when health is `expired` (for Part 3 missions).

### Part 2 API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/users/{user_id}/sessions` | List sessions with `re_auth_required`. |
| POST | `/users/{user_id}/sessions/{app_package}/verify` | Touch session + run mock check; creates user/session if missing. Optional JSON: `{"login_method":"otp","snapshot_id":"snap-..."}`. |
| GET | `/users/{user_id}/sessions/{app_package}/health-history?limit=100` | Check history (newest first in DB; response is chronological). |

### Example flow

Matches Docker Compose host port **`8082`** (see `docker-compose.yml`). For local uvicorn on **8080**, change the base URL.

```bash
BASE=http://localhost:8082
# 1) Provision from base (uses warm pool when available)
curl -s -X POST "$BASE/emulators" -H 'Content-Type: application/json' -d '{}' | jq

# 2) Save an “app” layer snapshot
EMU_ID=$(curl -s -X POST "$BASE/emulators" -H 'Content-Type: application/json' -d '{}' | jq -r .id)
curl -s -X POST "$BASE/emulators/$EMU_ID/snapshot" \
  -H 'Content-Type: application/json' \
  -d '{"layer":"app","label":"makemytrip"}' | jq

# 3) Provision a second emulator from that snapshot (session restore &lt; 30s in mock)
SNAP=$(curl -s -X POST "$BASE/emulators/$EMU_ID/snapshot" -H 'Content-Type: application/json' -d '{"layer":"session"}' | jq -r .snapshot_id)
curl -s -X POST "$BASE/emulators" -H 'Content-Type: application/json' \
  -d "{\"snapshot_id\":\"$SNAP\"}" | jq

# 4) Tear down
curl -s -X DELETE "$BASE/emulators/$EMU_ID" -v
```

OpenAPI docs: `http://localhost:8082/docs`

---

## Part 3: Mission execution pipeline (SQLite)

- **Persistence:** `missions`, `mission_tasks` (see ORM in [`app/db/orm.py`](app/db/orm.py)).
- **Scheduling:** `targets` is an ordered list of `{ app_package, goal }`. Tasks for the **same** `app_package` run **one after another** in list order. **Different** apps run **in parallel** (each app’s chain runs in its own coroutine; `asyncio.gather`).
- **Sessions:** Before allocating an emulator, the service loads `user_sessions` for `(user_id, app_package)`. **No row** or **`health: expired`** → task **FAILED** (no emulator provisioned). Other health values proceed; snapshot comes from `snapshot_id` or falls back to the Part 1 base snapshot `snap-base-default`.
- **Emulators:** Each task **provisions** a mock emulator, simulates execution, optionally hits the **identity gate**, then **destroys** the emulator so instances are not leaked.
- **Identity gate:** With probability `MISSION_IDENTITY_GATE_PROBABILITY` (default **0.3**), a task pauses in `IDENTITY_GATE`. If `webhook_url` is set on the mission, the service **POSTs** JSON `{"event":"identity_gate","mission_id",...}` (best-effort; failures are logged). **`POST /missions/{mission_id}/tasks/{task_id}/approve`** signals resume. **Timeout** `MISSION_IDENTITY_GATE_TIMEOUT_SECONDS` (default **300**) → task **FAILED** (`identity_gate timeout`).
- **Mission state:** Aggregated from tasks: **failed** if any task failed; **done** if all **done**; **running** while work is in progress; **queued** only before the background runner starts.

### Environment variables — missions (prefix `MISSION_`)

| Variable | Default | Role |
|----------|---------|------|
| `MISSION_IDENTITY_GATE_PROBABILITY` | `0.3` | Chance a task enters `IDENTITY_GATE` after simulated execution. |
| `MISSION_IDENTITY_GATE_TIMEOUT_SECONDS` | `300` | Max wait for approve (5 minutes). |
| `MISSION_WEBHOOK_CONNECT_TIMEOUT_SECONDS` | `5` | Outbound webhook connect timeout. |
| `MISSION_WEBHOOK_READ_TIMEOUT_SECONDS` | `15` | Outbound webhook read/write timeout. |
| `MISSION_EXECUTE_SIM_SECONDS` | `0.8` | Simulated “agent execution” delay per task. |

### Part 3 API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/missions` | Create mission: `user_id`, `targets[]`, optional `webhook_url`. Returns `mission_id` and per-task `task_id` (string UUIDs). |
| GET | `/missions/{mission_id}` | Mission aggregate state + all tasks. |
| POST | `/missions/{mission_id}/tasks/{task_id}/approve` | Resume after identity gate (idempotent if not in gate). |

### Example: mission with two apps (parallel chains)

Use a user that has **verified sessions** for each `app_package` (see Part 2 `verify`). Compose host port **8082**; change `BASE` if needed.

**Request — `POST /missions`**

```json
{
  "user_id": "demo-user-alpha",
  "targets": [
    { "app_package": "com.shop.retail", "goal": "search headphones" },
    { "app_package": "com.news.reader", "goal": "open top story" }
  ],
  "webhook_url": "http://host.docker.internal:9999/hook"
}
```

**Response (illustrative)**

```json
{
  "mission_id": "b1c2d3e4-...",
  "user_id": "demo-user-alpha",
  "state": "queued",
  "tasks": [
    {
      "task_id": "a0f1...",
      "sequence": 0,
      "app_package": "com.shop.retail",
      "goal": "search headphones",
      "state": "queued",
      "emulator_id": null,
      "error_message": null,
      "identity_gate_notified_at": null,
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

**`GET /missions/{mission_id}`** — Same task fields plus mission `state`, `error_detail`, `webhook_url`.

**`POST /missions/{mission_id}/tasks/{task_id}/approve`**

```json
{
  "mission_id": "b1c2d3e4-...",
  "task_id": "a0f1...",
  "state": "identity_gate",
  "message": "resume signaled"
}
```

If the task is not in `identity_gate`, `message` is `not in identity_gate; no-op` and `state` reflects the current task state.

### curl sketch

```bash
BASE=http://localhost:8082
# Ensure session exists and is not expired for each app (see Part 2 verify)
curl -s -X POST "$BASE/users/demo-user-alpha/sessions/com.shop.retail/verify" \
  -H 'Content-Type: application/json' -d '{"login_method":"otp"}' | jq

MID=$(curl -s -X POST "$BASE/missions" -H 'Content-Type: application/json' \
  -d '{"user_id":"demo-user-alpha","targets":[{"app_package":"com.shop.retail","goal":"demo"}]}' | jq -r .mission_id)

curl -s "$BASE/missions/$MID" | jq
```

Set `MISSION_IDENTITY_GATE_PROBABILITY=0` locally to skip the gate for quick runs.

---

## Documentation (architecture and API)

- **[docs/README.md](docs/README.md)** — Documentation index, overview, and system diagram.
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — Components, background workers, mission pipeline, extension points.
- **[docs/API.md](docs/API.md)** — HTTP API reference.
- **[docs/ASSUMPTIONS_AND_LIMITATIONS.md](docs/ASSUMPTIONS_AND_LIMITATIONS.md)** — Assumptions and known limits.
- **[docs/DATA_MODEL.md](docs/DATA_MODEL.md)** — SQLite schema summary.

Optional: `scripts/build_design_pdf.py` can generate a PDF when placeholder images exist under `docs/` (see script header).
