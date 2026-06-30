#!/usr/bin/env python3
"""Run the cheap public-release preflight and summarize remaining evidence."""

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
class GateCheck:
    id: str
    label: str
    command: tuple[str, ...]
    report_json: Path | None = None


def public_release_gate_checks(
    *,
    tmp_dir: Path,
    include_public_demo: bool = True,
    include_real_desktop: bool = False,
    include_provider_workflow: bool = False,
    include_ui: bool = False,
) -> list[GateCheck]:
    checks = [
        GateCheck(
            id="release_artifacts",
            label="Release artifact and documentation guards",
            command=(sys.executable, "scripts/verify_release_artifacts.py"),
        ),
        GateCheck(
            id="secret_redaction",
            label="Secret redaction verifier",
            command=(sys.executable, "scripts/verify_secret_redaction.py"),
        ),
        GateCheck(
            id="release_pytest",
            label="Focused release pytest coverage",
            command=(
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_release_artifact_verifier.py::test_verifier_accepts_current_release_files",
                "tests/test_release_smoke_summary.py",
                "tests/test_public_demo_smokes.py",
                "tests/test_refresh_local_rc_signoff.py",
            ),
        ),
    ]
    if include_public_demo:
        public_demo_json = tmp_dir / "public-demo.json"
        public_demo_markdown = tmp_dir / "public-demo.md"
        command = [
            sys.executable,
            "scripts/run_public_demo_smokes.py",
            "--output-json",
            str(public_demo_json),
            "--output-markdown",
            str(public_demo_markdown),
        ]
        if include_real_desktop:
            command.append("--include-real-desktop")
        if include_provider_workflow:
            command.append("--include-provider-workflow")
        if include_ui:
            command.append("--include-ui")
        checks.append(
            GateCheck(
                id="public_demo",
                label="Public demo smoke evidence",
                command=tuple(command),
                report_json=public_demo_json,
            )
        )
    return checks


def run_public_release_gate(
    *,
    tmp_dir: Path | str = Path("tmp/public-release-gate"),
    include_public_demo: bool = True,
    include_real_desktop: bool = False,
    include_provider_workflow: bool = False,
    include_ui: bool = False,
    require_release_ready: bool = False,
    plan_only: bool = False,
) -> dict[str, Any]:
    resolved_tmp_dir = _resolve_path(Path(tmp_dir))
    resolved_tmp_dir.mkdir(parents=True, exist_ok=True)
    checks = public_release_gate_checks(
        tmp_dir=resolved_tmp_dir,
        include_public_demo=include_public_demo,
        include_real_desktop=include_real_desktop,
        include_provider_workflow=include_provider_workflow,
        include_ui=include_ui,
    )
    check_results = [
        _check_result(check, plan_only=plan_only)
        for check in checks
    ]
    failed = [item for item in check_results if item["status"] == "failed"]
    release_blockers = [
        blocker
        for item in check_results
        for blocker in _dict_list(item.get("release_blockers"))
    ]
    release_ready = not failed and not release_blockers and not plan_only
    status = (
        "planned"
        if plan_only
        else "failed"
        if failed
        else "ready"
        if release_ready
        else "needs_release_evidence"
    )
    ok = not failed and (release_ready or not require_release_ready)
    return {
        "ok": ok,
        "release_ready": release_ready,
        "status": status,
        "require_release_ready": require_release_ready,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tmp_dir": _display_path(resolved_tmp_dir),
        "check_count": len(check_results),
        "passed_count": sum(1 for item in check_results if item["status"] == "passed"),
        "failed_count": len(failed),
        "release_blocker_count": len(release_blockers),
        "checks": check_results,
        "next_actions": _next_actions(check_results),
    }


def _check_result(check: GateCheck, *, plan_only: bool) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": check.id,
        "label": check.label,
        "command": list(check.command),
        "report_json": _display_path(check.report_json) if check.report_json else "",
    }
    if plan_only:
        return {**base, "status": "planned"}
    result = _run_command(check.command)
    status = "passed" if result.returncode == 0 else "failed"
    payload: dict[str, Any] = {
        **base,
        "status": status,
        "returncode": result.returncode,
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
    }
    if check.id == "public_demo":
        payload.update(_public_demo_gate_fields(check.report_json, command=check.command))
        if payload.get("release_level") != "full_public_demo_ready":
            payload["release_blockers"] = _public_demo_release_blockers(payload)
    return payload


