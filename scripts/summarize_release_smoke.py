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
from scripts.run_public_demo_smokes import demo_flows  # noqa: E402


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
    "--include-ui "
    "--output-json tmp/public-demo-smokes-full.json "
    "--output-markdown tmp/public-demo-smokes-full.md"
)
PUBLIC_DEMO_CAPABILITY_FLOW_MAP: dict[str, str] = {
    "source_data_analysis_artifact": "data_analysis_artifact",
    "source_browser_research_artifact": "browser_research_artifact",
    "source_desktop_planner_discovery": "desktop_planner_discovery",
    "source_agent_entrypoint_desktop_execution": "agent_entrypoint_desktop_execution",
    "source_agent_entrypoint_data_analysis": "agent_entrypoint_data_analysis",
    "source_agent_studio_planner_orchestration": "agent_studio_planner_orchestration",
    "source_real_desktop_discovery": "real_desktop_discovery",
    "source_approval_resume_timeline": "approval_resume",
    "source_yachiyo_route_approval": "yachiyo_route_approval",
    "source_group_run_timeline": "group_run",
    "source_real_desktop_app_open": "real_desktop_app_open",
    "source_real_desktop_ui_inspection": "real_desktop_ui_inspection",
    "source_real_desktop_interaction": "real_desktop_interaction",
}
PUBLIC_DEMO_FLOW_FLAGS: dict[str, str] = {
    "real_desktop_app_open": "--include-real-desktop-open",
    "real_desktop_ui_inspection": "--include-real-desktop-ui-inspection",
    "real_desktop_interaction": "--include-real-desktop-interaction",
    "workflow_provider": "--include-provider-workflow",
    "studio_replay_ui": "--include-ui",
    "workflow_ui": "--include-ui",
}
ELECTRON_UI_PUBLIC_DEMO_FLOW_MAP: dict[str, str] = {
    "scripts/smoke_agent_run_detail_ui.mjs": "studio_replay_ui",
    "scripts/smoke_workflow_save_run_ui.mjs": "workflow_ui",
}
PROVIDER_WORKFLOW_PUBLIC_DEMO_FLOW_ID = "workflow_provider"
PROVIDER_WORKFLOW_CONTRACT_DEMO_FLOW_ID = "native_provider_contract"
PROVIDER_WORKFLOW_PROVIDER_CHECK_LABEL = "native_workflow_full_chain"
PROVIDER_WORKFLOW_CONTRACT_CHECK_LABEL = "native_workflow_full_chain_contract"
PROVIDER_WORKFLOW_SMOKE_MODE = "native_workflow_full_chain_smoke"
PROVIDER_WORKFLOW_PROVIDER_EVIDENCE_KIND = "provider_workflow_full_chain"
PROVIDER_WORKFLOW_CONTRACT_EVIDENCE_KIND = "provider_contract_full_chain"
NATIVE_PROVIDER_CONTRACT_SMOKE_MODE = "native_provider_contract_smoke"
OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE = "oha_desktop_agent_release_smoke"
OHA_DESKTOP_AGENT_SECTION_EVIDENCE: dict[str, str] = {
    "deepagent_core": "oha_deepagent_core",
    "shared_daily_surfaces": "oha_chat_bubble_live2d_runtime",
    "desktop_executor_before_model": "oha_desktop_executor_before_model",
    "legacy_facade_planner_ownership": "oha_legacy_facade_planner_ownership",
    "capability_planner_tool_parity": "oha_capability_planner_tool_parity",
    "data_analysis_artifacts": "oha_data_analysis_artifacts",
    "agent_studio_orchestration": "oha_agent_studio_orchestration",
    "group_run_timeline": "oha_group_run_timeline",
    "workflow_run_timeline": "oha_workflow_run_timeline",
    "approval_policy_gate": "oha_approval_policy_gate",
    "studio_tool_catalog": "oha_studio_tool_catalog",
    "isolated_desktop_provider": "oha_isolated_desktop_provider",
}
SMOKE_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "id": "oha_desktop_agent_product",
        "label": "Oha desktop-agent product smoke covers the new Core, Executor, and Studio path",
        "required": (
            OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE,
            "oha_isolated_desktop_provider",
            "oha_real_virtual_desktop_backend",
        ),
        "related": (
            *tuple(OHA_DESKTOP_AGENT_SECTION_EVIDENCE.values()),
            "oha_isolated_desktop_backend_boundary",
        ),
        "next_action": (
            "python scripts/smoke_oha_desktop_agent_release.py "
            "--run-isolated-provider-smoke "
            "--use-configured-virtual-desktop-provider "
            "--provider-manifest /path/to/provider-manifest.json "
            "--report-json tmp/oha-desktop-agent-release-smoke.json"
        ),
    },
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
        "label": "Workflow has source entrypoint and provider-contract orchestration evidence",
        "required": (
            "source_agent_entrypoint_data_analysis",
            "advanced_workflow_orchestration",
        ),
        "required_evidence_kinds": {
            "advanced_workflow_orchestration": (
                PROVIDER_WORKFLOW_PROVIDER_EVIDENCE_KIND,
                PROVIDER_WORKFLOW_CONTRACT_EVIDENCE_KIND,
            ),
        },
        "next_action": (
            "python scripts/verify_release_candidate.py --source-only "
            "--report-json tmp/rc-verification-source-capabilities.json"
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
    _collect_public_demo_capability_projection(evidence)
    _collect_aggregate_public_demo_evidence(evidence)

    items = [_item_status(item, evidence) for item in SMOKE_ITEMS]
    passed_count = sum(1 for item in items if item["status"] == "passed")
    missing = [item for item in items if item["status"] != "passed"]
    public_demo = _public_demo_summary(evidence)
    return {
        "ok": not missing,
        "status": "passed" if not missing else "incomplete",
        "item_count": len(items),
        "passed_count": passed_count,
        "missing_count": len(missing),
        "missing_item_ids": [item["id"] for item in missing],
        "items": items,
        "public_demo": public_demo,
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
    ]
    public_demo = _dict(summary.get("public_demo"))
    if public_demo:
        passed_flows = int(public_demo.get("passed_required_flow_count") or 0)
        required_flows = int(public_demo.get("required_flow_count") or 0)
        release_level = str(public_demo.get("release_level") or "")
        lines.append(
            f"Public demo: {passed_flows}/{required_flows} required flows"
            + (f" (`{release_level}`)" if release_level else "")
        )
        missing_flows = _string_list(public_demo.get("missing_required_flow_ids"))
        if missing_flows:
            lines.append(
                "Missing demo flows: "
                + ", ".join(f"`{value}`" for value in missing_flows)
            )
    lines.extend(["", "## Checklist", ""])
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
    _collect_electron_ui_public_demo_evidence(report, source=source, evidence=evidence)
    _collect_provider_workflow_public_demo_evidence(
        report,
        source=source,
        evidence=evidence,
    )
    _collect_oha_desktop_agent_release_evidence(
        report,
        source=source,
        evidence=evidence,
    )
    electron_ui_smoke = report.get("electron_ui_smoke")
    if isinstance(electron_ui_smoke, dict):
        _collect_electron_ui_public_demo_evidence(
            electron_ui_smoke,
            source=source,
            evidence=evidence,
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
    required_kinds = _required_evidence_kinds(item)
    valid_required_evidence = {
        value: _matching_evidence_entries(evidence.get(value, []), required_kinds.get(value, ()))
        for value in required
    }
    present = [value for value in required if valid_required_evidence.get(value)]
    missing = [value for value in required if not valid_required_evidence.get(value)]
    related_present = [value for value in related if value in evidence]
    rejected = {
        value: evidence[value]
        for value in required
        if value in evidence and not valid_required_evidence.get(value)
    }
    return {
        "id": str(item["id"]),
        "label": str(item["label"]),
        "status": "passed" if not missing else "missing",
        "required_evidence_ids": list(required),
        "required_evidence_kinds": {
            key: list(value)
            for key, value in required_kinds.items()
            if key in required
        },
        "present_evidence_ids": present,
        "missing_evidence_ids": missing,
        "related_evidence_ids": related_present,
        "evidence": {
            evidence_id: valid_required_evidence[evidence_id]
            for evidence_id in present
        },
        "rejected_evidence": rejected,
        "related_evidence": {
            evidence_id: evidence[evidence_id]
            for evidence_id in related_present
        },
        "release_blockers": _item_release_blockers(
            str(item["id"]),
            missing,
            evidence,
        ),
        "next_action": str(item.get("next_action") or ""),
    }


def _required_evidence_kinds(item: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    raw = item.get("required_evidence_kinds")
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for evidence_id, kinds in raw.items():
        clean_id = str(evidence_id or "").strip()
        if not clean_id:
            continue
        if isinstance(kinds, str):
            clean_kinds = (kinds.strip(),)
        else:
            clean_kinds = tuple(
                str(kind or "").strip()
                for kind in (kinds if isinstance(kinds, Sequence) else ())
                if str(kind or "").strip()
            )
        if clean_kinds:
            result[clean_id] = clean_kinds
    return result


def _matching_evidence_entries(
    entries: Sequence[Mapping[str, Any]],
    required_kinds: Sequence[str],
) -> list[dict[str, Any]]:
    clean_kinds = {str(kind or "").strip() for kind in required_kinds if str(kind or "").strip()}
    if not clean_kinds:
        return [dict(entry) for entry in entries if isinstance(entry, Mapping)]
    return [
        dict(entry)
        for entry in entries
        if isinstance(entry, Mapping) and str(entry.get("kind") or "").strip() in clean_kinds
    ]


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
        release_blockers = _dict_list(item.get("release_blockers"))
        if release_blockers:
            action["release_blockers"] = release_blockers
        if item.get("id") == "public_demo":
            demo_details = _public_demo_item_details(item)
            if demo_details:
                command = _public_demo_command_for_missing_flows(
                    _string_list(demo_details.get("missing_required_flow_ids")),
                    _dict_list(demo_details.get("release_blockers")),
                )
                action.update(
                    {
                        key: value
                        for key, value in demo_details.items()
                        if key in {"release_level", "missing_required_flow_ids", "release_blockers"}
                    }
                )
                if command:
                    action["command"] = command
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
    flows = _dict_list(report.get("flows"))
    required_flow_ids = _string_list(report.get("required_flow_ids")) or [
        str(flow.get("id") or "")
        for flow in flows
        if flow.get("id") and flow.get("release_required") is not False
    ]
    passed_flow_ids = [
        str(flow.get("id") or "")
        for flow in flows
        if flow.get("id") and flow.get("status") == "passed"
    ]
    passed_required_flow_ids = _string_list(
        report.get("passed_required_flow_ids")
    ) or [flow_id for flow_id in passed_flow_ids if flow_id in required_flow_ids]
    return {
        "status": str(report.get("status") or ""),
        "release_level": str(report.get("release_level") or ""),
        "complete": bool(report.get("complete") is True),
        "selected_count": int(report.get("selected_count") or 0),
        "passed_count": int(report.get("passed_count") or 0),
        "required_flow_count": int(report.get("required_flow_count") or 0),
        "passed_required_flow_count": int(report.get("passed_required_flow_count") or 0),
        "required_flow_ids": required_flow_ids,
        "passed_required_flow_ids": passed_required_flow_ids,
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
            aggregate = next(
                (
                    dict(entry)
                    for entry in entries
                    if isinstance(entry, dict)
                    and entry.get("kind") == "public_demo_aggregate"
                ),
                None,
            )
            if aggregate is not None:
                return aggregate
            return dict(entries[0])
    return {}


def _public_demo_command_for_missing_flows(
    missing_flow_ids: Sequence[str],
    release_blockers: Sequence[Mapping[str, Any]],
) -> str:
    flags: list[str] = []
    missing = [flow_id for flow_id in missing_flow_ids if flow_id]
    blocker_by_id = {
        str(blocker.get("id") or "").strip(): blocker
        for blocker in release_blockers
        if str(blocker.get("id") or "").strip()
    }
    unknown_missing = False
    for flow_id in missing:
        blocker = blocker_by_id.get(flow_id, {})
        flag = str(blocker.get("opt_in_flag") or "").strip()
        if not flag:
            flag = PUBLIC_DEMO_FLOW_FLAGS.get(flow_id, "")
        if not flag:
            unknown_missing = True
            continue
        if flag not in flags:
            flags.append(flag)
    if not flags or unknown_missing:
        return FULL_PUBLIC_DEMO_COMMAND
    return (
        "python scripts/run_public_demo_smokes.py "
        + " ".join(flags)
        + " --output-json tmp/public-demo-smokes-missing.json "
        + "--output-markdown tmp/public-demo-smokes-missing.md"
    )


def _more_informative_blocker(
    existing: Mapping[str, Any] | None,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    if existing is None:
        return dict(candidate)
    if _blocker_detail_score(candidate) > _blocker_detail_score(existing):
        return dict(candidate)
    return dict(existing)


def _blocker_detail_score(blocker: Mapping[str, Any]) -> int:
    score = 0
    reason = str(blocker.get("reason") or "").strip()
    if reason and reason not in {
        "required public demo flow has not passed",
        "not collected",
    }:
        score += 2
    evidence_summary = _dict(blocker.get("evidence_summary"))
    for key in (
        "blocking_condition",
        "blocking_conditions",
        "missing_env",
        "recovery_hints",
        "recommended_tools",
        "checks",
        "error",
    ):
        if evidence_summary.get(key) not in (None, "", [], {}):
            score += 3
    if blocker.get("command"):
        score += 1
    if blocker.get("status") == "failed":
        score += 1
    return score


def _collect_aggregate_public_demo_evidence(
    evidence: dict[str, list[dict[str, Any]]],
) -> None:
    assessments = [
        entry
        for entry in evidence.get("public_demo_assessment", [])
        if isinstance(entry, dict)
    ]
    if len(assessments) < 2:
        return
    required_flow_ids = _canonical_public_demo_flow_ids()
    passed_flow_ids: list[str] = []
    blocker_by_id: dict[str, dict[str, Any]] = {}
    sources: list[str] = []
    for assessment in assessments:
        source = str(assessment.get("source") or "").strip()
        if source and source not in sources:
            sources.append(source)
        for flow_id in _string_list(assessment.get("required_flow_ids")):
            if flow_id not in required_flow_ids:
                required_flow_ids.append(flow_id)
        for flow_id in _string_list(assessment.get("passed_required_flow_ids")):
            if flow_id not in passed_flow_ids:
                passed_flow_ids.append(flow_id)
        for blocker in _dict_list(assessment.get("release_blockers")):
            blocker_id = str(blocker.get("id") or "").strip()
            if blocker_id:
                blocker_by_id[blocker_id] = _more_informative_blocker(
                    blocker_by_id.get(blocker_id),
                    blocker,
                )
    if not required_flow_ids:
        return
    missing_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id not in passed_flow_ids
    ]
    passed_required_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id in passed_flow_ids
    ]
    release_blockers = [
        blocker_by_id.get(flow_id)
        or {
            "id": flow_id,
            "status": "missing",
            "reason": "required public demo flow has not passed",
        }
        for flow_id in missing_flow_ids
    ]
    blocked = any(str(blocker.get("status") or "") == "failed" for blocker in release_blockers)
    complete = not missing_flow_ids
    release_level = (
        "full_public_demo_ready"
        if complete
        else "blocked"
        if blocked
        else "partial_demo_ready"
    )
    aggregate = {
        "source": ", ".join(sources),
        "kind": "public_demo_aggregate",
        "status": "passed" if complete else "partial",
        "release_level": release_level,
        "complete": complete,
        "selected_count": len(passed_flow_ids),
        "passed_count": len(passed_flow_ids),
        "required_flow_count": len(required_flow_ids),
        "passed_required_flow_count": len(passed_required_flow_ids),
        "required_flow_ids": required_flow_ids,
        "passed_required_flow_ids": passed_required_flow_ids,
        "missing_required_flow_ids": missing_flow_ids,
        "release_blockers": release_blockers,
        "full_demo_command": FULL_PUBLIC_DEMO_COMMAND,
    }
    evidence.setdefault("public_demo_assessment", []).append(aggregate)
    if passed_flow_ids:
        evidence.setdefault("public_demo_selected", []).append(aggregate)
    if complete:
        evidence.setdefault("public_demo_complete", []).append(aggregate)


def _public_demo_summary(evidence: Mapping[str, Any]) -> dict[str, Any]:
    assessments = _dict_list(evidence.get("public_demo_assessment"))
    if not assessments:
        return {}
    aggregates = [
        assessment
        for assessment in assessments
        if str(assessment.get("kind") or "") == "public_demo_aggregate"
    ]
    candidates = aggregates or assessments
    candidate = max(
        candidates,
        key=lambda assessment: (
            assessment.get("complete") is True,
            int(assessment.get("passed_required_flow_count") or 0),
            int(assessment.get("required_flow_count") or 0),
        ),
    )
    missing_flow_ids = _string_list(candidate.get("missing_required_flow_ids"))
    return {
        "source": str(candidate.get("source") or ""),
        "kind": str(candidate.get("kind") or ""),
        "status": str(candidate.get("status") or ""),
        "release_level": str(candidate.get("release_level") or ""),
        "complete": bool(candidate.get("complete") is True),
        "selected_count": int(candidate.get("selected_count") or 0),
        "passed_count": int(candidate.get("passed_count") or 0),
        "required_flow_count": int(candidate.get("required_flow_count") or 0),
        "passed_required_flow_count": int(
            candidate.get("passed_required_flow_count") or 0
        ),
        "remaining_required_flow_count": len(missing_flow_ids),
        "required_flow_ids": _string_list(candidate.get("required_flow_ids")),
        "passed_required_flow_ids": _string_list(
            candidate.get("passed_required_flow_ids")
        ),
        "missing_required_flow_ids": missing_flow_ids,
        "release_blockers": _dict_list(candidate.get("release_blockers")),
        "full_demo_command": str(
            candidate.get("full_demo_command") or FULL_PUBLIC_DEMO_COMMAND
        ),
    }


def _collect_public_demo_capability_projection(
    evidence: dict[str, list[dict[str, Any]]],
) -> None:
    required_flow_ids = _canonical_public_demo_flow_ids()
    passed_flow_ids: list[str] = []
    sources: list[str] = []
    for capability_id, flow_id in PUBLIC_DEMO_CAPABILITY_FLOW_MAP.items():
        entries = evidence.get(capability_id)
        if not entries:
            continue
        if flow_id not in passed_flow_ids:
            passed_flow_ids.append(flow_id)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source = str(entry.get("source") or "").strip()
            if source and source not in sources:
                sources.append(source)
    if not passed_flow_ids:
        return
    missing_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id not in passed_flow_ids
    ]
    passed_required_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id in passed_flow_ids
    ]
    complete = not missing_flow_ids
    projection = {
        "source": ", ".join(sources),
        "kind": "rc_capability_public_demo_projection",
        "status": "passed" if complete else "partial",
        "release_level": "full_public_demo_ready" if complete else "partial_demo_ready",
        "complete": complete,
        "selected_count": len(passed_flow_ids),
        "passed_count": len(passed_flow_ids),
        "required_flow_count": len(required_flow_ids),
        "passed_required_flow_count": len(passed_required_flow_ids),
        "required_flow_ids": required_flow_ids,
        "passed_required_flow_ids": passed_required_flow_ids,
        "missing_required_flow_ids": missing_flow_ids,
        "release_blockers": [
            {
                "id": flow_id,
                "status": "missing",
                "reason": "public demo flow is not covered by passed RC capability evidence",
            }
            for flow_id in missing_flow_ids
        ],
        "full_demo_command": FULL_PUBLIC_DEMO_COMMAND,
        "capability_flow_map": {
            capability_id: flow_id
            for capability_id, flow_id in PUBLIC_DEMO_CAPABILITY_FLOW_MAP.items()
            if flow_id in passed_flow_ids
        },
    }
    evidence.setdefault("public_demo_assessment", []).append(projection)
    evidence.setdefault("public_demo_selected", []).append(projection)
    if complete:
        evidence.setdefault("public_demo_complete", []).append(projection)


def _collect_electron_ui_public_demo_evidence(
    report: Mapping[str, Any],
    *,
    source: str,
    evidence: dict[str, list[dict[str, Any]]],
) -> None:
    if report.get("ok") is not True and report.get("status") != "passed":
        return
    passed_flow_ids: list[str] = []
    script_flow_map: dict[str, str] = {}
    for script in _dict_list(report.get("scripts")):
        script_path = _normalized_script_path(script.get("script"))
        if not script_path or script.get("exit_code") not in (0, "0"):
            continue
        flow_id = ELECTRON_UI_PUBLIC_DEMO_FLOW_MAP.get(script_path)
        if not flow_id:
            continue
        if flow_id not in passed_flow_ids:
            passed_flow_ids.append(flow_id)
        script_flow_map[script_path] = flow_id
    if not passed_flow_ids:
        return
    required_flow_ids = _canonical_public_demo_flow_ids()
    missing_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id not in passed_flow_ids
    ]
    passed_required_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id in passed_flow_ids
    ]
    complete = not missing_flow_ids
    projection = {
        "source": source,
        "kind": "electron_ui_public_demo_projection",
        "status": "passed" if complete else "partial",
        "release_level": "full_public_demo_ready" if complete else "partial_demo_ready",
        "complete": complete,
        "selected_count": len(passed_flow_ids),
        "passed_count": len(passed_flow_ids),
        "required_flow_count": len(required_flow_ids),
        "passed_required_flow_count": len(passed_required_flow_ids),
        "required_flow_ids": required_flow_ids,
        "passed_required_flow_ids": passed_required_flow_ids,
        "missing_required_flow_ids": missing_flow_ids,
        "release_blockers": [
            {
                "id": flow_id,
                "status": "missing",
                "reason": "public demo flow is not covered by passed Electron UI smoke evidence",
            }
            for flow_id in missing_flow_ids
        ],
        "full_demo_command": FULL_PUBLIC_DEMO_COMMAND,
        "script_flow_map": script_flow_map,
    }
    evidence.setdefault("public_demo_assessment", []).append(projection)
    evidence.setdefault("public_demo_selected", []).append(projection)
    if complete:
        evidence.setdefault("public_demo_complete", []).append(projection)


