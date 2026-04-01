# Moboclaw — Mobile Agent Infrastructure

FastAPI service with three features in one app:

| Part | Topic | Storage |
|------|--------|---------|
| **1** | Emulator orchestration (mock or real Android SDK) | In-memory emulators + snapshot catalog |
| **2** | Per-user, per-app **sessions** (tiered health, verify) | SQLite |
| **3** | **Missions** (tasks, identity gate, webhooks) | SQLite |

**Detailed docs:** [docs/README.md](docs/README.md) (index), [docs/LOCAL.md](docs/LOCAL.md) (run locally), [docs/API.md](docs/API.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATA_MODEL.md](docs/DATA_MODEL.md), [docs/ASSUMPTIONS_AND_LIMITATIONS.md](docs/ASSUMPTIONS_AND_LIMITATIONS.md).

---

## Table of contents

1. [Quick start](#quick-start) — Docker Compose and local Uvicorn  
2. [Configuration](#configuration) — env vars (sessions, emulators, missions)  
3. [Part 1: Emulators](#part-1-emulators-orchestration) — mock vs SDK, disk, snapshots, API  
4. [Part 2: Sessions](#part-2-sessions) — model, API, example curl  
5. [Part 3: Missions](#part-3-missions) — behavior, API, example  
6. [Scripts](#helper-scripts) — optional host setup  

---

## Quick start

### Docker Compose

From the `moboclaw/` directory:

```bash
docker compose up --build
# or detached:
docker compose up -d --build
```

- **API on host:** `http://localhost:8082` (maps host **8082** → container **8080**).  
- **Health:** `curl -sS http://127.0.0.1:8082/healthz` → `{"status":"ok"}`.  
- **OpenAPI:** `http://localhost:8082/docs`  

Compose uses the **mock** emulator backend unless you override env. Android SDK is **not** in the default image.

### Local (no Docker)

```bash
cd moboclaw
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

SQLite defaults to `./sessions.db` (or `/app/data/sessions.db` in Docker). Override with `SESSION_DATABASE_URL`.

**Step-by-step on your laptop** (venv, `EMULATOR_BACKEND=mock` vs `sdk`, `ANDROID_HOME`, golden AVD): [docs/LOCAL.md](docs/LOCAL.md).

---

## Configuration

### Sessions (`SESSION_*`)

| Variable | Default | Role |
|----------|---------|------|
| `SESSION_DATABASE_URL` | `sqlite+aiosqlite:///./sessions.db` | Async SQLAlchemy URL |
| `SESSION_SEED_DUMMY_ON_EMPTY` | `false` | Seed demo users/sessions when `users` is empty (Compose may set `true`) |
| `SESSION_TIER_HOT_ACCESS_SECONDS` | `86400` | Hot tier window |
| `SESSION_TIER_WARM_ACCESS_SECONDS` | `604800` | Warm tier upper bound |
| `SESSION_HOT_CHECK_INTERVAL_SECONDS` | `86400` | Auto-check interval for hot |
| `SESSION_WARM_CHECK_INTERVAL_SECONDS` | `604800` | Auto-check for warm (cold only via verify) |
| `SESSION_WORKER_TICK_SECONDS` | `30` | Session worker poll interval |
| `SESSION_MOCK_LOGGED_IN_PROBABILITY` | `0.8` | Mock “logged in” probability on verify/check |

### Emulators (`EMULATOR_*` and related)

| Variable | Default | Role |
|----------|---------|------|
| `EMULATOR_BACKEND` / `BACKEND` | `mock` | `mock` = simulated; **`sdk`** = real `emulator` + `adb` |
| `EMULATOR_ANDROID_SDK_ROOT` | _(unset)_ | Overrides `ANDROID_SDK_ROOT` / `ANDROID_HOME` |
| `EMULATOR_AVD_NAME` | `Pixel_6_API_34` | Golden AVD name (`emulator -list-avds`) |
| `EMULATOR_EMULATOR_BINARY` / `EMULATOR_ADB_BINARY` | _(unset)_ | Override binary paths |
| `EMULATOR_EMULATOR_EXTRA_ARGS` | _(see `config.py`)_ | Extra emulator CLI args |
| `EMULATOR_EMULATOR_UI_MODE` | `headless` | Set **`window`** to show UI (strips `-no-window`) |
| `EMULATOR_QCOW2_SESSION_ROOT` | _(unset)_ | Session + branch clones; default **`<cwd>/.moboclaw_qcow2_sessions`** |
| `EMULATOR_EMULATOR_PORT_START` | `5554` | First console port (`emulator-5554`, …) |
| `EMULATOR_EMULATOR_BOOT_COMPLETED_TIMEOUT_SECONDS` | `420` | Max wait for `sys.boot_completed=1` |
| `EMULATOR_WARM_POOL_SIZE` | `3` | Target warm idle emulators (base snapshot) |
| `EMULATOR_WARM_BOOT_READ_ONLY` | `false` | If `true`, warm boots read-only (no userdata writes for installs) |
| `EMULATOR_RESTORE_FROM_SNAPSHOT_SECONDS` | `2.5` | **Mock:** warm restore delay |
| `EMULATOR_COLD_BOOT_SECONDS` | `8` | **Mock:** cold boot delay |
| `EMULATOR_HEALTH_CHECK_INTERVAL_SECONDS` | `3` | Health loop interval |
| `EMULATOR_MOCK_UNHEALTHY_PROBABILITY` | `0.05` | **Mock:** random probe failure |
| `EMULATOR_MAX_HEALTH_FAILURES_BEFORE_REPLACE` | `2` | Consecutive failures → replace emulator |

**SDK on the host:** install command-line tools, platform-tools, emulator, system image; create an AVD. Optional macOS helper: `./scripts/install_android_emulator_prereqs_mac.sh`. Recommended once: `./scripts/host_setup_moboclaw_sdk_once.sh` (clears session cache, checks/repairs golden `userdata` qcow2 — see script header).

Example:

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$PATH"
export EMULATOR_BACKEND=sdk
export EMULATOR_AVD_NAME=Pixel_6_API_34
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### Missions (`MISSION_*`)

| Variable | Default | Role |
|----------|---------|------|
| `MISSION_IDENTITY_GATE_PROBABILITY` | `0.3` | Chance a task enters identity gate after “execution” |
| `MISSION_IDENTITY_GATE_TIMEOUT_SECONDS` | `300` | Approve timeout |
| `MISSION_WEBHOOK_CONNECT_TIMEOUT_SECONDS` | `5` | Webhook connect timeout |
| `MISSION_WEBHOOK_READ_TIMEOUT_SECONDS` | `15` | Webhook read/write timeout |
| `MISSION_EXECUTE_SIM_SECONDS` | `0.8` | Simulated work delay per task |

---

## Part 1: Emulator orchestration

### Mock vs SDK

- **`mock`** — No devices; simulated boot/health. Good for CI and Docker without SDK.  
- **`sdk`** — Spawns real **`emulator`** and uses **`adb`**. Each instance uses a **full clone** of the golden AVD under **`EMULATOR_QCOW2_SESSION_ROOT`** (default `.moboclaw_qcow2_sessions` in the process CWD). **Branch snapshots** copy another full tree under `branches/<snapshot_id>/`. **Disk usage is large**; use **`EMULATOR_WARM_POOL_SIZE=1`** while testing on a small disk.

### Layered snapshots (SDK)

`POST /emulators/{id}/snapshot` does **not** use `adb emu avd snapshot save`. The service stops the emulator, syncs best-effort, may **`qemu-img commit`** on `userdata-qemu.img.qcow2`, then **copies** the session AVD tree to `branches/<snapshot_id>/`. Metadata includes clone paths for the next provision. The captured instance is torn down after save.

**Mock** mode simulates the same API without real disk artifacts; base snapshot **`snap-base-default`** is seeded in memory on startup.

### Disk and OOM

- **`No space left on device`:** free disk; remove old trees under **`EMULATOR_QCOW2_SESSION_ROOT`**.  
- **Signal 9 (OOM):** reduce concurrent emulators; **`EMULATOR_WARM_POOL_SIZE=1`**.  
- **Conflicting `adb` serial:** quit other emulators; avoid two processes using the same golden AVD read-write.

### Code layout (`app/`)

| Layer | Modules |
|-------|---------|
| Entry | `main.py` |
| Controllers | `controllers/system.py`, `emulators.py`, `users_sessions.py`, `missions.py` |
| Services (Part 1) | `emulator_service`, `warm_pool`, `health_monitor`, `emulator_backend`, `android_sdk_emulator`, `qcow2_avd`, `qcow2_metadata`, `snapshot_capture`, `emulator_lifecycle`, `snapshots`, `ids` |
| Services (Part 2–3) | `session_service`, `session_health_worker`, `mission_service` |
| DB | `db/engine.py`, `orm.py`, `init_db.py`, `deps.py` |
| Models | `models.py` (Pydantic), `store.py` (in-memory) |

### Part 1 API (summary)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/emulators` | List emulators; `?running_only=true` for RUNNING only |
| `POST` | `/emulators` | Provision (`{"snapshot_id": "…"}` optional) |
| `GET` | `/emulators/{id}/status` | Status |
| `POST` | `/emulators/{id}/snapshot` | Layered snapshot (`layer`: `base` \| `app` \| `session`) |
| `DELETE` | `/emulators/{id}` | Tear down |
| `GET` | `/healthz` | Liveness |
| `GET` | `/internal/health-events` | Debug health events |

**Example (mock, Compose on 8082):**

```bash
BASE=http://localhost:8082
curl -sS -X POST "$BASE/emulators" -H 'Content-Type: application/json' -d '{}' | jq
EMU=$(curl -sS -X POST "$BASE/emulators" -H 'Content-Type: application/json' -d '{}' | jq -r .id)
curl -sS -X POST "$BASE/emulators/$EMU/snapshot" \
  -H 'Content-Type: application/json' \
  -d '{"layer":"app","label":"makemytrip"}' | jq
SNAP=$(curl -sS -X POST "$BASE/emulators/$EMU/snapshot" \
  -H 'Content-Type: application/json' \
  -d '{"layer":"session"}' | jq -r .snapshot_id)
curl -sS -X POST "$BASE/emulators" -H 'Content-Type: application/json' \
  -d "{\"snapshot_id\":\"$SNAP\"}" | jq
curl -sS -X DELETE "$BASE/emulators/$EMU" -v
```

### Docker: SDK inside Linux container

For emulators **inside** Docker (Linux image), use:

```bash
docker compose -f docker-compose.yml -f docker-compose.sdk.yml up --build
```

First build downloads SDK pieces (often 10+ minutes). **macOS** cannot reuse a host macOS SDK inside a Linux container. **`/dev/kvm`** is available on Linux hosts only.

---

## Part 2: Sessions

- **Schema:** [docs/DATA_MODEL.md](docs/DATA_MODEL.md).  
- **Behavior:** One row per `(user_id, app_package)`; tiering from `last_access_at`; mock health on **verify**; **`re_auth_required`** when health is `expired` (blocks Part 3 tasks).
- **Snapshot catalog:** Each emulator snapshot is stored in **`snapshots`** (SQLite) with the same **`id`** as the orchestrator (`SnapshotRecord`). On startup, rows are **loaded into** the in-memory store so provision works after restart. When you send **`snapshot_id`** on verify, it must already exist in that catalog (typically captured via `POST /emulators/{id}/snapshot`).

### Part 2 API

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/users` | Mint a **new** user; response `{"user_id":"<uuid>"}` (HTTP 201). |
| `GET` | `/users/{user_id}/sessions` | List sessions |
| `POST` | `/users/{user_id}/sessions/{app_package}/verify` | Verify / touch session; optional `{"login_method","snapshot_id"}`. If `snapshot_id` is set, it must be a known snapshot id. |
| `GET` | `/users/{user_id}/sessions/{app_package}/health-history` | Health history (`?limit=`) |

`user_id` is usually the UUID returned by **`POST /users`**. The service can still create the **user** row on first **verify** if you pass an existing id (e.g. demo seeds).

---

## Part 3: Missions

- Tasks need a **non-expired** session per `app_package`.  
- Different apps run **in parallel**; same app’s tasks run **in order**.  
- Each task **provisions** an emulator, simulates work, may enter **identity gate** (webhook + approve), then **destroys** the emulator.

### Part 3 API

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/missions` | Create mission (`user_id`, `targets[]`, optional `webhook_url`) |
| `GET` | `/missions/{mission_id}` | Mission + tasks |
| `POST` | `/missions/{mission_id}/tasks/{task_id}/approve` | Resume after identity gate |

**Example curl:**

```bash
BASE=http://localhost:8082

# Optional: mint a user (or use seeded demo-user-alpha when SESSION_SEED_DUMMY_ON_EMPTY=true)
curl -sS -X POST "$BASE/users" | jq

curl -sS -X POST "$BASE/users/demo-user-alpha/sessions/com.shop.retail/verify" \
  -H 'Content-Type: application/json' -d '{"login_method":"otp"}' | jq

MID=$(curl -sS -X POST "$BASE/missions" -H 'Content-Type: application/json' \
  -d '{"user_id":"demo-user-alpha","targets":[{"app_package":"com.shop.retail","goal":"demo"}]}' \
  | jq -r .mission_id)

curl -sS "$BASE/missions/$MID" | jq
```

Set `MISSION_IDENTITY_GATE_PROBABILITY=0` to skip the gate for quick runs.

---

## Helper scripts (`scripts/`)

### AVD / Android SDK setup (host)

| Script | Purpose |
|--------|---------|
| `scripts/install_android_emulator_prereqs_mac.sh` | **macOS + Homebrew:** JDK, cmdline-tools, `sdkmanager` packages, creates default AVD (`AVD_NAME` / `API_LEVEL` overridable). |
| `scripts/host_setup_moboclaw_sdk_once.sh` | **Before first `sdk` run:** optional macOS install, wipe `.moboclaw_qcow2_sessions`, `qemu-img check` + userdata/qcow2 repair for the **golden** AVD (`SKIP_MAC_SDK_INSTALL=1` = cache clear + repair only). |
| `scripts/recreate_golden_avd.sh` | **Clean slate:** remove session cache, delete and **recreate** golden AVD, then userdata repair; use if the base AVD is corrupt. |

### API smoke tests (API must be running)

| Script | Purpose |
|--------|---------|
| `scripts/test_sessions.sh` | Curl: provision/list emulator, snapshot, verify session (`BASE` / `APP`). |
| `scripts/snapshot_app_then_provision.sh` | Snapshot a **running** emulator at **app** layer, then provision another from that snapshot (`BASE_URL`). |

### Other

| Script | Purpose |
|--------|---------|
| `scripts/build_design_pdf.py` | Design PDF when placeholder images exist under `docs/` (see script header). |

Full context: [docs/LOCAL.md](docs/LOCAL.md).
