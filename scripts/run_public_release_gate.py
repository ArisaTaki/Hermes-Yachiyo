#!/usr/bin/env python3
"""Run the cheap public-release preflight and summarize remaining evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
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
                "tests/test_public_release_gate.py",
                "tests/test_release_smoke_summary.py",
                "tests/test_public_demo_smokes.py",
                "tests/test_refresh_local_rc_signoff.py",
                "tests/test_release_diagnostics_bundle.py",
            ),
        ),
    ]
    if include_public_demo:
        public_demo_json = tmp_dir / "public-demo.json"
        public_demo_markdown = tmp_dir / "public-demo.md"
        command = [
            sys.executable,
            "scripts/run_public_demo_smokes.py",
            "--tmp-dir",
            str(tmp_dir),
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
    include_release_smoke: bool = True,
    release_smoke_reports: Sequence[Path | str] = (),
    diagnostics_zips: Sequence[Path | str] = (),
    include_diagnostics_bundle: bool = True,
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
    generated_diagnostics_zips: list[Path] = []
    if include_diagnostics_bundle and include_public_demo:
        diagnostics_result = _diagnostics_bundle_check(
            tmp_dir=resolved_tmp_dir,
            plan_only=plan_only,
        )
        check_results.append(diagnostics_result)
        if diagnostics_result.get("status") == "passed":
            output_zip = _resolve_path(Path(str(diagnostics_result.get("output_zip") or "")))
            generated_diagnostics_zips.append(output_zip)
    failed = [item for item in check_results if item["status"] == "failed"]
    demo_release_blockers = [
        blocker
        for item in check_results
        for blocker in _dict_list(item.get("release_blockers"))
    ]
    release_smoke = (
        _release_smoke_assessment(
            tmp_dir=resolved_tmp_dir,
            checks=checks,
            extra_reports=release_smoke_reports,
            diagnostics_zips=[*generated_diagnostics_zips, *diagnostics_zips],
            plan_only=plan_only,
        )
        if include_release_smoke
        else {}
    )
    release_smoke_blockers = _release_smoke_blockers(release_smoke)
    release_blocker_count = len(demo_release_blockers) + len(release_smoke_blockers)
    release_ready = not failed and release_blocker_count == 0 and not plan_only
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
        "release_blocker_count": release_blocker_count,
        "checks": check_results,
        "release_smoke": release_smoke,
        "next_actions": _next_actions(check_results, release_smoke=release_smoke),
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


def _diagnostics_bundle_check(
    *,
    tmp_dir: Path,
    plan_only: bool,
) -> dict[str, Any]:
    output_zip = tmp_dir / "diagnostics.zip"
    command = [
        sys.executable,
        "scripts/collect_release_diagnostics.py",
        "--label",
        "public-release-gate",
        "--include",
        str(tmp_dir),
        "--output-zip",
        str(output_zip),
    ]
    base: dict[str, Any] = {
        "id": "diagnostics_export",
        "label": "Redacted public release diagnostics bundle",
        "command": command,
        "output_zip": _display_path(output_zip),
    }
    if plan_only:
        return {**base, "status": "planned"}
    result = _run_command(command)
    manifest = _load_diagnostics_manifest(output_zip)
    status = "passed" if result.returncode == 0 and manifest.get("ok") is True else "failed"
    return {
        **base,
        "status": status,
        "returncode": result.returncode,
        "included_count": int(manifest.get("included_count") or 0),
        "skipped_count": int(manifest.get("skipped_count") or 0),
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
    }


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
        "full_demo_command": _full_demo_command(),
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


def _release_smoke_assessment(
    *,
    tmp_dir: Path,
    checks: Sequence[GateCheck],
    extra_reports: Sequence[Path | str],
    diagnostics_zips: Sequence[Path | str],
    plan_only: bool,
) -> dict[str, Any]:
    output_json = tmp_dir / "release-smoke.json"
    output_markdown = tmp_dir / "release-smoke.md"
    report_paths = [_resolve_path(Path(path)) for path in extra_reports]
    for check in checks:
        if check.id == "public_demo" and check.report_json is not None:
            report_paths.append(check.report_json)
    command: list[str] = [
        sys.executable,
        "scripts/summarize_release_smoke.py",
        *[str(path) for path in report_paths],
    ]
    for archive_path in diagnostics_zips:
        command.extend(["--diagnostics-zip", str(_resolve_path(Path(archive_path)))])
    command.extend(
        [
            "--output-json",
            str(output_json),
            "--output-markdown",
            str(output_markdown),
        ]
    )
    base: dict[str, Any] = {
        "command": command,
        "report_json": _display_path(output_json),
        "report_markdown": _display_path(output_markdown),
    }
    if plan_only:
        return {**base, "status": "planned", "ok": False}
    result = _run_command(command)
    report = _load_json(output_json)
    if not report:
        return {
            **base,
            "ok": False,
            "status": "failed",
            "returncode": result.returncode,
            "stdout_tail": _tail(result.stdout),
            "stderr_tail": _tail(result.stderr),
        }
    return {
        **base,
        "ok": report.get("ok") is True,
        "status": str(report.get("status") or "unknown"),
        "returncode": result.returncode,
        "item_count": int(report.get("item_count") or 0),
        "passed_count": int(report.get("passed_count") or 0),
        "missing_count": int(report.get("missing_count") or 0),
        "missing_item_ids": _string_list(report.get("missing_item_ids")),
        "next_actions": _dict_list(report.get("next_actions")),
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
    }


def _release_smoke_blockers(assessment: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not assessment:
        return []
    if assessment.get("ok") is True:
        return []
    if assessment.get("status") == "planned":
        return []
    missing = _string_list(assessment.get("missing_item_ids"))
    if missing:
        return [
            {
                "id": item_id,
                "status": "missing",
                "reason": "release-smoke evidence is missing",
            }
            for item_id in missing
        ]
    return [
        {
            "id": "release_smoke",
            "status": str(assessment.get("status") or "failed"),
            "reason": "release-smoke summary did not pass",
        }
    ]


def _next_actions(
    checks: Sequence[Mapping[str, Any]],
    *,
    release_smoke: Mapping[str, Any],
) -> list[dict[str, Any]]:
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
    for action in _dict_list(release_smoke.get("next_actions")):
        command = str(action.get("command") or "").strip()
        if not command or command in seen:
            continue
        seen.add(command)
        actions.append(
            {
                "id": str(action.get("id") or "release_smoke"),
                "status": "missing",
                "command": command,
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
    release_smoke = summary.get("release_smoke")
    if isinstance(release_smoke, Mapping) and release_smoke:
        lines.extend(["", "## Release Smoke", ""])
        lines.append(f"Status: {release_smoke.get('status')}")
        item_count = release_smoke.get("item_count")
        passed_count = release_smoke.get("passed_count")
        if isinstance(item_count, int) and isinstance(passed_count, int):
            lines.append(f"Coverage: {passed_count}/{item_count} passed")
        missing_items = _string_list(release_smoke.get("missing_item_ids"))
        if missing_items:
            lines.append(f"Missing user paths: {', '.join(f'`{item}`' for item in missing_items)}")
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


def _load_diagnostics_manifest(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            data = json.loads(archive.read("diagnostics/manifest.json").decode("utf-8"))
    except Exception:
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
    parser.add_argument("--skip-release-smoke-assessment", action="store_true")
    parser.add_argument("--release-smoke-report", action="append", default=[], type=Path)
    parser.add_argument("--diagnostics-zip", action="append", default=[], type=Path)
    parser.add_argument("--skip-diagnostics-bundle", action="store_true")
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
        include_release_smoke=not args.skip_release_smoke_assessment,
        release_smoke_reports=args.release_smoke_report,
        diagnostics_zips=args.diagnostics_zip,
        include_diagnostics_bundle=not args.skip_diagnostics_bundle,
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
