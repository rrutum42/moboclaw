# Running Moboclaw on your machine

This guide covers **local** development: Python venv, Uvicorn, SQLite, and optionally the **real Android emulator** (`EMULATOR_BACKEND=sdk`).

For **Docker**, see the root [README.md](../README.md) (Compose uses mock emulators by default).

---

## Prerequisites

| Need | When |
|------|------|
| **Python 3.11+** (recommended) | Always |
| **Android SDK** (`emulator`, `platform-tools`, a system image) | Only if `EMULATOR_BACKEND=sdk` |
| **A golden AVD** (e.g. `Pixel_6_API_34`) | Only for `sdk` — create once in Studio or via `avdmanager`; must match `EMULATOR_AVD_NAME` |

---

## Scripts: AVD and Android emulator prerequisites (`scripts/`)

Run these from the **`moboclaw/`** directory (paths below are relative to that repo root).

| Script | Platform | What it does |
|--------|----------|----------------|
| [scripts/install_android_emulator_prereqs_mac.sh](../scripts/install_android_emulator_prereqs_mac.sh) | **macOS only** | Requires [Homebrew](https://brew.sh). Installs Temurin JDK + Android command-line tools, runs **`sdkmanager`** for platform-tools, emulator, system image, and **creates a sample AVD** (default name `Pixel_6_API_34`, override with `AVD_NAME` / `API_LEVEL`). Use this when you have no SDK yet. |
| [scripts/host_setup_moboclaw_sdk_once.sh](../scripts/host_setup_moboclaw_sdk_once.sh) | macOS/Linux (see script) | **One-time** prep for `EMULATOR_BACKEND=sdk`: optionally runs the macOS installer above (`SKIP_MAC_SDK_INSTALL=1` skips it), **deletes** `.moboclaw_qcow2_sessions`, runs **`qemu-img check`** on the golden AVD’s userdata and, if needed, repairs **qcow2/raw userdata** so clones stay consistent. Set `AVD_NAME` if your golden AVD is not the default. |
| [scripts/recreate_golden_avd.sh](../scripts/recreate_golden_avd.sh) | macOS/Linux | **Nuclear reset** of the golden AVD: clears `.moboclaw_qcow2_sessions`, removes the existing AVD, ensures SDK packages + licenses, **creates a fresh AVD** with `avdmanager`, then runs userdata repair (via `host_setup` with `SKIP_MAC_SDK_INSTALL=1`). Use when the golden image is corrupt or you want a clean slate. **Quit other emulators first** to avoid file locks. |

Typical order for a new Mac:

1. `./scripts/install_android_emulator_prereqs_mac.sh` (or install Studio manually).
2. `./scripts/host_setup_moboclaw_sdk_once.sh` before first serious `sdk` run.
3. If things stay broken, `./scripts/recreate_golden_avd.sh`.

---

## 1. Clone and install dependencies

```bash
cd moboclaw
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 2. Choose emulator mode

### Option A — Mock (no Android install)

Good for API and session/mission testing without real devices.

```bash
export EMULATOR_BACKEND=mock
# optional: defaults are fine
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Open **`http://127.0.0.1:8080/docs`**.

### Option B — Real Android Emulator (SDK)

1. Install **Android Studio** or the **command-line tools**, **platform-tools**, **emulator**, and at least one **system image**.
2. Create an AVD (Device Manager in Studio, or `avdmanager create avd`). Remember the **AVD name** (e.g. `Pixel_6_API_34`).
3. Put SDK tools on your **`PATH`** and set **`ANDROID_HOME`** (or **`ANDROID_SDK_ROOT`**):

   ```bash
   export ANDROID_HOME="$HOME/Library/Android/sdk"   # typical macOS
   export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$PATH"
   ```

4. Confirm the AVD exists:

   ```bash
   emulator -list-avds
   ```

5. Run the API:

   ```bash
   cd moboclaw
   source .venv/bin/activate
   export EMULATOR_BACKEND=sdk
   export EMULATOR_AVD_NAME=Pixel_6_API_34   # must match list-avds
   export EMULATOR_WARM_POOL_SIZE=1            # recommended: large disk clones
   # optional: show emulator window
   export EMULATOR_EMULATOR_UI_MODE=window
   uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
   ```

**First-time host prep:** see [Scripts: AVD and Android emulator prerequisites](#scripts-avd-and-android-emulator-prerequisites-scripts) above.

### SDK environment verification (macOS)

Before relying on missions or scripted flows, confirm the shell the API runs in can see the toolchain:

| Check | Command / expectation |
|--------|----------------------|
| `emulator` on `PATH` | `which emulator` → under `$ANDROID_HOME/emulator` |
| `adb` on `PATH` | `which adb` → under `$ANDROID_HOME/platform-tools` |
| AVD name matches config | `emulator -list-avds` includes **`EMULATOR_AVD_NAME`** (e.g. `Pixel_6_API_34`) |
| API sees SDK backend | Process env: `EMULATOR_BACKEND=sdk`; optional `EMULATOR_ANDROID_SDK_ROOT` if not using `ANDROID_HOME` |

**Warm pool:** use `EMULATOR_WARM_POOL_SIZE=1` on a laptop unless you have RAM and disk for multiple full AVD clones.

---

## 3. Check that the API is up

```bash
curl -sS http://127.0.0.1:8080/healthz
```

Expected: `{"status":"ok"}`.

---

## 4. SQLite and env files

| Item | Default (local) |
|------|------------------|
| Database | `./sessions.db` next to the working directory, unless you set **`SESSION_DATABASE_URL`** |
| Env file | Optional **`.env`** in `moboclaw/` — Pydantic loads **`EMULATOR_*`**, **`SESSION_*`**, **`MISSION_*`** prefixes (see root README tables) |

---

## 5. API smoke scripts (optional)

These assume the API is already running (`uvicorn`).

| Script | Purpose |
|--------|---------|
| [scripts/test_sessions.sh](../scripts/test_sessions.sh) | Curl flow: mint path, pick/provision emulator, session snapshot, **verify** session (set **`BASE`** if not `http://127.0.0.1:8080`). |
| [scripts/test_mission_parallel_and_sequence.sh](../scripts/test_mission_parallel_and_sequence.sh) | **`com.example.calculator`** + **`com.dream11.app`**: branch snapshot, verify both, mission with four targets interleaved (parallel per-app chains, sequential steps inside each app). |
| [scripts/snapshot_app_then_provision.sh](../scripts/snapshot_app_then_provision.sh) | **`GET /emulators?running_only=true`**, take an **app**-layer snapshot of a running emulator, then **`POST /emulators`** from that snapshot (set **`BASE_URL`** if needed). |

AVD/SDK setup scripts are listed [above](#scripts-avd-and-android-emulator-prerequisites-scripts).

---

## 6. End-to-end: branch snapshot, verify, mission (SDK)

Missions call the same **`EmulatorService.provision`** as **`POST /emulators`**. For a **non-base** snapshot, capture it via Part 1 first, attach it to the user session, then run the mission.

Assume API at **`BASE=http://127.0.0.1:8080`** and `EMULATOR_BACKEND=sdk` with a working golden AVD.

```bash
BASE=http://127.0.0.1:8080

# 1) User id (or use an existing seeded user)
USER_ID=$(curl -sS -X POST "$BASE/users" | jq -r .user_id)

# 2) Provision from base; capture an app (or session) layer snapshot — produces a catalog id + AVD clone metadata
EMU=$(curl -sS -X POST "$BASE/emulators" -H 'Content-Type: application/json' -d '{}' | jq -r .id)
SNAP=$(curl -sS -X POST "$BASE/emulators/$EMU/snapshot" \
  -H 'Content-Type: application/json' \
  -d '{"layer":"app","label":"demo_app"}' | jq -r .snapshot_id)

# 3) Tie session to that snapshot for your app package (must exist in snapshots table / hydrated store)
curl -sS -X POST "$BASE/users/$USER_ID/sessions/com.example.app/verify" \
  -H 'Content-Type: application/json' \
  -d "{\"login_method\":\"otp\",\"snapshot_id\":\"$SNAP\"}" | jq

# 4) Mission: tasks for that app_package provision from the session snapshot, then tear down
MID=$(curl -sS -X POST "$BASE/missions" -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"$USER_ID\",\"targets\":[{\"app_package\":\"com.example.app\",\"goal\":\"demo\"}]}" \
  | jq -r .mission_id)

curl -sS "$BASE/missions/$MID" | jq
```

If **`snapshot_id`** is wrong or metadata is incomplete, mission tasks fail at provision (same as a bad **`POST /emulators`** body). **`com.example.app`** must match the **`app_package`** used in **verify**.

---

## 7. Troubleshooting (local SDK)

| Symptom | What to try |
|---------|-------------|
| `RuntimeError: … ANDROID_HOME` | Export **`ANDROID_HOME`** / **`ANDROID_SDK_ROOT`** or set **`EMULATOR_ANDROID_SDK_ROOT`**. |
| `emulator-5554` / **offline** / stuck | Quit other emulators; **`adb kill-server`**; ensure only one process owns the golden AVD read-write. |
| **`No space left on device`** | Free disk; remove **`moboclaw/.moboclaw_qcow2_sessions`** when no runs are active; keep **`EMULATOR_WARM_POOL_SIZE=1`**. |
| Slow or OOM | Reduce warm pool; close other heavy apps; on Mac, software rendering is slower than Linux+KVM. |

---

## Related

- [ASSUMPTIONS_AND_LIMITATIONS.md](ASSUMPTIONS_AND_LIMITATIONS.md) — scope and limits  
- [API.md](API.md) — HTTP reference  
- [ARCHITECTURE.md](ARCHITECTURE.md) — components and background workers  
