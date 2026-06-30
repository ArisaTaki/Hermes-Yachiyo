#!/usr/bin/env python3
"""Summarize Phase 11 release-smoke coverage from existing evidence."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.summarize_native_agent_capabilities import (  # noqa: E402
    SOURCE_SECTION_CAPABILITIES,
    capability_matrix_from_report,
    summarize_capabilities,
)


SECTION_TO_CAPABILITY = {
    section: capability_id
    for capability_id, section in SOURCE_SECTION_CAPABILITIES.items()
}
SECTION_IDS = set(SOURCE_SECTION_CAPABILITIES.values()) | {
    "dmg_app_smoke",
    "dmg_ui_sampling_smoke",
    "dmg_chat_native_file_smoke",
    "packaged_backend_bridge_smoke",
    "provider_smoke",
}
FULL_PUBLIC_DEMO_COMMAND = (
    "python scripts/run_public_demo_smokes.py "
    "--include-real-desktop --include-provider-workflow --include-ui "
    "--output-json tmp/public-demo-smokes-full.json "
    "--output-markdown tmp/public-demo-smokes-full.md"
)
SMOKE_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "id": "packaged_launch",
        "label": "Packaged app launches and uses its own Bridge",
        "required": ("packaged_app_bridge_isolation",),
        "next_action": (
            "python scripts/verify_release_candidate.py --require-artifacts "
            "--run-dmg-app-smoke --report-json tmp/rc-verification-dmg-app.json"
        ),
    },
    {
        "id": "chat_desktop_task",
        "label": "Chat can route a desktop execution task",
        "required": ("source_agent_entrypoint_desktop_execution",),
        "next_action": (
            "python scripts/verify_release_candidate.py --source-only "
            "--report-json tmp/rc-verification-source-capabilities.json"
        ),
    },
    {
        "id": "approval_card",
        "label": "Approval card is observable and resumable",
        "required": (
            "source_approval_resume_timeline",
            "source_yachiyo_route_approval",
        ),
        "next_action": (
            "python scripts/verify_release_candidate.py --source-only "
            "--report-json tmp/rc-verification-source-capabilities.json"
        ),
    },
    {
        "id": "agent_studio_run_timeline",
        "label": "Agent Studio can show a replayable run timeline",
        "required": ("source_approval_resume_timeline",),
        "next_action": (
            "python scripts/smoke_approval_resume_timeline.py "
            "--report-json tmp/approval-resume-timeline.json"
        ),
    },
    {
        "id": "group_run",
        "label": "GroupRun stays observable in Agent Studio",
        "required": ("source_group_run_timeline",),
        "next_action": (
            "python scripts/smoke_group_run_timeline.py "
            "--report-json tmp/group-run-timeline.json"
        ),
    },
    {
        "id": "workflow",
        "label": "Workflow has source entrypoint and provider orchestration evidence",
        "required": (
            "source_agent_entrypoint_data_analysis",
            "advanced_workflow_orchestration",
        ),
        "next_action": (
            "python scripts/verify_release_candidate.py --require-artifacts "
            "--check-dmg-mount --run-provider-smoke "
            "--report-json tmp/rc-verification-provider-smoke.json"
        ),
    },
    {
        "id": "public_demo",
        "label": "Public demo evidence covers release-facing flows",
        "required": ("public_demo_complete",),
        "related": ("public_demo_assessment", "public_demo_selected"),
        "next_action": FULL_PUBLIC_DEMO_COMMAND,
    },
    {
        "id": "artifact_readback",
        "label": "Artifacts can be written and read back",
        "required": ("source_data_analysis_artifact",),
        "next_action": (
            "python scripts/verify_release_candidate.py --source-only "
            "--report-json tmp/rc-verification-source-capabilities.json"
        ),
    },
    {
        "id": "diagnostics_export",
        "label": "Redacted diagnostics bundle can be exported",
        "required": ("diagnostics_export",),
        "next_action": (
            "python scripts/collect_release_diagnostics.py "
            "--label $(git rev-parse --short=8 HEAD) "
            "--include-app-logs "
            "--output-zip tmp/oha-yachiyo-diagnostics-$(git rev-parse --short=8 HEAD).zip"
        ),
    },
)


def summarize_release_smoke(
    reports: Sequence[Path | str],
    *,
    diagnostics_zips: Sequence[Path | str] = (),
) -> dict[str, Any]:
    evidence: dict[str, list[dict[str, Any]]] = {}
    source_reports: list[str] = []
    visited_reports: set[Path] = set()
    for report_path in reports:
        path = _resolve_path(Path(report_path))
        source_reports.append(_display_path(path))
        report = _load_report(path)
        visited_reports.add(path.resolve())
        _collect_report_evidence(
            report,
            source=_display_path(path),
            evidence=evidence,
            visited_reports=visited_reports,
        )
    diagnostics_sources: list[str] = []
    for archive_path in diagnostics_zips:
        path = _resolve_path(Path(archive_path))
        diagnostics_sources.append(_display_path(path))
        _collect_diagnostics_evidence(path, evidence=evidence)

    items = [_item_status(item, evidence) for item in SMOKE_ITEMS]
    passed_count = sum(1 for item in items if item["status"] == "passed")
    missing = [item for item in items if item["status"] != "passed"]
    return {
        "ok": not missing,
        "status": "passed" if not missing else "incomplete",
        "item_count": len(items),
        "passed_count": passed_count,
        "missing_count": len(missing),
        "missing_item_ids": [item["id"] for item in missing],
        "items": items,
        "source_reports": source_reports,
        "diagnostics_sources": diagnostics_sources,
        "next_actions": _next_actions(missing),
    }


def render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Oha-Yachiyo Release Smoke Summary",
        "",
        f"Status: {summary.get('status')}",
        f"Coverage: {summary.get('passed_count')}/{summary.get('item_count')} passed",
        "",
        "## Checklist",
        "",
    ]
    for item in _dict_list(summary.get("items")):
        marker = "x" if item.get("status") == "passed" else " "
        lines.append(f"- [{marker}] `{item.get('id')}` - {item.get('label')}")
        missing = _string_list(item.get("missing_evidence_ids"))
        if missing:
            lines.append(f"  Missing evidence: {', '.join(f'`{value}`' for value in missing)}")
        demo_details = _public_demo_item_details(item)
        if demo_details:
            release_level = str(demo_details.get("release_level") or "")
            if release_level:
                lines.append(f"  Public demo level: `{release_level}`")
            missing_flows = _string_list(demo_details.get("missing_required_flow_ids"))
            if missing_flows:
                lines.append(
                    "  Missing demo flows: "
                    + ", ".join(f"`{value}`" for value in missing_flows)
                )
            for blocker in _dict_list(demo_details.get("release_blockers")):
                blocker_id = str(blocker.get("id") or "").strip()
                reason = str(blocker.get("reason") or "").strip()
                if blocker_id and reason:
                    lines.append(f"  Demo blocker `{blocker_id}`: `{reason}`")
    actions = _dict_list(summary.get("next_actions"))
    if actions:
        lines.extend(["", "## Next Actions", ""])
        for action in actions:
            lines.append(f"- `{action.get('id')}`")
            release_level = str(action.get("release_level") or "")
            if release_level:
                lines.append(f"  Release level: `{release_level}`")
            missing_flows = _string_list(action.get("missing_required_flow_ids"))
            if missing_flows:
                lines.append(
                    "  Missing demo flows: "
                    + ", ".join(f"`{value}`" for value in missing_flows)
                )
            for blocker in _dict_list(action.get("release_blockers")):
                blocker_id = str(blocker.get("id") or "").strip()
                reason = str(blocker.get("reason") or "").strip()
                if blocker_id and reason:
                    lines.append(f"  Demo blocker `{blocker_id}`: `{reason}`")
            command = str(action.get("command") or "").strip()
            if command:
                lines.extend(["", "```bash", command, "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _collect_report_evidence(
    report: Mapping[str, Any],
    *,
    source: str,
    evidence: dict[str, list[dict[str, Any]]],
    visited_reports: set[Path],
) -> None:
    mode = str(report.get("mode") or "").strip()
    if mode and report.get("ok") is True:
        _add_evidence(evidence, mode, source=source, kind="smoke_mode")
        capability_id = SECTION_TO_CAPABILITY.get(mode)
        if capability_id:
            _add_evidence(
                evidence,
                capability_id,
                source=source,
                kind="smoke_mode_capability",
            )
    _collect_public_demo_evidence(
        report,
        source=source,
        evidence=evidence,
        visited_reports=visited_reports,
    )
    for section_id in sorted(SECTION_IDS):
        section = report.get(section_id)
        if isinstance(section, dict) and _section_passed(section):
            _add_evidence(evidence, section_id, source=source, kind="section")
    matrix = _matrix_from_report(report)
    capabilities = matrix.get("capabilities") if isinstance(matrix, dict) else []
    if isinstance(capabilities, list):
        for capability in capabilities:
            if not isinstance(capability, dict) or capability.get("status") != "passed":
                continue
            capability_id = str(capability.get("id") or "").strip()
            if capability_id:
                _add_evidence(
                    evidence,
                    capability_id,
                    source=source,
                    kind="capability",
                    label=str(capability.get("label") or ""),
                )


def _collect_diagnostics_evidence(
    archive_path: Path,
    *,
    evidence: dict[str, list[dict[str, Any]]],
) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            payload = json.loads(archive.read("diagnostics/manifest.json").decode("utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    redaction = payload.get("redaction")
    redaction = redaction if isinstance(redaction, dict) else {}
    if (
        payload.get("ok") is True
        and int(payload.get("included_count") or 0) > 0
        and redaction.get("applied") is True
    ):
        _add_evidence(
            evidence,
            "diagnostics_export",
            source=_display_path(archive_path),
            kind="diagnostics_bundle",
            included_count=int(payload.get("included_count") or 0),
        )


def _item_status(
    item: Mapping[str, Any],
    evidence: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    required = tuple(str(value) for value in item.get("required", ()))
    related = tuple(str(value) for value in item.get("related", ()))
    present = [value for value in required if value in evidence]
    missing = [value for value in required if value not in evidence]
    related_present = [value for value in related if value in evidence]
    return {
        "id": str(item["id"]),
        "label": str(item["label"]),
        "status": "passed" if not missing else "missing",
        "required_evidence_ids": list(required),
        "present_evidence_ids": present,
        "missing_evidence_ids": missing,
        "related_evidence_ids": related_present,
        "evidence": {
            evidence_id: evidence[evidence_id]
            for evidence_id in present
        },
        "related_evidence": {
            evidence_id: evidence[evidence_id]
            for evidence_id in related_present
        },
        "next_action": str(item.get("next_action") or ""),
    }


def _next_actions(missing_items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen_commands: set[str] = set()
    for item in missing_items:
        command = str(item.get("next_action") or "").strip()
        if not command or command in seen_commands:
            continue
        seen_commands.add(command)
        action: dict[str, Any] = {
            "id": str(item.get("id") or "next_action"),
            "command": command,
        }
        if item.get("id") == "public_demo":
            demo_details = _public_demo_item_details(item)
            if demo_details:
                action.update(
                    {
                        key: value
                        for key, value in demo_details.items()
                        if key in {"release_level", "missing_required_flow_ids", "release_blockers"}
                    }
                )
                full_demo_command = str(demo_details.get("full_demo_command") or "").strip()
                if full_demo_command:
                    action["command"] = full_demo_command
        actions.append(action)
    return actions


def _matrix_from_report(report: Mapping[str, Any]) -> dict[str, Any]:
    raw_matrix = report.get("native_agent_capability_matrix")
    if isinstance(raw_matrix, dict):
        try:
            return capability_matrix_from_report(dict(report))
        except Exception:
            return dict(raw_matrix)
    if _has_capability_sections(report):
        return summarize_capabilities(dict(report))
    raw_capabilities = report.get("capabilities")
    if isinstance(raw_capabilities, list):
        return dict(report)
    return {"capabilities": []}


def _has_capability_sections(report: Mapping[str, Any]) -> bool:
    known_sections = tuple(SOURCE_SECTION_CAPABILITIES.values()) + (
        "provider_smoke",
        "native_provider_contract_smoke",
        "packaged_backend_bridge_smoke",
        "dmg_app_smoke",
    )
    return any(isinstance(report.get(section), dict) for section in known_sections)


def _section_passed(section: Mapping[str, Any]) -> bool:
    return section.get("status") == "passed" or section.get("ok") is True


def _collect_public_demo_evidence(
    report: Mapping[str, Any],
    *,
    source: str,
    evidence: dict[str, list[dict[str, Any]]],
    visited_reports: set[Path],
) -> None:
    if not isinstance(report.get("flows"), list):
        return
    if "selected_count" not in report or "complete" not in report:
        return
    assessment = _public_demo_assessment(report)
    _add_evidence(
        evidence,
        "public_demo_assessment",
        source=source,
        kind="public_demo_assessment",
        **assessment,
    )
    if report.get("ok") is True:
        _add_evidence(
            evidence,
            "public_demo_selected",
            source=source,
            kind="public_demo",
            **assessment,
        )
    if _public_demo_is_complete(report):
        _add_evidence(
            evidence,
            "public_demo_complete",
            source=source,
            kind="public_demo",
            **assessment,
        )
    _collect_public_demo_flow_reports(
        report,
        evidence=evidence,
        visited_reports=visited_reports,
    )


def _collect_public_demo_flow_reports(
    report: Mapping[str, Any],
    *,
    evidence: dict[str, list[dict[str, Any]]],
    visited_reports: set[Path],
) -> None:
    for flow in _dict_list(report.get("flows")):
        if flow.get("status") != "passed":
            continue
        report_json = str(flow.get("report_json") or "").strip()
        if not report_json:
            continue
        path = _resolve_path(Path(report_json))
        resolved = path.resolve()
        if resolved in visited_reports:
            continue
        visited_reports.add(resolved)
        flow_report = _load_report(path)
        if not flow_report:
            continue
        _collect_report_evidence(
            flow_report,
            source=_display_path(path),
            evidence=evidence,
            visited_reports=visited_reports,
        )


def _public_demo_is_complete(report: Mapping[str, Any]) -> bool:
    if report.get("ok") is not True or report.get("complete") is not True:
        return False
    release_level = str(report.get("release_level") or "").strip()
    return not release_level or release_level == "full_public_demo_ready"


def _public_demo_assessment(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": str(report.get("status") or ""),
        "release_level": str(report.get("release_level") or ""),
        "complete": bool(report.get("complete") is True),
        "selected_count": int(report.get("selected_count") or 0),
        "passed_count": int(report.get("passed_count") or 0),
        "required_flow_count": int(report.get("required_flow_count") or 0),
        "passed_required_flow_count": int(report.get("passed_required_flow_count") or 0),
        "missing_required_flow_ids": _string_list(report.get("missing_required_flow_ids")),
        "release_blockers": _dict_list(report.get("release_blockers")),
        "full_demo_command": FULL_PUBLIC_DEMO_COMMAND,
    }


def _public_demo_item_details(item: Mapping[str, Any]) -> dict[str, Any]:
    related = item.get("related_evidence")
    if not isinstance(related, dict):
        return {}
    for evidence_id in ("public_demo_assessment", "public_demo_selected"):
        entries = related.get(evidence_id)
        if isinstance(entries, list) and entries and isinstance(entries[0], dict):
            return dict(entries[0])
    return {}


def _add_evidence(
    evidence: dict[str, list[dict[str, Any]]],
    evidence_id: str,
    *,
    source: str,
    kind: str,
    **extra: Any,
) -> None:
    entry = {
        "source": source,
        "kind": kind,
        **{key: value for key, value in extra.items() if value not in (None, "", [], {})},
    }
    bucket = evidence.setdefault(evidence_id, [])
    if entry not in bucket:
        bucket.append(entry)


def _load_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"report must be a JSON object: {path}")
    return data


def _write_text(path: Path, value: str) -> None:
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values: Sequence[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        return []
    return [str(item) for item in values if str(item)]


def _resolve_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return ROOT / expanded


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="*", type=Path, help="RC or smoke report JSON files.")
    parser.add_argument(
        "--diagnostics-zip",
        action="append",
        default=[],
        type=Path,
        help="Redacted diagnostics zip produced by collect_release_diagnostics.py.",
    )
    parser.add_argument("--output-json", type=Path, help="Write summary JSON.")
    parser.add_argument("--output-markdown", type=Path, help="Write summary Markdown.")
    args = parser.parse_args(argv)

    try:
        summary = summarize_release_smoke(
            args.reports,
            diagnostics_zips=args.diagnostics_zip,
        )
        if args.output_json is not None:
            _write_json(args.output_json, summary)
        if args.output_markdown is not None:
            _write_text(args.output_markdown, render_markdown(summary))
        if args.output_json is None and args.output_markdown is None:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"release smoke summary: failed\n- {exc}", file=sys.stderr)
        return 1
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
