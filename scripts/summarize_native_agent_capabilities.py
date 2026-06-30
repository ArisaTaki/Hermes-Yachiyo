#!/usr/bin/env python3
"""Build a Native Agent capability matrix from release-candidate reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]


CAPABILITY_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "id": "source_data_analysis_artifact",
        "label": "Source data analysis artifact pipeline",
        "evidence": "data_analysis_artifact_smoke",
    },
    {
        "id": "source_browser_research_artifact",
        "label": "Browser research and artifact planner pipeline",
        "evidence": "browser_planner_artifact_smoke",
    },
    {
        "id": "source_desktop_planner_discovery",
        "label": "Runtime planner desktop discovery and operation coverage",
        "evidence": "desktop_planner_discovery_smoke",
    },
    {
        "id": "source_real_desktop_discovery",
        "label": "Real macOS desktop app discovery",
        "evidence": "real_desktop_discovery_smoke",
    },
    {
        "id": "source_real_desktop_app_open",
        "label": "Real macOS app open and verification",
        "evidence": "real_desktop_app_open_smoke",
    },
    {
        "id": "source_real_desktop_ui_inspection",
        "label": "Real macOS UI inspection",
        "evidence": "real_desktop_ui_inspection_smoke",
    },
    {
        "id": "source_real_desktop_interaction",
        "label": "Real macOS type, click, and verify loop",
        "evidence": "real_desktop_interaction_smoke",
    },
    {
        "id": "source_planner_runtime_tool_parity",
        "label": "Planner-to-runtime tool parity",
        "evidence": "planner_runtime_tool_parity_smoke",
    },
    {
        "id": "source_media_playback_chain",
        "label": "Media playback planning chain",
        "evidence": "media_playback_chain_smoke",
    },
    {
        "id": "source_agent_entrypoint_desktop_execution",
        "label": "Chat and Agent desktop execution entrypoints",
        "evidence": "agent_entrypoint_desktop_execution_smoke",
    },
    {
        "id": "source_agent_entrypoint_data_analysis",
        "label": "Chat, Agent Studio, and Workflow data analysis entrypoints",
        "evidence": "agent_entrypoint_data_analysis_smoke",
    },
    {
        "id": "source_approval_policy_gate",
        "label": "Approval and policy gate coverage",
        "evidence": "approval_policy_gate_smoke",
    },
    {
        "id": "source_approval_resume_timeline",
        "label": "Approval resume timeline projection",
        "evidence": "approval_resume_timeline_smoke",
    },
    {
        "id": "source_runtime_approval_resume",
        "label": "Runtime approval resume execution",
        "evidence": "runtime_approval_resume_smoke",
    },
    {
        "id": "source_yachiyo_route_approval",
        "label": "Yachiyo route approval API flow",
        "evidence": "yachiyo_route_approval_smoke",
    },
    {
        "id": "source_group_run_timeline",
        "label": "Group run timeline observability",
        "evidence": "group_run_timeline_smoke",
    },
    {
        "id": "provider_text_stream",
        "label": "Provider text streaming",
        "evidence": "provider_smoke.checks[text_stream].summary",
    },
    {
        "id": "provider_tool_call_stream",
        "label": "Provider tool-call streaming and follow-up",
        "evidence": "provider_smoke.checks[tool_call_stream].summary",
    },
    {
        "id": "model_profile_readiness",
        "label": "Model profile readiness without credential exposure",
        "evidence": "native_agent_full_chain:model_profile_readiness",
    },
    {
        "id": "agent_workspace_read",
        "label": "Agent workspace read tool use",
        "evidence": "native_agent_full_chain:agent_workspace_read",
    },
    {
        "id": "agent_artifact_write",
        "label": "Agent artifact write tool use",
        "evidence": "native_agent_full_chain:agent_artifact_write",
    },
    {
        "id": "agent_multi_tool_pipeline",
        "label": "Sequential multi-tool Agent pipeline",
        "evidence": "native_agent_full_chain:agent_multi_tool_pipeline",
    },
    {
        "id": "workflow_child_agent_artifact",
        "label": "Workflow child Agent artifact handoff",
        "evidence": "native_agent_full_chain:workflow_child_agent_artifact",
    },
    {
        "id": "terminal_approval_resume",
        "label": "Terminal approval and idempotent resume",
        "evidence": "native_agent_full_chain:terminal_approval_resume",
    },
    {
        "id": "main_chat_model_loop",
        "label": "Main chat model loop integration",
        "evidence": "native_agent_full_chain:main_chat_model_loop",
    },
    {
        "id": "advanced_workflow_orchestration",
        "label": "Advanced Workflow orchestration",
        "evidence": "native_workflow_full_chain:advanced_workflow_orchestration",
    },
    {
        "id": "workflow_budget_boundary",
        "label": "Workflow budget boundary failure",
        "evidence": "native_workflow_full_chain:workflow_budget_boundary",
    },
    {
        "id": "packaged_backend_bridge_identity",
        "label": "Packaged backend Bridge identity",
        "evidence": "packaged_backend_bridge_smoke",
    },
    {
        "id": "packaged_app_bridge_isolation",
        "label": "Packaged app Bridge isolation",
        "evidence": "dmg_app_smoke",
    },
)

SOURCE_SECTION_CAPABILITIES: dict[str, str] = {
    "source_data_analysis_artifact": "data_analysis_artifact_smoke",
    "source_browser_research_artifact": "browser_planner_artifact_smoke",
    "source_desktop_planner_discovery": "desktop_planner_discovery_smoke",
    "source_real_desktop_discovery": "real_desktop_discovery_smoke",
    "source_real_desktop_app_open": "real_desktop_app_open_smoke",
    "source_real_desktop_ui_inspection": "real_desktop_ui_inspection_smoke",
    "source_real_desktop_interaction": "real_desktop_interaction_smoke",
    "source_planner_runtime_tool_parity": "planner_runtime_tool_parity_smoke",
    "source_media_playback_chain": "media_playback_chain_smoke",
    "source_agent_entrypoint_desktop_execution": "agent_entrypoint_desktop_execution_smoke",
    "source_agent_entrypoint_data_analysis": "agent_entrypoint_data_analysis_smoke",
    "source_approval_policy_gate": "approval_policy_gate_smoke",
    "source_approval_resume_timeline": "approval_resume_timeline_smoke",
    "source_runtime_approval_resume": "runtime_approval_resume_smoke",
    "source_yachiyo_route_approval": "yachiyo_route_approval_smoke",
    "source_group_run_timeline": "group_run_timeline_smoke",
}


def _load_report(root: Path, path: Path) -> dict[str, Any]:
    candidate = path if path.is_absolute() else root / path
    data = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"report must be a JSON object: {path}")
    return data


def _provider_checks(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    provider_smoke = report.get("provider_smoke")
    if not isinstance(provider_smoke, dict):
        return {}
    raw_checks = provider_smoke.get("checks")
    if not isinstance(raw_checks, list):
        return {}
    checks: dict[str, dict[str, Any]] = {}
    for item in raw_checks:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if label:
            checks[label] = item
    return checks


def _nested_checks(provider_check: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(provider_check, dict):
        return {}
    summary = provider_check.get("summary")
    if not isinstance(summary, dict):
        return {}
    raw_checks = summary.get("checks")
    if not isinstance(raw_checks, list):
        return {}
    checks: dict[str, dict[str, Any]] = {}
    for item in raw_checks:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            checks[name] = item
    return checks


def _summary_ok(provider_check: dict[str, Any] | None) -> bool:
    if not isinstance(provider_check, dict) or provider_check.get("exit_code") != 0:
        return False
    summary = provider_check.get("summary")
    return isinstance(summary, dict) and summary.get("ok") is True


def _check_ok(checks: dict[str, dict[str, Any]], name: str) -> bool:
    item = checks.get(name)
    return isinstance(item, dict) and item.get("ok") is True


def _report_section_passed(report: dict[str, Any], section_name: str) -> bool:
    section = report.get(section_name)
    return isinstance(section, dict) and section.get("status") == "passed"


def _section_evidence(report: dict[str, Any], section_name: str) -> dict[str, Any]:
    section = report.get(section_name)
    if not isinstance(section, dict):
        return {}
    evidence = section.get("evidence")
    return evidence if isinstance(evidence, dict) else {}


def _section_ok(report: dict[str, Any], section_name: str) -> bool:
    evidence = _section_evidence(report, section_name)
    return (
        _report_section_passed(report, section_name)
        and evidence.get("ok") is True
        and evidence.get("skipped") is not True
    )


def _section_case_ids(evidence: dict[str, Any]) -> list[str]:
    cases = evidence.get("cases")
    if not isinstance(cases, list):
        return []
    case_ids: list[str] = []
    for item in cases:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("id") or item.get("name") or "").strip()
        if case_id:
            case_ids.append(case_id)
    return case_ids


def _source_section_summary(report: dict[str, Any], section_name: str) -> dict[str, Any]:
    section = report.get(section_name)
    section = section if isinstance(section, dict) else {}
    evidence = _section_evidence(report, section_name)
    summary: dict[str, Any] = {
        "status": section.get("status"),
        "mode": evidence.get("mode"),
        "case_count": evidence.get("case_count"),
    }
    case_ids = _section_case_ids(evidence)
    if case_ids:
        summary["case_ids"] = case_ids
    checks = evidence.get("checks")
    if isinstance(checks, dict):
        summary["checks"] = {
            str(key): value
            for key, value in checks.items()
            if isinstance(key, str) and value is not True
        }
    tool_chain = evidence.get("tool_chain")
    if isinstance(tool_chain, list):
        summary["tool_chain"] = [str(item) for item in tool_chain if str(item)]
    if evidence.get("skipped") is True:
        summary["skipped"] = True
        reason = str(evidence.get("reason") or "").strip()
        if reason:
            summary["reason"] = reason
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


def _first_summary_check(
    provider_checks: dict[str, dict[str, Any]],
    check_label: str,
) -> dict[str, Any]:
    item = provider_checks.get(check_label)
    summary = item.get("summary") if isinstance(item, dict) else None
    return summary if isinstance(summary, dict) else {}


def _capability_status(
    capability_id: str,
    *,
    report: dict[str, Any],
    provider_checks: dict[str, dict[str, Any]],
    native_agent_checks: dict[str, dict[str, Any]],
    native_workflow_checks: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    source_section = SOURCE_SECTION_CAPABILITIES.get(capability_id)
    if source_section:
        return (
            "passed" if _section_ok(report, source_section) else "missing",
            _source_section_summary(report, source_section),
        )
    if capability_id == "provider_text_stream":
        summary = _first_summary_check(provider_checks, "text_stream")
        ok = _summary_ok(provider_checks.get("text_stream"))
        return ("passed" if ok else "missing", {
            "finish_reasons": summary.get("finish_reasons", []),
            "content_chars": summary.get("content_chars"),
        })
    if capability_id == "provider_tool_call_stream":
        summary = _first_summary_check(provider_checks, "tool_call_stream")
        ok = (
            _summary_ok(provider_checks.get("tool_call_stream"))
            and int(summary.get("tool_call_count") or 0) >= 1
            and summary.get("tool_result_followup_finish_reasons") == ["stop"]
        )
        return ("passed" if ok else "missing", {
            "tool_call_count": summary.get("tool_call_count"),
            "tool_result_followup_finish_reasons": summary.get("tool_result_followup_finish_reasons", []),
        })
    if capability_id == "agent_multi_tool_pipeline":
        item = native_agent_checks.get("agent_multi_tool_pipeline", {})
        ok = (
            _check_ok(native_agent_checks, "agent_multi_tool_pipeline")
            and int(item.get("tool_call_count") or 0) >= 2
            and "pipeline-report.md" in (item.get("artifact_paths") or [])
        )
        return ("passed" if ok else "missing", {
            "tool_call_count": item.get("tool_call_count"),
            "artifact_paths": item.get("artifact_paths", []),
        })
    if capability_id in {
        "model_profile_readiness",
        "agent_workspace_read",
        "agent_artifact_write",
        "workflow_child_agent_artifact",
        "terminal_approval_resume",
        "main_chat_model_loop",
    }:
        return (
            "passed" if _check_ok(native_agent_checks, capability_id) else "missing",
            native_agent_checks.get(capability_id, {}),
        )
    if capability_id in {
        "advanced_workflow_orchestration",
        "workflow_budget_boundary",
    }:
        return (
            "passed" if _check_ok(native_workflow_checks, capability_id) else "missing",
            native_workflow_checks.get(capability_id, {}),
        )
    if capability_id == "packaged_backend_bridge_identity":
        section = report.get("packaged_backend_bridge_smoke")
        statuses = section.get("bridge_statuses") if isinstance(section, dict) else []
        return (
            "passed" if _report_section_passed(report, "packaged_backend_bridge_smoke") else "missing",
            {"bridge_statuses": statuses if isinstance(statuses, list) else []},
        )
    if capability_id == "packaged_app_bridge_isolation":
        section = report.get("dmg_app_smoke")
        statuses = section.get("bridge_statuses") if isinstance(section, dict) else []
        return (
            "passed" if _report_section_passed(report, "dmg_app_smoke") else "missing",
            {"bridge_statuses": statuses if isinstance(statuses, list) else []},
        )
    return "missing", {}


def summarize_capabilities(report: dict[str, Any]) -> dict[str, Any]:
    provider_checks = _provider_checks(report)
    native_agent_checks = _nested_checks(provider_checks.get("native_agent_full_chain"))
    native_workflow_checks = _nested_checks(provider_checks.get("native_workflow_full_chain"))
    capabilities: list[dict[str, Any]] = []
    for definition in CAPABILITY_DEFINITIONS:
        status, evidence = _capability_status(
            definition["id"],
            report=report,
            provider_checks=provider_checks,
            native_agent_checks=native_agent_checks,
            native_workflow_checks=native_workflow_checks,
        )
        capabilities.append(
            {
                **definition,
                "status": status,
                "evidence_summary": evidence,
            }
        )
    status_counts = {
        status: sum(1 for capability in capabilities if capability["status"] == status)
        for status in ("passed", "missing")
    }
    missing_ids = [
        str(capability["id"])
        for capability in capabilities
        if capability["status"] != "passed"
    ]
    return {
        "ok": not missing_ids,
        "capability_count": len(capabilities),
        "status_counts": status_counts,
        "missing_capability_ids": missing_ids,
        "capabilities": capabilities,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Release-candidate report JSON.")
    parser.add_argument("--output-json", type=Path, help="Write the capability matrix JSON.")
    args = parser.parse_args(argv)
    try:
        source = _load_report(ROOT, args.report)
        summary = summarize_capabilities(source)
        summary["source_report"] = str(args.report)
        if args.output_json is not None:
            output_path = args.output_json if args.output_json.is_absolute() else ROOT / args.output_json
            _write_report(output_path, summary)
        else:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"native Agent capability summary: failed\n- {exc}", file=sys.stderr)
        return 1
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
