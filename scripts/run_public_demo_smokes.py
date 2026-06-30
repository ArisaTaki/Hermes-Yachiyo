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


@dataclass(frozen=True)
class DemoFlow:
    id: str
    label: str
    category: str
    command: tuple[str, ...]
    report_json: Path | None = None
    opt_in_flag: str = ""
    opt_in_reason: str = ""


def demo_flows(tmp_dir: Path) -> list[DemoFlow]:
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
        ),
        DemoFlow(
            id="real_desktop_interaction",
            label="Real app type, click, and verify loop",
            category="real_desktop",
            command=(
                sys.executable,
                "scripts/smoke_real_desktop_interaction.py",
                "--report-json",
                str(tmp_dir / "real-desktop-interaction.json"),
            ),
            report_json=tmp_dir / "real-desktop-interaction.json",
            opt_in_flag="--include-real-desktop-interaction",
            opt_in_reason="types and clicks in a real macOS application",
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
            command=("node", "scripts/smoke_agent_run_detail_ui.mjs"),
            opt_in_flag="--include-ui",
            opt_in_reason="starts Vite and Electron UI smoke",
        ),
        DemoFlow(
            id="workflow_ui",
            label="Workflow save/run and artifact UI",
            category="ui",
            command=("node", "scripts/smoke_workflow_save_run_ui.mjs"),
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
    include_provider_workflow: bool = False,
    include_ui: bool = False,
    plan_only: bool = False,
) -> dict[str, Any]:
    resolved_tmp_dir = _resolve_path(Path(tmp_dir))
    flows = demo_flows(resolved_tmp_dir)
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
    complete = selected_ok and not skipped
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
    }
    if not selected:
        return {**base, "status": "skipped"}
    if plan_only:
        return {**base, "status": "planned"}

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
        actions.append(
            {
                "id": str(flow.get("id") or ""),
                "status": status,
                "command": " ".join(str(part) for part in command),
                "opt_in_flag": str(flow.get("opt_in_flag") or ""),
                "reason": str(flow.get("opt_in_reason") or flow.get("evidence_reason") or ""),
            }
        )
    return actions


def _release_assessment(
    flows: Sequence[Mapping[str, Any]],
    *,
    plan_only: bool,
) -> dict[str, Any]:
    incomplete = [
        flow for flow in flows if str(flow.get("status") or "") != "passed"
    ]
    failed = [flow for flow in flows if str(flow.get("status") or "") == "failed"]
    passed_count = len(flows) - len(incomplete)
    if not flows:
        release_level = "blocked"
    elif not incomplete:
        release_level = "full_public_demo_ready"
    elif plan_only:
        release_level = "planned"
    elif failed:
        release_level = "blocked"
    else:
        release_level = "partial_demo_ready"
    return {
        "release_level": release_level,
        "required_flow_count": len(flows),
        "passed_required_flow_count": passed_count,
        "missing_required_flow_ids": [
            str(flow.get("id") or "") for flow in incomplete if flow.get("id")
        ],
        "release_blockers": [
            _release_blocker(flow) for flow in incomplete if isinstance(flow, Mapping)
        ],
        "full_demo_command": (
            "python scripts/run_public_demo_smokes.py "
            "--include-real-desktop --include-provider-workflow --include-ui "
            "--output-json tmp/public-demo-smokes-full.json "
            "--output-markdown tmp/public-demo-smokes-full.md"
        ),
    }


def _release_blocker(flow: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(flow.get("id") or ""),
        "label": str(flow.get("label") or ""),
        "category": str(flow.get("category") or ""),
        "status": str(flow.get("status") or ""),
        "opt_in_flag": str(flow.get("opt_in_flag") or ""),
        "reason": str(flow.get("opt_in_reason") or flow.get("evidence_reason") or ""),
        "command": " ".join(str(part) for part in flow.get("command") or []),
    }


def render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Oha-Yachiyo Public Demo Smoke Summary",
        "",
        f"Status: {summary.get('status')}",
        f"Release level: {summary.get('release_level')}",
        f"Selected: {summary.get('passed_count')}/{summary.get('selected_count')} passed",
        (
            "Required demo flows: "
            f"{summary.get('passed_required_flow_count')}/{summary.get('required_flow_count')} passed"
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
    blockers = _dict_list(summary.get("release_blockers"))
    if blockers:
        lines.extend(["", "## Release Blockers", ""])
        for blocker in blockers:
            lines.append(
                f"- `{blocker.get('id')}` ({blocker.get('status')}) - {blocker.get('label')}"
            )
            opt_in = str(blocker.get("opt_in_flag") or "")
            reason = str(blocker.get("reason") or "")
            if opt_in:
                lines.append(f"  Requires `{opt_in}`: {reason}")
            elif reason:
                lines.append(f"  Reason: {reason}")
    actions = _dict_list(summary.get("next_actions"))
    if actions:
        lines.extend(["", "## Next Actions", ""])
        for action in actions:
            lines.append(f"- `{action.get('id')}` ({action.get('status')})")
            opt_in = str(action.get("opt_in_flag") or "")
            reason = str(action.get("reason") or "")
            if opt_in:
                lines.append(f"  Requires `{opt_in}`: {reason}")
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