def _collect_provider_workflow_public_demo_evidence(
    report: Mapping[str, Any],
    *,
    source: str,
    evidence: dict[str, list[dict[str, Any]]],
) -> None:
    provider_evidence = _provider_workflow_public_demo_evidence(report)
    if not provider_evidence:
        return
    _add_provider_workflow_release_evidence(
        source=source,
        evidence=evidence,
        provider_evidence=provider_evidence,
    )
    required_flow_ids = _canonical_public_demo_flow_ids()
    flow_id = str(
        provider_evidence.get("public_demo_flow_id")
        or PROVIDER_WORKFLOW_PUBLIC_DEMO_FLOW_ID
    )
    passed_flow_ids = [flow_id]
    missing_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id not in passed_flow_ids
    ]
    passed_required_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id in passed_flow_ids
    ]
    complete = not missing_flow_ids
    projection = {
        "source": source,
        "kind": "provider_workflow_public_demo_projection",
        "status": "passed" if complete else "partial",
        "release_level": "full_public_demo_ready" if complete else "partial_demo_ready",
        "complete": complete,
        "selected_count": len(passed_flow_ids),
        "passed_count": len(passed_flow_ids),
        "required_flow_count": len(required_flow_ids),
        "passed_required_flow_count": len(passed_required_flow_ids),
        "required_flow_ids": required_flow_ids,
        "passed_required_flow_ids": passed_required_flow_ids,
        "missing_required_flow_ids": missing_flow_ids,
        "release_blockers": [
            {
                "id": flow_id,
                "status": "missing",
                "reason": "public demo flow is not covered by passed provider Workflow evidence",
            }
            for flow_id in missing_flow_ids
        ],
        "full_demo_command": FULL_PUBLIC_DEMO_COMMAND,
        "provider_workflow_evidence": provider_evidence,
    }
    evidence.setdefault("public_demo_assessment", []).append(projection)
    evidence.setdefault("public_demo_selected", []).append(projection)
    if complete:
        evidence.setdefault("public_demo_complete", []).append(projection)


