#!/usr/bin/env python3
"""Run the cheap public-release preflight and summarize remaining evidence."""

from __future__ import annotations

import argparse
import json
import os
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
from scripts.run_public_demo_smokes import demo_flows  # noqa: E402


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
    include_isolated_provider_smoke: bool = False,
    provider_manifest: Path | None = None,
    include_real_desktop: bool = False,
    include_real_desktop_open: bool = False,
    include_real_desktop_ui_inspection: bool = False,
    include_real_desktop_interaction: bool = False,
    allow_existing_real_desktop_app: bool = False,
    include_provider_workflow: bool = False,
    include_ui: bool = False,
    reuse_public_demo_evidence: bool = False,
) -> list[GateCheck]:
    oha_release_smoke_command = [
        sys.executable,
        "scripts/smoke_oha_desktop_agent_release.py",
        "--report-json",
        str(tmp_dir / "oha-desktop-agent-release-smoke.json"),
    ]
    source_capabilities_json = tmp_dir / "rc-verification-source-capabilities.json"
    if include_isolated_provider_smoke or provider_manifest is not None:
        oha_release_smoke_command.append("--run-isolated-provider-smoke")
    if provider_manifest is not None:
        oha_release_smoke_command.extend(
            [
                "--use-configured-virtual-desktop-provider",
                "--provider-manifest",
                str(provider_manifest),
            ]
        )
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
            id="agent_market_parity",
            label="Hermes/Hanako-style Agent market parity evidence",
            command=(sys.executable, "scripts/summarize_agent_market_parity.py"),
        ),
        GateCheck(
            id="planner_runtime_tool_parity",
            label="Runtime Planner to executable tool parity smoke",
            command=(sys.executable, "scripts/smoke_planner_runtime_tool_parity.py"),
        ),
        GateCheck(
            id="source_capabilities",
            label="Source-level Chat, Studio, approval, artifact, and timeline evidence",
            command=(
                sys.executable,
                "scripts/verify_release_candidate.py",
                "--source-only",
                "--report-json",
                str(source_capabilities_json),
            ),
            report_json=source_capabilities_json,
        ),
        GateCheck(
            id="oha_desktop_agent_release_smoke",
            label="Oha desktop-agent Core, Executor, Studio product smoke",
            command=tuple(oha_release_smoke_command),
            report_json=tmp_dir / "oha-desktop-agent-release-smoke.json",
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
                "tests/test_oha_desktop_agent_release_smoke.py",
                "tests/test_oha_parity_summary.py",
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
        if include_real_desktop_open:
            command.append("--include-real-desktop-open")
        if include_real_desktop_ui_inspection:
            command.append("--include-real-desktop-ui-inspection")
        if include_real_desktop_interaction:
            command.append("--include-real-desktop-interaction")
        if allow_existing_real_desktop_app:
            command.append("--allow-existing-real-desktop-app")
        if include_provider_workflow:
            command.append("--include-provider-workflow")
        if include_ui:
            command.append("--include-ui")
        if reuse_public_demo_evidence:
            command.append("--reuse-existing-evidence")
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
    public_demo_reports: Sequence[Path | str] = (),
    diagnostics_zips: Sequence[Path | str] = (),
    include_diagnostics_bundle: bool = True,
    include_isolated_provider_smoke: bool = False,
    provider_manifest: Path | str | None = None,
    include_real_desktop: bool = False,
    include_real_desktop_open: bool = False,
    include_real_desktop_ui_inspection: bool = False,
    include_real_desktop_interaction: bool = False,
    allow_existing_real_desktop_app: bool = False,
    include_provider_workflow: bool = False,
    include_ui: bool = False,
    reuse_public_demo_evidence: bool = False,
    require_release_ready: bool = False,
    plan_only: bool = False,
) -> dict[str, Any]:
    resolved_tmp_dir = _resolve_path(Path(tmp_dir))
    resolved_tmp_dir.mkdir(parents=True, exist_ok=True)
    resolved_provider_manifest = (
        _resolve_path(Path(provider_manifest))
        if provider_manifest is not None
        else None
    )
    effective_include_isolated_provider_smoke = (
        include_isolated_provider_smoke
        or require_release_ready
        or resolved_provider_manifest is not None
    )
    checks = public_release_gate_checks(
        tmp_dir=resolved_tmp_dir,
        include_public_demo=include_public_demo,
        include_isolated_provider_smoke=effective_include_isolated_provider_smoke,
        provider_manifest=resolved_provider_manifest,
        include_real_desktop=include_real_desktop,
        include_real_desktop_open=include_real_desktop_open,
        include_real_desktop_ui_inspection=include_real_desktop_ui_inspection,
        include_real_desktop_interaction=include_real_desktop_interaction,
        allow_existing_real_desktop_app=allow_existing_real_desktop_app,
        include_provider_workflow=include_provider_workflow,
        include_ui=include_ui,
        reuse_public_demo_evidence=reuse_public_demo_evidence,
    )
    check_results = [
        _check_result(check, plan_only=plan_only)
        for check in checks
    ]
    release_smoke_report_paths = [
        _resolve_path(Path(path))
        for path in release_smoke_reports
    ]
    public_demo_report_paths = [
        _resolve_path(Path(path))
        for path in public_demo_reports
    ]
    freshness_check = _external_report_freshness_check(
        [*release_smoke_report_paths, *public_demo_report_paths],
        plan_only=plan_only,
    )
    stale_report_paths = _stale_external_report_paths(freshness_check)
    release_smoke_report_paths = [
        path
        for path in release_smoke_report_paths
        if _stable_path(path) not in stale_report_paths
    ]
    public_demo_report_paths = [
        path
        for path in public_demo_report_paths
        if _stable_path(path) not in stale_report_paths
    ]
    extra_public_demo_report_count = len(public_demo_report_paths)
    for check in checks:
        if check.id == "public_demo" and check.report_json is not None:
            public_demo_report_paths.append(check.report_json)
    _merge_public_demo_check_result(
        check_results,
        public_demo_report_paths,
        has_external_reports=extra_public_demo_report_count > 0,
        plan_only=plan_only,
    )
    if freshness_check:
        check_results.append(freshness_check)
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
            extra_reports=release_smoke_report_paths,
            public_demo_reports=public_demo_report_paths,
            diagnostics_zips=[*generated_diagnostics_zips, *diagnostics_zips],
            plan_only=plan_only,
        )
        if include_release_smoke
        else {}
    )
    public_demo = _best_public_demo_snapshot(
        _public_demo_snapshot_from_checks(check_results),
        _dict(release_smoke.get("public_demo")),
    )
    release_smoke_blockers = _release_smoke_blockers(release_smoke)
    effective_release_smoke_blockers = _effective_release_smoke_blockers(
        release_smoke_blockers,
        check_results=check_results,
    )
    release_blocker_count = len(demo_release_blockers) + len(effective_release_smoke_blockers)
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
    next_actions = _next_actions(check_results, release_smoke=release_smoke)
    external_requirements = _external_requirements(next_actions)
    progress = _release_progress_snapshot(
        check_results=check_results,
        public_demo=public_demo,
        release_smoke=release_smoke,
        release_ready=release_ready,
        release_blocker_count=release_blocker_count,
        external_requirements=external_requirements,
        plan_only=plan_only,
    )
    return {
        "ok": ok,
        "release_ready": release_ready,
        "status": status,
        "require_release_ready": require_release_ready,
        "include_isolated_provider_smoke": effective_include_isolated_provider_smoke,
        "provider_manifest": _display_path(resolved_provider_manifest),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tmp_dir": _display_path(resolved_tmp_dir),
        "check_count": len(check_results),
        "passed_count": sum(1 for item in check_results if item["status"] == "passed"),
        "failed_count": len(failed),
        "release_blocker_count": release_blocker_count,
        "external_requirement_count": len(external_requirements),
        "external_requirements": external_requirements,
        "progress": progress,
        "checks": check_results,
        "public_demo": public_demo,
        "release_smoke": release_smoke,
        "next_actions": next_actions,
    }


