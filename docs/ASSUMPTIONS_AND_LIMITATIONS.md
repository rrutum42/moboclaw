# Assumptions and limitations

## Assumptions

### Part 1 (emulators)

- **Mock backend** — Simulated timings and health; no Android SDK or AVD required.
- **SDK backend** — We assume a **golden (base) AVD already exists** on the machine: the name must match **`EMULATOR_AVD_NAME`** (default `Pixel_6_API_34`). Moboclaw does **not** create or download system images; you install the SDK, create an AVD (Android Studio or `avdmanager`), then run the API. Session clones copy that AVD tree from `~/.android/avd/…`.
- **Single process** — In-memory emulator state is not shared; scale-out needs an external orchestrator + shared snapshot storage if you keep the same API shape.
- **Warm pool** — A target number of idle instances is filled in the background; until filled, provisioning may cold-boot.

### Part 2 (sessions)

- **SQLite** — File-backed DB is fine for demo and single-node use; production HA would use a client/server database.
- **Mock health** — `verify` and scheduled checks use **`SESSION_MOCK_LOGGED_IN_PROBABILITY`** (random logged-in vs expired), not real screen analysis.
- **Tiering** — From `last_access_at` and configured windows; **cold** sessions are not auto-polled (use **verify** or mission access).

### Part 3 (missions)

- **Session required** — Tasks need a `user_sessions` row for `(user_id, app_package)` with health **not** `expired`.
- **Per-task emulator** — Each task provisions then destroys an emulator (prototype); no long-lived mission pool.
- **Parallelism** — Different `app_package` values run in parallel; same app → sequential in list order.
- **Identity gate** — Random gate + optional webhook + HTTP approve; timeouts and webhook failures behave as documented in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Known limitations

| Area | Limitation |
|------|------------|
| **Part 1 durability** | Snapshot **metadata** for provisioning lives in **memory**; API restart drops the in-memory catalog until base seed / new captures. |
| **Mission runner** | In-process `asyncio`; crash can leave missions mid-flight (no distributed queue). |
| **Identity gate** | In-memory events; not shared across replicas. |
| **Webhooks** | Best-effort; no retry with backoff in code. |
| **Security** | No authentication on `/emulators`, `/users`, `/missions` if the port is exposed. |
| **Rate limits** | None. |
| **Idempotency** | Duplicate `POST /missions` creates duplicate missions. |

Acceptable for a prototype; revisit before production.
