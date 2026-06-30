#!/usr/bin/env python3
"""Summarize release-readiness blockers from RC capability reports."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_SMOKE_ENV_VARS = (
    "OHA_YACHIYO_SMOKE_BASE_URL",
    "OHA_YACHIYO_SMOKE_MODEL",
    "OHA_YACHIYO_SMOKE_API_KEY",
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.summarize_native_agent_capabilities import (  # noqa: E402
    SOURCE_SECTION_CAPABILITIES,
    capability_category,
    capability_matrix_from_report,
    merge_capability_matrices,
    summarize_capabilities,
)


def _load_report(path: Path) -> dict[str, Any]:
    candidate = path if path.is_absolute() else ROOT / path
    data = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"report must be a JSON object: {path}")
    return data


def _write_text(path: Path, value: str) -> None:
    target = path if path.is_absolute() else ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


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


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _append_unique(target: list[str], values: Sequence[str]) -> None:
    for value in values:
        if value and value not in target:
            target.append(value)


def _append_unique_dict(target: list[dict[str, Any]], values: Sequence[dict[str, Any]]) -> None:
    seen = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in target}
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        target.append(value)


def _capabilities(matrix: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = matrix.get("capabilities")
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _missing_capabilities(matrix: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        capability
        for capability in _capabilities(matrix)
        if capability.get("status") != "passed"
    ]


def _category_for(capability: Mapping[str, Any]) -> str:
    return str(
        capability.get("category")
        or capability_category(str(capability.get("id") or ""))
    )


def _capability_ref(capability: Mapping[str, Any]) -> dict[str, str]:
    return {
        "id": str(capability.get("id") or ""),
        "label": str(capability.get("label") or ""),
        "category": _category_for(capability),
    }


def _upsert_blocker(
    blockers: dict[tuple[str, str], dict[str, Any]],
    *,
    blocker_type: str,
    blocker_id: str,
    title: str,
    capability: Mapping[str, Any],
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    key = (blocker_type, blocker_id)
    blocker = blockers.get(key)
    if blocker is None:
        blocker = {
            "type": blocker_type,
            "id": blocker_id,
            "title": title,
            "capabilities": [],
        }
        blockers[key] = blocker
    capability_ref = _capability_ref(capability)
    if capability_ref["id"] and capability_ref not in blocker["capabilities"]:
        blocker["capabilities"].append(capability_ref)
    for detail_key, detail_value in (details or {}).items():
        if detail_value in (None, "", [], {}):
            continue
        if isinstance(detail_value, list):
            if detail_key not in blocker:
                blocker[detail_key] = []
            if detail_value and all(isinstance(item, dict) for item in detail_value):
                _append_unique_dict(blocker[detail_key], detail_value)
            else:
                _append_unique(blocker[detail_key], [str(item) for item in detail_value])
        else:
            blocker.setdefault(detail_key, detail_value)
    return blocker


def _blockers_from_capabilities(
    missing_capabilities: Sequence[dict[str, Any]],
    *,
    env: Mapping[str, str],
) -> list[dict[str, Any]]:
    blockers: dict[tuple[str, str], dict[str, Any]] = {}
    blocked_capability_ids: set[str] = set()

    for capability in missing_capabilities:
        evidence = capability.get("evidence_summary")
        evidence = evidence if isinstance(evidence, dict) else {}
        conditions = _string_list(evidence.get("blocking_conditions"))
        if not conditions:
            conditions = _string_list(evidence.get("blocking_condition"))
        for condition in conditions:
            blocked_capability_ids.add(str(capability.get("id") or ""))
            _upsert_blocker(
                blockers,
                blocker_type="runtime_blocking_condition",
                blocker_id=condition,
                title=f"Runtime blocker: {condition}",
                capability=capability,
                details={
                    "stage": evidence.get("stage"),
                    "error": evidence.get("error"),
                    "recovery_hints": _string_list(evidence.get("recovery_hints")),
                    "recommended_tools": _string_list(evidence.get("recommended_tools")),
                    "recovery_actions": _dict_list(evidence.get("recovery_actions")),
                },
            )
        for permission in _string_list(evidence.get("missing_permissions")):
            blocked_capability_ids.add(str(capability.get("id") or ""))
            _upsert_blocker(
                blockers,
                blocker_type="permission_missing",
                blocker_id=permission,
                title=f"Missing permission: {permission}",
                capability=capability,
                details={
                    "permission_targets": _string_list(evidence.get("permission_targets")),
                    "recovery_hints": _string_list(evidence.get("recovery_hints")),
                    "recommended_tools": _string_list(evidence.get("recommended_tools")),
                    "recovery_actions": _dict_list(evidence.get("recovery_actions")),
                },
            )

    provider_missing = [
        capability
        for capability in missing_capabilities
        if _category_for(capability) == "provider"
    ]
    missing_provider_env = [
        name for name in PROVIDER_SMOKE_ENV_VARS if not str(env.get(name, "")).strip()
    ]
    for capability in provider_missing:
        blocked_capability_ids.add(str(capability.get("id") or ""))
        if missing_provider_env:
            _upsert_blocker(
                blockers,
                blocker_type="provider_credentials_missing",
                blocker_id="oha_yachiyo_smoke_credentials",
                title="Provider smoke credentials are not configured",
                capability=capability,
                details={"missing_env": missing_provider_env},
            )
        else:
            _upsert_blocker(
                blockers,
                blocker_type="provider_smoke_missing",
                blocker_id="provider_smoke",
                title="Provider smoke evidence is missing or failed",
                capability=capability,
            )

    for capability in missing_capabilities:
        if _category_for(capability) != "packaged":
            continue
        blocked_capability_ids.add(str(capability.get("id") or ""))
        _upsert_blocker(
            blockers,
            blocker_type="packaged_artifact_evidence_missing",
            blocker_id="packaged_artifacts",
            title="Packaged artifact smoke evidence is missing",
            capability=capability,
        )

    source_without_specific_blocker = [
        capability
        for capability in missing_capabilities
        if _category_for(capability) == "source"
        and str(capability.get("id") or "") not in blocked_capability_ids
    ]
    for capability in source_without_specific_blocker:
        _upsert_blocker(
            blockers,
            blocker_type="source_evidence_missing",
            blocker_id="source_smoke_evidence",
            title="Source smoke evidence is missing or failed",
            capability=capability,
        )

    return sorted(
        blockers.values(),
        key=lambda item: (str(item.get("type") or ""), str(item.get("id") or "")),
    )


def release_readiness_diagnostics(
    matrix: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = env or os.environ
    capabilities = _capabilities(matrix)
    missing_capabilities = _missing_capabilities(matrix)
    status_counts = matrix.get("status_counts")
    status_counts = status_counts if isinstance(status_counts, dict) else {}
    passed_count = int(status_counts.get("passed") or 0)
    capability_count = int(matrix.get("capability_count") or len(capabilities))
    blockers = _blockers_from_capabilities(missing_capabilities, env=env)
    source_reports = matrix.get("source_reports")
    if not isinstance(source_reports, list):
        source_report = matrix.get("source_report")
        source_reports = [source_report] if source_report else []
    return {
        "ok": bool(matrix.get("ok") is True and not blockers),
        "status": "ready" if matrix.get("ok") is True and not blockers else "incomplete",
        "capability_count": capability_count,
        "passed_count": passed_count,
        "missing_count": len(missing_capabilities),
        "missing_capability_ids": [
            str(capability.get("id") or "") for capability in missing_capabilities
        ],
        "missing_by_category": matrix.get("missing_by_category") or {},
        "blockers": blockers,
        "next_actions": matrix.get("next_actions") or [],
        "source_reports": source_reports,
    }


def render_markdown(diagnostics: Mapping[str, Any]) -> str:
    capability_count = int(diagnostics.get("capability_count") or 0)
    passed_count = int(diagnostics.get("passed_count") or 0)
    missing_ids = _string_list(diagnostics.get("missing_capability_ids"))
    lines = [
        "# Oha-Yachiyo Release Readiness Diagnostics",
        "",
        f"Status: {diagnostics.get('status')}",
        f"Capability matrix: {passed_count}/{capability_count} passed",
        "",
    ]
    if missing_ids:
        lines.extend(["## Missing Capabilities", ""])
        for capability_id in missing_ids:
            lines.append(f"- `{capability_id}`")
        lines.append("")
    blockers = diagnostics.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["## Blockers", ""])
        for blocker in blockers:
            if not isinstance(blocker, dict):
                continue
            title = str(blocker.get("title") or blocker.get("id") or "Blocker")
            lines.append(f"- {title}")
            capabilities = blocker.get("capabilities")
            if isinstance(capabilities, list):
                refs = [
                    str(item.get("id") or "")
                    for item in capabilities
                    if isinstance(item, dict) and str(item.get("id") or "")
                ]
                if refs:
                    lines.append(f"  Capabilities: {', '.join(f'`{item}`' for item in refs)}")
            for key in ("missing_env", "recovery_hints", "recommended_tools"):
                values = _string_list(blocker.get(key))
                if values:
                    label = key.replace("_", " ")
                    lines.append(f"  {label}: {', '.join(f'`{item}`' for item in values)}")
            for key in ("stage", "error"):
                value = str(blocker.get(key) or "").strip()
                if value:
                    lines.append(f"  {key}: `{value}`")
            recovery_actions = _recovery_action_labels(blocker.get("recovery_actions"))
            if recovery_actions:
                lines.append(
                    "  recovery actions: "
                    + ", ".join(f"`{item}`" for item in recovery_actions)
                )
        lines.append("")
    actions = diagnostics.get("next_actions")
    if isinstance(actions, list) and actions:
        lines.extend(["## Next Actions", ""])
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_id = str(action.get("id") or "next_action")
            command = str(action.get("command") or "").strip()
            lines.append(f"- `{action_id}`")
            if command:
                lines.append("")
                lines.extend(["```bash", command, "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _recovery_action_labels(value: Any) -> list[str]:
    labels: list[str] = []
    for item in _dict_list(value):
        label = str(item.get("label") or "").strip()
        tool = str(item.get("tool") or "").strip()
        permission_target = str(item.get("permission_target") or "").strip()
        if label and tool:
            text = f"{label} -> {tool}"
        elif label:
            text = label
        elif tool:
            text = tool
        else:
            continue
        if permission_target:
            text = f"{text} ({permission_target})"
        if text not in labels:
            labels.append(text)
    return labels


def _matrix_from_reports(report_paths: Sequence[Path]) -> dict[str, Any]:
    matrices: list[dict[str, Any]] = []
    source_reports: list[str] = []
    for report_path in report_paths:
        report = _load_report(report_path)
        matrix = _capability_matrix_for_readiness(report)
        matrix["source_report"] = str(report_path)
        matrices.append(matrix)
        source_reports.append(str(report_path))
    if len(matrices) == 1:
        return matrices[0]
    return merge_capability_matrices(matrices, source_reports=source_reports)


def _capability_matrix_for_readiness(report: Mapping[str, Any]) -> dict[str, Any]:
    raw_section_names = tuple(SOURCE_SECTION_CAPABILITIES.values()) + (
        "provider_smoke",
        "native_provider_contract_smoke",
        "packaged_backend_bridge_smoke",
        "dmg_app_smoke",
    )
    if any(isinstance(report.get(section_name), dict) for section_name in raw_section_names):
        matrix = summarize_capabilities(dict(report))
        matrix["status"] = "passed" if matrix.get("ok") is True else "incomplete"
        return matrix
    return capability_matrix_from_report(dict(report))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path, help="RC report JSON files.")
    parser.add_argument("--output-json", type=Path, help="Write diagnostics JSON.")
    parser.add_argument("--output-markdown", type=Path, help="Write diagnostics Markdown.")
    args = parser.parse_args(argv)
    try:
        matrix = _matrix_from_reports(args.reports)
        diagnostics = release_readiness_diagnostics(matrix)
        if args.output_json is not None:
            _write_json(args.output_json, diagnostics)
        if args.output_markdown is not None:
            _write_text(args.output_markdown, render_markdown(diagnostics))
        if args.output_json is None and args.output_markdown is None:
            print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"release readiness diagnostics: failed\n- {exc}", file=sys.stderr)
        return 1
    return 0 if diagnostics.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
