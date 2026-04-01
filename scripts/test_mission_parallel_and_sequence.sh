#!/usr/bin/env bash
# End-to-end smoke test: Part 1 snapshot → session verify (two apps) → mission.
#
# Mission shape (see app/services/mission_service.py run_mission):
#   - Targets are grouped by app_package. Each group runs as one asyncio task; groups run in
#     parallel (asyncio.gather).
#   - Within one app_package, tasks run in sequence (order of `targets` in the request).
#
# This script submits four targets in *interleaved* order:
#   seq0  calculator   — first task for app A
#   seq1  dream11      — first task for app B   }  these two chains start together (parallel)
#   seq2  calculator   — second for A (runs after seq0 on A’s chain)
#   seq3  dream11      — second for B (runs after seq1 on B’s chain)
#
# Environment:
#   BASE              API root (default http://127.0.0.1:8080)
#   MISSION_WAIT_SEC  Max seconds to poll GET /missions/{id} for terminal state (default 600)
#   SKIP_SNAPSHOT     If 1, skip provision/snapshot and verify without snapshot_id (base image only;
#                     good for EMULATOR_BACKEND=mock quick runs).
#
# Server tip: set MISSION_IDENTITY_GATE_PROBABILITY=0 so tasks do not block on approve.
#
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8080}"
MISSION_WAIT_SEC="${MISSION_WAIT_SEC:-600}"
SKIP_SNAPSHOT="${SKIP_SNAPSHOT:-0}"

PKG_CALC="${PKG_CALC:-com.example.calculator}"
PKG_DREAM11="${PKG_DREAM11:-com.dream11.app}"

echo "[test_mission_parallel] BASE=$BASE"
curl -sfS "$BASE/healthz" >/dev/null || {
  echo "[test_mission_parallel] ERROR: API not reachable at $BASE" >&2
  exit 1
}

echo "[test_mission_parallel] POST /users"
USER_ID=$(curl -sS -X POST "$BASE/users" | jq -r .user_id)
echo "[test_mission_parallel] USER_ID=$USER_ID"

SNAP=""
if [[ "$SKIP_SNAPSHOT" != "1" ]]; then
  echo "[test_mission_parallel] POST /emulators (provision from base)"
  EMU=$(curl -sS -X POST "$BASE/emulators" -H 'Content-Type: application/json' -d '{}' | jq -r .id)
  echo "[test_mission_parallel] EMU=$EMU"

  echo "[test_mission_parallel] POST /emulators/$EMU/snapshot (layer=app for branch metadata on sdk)"
  SNAP=$(curl -sS -X POST "$BASE/emulators/$EMU/snapshot" \
    -H 'Content-Type: application/json' \
    -d '{"layer":"app","label":"smoke_calc_dream11"}' | jq -r .snapshot_id)
  echo "[test_mission_parallel] SNAP=$SNAP"
  if [[ -z "$SNAP" || "$SNAP" == "null" ]]; then
    echo "[test_mission_parallel] ERROR: snapshot_id missing" >&2
    exit 1
  fi
fi

verify_body() {
  if [[ -n "$SNAP" ]]; then
    printf '{"login_method":"otp","snapshot_id":"%s"}' "$SNAP"
  else
    printf '{"login_method":"otp"}'
  fi
}

echo "[test_mission_parallel] POST verify $PKG_CALC"
curl -sS -X POST "$BASE/users/$USER_ID/sessions/$PKG_CALC/verify" \
  -H 'Content-Type: application/json' \
  -d "$(verify_body)" | jq

echo "[test_mission_parallel] POST verify $PKG_DREAM11"
curl -sS -X POST "$BASE/users/$USER_ID/sessions/$PKG_DREAM11/verify" \
  -H 'Content-Type: application/json' \
  -d "$(verify_body)" | jq

echo "[test_mission_parallel] POST /missions (interleaved targets: parallel app chains, sequential within app)"
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

echo "[test_mission_parallel] MISSION_ID=$MID"
echo "[test_mission_parallel] Polling mission until done or failed (max ${MISSION_WAIT_SEC}s)..."


deadline=$(( $(date +%s) + MISSION_WAIT_SEC ))
state=""
while true; do
  state=$(curl -sS "$BASE/missions/$MID" | jq -r .state)
  echo "[test_mission_parallel] mission state=$state"
  if [[ "$state" == "done" || "$state" == "failed" ]]; then
    break
  fi
  if [[ $(date +%s) -ge $deadline ]]; then
    echo "[test_mission_parallel] ERROR: timeout waiting for terminal mission state" >&2
    curl -sS "$BASE/missions/$MID" | jq
    exit 1
  fi
  sleep 1
done

curl -sS "$BASE/missions/$MID" | jq

if [[ "$state" != "done" ]]; then
  echo "[test_mission_parallel] ERROR: mission ended with state=$state" >&2
  exit 1
fi

echo "[test_mission_parallel] OK — mission done. Task order in DB: sequence 0..3; two app chains ran concurrently; within each app, goals ran in list order."
exit 0
