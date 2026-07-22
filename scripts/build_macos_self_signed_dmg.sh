#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT}/apps/frontend"
OUTPUT_DIR="${ROOT}/dist/electron"
APP_NAME="${APP_NAME:-Oha-Yachiyo}"
VOLUME_NAME="${VOLUME_NAME:-Oha-Yachiyo}"
SIGNING_IDENTITY="${1:-${MACOS_CODESIGN_IDENTITY:-Oha-Yachiyo Self Signed}}"
SIGNING_MODE="${2:-${MACOS_SIGNING_MODE:-}}"
ENTITLEMENTS="${ENTITLEMENTS:-${ROOT}/packaging/entitlements.mac.plist}"
CUA_ENTITLEMENTS="${CUA_ENTITLEMENTS:-${ROOT}/packaging/entitlements.cua-driver.plist}"
BACKEND_ENTITLEMENTS="${BACKEND_ENTITLEMENTS:-${ROOT}/packaging/entitlements.backend.plist}"
BACKEND_SIGNING_IDENTIFIER="io.github.arisataki.oha-yachiyo.backend"
TMP_BASE="${RUNNER_TEMP:-/tmp}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS DMG packaging requires macOS." >&2
  exit 1
fi

if [[ -z "${SIGNING_IDENTITY}" ]]; then
  echo "A code signing identity is required." >&2
  exit 1
fi

if [[ -z "${SIGNING_MODE}" ]]; then
  if [[ "${SIGNING_IDENTITY}" == "Developer ID Application:"* ]]; then
    SIGNING_MODE="developer-id-app-notarized-dmg"
  else
    SIGNING_MODE="self-signed-app-unsigned-dmg"
  fi
fi

case "${SIGNING_MODE}" in
  developer-id-app-notarized-dmg|self-signed-app-unsigned-dmg) ;;
  *)
    echo "Unsupported macOS signing mode: ${SIGNING_MODE}" >&2
    exit 1
    ;;
esac

python3 "${ROOT}/scripts/prepare_cua_driver.py"
npm --prefix "${FRONTEND_DIR}" run build

