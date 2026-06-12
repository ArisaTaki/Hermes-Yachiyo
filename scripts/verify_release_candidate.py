"""Local release-candidate verification entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

_SOURCE_REVISION_SUBPROCESS_POPEN = subprocess.Popen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_electron_ui_smokes import (
    electron_ui_smoke_scripts as release_ui_smoke_scripts,
    run_electron_ui_smoke_report,
)
from scripts.verify_release_artifacts import Finding, verify_release_artifacts
from packages.security import redact_api_error_text

DEFAULT_ARTIFACT_PATHS: tuple[Path, ...] = (
    Path("dist/backend"),
    Path("dist/electron"),
    Path("release"),
)
PACKAGED_APP_NAME = "Oha-Yachiyo.app"
PACKAGED_APP_EXECUTABLE_NAME = "Oha-Yachiyo"
DMG_APP_SMOKE_TIMEOUT_SECONDS = 45.0
DMG_SCREEN_PROBE_REQUEST_TIMEOUT_SECONDS = 10.0
DMG_UI_SAMPLING_SMOKE_TIMEOUT_SECONDS = 60.0
DMG_UI_SAMPLING_SMOKE_SCRIPT = Path("scripts/smoke_packaged_ui_sampling.mjs")
DMG_CHAT_NATIVE_FILE_SMOKE_TIMEOUT_SECONDS = 60.0
DMG_CHAT_NATIVE_FILE_SMOKE_SCRIPT = Path("scripts/smoke_packaged_chat_native_file_upload.mjs")
DMG_BRIDGE_STATUS_REPORT_SECTIONS: tuple[str, ...] = (
    "dmg_app_smoke",
    "dmg_screen_probe",
    "dmg_ui_sampling_smoke",
)
PROVIDER_SMOKE_ENV_VARS: tuple[str, ...] = (
    "OHA_YACHIYO_SMOKE_BASE_URL",
    "OHA_YACHIYO_SMOKE_MODEL",
    "OHA_YACHIYO_SMOKE_API_KEY",
)
PROVIDER_SMOKE_SCRIPT = Path("scripts/smoke_openai_compatible_stream.py")
PROVIDER_SMOKE_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "text_stream",
        (
            "--require-content",
            "--expect-finish-reason",
            "stop",
        ),
    ),
    (
        "tool_call_stream",
        (
            "--tool-call",
            "--require-tool-call",
            "--require-tool-result-content",
            "--expect-tool-name",
            "workspace_read",
            "--expect-tool-argument-substring",
            "README.md",
            "--expect-tool-argument-json-field",
            "path=README.md",
            "--expect-finish-reason",
            "tool_calls",
            "--expect-tool-result-finish-reason",
            "stop",
        ),
    ),
)
MANUAL_RELEASE_CANDIDATE_CHECK_STATUS_VALUES: tuple[str, ...] = (
    "manual_required",
    "passed",
    "failed",
    "not_applicable",
)
MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS: tuple[dict[str, str], ...] = (
    {
        "id": "gatekeeper_first_launch",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "Mount the DMG and launch Oha-Yachiyo.app once with the documented Gatekeeper first-launch flow.",
        "evidence": "Record the mounted DMG path and confirm Finder Control-click -> Open or System Settings allow-open flow reaches the app.",
        "next_action": "Manually mount the final DMG and launch Oha-Yachiyo.app through Finder Control-click -> Open or the System Settings allow-open flow.",
    },
    {
        "id": "packaged_bridge_isolation",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "Confirm the packaged app starts its local bridge and does not connect to a development backend.",
        "evidence": "Record the packaged bridge /status response and confirm the bridge URL is local loopback.",
        "next_action": "Prefer rerunning the RC gate with --run-dmg-app-smoke; otherwise manually record the packaged /status response and loopback bridge URL.",
    },
    {
        "id": "screen_recording_permission",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "Grant Screen Recording permission to Oha-Yachiyo.app and verify the local screenshot/proactive probe path.",
        "evidence": "Record the System Settings permission state and a successful local screenshot or proactive probe result.",
        "next_action": "Prefer rerunning the RC gate with --run-dmg-screen-smoke after granting Screen Recording; otherwise manually record the System Settings permission state and local screenshot/proactive probe result.",
    },
    {
        "id": "chat_native_file_upload",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "Use the packaged app's Chat image attach button with the native file picker and verify preview, send, message attachment, image viewer, and Run Detail handoff.",
        "evidence": "Record the image filename, native picker path used, sent message attachment metadata, image viewer open/close result, and linked Run Detail id.",
        "next_action": "Prefer rerunning the RC gate with --run-dmg-chat-native-file-smoke; otherwise manually use the packaged Chat image attach button and native file picker, then verify preview, send, image viewer, and Run Detail handoff.",
    },
    {
        "id": "packaged_ui_sampling",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "Sample mature packaged app surfaces across Chat approval/cancel, Run Detail replay, Workflow save-and-run, Agent Studio, group/delegation/session summary, manual TTS, and Live2D.",
        "evidence": "Record the packaged app build, sampled pages/actions, and visible pass/fail result for each sampled mature surface.",
        "next_action": "Prefer rerunning the RC gate with --run-dmg-ui-sampling-smoke; otherwise manually sample the packaged app surfaces listed here.",
    },
    {
        "id": "real_provider_smoke",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "If real provider credentials are available, run --run-provider-smoke for the opt-in streaming/tool-call provider gate.",
        "evidence": "Archive the RC report provider_smoke section from a credentialed run, or record that provider credentials were unavailable.",
        "next_action": "If OHA_YACHIYO_SMOKE_* credentials are available, rerun the RC gate with --run-provider-smoke; otherwise mark not_applicable with credentials-unavailable evidence.",
    },
)
MANUAL_RELEASE_CANDIDATE_CHECK_AUTOMATION_COMMANDS: dict[str, str] = {
    "packaged_bridge_isolation": (
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-app-smoke --report-json tmp/rc-verification-dmg-app.json"
    ),
    "screen_recording_permission": (
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-screen-smoke --report-json tmp/rc-verification-screen.json"
    ),
    "chat_native_file_upload": (
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-chat-native-file-smoke "
        "--report-json tmp/rc-verification-chat-native-file.json"
    ),
    "packaged_ui_sampling": (
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-ui-sampling-smoke --report-json tmp/rc-verification-packaged-ui.json"
    ),
    "real_provider_smoke": (
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--check-dmg-mount --run-provider-smoke "
        "--report-json tmp/rc-verification-provider-smoke.json"
    ),
}
MANUAL_RELEASE_CANDIDATE_CHECKS: tuple[str, ...] = tuple(
    check["description"] for check in MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
)
MANUAL_RELEASE_CANDIDATE_CHECK_MARKDOWN_RE = re.compile(
    r"^- \[(?P<checked>[ xX])\] `(?P<id>[^`]+)`(?: - (?P<status>[A-Za-z_]+))?\s*$"
)
MANUAL_RELEASE_CANDIDATE_CHECK_SOURCE_REVISIONS_MARKDOWN_PREFIX = (
    "<!-- manual_release_candidate_check_source_revisions: "
)
MANUAL_RELEASE_CANDIDATE_CHECK_SOURCE_REVISIONS_MARKDOWN_SUFFIX = " -->"


def _manual_release_candidate_check_report() -> list[dict[str, str]]:
    return [dict(check) for check in MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS]


def _manual_release_candidate_check_template() -> dict[str, object]:
    return {
        "checks": [
            {
                "id": check["id"],
                "status": "manual_required",
                "required_before": check["required_before"],
                "description": check["description"],
                "evidence_prompt": check["evidence"],
                "next_action": check["next_action"],
                "evidence": "",
                "notes": "",
            }
            for check in MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
        ]
    }


ManualChecksJsonInput = Path | Sequence[Path | str] | str | None
ManualChecksSource = Path | Sequence[Path | str] | str | None


def _manual_checks_json_paths(manual_checks_json: ManualChecksJsonInput) -> tuple[Path, ...]:
    if manual_checks_json is None:
        return ()
    if isinstance(manual_checks_json, (Path, str)):
        return (Path(manual_checks_json),)
    return tuple(Path(path) for path in manual_checks_json)


def _manual_checks_source_label(source_path: ManualChecksSource) -> str:
    if source_path is None:
        return ""
    if isinstance(source_path, str):
        return source_path
    if isinstance(source_path, Path):
        return str(source_path)
    return ", ".join(str(path) for path in source_path)


def _run_source_revision_git_command(
    command: Sequence[str],
    *,
    root: Path,
) -> subprocess.CompletedProcess[str]:
    git_command = list(command)
    with _SOURCE_REVISION_SUBPROCESS_POPEN(
        git_command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(
            process.returncode,
            git_command,
            output=stdout,
            stderr=stderr,
        )
    return subprocess.CompletedProcess(git_command, process.returncode, stdout, stderr)


def _source_revision(root: Path) -> dict[str, object]:
    try:
        commit = _run_source_revision_git_command(
            ["git", "rev-parse", "HEAD"],
            root=root,
        ).stdout.strip()
        status = _run_source_revision_git_command(
            ["git", "status", "--short"],
            root=root,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        return {
            "available": False,
            "commit": "",
            "short_commit": "",
            "dirty": True,
            "error": redact_api_error_text(str(exc), fallback="git source revision unavailable"),
        }
    return {
        "available": bool(commit),
        "commit": commit,
        "short_commit": commit[:7],
        "dirty": bool(status.strip()),
    }


def _manual_check_source_revisions(
    root: Path,
    source_path: ManualChecksSource,
) -> list[dict[str, object]]:
    revisions: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    for manual_checks_path in _manual_checks_json_paths(source_path):
        try:
            evidence_path = _resolve_project_file(
                root,
                manual_checks_path,
                "manual release-candidate checks",
            )
            raw_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(raw_payload, dict):
            continue
        candidates: list[dict[str, object]] = []
        source_revision = raw_payload.get("source_revision")
        if isinstance(source_revision, dict):
            candidates.append({"source": str(manual_checks_path), **source_revision})
        nested_revisions = raw_payload.get("manual_release_candidate_check_source_revisions")
        if isinstance(nested_revisions, list):
            candidates.extend(item for item in nested_revisions if isinstance(item, dict))
        for candidate in candidates:
            source = str(candidate.get("source") or manual_checks_path)
            commit = str(candidate.get("commit") or "")
            key = (source, commit)
            if key in seen:
                continue
            seen.add(key)
            revisions.append({"source": source, **candidate})
    return revisions


def _manual_check_source_revision_summary(
    source_revisions: Sequence[dict[str, object]],
) -> str:
    labels: list[str] = []
    for revision in source_revisions:
        source = str(revision.get("source") or "unknown-source")
        short_commit = str(revision.get("short_commit") or "").strip()
        commit = str(revision.get("commit") or "").strip()
        label_commit = short_commit or commit[:7] or "unavailable"
        dirty_suffix = " dirty" if revision.get("dirty") is True else ""
        labels.append(f"`{source}@{label_commit}{dirty_suffix}`")
    return ", ".join(labels) if labels else "none"


def _manual_check_source_revisions_from_markdown(
    raw_text: str,
) -> list[dict[str, object]]:
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not (
            stripped.startswith(MANUAL_RELEASE_CANDIDATE_CHECK_SOURCE_REVISIONS_MARKDOWN_PREFIX)
            and stripped.endswith(MANUAL_RELEASE_CANDIDATE_CHECK_SOURCE_REVISIONS_MARKDOWN_SUFFIX)
        ):
            continue
        payload = stripped[
            len(MANUAL_RELEASE_CANDIDATE_CHECK_SOURCE_REVISIONS_MARKDOWN_PREFIX) :
            -len(MANUAL_RELEASE_CANDIDATE_CHECK_SOURCE_REVISIONS_MARKDOWN_SUFFIX)
        ]
        try:
            raw_revisions = json.loads(payload)
        except json.JSONDecodeError:
            return []
        if isinstance(raw_revisions, list):
            return [dict(item) for item in raw_revisions if isinstance(item, dict)]
        return []
    return []


def _manual_check_markdown_source_revisions(
    root: Path,
    markdown_path: Path | None,
) -> list[dict[str, object]]:
    if markdown_path is None:
        return []
    try:
        evidence_path = _resolve_project_file(
            root,
            markdown_path,
            "manual release-candidate checks markdown",
        )
        return _manual_check_source_revisions_from_markdown(
            evidence_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return []


def _manual_release_candidate_check_draft(
    checks: Sequence[dict[str, str]],
    *,
    source_path: ManualChecksSource = None,
    source_revisions: Sequence[dict[str, object]] | None = None,
) -> dict[str, object]:
    check_details = {check["id"]: check for check in MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS}
    draft_checks: list[dict[str, str]] = []
    for check in checks:
        check_id = check["id"]
        details = check_details[check_id]
        status = check.get("status", "manual_required")
        evidence = str(check.get("evidence", "")).strip()
        if status == "manual_required" and evidence == details["evidence"]:
            evidence = ""
        draft_check = {
            "id": check_id,
            "status": status,
            "required_before": details["required_before"],
            "description": details["description"],
            "evidence_prompt": details["evidence"],
            "next_action": details["next_action"],
            "evidence": evidence,
            "notes": str(check.get("notes", "")),
        }
        evidence_source = str(check.get("evidence_source", "")).strip()
        if evidence_source:
            draft_check["evidence_source"] = evidence_source
        draft_checks.append(draft_check)

    draft: dict[str, object] = {
        "checks": draft_checks,
        "manual_release_candidate_check_summary": _manual_release_candidate_check_summary(
            draft_checks
        ),
    }
    source_label = _manual_checks_source_label(source_path)
    if source_label:
        draft["manual_release_candidate_checks_source"] = source_label
    if source_revisions:
        draft["manual_release_candidate_check_source_revisions"] = list(source_revisions)
    return draft


def _manual_release_candidate_checks_markdown(
    checks: Sequence[dict[str, str]],
    *,
    source_path: ManualChecksSource = None,
    source_revisions: Sequence[dict[str, object]] | None = None,
    markdown_path: Path | None = None,
) -> str:
    summary = _manual_release_candidate_check_summary(checks)
    remaining_checks = [
        check for check in checks if check.get("status") == "manual_required"
    ]
    completed_checks = [
        check for check in checks if check.get("status") != "manual_required"
    ]
    automated_ids = summary.get("automated_evidence_check_ids", [])
    failed_ids = summary.get("failed_check_ids", [])
    remaining_commands = summary.get("remaining_commands", [])
    manual_checks_arg = str(markdown_path) if markdown_path is not None else "<this-checklist.md>"
    source_revision_items = list(source_revisions or [])
    lines = [
        "# Oha-Yachiyo Manual Release-Candidate Signoff",
        "",
        f"- Source: `{_manual_checks_source_label(source_path)}`"
        if source_path is not None
        else "- Source: manual checks",
        f"- Source revisions: {_manual_check_source_revision_summary(source_revision_items)}",
        f"- Remaining checks: {summary['remaining_count']}",
        f"- Failed checks: {len(failed_ids) if isinstance(failed_ids, list) else 0}",
        "- Automated evidence: "
        + (
            ", ".join(f"`{check_id}`" for check_id in automated_ids)
            if isinstance(automated_ids, list) and automated_ids
            else "none"
        ),
        "",
        "## How To Fill",
        "",
        "- Leave ``- [ ] `check_id` `` unchanged to keep `manual_required`.",
        "- Change to ``- [x] `check_id` `` to mark `passed`; omitted status defaults to `passed`.",
        "- Use ``- [x] `check_id` - not_applicable`` or ``- [x] `check_id` - failed`` for explicit outcomes.",
        "- Every `passed`, `failed`, or `not_applicable` item needs non-empty `Evidence:`; indent continuation lines under it.",
        "",
        "## Final Gate",
        "",
        "After filling this checklist, run:",
        "",
        "```bash",
        "python scripts/verify_release_candidate.py --require-artifacts "
        f"--manual-checks-markdown {manual_checks_arg} "
        "--require-manual-checks-complete --report-json tmp/rc-with-manual-checks.json",
        "```",
        "",
        "## Remaining Automation Commands",
        "",
    ]
    if isinstance(remaining_commands, list) and remaining_commands:
        lines.append("Run any applicable automated gate before filling manual evidence:")
        lines.append("")
        for item in remaining_commands:
            if not isinstance(item, dict):
                continue
            check_id = str(item.get("id", "")).strip()
            command = str(item.get("command", "")).strip()
            if not check_id or not command:
                continue
            lines.extend(
                [
                    f"- `{check_id}`",
                    "```bash",
                    command,
                    "```",
                ]
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Remaining Manual Checks", ""])
    if source_revision_items:
        lines.extend(
            [
                (
                    MANUAL_RELEASE_CANDIDATE_CHECK_SOURCE_REVISIONS_MARKDOWN_PREFIX
                    + json.dumps(
                        source_revision_items,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + MANUAL_RELEASE_CANDIDATE_CHECK_SOURCE_REVISIONS_MARKDOWN_SUFFIX
                ),
                "",
            ]
        )
    if not remaining_checks:
        lines.append("- None")
    for check in remaining_checks:
        notes = str(check.get("notes", "")).strip()
        lines.extend(
            [
                f"- [ ] `{check['id']}`",
                f"  - Description: {check.get('description', '')}",
                f"  - Next action: {check.get('next_action', '')}",
                f"  - Evidence to record: {check.get('evidence_prompt', check.get('evidence', ''))}",
                "  - Evidence:",
                f"  - Notes: {notes}" if notes else "  - Notes:",
            ]
        )

    lines.extend(["", "## Completed Or Not Applicable Checks", ""])
    if not completed_checks:
        lines.append("- None")
    for check in completed_checks:
        evidence = str(check.get("evidence", "")).strip()
        notes = str(check.get("notes", "")).strip()
        lines.extend(
            [
                f"- [x] `{check['id']}` - {check.get('status', '')}",
                f"  - Description: {check.get('description', '')}",
            ]
        )
        evidence_source = str(check.get("evidence_source", "")).strip()
        if evidence_source:
            lines.append(f"  - Evidence source: {evidence_source}")
        if evidence:
            lines.append(f"  - Evidence: {evidence}")
        if notes:
            lines.append(f"  - Notes: {notes}")
    lines.append("")
    return "\n".join(lines)


def _mark_provider_smoke_not_applicable_if_missing(
    checks: Sequence[dict[str, str]],
) -> bool:
    missing = [name for name in PROVIDER_SMOKE_ENV_VARS if not os.environ.get(name)]
    if not missing:
        return False
    check = _manual_release_candidate_checks_by_id(checks).get("real_provider_smoke")
    if check is None or check.get("status") != "manual_required":
        return False
    check["status"] = "not_applicable"
    check["evidence"] = (
        "Real provider smoke credentials were unavailable in this environment; "
        f"missing environment variables: {', '.join(missing)}. No external provider "
        "call was attempted for this signoff draft."
    )
    check["evidence_source"] = "credentials_unavailable"
    return True


def _manual_release_candidate_checks_from_payload(raw_payload: Any) -> object:
    if isinstance(raw_payload, dict):
        if "checks" in raw_payload:
            checks = raw_payload.get("checks")
        else:
            checks = raw_payload.get("manual_release_candidate_check_statuses")
        if isinstance(checks, list):
            return _manual_release_candidate_checks_with_supporting_evidence(
                checks,
                raw_payload,
            )
        return checks
    return raw_payload


def _standalone_electron_ui_smoke_report(raw_payload: Any) -> dict[str, Any] | None:
    if not isinstance(raw_payload, dict):
        return None
    if "manual_release_candidate_check_statuses" in raw_payload or "checks" in raw_payload:
        return None
    scripts = raw_payload.get("scripts")
    if "ok" not in raw_payload or not isinstance(scripts, list):
        return None
    return {
        "status": "passed" if raw_payload.get("ok") is True else "failed",
        "script_count": raw_payload.get("script_count"),
        "scripts": scripts,
    }


def _append_manual_release_candidate_check_note(
    checks: Sequence[Any],
    check_id: str,
    note: str,
) -> None:
    for check in checks:
        if not isinstance(check, dict) or check.get("id") != check_id:
            continue
        existing = str(check.get("notes", "")).strip()
        if note in existing:
            return
        check["notes"] = f"{existing}\n{note}" if existing else note
        return


def _append_electron_ui_smoke_supporting_evidence(
    checks: Sequence[Any],
    electron_ui_smoke: Any,
) -> None:
    if not isinstance(electron_ui_smoke, dict) or electron_ui_smoke.get("status") != "passed":
        return
    scripts = electron_ui_smoke.get("scripts")
    if not isinstance(scripts, list):
        return
    passed_scripts = [
        str(script.get("script", "")).strip()
        for script in scripts
        if isinstance(script, dict)
        and script.get("exit_code") == 0
        and str(script.get("script", "")).strip()
    ]
    if not passed_scripts:
        return
    script_count = electron_ui_smoke.get("script_count")
    script_count_text = (
        str(script_count)
        if isinstance(script_count, int) and script_count >= len(passed_scripts)
        else str(len(passed_scripts))
    )
    _append_manual_release_candidate_check_note(
        checks,
        "packaged_ui_sampling",
        (
            f"Supporting automated evidence: --run-ui-smoke passed {script_count_text} "
            f"Electron UI smoke scripts: {', '.join(passed_scripts)}."
        ),
    )
    if any(script.endswith("smoke_chat_image_attachment_ui.mjs") for script in passed_scripts):
        _append_manual_release_candidate_check_note(
            checks,
            "chat_native_file_upload",
            (
                "Supporting automated evidence: smoke_chat_image_attachment_ui.mjs "
                "passed via Electron UI smoke, including the desktop chooseChatImages "
                "API path; the packaged OS file picker still requires manual evidence."
            ),
        )


def _dmg_screen_probe_failure_reason(dmg_screen_probe: dict[str, Any]) -> str:
    findings = dmg_screen_probe.get("findings")
    if not isinstance(findings, list):
        return "the recorded probe error"
    messages: list[str] = []
    for finding in findings:
        if isinstance(finding, dict):
            message = str(finding.get("message", "")).strip()
        else:
            message = str(finding).strip()
        if message:
            messages.append(message)
    for message in messages:
        if "screen_capture_permission_denied" in message:
            return "screen_capture_permission_denied"
        match = re.search(r'"error"\s*:\s*"([^"]+)"', message)
        if match:
            return match.group(1)
    return "the recorded probe error"


def _append_dmg_screen_probe_failure_supporting_evidence(
    checks: Sequence[Any],
    dmg_screen_probe: Any,
) -> None:
    if (
        not isinstance(dmg_screen_probe, dict)
        or dmg_screen_probe.get("status") != "failed"
    ):
        return
    raw_paths = dmg_screen_probe.get("bridge_ready_dmg_paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        return
    artifact_label = ", ".join(str(path) for path in raw_paths if path)
    if not artifact_label:
        artifact_label = "selected DMG artifacts"
    reason = _dmg_screen_probe_failure_reason(dmg_screen_probe)
    _append_manual_release_candidate_check_note(
        checks,
        "screen_recording_permission",
        (
            "Supporting automated evidence: --run-dmg-screen-smoke reached "
            f"packaged Bridge for {artifact_label}, but /screen/current failed "
            f"with {reason}; keep this check manual_required until Screen "
            "Recording is granted and the probe passes."
        ),
    )


def _manual_release_candidate_checks_with_supporting_evidence(
    raw_checks: Sequence[Any],
    raw_payload: dict[str, Any],
) -> list[Any]:
    checks = [dict(check) if isinstance(check, dict) else check for check in raw_checks]
    _append_electron_ui_smoke_supporting_evidence(
        checks,
        raw_payload.get("electron_ui_smoke"),
    )
    _append_dmg_screen_probe_failure_supporting_evidence(
        checks,
        raw_payload.get("dmg_screen_probe"),
    )
    return checks


def _manual_release_candidate_checks_from_markdown(raw_text: str) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    current_field = ""
    field_names = {
        "Evidence": "evidence",
        "Notes": "notes",
        "Evidence source": "evidence_source",
    }
    for line in raw_text.splitlines():
        match = MANUAL_RELEASE_CANDIDATE_CHECK_MARKDOWN_RE.match(line)
        if match:
            checked = match.group("checked").strip().lower() == "x"
            status = str(match.group("status") or "").strip()
            current = {
                "id": match.group("id").strip(),
                "status": status or ("passed" if checked else "manual_required"),
            }
            checks.append(current)
            current_field = ""
            continue

        if current is None:
            continue
        if line.startswith("  - "):
            raw_field = line[4:]
            field_label, separator, value = raw_field.partition(":")
            field_name = field_names.get(field_label.strip())
            if separator and field_name:
                current[field_name] = value.strip()
                current_field = field_name
            else:
                current_field = ""
            continue
        if current_field in {"evidence", "notes"} and line.startswith("    "):
            continuation = line.strip()
            if continuation:
                previous = current.get(current_field, "")
                current[current_field] = (
                    f"{previous}\n{continuation}" if previous else continuation
                )
    return checks


def _manual_release_candidate_check_status(
    checks: Sequence[dict[str, str]],
    findings: Sequence[Finding],
) -> str:
    if findings or any(check.get("status") == "failed" for check in checks):
        return "failed"
    if all(check.get("status") in {"passed", "not_applicable"} for check in checks):
        return "passed"
    return "manual_required"


def _manual_release_candidate_check_summary(
    checks: Sequence[dict[str, str]],
) -> dict[str, object]:
    status_counts = {
        status: sum(1 for check in checks if check.get("status") == status)
        for status in MANUAL_RELEASE_CANDIDATE_CHECK_STATUS_VALUES
    }
    remaining_check_ids = [
        check["id"] for check in checks if check.get("status") == "manual_required"
    ]
    remaining_next_actions = [
        {
            "id": check["id"],
            "next_action": check.get("next_action", ""),
        }
        for check in checks
        if check.get("status") == "manual_required"
    ]
    remaining_notes = [
        {
            "id": check["id"],
            "notes": str(check.get("notes", "")).strip(),
        }
        for check in checks
        if check.get("status") == "manual_required"
        and str(check.get("notes", "")).strip()
    ]
    remaining_commands = [
        {
            "id": check["id"],
            "command": MANUAL_RELEASE_CANDIDATE_CHECK_AUTOMATION_COMMANDS[check["id"]],
        }
        for check in checks
        if check.get("status") == "manual_required"
        and check["id"] in MANUAL_RELEASE_CANDIDATE_CHECK_AUTOMATION_COMMANDS
    ]
    failed_check_ids = [check["id"] for check in checks if check.get("status") == "failed"]
    automated_evidence_check_ids = [
        check["id"]
        for check in checks
        if check.get("evidence_source") == "automated_rc_gate"
    ]
    return {
        "total": len(checks),
        "status_counts": status_counts,
        "remaining_count": len(remaining_check_ids),
        "remaining_check_ids": remaining_check_ids,
        "remaining_next_actions": remaining_next_actions,
        "remaining_notes": remaining_notes,
        "remaining_commands": remaining_commands,
        "failed_check_ids": failed_check_ids,
        "automated_evidence_check_ids": automated_evidence_check_ids,
    }


def _print_manual_release_candidate_check_summary(summary: dict[str, Any]) -> None:
    remaining_ids = summary.get("remaining_check_ids")
    remaining_count = summary.get("remaining_count")
    total = summary.get("total")
    if isinstance(total, int) and isinstance(remaining_count, int):
        completed_count = max(0, total - remaining_count)
        print(
            "manual release-candidate check progress: "
            f"{completed_count}/{total} complete, {remaining_count} remaining"
        )
    if isinstance(remaining_ids, list) and remaining_ids:
        print(
            "manual release-candidate check summary: "
            f"{remaining_count} remaining ({', '.join(str(check_id) for check_id in remaining_ids)})"
        )
        remaining_next_actions = summary.get("remaining_next_actions")
        if isinstance(remaining_next_actions, list):
            print("manual release-candidate next actions:")
            for item in remaining_next_actions:
                if not isinstance(item, dict):
                    continue
                check_id = str(item.get("id", "")).strip()
                next_action = str(item.get("next_action", "")).strip()
                if check_id and next_action:
                    print(f"- [{check_id}] {next_action}")
        remaining_commands = summary.get("remaining_commands")
        if isinstance(remaining_commands, list) and remaining_commands:
            print("manual release-candidate recommended commands:")
            for item in remaining_commands:
                if not isinstance(item, dict):
                    continue
                check_id = str(item.get("id", "")).strip()
                command = str(item.get("command", "")).strip()
                if check_id and command:
                    print(f"- [{check_id}] {command}")
        remaining_notes = summary.get("remaining_notes")
        if isinstance(remaining_notes, list) and remaining_notes:
            print("manual release-candidate supporting notes:")
            for item in remaining_notes:
                if not isinstance(item, dict):
                    continue
                check_id = str(item.get("id", "")).strip()
                notes = str(item.get("notes", "")).strip()
                if check_id and notes:
                    print(f"- [{check_id}] {notes}")
    else:
        print("manual release-candidate check summary: complete")


def _print_manual_release_candidate_checks_for_write_action(
    root: Path,
    source_path: ManualChecksJsonInput | Path | None,
    *,
    mark_provider_smoke_not_applicable_if_missing: bool = False,
) -> None:
    source_is_markdown = isinstance(source_path, Path) and source_path.suffix.lower() in {
        ".md",
        ".markdown",
    }
    checks, findings = _load_manual_release_candidate_checks(
        root,
        None if source_is_markdown else source_path,
        source_path if source_is_markdown else None,
    )
    if findings:
        return
    if mark_provider_smoke_not_applicable_if_missing:
        _mark_provider_smoke_not_applicable_if_missing(checks)
    _print_manual_release_candidate_check_summary(
        _manual_release_candidate_check_summary(checks)
    )


def print_manual_release_candidate_checks_status(
    root: Path,
    source_path: ManualChecksJsonInput | Path | None,
    *,
    mark_provider_smoke_not_applicable_if_missing: bool = False,
) -> bool:
    source_is_markdown = isinstance(source_path, Path) and source_path.suffix.lower() in {
        ".md",
        ".markdown",
    }
    checks, findings = _load_manual_release_candidate_checks(
        root,
        None if source_is_markdown else source_path,
        source_path if source_is_markdown else None,
    )
    if findings:
        _print_findings("manual release-candidate checks status", findings)
        return False
    if mark_provider_smoke_not_applicable_if_missing:
        _mark_provider_smoke_not_applicable_if_missing(checks)
    print("manual release-candidate checks status:")
    _print_manual_release_candidate_check_summary(
        _manual_release_candidate_check_summary(checks)
    )
    return True


def _manual_release_candidate_checks_by_id(
    checks: Sequence[dict[str, str]],
) -> dict[str, dict[str, str]]:
    return {check["id"]: check for check in checks}


def _auto_apply_manual_release_candidate_check_evidence(
    checks: Sequence[dict[str, str]],
    check_id: str,
    evidence: str,
) -> bool:
    check = _manual_release_candidate_checks_by_id(checks).get(check_id)
    if check is None or check.get("status") != "manual_required":
        return False
    check["status"] = "passed"
    check["evidence"] = evidence
    check["evidence_source"] = "automated_rc_gate"
    return True


def _auto_apply_packaged_bridge_ready_evidence(
    checks: Sequence[dict[str, str]],
    gate_report: dict[str, Any],
    *,
    flag: str,
    detail: str,
) -> None:
    raw_paths = gate_report.get("bridge_ready_dmg_paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        return
    artifact_label = ", ".join(str(path) for path in raw_paths if path)
    if not artifact_label:
        artifact_label = "selected DMG artifacts"
    _auto_apply_manual_release_candidate_check_evidence(
        checks,
        "packaged_bridge_isolation",
        (
            f"Automated {flag} reached packaged /status for {artifact_label}: "
            "the packaged app was launched from a mounted DMG with temporary "
            "HOME/OHA_YACHIYO_HOME and loopback OHA_YACHIYO_BRIDGE_URL, and "
            f"/status returned service=oha-yachiyo before {detail}."
        ),
    )


def _refresh_manual_release_candidate_check_report(
    report: dict[str, Any],
    checks: Sequence[dict[str, str]],
    findings: Sequence[Finding],
) -> str:
    status = _manual_release_candidate_check_status(checks, findings)
    report["manual_release_candidate_check_status"] = status
    report["manual_release_candidate_check_statuses"] = list(checks)
    report["manual_release_candidate_check_summary"] = (
        _manual_release_candidate_check_summary(checks)
    )
    report["manual_release_candidate_check_findings"] = _finding_report(findings)
    return status


def _auto_apply_release_candidate_check_evidence(
    report: dict[str, Any],
    checks: Sequence[dict[str, str]],
) -> None:
    dmg_app_smoke = report.get("dmg_app_smoke")
    if isinstance(dmg_app_smoke, dict) and dmg_app_smoke.get("status") == "passed":
        dmg_paths = dmg_app_smoke.get("dmg_paths")
        if isinstance(dmg_paths, list) and dmg_paths:
            artifact_label = ", ".join(str(path) for path in dmg_paths)
        else:
            artifact_label = "selected DMG artifacts"
        _auto_apply_manual_release_candidate_check_evidence(
            checks,
            "packaged_bridge_isolation",
            (
                "Automated --run-dmg-app-smoke passed for "
                f"{artifact_label}: the packaged app was launched from a mounted DMG "
                "with temporary HOME/OHA_YACHIYO_HOME and loopback OHA_YACHIYO_BRIDGE_URL, "
                "and /status returned service=oha-yachiyo."
            ),
        )

    dmg_screen_probe = report.get("dmg_screen_probe")
    if isinstance(dmg_screen_probe, dict) and dmg_screen_probe.get("status") == "passed":
        dmg_paths = dmg_screen_probe.get("dmg_paths")
        if isinstance(dmg_paths, list) and dmg_paths:
            artifact_label = ", ".join(str(path) for path in dmg_paths)
        else:
            artifact_label = "selected DMG artifacts"
        screens = dmg_screen_probe.get("screens")
        screen_labels: list[str] = []
        if isinstance(screens, list):
            for item in screens:
                if isinstance(item, dict):
                    width = item.get("width")
                    height = item.get("height")
                    image_format = item.get("format")
                    dmg_path = item.get("dmg_path")
                    if width is not None and height is not None:
                        screen_labels.append(
                            f"{dmg_path or 'DMG'} /screen/current {width}x{height} {image_format or ''}".strip()
                        )
        screen_summary = "; ".join(screen_labels) if screen_labels else "/screen/current returned screenshot metadata"
        _auto_apply_manual_release_candidate_check_evidence(
            checks,
            "packaged_bridge_isolation",
            (
                "Automated --run-dmg-screen-smoke passed for "
                f"{artifact_label}: the packaged app was launched from a mounted DMG "
                "with temporary HOME/OHA_YACHIYO_HOME and loopback OHA_YACHIYO_BRIDGE_URL, "
                "and /status returned service=oha-yachiyo before the screen probe."
            ),
        )
        _auto_apply_manual_release_candidate_check_evidence(
            checks,
            "screen_recording_permission",
            (
                "Automated --run-dmg-screen-smoke passed for "
                f"{artifact_label}: {screen_summary}. "
                "Screenshot image bytes were not archived in the RC report."
            ),
        )
    elif isinstance(dmg_screen_probe, dict):
        _auto_apply_packaged_bridge_ready_evidence(
            checks,
            dmg_screen_probe,
            flag="--run-dmg-screen-smoke",
            detail="the screen probe failed",
        )
        _append_dmg_screen_probe_failure_supporting_evidence(
            checks,
            dmg_screen_probe,
        )

    dmg_ui_sampling_smoke = report.get("dmg_ui_sampling_smoke")
    if (
        isinstance(dmg_ui_sampling_smoke, dict)
        and dmg_ui_sampling_smoke.get("status") == "passed"
    ):
        dmg_paths = dmg_ui_sampling_smoke.get("dmg_paths")
        if isinstance(dmg_paths, list) and dmg_paths:
            artifact_label = ", ".join(str(path) for path in dmg_paths)
        else:
            artifact_label = "selected DMG artifacts"
        samples = dmg_ui_sampling_smoke.get("samples")
        route_labels: list[str] = []
        if isinstance(samples, list):
            for sample in samples:
                if not isinstance(sample, dict):
                    continue
                sample_routes = sample.get("routes")
                if isinstance(sample_routes, list):
                    route_labels.extend(str(route) for route in sample_routes if route)
        route_summary = (
            ", ".join(dict.fromkeys(route_labels))
            if route_labels
            else "packaged Chat, Agent Studio, Workflow, Activity, Diagnostics, TTS, and Live2D routes"
        )
        _auto_apply_manual_release_candidate_check_evidence(
            checks,
            "packaged_bridge_isolation",
            (
                "Automated --run-dmg-ui-sampling-smoke passed for "
                f"{artifact_label}: the packaged app was launched from a mounted DMG "
                "with temporary HOME/OHA_YACHIYO_HOME and loopback OHA_YACHIYO_BRIDGE_URL, "
                "and /status returned service=oha-yachiyo before packaged renderer sampling."
            ),
        )
        _auto_apply_manual_release_candidate_check_evidence(
            checks,
            "packaged_ui_sampling",
            (
                "Automated --run-dmg-ui-sampling-smoke passed for "
                f"{artifact_label}: Chromium DevTools sampled visible selectors on {route_summary} "
                "inside the packaged renderer."
            ),
        )
    elif isinstance(dmg_ui_sampling_smoke, dict):
        _auto_apply_packaged_bridge_ready_evidence(
            checks,
            dmg_ui_sampling_smoke,
            flag="--run-dmg-ui-sampling-smoke",
            detail="packaged renderer sampling failed",
        )

    dmg_chat_native_file_smoke = report.get("dmg_chat_native_file_smoke")
    if (
        isinstance(dmg_chat_native_file_smoke, dict)
        and dmg_chat_native_file_smoke.get("status") == "passed"
    ):
        dmg_paths = dmg_chat_native_file_smoke.get("dmg_paths")
        artifact_label = (
            ", ".join(str(path) for path in dmg_paths)
            if isinstance(dmg_paths, list) and dmg_paths
            else "selected DMG artifacts"
        )
        uploads = dmg_chat_native_file_smoke.get("uploads")
        upload_labels: list[str] = []
        if isinstance(uploads, list):
            for upload in uploads:
                if isinstance(upload, dict):
                    selected_file_name = str(upload.get("selected_file_name") or "").strip()
                    run_id = str(upload.get("run_id") or "").strip()
                    if selected_file_name and run_id:
                        upload_labels.append(f"{selected_file_name} -> Run Detail {run_id}")
                    elif selected_file_name:
                        upload_labels.append(selected_file_name)
        upload_summary = ", ".join(upload_labels) if upload_labels else "packaged native file upload flow"
        _auto_apply_manual_release_candidate_check_evidence(
            checks,
            "chat_native_file_upload",
            (
                f"Automated --run-dmg-chat-native-file-smoke passed for {artifact_label}: "
                "the packaged Chat attach button invoked the desktop chooseChatImages IPC "
                "against a smoke-selected local image, rendered the preview, sent the "
                "message, opened the image viewer, and verified Run Detail handoff "
                f"({upload_summary})."
            ),
        )

    provider_smoke = report.get("provider_smoke")
    if isinstance(provider_smoke, dict) and provider_smoke.get("status") == "passed":
        raw_checks = provider_smoke.get("checks")
        check_labels: list[str] = []
        if isinstance(raw_checks, list):
            for item in raw_checks:
                if isinstance(item, dict):
                    label = item.get("label")
                    exit_code = item.get("exit_code")
                    if label is not None:
                        check_labels.append(f"{label} exit_code={exit_code}")
        check_summary = ", ".join(check_labels) if check_labels else "all provider smoke checks passed"
        _auto_apply_manual_release_candidate_check_evidence(
            checks,
            "real_provider_smoke",
            (
                "Automated --run-provider-smoke passed in this RC gate: "
                f"{check_summary}. The archived provider_smoke report section is the release evidence."
            ),
        )

    _append_electron_ui_smoke_supporting_evidence(
        checks,
        report.get("electron_ui_smoke"),
    )


def existing_artifact_paths(root: Path) -> tuple[Path, ...]:
    return tuple(path for path in DEFAULT_ARTIFACT_PATHS if (root / path).exists())


def _print_findings(title: str, findings: Sequence[Finding]) -> None:
    if not findings:
        print(f"{title}: passed")
        return
    print(f"{title}: failed")
    for finding in findings:
        print(f"- {finding.format()}")


def _finding_report(findings: Sequence[Finding]) -> list[dict[str, str]]:
    return [{"path": str(finding.path), "message": finding.message} for finding in findings]


def _source_revision_final_signoff_findings(
    root: Path,
    report: dict[str, Any],
    *,
    require_manual_checks_complete: bool,
) -> list[Finding]:
    if not require_manual_checks_complete:
        return []
    source_revision = report.get("source_revision")
    if (
        not isinstance(source_revision, dict)
        or source_revision.get("available") is not True
        or source_revision.get("dirty") is not True
    ):
        return []
    short_commit = str(source_revision.get("short_commit") or "").strip()
    suffix = f" at {short_commit}" if short_commit else ""
    return [
        Finding(
            root,
            (
                "final signoff requires a clean source revision"
                f"{suffix}; commit or discard uncommitted changes and rebuild "
                "release artifacts before final signoff"
            ),
        )
    ]


def _manual_evidence_source_revision_final_signoff_findings(
    root: Path,
    report: dict[str, Any],
    *,
    require_manual_checks_complete: bool,
) -> list[Finding]:
    if not require_manual_checks_complete:
        return []
    source_revision = report.get("source_revision")
    if not isinstance(source_revision, dict) or source_revision.get("available") is not True:
        return []
    current_commit = str(source_revision.get("commit") or "").strip()
    if not current_commit:
        return []
    current_label = str(source_revision.get("short_commit") or current_commit[:7]).strip()
    raw_revisions = report.get("manual_release_candidate_check_source_revisions")
    if not isinstance(raw_revisions, list):
        return []

    findings: list[Finding] = []
    for revision in raw_revisions:
        if not isinstance(revision, dict) or revision.get("available") is not True:
            continue
        source = Path(str(revision.get("source") or "manual release-candidate evidence"))
        evidence_commit = str(revision.get("commit") or "").strip()
        evidence_label = str(
            revision.get("short_commit") or evidence_commit[:7] or "unavailable"
        ).strip()
        if revision.get("dirty") is True:
            findings.append(
                Finding(
                    source,
                    (
                        "final signoff requires manual release-candidate evidence "
                        f"from a clean source revision; {source}@{evidence_label} "
                        "was recorded with dirty source"
                    ),
                )
            )
            continue
        if evidence_commit and evidence_commit != current_commit:
            findings.append(
                Finding(
                    source,
                    (
                        "manual release-candidate evidence source revision "
                        f"{evidence_label} does not match current source_revision.commit "
                        f"{current_label}; rerun RC evidence or regenerate manual "
                        "checks from the current source before final signoff"
                    ),
                )
            )
    return findings


def _recorded_bridge_statuses(report: dict[str, Any]) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for section_name in DMG_BRIDGE_STATUS_REPORT_SECTIONS:
        section = report.get(section_name)
        if not isinstance(section, dict):
            continue
        raw_statuses = section.get("bridge_statuses")
        if not isinstance(raw_statuses, list):
            continue
        statuses.extend(status for status in raw_statuses if isinstance(status, dict))
    return statuses


def _recorded_packaged_build_metadata(report: dict[str, Any]) -> list[dict[str, Any]]:
    metadata_items: list[dict[str, Any]] = []
    for status in _recorded_bridge_statuses(report):
        metadata = status.get("build_metadata")
        if isinstance(metadata, dict):
            metadata_items.append(metadata)
    chat_native_file_smoke = report.get("dmg_chat_native_file_smoke")
    if isinstance(chat_native_file_smoke, dict):
        uploads = chat_native_file_smoke.get("uploads")
        if isinstance(uploads, list):
            for upload in uploads:
                if not isinstance(upload, dict):
                    continue
                metadata = upload.get("app_build_metadata")
                if isinstance(metadata, dict):
                    metadata_items.append(metadata)
    return metadata_items


def _source_revision_commit(report: dict[str, Any]) -> str:
    source_revision = report.get("source_revision")
    if not isinstance(source_revision, dict) or source_revision.get("available") is not True:
        return ""
    return str(source_revision.get("commit") or "").strip()


def _bridge_status_source_revision_findings(
    report: dict[str, Any],
) -> dict[str, list[Finding]]:
    source_commit = _source_revision_commit(report)
    if not source_commit:
        return {}
    source_revision = report["source_revision"]
    source_label = str(source_revision.get("short_commit") or source_commit[:7]).strip()

    findings: dict[str, list[Finding]] = {}
    for section_name in DMG_BRIDGE_STATUS_REPORT_SECTIONS:
        section = report.get(section_name)
        if not isinstance(section, dict):
            continue
        raw_statuses = section.get("bridge_statuses")
        if not isinstance(raw_statuses, list):
            continue
        for status in raw_statuses:
            if not isinstance(status, dict):
                continue
            dmg_path = Path(str(status.get("dmg_path") or section_name))
            build_metadata = status.get("build_metadata")
            build_commit = (
                str(build_metadata.get("commit") or "").strip()
                if isinstance(build_metadata, dict)
                else ""
            )
            if not build_commit:
                findings.setdefault(section_name, []).append(
                    Finding(
                        dmg_path,
                        (
                            f"{section_name} packaged Bridge /status must include "
                            f"build_metadata.commit to compare against source_revision "
                            f"{source_label}"
                        ),
                    )
                )
                continue
            if build_commit != source_commit:
                build_label = (
                    str(build_metadata.get("short_commit") or build_commit[:7]).strip()
                    if isinstance(build_metadata, dict)
                    else build_commit[:7]
                )
                findings.setdefault(section_name, []).append(
                    Finding(
                        dmg_path,
                        (
                            f"{section_name} packaged Bridge build_metadata.commit "
                            f"{build_label} does not match source_revision.commit "
                            f"{source_label}; rebuild the DMG from the current source "
                            "before final signoff"
                        ),
                    )
                )
    chat_native_file_smoke = report.get("dmg_chat_native_file_smoke")
    if isinstance(chat_native_file_smoke, dict):
        uploads = chat_native_file_smoke.get("uploads")
        if isinstance(uploads, list):
            for upload in uploads:
                if not isinstance(upload, dict):
                    continue
                dmg_path = Path(str(upload.get("dmg_path") or "dmg_chat_native_file_smoke"))
                build_metadata = upload.get("app_build_metadata")
                build_commit = (
                    str(build_metadata.get("commit") or "").strip()
                    if isinstance(build_metadata, dict)
                    else ""
                )
                if not build_commit:
                    findings.setdefault("dmg_chat_native_file_smoke", []).append(
                        Finding(
                            dmg_path,
                            (
                                "dmg_chat_native_file_smoke packaged Electron app "
                                "metadata must include app_build_metadata.commit to "
                                f"compare against source_revision {source_label}"
                            ),
                        )
                    )
                    continue
                if build_commit != source_commit:
                    build_label = (
                        str(build_metadata.get("short_commit") or build_commit[:7]).strip()
                        if isinstance(build_metadata, dict)
                        else build_commit[:7]
                    )
                    findings.setdefault("dmg_chat_native_file_smoke", []).append(
                        Finding(
                            dmg_path,
                            (
                                "dmg_chat_native_file_smoke packaged Electron app "
                                f"app_build_metadata.commit {build_label} does not "
                                f"match source_revision.commit {source_label}; rebuild "
                                "the DMG from the current source before final signoff"
                            ),
                        )
                    )
    return findings


def _apply_bridge_status_source_revision_findings(
    report: dict[str, Any],
) -> list[Finding]:
    findings_by_section = _bridge_status_source_revision_findings(report)
    all_findings: list[Finding] = []
    for section_name, section_findings in findings_by_section.items():
        section = report.get(section_name)
        if not isinstance(section, dict):
            continue
        existing_findings = section.get("findings")
        if not isinstance(existing_findings, list):
            existing_findings = []
        section["findings"] = [*existing_findings, *_finding_report(section_findings)]
        if section.get("status") != "skipped":
            section["status"] = "failed"
        if "bridge_ready_dmg_paths" in section:
            section["bridge_ready_dmg_paths"] = []
        all_findings.extend(section_findings)
    return all_findings


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_report_path(root: Path, report_json: Path) -> Path:
    root_path = root.resolve(strict=False)
    report_path = report_json if report_json.is_absolute() else root / report_json
    resolved = report_path.resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError:
        raise ValueError(
            f"release candidate report path must stay inside project root: {report_json}"
        )
    return resolved


def _resolve_project_file(root: Path, relative_or_absolute: Path, label: str) -> Path:
    root_path = root.resolve(strict=False)
    candidate = relative_or_absolute if relative_or_absolute.is_absolute() else root / relative_or_absolute
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError:
        raise ValueError(f"{label} path must stay inside project root: {relative_or_absolute}")
    return resolved


def write_manual_release_candidate_checks_template(root: Path, output_path: Path) -> Path:
    resolved = _resolve_project_file(
        root,
        output_path,
        "manual release-candidate checks template",
    )
    _write_report(resolved, _manual_release_candidate_check_template())
    return resolved


def write_manual_release_candidate_checks_draft(
    root: Path,
    output_path: Path,
    source_path: ManualChecksJsonInput = None,
    *,
    mark_provider_smoke_not_applicable_if_missing: bool = False,
) -> Path:
    checks, findings = _load_manual_release_candidate_checks(root, source_path)
    if findings:
        formatted = "; ".join(finding.format() for finding in findings)
        raise ValueError(f"manual release-candidate checks draft source is invalid: {formatted}")
    if mark_provider_smoke_not_applicable_if_missing:
        _mark_provider_smoke_not_applicable_if_missing(checks)
    resolved = _resolve_project_file(
        root,
        output_path,
        "manual release-candidate checks draft",
    )
    _write_report(
        resolved,
        _manual_release_candidate_check_draft(
            checks,
            source_path=source_path,
            source_revisions=_manual_check_source_revisions(root, source_path),
        ),
    )
    return resolved


def write_manual_release_candidate_checks_markdown(
    root: Path,
    output_path: Path,
    source_path: ManualChecksJsonInput = None,
    *,
    mark_provider_smoke_not_applicable_if_missing: bool = False,
) -> Path:
    source_is_markdown = isinstance(source_path, Path) and source_path.suffix.lower() in {
        ".md",
        ".markdown",
    }
    checks, findings = _load_manual_release_candidate_checks(
        root,
        None if source_is_markdown else source_path,
        source_path if source_is_markdown else None,
    )
    if findings:
        formatted = "; ".join(finding.format() for finding in findings)
        raise ValueError(f"manual release-candidate checks markdown source is invalid: {formatted}")
    if mark_provider_smoke_not_applicable_if_missing:
        _mark_provider_smoke_not_applicable_if_missing(checks)
    source_revisions = (
        _manual_check_markdown_source_revisions(root, source_path)
        if source_is_markdown and isinstance(source_path, Path)
        else _manual_check_source_revisions(root, source_path)
    )
    resolved = _resolve_project_file(
        root,
        output_path,
        "manual release-candidate checks markdown",
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        _manual_release_candidate_checks_markdown(
            checks,
            source_path=source_path,
            source_revisions=source_revisions,
            markdown_path=output_path,
        ),
        encoding="utf-8",
    )
    return resolved


def _validate_artifact_paths(root: Path, artifact_paths: Sequence[Path]) -> tuple[Path, ...]:
    root_path = root.resolve(strict=False)
    for artifact_path in artifact_paths:
        candidate = artifact_path if artifact_path.is_absolute() else root / artifact_path
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root_path)
        except ValueError:
            raise ValueError(
                f"release candidate artifact path must stay inside project root: {artifact_path}"
            )
    return tuple(artifact_paths)


def _load_manual_release_candidate_checks(
    root: Path,
    manual_checks_json: ManualChecksJsonInput,
    manual_checks_markdown: Path | None = None,
) -> tuple[list[dict[str, str]], list[Finding]]:
    checks = _manual_release_candidate_check_report()
    findings: list[Finding] = []
    json_paths = _manual_checks_json_paths(manual_checks_json)
    if json_paths and manual_checks_markdown is not None:
        findings.append(
            Finding(
                json_paths[0],
                "manual release-candidate checks must use either JSON or Markdown input, not both",
            )
        )
        return checks, findings
    if not json_paths and manual_checks_markdown is None:
        return checks, findings

    known = {check["id"]: check for check in checks}

    def apply_raw_checks(
        raw_checks: object,
        source_path: Path,
        *,
        preserve_existing_when_manual_required: bool = False,
    ) -> None:
        if not isinstance(raw_checks, list):
            findings.append(
                Finding(
                    source_path,
                    (
                        "manual release-candidate checks JSON must be a list, contain a checks list, "
                        "or be a previous RC report with manual_release_candidate_check_statuses"
                    ),
                )
            )
            return
        seen: set[str] = set()
        for index, raw_check in enumerate(raw_checks):
            if not isinstance(raw_check, dict):
                findings.append(
                    Finding(
                        source_path,
                        f"manual release-candidate check at index {index} must be an object",
                    )
                )
                continue
            check_id = str(raw_check.get("id", "")).strip()
            if check_id not in known:
                findings.append(
                    Finding(
                        source_path,
                        f"manual release-candidate check has unknown id: {check_id or '<missing>'}",
                    )
                )
                continue
            if check_id in seen:
                findings.append(
                    Finding(
                        source_path,
                        f"manual release-candidate check is duplicated: {check_id}",
                    )
                )
                continue
            seen.add(check_id)

            status = str(raw_check.get("status", "")).strip()
            if status not in MANUAL_RELEASE_CANDIDATE_CHECK_STATUS_VALUES:
                findings.append(
                    Finding(
                        source_path,
                        f"manual release-candidate check {check_id} has invalid status: {status or '<missing>'}",
                    )
                )
                continue
            evidence = str(raw_check.get("evidence", "")).strip()
            if status in {"passed", "failed", "not_applicable"} and not evidence:
                findings.append(
                    Finding(
                        source_path,
                        f"manual release-candidate check {check_id} requires evidence for status {status}",
                    )
                )
                continue

            target = known[check_id]
            notes = raw_check.get("notes")
            if (
                preserve_existing_when_manual_required
                and status == "manual_required"
                and target.get("status") != "manual_required"
            ):
                if notes is not None:
                    existing_notes = str(target.get("notes", "")).strip()
                    note_text = str(notes).strip()
                    if note_text and note_text not in existing_notes:
                        target["notes"] = (
                            f"{existing_notes}\n{note_text}" if existing_notes else note_text
                        )
                continue
            target["status"] = status
            if evidence:
                target["evidence"] = evidence
            if notes is not None:
                target["notes"] = str(notes)
            evidence_source = str(raw_check.get("evidence_source", "")).strip()
            if evidence_source in {"automated_rc_gate", "credentials_unavailable"}:
                target["evidence_source"] = evidence_source
            elif "evidence_source" in target and "evidence_source" in raw_check:
                target.pop("evidence_source", None)

    if manual_checks_markdown is not None:
        try:
            evidence_path = _resolve_project_file(
                root,
                manual_checks_markdown,
                "manual release-candidate checks markdown",
            )
            raw_checks = _manual_release_candidate_checks_from_markdown(
                evidence_path.read_text(encoding="utf-8")
            )
            if not raw_checks:
                findings.append(
                    Finding(
                        manual_checks_markdown,
                        "manual release-candidate checks Markdown must include checklist items",
                    )
                )
                return checks, findings
            apply_raw_checks(raw_checks, manual_checks_markdown)
        except (OSError, ValueError) as exc:
            findings.append(
                Finding(
                    manual_checks_markdown,
                    f"manual release-candidate checks could not be loaded: {exc}",
                )
            )
        return checks, findings

    for manual_checks_path in json_paths:
        try:
            evidence_path = _resolve_project_file(
                root,
                manual_checks_path,
                "manual release-candidate checks",
            )
            raw_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            standalone_electron_ui_smoke = _standalone_electron_ui_smoke_report(
                raw_payload
            )
            if standalone_electron_ui_smoke is not None:
                _append_electron_ui_smoke_supporting_evidence(
                    checks,
                    standalone_electron_ui_smoke,
                )
                continue
            preserve_existing_when_manual_required = (
                isinstance(raw_payload, dict)
                and "manual_release_candidate_check_statuses" in raw_payload
                and "checks" not in raw_payload
            )
            raw_checks = _manual_release_candidate_checks_from_payload(raw_payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append(
                Finding(
                    manual_checks_path,
                    f"manual release-candidate checks could not be loaded: {exc}",
                )
            )
            continue
        apply_raw_checks(
            raw_checks,
            manual_checks_path,
            preserve_existing_when_manual_required=preserve_existing_when_manual_required,
        )

    return checks, findings


def _absolute_artifact_path(root: Path, artifact_path: Path) -> Path:
    return artifact_path if artifact_path.is_absolute() else root / artifact_path


def _allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _terminate_process(process: subprocess.Popen[str], timeout_seconds: float = 5.0) -> None:
    if process.poll() is not None:
        return
    try:
        process_group_id = os.getpgid(process.pid)
    except (AttributeError, OSError):
        process_group_id = None
    if process_group_id is not None:
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        if process_group_id is not None:
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
        else:
            process.kill()
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            pass


def _read_process_output(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        return "", ""
    return stdout or "", stderr or ""


def _redacted_process_detail(stdout: str, stderr: str) -> str:
    detail = "\n".join(part.strip() for part in (stderr, stdout) if part and part.strip())
    return redact_api_error_text(detail.strip())


def _process_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _provider_smoke_missing_env() -> list[str]:
    return [name for name in PROVIDER_SMOKE_ENV_VARS if not os.getenv(name, "").strip()]


def verify_provider_smoke(root: Path) -> tuple[list[Finding], list[dict[str, object]]]:
    findings: list[Finding] = []
    results: list[dict[str, object]] = []
    missing_env = _provider_smoke_missing_env()
    if missing_env:
        findings.append(
            Finding(
                root,
                "real provider smoke requested but missing environment variables: "
                + ", ".join(missing_env),
            )
        )
        return findings, results

    script = root / PROVIDER_SMOKE_SCRIPT
    for label, args in PROVIDER_SMOKE_COMMANDS:
        command = [sys.executable, str(PROVIDER_SMOKE_SCRIPT), *args]
        try:
            result = subprocess.run(
                command,
                cwd=root,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            detail = redact_api_error_text(str(exc))
            findings.append(Finding(script, f"real provider {label} smoke could not start: {detail}"))
            results.append({"label": label, "exit_code": None})
            continue
        results.append({"label": label, "exit_code": result.returncode})
        if result.returncode != 0:
            detail = _redacted_process_detail(result.stdout, result.stderr)
            message = f"real provider {label} smoke failed with exit code {result.returncode}"
            if detail:
                message = f"{message}: {detail}"
            findings.append(Finding(script, message))
    return findings, results


def release_candidate_dmg_paths(root: Path, artifact_paths: Sequence[Path]) -> tuple[Path, ...]:
    dmg_paths: list[Path] = []
    seen: set[Path] = set()
    for artifact_path in artifact_paths:
        candidate = _absolute_artifact_path(root, artifact_path)
        if candidate.is_file() and candidate.suffix.lower() == ".dmg":
            resolved = candidate.resolve(strict=False)
            if resolved not in seen:
                dmg_paths.append(artifact_path)
                seen.add(resolved)
        elif candidate.is_dir():
            for dmg in sorted(candidate.rglob("*.dmg")):
                resolved = dmg.resolve(strict=False)
                if resolved in seen:
                    continue
                try:
                    dmg_paths.append(dmg.relative_to(root))
                except ValueError:
                    dmg_paths.append(dmg)
                seen.add(resolved)
    return tuple(dmg_paths)


def verify_dmg_mount_artifacts(root: Path, dmg_paths: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    if not dmg_paths:
        findings.append(Finding(root, "release candidate DMG mount check requested but no .dmg artifacts were found"))
        return findings
    if sys.platform != "darwin":
        findings.append(Finding(root, "release candidate DMG mount check requires macOS hdiutil"))
        return findings
    for dmg_path in dmg_paths:
        absolute_dmg = _absolute_artifact_path(root, dmg_path)
        mount_dir = Path(tempfile.mkdtemp(prefix="oha-yachiyo-rc-dmg-"))
        attached = False
        try:
            attach = subprocess.run(
                [
                    "hdiutil",
                    "attach",
                    str(absolute_dmg),
                    "-nobrowse",
                    "-readonly",
                    "-mountpoint",
                    str(mount_dir),
                    "-quiet",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if attach.returncode != 0:
                detail = redact_api_error_text((attach.stderr or attach.stdout or "").strip())
                message = "release candidate DMG could not be mounted"
                if detail:
                    message = f"{message}: {detail}"
                findings.append(Finding(dmg_path, message))
                continue
            attached = True
            app_path = mount_dir / PACKAGED_APP_NAME
            if not app_path.is_dir():
                findings.append(Finding(dmg_path, f"mounted release candidate DMG must contain {PACKAGED_APP_NAME}"))
                continue
            resources_path = app_path / "Contents" / "Resources"
            if not resources_path.is_dir():
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} must contain Contents/Resources"))
                continue
            findings.extend(
                verify_release_artifacts(
                    root=root,
                    paths=(resources_path,),
                    check_required_files=False,
                    check_release_security_guards=False,
                    allow_binary_targets=True,
                    check_packaged_app_bundle=True,
                )
            )
        finally:
            if attached:
                detach = subprocess.run(
                    ["hdiutil", "detach", str(mount_dir), "-quiet"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if detach.returncode != 0:
                    detail = redact_api_error_text((detach.stderr or detach.stdout or "").strip())
                    message = "release candidate DMG could not be detached"
                    if detail:
                        message = f"{message}: {detail}"
                    findings.append(Finding(dmg_path, message))
            shutil.rmtree(mount_dir, ignore_errors=True)
    return findings


def _read_json_url(url: str, *, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    return data if isinstance(data, dict) else {}


def _read_status_json(bridge_url: str) -> dict[str, Any]:
    return _read_json_url(f"{bridge_url}/status", timeout=1.0)


def _bridge_status_report(dmg_path: Path, status: dict[str, Any]) -> dict[str, object]:
    build_metadata = status.get("build_metadata")
    return {
        "dmg_path": str(dmg_path),
        "service": str(status.get("service") or ""),
        "version": str(status.get("version") or ""),
        "native_agent_ready": status.get("native_agent_ready")
        if isinstance(status.get("native_agent_ready"), bool)
        else None,
        "build_metadata": build_metadata if isinstance(build_metadata, dict) else {},
    }


def _read_screen_probe_metadata(bridge_url: str) -> dict[str, object]:
    data = _read_json_url(
        f"{bridge_url}/screen/current",
        timeout=DMG_SCREEN_PROBE_REQUEST_TIMEOUT_SECONDS,
    )
    width = data.get("width")
    height = data.get("height")
    if not isinstance(width, int) or width <= 0:
        raise ValueError(f"unexpected /screen/current width={width!r}")
    if not isinstance(height, int) or height <= 0:
        raise ValueError(f"unexpected /screen/current height={height!r}")
    image_format = str(data.get("format") or "").strip()
    if image_format.lower() != "png":
        raise ValueError(f"unexpected /screen/current format={image_format!r}")
    metadata: dict[str, object] = {
        "width": width,
        "height": height,
        "format": image_format,
    }
    captured_at = str(data.get("captured_at") or "").strip()
    if captured_at:
        metadata["captured_at"] = captured_at
    return metadata


def _redacted_url_error_detail(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return redact_api_error_text((body or str(exc)).strip())
    return redact_api_error_text(str(exc))


def _wait_for_dmg_app_status(
    process: subprocess.Popen[str],
    *,
    bridge_url: str,
    dmg_path: Path,
    timeout_seconds: float,
) -> tuple[Finding | None, dict[str, Any] | None]:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            stdout, stderr = _read_process_output(process)
            detail = _redacted_process_detail(stdout, stderr)
            message = f"release candidate app exited before /status was ready: exit_code={exit_code}"
            if detail:
                message = f"{message}: {detail}"
            return Finding(dmg_path, message), None
        try:
            status = _read_status_json(bridge_url)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = _redacted_url_error_detail(exc)
            time.sleep(0.5)
            continue
        if status.get("service") == "oha-yachiyo":
            return None, status
        last_error = redact_api_error_text(f"unexpected /status service={status.get('service')!r}")
        time.sleep(0.5)
    message = f"release candidate app did not expose /status within {timeout_seconds:.0f}s"
    if last_error:
        message = f"{message}: {last_error}"
    return Finding(dmg_path, message), None


def verify_dmg_app_startup(
    root: Path,
    dmg_paths: Sequence[Path],
    *,
    timeout_seconds: float = DMG_APP_SMOKE_TIMEOUT_SECONDS,
) -> tuple[list[Finding], list[dict[str, object]]]:
    findings: list[Finding] = []
    bridge_statuses: list[dict[str, object]] = []
    if not dmg_paths:
        findings.append(Finding(root, "release candidate DMG app startup smoke requested but no .dmg artifacts were found"))
        return findings, bridge_statuses
    if sys.platform != "darwin":
        findings.append(Finding(root, "release candidate DMG app startup smoke requires macOS"))
        return findings, bridge_statuses
    for dmg_path in dmg_paths:
        absolute_dmg = _absolute_artifact_path(root, dmg_path)
        mount_dir = Path(tempfile.mkdtemp(prefix="oha-yachiyo-rc-app-"))
        attached = False
        process: subprocess.Popen[str] | None = None
        try:
            attach = subprocess.run(
                [
                    "hdiutil",
                    "attach",
                    str(absolute_dmg),
                    "-nobrowse",
                    "-readonly",
                    "-mountpoint",
                    str(mount_dir),
                    "-quiet",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if attach.returncode != 0:
                detail = redact_api_error_text((attach.stderr or attach.stdout or "").strip())
                message = "release candidate DMG could not be mounted for app startup smoke"
                if detail:
                    message = f"{message}: {detail}"
                findings.append(Finding(dmg_path, message))
                continue
            attached = True
            app_path = mount_dir / PACKAGED_APP_NAME
            executable_path = app_path / "Contents" / "MacOS" / PACKAGED_APP_EXECUTABLE_NAME
            if not executable_path.is_file():
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} must contain executable {PACKAGED_APP_EXECUTABLE_NAME}"))
                continue
            if not os.access(executable_path, os.X_OK):
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} executable is not executable"))
                continue
            bridge_url = f"http://127.0.0.1:{_allocate_loopback_port()}"
            with tempfile.TemporaryDirectory(prefix="oha-yachiyo-rc-home-") as home_dir:
                env = {
                    **os.environ,
                    "HOME": home_dir,
                    "OHA_YACHIYO_HOME": str(Path(home_dir) / ".oha-yachiyo"),
                    "OHA_YACHIYO_BRIDGE_URL": bridge_url,
                }
                process = subprocess.Popen(
                    [str(executable_path)],
                    cwd=str(app_path),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                status_finding, status_payload = _wait_for_dmg_app_status(
                    process,
                    bridge_url=bridge_url,
                    dmg_path=dmg_path,
                    timeout_seconds=timeout_seconds,
                )
                if status_finding is not None:
                    findings.append(status_finding)
                    continue
                if status_payload is not None:
                    bridge_statuses.append(_bridge_status_report(dmg_path, status_payload))
        finally:
            if process is not None:
                _terminate_process(process)
            if attached:
                detach = subprocess.run(
                    ["hdiutil", "detach", str(mount_dir), "-quiet"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if detach.returncode != 0:
                    detail = redact_api_error_text((detach.stderr or detach.stdout or "").strip())
                    message = "release candidate DMG could not be detached after app startup smoke"
                    if detail:
                        message = f"{message}: {detail}"
                    findings.append(Finding(dmg_path, message))
            shutil.rmtree(mount_dir, ignore_errors=True)
    return findings, bridge_statuses


def verify_dmg_screen_recording_probe(
    root: Path,
    dmg_paths: Sequence[Path],
    *,
    timeout_seconds: float = DMG_APP_SMOKE_TIMEOUT_SECONDS,
) -> tuple[list[Finding], list[dict[str, object]], list[str], list[dict[str, object]]]:
    findings: list[Finding] = []
    screens: list[dict[str, object]] = []
    bridge_ready_dmg_paths: list[str] = []
    bridge_statuses: list[dict[str, object]] = []
    if not dmg_paths:
        findings.append(Finding(root, "release candidate DMG screen probe requested but no .dmg artifacts were found"))
        return findings, screens, bridge_ready_dmg_paths, bridge_statuses
    if sys.platform != "darwin":
        findings.append(Finding(root, "release candidate DMG screen probe requires macOS"))
        return findings, screens, bridge_ready_dmg_paths, bridge_statuses
    for dmg_path in dmg_paths:
        absolute_dmg = _absolute_artifact_path(root, dmg_path)
        mount_dir = Path(tempfile.mkdtemp(prefix="oha-yachiyo-rc-screen-"))
        attached = False
        process: subprocess.Popen[str] | None = None
        try:
            attach = subprocess.run(
                [
                    "hdiutil",
                    "attach",
                    str(absolute_dmg),
                    "-nobrowse",
                    "-readonly",
                    "-mountpoint",
                    str(mount_dir),
                    "-quiet",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if attach.returncode != 0:
                detail = redact_api_error_text((attach.stderr or attach.stdout or "").strip())
                message = "release candidate DMG could not be mounted for screen probe"
                if detail:
                    message = f"{message}: {detail}"
                findings.append(Finding(dmg_path, message))
                continue
            attached = True
            app_path = mount_dir / PACKAGED_APP_NAME
            executable_path = app_path / "Contents" / "MacOS" / PACKAGED_APP_EXECUTABLE_NAME
            if not executable_path.is_file():
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} must contain executable {PACKAGED_APP_EXECUTABLE_NAME}"))
                continue
            if not os.access(executable_path, os.X_OK):
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} executable is not executable"))
                continue
            bridge_url = f"http://127.0.0.1:{_allocate_loopback_port()}"
            with tempfile.TemporaryDirectory(prefix="oha-yachiyo-rc-home-") as home_dir:
                env = {
                    **os.environ,
                    "HOME": home_dir,
                    "OHA_YACHIYO_HOME": str(Path(home_dir) / ".oha-yachiyo"),
                    "OHA_YACHIYO_BRIDGE_URL": bridge_url,
                }
                process = subprocess.Popen(
                    [str(executable_path)],
                    cwd=str(app_path),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                status_finding, status_payload = _wait_for_dmg_app_status(
                    process,
                    bridge_url=bridge_url,
                    dmg_path=dmg_path,
                    timeout_seconds=timeout_seconds,
                )
                if status_finding is not None:
                    findings.append(status_finding)
                    continue
                bridge_ready_dmg_paths.append(str(dmg_path))
                if status_payload is not None:
                    bridge_statuses.append(_bridge_status_report(dmg_path, status_payload))
                try:
                    metadata = _read_screen_probe_metadata(bridge_url)
                except (
                    OSError,
                    ValueError,
                    urllib.error.URLError,
                    json.JSONDecodeError,
                ) as exc:
                    findings.append(
                        Finding(
                            dmg_path,
                            "release candidate packaged /screen/current probe failed: "
                            + _redacted_url_error_detail(exc),
                        )
                    )
                    continue
                screens.append({"dmg_path": str(dmg_path), **metadata})
        finally:
            if process is not None:
                _terminate_process(process)
            if attached:
                detach = subprocess.run(
                    ["hdiutil", "detach", str(mount_dir), "-quiet"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if detach.returncode != 0:
                    detail = redact_api_error_text((detach.stderr or detach.stdout or "").strip())
                    message = "release candidate DMG could not be detached after screen probe"
                    if detail:
                        message = f"{message}: {detail}"
                    findings.append(Finding(dmg_path, message))
            shutil.rmtree(mount_dir, ignore_errors=True)
    return findings, screens, bridge_ready_dmg_paths, bridge_statuses


def _read_packaged_ui_sampling_report(report_path: Path) -> dict[str, object]:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def verify_dmg_ui_sampling_smoke(
    root: Path,
    dmg_paths: Sequence[Path],
    *,
    timeout_seconds: float = DMG_UI_SAMPLING_SMOKE_TIMEOUT_SECONDS,
) -> tuple[list[Finding], list[dict[str, object]], list[str], list[dict[str, object]]]:
    findings: list[Finding] = []
    samples: list[dict[str, object]] = []
    bridge_ready_dmg_paths: list[str] = []
    bridge_statuses: list[dict[str, object]] = []
    if not dmg_paths:
        findings.append(Finding(root, "release candidate DMG UI sampling smoke requested but no .dmg artifacts were found"))
        return findings, samples, bridge_ready_dmg_paths, bridge_statuses
    if sys.platform != "darwin":
        findings.append(Finding(root, "release candidate DMG UI sampling smoke requires macOS"))
        return findings, samples, bridge_ready_dmg_paths, bridge_statuses

    script = root / DMG_UI_SAMPLING_SMOKE_SCRIPT
    if not script.is_file():
        findings.append(Finding(script, "packaged UI sampling smoke script not found"))
        return findings, samples, bridge_ready_dmg_paths, bridge_statuses

    for dmg_path in dmg_paths:
        absolute_dmg = _absolute_artifact_path(root, dmg_path)
        mount_dir = Path(tempfile.mkdtemp(prefix="oha-yachiyo-rc-ui-"))
        attached = False
        process: subprocess.Popen[str] | None = None
        try:
            attach = subprocess.run(
                [
                    "hdiutil",
                    "attach",
                    str(absolute_dmg),
                    "-nobrowse",
                    "-readonly",
                    "-mountpoint",
                    str(mount_dir),
                    "-quiet",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if attach.returncode != 0:
                detail = redact_api_error_text((attach.stderr or attach.stdout or "").strip())
                message = "release candidate DMG could not be mounted for UI sampling smoke"
                if detail:
                    message = f"{message}: {detail}"
                findings.append(Finding(dmg_path, message))
                continue
            attached = True
            app_path = mount_dir / PACKAGED_APP_NAME
            executable_path = app_path / "Contents" / "MacOS" / PACKAGED_APP_EXECUTABLE_NAME
            if not executable_path.is_file():
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} must contain executable {PACKAGED_APP_EXECUTABLE_NAME}"))
                continue
            if not os.access(executable_path, os.X_OK):
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} executable is not executable"))
                continue
            bridge_url = f"http://127.0.0.1:{_allocate_loopback_port()}"
            debug_port = _allocate_loopback_port()
            with tempfile.TemporaryDirectory(prefix="oha-yachiyo-rc-home-") as home_dir:
                env = {
                    **os.environ,
                    "HOME": home_dir,
                    "OHA_YACHIYO_HOME": str(Path(home_dir) / ".oha-yachiyo"),
                    "OHA_YACHIYO_BRIDGE_URL": bridge_url,
                }
                process = subprocess.Popen(
                    [
                        str(executable_path),
                        f"--remote-debugging-port={debug_port}",
                        "--remote-allow-origins=*",
                    ],
                    cwd=str(app_path),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                status_finding, status_payload = _wait_for_dmg_app_status(
                    process,
                    bridge_url=bridge_url,
                    dmg_path=dmg_path,
                    timeout_seconds=timeout_seconds,
                )
                if status_finding is not None:
                    findings.append(status_finding)
                    continue
                bridge_ready_dmg_paths.append(str(dmg_path))
                if status_payload is not None:
                    bridge_statuses.append(_bridge_status_report(dmg_path, status_payload))

                sample_report_path = Path(home_dir) / "packaged-ui-sampling.json"
                command = [
                    "node",
                    str(DMG_UI_SAMPLING_SMOKE_SCRIPT),
                    "--debug-port",
                    str(debug_port),
                    "--timeout-ms",
                    str(int(timeout_seconds * 1000)),
                    "--report-json",
                    str(sample_report_path),
                ]
                try:
                    result = subprocess.run(
                        command,
                        cwd=root,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=timeout_seconds + 10.0,
                    )
                except subprocess.TimeoutExpired as exc:
                    detail = _redacted_process_detail(
                        _process_output_text(exc.stdout),
                        _process_output_text(exc.stderr),
                    )
                    message = f"release candidate packaged UI sampling smoke timed out after {timeout_seconds:.0f}s"
                    if detail:
                        message = f"{message}: {detail}"
                    findings.append(Finding(dmg_path, message))
                    continue
                except OSError as exc:
                    detail = redact_api_error_text(str(exc))
                    findings.append(Finding(dmg_path, f"release candidate packaged UI sampling smoke could not start: {detail}"))
                    continue
                if result.returncode != 0:
                    detail = _redacted_process_detail(result.stdout, result.stderr)
                    message = f"release candidate packaged UI sampling smoke failed with exit code {result.returncode}"
                    if detail:
                        message = f"{message}: {detail}"
                    findings.append(Finding(dmg_path, message))
                    continue
                try:
                    sample_report = _read_packaged_ui_sampling_report(sample_report_path)
                except (OSError, json.JSONDecodeError) as exc:
                    findings.append(Finding(dmg_path, f"release candidate packaged UI sampling report could not be read: {exc}"))
                    continue
                if sample_report.get("ok") is not True:
                    findings.append(Finding(dmg_path, "release candidate packaged UI sampling report did not pass"))
                    continue
                raw_samples = sample_report.get("samples")
                route_labels: list[str] = []
                if isinstance(raw_samples, list):
                    for sample in raw_samples:
                        if isinstance(sample, dict) and sample.get("route"):
                            route_labels.append(str(sample["route"]))
                samples.append(
                    {
                        "dmg_path": str(dmg_path),
                        "sample_count": sample_report.get("sample_count", len(route_labels)),
                        "routes": route_labels,
                    }
                )
        finally:
            if process is not None:
                _terminate_process(process)
            if attached:
                detach = subprocess.run(
                    ["hdiutil", "detach", str(mount_dir), "-quiet"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if detach.returncode != 0:
                    detail = redact_api_error_text((detach.stderr or detach.stdout or "").strip())
                    message = "release candidate DMG could not be detached after UI sampling smoke"
                    if detail:
                        message = f"{message}: {detail}"
                    findings.append(Finding(dmg_path, message))
            shutil.rmtree(mount_dir, ignore_errors=True)
    return findings, samples, bridge_ready_dmg_paths, bridge_statuses


def verify_dmg_chat_native_file_upload_smoke(
    root: Path,
    dmg_paths: Sequence[Path],
    *,
    timeout_seconds: float = DMG_CHAT_NATIVE_FILE_SMOKE_TIMEOUT_SECONDS,
) -> tuple[list[Finding], list[dict[str, object]]]:
    findings: list[Finding] = []
    uploads: list[dict[str, object]] = []
    if not dmg_paths:
        findings.append(Finding(root, "release candidate DMG Chat native file smoke requested but no .dmg artifacts were found"))
        return findings, uploads
    if sys.platform != "darwin":
        findings.append(Finding(root, "release candidate DMG Chat native file smoke requires macOS"))
        return findings, uploads

    script = root / DMG_CHAT_NATIVE_FILE_SMOKE_SCRIPT
    if not script.is_file():
        findings.append(Finding(script, "packaged Chat native file smoke script not found"))
        return findings, uploads

    for dmg_path in dmg_paths:
        absolute_dmg = _absolute_artifact_path(root, dmg_path)
        mount_dir = Path(tempfile.mkdtemp(prefix="oha-yachiyo-rc-chat-file-"))
        attached = False
        try:
            attach = subprocess.run(
                [
                    "hdiutil",
                    "attach",
                    str(absolute_dmg),
                    "-nobrowse",
                    "-readonly",
                    "-mountpoint",
                    str(mount_dir),
                    "-quiet",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if attach.returncode != 0:
                detail = redact_api_error_text((attach.stderr or attach.stdout or "").strip())
                message = "release candidate DMG could not be mounted for Chat native file smoke"
                if detail:
                    message = f"{message}: {detail}"
                findings.append(Finding(dmg_path, message))
                continue
            attached = True
            app_path = mount_dir / PACKAGED_APP_NAME
            executable_path = app_path / "Contents" / "MacOS" / PACKAGED_APP_EXECUTABLE_NAME
            if not executable_path.is_file():
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} must contain executable {PACKAGED_APP_EXECUTABLE_NAME}"))
                continue
            if not os.access(executable_path, os.X_OK):
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} executable is not executable"))
                continue

            with tempfile.TemporaryDirectory(prefix="oha-yachiyo-rc-chat-file-") as home_dir:
                report_path = Path(home_dir) / "packaged-chat-native-file-upload.json"
                command = [
                    "node",
                    str(DMG_CHAT_NATIVE_FILE_SMOKE_SCRIPT),
                    "--app-executable",
                    str(executable_path),
                    "--app-cwd",
                    str(app_path),
                    "--timeout-ms",
                    str(int(timeout_seconds * 1000)),
                    "--report-json",
                    str(report_path),
                ]
                try:
                    result = subprocess.run(
                        command,
                        cwd=root,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=timeout_seconds + 10.0,
                    )
                except subprocess.TimeoutExpired as exc:
                    detail = _redacted_process_detail(
                        _process_output_text(exc.stdout),
                        _process_output_text(exc.stderr),
                    )
                    message = f"release candidate packaged Chat native file smoke timed out after {timeout_seconds:.0f}s"
                    if detail:
                        message = f"{message}: {detail}"
                    findings.append(Finding(dmg_path, message))
                    continue
                except OSError as exc:
                    detail = redact_api_error_text(str(exc))
                    findings.append(Finding(dmg_path, f"release candidate packaged Chat native file smoke could not start: {detail}"))
                    continue
                if result.returncode != 0:
                    detail = _redacted_process_detail(result.stdout, result.stderr)
                    message = f"release candidate packaged Chat native file smoke failed with exit code {result.returncode}"
                    if detail:
                        message = f"{message}: {detail}"
                    findings.append(Finding(dmg_path, message))
                    continue
                try:
                    upload_report = _read_packaged_ui_sampling_report(report_path)
                except (OSError, json.JSONDecodeError) as exc:
                    findings.append(Finding(dmg_path, f"release candidate packaged Chat native file smoke report could not be read: {exc}"))
                    continue
                if upload_report.get("ok") is not True:
                    findings.append(Finding(dmg_path, "release candidate packaged Chat native file smoke report did not pass"))
                    continue
                app_build_metadata = upload_report.get("app_build_metadata")
                uploads.append(
                    {
                        "dmg_path": str(dmg_path),
                        "selected_file_name": upload_report.get("selected_file_name"),
                        "selected_file_count": upload_report.get("selected_file_count"),
                        "submitted_attachment_count": upload_report.get("submitted_attachment_count"),
                        "run_id": upload_report.get("run_id"),
                        "task_id": upload_report.get("task_id"),
                        "image_viewer_verified": upload_report.get("image_viewer_verified"),
                        "run_detail_verified": upload_report.get("run_detail_verified"),
                        "desktop_picker_ipc_verified": upload_report.get("desktop_picker_ipc_verified"),
                        "app_build_metadata": app_build_metadata
                        if isinstance(app_build_metadata, dict)
                        else {},
                    }
                )
        finally:
            if attached:
                detach = subprocess.run(
                    ["hdiutil", "detach", str(mount_dir), "-quiet"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if detach.returncode != 0:
                    detail = redact_api_error_text((detach.stderr or detach.stdout or "").strip())
                    message = "release candidate DMG could not be detached after Chat native file smoke"
                    if detail:
                        message = f"{message}: {detail}"
                    findings.append(Finding(dmg_path, message))
            shutil.rmtree(mount_dir, ignore_errors=True)
    return findings, uploads


def verify_release_candidate(
    *,
    root: Path = PROJECT_ROOT,
    artifact_paths: Sequence[Path] | None = None,
    require_artifacts: bool = False,
    source_only: bool = False,
    check_dmg_mount: bool = False,
    run_dmg_app_smoke: bool = False,
    run_dmg_screen_smoke: bool = False,
    run_dmg_ui_sampling_smoke: bool = False,
    run_dmg_chat_native_file_smoke: bool = False,
    run_provider_smoke: bool = False,
    run_ui_smoke: bool = False,
    smoke_scripts: Sequence[Path] | None = None,
    manual_checks_json: ManualChecksJsonInput = None,
    manual_checks_markdown: Path | None = None,
    require_manual_checks_complete: bool = False,
    mark_provider_smoke_not_applicable_if_missing: bool = False,
    report_json: Path | None = None,
) -> int:
    root = Path(root)
    failed = False
    manual_checks, manual_check_findings = _load_manual_release_candidate_checks(
        root,
        manual_checks_json,
        manual_checks_markdown,
    )
    manual_checks_source = (
        manual_checks_markdown
        if manual_checks_markdown is not None
        else _manual_checks_source_label(_manual_checks_json_paths(manual_checks_json))
    )
    manual_check_source_revisions = (
        _manual_check_markdown_source_revisions(root, manual_checks_markdown)
        if manual_checks_markdown is not None
        else _manual_check_source_revisions(root, manual_checks_json)
    )
    manual_check_status = _manual_release_candidate_check_status(
        manual_checks,
        manual_check_findings,
    )
    report: dict[str, Any] = {
        "ok": False,
        "source_revision": _source_revision(root),
        "source_release_guards": {"status": "pending", "findings": []},
        "built_artifact_guards": {
            "status": "pending",
            "artifact_paths": [],
            "findings": [],
        },
        "electron_ui_smoke": {
            "status": "pending",
            "scripts": [],
            "run_requested": run_ui_smoke,
        },
        "dmg_mount_guards": {
            "status": "pending",
            "dmg_paths": [],
            "findings": [],
            "run_requested": check_dmg_mount,
        },
        "dmg_app_smoke": {
            "status": "pending",
            "dmg_paths": [],
            "bridge_statuses": [],
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        },
        "dmg_screen_probe": {
            "status": "pending",
            "dmg_paths": [],
            "bridge_ready_dmg_paths": [],
            "bridge_statuses": [],
            "screens": [],
            "findings": [],
            "run_requested": run_dmg_screen_smoke,
        },
        "dmg_ui_sampling_smoke": {
            "status": "pending",
            "dmg_paths": [],
            "bridge_ready_dmg_paths": [],
            "bridge_statuses": [],
            "samples": [],
            "findings": [],
            "run_requested": run_dmg_ui_sampling_smoke,
        },
        "dmg_chat_native_file_smoke": {
            "status": "pending",
            "dmg_paths": [],
            "uploads": [],
            "findings": [],
            "run_requested": run_dmg_chat_native_file_smoke,
        },
        "provider_smoke": {
            "status": "pending",
            "checks": [],
            "findings": [],
            "run_requested": run_provider_smoke,
        },
        "manual_release_candidate_check_status": manual_check_status,
        "manual_release_candidate_checks": list(MANUAL_RELEASE_CANDIDATE_CHECKS),
        "manual_release_candidate_check_statuses": manual_checks,
        "manual_release_candidate_check_summary": _manual_release_candidate_check_summary(
            manual_checks
        ),
        "manual_release_candidate_check_findings": _finding_report(manual_check_findings),
        "manual_release_candidate_checks_source": str(manual_checks_source),
        "manual_release_candidate_checks_required": require_manual_checks_complete,
    }
    if manual_check_source_revisions:
        report["manual_release_candidate_check_source_revisions"] = (
            manual_check_source_revisions
        )

    source_only_conflicts: list[str] = []
    if source_only:
        if artifact_paths:
            source_only_conflicts.append("artifact paths")
        if require_artifacts:
            source_only_conflicts.append("--require-artifacts")
        if check_dmg_mount:
            source_only_conflicts.append("--check-dmg-mount")
        if run_dmg_app_smoke:
            source_only_conflicts.append("--run-dmg-app-smoke")
        if run_dmg_screen_smoke:
            source_only_conflicts.append("--run-dmg-screen-smoke")
        if run_dmg_ui_sampling_smoke:
            source_only_conflicts.append("--run-dmg-ui-sampling-smoke")
        if run_dmg_chat_native_file_smoke:
            source_only_conflicts.append("--run-dmg-chat-native-file-smoke")
        if run_provider_smoke:
            source_only_conflicts.append("--run-provider-smoke")
        if run_ui_smoke:
            source_only_conflicts.append("--run-ui-smoke")

    if source_only_conflicts:
        conflict_message = f"--source-only cannot be combined with {', '.join(source_only_conflicts)}"
        print("source release guards: skipped")
        print(f"built artifact guards: failed\n- {conflict_message}")
        report["source_release_guards"] = {
            "status": "skipped",
            "findings": [],
        }
        report["built_artifact_guards"] = {
            "status": "failed",
            "artifact_paths": [],
            "findings": [
                {
                    "path": str(root),
                    "message": conflict_message,
                }
            ],
        }
        report["dmg_mount_guards"] = {
            "status": "skipped",
            "dmg_paths": [],
            "findings": [],
            "run_requested": check_dmg_mount,
        }
        report["dmg_app_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "bridge_statuses": [],
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        }
        report["provider_smoke"] = {
            "status": "skipped",
            "checks": [],
            "findings": [],
            "run_requested": run_provider_smoke,
        }
        report["dmg_screen_probe"] = {
            "status": "skipped",
            "dmg_paths": [],
            "bridge_ready_dmg_paths": [],
            "bridge_statuses": [],
            "screens": [],
            "findings": [],
            "run_requested": run_dmg_screen_smoke,
        }
        report["dmg_ui_sampling_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "bridge_ready_dmg_paths": [],
            "bridge_statuses": [],
            "samples": [],
            "findings": [],
            "run_requested": run_dmg_ui_sampling_smoke,
        }
        report["dmg_chat_native_file_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "uploads": [],
            "findings": [],
            "run_requested": run_dmg_chat_native_file_smoke,
        }
        report["electron_ui_smoke"] = {
            "status": "skipped",
            "scripts": [],
            "run_requested": run_ui_smoke,
        }
        if report_json is not None:
            try:
                report_path = _resolve_report_path(root, report_json)
                _write_report(report_path, report)
            except (OSError, ValueError) as exc:
                print(f"release candidate report: failed\n- {exc}")
                return 1
            print(f"release candidate report: {report_json}")
        return 1

    source_findings = verify_release_artifacts(root=root)
    _print_findings("source release guards", source_findings)
    failed = failed or bool(source_findings)
    report["source_release_guards"] = {
        "status": "failed" if source_findings else "passed",
        "findings": _finding_report(source_findings),
    }

    selected_artifacts = (
        ()
        if source_only
        else tuple(artifact_paths) if artifact_paths is not None else existing_artifact_paths(root)
    )
    artifact_paths_valid = True
    try:
        selected_artifacts = _validate_artifact_paths(root, selected_artifacts)
    except ValueError as exc:
        print(f"built artifact guards: failed\n- {exc}")
        failed = True
        artifact_paths_valid = False
        report["built_artifact_guards"] = {
            "status": "failed",
            "artifact_paths": [str(path) for path in selected_artifacts],
            "findings": [{"path": str(root), "message": str(exc)}],
        }
    if report["built_artifact_guards"]["status"] == "pending":
        if source_only:
            print("built artifact guards: skipped by --source-only")
            report["built_artifact_guards"] = {
                "status": "skipped",
                "artifact_paths": [],
                "findings": [],
            }
            report["dmg_mount_guards"] = {
                "status": "skipped",
                "dmg_paths": [],
                "findings": [],
                "run_requested": check_dmg_mount,
            }
            report["dmg_app_smoke"] = {
                "status": "skipped",
                "dmg_paths": [],
                "bridge_statuses": [],
                "findings": [],
                "run_requested": run_dmg_app_smoke,
            }
            report["provider_smoke"] = {
                "status": "skipped",
                "checks": [],
                "findings": [],
                "run_requested": run_provider_smoke,
            }
            report["dmg_screen_probe"] = {
                "status": "skipped",
                "dmg_paths": [],
                "bridge_ready_dmg_paths": [],
                "bridge_statuses": [],
                "screens": [],
                "findings": [],
                "run_requested": run_dmg_screen_smoke,
            }
            report["dmg_ui_sampling_smoke"] = {
                "status": "skipped",
                "dmg_paths": [],
                "bridge_ready_dmg_paths": [],
                "bridge_statuses": [],
                "samples": [],
                "findings": [],
                "run_requested": run_dmg_ui_sampling_smoke,
            }
            report["dmg_chat_native_file_smoke"] = {
                "status": "skipped",
                "dmg_paths": [],
                "uploads": [],
                "findings": [],
                "run_requested": run_dmg_chat_native_file_smoke,
            }
        elif selected_artifacts:
            artifact_findings = verify_release_artifacts(
                root=root,
                paths=selected_artifacts,
                allow_binary_targets=True,
                check_packaged_app_bundle=True,
            )
            _print_findings("built artifact guards", artifact_findings)
            failed = failed or bool(artifact_findings)
            report["built_artifact_guards"] = {
                "status": "failed" if artifact_findings else "passed",
                "artifact_paths": [str(path) for path in selected_artifacts],
                "findings": _finding_report(artifact_findings),
            }
        elif require_artifacts:
            print(
                "built artifact guards: failed\n"
                "- release candidate artifacts not found under dist/backend, dist/electron, or release"
            )
            failed = True
            report["built_artifact_guards"] = {
                "status": "failed",
                "artifact_paths": [],
                "findings": [
                    {
                        "path": str(root),
                        "message": "release candidate artifacts not found under dist/backend, dist/electron, or release",
                    }
                ],
            }
        else:
            print("built artifact guards: skipped; pass --require-artifacts for a release-candidate gate")
            report["built_artifact_guards"] = {
                "status": "skipped",
                "artifact_paths": [],
                "findings": [],
            }

    if check_dmg_mount and not artifact_paths_valid:
        print("DMG mount guards: skipped because artifact paths failed validation")
        report["dmg_mount_guards"] = {
            "status": "skipped",
            "dmg_paths": [],
            "findings": [],
            "run_requested": check_dmg_mount,
        }
    elif check_dmg_mount:
        dmg_paths = release_candidate_dmg_paths(root, selected_artifacts)
        dmg_findings = verify_dmg_mount_artifacts(root, dmg_paths)
        _print_findings("DMG mount guards", dmg_findings)
        failed = failed or bool(dmg_findings)
        report["dmg_mount_guards"] = {
            "status": "failed" if dmg_findings else "passed",
            "dmg_paths": [str(path) for path in dmg_paths],
            "findings": _finding_report(dmg_findings),
            "run_requested": check_dmg_mount,
        }
    else:
        print("DMG mount guards: skipped; pass --check-dmg-mount to inspect the app inside DMG artifacts")
        report["dmg_mount_guards"] = {
            "status": "skipped",
            "dmg_paths": [],
            "findings": [],
            "run_requested": check_dmg_mount,
        }

    if run_dmg_app_smoke and not artifact_paths_valid:
        print("DMG app startup smoke: skipped because artifact paths failed validation")
        report["dmg_app_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "bridge_statuses": [],
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        }
    elif run_dmg_app_smoke:
        dmg_paths = release_candidate_dmg_paths(root, selected_artifacts)
        startup_findings, startup_bridge_statuses = verify_dmg_app_startup(root, dmg_paths)
        _print_findings("DMG app startup smoke", startup_findings)
        failed = failed or bool(startup_findings)
        report["dmg_app_smoke"] = {
            "status": "failed" if startup_findings else "passed",
            "dmg_paths": [str(path) for path in dmg_paths],
            "bridge_statuses": startup_bridge_statuses,
            "findings": _finding_report(startup_findings),
            "run_requested": run_dmg_app_smoke,
        }
    else:
        print("DMG app startup smoke: skipped; pass --run-dmg-app-smoke to launch the app inside DMG artifacts")
        report["dmg_app_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "bridge_statuses": [],
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        }

    if run_dmg_screen_smoke and not artifact_paths_valid:
        print("DMG screen recording probe: skipped because artifact paths failed validation")
        report["dmg_screen_probe"] = {
            "status": "skipped",
            "dmg_paths": [],
            "bridge_ready_dmg_paths": [],
            "bridge_statuses": [],
            "screens": [],
            "findings": [],
            "run_requested": run_dmg_screen_smoke,
        }
    elif run_dmg_screen_smoke:
        dmg_paths = release_candidate_dmg_paths(root, selected_artifacts)
        screen_findings, screen_results, screen_bridge_ready_paths, screen_bridge_statuses = (
            verify_dmg_screen_recording_probe(root, dmg_paths)
        )
        _print_findings("DMG screen recording probe", screen_findings)
        failed = failed or bool(screen_findings)
        report["dmg_screen_probe"] = {
            "status": "failed" if screen_findings else "passed",
            "dmg_paths": [str(path) for path in dmg_paths],
            "bridge_ready_dmg_paths": screen_bridge_ready_paths,
            "bridge_statuses": screen_bridge_statuses,
            "screens": screen_results,
            "findings": _finding_report(screen_findings),
            "run_requested": run_dmg_screen_smoke,
        }
    else:
        print("DMG screen recording probe: skipped; pass --run-dmg-screen-smoke to verify packaged /screen/current")
        report["dmg_screen_probe"] = {
            "status": "skipped",
            "dmg_paths": [],
            "bridge_ready_dmg_paths": [],
            "bridge_statuses": [],
            "screens": [],
            "findings": [],
            "run_requested": run_dmg_screen_smoke,
        }

    if run_dmg_ui_sampling_smoke and not artifact_paths_valid:
        print("DMG packaged UI sampling smoke: skipped because artifact paths failed validation")
        report["dmg_ui_sampling_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "bridge_ready_dmg_paths": [],
            "bridge_statuses": [],
            "samples": [],
            "findings": [],
            "run_requested": run_dmg_ui_sampling_smoke,
        }
    elif run_dmg_ui_sampling_smoke:
        dmg_paths = release_candidate_dmg_paths(root, selected_artifacts)
        ui_findings, ui_samples, ui_bridge_ready_paths, ui_bridge_statuses = verify_dmg_ui_sampling_smoke(
            root,
            dmg_paths,
        )
        _print_findings("DMG packaged UI sampling smoke", ui_findings)
        failed = failed or bool(ui_findings)
        report["dmg_ui_sampling_smoke"] = {
            "status": "failed" if ui_findings else "passed",
            "dmg_paths": [str(path) for path in dmg_paths],
            "bridge_ready_dmg_paths": ui_bridge_ready_paths,
            "bridge_statuses": ui_bridge_statuses,
            "samples": ui_samples,
            "findings": _finding_report(ui_findings),
            "run_requested": run_dmg_ui_sampling_smoke,
        }
    else:
        print("DMG packaged UI sampling smoke: skipped; pass --run-dmg-ui-sampling-smoke to sample packaged renderer routes")
        report["dmg_ui_sampling_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "bridge_ready_dmg_paths": [],
            "bridge_statuses": [],
            "samples": [],
            "findings": [],
            "run_requested": run_dmg_ui_sampling_smoke,
        }

    if run_dmg_chat_native_file_smoke and not artifact_paths_valid:
        print("DMG Chat native file smoke: skipped because artifact paths failed validation")
        report["dmg_chat_native_file_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "uploads": [],
            "findings": [],
            "run_requested": run_dmg_chat_native_file_smoke,
        }
    elif run_dmg_chat_native_file_smoke:
        dmg_paths = release_candidate_dmg_paths(root, selected_artifacts)
        upload_findings, uploads = verify_dmg_chat_native_file_upload_smoke(
            root,
            dmg_paths,
        )
        _print_findings("DMG Chat native file smoke", upload_findings)
        failed = failed or bool(upload_findings)
        report["dmg_chat_native_file_smoke"] = {
            "status": "failed" if upload_findings else "passed",
            "dmg_paths": [str(path) for path in dmg_paths],
            "uploads": uploads,
            "findings": _finding_report(upload_findings),
            "run_requested": run_dmg_chat_native_file_smoke,
        }
    else:
        print("DMG Chat native file smoke: skipped; pass --run-dmg-chat-native-file-smoke to verify packaged Chat native file upload")
        report["dmg_chat_native_file_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "uploads": [],
            "findings": [],
            "run_requested": run_dmg_chat_native_file_smoke,
        }

    bridge_revision_findings = _apply_bridge_status_source_revision_findings(report)
    if bridge_revision_findings or (
        _source_revision_commit(report) and _recorded_packaged_build_metadata(report)
    ):
        _print_findings(
            "DMG packaged build metadata revision guards",
            bridge_revision_findings,
        )
    failed = failed or bool(bridge_revision_findings)

    if run_provider_smoke:
        provider_findings, provider_results = verify_provider_smoke(root)
        _print_findings("real provider smoke", provider_findings)
        failed = failed or bool(provider_findings)
        report["provider_smoke"] = {
            "status": "failed" if provider_findings else "passed",
            "checks": provider_results,
            "findings": _finding_report(provider_findings),
            "run_requested": run_provider_smoke,
        }
    else:
        print("real provider smoke: skipped; pass --run-provider-smoke when OHA_YACHIYO_SMOKE_* credentials are configured")
        report["provider_smoke"] = {
            "status": "skipped",
            "checks": [],
            "findings": [],
            "run_requested": run_provider_smoke,
        }

    selected_smoke_scripts = tuple(smoke_scripts) if smoke_scripts is not None else release_ui_smoke_scripts(root)
    if run_ui_smoke:
        smoke_report = run_electron_ui_smoke_report(
            root=root,
            smoke_scripts=selected_smoke_scripts,
        )
        smoke_failed = not bool(smoke_report.get("ok"))
        failed = failed or smoke_failed
        report["electron_ui_smoke"] = {
            "status": "failed" if smoke_failed else "passed",
            "script_count": smoke_report.get("script_count", len(selected_smoke_scripts)),
            "scripts": smoke_report.get("scripts", []),
            "run_requested": run_ui_smoke,
        }
    else:
        print("Electron UI smoke: skipped; pass --run-ui-smoke after installing frontend dependencies")
        report["electron_ui_smoke"] = {
            "status": "skipped",
            "scripts": [str(script) for script in selected_smoke_scripts],
            "run_requested": run_ui_smoke,
        }

    _auto_apply_release_candidate_check_evidence(report, manual_checks)
    if mark_provider_smoke_not_applicable_if_missing:
        _mark_provider_smoke_not_applicable_if_missing(manual_checks)
    manual_check_status = _refresh_manual_release_candidate_check_report(
        report,
        manual_checks,
        manual_check_findings,
    )

    print("manual release-candidate checks:")
    for check in manual_checks:
        print(f"- [{check['id']}] {check['status']}: {check['description']}")
    manual_summary = report["manual_release_candidate_check_summary"]
    if isinstance(manual_summary, dict):
        _print_manual_release_candidate_check_summary(manual_summary)
    if manual_check_findings:
        print("manual release-candidate check evidence: failed")
        for finding in manual_check_findings:
            print(f"- {finding.format()}")
    elif manual_checks_source is not None:
        print(f"manual release-candidate check evidence: {manual_check_status}")
    if require_manual_checks_complete and manual_check_status != "passed":
        print(
            "manual release-candidate check evidence: incomplete\n"
            "- final signoff requires every manual check to be passed or not_applicable"
        )
    source_revision_final_signoff_findings = _source_revision_final_signoff_findings(
        root,
        report,
        require_manual_checks_complete=require_manual_checks_complete,
    )
    if source_revision_final_signoff_findings:
        _print_findings(
            "source revision final signoff guard",
            source_revision_final_signoff_findings,
        )
    report["source_revision_final_signoff_findings"] = _finding_report(
        source_revision_final_signoff_findings
    )
    manual_source_revision_findings = (
        _manual_evidence_source_revision_final_signoff_findings(
            root,
            report,
            require_manual_checks_complete=require_manual_checks_complete,
        )
    )
    if manual_source_revision_findings:
        _print_findings(
            "manual evidence source revision guard",
            manual_source_revision_findings,
        )
    report["manual_release_candidate_check_source_revision_findings"] = _finding_report(
        manual_source_revision_findings
    )

    failed = failed or manual_check_status == "failed" or (
        require_manual_checks_complete and manual_check_status != "passed"
    ) or bool(source_revision_final_signoff_findings) or bool(
        manual_source_revision_findings
    )
    report["ok"] = not failed
    if report_json is not None:
        try:
            report_path = _resolve_report_path(root, report_json)
            _write_report(report_path, report)
        except (OSError, ValueError) as exc:
            print(f"release candidate report: failed\n- {exc}")
            return 1
        print(f"release candidate report: {report_json}")

    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run local Oha-Yachiyo release-candidate verification gates."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Optional built artifact paths. Defaults to existing dist/backend, dist/electron, and release.",
    )
    parser.add_argument(
        "--require-artifacts",
        action="store_true",
        help="Fail when no built release artifacts are present.",
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Run source-level release guards only, rejecting built artifacts and UI smoke gates.",
    )
    parser.add_argument(
        "--run-ui-smoke",
        action="store_true",
        help="Run every scripts/smoke_*_ui.mjs Electron UI smoke.",
    )
    parser.add_argument(
        "--check-dmg-mount",
        action="store_true",
        help="Mount every discovered DMG and verify the packaged app inside it.",
    )
    parser.add_argument(
        "--run-dmg-app-smoke",
        action="store_true",
        help="Launch the app inside discovered DMGs and wait for its packaged /status endpoint.",
    )
    parser.add_argument(
        "--run-dmg-screen-smoke",
        action="store_true",
        help="Launch the app inside discovered DMGs and verify packaged /screen/current for Screen Recording signoff evidence.",
    )
    parser.add_argument(
        "--run-dmg-ui-sampling-smoke",
        action="store_true",
        help="Launch the app inside discovered DMGs and sample key packaged renderer routes through Chromium DevTools.",
    )
    parser.add_argument(
        "--run-dmg-chat-native-file-smoke",
        action="store_true",
        help="Launch the packaged app inside discovered DMGs and verify Chat native image file upload through the desktop picker IPC.",
    )
    parser.add_argument(
        "--run-provider-smoke",
        action="store_true",
        help="Run opt-in real provider streaming and tool-call smoke using OHA_YACHIYO_SMOKE_* credentials.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Write a machine-readable release-candidate verification report.",
    )
    parser.add_argument(
        "--manual-checks-json",
        type=Path,
        action="append",
        help=(
            "Merge manual release-candidate check evidence from a project-local JSON file. "
            "May be passed multiple times; later files override earlier check ids."
        ),
    )
    parser.add_argument(
        "--manual-checks-markdown",
        type=Path,
        help="Merge manual release-candidate check evidence from a project-local Markdown checklist.",
    )
    parser.add_argument(
        "--require-manual-checks-complete",
        action="store_true",
        help="Fail unless every manual release-candidate check is passed or not_applicable.",
    )
    parser.add_argument(
        "--write-manual-checks-template",
        type=Path,
        help="Write a project-local manual release-candidate checks JSON template and exit.",
    )
    parser.add_argument(
        "--write-manual-checks-draft",
        type=Path,
        help=(
            "Write a project-local editable manual check draft, optionally seeded from "
            "--manual-checks-json, and exit."
        ),
    )
    parser.add_argument(
        "--write-manual-checks-markdown",
        type=Path,
        help=(
            "Write a project-local manual release-candidate signoff checklist in Markdown, "
            "optionally seeded from --manual-checks-json, and exit."
        ),
    )
    parser.add_argument(
        "--print-manual-checks-status",
        action="store_true",
        help=(
            "Load project-local manual release-candidate check evidence, print progress "
            "and remaining next actions, then exit without running artifact gates."
        ),
    )
    parser.add_argument(
        "--mark-provider-smoke-not-applicable-if-missing",
        action="store_true",
        help=(
            "Mark real_provider_smoke not_applicable if any OHA_YACHIYO_SMOKE_* "
            "credential is missing. Applies to RC reports, manual check drafts, "
            "and Markdown checklists."
        ),
    )
    args = parser.parse_args(argv)
    if args.manual_checks_json is not None and args.manual_checks_markdown is not None:
        print(
            "manual release-candidate checks: failed\n"
            "- choose either --manual-checks-json or --manual-checks-markdown"
        )
        return 1
    write_actions = [
        args.write_manual_checks_template is not None,
        args.write_manual_checks_draft is not None,
        args.write_manual_checks_markdown is not None,
    ]
    if sum(1 for enabled in [*write_actions, args.print_manual_checks_status] if enabled) > 1:
        print(
            "manual release-candidate checks: failed\n"
            "- choose only one of --write-manual-checks-template, "
            "--write-manual-checks-draft, --write-manual-checks-markdown, "
            "or --print-manual-checks-status"
        )
        return 1
    if args.print_manual_checks_status:
        ok = print_manual_release_candidate_checks_status(
            PROJECT_ROOT,
            args.manual_checks_markdown or args.manual_checks_json,
            mark_provider_smoke_not_applicable_if_missing=(
                args.mark_provider_smoke_not_applicable_if_missing
            ),
        )
        return 0 if ok else 1
    if args.write_manual_checks_template is not None:
        try:
            write_manual_release_candidate_checks_template(
                PROJECT_ROOT,
                args.write_manual_checks_template,
            )
        except (OSError, ValueError) as exc:
            print(f"manual release-candidate checks template: failed\n- {exc}")
            return 1
        print(f"manual release-candidate checks template: {args.write_manual_checks_template}")
        return 0
    if args.write_manual_checks_draft is not None:
        try:
            write_manual_release_candidate_checks_draft(
                PROJECT_ROOT,
                args.write_manual_checks_draft,
                args.manual_checks_json,
                mark_provider_smoke_not_applicable_if_missing=(
                    args.mark_provider_smoke_not_applicable_if_missing
                ),
            )
        except (OSError, ValueError) as exc:
            print(f"manual release-candidate checks draft: failed\n- {exc}")
            return 1
        print(f"manual release-candidate checks draft: {args.write_manual_checks_draft}")
        _print_manual_release_candidate_checks_for_write_action(
            PROJECT_ROOT,
            args.manual_checks_json,
            mark_provider_smoke_not_applicable_if_missing=(
                args.mark_provider_smoke_not_applicable_if_missing
            ),
        )
        return 0
    if args.write_manual_checks_markdown is not None:
        try:
            write_manual_release_candidate_checks_markdown(
                PROJECT_ROOT,
                args.write_manual_checks_markdown,
                args.manual_checks_markdown or args.manual_checks_json,
                mark_provider_smoke_not_applicable_if_missing=(
                    args.mark_provider_smoke_not_applicable_if_missing
                ),
            )
        except (OSError, ValueError) as exc:
            print(f"manual release-candidate checks markdown: failed\n- {exc}")
            return 1
        print(f"manual release-candidate checks markdown: {args.write_manual_checks_markdown}")
        _print_manual_release_candidate_checks_for_write_action(
            PROJECT_ROOT,
            args.manual_checks_markdown or args.manual_checks_json,
            mark_provider_smoke_not_applicable_if_missing=(
                args.mark_provider_smoke_not_applicable_if_missing
            ),
        )
        return 0
    return verify_release_candidate(
        artifact_paths=args.paths or None,
        require_artifacts=args.require_artifacts,
        source_only=args.source_only,
        check_dmg_mount=args.check_dmg_mount,
        run_dmg_app_smoke=args.run_dmg_app_smoke,
        run_dmg_screen_smoke=args.run_dmg_screen_smoke,
        run_dmg_ui_sampling_smoke=args.run_dmg_ui_sampling_smoke,
        run_dmg_chat_native_file_smoke=args.run_dmg_chat_native_file_smoke,
        run_provider_smoke=args.run_provider_smoke,
        run_ui_smoke=args.run_ui_smoke,
        manual_checks_json=args.manual_checks_json,
        manual_checks_markdown=args.manual_checks_markdown,
        require_manual_checks_complete=args.require_manual_checks_complete,
        mark_provider_smoke_not_applicable_if_missing=(
            args.mark_provider_smoke_not_applicable_if_missing
        ),
        report_json=args.report_json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
