#!/usr/bin/env bash
# One-time host preparation for Moboclaw with EMULATOR_BACKEND=sdk.
#
# Does (in order):
#   1) On macOS: runs scripts/install_android_emulator_prereqs_mac.sh (SDK + licenses + AVD create) unless SKIP_MAC_SDK_INSTALL=1.
#   2) Removes moboclaw/.moboclaw_qcow2_sessions (session clones + branch snapshots cache).
#   3) Runs qemu-img check on the golden AVD userdata; if userdata-qemu.img.qcow2 is missing or corrupt,
#      removes the overlay and rewrites config.ini / hardware-qemu.ini to use raw userdata-qemu.img
#      (userdata.useQcow2=no) so new clones are consistent.
#
# Usage (from moboclaw/):
#   ./scripts/host_setup_moboclaw_sdk_once.sh
#   AVD_NAME=MyAvd ./scripts/host_setup_moboclaw_sdk_once.sh
#   SKIP_MAC_SDK_INSTALL=1 ./scripts/host_setup_moboclaw_sdk_once.sh   # only clear + userdata repair
#
# Requires: ANDROID_HOME (default mac: ~/Library/Android/sdk), AVD_NAME (default: Pixel_6_API_34).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBOCLAW_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

die() {
  echo "error: $*" >&2
  exit 1
}

AVD_NAME="${AVD_NAME:-Pixel_6_API_34}"
ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_HOME
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"

ANDROID_AVD_HOME="${ANDROID_AVD_HOME:-$HOME/.android/avd}"
GOLDEN_AVD="${ANDROID_AVD_HOME}/${AVD_NAME}.avd"
SESSION_ROOT="${MOBOCLAW_DIR}/.moboclaw_qcow2_sessions"
QEMU_IMG="${ANDROID_HOME}/emulator/qemu-img"

echo "==> Moboclaw one-time SDK host setup"
echo "    MOBOCLAW_DIR=${MOBOCLAW_DIR}"
echo "    ANDROID_HOME=${ANDROID_HOME}"
echo "    AVD_NAME=${AVD_NAME}"
echo "    GOLDEN_AVD=${GOLDEN_AVD}"

if [[ "${SKIP_MAC_SDK_INSTALL:-0}" != "1" ]] && [[ "$(uname -s)" == "Darwin" ]]; then
  echo "==> Running macOS SDK + AVD bootstrap (install_android_emulator_prereqs_mac.sh)"
  AVD_NAME="${AVD_NAME}" API_LEVEL="${API_LEVEL:-34}" \
    "${MOBOCLAW_DIR}/scripts/install_android_emulator_prereqs_mac.sh"
else
  echo "==> Skipping macOS full install (SKIP_MAC_SDK_INSTALL=${SKIP_MAC_SDK_INSTALL:-0} or not Darwin)"
  [[ -d "${ANDROID_HOME}" ]] || die "ANDROID_HOME does not exist: ${ANDROID_HOME}"
  [[ -x "${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager" ]] || \
    die "sdkmanager not found under ${ANDROID_HOME}/cmdline-tools/latest/bin — run install_android_emulator_prereqs_mac.sh or install cmdline-tools"
fi

[[ -x "${QEMU_IMG}" ]] || die "qemu-img not found at ${QEMU_IMG}"

echo "==> Clearing Moboclaw session / branch cache: ${SESSION_ROOT}"
rm -rf "${SESSION_ROOT}"
mkdir -p "${SESSION_ROOT}"
echo "    Cleared."

[[ -d "${GOLDEN_AVD}" ]] || die "Golden AVD directory missing: ${GOLDEN_AVD} (create AVD ${AVD_NAME} first)"

repair_golden_raw_userdata() {
  python3 - "$GOLDEN_AVD" <<'PY'
import pathlib, re, sys
avd = pathlib.Path(sys.argv[1])
for name in ("config.ini", "hardware-qemu.ini"):
    p = avd / name
    if not p.is_file():
        continue
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    for line in lines:
        if re.match(r"^\s*disk\.dataPartition\.path\s*=", line):
            out.append("disk.dataPartition.path = userdata-qemu.img")
        elif re.match(r"^\s*userdata\.useQcow2\s*=", line):
            out.append("userdata.useQcow2=no")
        else:
            out.append(line)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
print("    Patched", avd, "to raw userdata-qemu.img (userdata.useQcow2=no)")
PY
}

OVERLAY="${GOLDEN_AVD}/userdata-qemu.img.qcow2"
RAW="${GOLDEN_AVD}/userdata-qemu.img"

echo "==> Checking golden userdata images"
if [[ -f "${OVERLAY}" ]]; then
  if "${QEMU_IMG}" check "${OVERLAY}" 2>/dev/null; then
    echo "    userdata-qemu.img.qcow2: OK"
  else
    echo "    userdata-qemu.img.qcow2: FAILED qemu-img check — removing overlay and switching golden to raw userdata"
    rm -f "${OVERLAY}"
    repair_golden_raw_userdata
  fi
else
  echo "    No userdata-qemu.img.qcow2 (using raw or absent overlay)"
    need_repair=0
    for f in "${GOLDEN_AVD}/config.ini" "${GOLDEN_AVD}/hardware-qemu.ini"; do
      [[ -f "${f}" ]] || continue
      if grep -qE "userdata-qemu\.img\.qcow2|userdata\.useQcow2[[:space:]]*=[[:space:]]*yes" "${f}" 2>/dev/null; then
        need_repair=1
      fi
    done
    if [[ "${need_repair}" -eq 1 ]]; then
      echo "    Ini still references qcow2 overlay — repairing to raw userdata-qemu.img"
      repair_golden_raw_userdata
    fi
fi

if [[ -f "${RAW}" ]]; then
  fmt="$("${QEMU_IMG}" info --output=json "${RAW}" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('format',''))" 2>/dev/null || true)"
  if [[ -n "${fmt}" ]]; then
    echo "    userdata-qemu.img format: ${fmt}"
    if ! "${QEMU_IMG}" check "${RAW}" 2>/dev/null; then
      die "userdata-qemu.img failed qemu-img check; recreate AVD ${AVD_NAME} or delete ${RAW} and let the emulator recreate (backup first)."
    fi
    echo "    userdata-qemu.img: OK"
  fi
fi

echo ""
echo "Done. Next:"
echo "  export ANDROID_HOME=\"${ANDROID_HOME}\""
echo "  export PATH=\"\${ANDROID_HOME}/emulator:\${ANDROID_HOME}/platform-tools:\${PATH}\""
echo "  cd \"${MOBOCLAW_DIR}\" && export EMULATOR_BACKEND=sdk EMULATOR_AVD_NAME=${AVD_NAME}"
echo "  uvicorn app.main:app --host 0.0.0.0 --port 8080"
echo ""
