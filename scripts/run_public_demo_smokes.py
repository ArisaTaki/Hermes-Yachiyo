#!/usr/bin/env python3
"""Run or plan public demo smokes for Oha-Yachiyo release readiness."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.security import redact_log_text  # noqa: E402

PUBLISH_CANDIDATE_TRACK_ID = "publish_candidate"
DESKTOP_EXECUTOR_TRACK_ID = "desktop_executor"
FULL_PUBLIC_DEMO_TRACK_ID = "full_public_demo"
DESKTOP_EXECUTOR_FLOW_IDS = (
    "desktop_planner_discovery",
    "agent_entrypoint_desktop_execution",
    "real_desktop_discovery",
    "isolated_desktop_provider",
    "isolated_desktop_interaction",
    "native_provider_contract",
    "approval_resume",
    "yachiyo_route_approval",
)


@dataclass(frozen=True)
class DemoFlow:
    id: str
    label: str
    category: str
    command: tuple[str, ...]
    report_json: Path | None = None
    opt_in_flag: str = ""
    opt_in_reason: str = ""
    release_required: bool = True
    manual_diagnostic_reason: str = ""


def demo_flows(
    tmp_dir: Path,
    *,
    allow_existing_real_desktop_app: bool = False,
) -> list[DemoFlow]:
    real_desktop_interaction_command = [
        sys.executable,
        "scripts/smoke_real_desktop_interaction.py",
        "--report-json",
        str(tmp_dir / "real-desktop-interaction.json"),
    ]
    if allow_existing_real_desktop_app:
        real_desktop_interaction_command.append("--allow-existing-app")
    return [
        DemoFlow(
            id="data_analysis_artifact",
            label="Data analysis artifact and readback",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_data_analysis_artifacts.py",
                "--workdir",
                str(tmp_dir / "data-analysis-workspace"),
                "--report-json",
                str(tmp_dir / "data-analysis-artifact.json"),
            ),
            report_json=tmp_dir / "data-analysis-artifact.json",
        ),
        DemoFlow(
            id="browser_research_artifact",
            label="Browser research planner and artifact expectation",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_browser_planner_artifacts.py",
                "--report-json",
                str(tmp_dir / "browser-research-artifact.json"),
            ),
            report_json=tmp_dir / "browser-research-artifact.json",
        ),
        DemoFlow(
            id="desktop_planner_discovery",
            label="Desktop planner discovery and operate tool plan",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_desktop_planner_discovery.py",
                "--report-json",
                str(tmp_dir / "desktop-planner-discovery.json"),
            ),
            report_json=tmp_dir / "desktop-planner-discovery.json",
        ),
        DemoFlow(
            id="agent_entrypoint_desktop_execution",
            label="Chat and Agent desktop execution entrypoints",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_agent_entrypoint_desktop_execution.py",
                "--report-json",
                str(tmp_dir / "agent-entrypoint-desktop-execution.json"),
            ),
            report_json=tmp_dir / "agent-entrypoint-desktop-execution.json",
        ),
        DemoFlow(
            id="agent_entrypoint_data_analysis",
            label="Agent data analysis entrypoint",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_agent_entrypoint_data_analysis.py",
                "--report-json",
                str(tmp_dir / "agent-entrypoint-data-analysis.json"),
            ),
            report_json=tmp_dir / "agent-entrypoint-data-analysis.json",
        ),
        DemoFlow(
            id="agent_studio_planner_orchestration",
            label="Agent Studio planner orchestration start",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_agent_studio_planner_orchestration.py",
                "--report-json",
                str(tmp_dir / "agent-studio-planner-orchestration.json"),
            ),
            report_json=tmp_dir / "agent-studio-planner-orchestration.json",
        ),
        DemoFlow(
            id="real_desktop_discovery",
            label="Real desktop app discovery without opening apps",
            category="real_desktop",
            command=(
                sys.executable,
                "scripts/smoke_real_desktop_discovery.py",
                "--report-json",
                str(tmp_dir / "real-desktop-discovery.json"),
            ),
            report_json=tmp_dir / "real-desktop-discovery.json",
        ),
        DemoFlow(
            id="isolated_desktop_provider",
            label="Isolated desktop provider keyboard/mouse interaction routing",
            category="sandbox",
            command=(
                sys.executable,
                "scripts/smoke_isolated_desktop_provider.py",
                "--report-json",
                str(tmp_dir / "isolated-desktop-provider.json"),
            ),
            report_json=tmp_dir / "isolated-desktop-provider.json",
        ),
        DemoFlow(
            id="isolated_desktop_interaction",
            label="Isolated desktop type, click, and verify loop",
            category="sandbox",
            command=(
                sys.executable,
                "scripts/smoke_isolated_desktop_interaction.py",
                "--report-json",
                str(tmp_dir / "isolated-desktop-interaction.json"),
            ),
            report_json=tmp_dir / "isolated-desktop-interaction.json",
        ),
        DemoFlow(
            id="native_provider_contract",
            label="Local provider contract for Agent and Workflow full chain",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_native_provider_contract.py",
                "--report-json",
                str(tmp_dir / "native-provider-contract.json"),
            ),
            report_json=tmp_dir / "native-provider-contract.json",
        ),
        DemoFlow(
            id="approval_resume",
            label="Approval card and replayable resume",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_approval_resume_timeline.py",
                "--report-json",
                str(tmp_dir / "approval-resume.json"),
            ),
            report_json=tmp_dir / "approval-resume.json",
        ),
        DemoFlow(
            id="yachiyo_route_approval",
            label="Yachiyo approval route boundary",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_yachiyo_route_approval.py",
                "--report-json",
                str(tmp_dir / "yachiyo-route-approval.json"),
            ),
            report_json=tmp_dir / "yachiyo-route-approval.json",
        ),
        DemoFlow(
            id="group_run",
            label="GroupRun public snapshot and replay",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_group_run_timeline.py",
                "--report-json",
                str(tmp_dir / "group-run.json"),
            ),
            report_json=tmp_dir / "group-run.json",
        ),
        DemoFlow(
            id="workflow_run",
            label="WorkflowRun public snapshot and replay",
            category="source",
            command=(
                sys.executable,
                "scripts/smoke_workflow_run_timeline.py",
                "--report-json",
                str(tmp_dir / "workflow-run.json"),
            ),
            report_json=tmp_dir / "workflow-run.json",
        ),
        DemoFlow(
            id="real_desktop_app_open",
            label="Arbitrary installed app discovery and open",
            category="real_desktop",
            command=(
                sys.executable,
                "scripts/smoke_real_desktop_app_open.py",
                "--report-json",
                str(tmp_dir / "real-desktop-app-open.json"),
            ),
            report_json=tmp_dir / "real-desktop-app-open.json",
            opt_in_flag="--include-real-desktop-open",
            opt_in_reason="opens a real macOS application",
            release_required=False,
            manual_diagnostic_reason=(
                "manual foreground diagnostic; isolated_desktop_interaction covers "
                "the non-invasive release path"
            ),
        ),
        DemoFlow(
            id="real_desktop_ui_inspection",
            label="Real app window and UI inspection",
            category="real_desktop",
            command=(
                sys.executable,
                "scripts/smoke_real_desktop_ui_inspection.py",
                "--report-json",
                str(tmp_dir / "real-desktop-ui-inspection.json"),
            ),
            report_json=tmp_dir / "real-desktop-ui-inspection.json",
            opt_in_flag="--include-real-desktop-ui-inspection",
            opt_in_reason="opens and inspects a real macOS application",
            release_required=False,
            manual_diagnostic_reason=(
                "manual foreground diagnostic; isolated_desktop_interaction covers "
                "the non-invasive release path"
            ),
        ),
        DemoFlow(
            id="real_desktop_interaction",
            label="Real app type, click, and verify loop",
            category="real_desktop",
            command=tuple(real_desktop_interaction_command),
            report_json=tmp_dir / "real-desktop-interaction.json",
            opt_in_flag="--include-real-desktop-interaction",
            opt_in_reason="types and clicks in a real macOS application",
            release_required=False,
            manual_diagnostic_reason=(
                "manual foreground diagnostic; isolated_desktop_interaction covers "
                "the non-invasive release path"
            ),
        ),
        DemoFlow(
            id="workflow_provider",
            label="Native Workflow full-chain provider orchestration",
            category="provider",
            command=(
                sys.executable,
                "scripts/smoke_native_workflow_full_chain.py",
                "--report-json",
                str(tmp_dir / "workflow-provider.json"),
            ),
            report_json=tmp_dir / "workflow-provider.json",
            opt_in_flag="--include-provider-workflow",
            opt_in_reason="requires live provider smoke credentials",
        ),
        DemoFlow(
            id="studio_replay_ui",
            label="Agent Studio Run Detail replay UI",
            category="ui",
            command=(
                "node",
                "scripts/smoke_agent_run_detail_ui.mjs",
                "--report-json",
                str(tmp_dir / "studio-replay-ui.json"),
            ),
            report_json=tmp_dir / "studio-replay-ui.json",
            opt_in_flag="--include-ui",
            opt_in_reason="starts Vite and Electron UI smoke",
        ),
        DemoFlow(
            id="workflow_ui",
            label="Workflow save/run and artifact UI",
            category="ui",
            command=(
                "node",
                "scripts/smoke_workflow_save_run_ui.mjs",
                "--report-json",
                str(tmp_dir / "workflow-ui.json"),
            ),
            report_json=tmp_dir / "workflow-ui.json",
            opt_in_flag="--include-ui",
            opt_in_reason="starts Vite and Electron UI smoke",
        ),
    ]


def run_public_demo_smokes(
    *,
    tmp_dir: Path | str = Path("tmp/public-demo-smokes"),
    include_real_desktop: bool = False,
    include_real_desktop_open: bool = False,
    include_real_desktop_ui_inspection: bool = False,
    include_real_desktop_interaction: bool = False,
    allow_existing_real_desktop_app: bool = False,
    include_provider_workflow: bool = False,
    include_ui: bool = False,
    plan_only: bool = False,
) -> dict[str, Any]:
    resolved_tmp_dir = _resolve_path(Path(tmp_dir))
    flows = demo_flows(
        resolved_tmp_dir,
        allow_existing_real_desktop_app=allow_existing_real_desktop_app,
    )
    selected_flags = {
        "--include-real-desktop-open": include_real_desktop or include_real_desktop_open,
        "--include-real-desktop-ui-inspection": (
            include_real_desktop or include_real_desktop_ui_inspection
        ),
        "--include-real-desktop-interaction": (
            include_real_desktop or include_real_desktop_interaction
        ),
        "--include-provider-workflow": include_provider_workflow,
        "--include-ui": include_ui,
    }
    resolved_tmp_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    flow_results = [
        _flow_result(
            flow,
            selected=_flow_selected(flow, selected_flags),
            plan_only=plan_only,
        )
        for flow in flows
    ]
    selected = [flow for flow in flow_results if flow.get("selected") is True]
    skipped = [flow for flow in flow_results if flow.get("status") == "skipped"]
    failed = [flow for flow in selected if flow.get("status") == "failed"]
    passed = [flow for flow in selected if flow.get("status") == "passed"]
    planned = [flow for flow in selected if flow.get("status") == "planned"]
    selected_ok = bool(selected) and not failed and not planned
    required_incomplete = [
        flow
        for flow in flow_results
        if flow.get("release_required") is not False
        and str(flow.get("status") or "") != "passed"
    ]
    complete = selected_ok and not required_incomplete
    status = (
        "planned"
        if plan_only
        else "passed"
        if complete
        else "partial"
        if selected_ok
        else "failed"
    )
    assessment = _release_assessment(flow_results, plan_only=plan_only)
    return {
        "ok": selected_ok,
        "complete": complete,
        "status": status,
        **assessment,
        "plan_only": plan_only,
        "generated_at": started_at,
        "tmp_dir": _display_path(resolved_tmp_dir),
        "flow_count": len(flow_results),
        "selected_count": len(selected),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "flows": flow_results,
        "next_actions": _next_actions(flow_results),
    }


def _flow_result(
    flow: DemoFlow,
    *,
    selected: bool,
    plan_only: bool,
) -> dict[str, Any]:
    command = list(flow.command)
    base: dict[str, Any] = {
        "id": flow.id,
        "label": flow.label,
        "category": flow.category,
        "selected": selected,
        "command": command,
        "report_json": _display_path(flow.report_json) if flow.report_json else "",
        "opt_in_flag": flow.opt_in_flag,
        "opt_in_reason": flow.opt_in_reason,
        "release_required": flow.release_required,
        "manual_diagnostic_reason": flow.manual_diagnostic_reason,
    }
    if not selected:
        return {**base, "status": "skipped"}
    if plan_only:
        return {**base, "status": "planned"}

    _clear_evidence(flow.report_json)
    result = _run_command(command)
    evidence = _load_evidence(flow.report_json) if flow.report_json else {}
    evidence_ok = evidence.get("ok") is True if evidence else result.returncode == 0
    evidence_skipped = evidence.get("skipped") is True if evidence else False
    status = (
        "skipped"
        if result.returncode == 0 and evidence_skipped
        else "passed"
        if result.returncode == 0 and evidence_ok
        else "failed"
    )
    return {
        **base,
        "status": status,
        "returncode": result.returncode,
        "evidence_ok": evidence_ok,
        "evidence_skipped": evidence_skipped,
        "evidence_mode": str(evidence.get("mode") or ""),
        "evidence_reason": str(evidence.get("reason") or ""),
        "evidence_summary": _evidence_summary(evidence),
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
    }


def _flow_selected(flow: DemoFlow, selected_flags: Mapping[str, bool]) -> bool:
    if not flow.opt_in_flag:
        return True
    return bool(selected_flags.get(flow.opt_in_flag))


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _load_evidence(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _clear_evidence(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _evidence_summary(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if not evidence:
        return {}
    keys = (
        "ok",
        "mode",
        "skipped",
        "platform",
        "stage",
        "error",
        "reason",
        "blocking_condition",
        "blocking_conditions",
        "missing_env",
        "recovery_hints",
        "recommended_tools",
        "app_name",
        "opened_app_name",
        "screen_visibility_status",
        "screen_blocking_condition",
        "release_level",
        "desktop_session_kind",
        "desktop_session_isolated",
        "foreground_takeover_required",
        "keyboard_mouse_capture_supported",
        "supported_tools",
        "covered_tools",
        "tool_sequence",
    )
    summary = {
        key: evidence[key]
        for key in keys
        if key in evidence and evidence[key] not in ("", [], {}, None)
    }
    checks = evidence.get("checks")
    if isinstance(checks, dict):
        summary["checks"] = {
            str(key): value for key, value in checks.items() if isinstance(value, bool)
        }
    for key in ("action_target", "observation_evidence", "observation_retry"):
        value = evidence.get(key)
        if isinstance(value, dict):
            summary[key] = dict(value)
    return summary


def _tail(value: str, *, limit: int = 1200) -> str:
    redacted = redact_log_text(value or "")
    if len(redacted) <= limit:
        return redacted
    return redacted[-limit:]


def _next_actions(flows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for flow in flows:
        status = str(flow.get("status") or "")
        if status not in {"failed", "skipped", "planned"}:
            continue
        command = flow.get("command")
        if not isinstance(command, list):
            continue
        command_parts = [str(part) for part in command]
        reason = _flow_blocker_reason(flow)
        if (
            str(flow.get("id") or "") == "real_desktop_interaction"
            and reason == "app_already_running"
            and "--allow-existing-app" not in command_parts
        ):
            command_parts.append("--allow-existing-app")
        actions.append(
            {
                "id": str(flow.get("id") or ""),
                "status": status,
                "command": " ".join(command_parts),
                "opt_in_flag": str(flow.get("opt_in_flag") or ""),
                "opt_in_reason": str(flow.get("opt_in_reason") or ""),
                "reason": reason,
                "evidence_summary": _dict(flow.get("evidence_summary")),
            }
        )
    return actions


def _release_assessment(
    flows: Sequence[Mapping[str, Any]],
    *,
    plan_only: bool,
) -> dict[str, Any]:
    required_flows = [
        flow for flow in flows if flow.get("release_required") is not False
    ]
    diagnostic_flows = [
        flow for flow in flows if flow.get("release_required") is False
    ]
    incomplete = [
        flow
        for flow in required_flows
        if str(flow.get("status") or "") != "passed"
    ]
    diagnostic_incomplete = [
        flow
        for flow in diagnostic_flows
        if str(flow.get("status") or "") != "passed"
    ]
    failed = [
        flow
        for flow in required_flows
        if str(flow.get("status") or "") == "failed"
    ]
    publish_candidate_flows = [
        flow for flow in flows if not str(flow.get("opt_in_flag") or "")
    ]
    publish_candidate_incomplete = [
        flow
        for flow in publish_candidate_flows
        if str(flow.get("status") or "") != "passed"
    ]
    publish_candidate_passed_count = len(publish_candidate_flows) - len(
        publish_candidate_incomplete
    )
    desktop_executor_flows = [
        flow for flow in flows if str(flow.get("id") or "") in DESKTOP_EXECUTOR_FLOW_IDS
    ]
    desktop_executor_incomplete = [
        flow
        for flow in desktop_executor_flows
        if str(flow.get("status") or "") != "passed"
    ]
    desktop_executor_passed_count = len(desktop_executor_flows) - len(
        desktop_executor_incomplete
    )
    passed_count = len(required_flows) - len(incomplete)
    if not flows:
        release_level = "blocked"
    elif plan_only:
        release_level = "planned"
    elif not incomplete:
        release_level = "full_public_demo_ready"
    elif failed:
        release_level = "blocked"
    elif not publish_candidate_incomplete:
        release_level = "publish_candidate_ready"
    else:
        release_level = "partial_demo_ready"
    publish_candidate_progress = _release_progress(
        publish_candidate_flows,
        passed_count=publish_candidate_passed_count,
        plan_only=plan_only,
        baseline_id=PUBLISH_CANDIDATE_TRACK_ID,
        baseline_label="Publish candidate readiness without foreground takeover",
        denominator="publish_candidate_flow_count",
        note=(
            "This track excludes opt-in flows that open real foreground apps, "
            "require live provider credentials, or start UI harnesses."
        ),
    )
    desktop_executor_progress = _release_progress(
        desktop_executor_flows,
        passed_count=desktop_executor_passed_count,
        plan_only=plan_only,
        baseline_id=DESKTOP_EXECUTOR_TRACK_ID,
        baseline_label="Desktop executor safe runtime readiness",
        denominator="desktop_executor_flow_count",
        note=(
            "This track proves the default desktop executor path: planner, "
            "Chat/Agent entrypoint execution, real read-only discovery, isolated "
            "keyboard/mouse interaction, provider routing, and approval boundaries."
        ),
    )
    full_public_demo_progress = _release_progress(
        required_flows,
        passed_count=passed_count,
        plan_only=plan_only,
        baseline_id=FULL_PUBLIC_DEMO_TRACK_ID,
        baseline_label="Full public demo release readiness",
        denominator="required_flow_count",
        note=(
            "Use full_public_demo for required release evidence. Foreground "
            "mouse/keyboard smokes are manual diagnostics; the required desktop "
            "release path is the isolated provider plus real read-only discovery."
        ),
    )
    manual_diagnostic_progress = _release_progress(
        diagnostic_flows,
        passed_count=len(diagnostic_flows) - len(diagnostic_incomplete),
        plan_only=plan_only,
        baseline_id="manual_foreground_diagnostics",
        baseline_label="Manual foreground desktop diagnostics",
        denominator="manual_diagnostic_flow_count",
        note=(
            "These opt-in smokes open, inspect, type, or click in real foreground "
            "macOS apps. They are useful diagnostics but are not required for the "
            "non-invasive public release baseline."
        ),
    )
    return {
        "release_level": release_level,
        "required_flow_count": len(required_flows),
        "passed_required_flow_count": passed_count,
        "manual_diagnostic_flow_count": len(diagnostic_flows),
        "passed_manual_diagnostic_flow_count": len(diagnostic_flows)
        - len(diagnostic_incomplete),
        "publish_candidate_flow_count": len(publish_candidate_flows),
        "passed_publish_candidate_flow_count": publish_candidate_passed_count,
        "desktop_executor_flow_count": len(desktop_executor_flows),
        "passed_desktop_executor_flow_count": desktop_executor_passed_count,
        "release_progress": full_public_demo_progress,
        "publish_candidate_progress": publish_candidate_progress,
        "desktop_executor_progress": desktop_executor_progress,
        "manual_diagnostic_progress": manual_diagnostic_progress,
        "release_tracks": {
            PUBLISH_CANDIDATE_TRACK_ID: publish_candidate_progress,
            DESKTOP_EXECUTOR_TRACK_ID: desktop_executor_progress,
            FULL_PUBLIC_DEMO_TRACK_ID: full_public_demo_progress,
            "manual_foreground_diagnostics": manual_diagnostic_progress,
        },
        "missing_required_flow_ids": [
            str(flow.get("id") or "") for flow in incomplete if flow.get("id")
        ],
        "missing_publish_candidate_flow_ids": [
            str(flow.get("id") or "")
            for flow in publish_candidate_incomplete
            if flow.get("id")
        ],
        "missing_desktop_executor_flow_ids": [
            str(flow.get("id") or "")
            for flow in desktop_executor_incomplete
            if flow.get("id")
        ],
        "manual_diagnostic_gap_ids": [
            str(flow.get("id") or "")
            for flow in diagnostic_incomplete
            if flow.get("id")
        ],
        "release_blockers": [
            _release_blocker(flow) for flow in incomplete if isinstance(flow, Mapping)
        ],
        "publish_candidate_blockers": [
            _release_blocker(flow)
            for flow in publish_candidate_incomplete
            if isinstance(flow, Mapping)
        ],
        "desktop_executor_blockers": [
            _release_blocker(flow)
            for flow in desktop_executor_incomplete
            if isinstance(flow, Mapping)
        ],
        "manual_diagnostic_actions": [
            _release_blocker(flow)
            for flow in diagnostic_incomplete
            if isinstance(flow, Mapping)
        ],
        "full_demo_command": (
            "python scripts/run_public_demo_smokes.py "
            "--include-provider-workflow --include-ui "
            "--output-json tmp/public-demo-smokes-full.json "
            "--output-markdown tmp/public-demo-smokes-full.md"
        ),
        "foreground_diagnostic_command": (
            "python scripts/run_public_demo_smokes.py "
            "--include-real-desktop "
            "--output-json tmp/public-demo-smokes-foreground-diagnostics.json "
            "--output-markdown tmp/public-demo-smokes-foreground-diagnostics.md"
        ),
    }


def _release_progress(
    flows: Sequence[Mapping[str, Any]],
    *,
    passed_count: int,
    plan_only: bool,
    baseline_id: str = FULL_PUBLIC_DEMO_TRACK_ID,
    baseline_label: str = "Full public demo release readiness",
    denominator: str = "required_flow_count",
    note: str | None = None,
) -> dict[str, Any]:
    total_count = len(flows)
    selected = [flow for flow in flows if flow.get("selected") is True]
    selected_passed = [
        flow for flow in selected if str(flow.get("status") or "") == "passed"
    ]
    incomplete = [
        flow for flow in flows if str(flow.get("status") or "") != "passed"
    ]
    skipped_opt_in = [
        flow
        for flow in flows
        if str(flow.get("status") or "") == "skipped"
        and str(flow.get("opt_in_flag") or "")
    ]
    remaining_count = len(incomplete)
    percent = round((passed_count / total_count) * 100, 2) if total_count else 0.0
    return {
        "baseline_id": baseline_id,
        "baseline_label": baseline_label,
        "denominator": denominator,
        "status_basis": "planned" if plan_only else "executed_smoke_results",
        "passed_count": passed_count,
        "total_count": total_count,
        "remaining_count": remaining_count,
        "percent": percent,
        "selected_count": len(selected),
        "selected_passed_count": len(selected_passed),
        "selected_remaining_count": max(len(selected) - len(selected_passed), 0),
        "missing_required_flow_ids": [
            str(flow.get("id") or "") for flow in incomplete if flow.get("id")
        ],
        "opt_in_gap_ids": [
            str(flow.get("id") or "") for flow in skipped_opt_in if flow.get("id")
        ],
        "note": note
        or (
            "Use passed_count/total_count for release progress. "
            "Selected counts describe this smoke invocation only."
        ),
    }


def _release_blocker(flow: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(flow.get("id") or ""),
        "label": str(flow.get("label") or ""),
        "category": str(flow.get("category") or ""),
        "status": str(flow.get("status") or ""),
        "opt_in_flag": str(flow.get("opt_in_flag") or ""),
        "opt_in_reason": str(flow.get("opt_in_reason") or ""),
        "release_required": flow.get("release_required") is not False,
        "manual_diagnostic_reason": str(flow.get("manual_diagnostic_reason") or ""),
        "reason": _flow_blocker_reason(flow),
        "evidence_summary": _dict(flow.get("evidence_summary")),
        "command": " ".join(str(part) for part in flow.get("command") or []),
    }


def _flow_blocker_reason(flow: Mapping[str, Any]) -> str:
    evidence_summary = _dict(flow.get("evidence_summary"))
    blocking_conditions = _string_list(evidence_summary.get("blocking_conditions"))
    if len(blocking_conditions) > 1:
        return ", ".join(blocking_conditions)
    for key in ("blocking_condition", "error", "reason"):
        value = str(evidence_summary.get(key) or "").strip()
        if value:
            return value
    return str(flow.get("evidence_reason") or flow.get("opt_in_reason") or "").strip()


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


def render_markdown(summary: Mapping[str, Any]) -> str:
    release_progress = _dict(summary.get("release_progress"))
    publish_candidate_progress = _dict(summary.get("publish_candidate_progress"))
    desktop_executor_progress = _dict(summary.get("desktop_executor_progress"))
    manual_diagnostic_progress = _dict(summary.get("manual_diagnostic_progress"))
    lines = [
        "# Oha-Yachiyo Public Demo Smoke Summary",
        "",
        f"Status: {summary.get('status')}",
        f"Release level: {summary.get('release_level')}",
        f"Selected: {summary.get('passed_count')}/{summary.get('selected_count')} passed",
        (
            "Publish candidate flows: "
            f"{summary.get('passed_publish_candidate_flow_count')}/"
            f"{summary.get('publish_candidate_flow_count')} passed"
        ),
        (
            "Desktop executor flows: "
            f"{summary.get('passed_desktop_executor_flow_count')}/"
            f"{summary.get('desktop_executor_flow_count')} passed"
        ),
        (
            "Required demo flows: "
            f"{summary.get('passed_required_flow_count')}/{summary.get('required_flow_count')} passed"
        ),
        (
            "Manual foreground diagnostics: "
            f"{summary.get('passed_manual_diagnostic_flow_count')}/"
            f"{summary.get('manual_diagnostic_flow_count')} passed"
        ),
        (
            "Publish candidate baseline: "
            f"{publish_candidate_progress.get('baseline_id') or PUBLISH_CANDIDATE_TRACK_ID} "
            f"({publish_candidate_progress.get('passed_count', summary.get('passed_publish_candidate_flow_count'))}/"
            f"{publish_candidate_progress.get('total_count', summary.get('publish_candidate_flow_count'))} passed, "
            f"{publish_candidate_progress.get('remaining_count', '?')} remaining)"
        ),
        (
            "Desktop executor baseline: "
            f"{desktop_executor_progress.get('baseline_id') or DESKTOP_EXECUTOR_TRACK_ID} "
            f"({desktop_executor_progress.get('passed_count', summary.get('passed_desktop_executor_flow_count'))}/"
            f"{desktop_executor_progress.get('total_count', summary.get('desktop_executor_flow_count'))} passed, "
            f"{desktop_executor_progress.get('remaining_count', '?')} remaining)"
        ),
        (
            "Full demo baseline: "
            f"{release_progress.get('baseline_id') or FULL_PUBLIC_DEMO_TRACK_ID} "
            f"({release_progress.get('passed_count', summary.get('passed_required_flow_count'))}/"
            f"{release_progress.get('total_count', summary.get('required_flow_count'))} passed, "
            f"{release_progress.get('remaining_count', '?')} remaining)"
        ),
        (
            "Manual foreground baseline: "
            f"{manual_diagnostic_progress.get('baseline_id') or 'manual_foreground_diagnostics'} "
            f"({manual_diagnostic_progress.get('passed_count', summary.get('passed_manual_diagnostic_flow_count'))}/"
            f"{manual_diagnostic_progress.get('total_count', summary.get('manual_diagnostic_flow_count'))} passed, "
            f"{manual_diagnostic_progress.get('remaining_count', '?')} remaining)"
        ),
        f"Complete demo evidence: {str(bool(summary.get('complete'))).lower()}",
        "",
        "## Flows",
        "",
    ]
    for flow in _dict_list(summary.get("flows")):
        marker = "x" if flow.get("status") == "passed" else " "
        lines.append(f"- [{marker}] `{flow.get('id')}` - {flow.get('status')} - {flow.get('label')}")
        reason = str(flow.get("opt_in_reason") or "")
        if flow.get("status") == "skipped" and reason:
            lines.append(f"  Opt-in: `{flow.get('opt_in_flag')}` ({reason})")
        diagnostic_reason = str(flow.get("manual_diagnostic_reason") or "")
        if flow.get("release_required") is False and diagnostic_reason:
            lines.append(f"  Manual diagnostic: {diagnostic_reason}")
        blocker = _flow_blocker_reason(flow)
        if flow.get("status") == "failed" and blocker:
            lines.append(f"  Blocker: `{blocker}`")
    blockers = _dict_list(summary.get("release_blockers"))
    if blockers:
        lines.extend(["", "## Release Blockers", ""])
        for blocker in blockers:
            lines.append(
                f"- `{blocker.get('id')}` ({blocker.get('status')}) - {blocker.get('label')}"
            )
            opt_in = str(blocker.get("opt_in_flag") or "")
            opt_in_reason = str(blocker.get("opt_in_reason") or "")
            reason = str(blocker.get("reason") or "")
            if opt_in:
                if opt_in_reason:
                    lines.append(f"  Requires `{opt_in}`: {opt_in_reason}")
                if reason and reason != opt_in_reason:
                    lines.append(f"  Blocker: `{reason}`")
            elif reason:
                lines.append(f"  Reason: {reason}")
    diagnostics = _dict_list(summary.get("manual_diagnostic_actions"))
    if diagnostics:
        lines.extend(["", "## Manual Foreground Diagnostics", ""])
        for diagnostic in diagnostics:
            lines.append(
                f"- `{diagnostic.get('id')}` ({diagnostic.get('status')}) - {diagnostic.get('label')}"
            )
            opt_in = str(diagnostic.get("opt_in_flag") or "")
            opt_in_reason = str(diagnostic.get("opt_in_reason") or "")
            manual_reason = str(diagnostic.get("manual_diagnostic_reason") or "")
            if opt_in and opt_in_reason:
                lines.append(f"  Optional `{opt_in}`: {opt_in_reason}")
            if manual_reason:
                lines.append(f"  Reason: {manual_reason}")
    actions = _dict_list(summary.get("next_actions"))
    if actions:
        lines.extend(["", "## Next Actions", ""])
        for action in actions:
            lines.append(f"- `{action.get('id')}` ({action.get('status')})")
            opt_in = str(action.get("opt_in_flag") or "")
            opt_in_reason = str(action.get("opt_in_reason") or "")
            reason = str(action.get("reason") or "")
            if opt_in:
                if opt_in_reason:
                    lines.append(f"  Requires `{opt_in}`: {opt_in_reason}")
                if reason and reason != opt_in_reason:
                    lines.append(f"  Blocker: `{reason}`")
            elif reason:
                lines.append(f"  Reason: {reason}")
            lines.extend(["", "```bash", str(action.get("command") or ""), "```", ""])
    return "\n".join(lines).rstrip() + "\n"


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


def _resolve_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return ROOT / expanded


def _display_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tmp-dir", type=Path, default=Path("tmp/public-demo-smokes"))
    parser.add_argument("--include-real-desktop", action="store_true")
    parser.add_argument("--include-real-desktop-open", action="store_true")
    parser.add_argument("--include-real-desktop-ui-inspection", action="store_true")
    parser.add_argument("--include-real-desktop-interaction", action="store_true")
    parser.add_argument("--allow-existing-real-desktop-app", action="store_true")
    parser.add_argument("--include-provider-workflow", action="store_true")
    parser.add_argument("--include-ui", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    args = parser.parse_args(argv)

    summary = run_public_demo_smokes(
        tmp_dir=args.tmp_dir,
        include_real_desktop=bool(args.include_real_desktop),
        include_real_desktop_open=bool(args.include_real_desktop_open),
        include_real_desktop_ui_inspection=bool(args.include_real_desktop_ui_inspection),
        include_real_desktop_interaction=bool(args.include_real_desktop_interaction),
        allow_existing_real_desktop_app=bool(args.allow_existing_real_desktop_app),
        include_provider_workflow=bool(args.include_provider_workflow),
        include_ui=bool(args.include_ui),
        plan_only=bool(args.plan_only),
    )
    if args.output_json is not None:
        _write_json(args.output_json, summary)
    if args.output_markdown is not None:
        _write_text(args.output_markdown, render_markdown(summary))
    if args.output_json is None and args.output_markdown is None:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.plan_only:
        return 0
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