def _add_provider_workflow_release_evidence(
    *,
    source: str,
    evidence: dict[str, list[dict[str, Any]]],
    provider_evidence: Mapping[str, Any],
) -> None:
    evidence_kind = str(
        provider_evidence.get("release_evidence_kind")
        or PROVIDER_WORKFLOW_PROVIDER_EVIDENCE_KIND
    )
    for evidence_id in ("advanced_workflow_orchestration", "workflow_budget_boundary"):
        _add_evidence(
            evidence,
            evidence_id,
            source=source,
            kind=evidence_kind,
            provider_workflow_evidence=dict(provider_evidence),
        )


def _provider_workflow_public_demo_evidence(report: Mapping[str, Any]) -> dict[str, Any]:
    provider_smoke = report.get("provider_smoke")
    if isinstance(provider_smoke, dict) and provider_smoke.get("status") == "passed":
        for check in _dict_list(provider_smoke.get("checks")):
            label = str(check.get("label") or "").strip()
            if label != PROVIDER_WORKFLOW_PROVIDER_CHECK_LABEL:
                continue
            if check.get("exit_code") not in (0, "0"):
                continue
            summary = check.get("summary")
            if not isinstance(summary, dict) or summary.get("ok") is not True:
                continue
            return {
                "source_kind": "provider_smoke",
                "check_label": label,
                "exit_code": check.get("exit_code"),
                "summary_ok": True,
                "release_evidence_kind": PROVIDER_WORKFLOW_PROVIDER_EVIDENCE_KIND,
                "public_demo_flow_id": PROVIDER_WORKFLOW_PUBLIC_DEMO_FLOW_ID,
            }
    if (
        report.get("mode") == PROVIDER_WORKFLOW_SMOKE_MODE
        and report.get("ok") is True
        and report.get("skipped") is not True
    ):
        return {
            "source_kind": PROVIDER_WORKFLOW_SMOKE_MODE,
            "mode": PROVIDER_WORKFLOW_SMOKE_MODE,
            "summary_ok": True,
            "release_evidence_kind": PROVIDER_WORKFLOW_PROVIDER_EVIDENCE_KIND,
            "public_demo_flow_id": PROVIDER_WORKFLOW_PUBLIC_DEMO_FLOW_ID,
        }
    contract_evidence = _provider_workflow_contract_evidence(report)
    if contract_evidence:
        return contract_evidence
    return {}


