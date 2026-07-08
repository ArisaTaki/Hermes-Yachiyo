#!/usr/bin/env python3
"""Build an Oha-Yachiyo parity/readiness summary from signoff evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from packages.security import sanitize_sensitive_value


PRODUCT_IDENTITY_REQUIREMENTS: tuple[dict[str, str], ...] = (
    {
        "id": "electron_app_id",
        "path": "apps/frontend/electron-builder.yml",
        "fragment": "appId: io.github.arisataki.oha-yachiyo",
        "label": "Electron app id is Oha-Yachiyo",
    },
    {
        "id": "electron_product_name",
        "path": "apps/frontend/electron-builder.yml",
        "fragment": "productName: Oha-Yachiyo",
        "label": "Electron product name is Oha-Yachiyo",
    },
    {
        "id": "dmg_artifact_name",
        "path": "apps/frontend/electron-builder.yml",
        "fragment": "artifactName: Oha-Yachiyo-${version}-${arch}.${ext}",
        "label": "DMG artifact uses Oha-Yachiyo name",
    },
    {
        "id": "release_workflow_oha_branch",
        "path": ".github/workflows/release-macos.yml",
        "fragment": "- oha-develop",
        "label": "Oha experimental release branch is oha-develop",
    },
    {
        "id": "legacy_develop_reserved",
        "path": "docs/release-packaging.md",
        "fragment": "`develop` 分支保留给彻底重构前的旧版发布线，不触发 Oha DMG",
        "label": "Legacy develop branch is documented as non-Oha release line",
    },
    {
        "id": "oha_latest_dmg",
        "path": "docs/release-packaging.md",
        "fragment": "Oha-Yachiyo-oha-develop-latest.dmg",
        "label": "Experimental latest DMG uses oha-develop channel",
    },
)


SIGNOFF_AREAS: tuple[dict[str, str], ...] = (
    {
        "id": "gatekeeper_first_launch",
        "label": "Gatekeeper first launch",
        "check_id": "gatekeeper_first_launch",
        "parity_surface": "macOS distribution",
    },
    {
        "id": "packaged_bridge_isolation",
        "label": "Packaged Bridge isolation",
        "check_id": "packaged_bridge_isolation",
        "parity_surface": "packaged runtime",
    },
    {
        "id": "screen_recording_permission",
        "label": "Packaged screen capture permission path",
        "check_id": "screen_recording_permission",
        "parity_surface": "desktop observation",
    },
    {
        "id": "chat_native_file_upload",
        "label": "Chat native image attachment flow",
        "check_id": "chat_native_file_upload",
        "parity_surface": "chat",
    },
    {
        "id": "packaged_ui_sampling",
        "label": "Packaged mature UI surface sampling",
        "check_id": "packaged_ui_sampling",
        "parity_surface": "frontend parity",
    },
    {
        "id": "real_provider_agent_chain",
        "label": "Real provider Native Agent chain",
        "check_id": "real_provider_smoke",
        "parity_surface": "Native Agent",
    },
    {
        "id": "external_integrations",
        "label": "Live2D, GPT-SoVITS, and AstrBot external integrations",
        "check_id": "external_integrations_smoke",
        "parity_surface": "external ecosystem",
    },
)


OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE = "oha_desktop_agent_release_smoke"
OHA_DESKTOP_AGENT_REQUIRED_SECTIONS: tuple[str, ...] = (
    "deepagent_core",
    "shared_daily_surfaces",
    "desktop_executor_before_model",
    "legacy_facade_planner_ownership",
    "capability_planner_tool_parity",
    "data_analysis_artifacts",
    "agent_studio_orchestration",
    "group_run_timeline",
    "workflow_run_timeline",
    "approval_policy_gate",
    "studio_tool_catalog",
    "isolated_desktop_provider",
)
OHA_DESKTOP_AGENT_NEXT_ACTION = (
    "python scripts/smoke_oha_desktop_agent_release.py "
    "--run-isolated-provider-smoke "
    "--report-json tmp/oha-desktop-agent-release-smoke.json"
)


def _project_file(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve(strict=False)
    root_path = root.resolve(strict=False)
    try:
        candidate.relative_to(root_path)
    except ValueError:
        raise ValueError(f"path must stay inside project root: {relative_path}")
    return candidate


def _load_report(root: Path, path: Path) -> dict[str, Any]:
    report_path = path if path.is_absolute() else root / path
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"report must be a JSON object: {path}")
    return data


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _optional_report(root: Path, path: Path) -> dict[str, Any] | None:
    try:
        return _load_report(root, path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _checks_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_checks = report.get("checks")
    if not isinstance(raw_checks, list):
        raw_checks = report.get("manual_release_candidate_check_statuses")
    checks: dict[str, dict[str, Any]] = {}
    if isinstance(raw_checks, list):
        for item in raw_checks:
            if not isinstance(item, dict):
                continue
            check_id = str(item.get("id") or "").strip()
            if check_id:
                checks[check_id] = item
    return checks


def _status_from_check(check: dict[str, Any] | None) -> str:
    if not isinstance(check, dict):
        return "missing"
    status = str(check.get("status") or "").strip()
    return status or "missing"


def _manual_evidence_summary(check: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(check, dict):
        return {}
    summary: dict[str, Any] = {}
    evidence_source = str(check.get("evidence_source") or "").strip()
    evidence = str(check.get("evidence") or "").strip()
    notes = str(check.get("notes") or "").strip()
    if evidence_source:
        summary["evidence_source"] = evidence_source
    if evidence:
        summary["evidence_preview"] = evidence[:400]
    if notes:
        summary["notes_preview"] = notes[:400]
    return sanitize_sensitive_value(summary, max_depth=4)


def _manual_summary_items_by_id(
    manual_summary: dict[str, Any],
    key: str,
    value_key: str,
) -> dict[str, str]:
    raw_items = manual_summary.get(key)
    items: dict[str, str] = {}
    if not isinstance(raw_items, list):
        return items
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        check_id = str(item.get("id") or "").strip()
        value = str(item.get(value_key) or "").strip()
        if check_id and value:
            items[check_id] = value
    return items


def _product_identity_area(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for requirement in PRODUCT_IDENTITY_REQUIREMENTS:
        path = requirement["path"]
        fragment = requirement["fragment"]
        try:
            text = _project_file(root, path).read_text(encoding="utf-8")
            passed = fragment in text
        except OSError as exc:
            checks.append(
                {
                    "id": requirement["id"],
                    "label": requirement["label"],
                    "status": "missing",
                    "path": path,
                    "error": str(exc),
                }
            )
            continue
        checks.append(
            {
                "id": requirement["id"],
                "label": requirement["label"],
                "status": "passed" if passed else "missing",
                "path": path,
            }
        )
    missing = [item["id"] for item in checks if item["status"] != "passed"]
    return {
        "id": "product_release_identity",
        "label": "Oha product identity and split release line",
        "status": "passed" if not missing else "missing",
        "checks": checks,
        "missing_requirement_ids": missing,
    }


def _native_agent_area(report: dict[str, Any]) -> dict[str, Any]:
    matrix = report.get("native_agent_capability_matrix")
    if not isinstance(matrix, dict):
        return {
            "id": "native_agent_capability_matrix",
            "label": "Native Agent capability matrix",
            "status": "missing",
            "capability_count": 0,
            "missing_capability_ids": [],
        }
    missing_ids = matrix.get("missing_capability_ids")
    missing = [str(item) for item in missing_ids] if isinstance(missing_ids, list) else []
    status = str(matrix.get("status") or "").strip()
    ok = matrix.get("ok") is True and not missing
    return {
        "id": "native_agent_capability_matrix",
        "label": "Native Agent capability matrix",
        "status": "passed" if ok else status or "incomplete",
        "ok": ok,
        "capability_count": matrix.get("capability_count", 0),
        "status_counts": matrix.get("status_counts", {}),
        "missing_capability_ids": missing,
        "source_reports": matrix.get("source_reports", []),
    }


def _source_label_from_report_path(report_path: Path) -> str:
    name = report_path.name
    shapes = (
        ("rc-signoff-", "-current.json"),
        ("rc-signoff-", "-final.json"),
        ("rc-signoff-", "-preview.json"),
        ("rc-verification-", "-release-smoke.json"),
        ("rc-verification-", "-release-readiness.json"),
        ("rc-verification-", "-native-capability-matrix.json"),
        ("rc-verification-", "-source-capabilities.json"),
        ("rc-verification-", "-packaged-batch.json"),
        ("rc-verification-", "-screen.json"),
    )
    for prefix, suffix in shapes:
        if name.startswith(prefix) and name.endswith(suffix):
            return name[len(prefix) : -len(suffix)]
    return ""


def _candidate_oha_desktop_agent_smoke_paths(root: Path, report_path: Path) -> list[Path]:
    report = report_path if report_path.is_absolute() else root / report_path
    label = _source_label_from_report_path(report)
    candidates: list[Path] = []
    if label:
        filename = f"rc-verification-{label}-oha-desktop-agent-release-smoke.json"
        candidates.extend([report.parent / filename, root / "tmp" / filename])
    candidates.extend(
        [
            report.parent / "oha-desktop-agent-release-smoke.json",
            root / "tmp" / "oha-desktop-agent-release-smoke.json",
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _embedded_oha_desktop_agent_smoke(
    report: Mapping[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    if report.get("mode") == OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE:
        return "input_report", dict(report)
    for key in ("oha_desktop_agent_release_smoke", "oha_desktop_agent_smoke"):
        nested = report.get(key)
        if isinstance(nested, Mapping):
            return key, dict(nested)
    return None


def _release_smoke_oha_item(report: Mapping[str, Any]) -> dict[str, Any]:
    for item in _dict_list(report.get("items")):
        if str(item.get("id") or "").strip() == "oha_desktop_agent_product":
            return item
    return {}


def _load_oha_desktop_agent_smoke(
    root: Path,
    report_path: Path,
    report: Mapping[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    embedded = _embedded_oha_desktop_agent_smoke(report)
    if embedded is not None:
        return embedded
    for candidate in _candidate_oha_desktop_agent_smoke_paths(root, report_path):
        payload = _optional_report(root, candidate)
        if isinstance(payload, dict):
            return (_display_path(root, candidate), payload)
    return None


def _oha_desktop_agent_product_area_from_smoke(
    source: str,
    smoke: Mapping[str, Any],
) -> dict[str, Any]:
    sections = {
        str(section.get("id") or "").strip(): section
        for section in _dict_list(smoke.get("sections"))
        if str(section.get("id") or "").strip()
    }
    passed_sections = [
        section_id
        for section_id in OHA_DESKTOP_AGENT_REQUIRED_SECTIONS
        if sections.get(section_id, {}).get("ok") is True
    ]
    missing_sections = [
        section_id
        for section_id in OHA_DESKTOP_AGENT_REQUIRED_SECTIONS
        if section_id not in passed_sections
    ]
    failed_sections = _string_list(smoke.get("failed_sections"))
    for section_id in missing_sections:
        if section_id in sections and section_id not in failed_sections:
            failed_sections.append(section_id)
    ok = (
        smoke.get("mode") == OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE
        and smoke.get("ok") is True
        and not missing_sections
    )
    status = "passed" if ok else "failed" if failed_sections else "missing"
    area: dict[str, Any] = {
        "id": "oha_desktop_agent_product",
        "label": "Oha desktop-agent Core, Executor, and Studio product smoke",
        "status": status,
        "parity_surface": "desktop agent product",
        "source_report": source,
        "mode": str(smoke.get("mode") or ""),
        "required_section_count": len(OHA_DESKTOP_AGENT_REQUIRED_SECTIONS),
        "passed_section_count": len(passed_sections),
        "section_count": smoke.get("section_count", len(sections)),
        "passed_section_ids": passed_sections,
        "missing_section_ids": missing_sections,
        "failed_section_ids": failed_sections,
        "next_action": OHA_DESKTOP_AGENT_NEXT_ACTION,
    }
    checks = smoke.get("checks")
    if isinstance(checks, Mapping):
        area["checks"] = sanitize_sensitive_value(dict(checks), max_depth=4)
    return area


def _oha_desktop_agent_product_area_from_release_smoke_item(
    item: Mapping[str, Any],
) -> dict[str, Any]:
    status = str(item.get("status") or "").strip() or "missing"
    related = _string_list(item.get("related_evidence_ids"))
    return {
        "id": "oha_desktop_agent_product",
        "label": "Oha desktop-agent Core, Executor, and Studio product smoke",
        "status": "passed" if status == "passed" else "missing",
        "parity_surface": "desktop agent product",
        "required_evidence_ids": _string_list(item.get("required_evidence_ids")),
        "present_evidence_ids": _string_list(item.get("present_evidence_ids")),
        "missing_evidence_ids": _string_list(item.get("missing_evidence_ids")),
        "related_evidence_count": len(related),
        "related_evidence_ids": related,
        "next_action": str(item.get("next_action") or OHA_DESKTOP_AGENT_NEXT_ACTION),
    }


def _oha_desktop_agent_product_area(
    root: Path,
    report_path: Path,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    loaded = _load_oha_desktop_agent_smoke(root, report_path, report)
    if loaded is not None:
        source, smoke = loaded
        return _oha_desktop_agent_product_area_from_smoke(source, smoke)
    release_item = _release_smoke_oha_item(report)
    if release_item:
        return _oha_desktop_agent_product_area_from_release_smoke_item(release_item)
    return {
        "id": "oha_desktop_agent_product",
        "label": "Oha desktop-agent Core, Executor, and Studio product smoke",
        "status": "missing",
        "parity_surface": "desktop agent product",
        "required_before": "public_release_signoff",
        "required_evidence": (
            "Run the Oha desktop-agent release smoke so DeepAgent Core, "
            "desktop executor, Agent Studio, Groups, Workflow, Approval, and "
            "Artifact paths are visible in the parity summary."
        ),
        "next_action": OHA_DESKTOP_AGENT_NEXT_ACTION,
    }


def _signoff_areas(
    checks_by_id: dict[str, dict[str, Any]],
    manual_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    areas: list[dict[str, Any]] = []
    remaining_commands = _manual_summary_items_by_id(
        manual_summary,
        "remaining_commands",
        "command",
    )
    remaining_next_actions = _manual_summary_items_by_id(
        manual_summary,
        "remaining_next_actions",
        "next_action",
    )
    for definition in SIGNOFF_AREAS:
        check = checks_by_id.get(definition["check_id"])
        status = _status_from_check(check)
        check_id = definition["check_id"]
        area: dict[str, Any] = {
            "id": definition["id"],
            "label": definition["label"],
            "parity_surface": definition["parity_surface"],
            "manual_check_id": check_id,
            "status": status,
            "evidence_summary": _manual_evidence_summary(check),
        }
        if isinstance(check, dict):
            for source_key, target_key in (
                ("description", "description"),
                ("required_before", "required_before"),
                ("evidence_prompt", "required_evidence"),
            ):
                value = str(check.get(source_key) or "").strip()
                if value:
                    area[target_key] = value
            next_action = str(check.get("next_action") or "").strip()
            if next_action:
                area["next_action"] = next_action
        if check_id in remaining_next_actions:
            area["next_action"] = remaining_next_actions[check_id]
        if check_id in remaining_commands:
            area["recommended_command"] = remaining_commands[check_id]
        areas.append(area)
    return areas


def summarize_parity(root: Path, report_path: Path) -> dict[str, Any]:
    report = _load_report(root, report_path)
    checks = _checks_by_id(report)
    manual_summary = report.get("manual_release_candidate_check_summary")
    if not isinstance(manual_summary, dict):
        manual_summary = {}
    areas = [
        _product_identity_area(root),
        _native_agent_area(report),
        _oha_desktop_agent_product_area(root, report_path, report),
        *_signoff_areas(checks, manual_summary),
    ]
    incomplete_area_ids = [
        str(area["id"])
        for area in areas
        if area.get("status") not in {"passed", "not_applicable"}
    ]
    return {
        "ok": not incomplete_area_ids,
        "status": "passed" if not incomplete_area_ids else "incomplete",
        "source_report": str(report_path),
        "area_count": len(areas),
        "passed_area_count": sum(
            1 for area in areas if area.get("status") in {"passed", "not_applicable"}
        ),
        "incomplete_area_ids": incomplete_area_ids,
        "manual_remaining_check_ids": manual_summary.get("remaining_check_ids", []),
        "manual_status_counts": manual_summary.get("status_counts", {}),
        "areas": areas,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Signoff draft or RC report JSON.")
    parser.add_argument("--output-json", type=Path, help="Write the parity summary JSON.")
    args = parser.parse_args(argv)
    try:
        summary = summarize_parity(PROJECT_ROOT, args.report)
        if args.output_json is not None:
            output = args.output_json if args.output_json.is_absolute() else PROJECT_ROOT / args.output_json
            _write_report(output, summary)
        else:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"Oha parity summary: failed\n- {exc}", file=sys.stderr)
        return 1
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