def _release_progress_snapshot(
    *,
    check_results: Sequence[Mapping[str, Any]],
    public_demo: Mapping[str, Any],
    release_smoke: Mapping[str, Any],
    release_ready: bool,
    release_blocker_count: int,
    external_requirements: Sequence[Mapping[str, Any]],
    plan_only: bool,
) -> dict[str, Any]:
    check_total = len(check_results)
    check_passed = sum(1 for item in check_results if item.get("status") == "passed")
    demo_total = _positive_int(public_demo.get("required_flow_count"))
    demo_passed = _bounded_count(
        public_demo.get("passed_required_flow_count"),
        total=demo_total,
    )
    smoke_total = _positive_int(release_smoke.get("item_count"))
    smoke_passed = _bounded_count(release_smoke.get("passed_count"), total=smoke_total)
    evidence_total = demo_total + smoke_total
    evidence_passed = demo_passed + smoke_passed
    combined_total = check_total + evidence_total
    combined_passed = check_passed + evidence_passed
    external_total = 1 if external_requirements else 0
    release_total = combined_total + external_total
    release_passed = combined_passed
    if release_ready and external_total:
        release_passed += external_total
    core_completion = _completion_percent(check_passed, check_total)
    evidence_completion = _completion_percent(evidence_passed, evidence_total)
    combined_completion = _completion_percent(combined_passed, combined_total)
    release_completion = _completion_percent(release_passed, release_total)
    if plan_only:
        stage = "planned"
    elif release_ready:
        stage = "ready"
    elif any(item.get("status") == "failed" for item in check_results):
        stage = "checks_failed"
    elif external_requirements:
        stage = "external_requirements"
    elif release_blocker_count:
        stage = "release_evidence"
    else:
        stage = "needs_release_evidence"
    return {
        "stage": stage,
        "code_completion_percent": core_completion,
        "core_code_completion_percent": core_completion,
        "release_evidence_completion_percent": evidence_completion,
        "combined_code_and_evidence_completion_percent": combined_completion,
        "legacy_combined_completion_percent": combined_completion,
        "release_completion_percent": release_completion,
        "publication_completion_percent": release_completion,
        "code_remaining_percent": round(100.0 - core_completion, 1),
        "core_code_remaining_percent": round(100.0 - core_completion, 1),
        "release_evidence_remaining_percent": round(100.0 - evidence_completion, 1),
        "combined_code_and_evidence_remaining_percent": round(
            100.0 - combined_completion,
            1,
        ),
        "legacy_combined_remaining_percent": round(100.0 - combined_completion, 1),
        "release_remaining_percent": round(100.0 - release_completion, 1),
        "publication_remaining_percent": round(100.0 - release_completion, 1),
        "core_code": {"passed": check_passed, "total": check_total},
        "release_evidence": {"passed": evidence_passed, "total": evidence_total},
        "publication": {"passed": release_passed, "total": release_total},
        "progress_basis": {
            "code_completion_percent": "automated_checks_only",
            "release_evidence_completion_percent": "public_demo_plus_release_smoke",
            "release_completion_percent": (
                "automated_checks_plus_release_evidence_plus_external_requirements"
            ),
        },
        "automated_checks": {"passed": check_passed, "total": check_total},
        "public_demo": {"passed": demo_passed, "total": demo_total},
        "release_smoke": {"passed": smoke_passed, "total": smoke_total},
        "external_requirements": len(external_requirements),
        "external_blocked": bool(external_requirements),
    }


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _bounded_count(value: Any, *, total: int) -> int:
    parsed = _positive_int(value)
    if total <= 0:
        return parsed
    return min(parsed, total)


