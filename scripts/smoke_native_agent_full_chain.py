#!/usr/bin/env python3
"""Opt-in full-chain smoke for the Oha-Yachiyo Native Agent runtime.

This smoke uses real OpenAI-compatible credentials from OHA_YACHIYO_SMOKE_*
environment variables. It keeps all runtime state in a temporary directory,
uses an in-memory credential store, and prints only redacted structured
summaries.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import apps.shell.agent_runtime as agent_runtime
import apps.shell.model_profiles as model_profiles
from apps.shell.agent_runtime import NativeRunEngine, get_native_agent_readiness
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.model_profiles import ModelProfileService
from packages.security import contains_sensitive_text, redact_sensitive_text, sanitize_sensitive_value

BASE_URL_ENV = "OHA_YACHIYO_SMOKE_BASE_URL"
MODEL_ENV = "OHA_YACHIYO_SMOKE_MODEL"
API_KEY_ENV = "OHA_YACHIYO_SMOKE_API_KEY"


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _required_env() -> tuple[str, str, str]:
    base_url = _env(BASE_URL_ENV)
    model = _env(MODEL_ENV)
    api_key = _env(API_KEY_ENV)
    missing = [name for name, value in ((BASE_URL_ENV, base_url), (MODEL_ENV, model), (API_KEY_ENV, api_key)) if not value]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))
    return base_url.rstrip("/"), model, api_key


def _is_ok(value: Any) -> bool:
    return bool(value)


def _events(service: NativeRunEngine, run_id: str) -> list[str]:
    return [str(event.get("event_type") or "") for event in service.list_run_events(run_id)["events"]]


def _artifact_paths(run: dict[str, Any]) -> list[str]:
    return [
        str(item.get("path") or "")
        for item in run.get("artifacts") or []
        if isinstance(item, dict) and item.get("path")
    ]


def _preview(value: Any, *, limit: int = 180) -> str:
    return redact_sensitive_text(value, limit=limit)


def _check(name: str, ok: bool, **details: Any) -> dict[str, Any]:
    payload = {"name": name, "ok": bool(ok), **details}
    return sanitize_sensitive_value(payload, max_depth=6)


@contextmanager
def _temporary_model_profile_service(profile_service: ModelProfileService) -> Iterator[None]:
    original_model_profile_service = model_profiles._model_profile_service
    original_agent_runtime_getter = agent_runtime.get_model_profile_service
    model_profiles._model_profile_service = profile_service
    agent_runtime.get_model_profile_service = lambda: profile_service
    try:
        yield
    finally:
        agent_runtime.get_model_profile_service = original_agent_runtime_getter
        model_profiles._model_profile_service = original_model_profile_service


def _agent_model_config(base_url: str, model: str, api_key: str) -> dict[str, str]:
    return {
        "provider": "openai_compatible",
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
    }


def _create_profile(profile_service: ModelProfileService, *, base_url: str, model: str, api_key: str) -> dict[str, Any]:
    profile = profile_service.create_profile(
        {
            "name": "Native Agent Full Chain Smoke",
            "capability": "chat",
            "provider": "openai_compatible",
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
        }
    )
    test = profile_service.test_profile(profile["profile_id"])
    profile_service.set_defaults({"chat": profile["profile_id"]})
    return {"profile": profile, "test": test}


def _run_workspace_read(service: NativeRunEngine, workdir: Path, model_config: dict[str, str]) -> dict[str, Any]:
    (workdir / "facts.txt").write_text(
        "project_code_name=Oha-Yachiyo\nanswer_token=MIYABI-742\n",
        encoding="utf-8",
    )
    agent = service.create_agent(
        {
            "name": "Full Chain Reader",
            "model_mode": "custom_api",
            "model_config": model_config,
            "instructions": (
                "You must use the workspace_read tool to read facts.txt. "
                "Then answer with the exact answer_token and project_code_name."
            ),
            "tool_policy": {"allowed_tools": ["workspace.read"]},
            "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
        }
    )
    run = service.create_agent_run(
        {
            "agent_id": agent["agent_id"],
            "user_goal": "Read facts.txt with workspace_read and report the token.",
        }
    )
    result = str(run.get("result") or "")
    event_types = _events(service, run["run_id"])
    ok = run.get("status") == "completed" and "agent.tool.call" in event_types and "MIYABI-742" in result
    return _check(
        "agent_workspace_read",
        ok,
        status=run.get("status"),
        event_types=event_types,
        result_preview=_preview(result),
    )


def _run_artifact_write(service: NativeRunEngine, workdir: Path, model_config: dict[str, str]) -> dict[str, Any]:
    agent = service.create_agent(
        {
            "name": "Full Chain Artifact Writer",
            "model_mode": "custom_api",
            "model_config": model_config,
            "instructions": (
                "You must use artifact_write to write live-chain-report.md with a short "
                "report that includes Oha-Yachiyo and MIYABI-742. Then reply DONE."
            ),
            "tool_policy": {"allowed_tools": ["artifact.write"]},
            "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
        }
    )
    run = service.create_agent_run(
        {
            "agent_id": agent["agent_id"],
            "user_goal": "Write live-chain-report.md via artifact_write.",
        }
    )
    paths = _artifact_paths(run)
    ok = run.get("status") == "completed" and "live-chain-report.md" in paths
    return _check(
        "agent_artifact_write",
        ok,
        status=run.get("status"),
        artifact_paths=paths,
        result_preview=_preview(run.get("result")),
    )


def _run_multi_tool_pipeline(service: NativeRunEngine, workdir: Path, model_config: dict[str, str]) -> dict[str, Any]:
    (workdir / "pipeline-facts.txt").write_text(
        "project_code_name=Oha-Yachiyo\nanswer_token=MIYABI-742\npipeline_required=true\n",
        encoding="utf-8",
    )
    agent = service.create_agent(
        {
            "name": "Full Chain Multi Tool Pipeline",
            "model_mode": "custom_api",
            "model_config": model_config,
            "instructions": (
                "You must complete a two-step tool pipeline. First call workspace_read "
                "to read pipeline-facts.txt. After you receive the tool result, call "
                "artifact_write to write pipeline-report.md containing the answer_token "
                "and project_code_name. Then answer PIPELINE_DONE with the token."
            ),
            "tool_policy": {"allowed_tools": ["workspace.read", "artifact.write"]},
            "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
        }
    )
    run = service.create_agent_run(
        {
            "agent_id": agent["agent_id"],
            "user_goal": (
                "Read pipeline-facts.txt, write pipeline-report.md, and return PIPELINE_DONE."
            ),
        }
    )
    event_types = _events(service, run["run_id"])
    paths = _artifact_paths(run)
    result = str(run.get("result") or "")
    tool_call_count = event_types.count("agent.tool.call")
    ok = (
        run.get("status") == "completed"
        and tool_call_count >= 2
        and "pipeline-report.md" in paths
        and "MIYABI-742" in result
    )
    return _check(
        "agent_multi_tool_pipeline",
        ok,
        status=run.get("status"),
        tool_call_count=tool_call_count,
        event_types=event_types,
        artifact_paths=paths,
        result_preview=_preview(result),
    )


def _run_workflow(service: NativeRunEngine, workdir: Path, model_config: dict[str, str]) -> dict[str, Any]:
    child = service.create_agent(
        {
            "name": "Full Chain Workflow Child",
            "model_mode": "custom_api",
            "model_config": model_config,
            "instructions": "Read facts.txt with workspace_read and answer only the answer_token.",
            "tool_policy": {"allowed_tools": ["workspace.read"]},
            "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
        }
    )
    workflow = service.create_workflow(
        {
            "name": "Full Chain Workflow",
            "nodes": [
                {"id": "start", "type": "start", "data": {"label": "Start"}},
                {"id": "child", "type": "agent", "data": {"label": "Child", "agent_id": child["agent_id"]}},
                {
                    "id": "summary",
                    "type": "artifact",
                    "data": {"label": "Summary", "artifact_path": "workflow-summary.md"},
                },
            ],
            "edges": [
                {"source": "start", "target": "child"},
                {"source": "child", "target": "summary"},
            ],
        }
    )
    run = service.create_workflow_run(
        {
            "workflow_id": workflow["workflow_id"],
            "user_goal": "Extract the token from facts.txt and write a workflow summary.",
        }
    )
    event_types = _events(service, run["run_id"])
    paths = _artifact_paths(run)
    ok = run.get("status") == "completed" and "workflow.node.agent" in event_types and "workflow-summary.md" in paths
    return _check(
        "workflow_child_agent_artifact",
        ok,
        status=run.get("status"),
        event_types=event_types,
        artifact_paths=paths,
        result_preview=_preview(run.get("result")),
    )


def _run_terminal_approval(service: NativeRunEngine, workdir: Path, model_config: dict[str, str]) -> dict[str, Any]:
    agent = service.create_agent(
        {
            "name": "Full Chain Approval Runner",
            "model_mode": "custom_api",
            "model_config": model_config,
            "instructions": (
                "You must use terminal_run once to execute exactly: printf APPROVED_CHAIN_OK. "
                "After the tool result, answer with APPROVED_CHAIN_OK."
            ),
            "tool_policy": {"allowed_tools": ["terminal.run"]},
            "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
        }
    )
    waiting = service.create_agent_run(
        {
            "agent_id": agent["agent_id"],
            "user_goal": "Run printf APPROVED_CHAIN_OK with terminal_run.",
        }
    )
    pending_tool = ""
    pending = waiting.get("pending_approval")
    if isinstance(pending, dict):
        pending_tool = str(pending.get("tool") or "")
    resumed = service.approve_run_approval(waiting["run_id"])
    repeated = service.approve_run_approval(waiting["run_id"])
    event_types = _events(service, waiting["run_id"])
    result = str(resumed.get("result") or "")
    ok = (
        waiting.get("status") == "approval_required"
        and pending_tool == "terminal.run"
        and resumed.get("status") == "completed"
        and repeated.get("status") == "completed"
        and "APPROVED_CHAIN_OK" in result
    )
    return _check(
        "terminal_approval_resume",
        ok,
        initial_status=waiting.get("status"),
        pending_tool=pending_tool,
        resumed_status=resumed.get("status"),
        repeated_status=repeated.get("status"),
        event_types=event_types,
        result_preview=_preview(result),
    )


def _run_main_chat(service: NativeRunEngine, workdir: Path, profile_id: str) -> dict[str, Any]:
    run = service.start_main_chat_run(
        task_id="smoke-main-chat-task",
        session_id="smoke-main-chat-session",
        user_goal="Return MAIN_CHAT_OK.",
    )
    updated = service.execute_main_chat_model_loop(
        run["run_id"],
        [{"role": "user", "content": "Please reply with exactly MAIN_CHAT_OK."}],
        profile_id=profile_id,
        workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
    )
    completed = service.complete_main_chat_run(run["run_id"], str(updated.get("result") or ""))
    event_types = _events(service, run["run_id"])
    ok = completed.get("status") == "completed" and "MAIN_CHAT_OK" in str(completed.get("result") or "")
    return _check(
        "main_chat_model_loop",
        ok,
        status=completed.get("status"),
        event_types=event_types,
        result_preview=_preview(completed.get("result")),
    )


def run_full_chain_smoke(*, base_url: str, model: str, api_key: str) -> dict[str, Any]:
    credential_store = MemoryCredentialStore()
    with tempfile.TemporaryDirectory(prefix="oha-native-agent-full-chain-") as temp:
        temp_root = Path(temp)
        workdir = temp_root / "workspace"
        workdir.mkdir()
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
                checks.append(_run_workspace_read(service, workdir, model_config))
                checks.append(_run_artifact_write(service, workdir, model_config))
                checks.append(_run_multi_tool_pipeline(service, workdir, model_config))
                checks.append(_run_workflow(service, workdir, model_config))
                checks.append(_run_terminal_approval(service, workdir, model_config))
                checks.append(_run_main_chat(service, workdir, profile["profile_id"]))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        base_url, model, api_key = _required_env()
        summary = run_full_chain_smoke(base_url=base_url, model=model, api_key=api_key)
    except Exception as exc:
        summary = sanitize_sensitive_value({"ok": False, "error": redact_sensitive_text(exc, limit=500)})
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 1
    text = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    if contains_sensitive_text(text):
        print(json.dumps({"ok": False, "error": "smoke output still contains sensitive text"}, sort_keys=True))
        return 1
    print(text)
    return 0 if _is_ok(summary.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
