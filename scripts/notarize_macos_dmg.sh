#!/usr/bin/env bash
set -euo pipefail

DMG_PATH="${1:-}"
KEY_PATH="${APPLE_NOTARY_KEY_PATH:-}"
KEY_ID="${APPLE_NOTARY_KEY_ID:-}"
ISSUER_ID="${APPLE_NOTARY_ISSUER_ID:-}"
OUTPUT_DIR="${NOTARIZATION_OUTPUT_DIR:-release}"
SUBMISSION_PATH="${OUTPUT_DIR}/notarization.json"
LOG_PATH="${OUTPUT_DIR}/notarization-log.json"
TIMEOUT="${APPLE_NOTARY_TIMEOUT:-30m}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS notarization requires macOS." >&2
  exit 1
fi

if [[ -z "${DMG_PATH}" || ! -f "${DMG_PATH}" ]]; then
  echo "A readable DMG path is required." >&2
  exit 1
fi

if [[ -z "${KEY_PATH}" || ! -f "${KEY_PATH}" || -L "${KEY_PATH}" ]]; then
  echo "APPLE_NOTARY_KEY_PATH must reference a regular private key file." >&2
  exit 1
fi

if [[ -z "${KEY_ID}" ]]; then
  echo "APPLE_NOTARY_KEY_ID is required." >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"
notary_auth=(--key "${KEY_PATH}" --key-id "${KEY_ID}")
if [[ -n "${ISSUER_ID}" ]]; then
  notary_auth+=(--issuer "${ISSUER_ID}")
fi

NOTARYTOOL_EXIT=0
xcrun notarytool submit \
  "${DMG_PATH}" \
  "${notary_auth[@]}" \
  --wait \
  --timeout "${TIMEOUT}" \
  --output-format json > "${SUBMISSION_PATH}" || NOTARYTOOL_EXIT=$?

if ! SUBMISSION_FIELDS="$(
  python3 - "${SUBMISSION_PATH}" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        payload = json.load(source)
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit(2)
print(f"{payload.get('id', '')}\t{payload.get('status', '')}")
PY
)"; then
  echo "Apple notarytool did not return valid submission JSON (exit: ${NOTARYTOOL_EXIT})." >&2
  exit 1
fi
SUBMISSION_ID="${SUBMISSION_FIELDS%%$'\t'*}"
SUBMISSION_STATUS="${SUBMISSION_FIELDS#*$'\t'}"

if [[ -z "${SUBMISSION_ID}" ]]; then
  echo "Apple notarytool did not return a submission id (exit: ${NOTARYTOOL_EXIT})." >&2
  exit 1
fi

xcrun notarytool log \
  "${SUBMISSION_ID}" \
  "${LOG_PATH}" \
  "${notary_auth[@]}"

if [[ "${SUBMISSION_STATUS}" != "Accepted" || "${NOTARYTOOL_EXIT}" -ne 0 ]]; then
  echo "Apple notarization was not accepted (status: ${SUBMISSION_STATUS:-missing}, notarytool exit: ${NOTARYTOOL_EXIT})." >&2
  echo "Review ${LOG_PATH}." >&2
  exit 1
fi

xcrun stapler staple "${DMG_PATH}"
xcrun stapler validate "${DMG_PATH}"
spctl --assess --type open --context context:primary-signature --verbose=2 "${DMG_PATH}"

echo "Notarized and stapled ${DMG_PATH} (submission ${SUBMISSION_ID})."
