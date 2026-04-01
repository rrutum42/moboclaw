#!/usr/bin/env bash
# Recreate the Moboclaw golden AVD from scratch (default: Pixel_6_API_34, API 34).
#
# 1) Clears moboclaw/.moboclaw_qcow2_sessions
# 2) Removes the existing AVD (same idea as a clean "golden" in manual-snapshot-restore notes)
# 3) Ensures SDK packages + licenses, creates a fresh AVD with avdmanager
# 4) Runs host_setup_moboclaw_sdk_once.sh (SKIP_MAC_SDK_INSTALL=1) for userdata/qemu-img repair
#
# Usage (from moboclaw/):
#   ./scripts/recreate_golden_avd.sh
#   AVD_NAME=Pixel_6_API_34 API_LEVEL=34 ./scripts/recreate_golden_avd.sh
#
# Optional second instance (clone AVD, like manual snapshot notes): copy ~/.android/avd/<name>.avd
# to session_test.avd, fix .ini paths, then emulator -avd session_test -port 5556 -no-snapshot-load -no-snapshot-save
#
# Requires: ANDROID_HOME (default: ~/Library/Android/sdk), cmdline-tools with sdkmanager/avdmanager.
# Quit other Android Emulator instances first to avoid file locks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBOCLAW_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

die() {
  echo "error: $*" >&2
  exit 1
}

AVD_NAME="${AVD_NAME:-Pixel_6_API_34}"
API_LEVEL="${API_LEVEL:-34}"
ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_HOME
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"

ANDROID_AVD_HOME="${ANDROID_AVD_HOME:-$HOME/.android/avd}"
SESSION_ROOT="${MOBOCLAW_DIR}/.moboclaw_qcow2_sessions"

SDKMANAGER="${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager"
AVDMANAGER="${ANDROID_HOME}/cmdline-tools/latest/bin/avdmanager"

[[ -x "${SDKMANAGER}" ]] || die "sdkmanager not found: ${SDKMANAGER} (install cmdline-tools or run install_android_emulator_prereqs_mac.sh once)"

pick_installed_sysimg() {
  local ARCH abi line
  ARCH="$(uname -m)"
  [[ "${ARCH}" == "arm64" ]] && abi="arm64-v8a" || abi="x86_64"
  line="$("${SDKMANAGER}" --sdk_root="${ANDROID_HOME}" --list_installed 2>/dev/null \
    | grep -E "[[:space:]]*system-images;android-${API_LEVEL};" \
    | grep -F "${abi}" \
    | grep -E "google_apis|google_apis_playstore" \
    | head -1 || true)"
  if [[ -z "${line}" ]]; then
    line="$("${SDKMANAGER}" --sdk_root="${ANDROID_HOME}" --list_installed 2>/dev/null \
      | grep -E "[[:space:]]*system-images;android-${API_LEVEL};" \
      | grep -F "${abi}" \
      | head -1 || true)"
  fi
  [[ -z "${line}" ]] && return 1
  echo "${line}" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $1); print $1}'
}

echo "==> Recreate golden AVD"
echo "    MOBOCLAW_DIR=${MOBOCLAW_DIR}"
echo "    ANDROID_HOME=${ANDROID_HOME}"
echo "    AVD_NAME=${AVD_NAME}  API_LEVEL=${API_LEVEL}"
echo ""

echo "==> (1) Clear Moboclaw session / branch cache"
rm -rf "${SESSION_ROOT}"
mkdir -p "${SESSION_ROOT}"
echo "    ${SESSION_ROOT}"

echo "==> (2) Remove existing AVD if present"
if [[ -d "${ANDROID_AVD_HOME}/${AVD_NAME}.avd" ]] || [[ -f "${ANDROID_AVD_HOME}/${AVD_NAME}.ini" ]]; then
  if "${AVDMANAGER}" list avd 2>/dev/null | grep -q "Name: ${AVD_NAME}"; then
    echo "    avdmanager delete avd -n ${AVD_NAME}"
    "${AVDMANAGER}" delete avd -n "${AVD_NAME}" 2>/dev/null || true
  fi
  rm -rf "${ANDROID_AVD_HOME}/${AVD_NAME}.avd" "${ANDROID_AVD_HOME}/${AVD_NAME}.ini"
  echo "    Removed ${AVD_NAME} under ${ANDROID_AVD_HOME}"
else
  echo "    No existing ${AVD_NAME} — nothing to delete"
fi

ARCH="$(uname -m)"
if [[ "${ARCH}" == "arm64" ]]; then
  SYSIMG_REQUEST="system-images;android-${API_LEVEL};google_apis;arm64-v8a"
else
  SYSIMG_REQUEST="system-images;android-${API_LEVEL};google_apis;x86_64"
fi

echo "==> (3) Accept licenses and install SDK pieces"
set +o pipefail
yes | "${SDKMANAGER}" --sdk_root="${ANDROID_HOME}" --licenses
set -o pipefail

echo "==>     sdkmanager --install …"
"${SDKMANAGER}" --sdk_root="${ANDROID_HOME}" --install \
  "platform-tools" \
  "emulator" \
  "platforms;android-${API_LEVEL}" \
  "${SYSIMG_REQUEST}"

SYSIMG="$(pick_installed_sysimg || true)"
[[ -n "${SYSIMG}" ]] || die "could not resolve installed system image for API ${API_LEVEL}; check: sdkmanager --list_installed | grep system-images"

echo "    Using system image: ${SYSIMG}"

echo "==> (4) Create fresh AVD ${AVD_NAME} (Pixel 6 device profile when available)"
if echo no | "${AVDMANAGER}" create avd \
  -n "${AVD_NAME}" \
  -k "${SYSIMG}" \
  -d pixel_6; then
  :
else
  echo "    Retrying without -d pixel_6…"
  echo no | "${AVDMANAGER}" create avd \
    -n "${AVD_NAME}" \
    -k "${SYSIMG}" \
    || die "avdmanager create avd failed"
fi

echo "==> (5) Golden userdata repair + session dir (host_setup_moboclaw_sdk_once.sh)"
SKIP_MAC_SDK_INSTALL=1 AVD_NAME="${AVD_NAME}" API_LEVEL="${API_LEVEL}" \
  "${MOBOCLAW_DIR}/scripts/host_setup_moboclaw_sdk_once.sh"

echo ""
echo "Done. Test boot (optional):"
echo "  export PATH=\"\${ANDROID_HOME}/emulator:\${ANDROID_HOME}/platform-tools:\${PATH}\""
echo "  \"\${ANDROID_HOME}/emulator/emulator\" -avd \"${AVD_NAME}\" -no-snapshot-load -no-snapshot-save"
echo ""
