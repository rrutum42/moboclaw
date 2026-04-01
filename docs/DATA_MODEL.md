# Data model (SQLite)

ORM: `app/db/orm.py`. Driver: **async SQLAlchemy** + **SQLite** (`aiosqlite`).

## Relationships (conceptual)

```text
Snapshot (snapshots)       — catalog; same ids as orchestrator SnapshotRecord
User (users)
  ├── UserSession (many)     — unique (user_id, app_package); optional FK → snapshots.id
  │       └── SessionHealthEvent (many)
  └── Mission (many)
          └── MissionTask (many)
```

- **`users.id`**: string primary key. Prefer **`POST /users`** (server-minted UUID); **`verify`** can still create the row if missing.
- **`user_sessions`**: integer **`id`** is returned as **`session_id`** in JSON.
- **`snapshot_id`** on a session: optional FK to **`snapshots.id`** (same strings as `InMemoryStore.snapshots`).

The **snapshot catalog** is stored in **`snapshots`** (layer, parent, label, JSON metadata). On API startup, rows are **hydrated** into the in-memory store so provisioning survives restarts.

---

## Tables

### `snapshots`

| Column | Description |
|--------|-------------|
| `id` | String PK; same id returned by `POST /emulators/.../snapshot`. |
| `layer` | `base` / `app` / `session`. |
| `parent_snapshot_id` | Optional FK → `snapshots.id`. |
| `label` | Optional. |
| `created_at` | Timestamp. |
| `snapshot_metadata` | JSON (qcow2 paths, AVD names, mock flags, etc.). |

### `users`

| Column | Description |
|--------|-------------|
| `id` | String PK. |
| `created_at` | Timezone-aware datetime. |

### `user_sessions`

| Column | Description |
|--------|-------------|
| `id` | Autoincrement PK (exposed as `session_id`). |
| `user_id` | FK → `users.id` (CASCADE delete). |
| `app_package` | Android package name; unique with `user_id`. |
| `snapshot_id` | Optional FK → `snapshots.id` for provisioning. |
| `health` | `alive` / `expired` / `unknown`. |
| `last_verified_at`, `last_access_at` | Nullable datetimes. |
| `login_method` | e.g. `otp`, `sso`, `password`. |
| `tier` | `hot` / `warm` / `cold`. |

### `session_health_history`

| Column | Description |
|--------|-------------|
| `session_id` | FK → `user_sessions.id`. |
| `checked_at` | When the check ran. |
| `observed` | Label from mock (or future real) check. |
| `detail` | Optional text. |

### `missions`

| Column | Description |
|--------|-------------|
| `id` | String PK (UUID in practice). |
| `user_id` | FK → `users.id`. |
| `state` | `queued` / `running` / `done` / `failed`. |
| `webhook_url` | Optional; identity-gate POST target. |
| `error_detail` | Optional mission-level error. |
| `created_at`, `updated_at` | Timestamps. |

### `mission_tasks`

| Column | Description |
|--------|-------------|
| `mission_id` | FK → `missions.id`. |
| `task_id` | Unique string (client-facing id). |
| `sequence` | Order within mission. |
| `app_package`, `goal` | Task targeting. |
| `state` | Includes `identity_gate` when paused for approve. |
| `emulator_id` | Part 1 emulator id while running. |
| `identity_gate_notified_at` | When webhook was sent (if any). |
| `error_message` | Failure reason. |
| `created_at`, `updated_at` | Timestamps. |
