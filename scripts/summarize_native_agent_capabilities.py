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
