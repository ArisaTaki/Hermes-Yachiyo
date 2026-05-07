#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IDENTITY="Hermes-Yachiyo Self Signed"
OUTPUT_DIR="${ROOT}/dist/signing"
DAYS="825"
IMPORT_CERT="true"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --identity)
      IDENTITY="${2:?Missing value for --identity}"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="${2:?Missing value for --output-dir}"
      shift 2
      ;;
    --days)
      DAYS="${2:?Missing value for --days}"
      shift 2
      ;;
    --no-import)
      IMPORT_CERT="false"
      shift
      ;;
    -h|--help)
      cat <<EOF
Usage: scripts/create_macos_self_signed_cert.sh [options]

Options:
  --identity NAME     Certificate common name. Default: Hermes-Yachiyo Self Signed
  --output-dir DIR    Output directory. Default: dist/signing
  --days DAYS         Certificate validity period. Default: 825
  --no-import         Do not import the generated p12 into the login keychain

Set MACOS_CODESIGN_CERTIFICATE_PASSWORD to control the p12 password.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS code signing certificates should be generated on macOS." >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

SLUG="$(printf '%s' "${IDENTITY}" | tr -cs '[:alnum:]_.-' '-' | sed 's/^-//;s/-$//')"
KEY_PATH="${OUTPUT_DIR}/${SLUG}.key"
CERT_PATH="${OUTPUT_DIR}/${SLUG}.crt"
P12_PATH="${OUTPUT_DIR}/${SLUG}.p12"
BASE64_PATH="${OUTPUT_DIR}/${SLUG}.p12.base64"
OPENSSL_CONFIG="${OUTPUT_DIR}/${SLUG}.openssl.cnf"
SECRETS_PATH="${OUTPUT_DIR}/${SLUG}.github-secrets.env"
PASSWORD="${MACOS_CODESIGN_CERTIFICATE_PASSWORD:-$(openssl rand -hex 24)}"
SUBJECT="/CN=${IDENTITY//\//\\/}"

cat > "${OPENSSL_CONFIG}" <<EOF
[ req ]
distinguished_name = req_distinguished_name
x509_extensions = codesign
prompt = no

[ req_distinguished_name ]
CN = ${IDENTITY}

[ codesign ]
basicConstraints = critical,CA:true
keyUsage = critical,digitalSignature,keyCertSign,cRLSign
extendedKeyUsage = codeSigning
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
EOF

openssl req \
  -x509 \
  -newkey rsa:2048 \
  -nodes \
  -days "${DAYS}" \
  -keyout "${KEY_PATH}" \
  -out "${CERT_PATH}" \
  -subj "${SUBJECT}" \
  -config "${OPENSSL_CONFIG}" \
  -extensions codesign

openssl pkcs12 \
  -export \
  -inkey "${KEY_PATH}" \
  -in "${CERT_PATH}" \
  -name "${IDENTITY}" \
  -keypbe PBE-SHA1-3DES \
  -certpbe PBE-SHA1-3DES \
  -macalg SHA1 \
  -out "${P12_PATH}" \
  -passout "pass:${PASSWORD}"

openssl pkcs12 \
  -in "${P12_PATH}" \
  -info \
  -noout \
  -passin "pass:${PASSWORD}" >/dev/null

base64 < "${P12_PATH}" | tr -d '\n' > "${BASE64_PATH}"

cat > "${SECRETS_PATH}" <<EOF
MACOS_CODESIGN_CERTIFICATE_BASE64=$(cat "${BASE64_PATH}")
MACOS_CODESIGN_CERTIFICATE_PASSWORD=${PASSWORD}
MACOS_CODESIGN_IDENTITY=${IDENTITY}
EOF

chmod 600 "${KEY_PATH}" "${P12_PATH}" "${BASE64_PATH}" "${SECRETS_PATH}"

if [[ "${IMPORT_CERT}" == "true" ]]; then
  if security import "${P12_PATH}" \
      -k "${HOME}/Library/Keychains/login.keychain-db" \
      -P "${PASSWORD}" \
      -T /usr/bin/codesign \
      -T /usr/bin/security; then
    security add-trusted-cert \
      -r trustRoot \
      -p codeSign \
      -k "${HOME}/Library/Keychains/login.keychain-db" \
      "${CERT_PATH}" || true
  else
    echo "Warning: generated the certificate files, but importing the p12 into the login keychain failed." >&2
    echo "This is not required for GitHub Actions. Use the generated *.github-secrets.env values as GitHub Secrets." >&2
  fi
fi

echo "Created self-signed certificate: ${IDENTITY}"
echo "p12: ${P12_PATH}"
echo "GitHub Secrets values: ${SECRETS_PATH}"