def _public_demo_gate_fields(path: Path | None, *, command: Sequence[str]) -> dict[str, Any]:
    report = _load_json(path)
    if not report:
        return {
            "release_level": "",
            "complete": False,
            "missing_required_flow_ids": [],
            "full_demo_command": _full_demo_command(),
        }
    return {
        "release_level": str(report.get("release_level") or ""),
        "complete": bool(report.get("complete") is True),
        "selected_count": int(report.get("selected_count") or 0),
        "passed_count": int(report.get("passed_count") or 0),
        "required_flow_count": int(report.get("required_flow_count") or 0),
        "passed_required_flow_count": int(report.get("passed_required_flow_count") or 0),
        "missing_required_flow_ids": _string_list(report.get("missing_required_flow_ids")),
        "release_blockers": _dict_list(report.get("release_blockers")),
        "full_demo_command": str(report.get("full_demo_command") or "") or _full_demo_command(),
        "public_demo_command": " ".join(str(part) for part in command),
    }


def _public_demo_release_blockers(check: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers = _dict_list(check.get("release_blockers"))
    if blockers:
        return blockers
    missing = _string_list(check.get("missing_required_flow_ids"))
    return [
        {
            "id": flow_id,
            "status": "missing",
            "reason": "required public demo flow has not passed",
        }
        for flow_id in missing
    ]


def _next_actions(checks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for check in checks:
        command = " ".join(str(part) for part in check.get("command") or [])
        if check.get("id") == "public_demo" and check.get("release_level") != "full_public_demo_ready":
            command = str(check.get("full_demo_command") or "") or _full_demo_command()
        if not command or command in seen:
            continue
        if check.get("status") == "passed" and not _dict_list(check.get("release_blockers")):
            continue
        seen.add(command)
        actions.append(
            {
                "id": str(check.get("id") or "next_action"),
                "status": str(check.get("status") or ""),
                "command": command,
                "release_level": str(check.get("release_level") or ""),
                "missing_required_flow_ids": _string_list(check.get("missing_required_flow_ids")),
            }
        )
    return actions


def render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Oha-Yachiyo Public Release Gate",
        "",
        f"Status: {summary.get('status')}",
        f"Release ready: {str(bool(summary.get('release_ready'))).lower()}",
        f"Checks: {summary.get('passed_count')}/{summary.get('check_count')} passed",
        "",
        "## Checks",
        "",
    ]
    for check in _dict_list(summary.get("checks")):
        marker = "x" if check.get("status") == "passed" else " "
        lines.append(f"- [{marker}] `{check.get('id')}` - {check.get('status')} - {check.get('label')}")
        release_level = str(check.get("release_level") or "")
        if release_level:
            lines.append(f"  Release level: `{release_level}`")
        missing = _string_list(check.get("missing_required_flow_ids"))
        if missing:
            lines.append(f"  Missing demo flows: {', '.join(f'`{item}`' for item in missing)}")
    actions = _dict_list(summary.get("next_actions"))
    if actions:
        lines.extend(["", "## Next Actions", ""])
        for action in actions:
            lines.append(f"- `{action.get('id')}`")
            command = str(action.get("command") or "").strip()
            if command:
                lines.extend(["", "```bash", command, "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _load_json(path: Path | None) -> dict[str, Any]:
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


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values: Sequence[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        return []
    return [str(item) for item in values if str(item)]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _full_demo_command() -> str:
    return (
        "python scripts/run_public_demo_smokes.py "
        "--include-real-desktop --include-provider-workflow --include-ui "
        "--output-json tmp/public-demo-smokes-full.json "
        "--output-markdown tmp/public-demo-smokes-full.md"
    )


def _write_text(path: Path, value: str) -> None:
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


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
    parser.add_argument("--tmp-dir", type=Path, default=Path("tmp/public-release-gate"))
    parser.add_argument("--skip-public-demo", action="store_true")
    parser.add_argument("--include-real-desktop", action="store_true")
    parser.add_argument("--include-provider-workflow", action="store_true")
    parser.add_argument("--include-ui", action="store_true")
    parser.add_argument("--require-release-ready", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    args = parser.parse_args(argv)

    summary = run_public_release_gate(
        tmp_dir=args.tmp_dir,
        include_public_demo=not args.skip_public_demo,
        include_real_desktop=bool(args.include_real_desktop),
        include_provider_workflow=bool(args.include_provider_workflow),
        include_ui=bool(args.include_ui),
        require_release_ready=bool(args.require_release_ready),
        plan_only=bool(args.plan_only),
    )
    if args.output_json is not None:
        _write_json(args.output_json, summary)
    if args.output_markdown is not None:
        _write_text(args.output_markdown, render_markdown(summary))
    if args.output_json is None and args.output_markdown is None:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
