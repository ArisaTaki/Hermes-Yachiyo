#!/usr/bin/env python3
"""Build a market-agent parity summary from Oha-Yachiyo source evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]


MARKET_REQUIREMENTS: tuple[dict[str, Any], ...] = (
    {
        "id": "market_operating_doctrine",
        "label": "Market-grade Agent operating doctrine",
        "market_pattern": "Persistent personal agent behavior, reliable tool discipline, handoff-aware output.",
        "priority": "P0",
        "passed": [
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": [
                    "_MARKET_AGENT_OPERATING_DOCTRINE",
                    "persistent personal agent",
                    "Respect safety boundaries",
                ],
            }
        ],
    },
    {
        "id": "persona_and_identity_context",
        "label": "Persona, nickname, and role identity",
        "market_pattern": "Open-Hanako/OpenClaw-style distinct agent identity and user-facing personality.",
        "priority": "P0",
        "passed": [
            {
                "path": "apps/bridge/routes/agents.py",
                "fragments": ["nickname", "persona_prompt"],
            },
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": ["# Persona Prompt", "Nickname:"],
            },
        ],
    },
    {
        "id": "controlled_tool_loop",
        "label": "Controlled tool loop with approvals",
        "market_pattern": "Hermes/OpenClaw/AstrBot-style tools, approvals, workspace scope, and recovery.",
        "priority": "P0",
        "passed": [
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": [
                    "class ToolBroker",
                    "class ToolDescriptorRegistry",
                    "class ApprovalCoordinator",
                    "class ApprovalResumeCoordinator",
                    "workspace.write_patch",
                    "terminal.run",
                ],
            }
        ],
    },
    {
        "id": "multi_agent_workflow_orchestration",
        "label": "Multi-Agent and Workflow orchestration",
        "market_pattern": "Specialist agents, DAG/parallel/subworkflow/loop execution, and approval checkpoints.",
        "priority": "P0",
        "passed": [
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": [
                    '"parallel"',
                    '"workflow"',
                    '"loop"',
                    "workflow.node.parallel",
                    "workflow.node.workflow",
                    "workflow.node.loop",
                ],
            },
            {
                "path": "apps/bridge/routes/agents.py",
                "fragments": ["/workflows", "WorkflowRunRequest"],
            },
        ],
    },
    {
        "id": "agent_workspace_and_artifacts",
        "label": "Agent workspace and artifact handoff",
        "market_pattern": "Open-Hanako desk/OpenClaw workspace-style async collaboration surface.",
        "priority": "P1",
        "passed": [
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": [
                    "workspace_list",
                    "workspace_read",
                    "workspace_write_patch",
                    "artifact_write",
                    "agent-context.md",
                ],
            }
        ],
    },
    {
        "id": "skill_library",
        "label": "Skill library and mounted Skills",
        "market_pattern": "Hermes/OpenClaw/AstrBot Skill ecosystem for reusable task manuals.",
        "priority": "P0",
        "passed": [
            {
                "path": "apps/bridge/routes/agents.py",
                "fragments": [
                    "/skills",
                    "sync_native_skills",
                    "install_skill",
                    "attach_agent_skill",
                ],
            },
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": ["_load_agent_skills", "skill_markdown"],
            },
        ],
    },
    {
        "id": "skill_progressive_disclosure",
        "label": "Skill progressive disclosure",
        "market_pattern": "Load skill names/descriptions first, then full SKILL.md only when the task matches.",
        "priority": "P0",
        "passed": [
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": [
                    '"skill.read"',
                    "Skill summary index (progressive disclosure)",
                    "Call skill.read with skill_id",
                    "def skill_read",
                ],
            }
        ],
        "partial": [
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": ["_load_agent_skills", "skill_markdown"],
            }
        ],
        "next_action": "Add a Skill summary index and a model/tool path to expand full SKILL.md only after task matching.",
    },
    {
        "id": "agent_managed_long_term_memory",
        "label": "Agent-managed long-term memory",
        "market_pattern": "Hermes/OpenClaw-style explicit durable memory/user profile, bounded and injected across sessions.",
        "priority": "P0",
        "passed": [
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": ["memory.add", "memory.replace", "memory.remove", "memory_items", "memory_events"],
            },
            {
                "path": "apps/bridge/routes/agents.py",
                "fragments": ["/memories", "create_memory", "update_memory", "delete_memory"],
            }
        ],
        "partial": [
            {
                "path": "apps/core/executor.py",
                "fragments": ["build_cross_session_memory_context", "_MEMORY_MARKERS"],
            },
            {
                "path": "docs/memory-architecture.md",
                "fragments": ["memory"],
            },
        ],
        "next_action": "Promote memory from history heuristics to explicit Agent-managed memory/user stores with add/replace/remove semantics.",
    },
    {
        "id": "future_task_proactivity",
        "label": "Future task and proactive execution",
        "market_pattern": "Open-Hanako/OpenClaw/AstrBot-style cron, heartbeat, standing orders, and FutureTask self wakeups.",
        "priority": "P1",
        "passed": [
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": [
                    "future_task.schedule",
                    "future_task.list",
                    "future_task.cancel",
                    "future_tasks",
                    "trigger_due_future_tasks",
                ],
            },
            {
                "path": "apps/bridge/routes/agents.py",
                "fragments": ["/future-tasks", "schedule_future_task", "trigger_due_future_tasks"],
            }
        ],
        "partial": [
            {
                "path": "apps/shell/proactive.py",
                "fragments": ["class ProactiveDesktopService", "trigger_now", "desktop_watch"],
            }
        ],
        "next_action": "Extend proactive desktop observation into user-visible future tasks with editable schedules and delivery targets.",
    },
    {
        "id": "external_channel_bridge",
        "label": "External channel bridge",
        "market_pattern": "OpenClaw/AstrBot channel adapters route chat surfaces into the same Agent runtime.",
        "priority": "P1",
        "passed": [
            {
                "path": "integrations/astrbot_plugin/api_client.py",
                "fragments": ["assistant_intent", "X-Oha-Yachiyo-Bridge-Token"],
            },
            {
                "path": "integrations/astrbot_plugin/main.py",
                "fragments": ["on_y_command", "allowed_senders"],
            },
        ],
    },
    {
        "id": "security_governance",
        "label": "Security, sandbox, and governance floor",
        "market_pattern": "Approvals, redaction, workspace scopes, least privilege, and operator boundary.",
        "priority": "P0",
        "passed": [
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": [
                    "redact_secrets",
                    "readable_scopes",
                    "writable_scopes",
                    "_HIGH_RISK_AGENT_TOOLS",
                    "approval_required",
                ],
            },
            {
                "path": "packages/security/__init__.py",
                "fragments": ["redact", "sensitive"],
            },
        ],
    },
    {
        "id": "observability_and_replay",
        "label": "Observability, events, and replay",
        "market_pattern": "Gateway/UI traces, run events, artifacts, and diagnostics for debuggable Agent behavior.",
        "priority": "P1",
        "passed": [
            {
                "path": "apps/shell/agent_runtime.py",
                "fragments": ["append_run_event", "RunEventRepository", "timeline"],
            },
            {
                "path": "apps/bridge/routes/agents.py",
                "fragments": ["/runs", "list_runs", "get_run"],
            },
        ],
    },
)


def _project_file(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve(strict=False)
    root_path = root.resolve(strict=False)
    try:
        candidate.relative_to(root_path)
    except ValueError:
        raise ValueError(f"path must stay inside project root: {relative_path}")
    return candidate


def _evidence_matches(root: Path, evidence: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    path = str(evidence.get("path") or "").strip()
    fragments = [str(item) for item in evidence.get("fragments") or []]
    if not path or not fragments:
        return False, {"path": path, "missing_fragments": fragments}
    try:
        text = _project_file(root, path).read_text(encoding="utf-8")
    except OSError as exc:
        return False, {"path": path, "error": str(exc), "missing_fragments": fragments}
    missing = [fragment for fragment in fragments if fragment not in text]
    return not missing, {"path": path, "fragments": fragments, "missing_fragments": missing}


def _group_matches(root: Path, items: Sequence[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    evidence_results: list[dict[str, Any]] = []
    ok = True
    for item in items:
        matched, evidence = _evidence_matches(root, item)
        evidence_results.append(evidence)
        ok = ok and matched
    return ok, evidence_results


def summarize_market_parity(root: Path) -> dict[str, Any]:
    capabilities: list[dict[str, Any]] = []
    for requirement in MARKET_REQUIREMENTS:
        passed, passed_evidence = _group_matches(root, requirement.get("passed") or [])
        partial = False
        partial_evidence: list[dict[str, Any]] = []
        if not passed and requirement.get("partial"):
            partial, partial_evidence = _group_matches(root, requirement.get("partial") or [])
        status = "passed" if passed else "partial" if partial else "missing"
        capability = {
            "id": requirement["id"],
            "label": requirement["label"],
            "market_pattern": requirement["market_pattern"],
            "priority": requirement["priority"],
            "status": status,
            "evidence": passed_evidence if passed or not partial_evidence else partial_evidence,
        }
        if status != "passed":
            capability["next_action"] = requirement.get("next_action") or "Implement this market Agent capability and add source/runtime evidence."
        capabilities.append(capability)

    status_counts = {
        status: sum(1 for capability in capabilities if capability["status"] == status)
        for status in ("passed", "partial", "missing")
    }
    incomplete = [
        str(capability["id"])
        for capability in capabilities
        if capability["status"] != "passed"
    ]
    return {
        "ok": not incomplete,
        "status": "passed" if not incomplete else "incomplete",
        "capability_count": len(capabilities),
        "status_counts": status_counts,
        "incomplete_capability_ids": incomplete,
        "capabilities": capabilities,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, help="Write the market Agent parity JSON.")
    args = parser.parse_args(argv)
    try:
        summary = summarize_market_parity(PROJECT_ROOT)
        if args.output_json is not None:
            output = args.output_json if args.output_json.is_absolute() else PROJECT_ROOT / args.output_json
            _write_report(output, summary)
        else:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"Agent market parity summary: failed\n- {exc}", file=sys.stderr)
        return 1
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