def _provider_workflow_contract_evidence(report: Mapping[str, Any]) -> dict[str, Any]:
    contract_report = _native_provider_contract_report(report)
    if not contract_report:
        return {}
    for check in _dict_list(contract_report.get("checks")):
        label = str(check.get("label") or "").strip()
        if label != PROVIDER_WORKFLOW_CONTRACT_CHECK_LABEL:
            continue
        summary = check.get("summary")
        if not isinstance(summary, dict) or summary.get("ok") is not True:
            continue
        nested = {
            str(item.get("name") or "").strip(): item
            for item in _dict_list(summary.get("checks"))
            if str(item.get("name") or "").strip()
        }
        if not all(
            _dict(nested.get(name)).get("ok") is True
            for name in ("advanced_workflow_orchestration", "workflow_budget_boundary")
        ):
            continue
        return {
            "source_kind": NATIVE_PROVIDER_CONTRACT_SMOKE_MODE,
            "check_label": label,
            "summary_ok": True,
            "release_evidence_kind": PROVIDER_WORKFLOW_CONTRACT_EVIDENCE_KIND,
            "public_demo_flow_id": PROVIDER_WORKFLOW_CONTRACT_DEMO_FLOW_ID,
            "provider": str(contract_report.get("provider") or ""),
        }
    return {}