mkdir -p "${OUTPUT_DIR}"
rm -f "${OUTPUT_DIR}"/*.dmg

(
  cd "${FRONTEND_DIR}"
  CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --config electron-builder.yml --mac dir
)

APP_PATH="$(find "${OUTPUT_DIR}" -maxdepth 3 -name "${APP_NAME}.app" -type d -print -quit)"
if [[ -z "${APP_PATH}" ]]; then
  echo "No packaged app found under ${OUTPUT_DIR}." >&2
  exit 1
fi

STANDALONE_BACKEND_PATH="${ROOT}/dist/backend/oha-yachiyo-backend"
PACKAGED_BACKEND_PATH="${APP_PATH}/Contents/Resources/backend/oha-yachiyo-backend"
for backend_path in "${STANDALONE_BACKEND_PATH}" "${PACKAGED_BACKEND_PATH}"; do
  if [[ -L "${backend_path}" || ! -f "${backend_path}" || ! -x "${backend_path}" ]]; then
    echo "Packaged backend must be a regular executable: ${backend_path}" >&2
    exit 1
  fi
done

CUA_HELPER_PATH="${APP_PATH}/Contents/Resources/computer-use/macos/OhaCuaDriver.app"
CUA_HELPER_INFO_PATH="${CUA_HELPER_PATH}/Contents/Info.plist"
CUA_DRIVER_PATH="${CUA_HELPER_PATH}/Contents/MacOS/cua-driver"
if [[ -L "${CUA_HELPER_PATH}" || ! -d "${CUA_HELPER_PATH}" ]]; then
  echo "Packaged Cua Driver helper must be a real app bundle: ${CUA_HELPER_PATH}" >&2
  exit 1
fi
if [[ -L "${CUA_DRIVER_PATH}" || ! -f "${CUA_DRIVER_PATH}" || ! -x "${CUA_DRIVER_PATH}" ]]; then
  echo "Packaged Cua Driver must be a regular executable: ${CUA_DRIVER_PATH}" >&2
  exit 1
fi

python3 -c '
import plistlib
import sys

expected = {
    "com.apple.security.automation.apple-events": True,
    "com.apple.security.device.screen-capture": True,
}
with open(sys.argv[1], "rb") as handle:
    actual = plistlib.load(handle)
if actual != expected:
    raise SystemExit("Cua Driver entitlement policy must contain exactly Apple Events and Screen Capture.")
' "${CUA_ENTITLEMENTS}"

python3 -c '
import plistlib
import sys

expected = {
    "com.apple.security.cs.disable-library-validation": True,
}
with open(sys.argv[1], "rb") as handle:
    actual = plistlib.load(handle)
if actual != expected:
    raise SystemExit("Backend entitlement policy must contain exactly Disable Library Validation.")
' "${BACKEND_ENTITLEMENTS}"

python3 -c '
import plistlib
import sys

with open(sys.argv[1], "rb") as handle:
    info = plistlib.load(handle)
expected = {
    "CFBundleExecutable": "cua-driver",
    "CFBundleIdentifier": "io.github.arisataki.oha-yachiyo.cua-driver",
    "CFBundlePackageType": "APPL",
    "LSBackgroundOnly": True,
}
if any(info.get(key) != value for key, value in expected.items()):
    raise SystemExit("Cua Driver helper must be an LSBackgroundOnly app bundle.")
' "${CUA_HELPER_INFO_PATH}"

cua_codesign_args=(
  --force
  --verbose
  --options runtime
  --entitlements "${CUA_ENTITLEMENTS}"
  --sign "${SIGNING_IDENTITY}"
)
if [[ "${SIGNING_MODE}" == "developer-id-app-notarized-dmg" ]]; then
  cua_codesign_args+=(--timestamp)
fi
codesign "${cua_codesign_args[@]}" "${CUA_HELPER_PATH}"

backend_codesign_args=(
  --force
  --verbose
  --options runtime
  --identifier "${BACKEND_SIGNING_IDENTIFIER}"
  --entitlements "${BACKEND_ENTITLEMENTS}"
  --sign "${SIGNING_IDENTITY}"
)
if [[ "${SIGNING_MODE}" == "developer-id-app-notarized-dmg" ]]; then
  backend_codesign_args+=(--timestamp)
fi
# The backend is a separate executable and intentionally receives only the
# library-validation exception required by its adjacent PyInstaller runtime,
# not the Electron main-process JIT entitlements.  A stable identifier plus the
# long-lived app signing identity keeps its Keychain ACL stable across rebuilds.
codesign "${backend_codesign_args[@]}" "${STANDALONE_BACKEND_PATH}"
codesign "${backend_codesign_args[@]}" "${PACKAGED_BACKEND_PATH}"

codesign_args=(
  --force
  --verbose
  --options runtime
  --entitlements "${ENTITLEMENTS}"
  --sign "${SIGNING_IDENTITY}"
)
if [[ "${SIGNING_MODE}" == "developer-id-app-notarized-dmg" ]]; then
  codesign_args+=(--timestamp)
fi
# Sign only the outer bundle here.  The Cua helper is an independent nested
# code object that was deliberately signed above with a stricter entitlement
# set.  `codesign --deep --force` would recursively overwrite that signature
# with the Electron app entitlements and silently break background control.
codesign "${codesign_args[@]}" "${APP_PATH}"

verify_backend_signature() {
  local backend_path="$1"
  local signature_details
  local actual_identifier
  local requirement_output
  local designated_requirement

  codesign --verify --strict --verbose=2 "${backend_path}"
  signature_details="$(codesign -d --verbose=4 "${backend_path}" 2>&1)"
  actual_identifier="$(printf '%s\n' "${signature_details}" | sed -n 's/^Identifier=//p')"
  if [[ "${actual_identifier}" != "${BACKEND_SIGNING_IDENTIFIER}" ]]; then
    echo "Signed backend identifier is unstable: ${actual_identifier:-<missing>}" >&2
    exit 1
  fi

  requirement_output="$(codesign -dr - "${backend_path}" 2>&1)"
  if [[ "${SIGNING_IDENTITY}" == "-" ]]; then
    echo "Backend is ad-hoc signed; Keychain ACL stability is not available: ${backend_path}" >&2
  else
    if [[ "${requirement_output}" != *"designated => "* ]]; then
      echo "Signed backend has no designated requirement: ${backend_path}" >&2
      exit 1
    fi
    designated_requirement="${requirement_output##*designated => }"
    if [[ "${designated_requirement}" == cdhash* ]]; then
      echo "Signed backend designated requirement is cdhash-only: ${backend_path}" >&2
      exit 1
    fi
    if [[ "${designated_requirement}" != *"identifier \"${BACKEND_SIGNING_IDENTIFIER}\""* ]]; then
      echo "Signed backend designated requirement does not contain the stable identifier: ${backend_path}" >&2
      exit 1
    fi
  fi

  codesign -d --entitlements - --xml "${backend_path}" 2>/dev/null | python3 -c '
import plistlib
import sys

expected = {
    "com.apple.security.cs.disable-library-validation": True,
}
actual = plistlib.loads(sys.stdin.buffer.read())
if actual != expected:
    raise SystemExit("Signed backend entitlement policy is not exact.")
'
}

verify_backend_signature "${STANDALONE_BACKEND_PATH}"
verify_backend_signature "${PACKAGED_BACKEND_PATH}"
codesign --verify --strict --verbose=2 "${CUA_HELPER_PATH}"
codesign --verify --strict --verbose=2 "${CUA_DRIVER_PATH}"
codesign -d --entitlements - --xml "${CUA_DRIVER_PATH}" 2>/dev/null | python3 -c '
import plistlib
import sys

expected = {
    "com.apple.security.automation.apple-events": True,
    "com.apple.security.device.screen-capture": True,
}
actual = plistlib.loads(sys.stdin.buffer.read())
if actual != expected:
    raise SystemExit("Signed Cua Driver entitlement policy is not exact.")
'
codesign --verify --deep --strict --verbose=2 "${APP_PATH}"

VERSION="$(node -e "console.log(require('${FRONTEND_DIR}/package.json').version)")"
ARCH="$(uname -m)"
case "${ARCH}" in
  arm64) DMG_ARCH="arm64" ;;
  x86_64) DMG_ARCH="x64" ;;
  *) DMG_ARCH="${ARCH}" ;;
esac

DMG_STAGING="$(mktemp -d "${TMP_BASE}/oha-yachiyo-dmg.XXXXXX")"
trap 'rm -rf "${DMG_STAGING}"' EXIT

cp -R "${APP_PATH}" "${DMG_STAGING}/"
ln -s /Applications "${DMG_STAGING}/Applications"

DMG_PATH="${OUTPUT_DIR}/${APP_NAME}-${VERSION}-${DMG_ARCH}.dmg"
hdiutil create \
  -volname "${VOLUME_NAME}" \
  -srcfolder "${DMG_STAGING}" \
  -ov \
  -format UDZO \
  "${DMG_PATH}"

echo "${DMG_PATH}"
