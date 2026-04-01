#!/usr/bin/env bash
# List RUNNING emulators from moboclaw, take an app-layer snapshot of the first one,
# then provision a new emulator from that snapshot.
#
# Provisioning from a snapshot drains warm instances first, then boots a new emulator with
# full userdata (apps, sessions). The warm emulator used for the snapshot is stopped as part of provision.
#
# Requires: curl, jq
# Usage:
#   ./scripts/snapshot_app_then_provision.sh
#   EMU_ID=emu-abc123 ./scripts/snapshot_app_then_provision.sh   # snapshot a specific instance
#   BASE_URL=http://localhost:9000 ./scripts/snapshot_app_then_provision.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"

if ! command -v jq &>/dev/null; then
  echo "error: jq is required (brew install jq)" >&2
  exit 1
fi

echo "Fetching running emulators from ${BASE_URL} ..."
list_json="$(curl -sS -f "${BASE_URL}/emulators?running_only=true" -H 'accept: application/json')"

count="$(echo "$list_json" | jq 'length')"
if [[ "$count" -eq 0 ]]; then
  echo "error: no RUNNING emulators returned; start the pool or provision one first." >&2
  exit 1
fi

# With a warm pool, list order is usually warm instances first; the first row is often NOT the
# emulator where you installed apps (that is typically pool_role=provisioned). Prefer that.
if [[ -n "${EMU_ID:-}" ]]; then
  emu_id="$EMU_ID"
  if ! echo "$list_json" | jq -e --arg id "$emu_id" 'map(.id) | index($id) != null' >/dev/null; then
    echo "error: EMU_ID=${emu_id} is not among RUNNING emulators." >&2
    exit 1
  fi
  echo "Using EMU_ID: ${emu_id}"
else
  prov="$(echo "$list_json" | jq '[.[] | select(.pool_role == "provisioned" or .assigned == true)]')"
  prov_count="$(echo "$prov" | jq 'length')"
  if [[ "$prov_count" -ge 1 ]]; then
    emu_id="$(echo "$prov" | jq -r '.[0].id')"
    echo "Using provisioned emulator (not warm-pool order): ${emu_id}"
  elif [[ "$count" -eq 1 ]]; then
    emu_id="$(echo "$list_json" | jq -r '.[0].id')"
    echo "Using sole RUNNING emulator: ${emu_id}"
  else
    echo "error: multiple RUNNING emulators and none are provisioned (pool_role=provisioned)." >&2
    echo "Install the app on the instance you want, then run:" >&2
    echo "  EMU_ID=<id from: curl -s ${BASE_URL}/emulators?running_only=true | jq> $0" >&2
    exit 1
  fi
fi

echo "Creating app-layer snapshot ..."
snap_json="$(curl -sS -f -X POST "${BASE_URL}/emulators/${emu_id}/snapshot" \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{"layer":"app"}')"

snapshot_id="$(echo "$snap_json" | jq -r '.snapshot_id')"
echo "Snapshot id: ${snapshot_id}"
echo "$snap_json" | jq .

echo "Provisioning new emulator from snapshot (may take several minutes; client max 15m) ..."
prov_json="$(curl -sS -f --max-time 900 -X POST "${BASE_URL}/emulators" \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg sid "$snapshot_id" '{snapshot_id: $sid}')")"

echo "Provisioned:"
echo "$prov_json" | jq .