def _native_provider_contract_report(report: Mapping[str, Any]) -> Mapping[str, Any]:
    if report.get("mode") == NATIVE_PROVIDER_CONTRACT_SMOKE_MODE and report.get("ok") is True:
        return report
    section = report.get(NATIVE_PROVIDER_CONTRACT_SMOKE_MODE)
    if not isinstance(section, Mapping) or section.get("status") != "passed":
        return {}
    evidence = section.get("evidence")
    if isinstance(evidence, Mapping) and evidence.get("ok") is True:
        return evidence
    return {}


def _collect_oha_desktop_agent_release_evidence(
    report: Mapping[str, Any],
    *,
    source: str,
    evidence: dict[str, list[dict[str, Any]]],
) -> None:
    if report.get("mode") != OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE:
        return
    backend = report.get("isolated_provider_backend")
    if isinstance(backend, Mapping):
        _collect_oha_desktop_backend_evidence(
            {"id": "isolated_desktop_provider", "report": backend},
            source=source,
            evidence=evidence,
        )
    if report.get("ok") is not True:
        return
    for section in _dict_list(report.get("sections")):
        if section.get("ok") is not True:
            continue
        section_id = str(section.get("id") or "").strip()
        evidence_id = OHA_DESKTOP_AGENT_SECTION_EVIDENCE.get(section_id)
        if not evidence_id:
            continue
        _add_evidence(
            evidence,
            evidence_id,
            source=source,
            kind="oha_desktop_agent_release_section",
            section_id=section_id,
            mode=str(section.get("mode") or ""),
            objective=str(section.get("objective") or ""),
        )
        if section_id == "isolated_desktop_provider":
            _collect_oha_desktop_backend_evidence(
                section,
                source=source,
                evidence=evidence,
            )


