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

emu_id="$(echo "$list_json" | jq -r '.[0].id')"
echo "Using first emulator: ${emu_id}"

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
