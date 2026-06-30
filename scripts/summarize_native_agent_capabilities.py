#!/usr/bin/env python3
"""Build a Native Agent capability matrix from release-candidate reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.security import sanitize_sensitive_value  # noqa: E402


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
        "id": "source_agent_studio_planner_orchestration",
        "label": "Agent Studio planner orchestration start boundary",
        "evidence": "agent_studio_planner_orchestration_smoke",
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
    "source_agent_studio_planner_orchestration": (
        "agent_studio_planner_orchestration_smoke"
    ),
    "source_approval_policy_gate": "approval_policy_gate_smoke",
    "source_approval_resume_timeline": "approval_resume_timeline_smoke",
    "source_runtime_approval_resume": "runtime_approval_resume_smoke",
    "source_yachiyo_route_approval": "yachiyo_route_approval_smoke",
    "source_group_run_timeline": "group_run_timeline_smoke",
}

REAL_DESKTOP_OPT_IN_CAPABILITY_IDS = {
    "source_real_desktop_app_open",
    "source_real_desktop_ui_inspection",
    "source_real_desktop_interaction",
}

SOURCE_CAPABILITY_IDS = set(SOURCE_SECTION_CAPABILITIES)
PROVIDER_CAPABILITY_IDS = {
    "provider_text_stream",
    "provider_tool_call_stream",
    "model_profile_readiness",
    "agent_workspace_read",
    "agent_artifact_write",
    "agent_multi_tool_pipeline",
    "workflow_child_agent_artifact",
    "terminal_approval_resume",
    "main_chat_model_loop",
    "advanced_workflow_orchestration",
    "workflow_budget_boundary",
}
PACKAGED_CAPABILITY_IDS = {
    "packaged_backend_bridge_identity",
    "packaged_app_bridge_isolation",
}

NEXT_ACTION_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "source_capability_smoke",
        "category": "source",
        "reason": "Refresh source-level planner, artifact, approval, entrypoint, and default desktop discovery evidence.",
        "command": (
            "python scripts/verify_release_candidate.py --source-only "
            "--report-json tmp/rc-verification-source-capabilities.json"
        ),
        "capability_ids": tuple(
            capability_id
            for capability_id in SOURCE_SECTION_CAPABILITIES
            if capability_id not in REAL_DESKTOP_OPT_IN_CAPABILITY_IDS
        ),
    },
    {
        "id": "real_desktop_smokes",
        "category": "source",
        "reason": "Run opt-in real macOS app open, UI inspection, and interaction evidence.",
        "command": (
            "python scripts/verify_release_candidate.py --source-only "
            "--run-real-desktop-app-open-smoke "
            "--run-real-desktop-ui-inspection-smoke "
            "--run-real-desktop-interaction-smoke "
            "--report-json tmp/rc-verification-real-desktop.json"
        ),
        "capability_ids": tuple(sorted(REAL_DESKTOP_OPT_IN_CAPABILITY_IDS)),
    },
    {
        "id": "provider_smoke",
        "category": "provider",
        "reason": "Run live provider, model loop, Agent, Workflow, tool-call, and approval resume evidence.",
        "command": (
            "python scripts/verify_release_candidate.py --require-artifacts "
            "--check-dmg-mount --run-provider-smoke "
            "--report-json tmp/rc-verification-provider-smoke.json"
        ),
        "capability_ids": tuple(sorted(PROVIDER_CAPABILITY_IDS)),
    },
    {
        "id": "packaged_backend_bridge_smoke",
        "category": "packaged",
        "reason": "Verify the packaged backend Bridge identity.",
        "command": (
            "python scripts/verify_release_candidate.py --require-artifacts "
            "--run-packaged-backend-bridge-smoke "
            "--report-json tmp/rc-verification-backend-bridge.json"
        ),
        "capability_ids": ("packaged_backend_bridge_identity",),
    },
    {
        "id": "packaged_app_smoke",
        "category": "packaged",
        "reason": "Verify the packaged app uses its own Bridge instead of a development backend.",
        "command": (
            "python scripts/verify_release_candidate.py --require-artifacts "
            "--run-dmg-app-smoke --report-json tmp/rc-verification-dmg-app.json"
        ),
        "capability_ids": ("packaged_app_bridge_isolation",),
    },
)


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


def _native_provider_contract_checks(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    section = report.get("native_provider_contract_smoke")
    if not isinstance(section, dict) or section.get("status") != "passed":
        return {}
    evidence = section.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("ok") is not True:
        return {}
    raw_checks = evidence.get("checks")
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


def _provider_smoke_failed_or_requested(report: dict[str, Any]) -> bool:
    section = report.get("provider_smoke")
    if not isinstance(section, dict):
        return False
    status = str(section.get("status") or "").strip()
    if status in {"", "pending", "skipped"}:
        return False
    return status != "passed" or section.get("run_requested") is True


def _runtime_chain_checks(
    report: dict[str, Any],
    provider_checks: dict[str, dict[str, Any]],
    contract_checks: dict[str, dict[str, Any]],
    *,
    provider_label: str,
    contract_label: str,
) -> tuple[dict[str, dict[str, Any]], str]:
    if provider_label in provider_checks:
        return _nested_checks(provider_checks.get(provider_label)), "provider_smoke"
    if _provider_smoke_failed_or_requested(report):
        return {}, "provider_smoke"
    if contract_label in contract_checks:
        return _nested_checks(contract_checks.get(contract_label)), "native_provider_contract_smoke"
    return {}, ""


def _with_evidence_source(evidence: dict[str, Any], source: str) -> dict[str, Any]:
    if not source:
        return evidence
    result = dict(evidence)
    result.setdefault("evidence_source", source)
    return result


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


def _contract_summary_ok(contract_check: dict[str, Any] | None) -> bool:
    if not isinstance(contract_check, dict) or contract_check.get("ok") is not True:
        return False
    summary = contract_check.get("summary")
    return isinstance(summary, dict) and summary.get("ok") is True


def _check_ok(checks: dict[str, dict[str, Any]], name: str) -> bool:
    item = checks.get(name)
    return isinstance(item, dict) and item.get("ok") is True


def _report_section_passed(report: dict[str, Any], section_name: str) -> bool:
    section = report.get(section_name)
    return isinstance(section, dict) and section.get("status") == "passed"


def capability_category(capability_id: str) -> str:
    if capability_id in SOURCE_CAPABILITY_IDS:
        return "source"
    if capability_id in PROVIDER_CAPABILITY_IDS:
        return "provider"
    if capability_id in PACKAGED_CAPABILITY_IDS:
        return "packaged"
    return "unknown"


def _status_counts(capabilities: Sequence[dict[str, Any]]) -> dict[str, int]:
    return {
        status: sum(1 for capability in capabilities if capability.get("status") == status)
        for status in ("passed", "missing")
    }


def _capability_category_value(capability: dict[str, Any]) -> str:
    return str(
        capability.get("category")
        or capability_category(str(capability.get("id") or ""))
    )


def _category_status_counts(capabilities: Sequence[dict[str, Any]]) -> dict[str, dict[str, int]]:
    categories = ("source", "provider", "packaged", "unknown")
    counts: dict[str, dict[str, int]] = {}
    for category in categories:
        category_capabilities = [
            capability
            for capability in capabilities
            if _capability_category_value(capability) == category
        ]
        if category_capabilities:
            counts[category] = _status_counts(category_capabilities)
    return counts


def _missing_by_category(capabilities: Sequence[dict[str, Any]]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for capability in capabilities:
        if capability.get("status") == "passed":
            continue
        capability_id = str(capability.get("id") or "").strip()
        if not capability_id:
            continue
        category = str(capability.get("category") or capability_category(capability_id))
        missing.setdefault(category, []).append(capability_id)
    return missing


def capability_next_actions(capabilities: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    missing_ids = {
        str(capability.get("id") or "").strip()
        for capability in capabilities
        if capability.get("status") != "passed"
    }
    missing_ids.discard("")
    actions: list[dict[str, Any]] = []
    for action in NEXT_ACTION_DEFINITIONS:
        raw_capability_ids = action.get("capability_ids")
        action_capability_ids = (
            [str(item) for item in raw_capability_ids if str(item)]
            if isinstance(raw_capability_ids, (list, tuple))
            else []
        )
        target_ids = [
            capability_id
            for capability_id in action_capability_ids
            if capability_id in missing_ids
        ]
        if not target_ids:
            continue
        actions.append(
            {
                "id": action["id"],
                "category": action["category"],
                "reason": action["reason"],
                "command": action["command"],
                "capability_ids": target_ids,
            }
        )
    return actions


def capability_matrix_status_summary(
    capabilities: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    missing_ids = [
        str(capability.get("id"))
        for capability in capabilities
        if capability.get("status") != "passed"
    ]
    return {
        "ok": not missing_ids,
        "capability_count": len(capabilities),
        "status_counts": _status_counts(capabilities),
        "category_status_counts": _category_status_counts(capabilities),
        "missing_capability_ids": missing_ids,
        "missing_by_category": _missing_by_category(capabilities),
        "next_actions": capability_next_actions(capabilities),
    }


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


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values: list[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        return []
    values: list[str] = []
    for item in raw_values:
        clean = str(item or "").strip()
        if clean and clean not in values:
            values.append(clean)
    return values


def _safe_recovery_actions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    actions: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        action: dict[str, Any] = {}
        for key in ("label", "tool", "permission_target", "risk_level"):
            clean = str(item.get(key) or "").strip()
            if clean:
                action[key] = clean
        raw_input = item.get("input")
        if isinstance(raw_input, dict) and raw_input:
            action["input"] = sanitize_sensitive_value(
                raw_input,
                max_depth=2,
                text_limit=240,
                max_items=12,
            )
        if action:
            actions.append(action)
    return actions


def _copy_failure_recovery_metadata(
    *,
    summary: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    for key in ("stage", "error", "blocking_condition"):
        clean = str(evidence.get(key) or "").strip()
        if clean:
            summary[key] = clean
    for key in (
        "blocking_conditions",
        "permission_targets",
        "missing_permissions",
        "recovery_hints",
        "recommended_tools",
    ):
        values = _string_list(evidence.get(key))
        if values:
            summary[key] = values
    recovery_actions = _safe_recovery_actions(evidence.get("recovery_actions"))
    if recovery_actions:
        summary["recovery_actions"] = recovery_actions


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
    _copy_failure_recovery_metadata(summary=summary, evidence=evidence)
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
    contract_checks: dict[str, dict[str, Any]],
    native_agent_checks: dict[str, dict[str, Any]],
    native_workflow_checks: dict[str, dict[str, Any]],
    native_agent_source: str,
    native_workflow_source: str,
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
        evidence_source = ""
        if not ok and not _provider_smoke_failed_or_requested(report):
            contract_summary = _first_summary_check(contract_checks, "text_stream_contract")
            contract_ok = _contract_summary_ok(contract_checks.get("text_stream_contract"))
            if contract_ok:
                summary = contract_summary
                ok = True
                evidence_source = "native_provider_contract_smoke"
        return ("passed" if ok else "missing", _with_evidence_source({
            "finish_reasons": summary.get("finish_reasons", []),
            "content_chars": summary.get("content_chars"),
        }, evidence_source))
    if capability_id == "provider_tool_call_stream":
        summary = _first_summary_check(provider_checks, "tool_call_stream")
        ok = (
            _summary_ok(provider_checks.get("tool_call_stream"))
            and int(summary.get("tool_call_count") or 0) >= 1
            and summary.get("tool_result_followup_finish_reasons") == ["stop"]
        )
        evidence_source = ""
        if not ok and not _provider_smoke_failed_or_requested(report):
            contract_summary = _first_summary_check(
                contract_checks,
                "tool_call_stream_contract",
            )
            contract_ok = (
                _contract_summary_ok(contract_checks.get("tool_call_stream_contract"))
                and int(contract_summary.get("tool_call_count") or 0) >= 1
                and contract_summary.get("tool_result_followup_finish_reasons") == ["stop"]
            )
            if contract_ok:
                summary = contract_summary
                ok = True
                evidence_source = "native_provider_contract_smoke"
        return ("passed" if ok else "missing", _with_evidence_source({
            "tool_call_count": summary.get("tool_call_count"),
            "tool_result_followup_finish_reasons": summary.get("tool_result_followup_finish_reasons", []),
        }, evidence_source))
    if capability_id == "agent_multi_tool_pipeline":
        item = native_agent_checks.get("agent_multi_tool_pipeline", {})
        ok = (
            _check_ok(native_agent_checks, "agent_multi_tool_pipeline")
            and int(item.get("tool_call_count") or 0) >= 2
            and "pipeline-report.md" in (item.get("artifact_paths") or [])
        )
        return (
            "passed" if ok else "missing",
            _with_evidence_source(
                {
                    "tool_call_count": item.get("tool_call_count"),
                    "artifact_paths": item.get("artifact_paths", []),
                },
                native_agent_source,
            ),
        )
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
            _with_evidence_source(
                native_agent_checks.get(capability_id, {}),
                native_agent_source,
            ),
        )
    if capability_id in {
        "advanced_workflow_orchestration",
        "workflow_budget_boundary",
    }:
        return (
            "passed" if _check_ok(native_workflow_checks, capability_id) else "missing",
            _with_evidence_source(
                native_workflow_checks.get(capability_id, {}),
                native_workflow_source,
            ),
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
    contract_checks = _native_provider_contract_checks(report)
    native_agent_checks, native_agent_source = _runtime_chain_checks(
        report,
        provider_checks,
        contract_checks,
        provider_label="native_agent_full_chain",
        contract_label="native_agent_full_chain_contract",
    )
    native_workflow_checks, native_workflow_source = _runtime_chain_checks(
        report,
        provider_checks,
        contract_checks,
        provider_label="native_workflow_full_chain",
        contract_label="native_workflow_full_chain_contract",
    )
    capabilities: list[dict[str, Any]] = []
    for definition in CAPABILITY_DEFINITIONS:
        status, evidence = _capability_status(
            definition["id"],
            report=report,
            provider_checks=provider_checks,
            contract_checks=contract_checks,
            native_agent_checks=native_agent_checks,
            native_workflow_checks=native_workflow_checks,
            native_agent_source=native_agent_source,
            native_workflow_source=native_workflow_source,
        )
        capabilities.append(
            {
                **definition,
                "category": capability_category(definition["id"]),
                "status": status,
                "evidence_summary": evidence,
            }
        )
    return {
        **capability_matrix_status_summary(capabilities),
        "capabilities": capabilities,
    }


def merge_capability_matrices(
    matrices: Sequence[dict[str, Any]],
    *,
    source_reports: Sequence[str] | None = None,
) -> dict[str, Any]:
    capability_order: list[str] = []
    capability_by_id: dict[str, dict[str, Any]] = {}
    for matrix in matrices:
        raw_capabilities = matrix.get("capabilities")
        if not isinstance(raw_capabilities, list):
            continue
        for raw_capability in raw_capabilities:
            if not isinstance(raw_capability, dict):
                continue
            capability_id = str(raw_capability.get("id") or "").strip()
            if not capability_id:
                continue
            if capability_id not in capability_order:
                capability_order.append(capability_id)
            capability = dict(raw_capability)
            capability.setdefault("category", capability_category(capability_id))
            existing = capability_by_id.get(capability_id)
            if existing is None:
                capability_by_id[capability_id] = capability
                continue
            if existing.get("status") != "passed" and capability.get("status") == "passed":
                capability_by_id[capability_id] = capability

    capabilities = [capability_by_id[capability_id] for capability_id in capability_order]
    merged = {
        **capability_matrix_status_summary(capabilities),
        "capabilities": capabilities,
    }
    if source_reports:
        merged["source_reports"] = list(source_reports)
    return merged


def _normalize_capability_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    result = dict(matrix)
    raw_capabilities = result.get("capabilities")
    if not isinstance(raw_capabilities, list):
        return result

    capabilities: list[dict[str, Any]] = []
    for raw_capability in raw_capabilities:
        if not isinstance(raw_capability, dict):
            continue
        capability = dict(raw_capability)
        capability_id = str(capability.get("id") or "").strip()
        if capability_id and not str(capability.get("category") or "").strip():
            capability["category"] = capability_category(capability_id)
        capabilities.append(capability)
    if not capabilities:
        return result

    status_summary = capability_matrix_status_summary(capabilities)
    for key in (
        "ok",
        "capability_count",
        "status_counts",
        "missing_capability_ids",
        "category_status_counts",
        "missing_by_category",
        "next_actions",
    ):
        result.setdefault(key, status_summary[key])
    result["capabilities"] = capabilities
    if str(result.get("status") or "").strip() not in {"passed", "incomplete"}:
        result["status"] = "passed" if result.get("ok") is True else "incomplete"
    return result


def _should_preserve_report_matrix(raw_matrix: Any) -> bool:
    if not isinstance(raw_matrix, dict) or not isinstance(raw_matrix.get("capabilities"), list):
        return False
    if isinstance(raw_matrix.get("source_reports"), list) and raw_matrix.get("source_reports"):
        return True
    raw_count = raw_matrix.get("capability_count")
    return isinstance(raw_count, int) and raw_count >= len(CAPABILITY_DEFINITIONS)


def _report_can_rebuild_matrix(report: dict[str, Any]) -> bool:
    if isinstance(report.get("provider_smoke"), dict):
        return True
    rebuild_sections = tuple(SOURCE_SECTION_CAPABILITIES.values()) + (
        "packaged_backend_bridge_smoke",
        "dmg_app_smoke",
    )
    return any(isinstance(report.get(section), dict) for section in rebuild_sections)


def capability_matrix_from_report(report: dict[str, Any]) -> dict[str, Any]:
    raw_matrix = report.get("native_agent_capability_matrix")
    if _should_preserve_report_matrix(raw_matrix):
        return _normalize_capability_matrix(dict(raw_matrix))
    if _report_can_rebuild_matrix(report):
        matrix = summarize_capabilities(report)
        matrix["status"] = "passed" if matrix.get("ok") is True else "incomplete"
        return matrix
    if isinstance(raw_matrix, dict) and isinstance(raw_matrix.get("capabilities"), list):
        return _normalize_capability_matrix(dict(raw_matrix))
    return summarize_capabilities(report)


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "reports",
        nargs="+",
        type=Path,
        help="One or more release-candidate report JSON files.",
    )
    parser.add_argument("--output-json", type=Path, help="Write the capability matrix JSON.")
    args = parser.parse_args(argv)
    try:
        matrices: list[dict[str, Any]] = []
        source_reports: list[str] = []
        for report_path in args.reports:
            source = _load_report(ROOT, report_path)
            matrix = capability_matrix_from_report(source)
            matrix["source_report"] = str(report_path)
            matrices.append(matrix)
            source_reports.append(str(report_path))
        summary = (
            matrices[0]
            if len(matrices) == 1
            else merge_capability_matrices(matrices, source_reports=source_reports)
        )
        if len(matrices) == 1:
            summary["source_report"] = source_reports[0]
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