def _collect_oha_desktop_backend_evidence(
    section: Mapping[str, Any],
    *,
    source: str,
    evidence: dict[str, list[dict[str, Any]]],
) -> None:
    report = section.get("report") if isinstance(section.get("report"), Mapping) else {}
    if not report:
        return
    backend_kind = str(report.get("desktop_backend_kind") or "").strip()
    backend_is_loopback = report.get("desktop_backend_is_loopback")
    backend_ready = report.get("desktop_backend_ready_for_public_release")
    requires_real_backend = report.get("requires_real_virtual_desktop_backend")
    provider_contract = (
        report.get("provider_contract")
        if isinstance(report.get("provider_contract"), dict)
        else {}
    )
    provider_contract_ok = (
        report.get("provider_contract_ok")
        if "provider_contract_ok" in report
        else provider_contract.get("ok")
    )
    provider_contract_version = str(
        report.get("provider_contract_version")
        or provider_contract.get("contract_version")
        or ""
    )
    provider_contract_blockers = _string_list(
        report.get("provider_contract_blocking_conditions")
        or provider_contract.get("blocking_conditions")
    )
    if not backend_kind and backend_ready is None and requires_real_backend is None:
        return
    backend_payload = {
        "desktop_backend_kind": backend_kind,
        "desktop_backend_is_loopback": backend_is_loopback,
        "desktop_backend_ready_for_public_release": backend_ready,
        "requires_real_virtual_desktop_backend": requires_real_backend,
        "provider_contract_ok": provider_contract_ok,
        "provider_contract_version": provider_contract_version,
        "provider_contract_blocking_conditions": provider_contract_blockers,
    }
    _add_evidence(
        evidence,
        "oha_isolated_desktop_backend_boundary",
        source=source,
        kind="oha_desktop_agent_release_section",
        section_id=str(section.get("id") or ""),
        **backend_payload,
    )
    if (
        backend_ready is True
        and backend_is_loopback is not True
        and provider_contract_ok is not False
    ):
        _add_evidence(
            evidence,
            "oha_real_virtual_desktop_backend",
            source=source,
            kind="oha_desktop_backend",
            **backend_payload,
        )


