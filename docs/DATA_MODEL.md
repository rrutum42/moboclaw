# Data model (SQLite)

ORM definitions live in `app/db/orm.py`. The API uses async SQLAlchemy with SQLite (`aiosqlite`).

## Entity relationship (conceptual)

- **User** `users.id` (string PK) has many **UserSession** and many **Mission**.
- **UserSession** `user_sessions` — one row per `(user_id, app_package)` (unique constraint). Integer `id` is exposed as `session_id` in APIs.
- **SessionHealthEvent** `session_health_history` — many rows per session (check history).
- **Mission** `missions.id` (string PK, UUID in practice) belongs to one user.
- **MissionTask** `mission_tasks` — many per mission; `task_id` is a unique string (UUID); `sequence` orders tasks within the mission.

## Tables summary

### `users`

| Column | Notes |
|--------|--------|
| `id` | String PK (user identifier from API). |
| `created_at` | Timezone-aware datetime. |

### `user_sessions`

| Column | Notes |
|--------|--------|
| `id` | Autoincrement PK (`session_id` in responses). |
| `user_id` | FK → `users.id` (CASCADE delete). |
| `app_package` | With `user_id`, unique (`uq_user_app`). |
| `snapshot_id` | Optional string ref to Part 1 snapshot. |
| `health` | `alive` \| `expired` \| `unknown` (stored as string). |
| `last_verified_at`, `last_access_at` | Nullable datetimes. |
| `login_method` | e.g. `otp`, `sso`, `password`. |
| `tier` | `hot`, `warm`, `cold` (derived/maintained by session logic). |

### `session_health_history`

| Column | Notes |
|--------|--------|
| `session_id` | FK → `user_sessions.id`. |
| `checked_at` | When the check ran. |
| `observed` | Outcome label from mock/real check. |
| `detail` | Optional text. |

### `missions`

| Column | Notes |
|--------|--------|
| `id` | String PK. |
| `user_id` | FK → `users.id`. |
| `state` | `queued`, `running`, `done`, `failed`. |
| `webhook_url` | Optional; used for identity gate POST. |
| `error_detail` | Optional mission-level error. |
| `created_at`, `updated_at` | Timestamps. |

### `mission_tasks`

| Column | Notes |
|--------|--------|
| `id` | Internal autoincrement PK. |
| `mission_id` | FK → `missions.id`. |
| `task_id` | Unique string (client-facing id). |
| `sequence` | Order within mission; unique per `mission_id`. |
| `app_package`, `goal` | Task targeting. |
| `state` | `queued`, `allocating`, `executing`, `identity_gate`, `completing`, `done`, `failed`. |
| `emulator_id` | Mock emulator id while running. |
| `identity_gate_notified_at` | When webhook was sent (if applicable). |
| `error_message` | Task failure reason. |
| `created_at`, `updated_at` | Timestamps. |

Part 1 emulator and snapshot metadata are **not** stored in these tables; they exist only in memory unless you extend the schema.
