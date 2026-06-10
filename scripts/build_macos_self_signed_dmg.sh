#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT}/apps/frontend"
OUTPUT_DIR="${ROOT}/dist/electron"
APP_NAME="${APP_NAME:-Oha-Yachiyo}"
VOLUME_NAME="${VOLUME_NAME:-Oha-Yachiyo}"
SIGNING_IDENTITY="${1:-${MACOS_CODESIGN_IDENTITY:-Oha-Yachiyo Self Signed}}"
ENTITLEMENTS="${ENTITLEMENTS:-${ROOT}/packaging/entitlements.mac.plist}"
TMP_BASE="${RUNNER_TEMP:-/tmp}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS DMG packaging requires macOS." >&2
  exit 1
fi

if [[ -z "${SIGNING_IDENTITY}" ]]; then
  echo "A code signing identity is required." >&2
  exit 1
fi

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

codesign \
  --deep \
  --force \
  --verbose \
  --options runtime \
  --entitlements "${ENTITLEMENTS}" \
  --sign "${SIGNING_IDENTITY}" \
  "${APP_PATH}"
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
