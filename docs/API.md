# API reference

## Base URL

| Environment | Example base URL |
|-------------|------------------|
| Docker Compose (this repo) | `http://localhost:8082` — host maps **`8082:8080`**. |
| Local Uvicorn | `http://localhost:8080` (or your `--port`). |

Use header **`Content-Type: application/json`** for request bodies where a body is required.

---

## System

### `GET /healthz`

**Purpose:** Liveness.

**Response** `200 OK`

```json
{ "status": "ok" }
```

---

## Emulators

**OpenAPI tag:** `emulators`

Behavior depends on **`EMULATOR_BACKEND`**: **`mock`** (simulated) vs **`sdk`** (real emulator + `adb`).

### `GET /emulators`

**Purpose:** List emulators tracked by this process.

**Query parameters**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `running_only` | boolean | `false` | If `true`, only **`RUNNING`** emulators. |

**Response** `200 OK` — JSON array of `EmulatorStatusResponse` (see status endpoint).

---

### `POST /emulators`

**Purpose:** Provision an emulator, optionally from a snapshot (defaults to base when omitted).

**Request body** (optional)

| Field | Type | Description |
|-------|------|-------------|
| `snapshot_id` | string \| null | Snapshot to restore; omit or `null` for default base. |

**Response** `200 OK` — `ProvisionEmulatorResponse`

| Field | Type |
|-------|------|
| `id` | string (e.g. `emu-…`) |
| `state` | string (e.g. `RUNNING`) |
| `restored_snapshot_id` | string \| null |
| `boot_seconds` | number |

**Errors:** `400` — invalid snapshot or input (`detail` in body).

---

### `GET /emulators/{emulator_id}/status`

**Response** `200 OK` — `EmulatorStatusResponse`

| Field | Type |
|-------|------|
| `id` | string |
| `state` | `CREATING`, `STARTING`, `RUNNING`, … |
| `current_snapshot_id` | string \| null |
| `assigned` | boolean |
| `pool_role` | string |
| `last_boot_seconds` | number \| null |
| `health_ok` | boolean |
| `consecutive_health_failures` | integer |
| `message` | string \| null |
| `adb_serial` | string \| null (SDK: e.g. `emulator-5554`) |

**Errors:** `404` — emulator not found.

---

### `POST /emulators/{emulator_id}/snapshot`

**Purpose:** Create a layered snapshot from a **running** emulator.

**Request body** — `CreateSnapshotRequest`

| Field | Type | Description |
|-------|------|-------------|
| `layer` | string | One of `base`, `app`, `session`. |
| `label` | string \| null | Optional label. |

**Response** `200 OK` — `CreateSnapshotResponse`

| Field | Type |
|-------|------|
| `snapshot_id` | string |
| `layer` | string |
| `parent_snapshot_id` | string \| null |

**Errors:** `404` — emulator not found. `409` / `400` — invalid state or input (`detail`).

---

### `DELETE /emulators/{emulator_id}`

**Purpose:** Tear down the emulator.

**Response** `204 No Content`

**Errors:** `404` — not found.

---

### `GET /internal/health-events`

**Purpose:** Debug — recent emulator health probe events.

**Query:** `limit` (default `50`).

**Response** `200 OK` — JSON with an `events` array.

---

## Sessions

**OpenAPI tag:** `sessions` — routes live under **`/users`**.

### `GET /users/{user_id}/sessions`

**Purpose:** List all sessions for a user.

**Response** `200 OK` — `SessionsListResponse`

- `user_id` (string)
- `sessions` — array of `SessionEntry` (`session_id`, `app_package`, `snapshot_id`, `health`, timestamps, `login_method`, `tier`, `re_auth_required`)

---

### `POST /users/{user_id}/sessions/{app_package}/verify`

**Purpose:** Touch the session and run the mock health check; creates **user** and **session** rows if missing.

**Path:** `app_package` is the Android package (e.g. `com.example.app`).

**Request body** (optional)

| Field | Type |
|-------|------|
| `login_method` | `otp` \| `sso` \| `password` \| omitted |
| `snapshot_id` | string \| null — bind this Part 1 snapshot to the session |

**Response** `200 OK` — `VerifySessionResponse`

| Field | Type |
|-------|------|
| `session_id` | integer |
| `observed` | string |
| `health` | string |
| `tier` | string |
| `re_auth_required` | boolean |

---

### `GET /users/{user_id}/sessions/{app_package}/health-history`

**Query:** `limit` (default `100`).

**Response** `200 OK` — `HealthHistoryResponse` (`user_id`, `app_package`, `events` chronological).

**Errors:** `404` — no session for that user/app.

---

## Missions

**OpenAPI tag:** `missions`

### `POST /missions`

**Request body** — `CreateMissionRequest`

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | string | Required. |
| `targets` | array | At least one `{ "app_package", "goal" }`. |
| `webhook_url` | string \| null | Optional; used for identity-gate notifications. |

**Response** `200 OK` — `CreateMissionResponse` (mission id, state, tasks with `task_id`, etc.).

---

### `GET /missions/{mission_id}`

**Response** `200 OK` — mission + tasks + `webhook_url`, `error_detail`. When `state` is `re_auth_required` (expired session for a targeted app), the body also includes **`re_auth_app_package`** and **`re_auth_login_method`** (from that app’s stored session / verify), and **`error_detail`** is set as soon as that happens (not only after the mission runner finishes). Per-task `re_auth_login_method` is set on the task in that state.

**Errors:** `404` — mission not found.

---

### `POST /missions/{mission_id}/tasks/{task_id}/approve`

**Purpose:** Resume a task blocked in **identity_gate** (no-op if not in that state).

**Response** `200 OK` — `ApproveMissionTaskResponse` (`mission_id`, `task_id`, `state`, `message`).

**Errors:** `404` — task not found.

---

### Identity gate webhook (outbound)

When a task enters `identity_gate` and the mission has `webhook_url`, the service **POST**s JSON like:

```json
{
  "event": "identity_gate",
  "mission_id": "<id>",
  "task_id": "<id>",
  "user_id": "<id>",
  "app_package": "<package>"
}
```

Delivery is best-effort; failures are logged.

---

## OpenAPI

| URL | Description |
|-----|-------------|
| `/docs` | Swagger UI |
| `/openapi.json` | OpenAPI schema |
