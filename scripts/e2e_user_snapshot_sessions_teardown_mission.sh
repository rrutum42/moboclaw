#!/usr/bin/env bash
# End-to-end: create user → one app-layer snapshot from the first running emulator →
# verify a session per app with that snapshot → optional DELETE that emulator → run mission.
#
# EMULATOR_BACKEND=sdk: POST /emulators/{id}/snapshot already stops the instance and removes it
# from the store (capture needs the AVD offline). DELETE may return 404 — that is OK.
# mock: snapshot leaves the emulator RUNNING; DELETE returns 204 if you want explicit teardown.
#
# Sessions only store user_id, app_package, and snapshot_id; they do not own emulators.
# The mission runner provisions a fresh emulator per task from each session's snapshot.
#
# Environment:
#   BASE              API root (default http://127.0.0.1:8080)
#   MISSION_WAIT_SEC  Max seconds to poll GET /missions/{id} (default 600)
#   SKIP_SNAPSHOT     If 1, skip snapshot; verify without snapshot_id (mock smoke)
#   EMU_WAIT_SEC      If >0, poll GET /emulators?running_only=true until one appears (default 0)
#   PKG_CALC          Default com.example.calculator
#   PKG_DREAM11       Default com.dream11.app
#
# Server: for non-interactive runs set MISSION_IDENTITY_GATE_PROBABILITY=0.
# Server: set SESSION_MOCK_LOGGED_IN_PROBABILITY=1 so each /verify rolls "alive" (default 0.8 is
# random per app — one session can be expired and missions fail with re_auth_required).
# SDK: install both apps on the running emulator (e.g. warm pool) before snapshot; this script
# does not POST /emulators — it uses the first RUNNING emulator from the list API.
#
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8080}"
MISSION_WAIT_SEC="${MISSION_WAIT_SEC:-600}"
SKIP_SNAPSHOT="${SKIP_SNAPSHOT:-0}"
EMU_WAIT_SEC="${EMU_WAIT_SEC:-0}"

PKG_CALC="${PKG_CALC:-com.example.calculator}"
PKG_DREAM11="${PKG_DREAM11:-com.dream11.app}"

echo "[e2e] BASE=$BASE"
curl -sfS "$BASE/healthz" >/dev/null || {
  echo "[e2e] ERROR: API not reachable at $BASE" >&2
  exit 1
}

echo "[e2e] POST /users"
USER_ID=$(curl -sS -X POST "$BASE/users" | jq -r .user_id)
echo "[e2e] USER_ID=$USER_ID"

SNAP=""
EMU=""
if [[ "$SKIP_SNAPSHOT" != "1" ]]; then
  echo "[e2e] GET /emulators?running_only=true (first RUNNING emulator; install both apps before snapshot)"
  deadline=$(( $(date +%s) + EMU_WAIT_SEC ))
  while true; do
    EMU=$(curl -sS "$BASE/emulators?running_only=true" | jq -r '.[0].id // empty')
    if [[ -n "$EMU" ]]; then
      break
    fi
    if [[ $(date +%s) -ge $deadline ]]; then
      echo "[e2e] ERROR: no running emulators. Start the pool / wait for RUNNING, or set EMU_WAIT_SEC." >&2
      exit 1
    fi
    if [[ "$EMU_WAIT_SEC" -gt 0 ]]; then
      echo "[e2e] waiting for a running emulator..."
      sleep 2
    else
      echo "[e2e] ERROR: no running emulators. Start the service warm pool or set EMU_WAIT_SEC." >&2
      exit 1
    fi
  done
  echo "[e2e] EMU=$EMU"

  echo "[e2e] POST /emulators/$EMU/snapshot (single app-layer branch: both apps on same userdata)"
  SNAP=$(curl -sS -X POST "$BASE/emulators/$EMU/snapshot" \
    -H 'Content-Type: application/json' \
    -d '{"layer":"app","label":"e2e_calc_and_dream11"}' | jq -r .snapshot_id)
  echo "[e2e] SNAP=$SNAP"
  if [[ -z "$SNAP" || "$SNAP" == "null" ]]; then
    echo "[e2e] ERROR: snapshot_id missing" >&2
    exit 1
  fi
fi

verify_json() {
  if [[ -n "$SNAP" ]]; then
    jq -n --arg s "$SNAP" '{login_method:"otp",snapshot_id:$s}'
  else
    jq -n '{login_method:"otp"}'
  fi
}

echo "[e2e] POST verify session $PKG_CALC"
curl -sS -X POST "$BASE/users/$USER_ID/sessions/$PKG_CALC/verify" \
  -H 'Content-Type: application/json' \
  -d "$(verify_json)" | jq

echo "[e2e] POST verify session $PKG_DREAM11"
curl -sS -X POST "$BASE/users/$USER_ID/sessions/$PKG_DREAM11/verify" \
  -H 'Content-Type: application/json' \
  -d "$(verify_json)" | jq

if [[ -n "$EMU" ]]; then
  echo "[e2e] DELETE /emulators/$EMU (no-op if snapshot already tore it down)"
  del_code=$(curl -sS -o /dev/null -w "%{http_code}" -X DELETE "$BASE/emulators/$EMU")
  if [[ "$del_code" == "204" ]]; then
    echo "[e2e] deleted emulator $EMU"
  elif [[ "$del_code" == "404" ]]; then
    echo "[e2e] DELETE 404 — emulator already removed (normal for SDK after snapshot capture)"
  else
    echo "[e2e] ERROR: DELETE /emulators/$EMU HTTP $del_code (expected 204 or 404)" >&2
    exit 1
  fi
fi

echo "[e2e] POST /missions (parallel per app, sequential goals within app)"
MID=$(curl -sS -X POST "$BASE/missions" -H 'Content-Type: application/json' -d "$(jq -n \
  --arg uid "$USER_ID" \
  --arg p1 "$PKG_CALC" \
  --arg p2 "$PKG_DREAM11" \
  '{
    user_id: $uid,
    targets: [
      {app_package: $p1, goal: "calculator_open_app"},
      {app_package: $p2, goal: "dream11_open_app"},
      {app_package: $p1, goal: "calculator_add_numbers"},
      {app_package: $p2, goal: "dream11_check_contests"}
    ]
  }')" | jq -r .mission_id)

echo "[e2e] MISSION_ID=$MID"
echo "[e2e] Polling mission (max ${MISSION_WAIT_SEC}s)..."

deadline=$(( $(date +%s) + MISSION_WAIT_SEC ))
state=""
while true; do
  state=$(curl -sS "$BASE/missions/$MID" | jq -r .state)
  echo "[e2e] mission state=$state"
  if [[ "$state" == "done" || "$state" == "failed" ]]; then
    break
  fi
  if [[ $(date +%s) -ge $deadline ]]; then
    echo "[e2e] ERROR: timeout waiting for terminal mission state" >&2
    curl -sS "$BASE/missions/$MID" | jq
    exit 1
  fi
  sleep 1
done

curl -sS "$BASE/missions/$MID" | jq

if [[ "$state" != "done" ]]; then
  echo "[e2e] ERROR: mission ended with state=$state" >&2
  exit 1
fi

echo "[e2e] OK — user, shared snapshot, two sessions, post-snapshot cleanup, mission completed."
exit 0
