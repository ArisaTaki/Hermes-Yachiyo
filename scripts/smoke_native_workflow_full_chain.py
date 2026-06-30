#!/usr/bin/env python3
"""Opt-in advanced Workflow smoke for the Oha-Yachiyo Native runtime.

This smoke uses real OpenAI-compatible credentials from OHA_YACHIYO_SMOKE_*
environment variables. It exercises advanced Workflow orchestration with real
model calls while keeping all state in a temporary directory and printing only
redacted structured summaries.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import apps.shell.agent_runtime as agent_runtime
import apps.shell.model_profiles as model_profiles
from apps.shell.agent_runtime import NativeRunEngine, get_native_agent_readiness
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.model_profiles import ModelProfileService
from packages.security import contains_sensitive_text, redact_sensitive_text, sanitize_sensitive_value
from scripts.smoke_native_agent_full_chain import (
    API_KEY_ENV,
    BASE_URL_ENV,
    MODEL_ENV,
    _agent_model_config,
    _artifact_paths,
    _check,
    _create_profile,
    _events,
    _is_ok,
    _preview,
    _required_env,
    _temporary_model_profile_service,
)

PROVIDER_ENV_NAMES = (BASE_URL_ENV, MODEL_ENV, API_KEY_ENV)


def _missing_provider_env() -> list[str]:
    return [name for name in PROVIDER_ENV_NAMES if not os.getenv(name, "").strip()]


def _missing_provider_credentials_summary(missing_env: list[str]) -> dict[str, Any]:
    return sanitize_sensitive_value(
        {
            "ok": False,
            "skipped": True,
            "mode": "native_workflow_full_chain_smoke",
            "stage": "provider_credentials",
            "reason": "provider_smoke_credentials_missing",
            "blocking_condition": "provider_smoke_credentials_missing",
            "blocking_conditions": ["provider_smoke_credentials_missing"],
            "missing_env": missing_env,
            "recovery_hints": [
                "Configure OHA_YACHIYO_SMOKE_BASE_URL, OHA_YACHIYO_SMOKE_MODEL, and OHA_YACHIYO_SMOKE_API_KEY.",
                "Re-run scripts/run_public_demo_smokes.py --include-provider-workflow after credentials are available.",
            ],
            "recommended_tools": [
                "scripts/run_provider_smoke_with_prompt.py",
                "scripts/run_public_demo_smokes.py --include-provider-workflow",
            ],
        },
        max_depth=4,
    )


def _create_exact_agent(
    service: NativeRunEngine,
    *,
    name: str,
    model_config: dict[str, str],
    exact_output: str,
) -> dict[str, Any]:
    return service.create_agent(
        {
            "name": name,
            "model_mode": "custom_api",
            "model_config": model_config,
            "instructions": (
                f"Return exactly this text and nothing else: {exact_output}. "
                "Do not call tools."
            ),
            "tool_policy": {"allowed_tools": []},
            "workspace_policy": {"default_workdir": "", "readable_scopes": ["."]},
        }
    )


def _run_advanced_workflow(
    service: NativeRunEngine,
    model_config: dict[str, str],
) -> dict[str, Any]:
    classifier = _create_exact_agent(
        service,
        name="Advanced Workflow Classifier",
        model_config=model_config,
        exact_output="decision: ship",
    )
    subflow_agent = _create_exact_agent(
        service,
        name="Advanced Workflow Subflow Agent",
        model_config=model_config,
        exact_output="SUBFLOW_READY",
    )
    design = _create_exact_agent(
        service,
        name="Advanced Workflow Design",
        model_config=model_config,
        exact_output="DESIGN_READY",
    )
    code = _create_exact_agent(
        service,
        name="Advanced Workflow Code",
        model_config=model_config,
        exact_output="CODE_READY",
    )
    skip = _create_exact_agent(
        service,
        name="Advanced Workflow Skip",
        model_config=model_config,
        exact_output="SKIPPED",
    )
    child_workflow = service.create_workflow(
        {
            "name": "Advanced Child Workflow",
            "nodes": [
                {"id": "start", "type": "start", "data": {"label": "Start"}},
                {
                    "id": "child-agent",
                    "type": "agent",
                    "data": {"label": "Child Agent", "agent_id": subflow_agent["agent_id"]},
                },
                {
                    "id": "child-report",
                    "type": "artifact",
                    "data": {"label": "Child Report", "artifact_path": "reports/child-workflow.md"},
                },
            ],
            "edges": [
                {"source": "start", "target": "child-agent"},
                {"source": "child-agent", "target": "child-report"},
            ],
        }
    )
    parent_workflow = service.create_workflow(
        {
            "name": "Advanced Native Workflow Full Chain",
            "nodes": [
                {"id": "start", "type": "start", "data": {"label": "Start"}},
                {
                    "id": "classify",
                    "type": "agent",
                    "data": {"label": "Classify", "agent_id": classifier["agent_id"]},
                },
                {
                    "id": "route",
                    "type": "condition",
                    "data": {"label": "Route", "condition": "ship", "operator": "contains"},
                },
                {
                    "id": "child-flow",
                    "type": "workflow",
                    "data": {
                        "label": "Run Child Flow",
                        "workflow_id": child_workflow["workflow_id"],
                    },
                },
                {
                    "id": "gate",
                    "type": "approval",
                    "data": {
                        "label": "Human Gate",
                        "approval_criteria": "Confirm child workflow output before parallel work.",
                    },
                },
                {"id": "fanout", "type": "parallel", "data": {"label": "Parallel Work"}},
                {
                    "id": "design",
                    "type": "agent",
                    "data": {"label": "Design", "agent_id": design["agent_id"]},
                },
                {
                    "id": "code",
                    "type": "agent",
                    "data": {"label": "Code", "agent_id": code["agent_id"]},
                },
                {
                    "id": "repeat",
                    "type": "loop",
                    "data": {"label": "Loop Exit Check", "condition": "again", "max_iterations": 2},
                },
                {
                    "id": "skip",
                    "type": "agent",
                    "data": {"label": "Skip", "agent_id": skip["agent_id"]},
                },
                {
                    "id": "report",
                    "type": "artifact",
                    "data": {"label": "Advanced Report", "artifact_path": "reports/advanced-workflow.md"},
                },
            ],
            "edges": [
                {"source": "start", "target": "classify"},
                {"source": "classify", "target": "route"},
                {"source": "route", "target": "child-flow", "data": {"branch": "true"}},
                {"source": "route", "target": "skip", "data": {"branch": "false"}},
                {"source": "child-flow", "target": "gate"},
                {"source": "gate", "target": "fanout"},
                {"source": "fanout", "target": "design"},
                {"source": "fanout", "target": "code"},
                {"source": "design", "target": "repeat"},
                {"source": "code", "target": "repeat"},
                {"source": "repeat", "target": "design", "data": {"branch": "continue"}},
                {"source": "repeat", "target": "report", "data": {"branch": "exit"}},
                {"source": "skip", "target": "report"},
            ],
        }
    )

    waiting = service.create_workflow_run(
        {
            "workflow_id": parent_workflow["workflow_id"],
            "user_goal": "Run the advanced native Workflow smoke.",
        }
    )
    completed = service.approve_run_approval(waiting["run_id"])
    event_types = _events(service, completed["run_id"])
    paths = _artifact_paths(completed)
    result_text = str(completed.get("result") or "")
    required_events = {
        "workflow.node.condition",
        "workflow.node.workflow",
        "workflow.node.approval_required",
        "workflow.node.parallel",
        "workflow.node.loop",
        "workflow.node.artifact",
    }
    ok = (
        waiting.get("status") == "approval_required"
        and completed.get("status") == "completed"
        and required_events.issubset(set(event_types))
        and "reports/advanced-workflow.md" in paths
        and "DESIGN_READY" in result_text
        and "CODE_READY" in result_text
    )
    return _check(
        "advanced_workflow_orchestration",
        ok,
        initial_status=waiting.get("status"),
        final_status=completed.get("status"),
        event_types=event_types,
        artifact_paths=paths,
        result_preview=_preview(result_text),
    )


def _run_workflow_budget_boundary(service: NativeRunEngine) -> dict[str, Any]:
    previous_limits = service.runtime_limits
    service.runtime_limits = service.runtime_limits.__class__(max_workflow_steps=1)
    try:
        workflow = service.create_workflow(
            {
                "name": "Advanced Workflow Budget Boundary",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "report",
                        "type": "artifact",
                        "data": {
                            "label": "Budget Report",
                            "artifact_path": "reports/budget-boundary.md",
                        },
                    },
                ],
                "edges": [{"source": "start", "target": "report"}],
            }
        )
        run = service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Trigger workflow step budget.",
            }
        )
    finally:
        service.runtime_limits = previous_limits
    paths = _artifact_paths(run)
    result_text = str(run.get("result") or "")
    ok = (
        run.get("status") == "failed"
        and "max_workflow_steps=1" in result_text
        and "reports/budget-boundary.md" not in paths
    )
    return _check(
        "workflow_budget_boundary",
        ok,
        status=run.get("status"),
        artifact_paths=paths,
        result_preview=_preview(result_text),
    )


def run_workflow_full_chain_smoke(*, base_url: str, model: str, api_key: str) -> dict[str, Any]:
    credential_store = MemoryCredentialStore()
    with tempfile.TemporaryDirectory(prefix="oha-native-workflow-full-chain-") as temp:
        temp_root = Path(temp)
        profile_service = ModelProfileService(
            db_path=temp_root / "model-profiles.db",
            workspace_dir=temp_root / "profiles",
            credential_store=credential_store,
        )
        service = NativeRunEngine(
            db_path=temp_root / "agent-runtime.db",
            workspace_dir=temp_root / "runtime",
            credential_store=credential_store,
            seed_templates=False,
        )
        checks: list[dict[str, Any]] = []
        try:
            with _temporary_model_profile_service(profile_service):
                created = _create_profile(profile_service, base_url=base_url, model=model, api_key=api_key)
                profile = created["profile"]
                public_profile = profile_service.get_profile(profile["profile_id"])
                readiness = get_native_agent_readiness()
                checks.append(
                    _check(
                        "model_profile_readiness",
                        bool(created["test"].get("ok"))
                        and bool(readiness.get("ready"))
                        and not public_profile.get("api_key"),
                        profile_status=(created["test"].get("profile") or {}).get("status") or profile.get("status"),
                        readiness=readiness,
                        public_credential_exposed=bool(public_profile.get("api_key")),
                    )
                )
                model_config = _agent_model_config(base_url, model, api_key)
                checks.append(_run_advanced_workflow(service, model_config))
                checks.append(_run_workflow_budget_boundary(service))
        finally:
            service.close()
            profile_service.close()
    ok = all(bool(check.get("ok")) for check in checks)
    return sanitize_sensitive_value(
        {
            "ok": ok,
            "model": model,
            "check_count": len(checks),
            "checks": checks,
        },
        max_depth=6,
    )


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional JSON evidence report path.",
    )
    args = parser.parse_args(argv)
    missing_env = _missing_provider_env()
    if missing_env:
        summary = _missing_provider_credentials_summary(missing_env)
        if args.report_json is not None:
            _write_report(args.report_json, summary)
            print(
                f"native workflow full-chain smoke report: {args.report_json}",
                file=sys.stderr,
            )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    try:
        base_url, model, api_key = _required_env()
        summary = run_workflow_full_chain_smoke(base_url=base_url, model=model, api_key=api_key)
    except Exception as exc:
        summary = sanitize_sensitive_value({"ok": False, "error": redact_sensitive_text(exc, limit=500)})
        if args.report_json is not None:
            _write_report(args.report_json, summary)
            print(
                f"native workflow full-chain smoke report: {args.report_json}",
                file=sys.stderr,
            )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 1
    text = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    if contains_sensitive_text(text):
        safe_summary = {"ok": False, "error": "smoke output still contains sensitive text"}
        if args.report_json is not None:
            _write_report(args.report_json, safe_summary)
            print(
                f"native workflow full-chain smoke report: {args.report_json}",
                file=sys.stderr,
            )
        print(json.dumps(safe_summary, sort_keys=True))
        return 1
    if args.report_json is not None:
        _write_report(args.report_json, summary)
        print(
            f"native workflow full-chain smoke report: {args.report_json}",
            file=sys.stderr,
        )
    print(text)
    return 0 if _is_ok(summary.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
