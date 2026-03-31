#!/usr/bin/env bash
# Install Android Emulator prerequisites on macOS (Apple Silicon or Intel).
# Usage:
#   ./scripts/install_android_emulator_prereqs_mac.sh
#   ANDROID_HOME="$HOME/Library/Android/sdk" ./scripts/install_android_emulator_prereqs_mac.sh
#
# Requires: Homebrew (https://brew.sh). Installs Temurin JDK + Android command-line tools via Homebrew,
# then uses sdkmanager to pull platform-tools, emulator, a system image, and creates a sample AVD.
#
# Optional: HOMEBREW_NO_AUTO_UPDATE=1 ./scripts/install_android_emulator_prereqs_mac.sh
# skips Homebrew's long "Auto-updating Homebrew" step when you re-run the script.

set -euo pipefail

API_LEVEL="${API_LEVEL:-34}"
AVD_NAME="${AVD_NAME:-Pixel_6_API_34}"

die() {
  echo "error: $*" >&2
  exit 1
}

[[ "$(uname -s)" == "Darwin" ]] || die "this script is for macOS only"

if ! command -v brew >/dev/null 2>&1; then
  die "Homebrew not found. Install from https://brew.sh then re-run."
fi

BREW_PREFIX="$(brew --prefix)"
ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_HOME
# avdmanager/sdkmanager both honor this; some tools only read ANDROID_SDK_ROOT.
export ANDROID_SDK_ROOT="${ANDROID_HOME}"

JAVA_HOME=""
if /usr/libexec/java_home -V >/dev/null 2>&1; then
  JAVA_HOME="$(/usr/libexec/java_home 2>/dev/null || true)"
fi

echo "==> Checking Java (Temurin recommended for Android tooling)"
if [[ -z "${JAVA_HOME}" ]] || ! command -v java >/dev/null 2>&1; then
  echo "    Installing Temurin (JDK) via Homebrew…"
  brew install --cask temurin
  JAVA_HOME="$(/usr/libexec/java_home)"
fi
export JAVA_HOME
echo "    JAVA_HOME=${JAVA_HOME}"

echo "==> Installing Android SDK command-line tools (Homebrew cask)"
brew install --cask android-commandlinetools

CMDLINE_SRC="${BREW_PREFIX}/share/android-commandlinetools/cmdline-tools/latest"
[[ -d "${CMDLINE_SRC}/bin" ]] || die "unexpected Homebrew layout; missing ${CMDLINE_SRC}/bin"

echo "==> Preparing ANDROID_HOME=${ANDROID_HOME}"
mkdir -p "${ANDROID_HOME}/cmdline-tools"
# Do NOT symlink cmdline-tools from Homebrew: avdmanager resolves the SDK root using the *real*
# path of its binaries. A symlink makes that root /opt/homebrew/share/android-commandlinetools
# while sdkmanager --sdk_root installs into ANDROID_HOME — so packages appear in list_installed
# but avdmanager sees no system images ("Valid system image paths are: … null").
rm -rf "${ANDROID_HOME}/cmdline-tools/latest"
cp -a "${CMDLINE_SRC}" "${ANDROID_HOME}/cmdline-tools/latest"
echo "    Copied cmdline-tools into ANDROID_HOME (not a symlink)."

SDKMANAGER="${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager"
AVDMANAGER="${ANDROID_HOME}/cmdline-tools/latest/bin/avdmanager"
[[ -x "${SDKMANAGER}" ]] || die "sdkmanager not found at ${SDKMANAGER}"

# Preferred system image id for sdkmanager --install (must match a repo package name).
ARCH="$(uname -m)"
if [[ "${ARCH}" == "arm64" ]]; then
  SYSIMG_REQUEST="system-images;android-${API_LEVEL};google_apis;arm64-v8a"
else
  SYSIMG_REQUEST="system-images;android-${API_LEVEL};google_apis;x86_64"
fi

# After install, use the exact package string from --list_installed (avdmanager is picky).
pick_installed_sysimg() {
  local abi
  [[ "${ARCH}" == "arm64" ]] && abi="arm64-v8a" || abi="x86_64"
  local line
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

echo "==> Accepting SDK licenses (non-interactive; often 2–5+ minutes)"
echo "    Output is shown below—do not redirect this step. Many 'y' prompts is normal."
# Avoid hiding output: sdkmanager can look 'stuck' when sent to /dev/null.
# Some bash builds treat yes|cmd oddly with pipefail; disable briefly.
set +o pipefail
yes | "${SDKMANAGER}" --sdk_root="${ANDROID_HOME}" --licenses
set -o pipefail

echo "==> Installing platform-tools, emulator, platform ${API_LEVEL}, and ${SYSIMG_REQUEST}"
"${SDKMANAGER}" --sdk_root="${ANDROID_HOME}" --install \
  "platform-tools" \
  "emulator" \
  "platforms;android-${API_LEVEL}" \
  "${SYSIMG_REQUEST}"

SYSIMG="$(pick_installed_sysimg || true)"
[[ -n "${SYSIMG}" ]] || die "no system image under ${ANDROID_HOME}; check sdkmanager --list_installed (API ${API_LEVEL})"
echo "    Using installed system image package: ${SYSIMG}"

echo "==> Creating AVD '${AVD_NAME}' (if missing)"
if "${AVDMANAGER}" list avd 2>/dev/null | grep -q "Name: ${AVD_NAME}"; then
  echo "    AVD '${AVD_NAME}' already exists; skipping create."
else
  # Pipe "no" when asked for a custom hardware profile. -d is optional.
  if echo no | "${AVDMANAGER}" create avd \
    -n "${AVD_NAME}" \
    -k "${SYSIMG}" \
    -d pixel_6; then
    :
  else
    echo "    Retrying without -d pixel_6 (device id optional)…"
    echo no | "${AVDMANAGER}" create avd \
      -n "${AVD_NAME}" \
      -k "${SYSIMG}" \
      || die "avdmanager create avd failed; check: ANDROID_SDK_ROOT=${ANDROID_SDK_ROOT} sdkmanager --list_installed | grep system-images"
  fi
fi

echo ""
echo "Done. Add to your shell profile (~/.zshrc):"
echo ""
echo "  export ANDROID_HOME=\"${ANDROID_HOME}\""
echo "  export PATH=\"\${ANDROID_HOME}/emulator:\${ANDROID_HOME}/platform-tools:\${PATH}\""
echo ""
echo "Test the emulator CLI:"
echo "  \"\${ANDROID_HOME}/emulator/emulator\" -list-avds"
echo "  \"\${ANDROID_HOME}/emulator/emulator\" -avd \"${AVD_NAME}\" -no-window -no-audio -gpu swiftshader_indirect"
echo ""
echo "Run moboclaw with real emulators:"
echo "  export EMULATOR_BACKEND=sdk EMULATOR_AVD_NAME=${AVD_NAME}"
echo "  uvicorn app.main:app --host 0.0.0.0 --port 8080"