def _completion_percent(passed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (passed / total) * 100.0)), 1)


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
    if check.id == "oha_desktop_agent_release_smoke" and status == "failed":
        blockers = _oha_desktop_agent_release_gate_blockers(check.report_json)
        if blockers:
            payload["status"] = "blocked"
            payload["failure_category"] = _oha_desktop_agent_failure_category(blockers)
            payload["release_blockers"] = blockers
    if check.id == "public_demo":
        payload.update(_public_demo_gate_fields(check.report_json, command=check.command))
        if payload.get("report_loaded") is True:
            payload["status"] = "passed"
        if payload.get("release_level") != "full_public_demo_ready":
            payload["release_blockers"] = _public_demo_release_blockers(payload)
    return payload


def _merge_public_demo_check_result(
    check_results: list[dict[str, Any]],
    report_paths: Sequence[Path],
    *,
    has_external_reports: bool,
    plan_only: bool,
) -> None:
    if plan_only or not report_paths:
        return
    existing = next((item for item in check_results if item.get("id") == "public_demo"), None)
    if existing is not None and not has_external_reports:
        return
    aggregate = _aggregate_public_demo_reports(report_paths)
    if not aggregate:
        return
    if existing is None:
        existing = {
            "id": "public_demo",
            "label": "Public demo smoke evidence",
            "command": [],
            "report_json": "",
            "status": "passed",
            "returncode": 0,
        }
        check_results.append(existing)
    existing.update(aggregate)
    existing["status"] = "passed"
    if existing.get("release_level") != "full_public_demo_ready":
        existing["release_blockers"] = _public_demo_release_blockers(existing)


def _aggregate_public_demo_reports(report_paths: Sequence[Path]) -> dict[str, Any]:
    reports = [_load_json(path) for path in report_paths]
    reports = [report for report in reports if _dict_list(report.get("flows"))]
    if not reports:
        return {}
    required_flow_ids = _public_demo_required_flow_ids(reports)
    passed_flow_ids: list[str] = []
    blocker_by_id: dict[str, dict[str, Any]] = {}
    sources: list[str] = []
    for path, report in zip(report_paths, [_load_json(path) for path in report_paths]):
        if not _dict_list(report.get("flows")):
            continue
        source = _display_path(path)
        if source not in sources:
            sources.append(source)
        for flow in _dict_list(report.get("flows")):
            flow_id = str(flow.get("id") or "").strip()
            if not flow_id:
                continue
            if flow.get("status") == "passed":
                if flow_id not in passed_flow_ids:
                    passed_flow_ids.append(flow_id)
            elif flow_id not in blocker_by_id:
                blocker_by_id[flow_id] = _public_demo_blocker_from_flow(flow)
        for blocker in _dict_list(report.get("release_blockers")):
            blocker_id = str(blocker.get("id") or "").strip()
            if blocker_id:
                blocker_by_id[blocker_id] = _more_informative_blocker(
                    blocker_by_id.get(blocker_id),
                    blocker,
                )
    missing_flow_ids = [flow_id for flow_id in required_flow_ids if flow_id not in passed_flow_ids]
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
    complete = bool(required_flow_ids) and not missing_flow_ids
    release_level = (
        "full_public_demo_ready"
        if complete
        else "blocked"
        if blocked
        else "partial_demo_ready"
    )
    return {
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
        "full_demo_command": _full_demo_command(),
        "public_demo_report_sources": sources,
        "report_loaded": True,
    }


def _public_demo_required_flow_ids(reports: Sequence[Mapping[str, Any]]) -> list[str]:
    canonical = [
        flow.id
        for flow in demo_flows(Path("tmp/public-demo-flow-catalog"))
        if flow.release_required
    ]
    if canonical:
        return canonical
    required: list[str] = []
    for report in reports:
        for flow in _dict_list(report.get("flows")):
            flow_id = str(flow.get("id") or "").strip()
            if flow_id and flow_id not in required:
                required.append(flow_id)
    return required


def _public_demo_blocker_from_flow(flow: Mapping[str, Any]) -> dict[str, Any]:
    evidence_summary = _dict(flow.get("evidence_summary"))
    blocking_conditions = _string_list(evidence_summary.get("blocking_conditions"))
    reason = (
        ", ".join(blocking_conditions)
        if len(blocking_conditions) > 1
        else str(
            evidence_summary.get("blocking_condition")
            or evidence_summary.get("error")
            or evidence_summary.get("reason")
            or flow.get("evidence_reason")
            or flow.get("opt_in_reason")
            or "required public demo flow has not passed"
        ).strip()
    )
    return {
        "id": str(flow.get("id") or ""),
        "label": str(flow.get("label") or ""),
        "category": str(flow.get("category") or ""),
        "status": str(flow.get("status") or "missing"),
        "opt_in_flag": str(flow.get("opt_in_flag") or ""),
        "opt_in_reason": str(flow.get("opt_in_reason") or ""),
        "reason": reason,
        "evidence_summary": evidence_summary,
        "command": " ".join(str(part) for part in flow.get("command") or []),
    }


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


