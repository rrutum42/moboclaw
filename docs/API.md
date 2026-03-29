# API reference

Base URL examples:

- **Docker Compose** (this repo): `http://localhost:8082` (host maps `8082:8080`).
- **Local uvicorn**: `http://localhost:8080` unless you pass another `--port`.

All JSON bodies use `Content-Type: application/json` where a body is shown.

---

## System

### `GET /healthz`

Liveness probe.

**Response** `200 OK`

```json
{
  "status": "ok"
}
```

---

## Emulators (mock orchestration)

Tag: `emulators`

### `POST /emulators`

Provision an emulator, optionally restored from a snapshot (defaults to base snapshot when omitted).

**Request body** (optional; defaults to empty object)

| Field | Type | Description |
|-------|------|-------------|
| `snapshot_id` | string \| null | Snapshot to restore from; omit or null for default base. |

**Response** `200 OK` — `ProvisionEmulatorResponse`

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Emulator id (e.g. `emu-…`). |
| `state` | string | e.g. `RUNNING`. |
| `restored_snapshot_id` | string \| null | Snapshot used for restore. |
| `boot_seconds` | number | Simulated boot/restore time. |

**Errors**

- `400` — invalid snapshot or bad input (`detail` string).

---

### `GET /emulators/{emulator_id}/status`

**Response** `200 OK` — `EmulatorStatusResponse`

| Field | Type |
|-------|------|
| `id` | string |
| `state` | enum: `CREATING`, `STARTING`, `RUNNING`, `SNAPSHOTTING`, `STOPPING`, `STOPPED`, `FAILED`, `DESTROYED` |
| `current_snapshot_id` | string \| null |
| `assigned` | boolean |
| `pool_role` | string |
| `last_boot_seconds` | number \| null |
| `health_ok` | boolean |
| `consecutive_health_failures` | integer |
| `message` | string \| null |

**Errors**

- `404` — emulator not found.

---

### `POST /emulators/{emulator_id}/snapshot`

Create a layered snapshot from the running emulator.

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

**Errors**

- `404` — emulator not found.
- `409` — conflict (e.g. invalid state; `detail` explains).

---

### `DELETE /emulators/{emulator_id}`

Tear down the emulator.

**Response** `204 No Content`

**Errors**

- `404` — emulator not found.

---

### `GET /internal/health-events`

Debug: recent mock emulator health probe events.

**Query**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `50` | Max events returned. |

**Response** `200 OK`

```json
{
  "events": [ { "...": "HealthEvent fields" } ]
}
```

---

## Sessions (SQLite)

Tag: `sessions` — routes are under prefix `/users`.

### `GET /users/{user_id}/sessions`

List sessions for a user.

**Response** `200 OK` — `SessionsListResponse`

| Field | Type |
|-------|------|
| `user_id` | string |
| `sessions` | array of `SessionEntry` |

`SessionEntry` fields:

| Field | Type |
|-------|------|
| `session_id` | integer |
| `app_package` | string |
| `snapshot_id` | string \| null |
| `health` | string |
| `last_verified_at` | ISO datetime \| null |
| `last_access_at` | ISO datetime \| null |
| `login_method` | string |
| `tier` | string (`hot` \| `warm` \| `cold`) |
| `re_auth_required` | boolean |

---

### `POST /users/{user_id}/sessions/{app_package}/verify`

Touch the session and run a mock health check; creates user and session if missing.

**Request body** (optional)

| Field | Type |
|-------|------|
| `login_method` | `otp` \| `sso` \| `password` \| omitted |
| `snapshot_id` | string \| null |

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

**Query**

| Parameter | Default |
|-----------|---------|
| `limit` | `100` |

**Response** `200 OK` — `HealthHistoryResponse`

| Field | Type |
|-------|------|
| `user_id` | string |
| `app_package` | string |
| `events` | array of `{ checked_at, observed, detail }` (chronological order in response) |

**Errors**

- `404` — session not found for that user/app.

---

## Missions

Tag: `missions`

### `POST /missions`

Create a mission and enqueue background execution.

**Request body** — `CreateMissionRequest`

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | string | Required, non-empty. |
| `targets` | array | At least one `{ app_package, goal }`. |
| `webhook_url` | string \| null | Optional URL for identity-gate notifications. |

Each target:

| Field | Type |
|-------|------|
| `app_package` | string |
| `goal` | string |

**Response** `200 OK` — `CreateMissionResponse`

Includes `mission_id`, `user_id`, `state`, `tasks` (each task has `task_id` UUID string, `sequence`, `app_package`, `goal`, `state`, optional `emulator_id`, `error_message`, `identity_gate_notified_at`, timestamps), `created_at`, `updated_at`.

---

### `GET /missions/{mission_id}`

**Response** `200 OK` — `MissionDetailResponse`

Same task shape as create, plus mission-level `webhook_url`, `error_detail`.

**Errors**

- `404` — mission not found.

---

### Identity gate webhook (outbound)

When a task enters `identity_gate` and the mission has a `webhook_url`, the service **POST**s JSON:

```json
{
  "event": "identity_gate",
  "mission_id": "<mission id>",
  "task_id": "<task id>",
  "user_id": "<user id>",
  "app_package": "<app package>"
}
```

Delivery is best-effort; failures are logged. The task still waits for approve or timeout even if the webhook fails.

---

### `POST /missions/{mission_id}/tasks/{task_id}/approve`

Resume a task blocked in **identity_gate** (idempotent if not in that state).

**Response** `200 OK` — `ApproveMissionTaskResponse`

| Field | Type |
|-------|------|
| `mission_id` | string |
| `task_id` | string |
| `state` | string (current task state) |
| `message` | string — e.g. `resume signaled` or `not in identity_gate; no-op` |

**Errors**

- `404` — task not found.

---

## OpenAPI

The running app exposes interactive schemas at:

- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`
