"""Behavioral tests for the macOS notarization shell boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "notarize_macos_dmg.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_tools(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    events = tmp_path / "events.log"
    _write_executable(bin_dir / "uname", "#!/usr/bin/env bash\necho Darwin\n")
    _write_executable(
        bin_dir / "xcrun",
        """#!/usr/bin/env bash
set -euo pipefail
case "$1:$2" in
  notarytool:submit)
    if [[ "${MOCK_SUBMIT_MALFORMED:-false}" == "true" ]]; then
      printf 'authentication failed\n'
    elif [[ "${MOCK_SUBMIT_WITHOUT_ID:-false}" == "true" ]]; then
      printf '{"status":"%s"}\n' "${MOCK_NOTARY_STATUS:-Accepted}"
    else
      printf '{"id":"submission-123","status":"%s"}\n' "${MOCK_NOTARY_STATUS:-Accepted}"
    fi
    echo submit >> "${MOCK_EVENT_LOG}"
    exit "${MOCK_SUBMIT_EXIT:-0}"
    ;;
  notarytool:log)
    printf '{"jobId":"%s","status":"%s"}\n' "$3" "${MOCK_NOTARY_STATUS:-Accepted}" > "$4"
    echo log >> "${MOCK_EVENT_LOG}"
    ;;
  stapler:staple|stapler:validate)
    echo "$2" >> "${MOCK_EVENT_LOG}"
    ;;
  *)
    echo "unexpected xcrun command: $*" >&2
    exit 2
    ;;
esac
""",
    )
    _write_executable(
        bin_dir / "spctl",
        "#!/usr/bin/env bash\nset -euo pipefail\necho assess >> \"${MOCK_EVENT_LOG}\"\n",
    )
    return bin_dir, events


def _run_notarization(
    tmp_path: Path,
    *,
    status: str,
    submit_exit: int = 0,
    malformed: bool = False,
    without_id: bool = False,
) -> subprocess.CompletedProcess[str]:
    bin_dir, events = _fake_tools(tmp_path)
    dmg = tmp_path / "Oha-Yachiyo.dmg"
    dmg.write_bytes(b"fake dmg")
    key = tmp_path / "AuthKey_TEST.p8"
    key.write_text("fake private key", encoding="utf-8")
    key.chmod(0o600)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "APPLE_NOTARY_KEY_PATH": str(key),
            "APPLE_NOTARY_KEY_ID": "TESTKEY123",
            "APPLE_NOTARY_ISSUER_ID": "00000000-0000-0000-0000-000000000000",
            "MOCK_NOTARY_STATUS": status,
            "MOCK_SUBMIT_EXIT": str(submit_exit),
            "MOCK_SUBMIT_MALFORMED": str(malformed).lower(),
            "MOCK_SUBMIT_WITHOUT_ID": str(without_id).lower(),
            "MOCK_EVENT_LOG": str(events),
        }
    )
    return subprocess.run(
        [str(SCRIPT), str(dmg)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_notarization_script_persists_log_and_staples_accepted_dmg(tmp_path):
    result = _run_notarization(tmp_path, status="Accepted")

    assert result.returncode == 0, result.stderr
    assert json.loads(
        (tmp_path / "release" / "notarization.json").read_text(encoding="utf-8")
    ) == {
        "id": "submission-123",
        "status": "Accepted",
    }
    assert json.loads(
        (tmp_path / "release" / "notarization-log.json").read_text(encoding="utf-8")
    )["status"] == "Accepted"
    assert (tmp_path / "events.log").read_text(encoding="utf-8").splitlines() == [
        "submit",
        "log",
        "staple",
        "validate",
        "assess",
    ]


def test_notarization_script_rejects_invalid_submission_before_stapling(tmp_path):
    result = _run_notarization(tmp_path, status="Invalid", submit_exit=3)

    assert result.returncode == 1
    assert "Apple notarization was not accepted (status: Invalid, notarytool exit: 3)." in result.stderr
    assert (tmp_path / "events.log").read_text(encoding="utf-8").splitlines() == [
        "submit",
        "log",
    ]


def test_notarization_script_reports_malformed_submit_output_without_traceback(tmp_path):
    result = _run_notarization(
        tmp_path,
        status="",
        submit_exit=2,
        malformed=True,
    )

    assert result.returncode == 1
    assert "Apple notarytool did not return valid submission JSON (exit: 2)." in result.stderr
    assert "Traceback" not in result.stderr
    assert (tmp_path / "events.log").read_text(encoding="utf-8").splitlines() == ["submit"]


def test_notarization_script_rejects_submit_output_without_submission_id(tmp_path):
    result = _run_notarization(
        tmp_path,
        status="Accepted",
        without_id=True,
    )

    assert result.returncode == 1
    assert "Apple notarytool did not return a submission id (exit: 0)." in result.stderr
    assert (tmp_path / "events.log").read_text(encoding="utf-8").splitlines() == ["submit"]