def _public_demo_snapshot_from_checks(
    check_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    check = next(
        (
            item
            for item in check_results
            if item.get("id") == "public_demo"
            and (
                item.get("release_level")
                or item.get("required_flow_count")
                or item.get("missing_required_flow_ids")
            )
        ),
        {},
    )
    return _public_demo_snapshot(check)


def _best_public_demo_snapshot(
    *candidates: Mapping[str, Any],
) -> dict[str, Any]:
    snapshots = [_public_demo_snapshot(candidate) for candidate in candidates]
    snapshots = [snapshot for snapshot in snapshots if snapshot]
    if not snapshots:
        return {}
    return max(
        snapshots,
        key=lambda snapshot: (
            snapshot.get("complete") is True,
            int(snapshot.get("passed_required_flow_count") or 0),
            int(snapshot.get("required_flow_count") or 0),
            len(_string_list(snapshot.get("public_demo_report_sources"))),
            len(_string_list(snapshot.get("passed_required_flow_ids"))),
        ),
    )


def _public_demo_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        return {}
    missing_flow_ids = _string_list(value.get("missing_required_flow_ids"))
    required_flow_count = int(value.get("required_flow_count") or 0)
    if (
        not str(value.get("release_level") or "")
        and required_flow_count == 0
        and not missing_flow_ids
    ):
        return {}
    return {
        "release_level": str(value.get("release_level") or ""),
        "complete": bool(value.get("complete") is True),
        "selected_count": int(value.get("selected_count") or 0),
        "passed_count": int(value.get("passed_count") or 0),
        "required_flow_count": required_flow_count,
        "passed_required_flow_count": int(
            value.get("passed_required_flow_count") or 0
        ),
        "remaining_required_flow_count": len(missing_flow_ids),
        "required_flow_ids": _string_list(value.get("required_flow_ids")),
        "passed_required_flow_ids": _string_list(
            value.get("passed_required_flow_ids")
        ),
        "missing_required_flow_ids": missing_flow_ids,
        "release_blockers": _dict_list(value.get("release_blockers")),
        "full_demo_command": str(
            value.get("full_demo_command") or _full_demo_command()
        ),
        "public_demo_report_sources": _string_list(
            value.get("public_demo_report_sources") or value.get("source")
        ),
    }


def _release_smoke_assessment(
    *,
    tmp_dir: Path,
    checks: Sequence[GateCheck],
    extra_reports: Sequence[Path | str],
    public_demo_reports: Sequence[Path | str],
    diagnostics_zips: Sequence[Path | str],
    plan_only: bool,
) -> dict[str, Any]:
    output_json = tmp_dir / "release-smoke.json"
    output_markdown = tmp_dir / "release-smoke.md"
    report_paths = [_resolve_path(Path(path)) for path in extra_reports]
    report_paths.extend(_resolve_path(Path(path)) for path in public_demo_reports)
    for check in checks:
        if check.report_json is None:
            continue
        resolved = check.report_json.resolve(strict=False)
        if all(path.resolve(strict=False) != resolved for path in report_paths):
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
        "public_demo": _dict(report.get("public_demo")),
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


def _effective_release_smoke_blockers(
    blockers: Sequence[Mapping[str, Any]],
    *,
    check_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    public_demo_expanded = any(
        check.get("id") == "public_demo" and _dict_list(check.get("release_blockers"))
        for check in check_results
    )
    if not public_demo_expanded:
        return [dict(blocker) for blocker in blockers]
    return [
        dict(blocker)
        for blocker in blockers
        if str(blocker.get("id") or "").strip() != "public_demo"
    ]


def _external_report_freshness_check(
    report_paths: Sequence[Path],
    *,
    plan_only: bool,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--require-artifacts",
        "--report-json",
        "tmp/rc-verification-current.json",
    ]
    base: dict[str, Any] = {
        "id": "external_report_freshness",
        "label": "External release evidence freshness",
        "command": command,
    }
    if plan_only:
        return {**base, "status": "planned"} if report_paths else {}
    current_commit = _current_git_commit()
    if not current_commit:
        return {}
    blockers: list[dict[str, Any]] = []
    seen_reports: set[Path] = set()
    for report_path in report_paths:
        resolved = _resolve_path(report_path)
        stable = resolved.resolve(strict=False)
        if stable in seen_reports:
            continue
        seen_reports.add(stable)
        report = _load_json(resolved)
        report_commit = _report_source_commit(report)
        if not report_commit or report_commit == current_commit:
            continue
        blockers.append(
            {
                "id": "stale_external_report",
                "status": "stale",
                "reason": (
                    f"{_display_path(resolved)} was generated for "
                    f"{_short_commit(report_commit)}, current HEAD is "
                    f"{_short_commit(current_commit)}"
                ),
                "report_json": _display_path(resolved),
                "report_commit": report_commit,
                "current_commit": current_commit,
            }
        )
    if not blockers:
        return {}
    return {
        **base,
        "status": "passed",
        "current_commit": current_commit,
        "stale_report_count": len(blockers),
        "release_blockers": blockers,
    }


def _stale_external_report_paths(freshness_check: Mapping[str, Any]) -> set[Path]:
    return {
        _stable_path(_resolve_path(Path(str(blocker.get("report_json") or ""))))
        for blocker in _dict_list(freshness_check.get("release_blockers"))
        if str(blocker.get("report_json") or "").strip()
    }


def _current_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _report_source_commit(report: Mapping[str, Any]) -> str:
    source_revision = report.get("source_revision")
    if isinstance(source_revision, Mapping):
        commit = str(source_revision.get("commit") or "").strip()
        if commit:
            return commit
    for section_name in (
        "dmg_app_smoke",
        "packaged_backend_bridge_smoke",
        "packaged_backend_smoke",
    ):
        section = report.get(section_name)
        if not isinstance(section, Mapping):
            continue
        for status in _dict_list(section.get("bridge_statuses")):
            build_metadata = _dict(status.get("build_metadata"))
            commit = str(build_metadata.get("commit") or "").strip()
            if commit:
                return commit
    return ""


def _short_commit(commit: str) -> str:
    return commit[:8] if commit else "unknown"


def _stable_path(path: Path) -> Path:
    return path.resolve(strict=False)


def _next_actions(
    checks: Sequence[Mapping[str, Any]],
    *,
    release_smoke: Mapping[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_action_ids: set[str] = set()
    for check in checks:
        if check.get("id") == "public_demo" and check.get("release_level") != "full_public_demo_ready":
            for action in _public_demo_next_actions(check):
                command = str(action.get("command") or "").strip()
                action_id = str(action.get("id") or "public_demo")
                if not command or command in seen:
                    continue
                seen.add(command)
                seen_action_ids.add(action_id)
                seen_action_ids.add("public_demo")
                actions.append(action)
            continue
        command = " ".join(str(part) for part in check.get("command") or [])
        if not command or command in seen:
            continue
        if check.get("status") == "passed" and not _dict_list(check.get("release_blockers")):
            continue
        action_id = str(check.get("id") or "next_action")
        seen.add(command)
        seen_action_ids.add(action_id)
        actions.append(
            {
                "id": action_id,
                "status": str(check.get("status") or ""),
                "command": command,
                "release_level": str(check.get("release_level") or ""),
                "missing_required_flow_ids": _string_list(check.get("missing_required_flow_ids")),
                "release_blockers": _dict_list(check.get("release_blockers")),
            }
        )
    for action in _dict_list(release_smoke.get("next_actions")):
        action_id = str(action.get("id") or "release_smoke")
        if action_id in seen_action_ids:
            continue
        command = str(action.get("command") or "").strip()
        if not command or command in seen:
            continue
        seen.add(command)
        seen_action_ids.add(action_id)
        actions.append(
            {
                "id": action_id,
                "status": "missing",
                "command": command,
                "release_level": str(action.get("release_level") or ""),
                "missing_required_flow_ids": _string_list(action.get("missing_required_flow_ids")),
                "release_blockers": _dict_list(action.get("release_blockers")),
            }
        )
    return actions


def _external_requirements(actions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    requirements: dict[str, dict[str, Any]] = {}
    for action in actions:
        action_id = str(action.get("id") or "").strip()
        if action_id == "public_demo_real_desktop":
            _merge_external_requirement(
                requirements,
                requirement_id="real_desktop_smoke_opt_in",
                label="Real desktop smoke opt-in",
                kind="desktop_operation",
                action=action,
            )
        elif action_id == "public_demo_provider":
            _merge_external_requirement(
                requirements,
                requirement_id="provider_smoke_credentials",
                label="Provider Workflow smoke credentials",
                kind="provider_credentials",
                action=action,
            )
        elif action_id == "workflow" and _action_runs_provider_smoke(action):
            _merge_external_requirement(
                requirements,
                requirement_id="provider_smoke_credentials",
                label="Provider Workflow smoke credentials",
                kind="provider_credentials",
                action=action,
            )
        elif action_id == "oha_desktop_agent_release_smoke" and _action_has_blocking_condition(
            action,
            "local_loopback_permission_required",
        ):
            _merge_external_requirement(
                requirements,
                requirement_id="local_loopback_permission",
                label="Local loopback permission for isolated desktop provider smoke",
                kind="local_permission",
                action=action,
            )
        elif action_id in {
            "oha_desktop_agent_product",
            "oha_desktop_agent_release_smoke",
        } and _action_has_blocking_condition(
            action,
            "real_virtual_desktop_backend_required",
        ):
            _merge_external_requirement(
                requirements,
                requirement_id="real_virtual_desktop_backend",
                label="Real virtual desktop backend",
                kind="desktop_backend",
                action=action,
            )
    order = {
        "real_desktop_smoke_opt_in": 0,
        "provider_smoke_credentials": 1,
        "local_loopback_permission": 2,
        "real_virtual_desktop_backend": 3,
    }
    return sorted(
        requirements.values(),
        key=lambda item: order.get(str(item.get("id") or ""), 99),
    )


def _merge_external_requirement(
    requirements: dict[str, dict[str, Any]],
    *,
    requirement_id: str,
    label: str,
    kind: str,
    action: Mapping[str, Any],
) -> None:
    requirement = requirements.setdefault(
        requirement_id,
        {
            "id": requirement_id,
            "label": label,
            "kind": kind,
            "status": "missing",
            "missing_required_flow_ids": [],
            "missing_env": [],
            "opt_in_flags": [],
            "opt_in_reasons": [],
            "blocking_conditions": [],
            "commands": [],
            "release_blockers": [],
        },
    )
    _append_unique(
        requirement["missing_required_flow_ids"],
        _string_list(action.get("missing_required_flow_ids")),
    )
    command = str(action.get("command") or "").strip()
    if command:
        _append_unique(requirement["commands"], [command])
    if kind == "provider_credentials" and "--run-provider-smoke" in command:
        missing_env = [
            name for name in PROVIDER_SMOKE_ENV_VARS if not os.getenv(name, "").strip()
        ]
        _append_unique(requirement["missing_env"], missing_env)
        if missing_env:
            _append_unique(
                requirement["blocking_conditions"],
                ["provider_smoke_credentials_missing"],
            )
    blockers = _dict_list(action.get("release_blockers"))
    if blockers:
        requirement["release_blockers"].extend(blockers)
    for blocker in blockers:
        evidence_summary = _dict(blocker.get("evidence_summary"))
        flow_id = str(blocker.get("id") or "").strip()
        flow_flag_info = PUBLIC_DEMO_FLOW_FLAGS.get(flow_id)
        fallback_opt_in_flag = flow_flag_info[1] if flow_flag_info else ""
        _append_unique(
            requirement["opt_in_flags"],
            _string_list(blocker.get("opt_in_flag") or fallback_opt_in_flag),
        )
        _append_unique(
            requirement["opt_in_reasons"],
            _string_list(
                blocker.get("opt_in_reason")
                or PUBLIC_DEMO_FLOW_OPT_IN_REASONS.get(flow_id, "")
            ),
        )
        _append_unique(
            requirement["missing_env"],
            _string_list(evidence_summary.get("missing_env")),
        )
        structured_conditions = [
            *_string_list(evidence_summary.get("blocking_conditions")),
            *_string_list(evidence_summary.get("blocking_condition")),
        ]
        _append_unique(
            requirement["blocking_conditions"],
            structured_conditions,
        )
        reason = str(blocker.get("reason") or "").strip()
        if reason and not structured_conditions:
            _append_unique(requirement["blocking_conditions"], [reason])


def _action_runs_provider_smoke(action: Mapping[str, Any]) -> bool:
    command = str(action.get("command") or "").strip()
    return "--run-provider-smoke" in command


def _action_has_blocking_condition(
    action: Mapping[str, Any],
    condition: str,
) -> bool:
    clean_condition = str(condition or "").strip()
    if not clean_condition:
        return False
    for blocker in _dict_list(action.get("release_blockers")):
        evidence_summary = _dict(blocker.get("evidence_summary"))
        conditions = [
            *_string_list(evidence_summary.get("blocking_condition")),
            *_string_list(evidence_summary.get("blocking_conditions")),
            str(blocker.get("reason") or "").strip(),
        ]
        if clean_condition in conditions:
            return True
    return False


def _oha_desktop_agent_release_gate_blockers(
    report_json: Path | None,
) -> list[dict[str, Any]]:
    report = _load_json(report_json)
    provider_blockers = _oha_desktop_agent_provider_release_blockers(report)
    if provider_blockers:
        return provider_blockers
    for section in _dict_list(report.get("sections")):
        if str(section.get("id") or "").strip() != "isolated_desktop_provider":
            continue
        if section.get("ok") is True:
            return []
        error = str(section.get("error") or "").strip()
        if "Operation not permitted" not in error and "Errno 1" not in error:
            return []
        return [
            {
                "id": "oha_isolated_desktop_provider_loopback_permission",
                "status": "blocked",
                "reason": "local_loopback_permission_required",
                "evidence_summary": {
                    "blocking_condition": "local_loopback_permission_required",
                    "error": error,
                    "recovery_hints": [
                        "rerun the release gate outside the restricted sandbox",
                        "or allow python scripts/run_public_release_gate.py to bind the local isolated provider smoke server",
                    ],
                },
            }
        ]
    return []


def _oha_desktop_agent_provider_release_blockers(
    report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if report.get("isolated_provider_smoke_requested") is not True:
        return []
    if report.get("configured_virtual_desktop_provider_requested") is not True:
        return []
    if report.get("isolated_provider_release_ready") is True:
        return []
    blockers: list[str] = []
    _append_unique(
        blockers,
        _string_list(report.get("isolated_provider_release_blockers")),
    )
    backend = _dict(report.get("isolated_provider_backend"))
    _append_unique(
        blockers,
        _string_list(backend.get("provider_contract_blocking_conditions")),
    )
    _append_unique(
        blockers,
        _string_list(backend.get("provider_conformance_release_blocking_conditions")),
    )
    if not blockers:
        return []
    release_provider_conditions = {
        "configured_virtual_desktop_provider_required",
        "loopback_desktop_backend",
        "desktop_backend_not_release_ready",
        "real_virtual_desktop_backend_required",
        "virtual_desktop_provider_contract_not_ready",
    }
    if not any(condition in release_provider_conditions for condition in blockers):
        return []
    requires_real_backend = (
        "real_virtual_desktop_backend_required" in blockers
        or backend.get("requires_real_virtual_desktop_backend") is True
        or backend.get("desktop_backend_is_loopback") is True
    )
    reason = (
        "real_virtual_desktop_backend_required"
        if requires_real_backend
        else "virtual_desktop_provider_contract_not_ready"
    )
    blocker_id = (
        "oha_real_virtual_desktop_backend"
        if requires_real_backend
        else "oha_virtual_desktop_provider_contract"
    )
    evidence_summary: dict[str, Any] = {
        "blocking_condition": reason,
        "blocking_conditions": blockers,
        "recovery_hints": [
            "write and validate a virtual desktop provider manifest",
            (
                "rerun the smoke with --use-configured-virtual-desktop-provider "
                "and --provider-manifest"
            ),
        ],
    }
    for key in (
        "desktop_session_kind",
        "desktop_session_isolated",
        "foreground_takeover_required",
        "keyboard_mouse_capture_supported",
        "desktop_backend_kind",
        "desktop_backend_is_loopback",
        "desktop_backend_ready_for_public_release",
        "requires_real_virtual_desktop_backend",
        "provider_contract_ok",
        "provider_contract_version",
        "provider_contract_blocking_conditions",
        "provider_conformance_ok",
        "provider_conformance_mode",
        "provider_conformance_smoke_ok",
        "provider_conformance_public_release_ready",
        "provider_conformance_release_candidate",
        "provider_conformance_release_blocking_conditions",
        "provider_conformance_missing_required_tools",
        "provider_conformance_failed_tools",
    ):
        if backend.get(key) not in (None, "", [], {}):
            evidence_summary[key] = backend.get(key)
    return [
        {
            "id": blocker_id,
            "status": "missing" if requires_real_backend else "blocked",
            "reason": reason,
            "evidence_summary": evidence_summary,
        }
    ]


def _oha_desktop_agent_failure_category(
    blockers: Sequence[Mapping[str, Any]],
) -> str:
    for blocker in blockers:
        summary = _dict(blocker.get("evidence_summary"))
        conditions = [
            str(blocker.get("reason") or "").strip(),
            *_string_list(summary.get("blocking_condition")),
            *_string_list(summary.get("blocking_conditions")),
        ]
        if "real_virtual_desktop_backend_required" in conditions:
            return "real_virtual_desktop_backend"
        if "local_loopback_permission_required" in conditions:
            return "local_loopback_permission"
    return "external_requirement"


def _append_unique(target: list[Any], values: Sequence[Any]) -> None:
    for value in values:
        if value in (None, "", [], {}):
            continue
        if value not in target:
            target.append(value)


PUBLIC_DEMO_FLOW_FLAGS: dict[str, tuple[str, str]] = {
    "real_desktop_app_open": ("real_desktop", "--include-real-desktop-open"),
    "real_desktop_ui_inspection": ("real_desktop", "--include-real-desktop-ui-inspection"),
    "real_desktop_interaction": ("real_desktop", "--include-real-desktop-interaction"),
    "workflow_provider": ("provider", "--include-provider-workflow"),
    "studio_replay_ui": ("ui", "--include-ui"),
    "workflow_ui": ("ui", "--include-ui"),
}

PROVIDER_SMOKE_ENV_VARS: tuple[str, ...] = (
    "OHA_YACHIYO_SMOKE_BASE_URL",
    "OHA_YACHIYO_SMOKE_MODEL",
    "OHA_YACHIYO_SMOKE_API_KEY",
)

PUBLIC_DEMO_FLOW_OPT_IN_REASONS: dict[str, str] = {
    flow.id: flow.opt_in_reason
    for flow in demo_flows(Path("tmp/public-demo-flow-catalog"))
    if flow.opt_in_reason
}

PUBLIC_DEMO_GROUP_LABELS: dict[str, str] = {
    "real_desktop": "Real desktop public demo evidence",
    "provider": "Provider Workflow public demo evidence",
    "ui": "UI public demo evidence",
}

PUBLIC_DEMO_GROUP_OUTPUT_SLUGS: dict[str, str] = {
    "real_desktop": "real-desktop",
    "provider": "provider",
    "ui": "ui",
}


def _public_demo_next_actions(check: Mapping[str, Any]) -> list[dict[str, Any]]:
    grouped_flags: dict[str, list[str]] = {}
    grouped_missing: dict[str, list[str]] = {}
    grouped_blockers: dict[str, list[dict[str, Any]]] = {}
    missing_ids = _string_list(check.get("missing_required_flow_ids"))
    blockers = _dict_list(check.get("release_blockers"))
    blocker_by_id = {
        str(blocker.get("id") or "").strip(): blocker
        for blocker in blockers
        if str(blocker.get("id") or "").strip()
    }
    unknown_missing_ids: list[str] = []
    for blocker in blockers:
        flag = str(blocker.get("opt_in_flag") or "").strip()
        flow_id = str(blocker.get("id") or "").strip()
        group = str(blocker.get("category") or "").strip()
        if not group and flow_id in PUBLIC_DEMO_FLOW_FLAGS:
            group = PUBLIC_DEMO_FLOW_FLAGS[flow_id][0]
        if not group:
            continue
        if flag:
            grouped_flags.setdefault(group, [])
            if flag not in grouped_flags[group]:
                grouped_flags[group].append(flag)
        if flow_id:
            grouped_missing.setdefault(group, [])
            if flow_id not in grouped_missing[group]:
                grouped_missing[group].append(flow_id)
        grouped_blockers.setdefault(group, []).append(blocker)
    for flow_id in missing_ids:
        flag_info = PUBLIC_DEMO_FLOW_FLAGS.get(flow_id)
        if flag_info:
            group, flag = flag_info
            grouped_flags.setdefault(group, [])
            if flag not in grouped_flags[group]:
                grouped_flags[group].append(flag)
            grouped_missing.setdefault(group, [])
            if flow_id not in grouped_missing[group]:
                grouped_missing[group].append(flow_id)
            if flow_id in blocker_by_id:
                grouped_blockers.setdefault(group, [])
        else:
            unknown_missing_ids.append(flow_id)
    if not grouped_flags or unknown_missing_ids:
        command = str(check.get("full_demo_command") or "") or _full_demo_command()
        return [
            {
                "id": "public_demo",
                "status": str(check.get("status") or ""),
                "command": command,
                "release_level": str(check.get("release_level") or ""),
                "missing_required_flow_ids": missing_ids,
                "release_blockers": blockers,
            }
        ]
    actions: list[dict[str, Any]] = []
    for group in ("real_desktop", "provider", "ui"):
        flags = grouped_flags.get(group)
        if not flags:
            continue
        command_flags = list(flags)
        if group == "real_desktop" and _has_app_already_running_blocker(
            grouped_blockers.get(group, [])
        ):
            command_flags.append("--allow-existing-real-desktop-app")
        suffix = PUBLIC_DEMO_GROUP_OUTPUT_SLUGS.get(group, group)
        command = (
            "python scripts/run_public_demo_smokes.py "
            + " ".join(command_flags)
            + f" --output-json tmp/public-demo-smokes-{suffix}-missing.json "
            + f"--output-markdown tmp/public-demo-smokes-{suffix}-missing.md"
        )
        actions.append(
            {
                "id": f"public_demo_{group}",
                "status": str(check.get("status") or ""),
                "command": command,
                "release_level": str(check.get("release_level") or ""),
                "missing_required_flow_ids": grouped_missing.get(group, []),
                "release_blockers": grouped_blockers.get(group, []),
                "label": PUBLIC_DEMO_GROUP_LABELS.get(group, "Public demo evidence"),
            }
        )
    return actions


def _has_app_already_running_blocker(blockers: Sequence[Mapping[str, Any]]) -> bool:
    for blocker in blockers:
        if str(blocker.get("id") or "") != "real_desktop_interaction":
            continue
        summary = _dict(blocker.get("evidence_summary"))
        values = [
            str(blocker.get("reason") or ""),
            str(summary.get("error") or ""),
            str(summary.get("reason") or ""),
        ]
        if any(value.strip() == "app_already_running" for value in values):
            return True
    return False


def _public_demo_next_command(check: Mapping[str, Any]) -> str:
    actions = _public_demo_next_actions(check)
    if not actions:
        return ""
    if len(actions) == 1:
        return str(actions[0].get("command") or "")
    combined_flags: list[str] = []
    for action in actions:
        command = str(action.get("command") or "")
        for part in command.split():
            if (
                part.startswith("--include-") or part.startswith("--allow-")
            ) and part not in combined_flags:
                combined_flags.append(part)
    if not combined_flags:
        return str(actions[0].get("command") or "")
    return (
        "python scripts/run_public_demo_smokes.py "
        + " ".join(combined_flags)
        + " --output-json tmp/public-demo-smokes-missing.json "
        + "--output-markdown tmp/public-demo-smokes-missing.md"
    )


def render_markdown(summary: Mapping[str, Any]) -> str:
    progress = _dict(summary.get("progress"))
    lines = [
        "# Oha-Yachiyo Public Release Gate",
        "",
        f"Status: {summary.get('status')}",
        f"Release ready: {str(bool(summary.get('release_ready'))).lower()}",
        f"Release blockers: {int(summary.get('release_blocker_count') or 0)}",
        f"External requirements: {int(summary.get('external_requirement_count') or 0)}",
        f"Checks: {summary.get('passed_count')}/{summary.get('check_count')} passed",
    ]
    if progress:
        core_percent = progress.get(
            "core_code_completion_percent",
            progress.get("code_completion_percent"),
        )
        core_remaining = progress.get(
            "core_code_remaining_percent",
            progress.get("code_remaining_percent"),
        )
        publication_percent = progress.get(
            "publication_completion_percent",
            progress.get("release_completion_percent"),
        )
        publication_remaining = progress.get(
            "publication_remaining_percent",
            progress.get("release_remaining_percent"),
        )
        lines.extend(
            [
                f"Progress stage: `{progress.get('stage')}`",
                (
                    "Core code progress: "
                    f"{core_percent}% "
                    f"({core_remaining}% remaining)"
                ),
                (
                    "Release evidence progress: "
                    f"{progress.get('release_evidence_completion_percent')}% "
                    f"({progress.get('release_evidence_remaining_percent')}% remaining)"
                ),
                (
                    "Publication progress: "
                    f"{publication_percent}% "
                    f"({publication_remaining}% remaining)"
                ),
            ]
        )
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
                + ", ".join(f"`{item}`" for item in missing_flows)
            )
    lines.extend(["", "## Checks", ""])
    for check in _dict_list(summary.get("checks")):
        marker = "x" if check.get("status") == "passed" else " "
        lines.append(f"- [{marker}] `{check.get('id')}` - {check.get('status')} - {check.get('label')}")
        release_level = str(check.get("release_level") or "")
        if release_level:
            lines.append(f"  Release level: `{release_level}`")
        missing = _string_list(check.get("missing_required_flow_ids"))
        if missing:
            lines.append(f"  Missing demo flows: {', '.join(f'`{item}`' for item in missing)}")
        for blocker in _dict_list(check.get("release_blockers")):
            blocker_id = str(blocker.get("id") or "").strip()
            reason = str(blocker.get("reason") or "").strip()
            if blocker_id and reason:
                lines.append(f"  Demo blocker `{blocker_id}`: `{reason}`")
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
    external_requirements = _dict_list(summary.get("external_requirements"))
    if external_requirements:
        lines.extend(["", "## External Requirements", ""])
        for requirement in external_requirements:
            lines.append(f"- `{requirement.get('id')}` - {requirement.get('label')}")
            missing_flows = _string_list(requirement.get("missing_required_flow_ids"))
            if missing_flows:
                lines.append(
                    "  Missing demo flows: "
                    + ", ".join(f"`{item}`" for item in missing_flows)
                )
            missing_env = _string_list(requirement.get("missing_env"))
            if missing_env:
                lines.append(
                    "  Missing env: "
                    + ", ".join(f"`{item}`" for item in missing_env)
                )
            opt_in_flags = _string_list(requirement.get("opt_in_flags"))
            if opt_in_flags:
                lines.append(
                    "  Opt-in flags: "
                    + ", ".join(f"`{item}`" for item in opt_in_flags)
                )
            opt_in_reasons = _string_list(requirement.get("opt_in_reasons"))
            if opt_in_reasons:
                lines.append(
                    "  Opt-in reasons: "
                    + "; ".join(opt_in_reasons)
                )
            blocking_conditions = _string_list(requirement.get("blocking_conditions"))
            if blocking_conditions:
                lines.append(
                    "  Conditions: "
                    + ", ".join(f"`{item}`" for item in blocking_conditions)
                )
            commands = _string_list(requirement.get("commands"))
            for command in commands:
                lines.extend(["", "```bash", command, "```", ""])
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
                    + ", ".join(f"`{item}`" for item in missing_flows)
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


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _full_demo_command() -> str:
    return (
        "python scripts/run_public_demo_smokes.py "
        "--include-ui "
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
    parser.add_argument("--public-demo-report", action="append", default=[], type=Path)
    parser.add_argument("--diagnostics-zip", action="append", default=[], type=Path)
    parser.add_argument("--skip-diagnostics-bundle", action="store_true")
    parser.add_argument("--include-isolated-provider-smoke", action="store_true")
    parser.add_argument(
        "--provider-manifest",
        type=Path,
        help=(
            "Provider manifest for the isolated Oha desktop-agent product smoke. "
            "Passing this also enables --include-isolated-provider-smoke."
        ),
    )
    parser.add_argument("--include-real-desktop", action="store_true")
    parser.add_argument("--include-real-desktop-open", action="store_true")
    parser.add_argument("--include-real-desktop-ui-inspection", action="store_true")
    parser.add_argument("--include-real-desktop-interaction", action="store_true")
    parser.add_argument("--allow-existing-real-desktop-app", action="store_true")
    parser.add_argument("--include-provider-workflow", action="store_true")
    parser.add_argument("--include-ui", action="store_true")
    parser.add_argument("--reuse-public-demo-evidence", action="store_true")
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
        public_demo_reports=args.public_demo_report,
        diagnostics_zips=args.diagnostics_zip,
        include_diagnostics_bundle=not args.skip_diagnostics_bundle,
        include_isolated_provider_smoke=bool(args.include_isolated_provider_smoke),
        provider_manifest=args.provider_manifest,
        include_real_desktop=bool(args.include_real_desktop),
        include_real_desktop_open=bool(args.include_real_desktop_open),
        include_real_desktop_ui_inspection=bool(args.include_real_desktop_ui_inspection),
        include_real_desktop_interaction=bool(args.include_real_desktop_interaction),
        allow_existing_real_desktop_app=bool(args.allow_existing_real_desktop_app),
        include_provider_workflow=bool(args.include_provider_workflow),
        include_ui=bool(args.include_ui),
        reuse_public_demo_evidence=bool(args.reuse_public_demo_evidence),
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
