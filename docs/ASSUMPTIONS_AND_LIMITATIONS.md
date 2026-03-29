# Assumptions and known limitations

## Assumptions

### Emulator layer (Part 1)

- **Mock backend** — Emulators are simulated in process (timing, health flakiness, snapshot chain). Production would replace `EmulatorService` / warm pool with real devices or VMs while keeping the same REST surface.
- **Single replica** — In-memory emulator state is not shared across processes; horizontal scaling would require an external orchestrator and shared snapshot store.
- **Warm pool** — A fixed number of idle “warm” instances is filled asynchronously; until then, provisioning may cold-boot (still within simulated SLA targets in README).

### Sessions (Part 2)

- **SQLite** — Default deployment uses file-backed SQLite with `aiosqlite`. Suitable for demo and single-node workloads; high concurrency or HA would move to a client/server RDBMS.
- **Mock vision health** — `verify` and scheduled checks use probabilistic logged-in vs expired outcomes (`SESSION_MOCK_LOGGED_IN_PROBABILITY`), not real screen analysis.
- **Tiering** — Derived from `last_access_at` and configured windows; cold sessions are not auto-polled by the worker (manual `verify` or mission-driven access applies).

### Missions (Part 3)

- **Session prerequisite** — Tasks require a `user_sessions` row for `(user_id, app_package)` with health not `expired`; otherwise the task fails without provisioning.
- **Emulator lifecycle** — Each task allocates a mock emulator and destroys it after work; no long-lived pooled mission emulators in this prototype.
- **Parallelism model** — Different `app_package` values run in parallel; multiple tasks for the **same** app run **sequentially** in target list order.
- **Identity gate** — Optional random gate with webhook + HTTP approve; timeouts and webhook failures are handled as documented in architecture (best-effort webhook, timeout → failed task).

## Known limitations

| Area | Limitation |
|------|------------|
| **Persistence** | Emulator and snapshot metadata for Part 1 live in memory only; restart loses mock emulators (DB tables hold sessions/missions only). |
| **Mission runner** | Background mission execution uses in-process asyncio; process crash can leave missions mid-flight (no distributed queue). |
| **Identity gate** | Coordination uses in-memory `asyncio.Event` map (`_gate_events`); multiple API replicas would not share gate state without external sync. |
| **Webhooks** | Outbound calls are best-effort; failures are logged, not retried with backoff in this codebase. |
| **Authn/z** | No API authentication; all routes are open if the port is reachable. |
| **Rate limits** | No rate limiting or quota enforcement on endpoints. |
| **Idempotency** | Mission create is not idempotent; duplicate POSTs create duplicate missions. |

These limits are acceptable for the take-home / prototype scope and should be revisited before production use.