def _item_release_blockers(
    item_id: str,
    missing: Sequence[str],
    evidence: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if (
        item_id != "oha_desktop_agent_product"
        or "oha_real_virtual_desktop_backend" not in missing
    ):
        return []
    boundary = _dict_list(evidence.get("oha_isolated_desktop_backend_boundary"))
    latest = boundary[-1] if boundary else {}
    return [
        {
            "id": "oha_real_virtual_desktop_backend",
            "status": "missing",
            "reason": "real_virtual_desktop_backend_required",
            "evidence_summary": {
                "blocking_condition": "real_virtual_desktop_backend_required",
                "desktop_backend_kind": str(
                    latest.get("desktop_backend_kind") or ""
                ),
                "desktop_backend_is_loopback": latest.get(
                    "desktop_backend_is_loopback"
                ),
                "desktop_backend_ready_for_public_release": latest.get(
                    "desktop_backend_ready_for_public_release"
                ),
                "requires_real_virtual_desktop_backend": latest.get(
                    "requires_real_virtual_desktop_backend"
                ),
                "provider_contract_ok": latest.get("provider_contract_ok"),
                "provider_contract_version": latest.get("provider_contract_version"),
                "provider_contract_blocking_conditions": _string_list(
                    latest.get("provider_contract_blocking_conditions")
                ),
            },
        }
    ]


def _canonical_public_demo_flow_ids() -> list[str]:
    return [
        flow.id
        for flow in demo_flows(Path("tmp/public-demo-flow-catalog"))
        if flow.release_required
    ]


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


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values: Sequence[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        return []
    return [str(item) for item in values if str(item)]


def _normalized_script_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


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
