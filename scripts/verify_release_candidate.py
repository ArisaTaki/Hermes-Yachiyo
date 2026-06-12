"""Local release-candidate verification entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

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
        "next_action": "Manually grant Screen Recording to the packaged app in System Settings and verify local screenshot or proactive probe success.",
    },
    {
        "id": "chat_native_file_upload",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "Use the packaged app's Chat image attach button with the native file picker and verify preview, send, message attachment, image viewer, and Run Detail handoff.",
        "evidence": "Record the image filename, native picker path used, sent message attachment metadata, image viewer open/close result, and linked Run Detail id.",
        "next_action": "Manually use the packaged Chat image attach button and native file picker, then verify preview, send, image viewer, and Run Detail handoff.",
    },
    {
        "id": "packaged_ui_sampling",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "Sample mature packaged app surfaces across Chat approval/cancel, Run Detail replay, Workflow save-and-run, Agent Studio, group/delegation/session summary, manual TTS, and Live2D.",
        "evidence": "Record the packaged app build, sampled pages/actions, and visible pass/fail result for each sampled mature surface.",
        "next_action": "Manually sample the packaged app surfaces listed here; --run-ui-smoke is supporting regression evidence but does not replace packaged UI sampling.",
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
MANUAL_RELEASE_CANDIDATE_CHECKS: tuple[str, ...] = tuple(
    check["description"] for check in MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
)
MANUAL_RELEASE_CANDIDATE_CHECK_MARKDOWN_RE = re.compile(
    r"^- \[(?P<checked>[ xX])\] `(?P<id>[^`]+)`(?: - (?P<status>[A-Za-z_]+))?\s*$"
)


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


def _manual_release_candidate_check_draft(
    checks: Sequence[dict[str, str]],
    *,
    source_path: Path | None = None,
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
    if source_path is not None:
        draft["manual_release_candidate_checks_source"] = str(source_path)
    return draft


def _manual_release_candidate_checks_markdown(
    checks: Sequence[dict[str, str]],
    *,
    source_path: Path | None = None,
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
    manual_checks_arg = str(markdown_path) if markdown_path is not None else "<this-checklist.md>"
    lines = [
        "# Oha-Yachiyo Manual Release-Candidate Signoff",
        "",
        f"- Source: `{source_path}`" if source_path is not None else "- Source: manual checks",
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
        "## Remaining Manual Checks",
        "",
    ]
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
                "passed via Electron UI smoke; the packaged native file picker still "
                "requires manual evidence."
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
        "failed_check_ids": failed_check_ids,
        "automated_evidence_check_ids": automated_evidence_check_ids,
    }


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
    source_path: Path | None = None,
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
        _manual_release_candidate_check_draft(checks, source_path=source_path),
    )
    return resolved


def write_manual_release_candidate_checks_markdown(
    root: Path,
    output_path: Path,
    source_path: Path | None = None,
    *,
    mark_provider_smoke_not_applicable_if_missing: bool = False,
) -> Path:
    source_is_markdown = (
        source_path is not None and source_path.suffix.lower() in {".md", ".markdown"}
    )
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
    manual_checks_json: Path | None,
    manual_checks_markdown: Path | None = None,
) -> tuple[list[dict[str, str]], list[Finding]]:
    checks = _manual_release_candidate_check_report()
    findings: list[Finding] = []
    if manual_checks_json is not None and manual_checks_markdown is not None:
        findings.append(
            Finding(
                manual_checks_json,
                "manual release-candidate checks must use either JSON or Markdown input, not both",
            )
        )
        return checks, findings
    if manual_checks_json is None and manual_checks_markdown is None:
        return checks, findings

    try:
        if manual_checks_markdown is not None:
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
        else:
            evidence_path = _resolve_project_file(
                root,
                manual_checks_json,
                "manual release-candidate checks",
            )
            raw_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            raw_checks = _manual_release_candidate_checks_from_payload(raw_payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        source_path = manual_checks_markdown or manual_checks_json
        findings.append(
            Finding(
                source_path or root,
                f"manual release-candidate checks could not be loaded: {exc}",
            )
        )
        return checks, findings

    if not isinstance(raw_checks, list):
        findings.append(
            Finding(
                manual_checks_markdown or manual_checks_json or root,
                (
                    "manual release-candidate checks JSON must be a list, contain a checks list, "
                    "or be a previous RC report with manual_release_candidate_check_statuses"
                ),
            )
        )
        return checks, findings

    known = {check["id"]: check for check in checks}
    seen: set[str] = set()
    for index, raw_check in enumerate(raw_checks):
        if not isinstance(raw_check, dict):
            findings.append(
                Finding(
                    manual_checks_markdown or manual_checks_json or root,
                    f"manual release-candidate check at index {index} must be an object",
                )
            )
            continue
        check_id = str(raw_check.get("id", "")).strip()
        if check_id not in known:
            findings.append(
                Finding(
                    manual_checks_markdown or manual_checks_json or root,
                    f"manual release-candidate check has unknown id: {check_id or '<missing>'}",
                )
            )
            continue
        if check_id in seen:
            findings.append(
                Finding(
                    manual_checks_markdown or manual_checks_json or root,
                    f"manual release-candidate check is duplicated: {check_id}",
                )
            )
            continue
        seen.add(check_id)

        status = str(raw_check.get("status", "")).strip()
        if status not in MANUAL_RELEASE_CANDIDATE_CHECK_STATUS_VALUES:
            findings.append(
                Finding(
                    manual_checks_markdown or manual_checks_json or root,
                    f"manual release-candidate check {check_id} has invalid status: {status or '<missing>'}",
                )
            )
            continue
        evidence = str(raw_check.get("evidence", "")).strip()
        if status in {"passed", "failed", "not_applicable"} and not evidence:
            findings.append(
                Finding(
                    manual_checks_markdown or manual_checks_json or root,
                    f"manual release-candidate check {check_id} requires evidence for status {status}",
                )
            )
            continue

        target = known[check_id]
        target["status"] = status
        if evidence:
            target["evidence"] = evidence
        notes = raw_check.get("notes")
        if notes is not None:
            target["notes"] = str(notes)
        evidence_source = str(raw_check.get("evidence_source", "")).strip()
        if evidence_source in {"automated_rc_gate", "credentials_unavailable"}:
            target["evidence_source"] = evidence_source

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
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
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


def _read_status_json(bridge_url: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{bridge_url}/status", timeout=1.0) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    return data if isinstance(data, dict) else {}


def verify_dmg_app_startup(
    root: Path,
    dmg_paths: Sequence[Path],
    *,
    timeout_seconds: float = DMG_APP_SMOKE_TIMEOUT_SECONDS,
) -> list[Finding]:
    findings: list[Finding] = []
    if not dmg_paths:
        findings.append(Finding(root, "release candidate DMG app startup smoke requested but no .dmg artifacts were found"))
        return findings
    if sys.platform != "darwin":
        findings.append(Finding(root, "release candidate DMG app startup smoke requires macOS"))
        return findings
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
                )
                deadline = time.monotonic() + timeout_seconds
                last_error = ""
                passed = False
                while time.monotonic() < deadline:
                    exit_code = process.poll()
                    if exit_code is not None:
                        stdout, stderr = _read_process_output(process)
                        detail = _redacted_process_detail(stdout, stderr)
                        message = f"release candidate app exited before /status was ready: exit_code={exit_code}"
                        if detail:
                            message = f"{message}: {detail}"
                        findings.append(Finding(dmg_path, message))
                        break
                    try:
                        status = _read_status_json(bridge_url)
                    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                        last_error = redact_api_error_text(str(exc))
                        time.sleep(0.5)
                        continue
                    if status.get("service") == "oha-yachiyo":
                        passed = True
                        break
                    last_error = redact_api_error_text(f"unexpected /status service={status.get('service')!r}")
                    time.sleep(0.5)
                if not passed and not any(finding.path == dmg_path for finding in findings):
                    message = f"release candidate app did not expose /status within {timeout_seconds:.0f}s"
                    if last_error:
                        message = f"{message}: {last_error}"
                    findings.append(Finding(dmg_path, message))
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
    return findings


def verify_release_candidate(
    *,
    root: Path = PROJECT_ROOT,
    artifact_paths: Sequence[Path] | None = None,
    require_artifacts: bool = False,
    source_only: bool = False,
    check_dmg_mount: bool = False,
    run_dmg_app_smoke: bool = False,
    run_provider_smoke: bool = False,
    run_ui_smoke: bool = False,
    smoke_scripts: Sequence[Path] | None = None,
    manual_checks_json: Path | None = None,
    manual_checks_markdown: Path | None = None,
    require_manual_checks_complete: bool = False,
    report_json: Path | None = None,
) -> int:
    root = Path(root)
    failed = False
    manual_checks, manual_check_findings = _load_manual_release_candidate_checks(
        root,
        manual_checks_json,
        manual_checks_markdown,
    )
    manual_checks_source = manual_checks_markdown or manual_checks_json
    manual_check_status = _manual_release_candidate_check_status(
        manual_checks,
        manual_check_findings,
    )
    report: dict[str, Any] = {
        "ok": False,
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
            "findings": [],
            "run_requested": run_dmg_app_smoke,
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
        "manual_release_candidate_checks_source": str(manual_checks_source)
        if manual_checks_source
        else "",
        "manual_release_candidate_checks_required": require_manual_checks_complete,
    }

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
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        }
        report["provider_smoke"] = {
            "status": "skipped",
            "checks": [],
            "findings": [],
            "run_requested": run_provider_smoke,
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
                "findings": [],
                "run_requested": run_dmg_app_smoke,
            }
            report["provider_smoke"] = {
                "status": "skipped",
                "checks": [],
                "findings": [],
                "run_requested": run_provider_smoke,
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
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        }
    elif run_dmg_app_smoke:
        dmg_paths = release_candidate_dmg_paths(root, selected_artifacts)
        startup_findings = verify_dmg_app_startup(root, dmg_paths)
        _print_findings("DMG app startup smoke", startup_findings)
        failed = failed or bool(startup_findings)
        report["dmg_app_smoke"] = {
            "status": "failed" if startup_findings else "passed",
            "dmg_paths": [str(path) for path in dmg_paths],
            "findings": _finding_report(startup_findings),
            "run_requested": run_dmg_app_smoke,
        }
    else:
        print("DMG app startup smoke: skipped; pass --run-dmg-app-smoke to launch the app inside DMG artifacts")
        report["dmg_app_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        }

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
        remaining_ids = manual_summary.get("remaining_check_ids")
        remaining_count = manual_summary.get("remaining_count")
        if isinstance(remaining_ids, list) and remaining_ids:
            print(
                "manual release-candidate check summary: "
                f"{remaining_count} remaining ({', '.join(str(check_id) for check_id in remaining_ids)})"
            )
            remaining_next_actions = manual_summary.get("remaining_next_actions")
            if isinstance(remaining_next_actions, list):
                print("manual release-candidate next actions:")
                for item in remaining_next_actions:
                    if not isinstance(item, dict):
                        continue
                    check_id = str(item.get("id", "")).strip()
                    next_action = str(item.get("next_action", "")).strip()
                    if check_id and next_action:
                        print(f"- [{check_id}] {next_action}")
        else:
            print("manual release-candidate check summary: complete")
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

    failed = failed or manual_check_status == "failed" or (
        require_manual_checks_complete and manual_check_status != "passed"
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
        help="Merge manual release-candidate check evidence from a project-local JSON file.",
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
        "--mark-provider-smoke-not-applicable-if-missing",
        action="store_true",
        help=(
            "When writing a manual check draft or Markdown checklist, mark "
            "real_provider_smoke not_applicable if any OHA_YACHIYO_SMOKE_* credential "
            "is missing."
        ),
    )
    args = parser.parse_args(argv)
    if args.manual_checks_json is not None and args.manual_checks_markdown is not None:
        print(
            "manual release-candidate checks: failed\n"
            "- choose either --manual-checks-json or --manual-checks-markdown"
        )
        return 1
    if (
        args.mark_provider_smoke_not_applicable_if_missing
        and args.write_manual_checks_draft is None
        and args.write_manual_checks_markdown is None
    ):
        print(
            "manual release-candidate checks: failed\n"
            "- --mark-provider-smoke-not-applicable-if-missing requires "
            "--write-manual-checks-draft or --write-manual-checks-markdown"
        )
        return 1
    write_actions = [
        args.write_manual_checks_template is not None,
        args.write_manual_checks_draft is not None,
        args.write_manual_checks_markdown is not None,
    ]
    if sum(1 for enabled in write_actions if enabled) > 1:
        print(
            "manual release-candidate checks: failed\n"
            "- choose only one of --write-manual-checks-template, "
            "--write-manual-checks-draft, or --write-manual-checks-markdown"
        )
        return 1
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
        return 0
    return verify_release_candidate(
        artifact_paths=args.paths or None,
        require_artifacts=args.require_artifacts,
        source_only=args.source_only,
        check_dmg_mount=args.check_dmg_mount,
        run_dmg_app_smoke=args.run_dmg_app_smoke,
        run_provider_smoke=args.run_provider_smoke,
        run_ui_smoke=args.run_ui_smoke,
        manual_checks_json=args.manual_checks_json,
        manual_checks_markdown=args.manual_checks_markdown,
        require_manual_checks_complete=args.require_manual_checks_complete,
        report_json=args.report_json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
