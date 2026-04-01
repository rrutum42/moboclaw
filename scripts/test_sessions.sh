#!/usr/bin/env bash
set -euo pipefail

BASE=http://127.0.0.1:8080
echo "[test_sessions] BASE=$BASE"

echo "[test_sessions] POST /users (mint user)"
USER_ID=$(curl -sS -X POST "$BASE/users" | jq -r .user_id)
echo "[test_sessions] USER_ID=$USER_ID"

# To reuse an existing user instead: USER_ID='your-uuid-here'
APP='com.dream11.app'
echo "[test_sessions] APP=$APP"

echo "[test_sessions] GET /emulators?running_only=true (first running emulator)"
EMU=$(curl -sS "$BASE/emulators?running_only=true" | jq -r '.[0].id // empty')
if [[ -z "$EMU" ]]; then
  echo "[test_sessions] ERROR: no running emulators. Provision one (POST /emulators) or start the pool, then retry." >&2
  exit 1
fi
echo "[test_sessions] EMU=$EMU"

# SDK: wait until the device is booted before snapshot, or capture may fail.
echo "[test_sessions] POST /emulators/$EMU/snapshot (layer=session)"
SNAP=$(curl -sS -X POST "$BASE/emulators/$EMU/snapshot" \
  -H 'Content-Type: application/json' \
  -d '{"layer":"session","label":"manual-login"}' | jq -r .snapshot_id)
echo "[test_sessions] SNAP=$SNAP"

echo "[test_sessions] POST /users/.../verify (link session to snapshot)"
curl -sS -X POST "$BASE/users/$USER_ID/sessions/$APP/verify" \
  -H 'Content-Type: application/json' \
  -d "{\"snapshot_id\":\"$SNAP\",\"login_method\":\"password\"}" | jq
echo "[test_sessions] done"
