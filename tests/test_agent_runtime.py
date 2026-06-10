"""Agent Runtime Service tests."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import subprocess
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.agent_runtime import (
    AgentRuntimeError,
    AgentRuntimeService,
    ApprovalResumeCoordinator,
    NativeRunEngine,
    ToolApprovalResumeContext,
    ToolBroker,
    WorkflowContinuationCoordinator,
    WorkflowParentResumeCoordinator,
)
from scripts.verify_secret_redaction import verify_secret_redaction


def make_service(tmp_path, *, seed_templates: bool = False) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=seed_templates,
    )


def test_agent_runtime_service_is_native_run_engine_compatibility_name():
    assert AgentRuntimeService is NativeRunEngine


def test_approval_resume_coordinator_executes_approved_tool_and_remaining_requests():
    calls: list[tuple[str, dict[str, object]]] = []
    broker = SimpleNamespace(name="broker")
    budget = SimpleNamespace(name="budget")
    timeline: list[dict[str, object]] = []
    artifacts: list[dict[str, object]] = []
    messages: list[dict[str, object]] = [{"role": "user", "content": "run approved tool"}]
    tool_request = {"name": "terminal.run", "input": {"command": "printf ok"}}
    remaining_requests = [{"name": "artifact.write", "input": {"path": "report.md"}}]

    def call_agent_tool(
        request,
        allowed_tools,
        tool_broker,
        run_timeline,
        *,
        artifacts,
        approved,
        run_id,
        budget,
    ):
        calls.append(
            (
                "call_agent_tool",
                {
                    "request": request,
                    "allowed_tools": allowed_tools,
                    "broker": tool_broker,
                    "timeline": run_timeline,
                    "artifacts": artifacts,
                    "approved": approved,
                    "run_id": run_id,
                    "budget": budget,
                },
            )
        )
        return {"ok": True, "stdout": "ok"}

    def append_tool_result_message(run_messages, request, tool_result):
        calls.append(("append_tool_result_message", {"request": request, "tool_result": tool_result}))
        run_messages.append({"role": "tool", "content": json.dumps(tool_result)})

    def run_tool_requests(
        requests,
        allowed_tools,
        tool_broker,
        run_messages,
        run_timeline,
        run_artifacts,
        *,
        next_iteration,
        run_id,
        budget,
    ):
        calls.append(
            (
                "run_tool_requests",
                {
                    "requests": requests,
                    "allowed_tools": allowed_tools,
                    "broker": tool_broker,
                    "messages": run_messages,
                    "timeline": run_timeline,
                    "artifacts": run_artifacts,
                    "next_iteration": next_iteration,
                    "run_id": run_id,
                    "budget": budget,
                },
            )
        )

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=call_agent_tool,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=append_tool_result_message,
        run_tool_requests=run_tool_requests,
        timeline_factory=lambda event, detail, **payload: {"event": event, "detail": detail, **payload},
    )

    coordinator.execute_approved_tool(
        ToolApprovalResumeContext(
            run_id="run_approved",
            timeline=timeline,
            artifacts=artifacts,
            broker=broker,
            allowed_tools=["terminal.run", "artifact.write"],
            budget=budget,
            messages=messages,
            tool_request=tool_request,
            tool_name="terminal.run",
            input_preview={"command": "printf ok"},
            remaining_requests=remaining_requests,
            next_iteration=7,
        )
    )

    assert [name for name, _payload in calls] == [
        "call_agent_tool",
        "append_tool_result_message",
        "run_tool_requests",
    ]
    assert calls[0][1]["approved"] is True
    assert calls[0][1]["run_id"] == "run_approved"
    assert calls[0][1]["broker"] is broker
    assert calls[0][1]["budget"] is budget
    assert calls[1][1]["tool_result"] == {"ok": True, "stdout": "ok"}
    assert calls[2][1]["requests"] == remaining_requests
    assert calls[2][1]["next_iteration"] == 7
    assert messages[-1] == {"role": "tool", "content": '{"ok": true, "stdout": "ok"}'}


def test_approval_resume_coordinator_stops_on_fatal_tool_failure():
    calls: list[str] = []
    timeline: list[dict[str, object]] = []

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {"ok": False, "stderr": "denied"},
        fatal_tool_failure_detail=lambda *_args: "terminal.run failed fatally",
        append_tool_result_message=lambda *_args: calls.append("append_tool_result_message"),
        run_tool_requests=lambda *_args, **_kwargs: calls.append("run_tool_requests"),
        timeline_factory=lambda event, detail, **payload: {"event": event, "detail": detail, **payload},
    )

    with pytest.raises(AgentRuntimeError, match="terminal.run failed fatally"):
        coordinator.execute_approved_tool(
            ToolApprovalResumeContext(
                run_id="run_failed",
                timeline=timeline,
                artifacts=[],
                broker=SimpleNamespace(name="broker"),
                allowed_tools=["terminal.run"],
                budget=SimpleNamespace(name="budget"),
                messages=[],
                tool_request={"name": "terminal.run", "input": {"command": "false"}},
                tool_name="terminal.run",
                input_preview={"command": "false"},
                remaining_requests=[{"name": "artifact.write"}],
                next_iteration=2,
            )
        )

    assert calls == []
    assert timeline == [
        {
            "event": "agent.tool.failed",
            "detail": "terminal.run",
            "input_preview": {"command": "false"},
            "result": {"ok": False, "stderr": "denied"},
            "status": "failed",
        }
    ]


def test_workflow_parent_resume_coordinator_continues_completed_child():
    appended_events: list[tuple[str, str, dict[str, object]]] = []
    continued: dict[str, object] = {}
    child_node_info = {
        "workflow_node_id": "agent",
        "workflow_node_kind": "agent",
        "workflow_node_label": "Research Agent",
    }
    child_artifact = {
        "kind": "workflow_child_artifact",
        "source_run_id": "child_run",
        "path": "reports/result.md",
    }

    workflow_run = {
        "run_id": "workflow_parent",
        "run_group_id": "run_group_parent",
        "timeline": [
            {
                "event": "workflow.run.approval_required",
                "child_run_id": "child_run",
                **child_node_info,
            }
        ],
        "artifacts": [],
    }
    child_run = {
        "run_id": "child_run",
        "status": "completed",
        "result": "Child Agent completed after approval.",
        "runnable_name": "Research Agent",
    }

    def merge_child_outcome(timeline, artifacts, run, label):
        assert run is child_run
        assert label == "Research Agent"
        artifacts.append(dict(child_artifact))

    def continue_workflow_run(
        run,
        workflow,
        *,
        context,
        timeline,
        artifacts,
        start_index,
        root_group,
    ):
        continued.update(
            {
                "run": run,
                "workflow": workflow,
                "context": context,
                "timeline": timeline,
                "artifacts": artifacts,
                "start_index": start_index,
                "root_group": root_group,
            }
        )
        return {"run_id": run["run_id"], "status": "completed", "result": context}

    coordinator = WorkflowParentResumeCoordinator(
        parent_runs_waiting_for_child=lambda _child: [workflow_run],
        workflow_run_is_group_root=lambda _run: True,
        workflow_child_node_context=lambda _timeline, _child: (
            "Research Agent",
            dict(child_node_info),
        ),
        merge_workflow_child_run_outcome=merge_child_outcome,
        workflow_for_run_resume=lambda _run: {"workflow_id": "workflow_demo"},
        workflow_resume_start_index=lambda _workflow, _run, child_run_id: (
            3 if child_run_id == "child_run" else None
        ),
        continue_workflow_run=continue_workflow_run,
        timeline_factory=lambda event, detail, **payload: {"event": event, "detail": detail, **payload},
        append_run_event=lambda run_id, event_type, payload: appended_events.append((run_id, event_type, payload)),
        update_run=lambda *_args, **_kwargs: pytest.fail(
            "completed child continuation should not update parent directly"
        ),
        update_run_group=lambda *_args, **_kwargs: pytest.fail(
            "completed child continuation should not update group directly"
        ),
    )

    result = coordinator.resume_parent_after_child_update(workflow_run, child_run)

    assert result == {
        "run_id": "workflow_parent",
        "status": "completed",
        "result": "Child Agent completed after approval.",
    }
    assert continued["run"] is workflow_run
    assert continued["workflow"] == {"workflow_id": "workflow_demo"}
    assert continued["context"] == "Child Agent completed after approval."
    assert continued["start_index"] == 3
    assert continued["root_group"] is True
    assert continued["artifacts"] == [child_artifact]
    continued_timeline = continued["timeline"]
    assert isinstance(continued_timeline, list)
    assert continued_timeline[-1] == {
        "event": "workflow.run.resumed",
        "detail": "Workflow resumed after child Agent approval",
        "child_run_id": "child_run",
        "status": "running",
        **child_node_info,
    }
    assert appended_events == [
        (
            "workflow_parent",
            "workflow.node.agent",
            {
                "child_run_id": "child_run",
                "status": "completed",
                "result": "Child Agent completed after approval.",
                "artifact_count": 1,
                **child_node_info,
            },
        ),
        (
            "workflow_parent",
            "workflow.run.resumed",
            {
                "child_run_id": "child_run",
                "status": "running",
                **child_node_info,
            },
        ),
    ]


def test_workflow_parent_resume_coordinator_does_not_resume_completed_child_twice():
    workflow_run = {
        "run_id": "workflow_parent",
        "run_group_id": "run_group_parent",
        "status": "completed",
        "timeline": [
            {
                "event": "workflow.run.resumed",
                "child_run_id": "child_run",
                "status": "running",
                "workflow_node_id": "agent",
            },
            {
                "event": "workflow.run.completed",
                "detail": "Workflow run completed",
            },
        ],
        "artifacts": [{"kind": "workflow_artifact", "path": "summary.md"}],
        "result": "Child Agent completed after approval.",
    }
    child_run = {
        "run_id": "child_run",
        "status": "completed",
        "result": "Child Agent completed after approval.",
        "runnable_name": "Research Agent",
    }

    coordinator = WorkflowParentResumeCoordinator(
        parent_runs_waiting_for_child=lambda _child: [workflow_run],
        workflow_run_is_group_root=lambda _run: True,
        workflow_child_node_context=lambda *_args: pytest.fail("already resumed child should not be re-projected"),
        merge_workflow_child_run_outcome=lambda *_args: pytest.fail("already resumed child should not merge again"),
        workflow_for_run_resume=lambda *_args: pytest.fail("already resumed child should not load workflow"),
        workflow_resume_start_index=lambda *_args: pytest.fail("already resumed child should not compute start index"),
        continue_workflow_run=lambda *_args, **_kwargs: pytest.fail("already resumed child should not continue twice"),
        timeline_factory=lambda event, detail, **payload: {"event": event, "detail": detail, **payload},
        append_run_event=lambda *_args: pytest.fail("already resumed child should not append replay facts"),
        update_run=lambda *_args, **_kwargs: pytest.fail("already resumed child should not update parent"),
        update_run_group=lambda *_args, **_kwargs: pytest.fail("already resumed child should not update group"),
    )

    result = coordinator.resume_parent_after_child_update(workflow_run, child_run)

    assert result is workflow_run
    assert workflow_run["timeline"] == [
        {
            "event": "workflow.run.resumed",
            "child_run_id": "child_run",
            "status": "running",
            "workflow_node_id": "agent",
        },
        {
            "event": "workflow.run.completed",
            "detail": "Workflow run completed",
        },
    ]
    assert workflow_run["artifacts"] == [{"kind": "workflow_artifact", "path": "summary.md"}]


def test_workflow_continuation_coordinator_pauses_for_approval_node():
    class FakeEngine:
        def __init__(self):
            self.events: list[tuple[str, str, dict[str, object]]] = []
            self.run_updates: list[tuple[str, dict[str, object]]] = []
            self.group_updates: list[tuple[str, dict[str, object]]] = []

        def _workflow_path(self, workflow):
            return workflow["nodes"]

        def _node_kind(self, node):
            return node["type"]

        def _workflow_approval_criteria(self, node):
            return str((node.get("data") or {}).get("criteria") or "")

        def _timeline(self, event, detail, **payload):
            return {"event": event, "detail": detail, **payload}

        def append_run_event(self, run_id, event_type, payload):
            self.events.append((run_id, event_type, payload))

        def _update_run(self, run_id, **fields):
            self.run_updates.append((run_id, fields))
            return {"run_id": run_id, "run_group_id": "run_group", **fields}

        def _update_run_group(self, run_group_id, **fields):
            self.group_updates.append((run_group_id, fields))

        def get_run(self, run_id):
            assert run_id == "workflow_run"
            assert self.run_updates
            fields = dict(self.run_updates[-1][1])
            private_pending = fields.get("pending_approval")
            if isinstance(private_pending, dict):
                fields["pending_approval"] = {
                    "approval_id": str(private_pending.get("approval_id") or ""),
                    "tool": str(private_pending.get("tool") or ""),
                    "input_preview": private_pending.get("input_preview") or {},
                    "requested_at": str(private_pending.get("requested_at") or ""),
                }
            return {
                "run_id": run_id,
                "run_group_id": "run_group",
                **fields,
            }

    engine = FakeEngine()
    coordinator = WorkflowContinuationCoordinator(engine)
    timeline: list[dict[str, object]] = []
    artifacts: list[dict[str, object]] = []
    run = {
        "run_id": "workflow_run",
        "run_group_id": "run_group",
        "user_goal": "Ship workflow",
    }
    workflow = {
        "nodes": [
            {
                "id": "gate",
                "type": "approval",
                "data": {
                    "label": "Human Gate",
                    "criteria": "Review child output before continuing.",
                },
            }
        ]
    }

    result = coordinator.continue_run(
        run,
        workflow,
        context="Child result ready",
        timeline=timeline,
        artifacts=artifacts,
        start_index=0,
        root_group=True,
    )

    pending = result["pending_approval"]
    assert result["status"] == "approval_required"
    assert result["result"] == "等待审批：Human Gate"
    assert pending["tool"] == "workflow.approval"
    assert pending["input_preview"] == {
        "checkpoint": "Human Gate",
        "context": "Child result ready",
        "criteria": "Review child output before continuing.",
    }
    assert "workflow_context" not in pending
    assert timeline == [
        {
            "event": "workflow.node.approval_required",
            "detail": "Human Gate",
            "workflow_node_id": "gate",
            "workflow_node_kind": "approval",
            "workflow_node_label": "Human Gate",
            "workflow_node_approval_criteria": "Review child output before continuing.",
            "status": "approval_required",
            "pending_approval": pending,
        }
    ]
    assert engine.events == [
        (
            "workflow_run",
            "workflow.node.approval_required",
            {
                "workflow_node_id": "gate",
                "workflow_node_kind": "approval",
                "workflow_node_label": "Human Gate",
                "workflow_node_approval_criteria": "Review child output before continuing.",
                "status": "approval_required",
                "pending_approval": pending,
            },
        )
    ]
    assert len(engine.run_updates) == 1
    run_id, run_update = engine.run_updates[0]
    assert run_id == "workflow_run"
    assert run_update["status"] == "approval_required"
    assert run_update["result"] == "等待审批：Human Gate"
    assert run_update["timeline"] is timeline
    assert run_update["artifacts"] is artifacts
    private_pending = run_update["pending_approval"]
    assert private_pending["approval_id"].startswith("approval_")
    assert private_pending["workflow_context"] == "Child result ready"
    assert private_pending["workflow_next_index"] == 1
    assert private_pending["workflow_node_id"] == "gate"
    assert private_pending["workflow_node_label"] == "Human Gate"
    assert private_pending["workflow_node_approval_criteria"] == "Review child output before continuing."
    assert engine.group_updates == [
        (
            "run_group",
            {
                "status": "approval_required",
                "summary": "等待审批：Human Gate",
            },
        )
    ]


def test_workflow_continuation_coordinator_fails_unknown_node_without_secret_leak():
    leaked_secret = "sk-workflow-continuation-secret123456"

    class FakeEngine:
        def __init__(self):
            self.events: list[tuple[str, str, dict[str, object]]] = []
            self.run_updates: list[tuple[str, dict[str, object]]] = []
            self.group_updates: list[tuple[str, dict[str, object]]] = []

        def _workflow_path(self, workflow):
            return workflow["nodes"]

        def _node_kind(self, node):
            return node["type"]

        def _timeline(self, event, detail, **payload):
            return {"event": event, "detail": detail, **payload}

        def append_run_event(self, run_id, event_type, payload):
            self.events.append((run_id, event_type, payload))

        def _update_run(self, run_id, **fields):
            self.run_updates.append((run_id, fields))
            return {"run_id": run_id, "run_group_id": "run_group", **fields}

        def _update_run_group(self, run_group_id, **fields):
            self.group_updates.append((run_group_id, fields))

        def get_run(self, run_id):
            assert run_id == "workflow_run"
            assert self.run_updates
            return {
                "run_id": run_id,
                "run_group_id": "run_group",
                **self.run_updates[-1][1],
            }

    engine = FakeEngine()
    coordinator = WorkflowContinuationCoordinator(engine)
    timeline: list[dict[str, object]] = []
    artifacts: list[dict[str, object]] = []
    workflow = {
        "nodes": [
            {
                "id": "bad",
                "type": f"custom_api_key={leaked_secret}",
                "data": {"label": "Bad Node"},
            }
        ]
    }

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "run_group_id": "run_group", "user_goal": "Ship workflow"},
        workflow,
        context="previous context",
        timeline=timeline,
        artifacts=artifacts,
        start_index=0,
        root_group=True,
    )

    serialized = json.dumps(
        {
            "result": result,
            "timeline": timeline,
            "events": engine.events,
            "run_updates": engine.run_updates,
            "group_updates": engine.group_updates,
        },
        ensure_ascii=False,
    )
    assert result["status"] == "failed"
    assert leaked_secret not in serialized
    assert "[redacted]" in result["result"]
    assert timeline == [
        {
            "event": "workflow.run.failed",
            "detail": result["result"],
            "status": "failed",
            "workflow_node_id": "bad",
            "workflow_node_kind": "custom_api_key=[redacted]",
            "workflow_node_label": "Bad Node",
        }
    ]
    assert engine.events == [
        (
            "workflow_run",
            "workflow.run.failed",
            {
                "error": result["result"],
                "workflow_node_id": "bad",
                "workflow_node_kind": "custom_api_key=[redacted]",
                "workflow_node_label": "Bad Node",
            },
        )
    ]
    assert engine.run_updates == [
        (
            "workflow_run",
            {
                "status": "failed",
                "result": result["result"],
                "timeline": timeline,
                "artifacts": artifacts,
            },
        )
    ]
    assert engine.group_updates == [
        (
            "run_group",
            {
                "status": "failed",
                "summary": result["result"],
            },
        )
    ]


def test_workflow_continuation_coordinator_writes_artifact_node(tmp_path):
    class FakeEngine:
        def __init__(self):
            self.workflow_artifacts_dir = tmp_path / "workflow-artifacts"
            self.events: list[tuple[str, str, dict[str, object]]] = []
            self.run_updates: list[tuple[str, dict[str, object]]] = []
            self.group_updates: list[tuple[str, dict[str, object]]] = []

        def _workflow_path(self, workflow):
            return workflow["nodes"]

        def _node_kind(self, node):
            return node["type"]

        def _timeline(self, event, detail, **payload):
            return {"event": event, "detail": detail, **payload}

        def append_run_event(self, run_id, event_type, payload):
            self.events.append((run_id, event_type, payload))

        def _update_run(self, run_id, **fields):
            self.run_updates.append((run_id, fields))
            return {"run_id": run_id, "run_group_id": "run_group", **fields}

        def _update_run_group(self, run_group_id, **fields):
            self.group_updates.append((run_group_id, fields))

        def get_run(self, run_id):
            assert run_id == "workflow_run"
            assert self.run_updates
            return {
                "run_id": run_id,
                "run_group_id": "run_group",
                **self.run_updates[-1][1],
            }

        def _default_workspace_policy(self):
            return {"default_workdir": "", "readable_scopes": ["."], "writable_scopes": []}

        def _workflow_artifact_path(self, label, artifacts, requested):
            assert label == "Final Report"
            assert artifacts == []
            return requested or "final.md"

    engine = FakeEngine()
    coordinator = WorkflowContinuationCoordinator(engine)
    artifact_content = "Final workflow summary"
    artifact_bytes = len(artifact_content.encode("utf-8"))
    timeline: list[dict[str, object]] = []
    artifacts: list[dict[str, object]] = []
    workflow = {
        "nodes": [
            {
                "id": "report",
                "type": "artifact",
                "data": {
                    "label": "Final Report",
                    "artifact_path": "reports/final.md",
                },
            }
        ]
    }

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "run_group_id": "run_group", "user_goal": "Ship workflow"},
        workflow,
        context=artifact_content,
        timeline=timeline,
        artifacts=artifacts,
        start_index=0,
        root_group=True,
    )

    artifact_path = tmp_path / "workflow-artifacts" / "workflow_run" / "reports" / "final.md"
    assert artifact_path.read_text(encoding="utf-8") == artifact_content
    assert result["status"] == "completed"
    assert result["result"] == artifact_content
    assert artifacts == [
        {
            "kind": "workflow_artifact",
            "workflow_node_id": "report",
            "workflow_node_label": "Final Report",
            "ok": True,
            "path": "reports/final.md",
            "bytes": artifact_bytes,
        }
    ]
    assert timeline == [
        {
            "event": "workflow.node.artifact",
            "detail": "Final Report",
            "workflow_node_id": "report",
            "workflow_node_kind": "artifact",
            "workflow_node_label": "Final Report",
            "status": "completed",
            "artifact": {"ok": True, "path": "reports/final.md", "bytes": artifact_bytes},
        },
        {
            "event": "workflow.run.completed",
            "detail": "Workflow run completed",
        },
    ]
    assert engine.events == [
        (
            "workflow_run",
            "workflow.node.artifact",
            {
                "workflow_node_id": "report",
                "workflow_node_kind": "artifact",
                "workflow_node_label": "Final Report",
                "status": "completed",
                "artifact": {"ok": True, "path": "reports/final.md", "bytes": artifact_bytes},
            },
        ),
        (
            "workflow_run",
            "workflow.run.completed",
            {"result": artifact_content},
        ),
    ]
    assert engine.run_updates == [
        (
            "workflow_run",
            {
                "status": "completed",
                "result": artifact_content,
                "timeline": timeline,
                "artifacts": artifacts,
            },
        )
    ]
    assert engine.group_updates == [
        (
            "run_group",
            {"status": "completed", "summary": artifact_content},
        )
    ]


class FakeDefaultProfileService:
    def get_defaults(self):
        return {"chat": "profile_default"}

    def get_profile_private(self, profile_id):
        assert profile_id == "profile_default"
        return {
            "profile_id": profile_id,
            "provider": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
            "capability": "chat",
            "status": "available",
            "enabled": True,
        }


class FakeNoDefaultProfileService:
    def get_defaults(self):
        return {"chat": ""}

    def get_profile_private(self, profile_id):
        raise KeyError(profile_id)


def test_runtime_migrates_legacy_runs_before_index_creation(tmp_path):
    db_path = tmp_path / "agent-runtime.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            runnable_id TEXT NOT NULL,
            status TEXT NOT NULL,
            user_goal TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',
            timeline_json TEXT NOT NULL DEFAULT '[]',
            artifacts_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.close()

    service = make_service(tmp_path)
    try:
        columns = {row["name"] for row in service._conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "run_group_id" in columns
        indexes = {row["name"] for row in service._conn.execute("PRAGMA index_list(runs)").fetchall()}
        assert "idx_runs_group_updated" in indexes
    finally:
        service.close()


def test_runtime_migrates_task_run_link_projection_columns(tmp_path):
    db_path = tmp_path / "agent-runtime.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            run_group_id TEXT NOT NULL DEFAULT '',
            client_request_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            runnable_id TEXT NOT NULL,
            status TEXT NOT NULL,
            user_goal TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',
            timeline_json TEXT NOT NULL DEFAULT '[]',
            artifacts_json TEXT NOT NULL DEFAULT '[]',
            pending_approval_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE task_run_links (
            task_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'native_runtime',
            visibility TEXT NOT NULL DEFAULT 'user',
            sensitivity TEXT NOT NULL DEFAULT 'public',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
            UNIQUE (run_id, sequence)
        );
        INSERT INTO runs (
            run_id, kind, runnable_id, status, user_goal, result,
            timeline_json, artifacts_json, pending_approval_json, created_at, updated_at
        ) VALUES (
            'main_chat_run_legacy_link', 'main_chat_run', 'builtin:yachiyo-main', 'completed',
            'legacy task', 'done', '[]', '[]', '{}', '2026-06-09T00:00:00+00:00',
            '2026-06-09T00:00:01+00:00'
        );
        INSERT INTO task_run_links (task_id, run_id, session_id, created_at)
        VALUES (
            'task-legacy-link', 'main_chat_run_legacy_link', 'session-legacy-link',
            '2026-06-09T00:00:00+00:00'
        );
        INSERT INTO run_events (
            event_id, run_id, sequence, event_type, payload_json, created_at
        ) VALUES
            ('event_legacy_1', 'main_chat_run_legacy_link', 1, 'run.started', '{}', '2026-06-09T00:00:00+00:00'),
            ('event_legacy_2', 'main_chat_run_legacy_link', 2, 'run.completed', '{}', '2026-06-09T00:00:01+00:00');
        """
    )
    conn.commit()
    conn.close()

    service = make_service(tmp_path)
    try:
        link_columns = {row["name"] for row in service._conn.execute("PRAGMA table_info(task_run_links)").fetchall()}
        assert {"run_status", "last_event_sequence", "updated_at"}.issubset(link_columns)
        link = service.get_task_run_link("task-legacy-link")
        assert link["run_status"] == "completed"
        assert link["last_event_sequence"] == 2
        assert link["updated_at"] == "2026-06-09T00:00:00+00:00"
    finally:
        service.close()


def test_runtime_sqlite_enables_required_database_guards(tmp_path):
    service = make_service(tmp_path)
    try:
        metadata = {
            row["key"]: row["value"]
            for row in service._conn.execute("SELECT key, value FROM runtime_schema_metadata").fetchall()
        }
        assert metadata["schema_version"] == "1"
        assert service._conn.execute("PRAGMA foreign_keys").fetchone()["foreign_keys"] == 1
        assert service._conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"].lower() == "wal"
        assert service._conn.execute("PRAGMA busy_timeout").fetchone()["timeout"] == 5000
        link_columns = {row["name"] for row in service._conn.execute("PRAGMA table_info(task_run_links)").fetchall()}
        assert {"run_status", "last_event_sequence", "updated_at"}.issubset(link_columns)

        run = service.start_main_chat_run(task_id="task-db-guard", session_id="session-db-guard", user_goal="db guard")
        link = service.get_task_run_link("task-db-guard")
        assert link["run_id"] == run["run_id"]
        assert link["run_status"] == "running"
        assert link["last_event_sequence"] == 2

        service._conn.execute("DELETE FROM runs WHERE run_id=?", (run["run_id"],))
        service._conn.commit()

        with pytest.raises(KeyError):
            service.get_task_run_link("task-db-guard")
    finally:
        service.close()


def test_main_chat_run_links_task_and_records_replayable_events(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {"role": "assistant", "content": "完成 sk-secret-value"},
    )
    try:
        run = service.start_main_chat_run(
            task_id="task-main-1",
            session_id="session-main-1",
            user_goal="请处理",
        )
        result = service.call_main_chat_model(
            run["run_id"],
            [{"role": "user", "content": "请处理"}],
        )
        completed = service.complete_main_chat_run(run["run_id"], result)
        link = service.get_task_run_link("task-main-1")
        events = service.list_run_events(run["run_id"])["events"]

        assert link["run_id"] == run["run_id"]
        assert link["session_id"] == "session-main-1"
        assert link["run_status"] == "completed"
        assert link["last_event_sequence"] == len(events)
        assert completed["kind"] == "main_chat_run"
        assert completed["runnable_name"] == "Yachiyo"
        assert completed["status"] == "completed"
        assert completed["result"] == "完成 [redacted]"
        assert completed["task_id"] == "task-main-1"
        assert completed["session_id"] == "session-main-1"
        listed_run = next(item for item in service.list_runs()["runs"] if item["run_id"] == run["run_id"])
        assert listed_run["task_id"] == "task-main-1"
        assert listed_run["session_id"] == "session-main-1"
        assert listed_run["task_run_link_run_status"] == "completed"
        assert listed_run["task_run_link_last_event_sequence"] == len(events)
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert [event["event_type"] for event in events] == [
            "run.started",
            "task.linked",
            "model.request.started",
            "model.output.completed",
            "run.completed",
        ]
    finally:
        service.close()


def test_main_chat_cancelled_run_ignores_late_model_output(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    run = service.start_main_chat_run(
        task_id="task-main-cancel",
        session_id="session-main-cancel",
        user_goal="cancel me",
    )

    def fake_chat(*_args, **_kwargs):
        service.cancel_run(run["run_id"])
        return {"role": "assistant", "content": "late model output should not win"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)

    try:
        cancelled = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "cancel me"}],
        )
        completed_after_cancel = service.complete_main_chat_run(
            run["run_id"],
            "late model output should not win",
        )
        failed_after_cancel = service.fail_main_chat_run(
            run["run_id"],
            "late failure should not win",
        )
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        stored = service.get_run(run["run_id"])

        assert cancelled["status"] == "cancelled"
        assert completed_after_cancel["status"] == "cancelled"
        assert failed_after_cancel["status"] == "cancelled"
        assert stored["status"] == "cancelled"
        assert "late model output should not win" not in stored["result"]
        assert "model.output.completed" not in event_types
        assert "run.completed" not in event_types
        assert "run.failed" not in event_types
        assert event_types[-1] == "run.cancelled"
    finally:
        service.close()


def test_main_chat_model_output_is_truncated_by_runtime_budget(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    service.runtime_limits = service.runtime_limits.__class__(max_model_output_chars=20)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {"role": "assistant", "content": "x" * 60},
    )
    try:
        run = service.start_main_chat_run(
            task_id="task-main-budget",
            session_id="session-main-budget",
            user_goal="请处理",
        )
        result = service.call_main_chat_model(
            run["run_id"],
            [{"role": "user", "content": "请处理"}],
        )
        events = service.list_run_events(run["run_id"])["events"]
        output_event = next(event for event in events if event["event_type"] == "model.output.completed")

        assert len(result) <= 20
        assert "[truncated]" in result
        assert output_event["payload"]["content"] == result
        assert output_event["payload"]["truncated"] is True
    finally:
        service.close()


def test_main_chat_model_persists_batched_output_event_not_token_deltas(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    model_output = "chunk-" * 1000
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {"role": "assistant", "content": model_output},
    )
    try:
        run = service.start_main_chat_run(
            task_id="task-main-batched-output",
            session_id="session-main-batched-output",
            user_goal="请处理长输出",
        )
        result = service.call_main_chat_model(
            run["run_id"],
            [{"role": "user", "content": "请处理长输出"}],
        )
        rows = service._conn.execute(
            "SELECT event_type, payload_json FROM run_events WHERE run_id=? ORDER BY sequence",
            (run["run_id"],),
        ).fetchall()
        output_rows = [row for row in rows if row["event_type"] == "model.output.completed"]

        assert result == model_output
        assert len(output_rows) == 1
        assert json.loads(output_rows[0]["payload_json"])["content"] == model_output
        assert not any(str(row["event_type"]).endswith(".delta") for row in rows)
    finally:
        service.close()


def test_main_chat_model_loop_coalesces_stream_chunks_before_persisting(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    chunks = [f"chunk-{index};" for index in range(300)]
    expected = "".join(chunks)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None, stream=False):
        assert tools is not None
        assert stream is True

        def stream():
            for chunk in chunks:
                yield {"choices": [{"delta": {"content": chunk}}]}

        return stream()

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-stream-batched-output",
            session_id="session-main-stream-batched-output",
            user_goal="请处理 streaming 输出",
        )
        updated = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "请处理 streaming 输出"}],
        )
        rows = service._conn.execute(
            "SELECT event_type, payload_json FROM run_events WHERE run_id=? ORDER BY sequence",
            (run["run_id"],),
        ).fetchall()
        output_rows = [row for row in rows if row["event_type"] == "model.output.completed"]

        assert updated["result"] == expected
        assert len(output_rows) == 1
        assert json.loads(output_rows[0]["payload_json"])["content"] == expected
        assert not any(str(row["event_type"]).endswith(".delta") for row in rows)
    finally:
        service.close()


def test_main_chat_model_consumes_openai_compatible_sse_stream(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    chunks = ["native ", "http ", "sse"]
    expected = "".join(chunks)
    requests = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            for chunk in chunks:
                payload = json.dumps({"choices": [{"delta": {"content": chunk}}]})
                yield f"data: {payload}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, **kwargs):
        body = json.loads(request.data.decode("utf-8"))
        requests.append({"request": request, "body": body, "kwargs": kwargs})
        assert request.full_url == "https://api.example.test/v1/chat/completions"
        assert request.get_header("Accept") == "text/event-stream"
        assert body["stream"] is True
        assert "tools" not in body
        return FakeResponse()

    monkeypatch.setattr("apps.core.tls.urlrequest.urlopen", fake_urlopen)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-http-sse-stream",
            session_id="session-main-http-sse-stream",
            user_goal="Use native HTTP SSE stream",
        )
        result = service.call_main_chat_model(
            run["run_id"],
            [{"role": "user", "content": "Use native HTTP SSE stream"}],
        )
        rows = service._conn.execute(
            "SELECT event_type, payload_json FROM run_events WHERE run_id=? ORDER BY sequence",
            (run["run_id"],),
        ).fetchall()
        output_rows = [row for row in rows if row["event_type"] == "model.output.completed"]

        assert result == expected
        assert len(requests) == 1
        assert len(output_rows) == 1
        assert json.loads(output_rows[0]["payload_json"])["content"] == expected
        assert not any(str(row["event_type"]).endswith(".delta") for row in rows)
    finally:
        service.close()


def test_main_chat_model_consumes_coalesced_openai_compatible_sse_frames(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    requests = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            first = json.dumps({"choices": [{"delta": {"content": "coalesced "}}]})
            second = json.dumps({"choices": [{"delta": {"content": "frames"}}]})
            yield f": keepalive\n\ndata: {first}\n\ndata: {second}\n\ndata: [DONE]\n\n".encode("utf-8")

    def fake_urlopen(request, **kwargs):
        body = json.loads(request.data.decode("utf-8"))
        requests.append({"request": request, "body": body, "kwargs": kwargs})
        assert request.full_url == "https://api.example.test/v1/chat/completions"
        assert request.get_header("Accept") == "text/event-stream"
        assert body["stream"] is True
        return FakeResponse()

    monkeypatch.setattr("apps.core.tls.urlrequest.urlopen", fake_urlopen)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-http-coalesced-sse-stream",
            session_id="session-main-http-coalesced-sse-stream",
            user_goal="Use coalesced native HTTP SSE stream",
        )
        result = service.call_main_chat_model(
            run["run_id"],
            [{"role": "user", "content": "Use coalesced native HTTP SSE stream"}],
        )
        events = service.list_run_events(run["run_id"])["events"]
        output_events = [event for event in events if event["event_type"] == "model.output.completed"]

        assert result == "coalesced frames"
        assert len(requests) == 1
        assert output_events[-1]["payload"]["content"] == "coalesced frames"
        assert not any(str(event["event_type"]).endswith(".delta") for event in events)
    finally:
        service.close()


def test_main_chat_model_consumes_split_openai_compatible_sse_frame_chunks(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    requests = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            payload = json.dumps({"choices": [{"delta": {"content": "split runtime frame"}}]})
            frame = f"data: {payload}\n\ndata: [DONE]\n\n".encode("utf-8")
            yield frame[:8]
            yield frame[8:29]
            yield frame[29:53]
            yield frame[53:]

    def fake_urlopen(request, **kwargs):
        body = json.loads(request.data.decode("utf-8"))
        requests.append({"request": request, "body": body, "kwargs": kwargs})
        assert request.full_url == "https://api.example.test/v1/chat/completions"
        assert request.get_header("Accept") == "text/event-stream"
        assert body["stream"] is True
        return FakeResponse()

    monkeypatch.setattr("apps.core.tls.urlrequest.urlopen", fake_urlopen)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-http-split-sse-frame",
            session_id="session-main-http-split-sse-frame",
            user_goal="Use split native HTTP SSE frame",
        )
        result = service.call_main_chat_model(
            run["run_id"],
            [{"role": "user", "content": "Use split native HTTP SSE frame"}],
        )
        events = service.list_run_events(run["run_id"])["events"]
        output_events = [event for event in events if event["event_type"] == "model.output.completed"]

        assert result == "split runtime frame"
        assert len(requests) == 1
        assert output_events[-1]["payload"]["content"] == "split runtime frame"
        assert not any(str(event["event_type"]).endswith(".delta") for event in events)
    finally:
        service.close()


def test_main_chat_model_consumes_multiline_openai_compatible_sse_data_event(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    requests = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield (
                b"id: runtime-chunk-1\r\n"
                b"event: completion.chunk\r\n"
                b'data: {"choices":[{"delta":{"content":"runtime multiline"}\r\n'
                b'data: ,"finish_reason":"stop"}]}\r\n\r\n'
                b"data: [DONE]\r\n\r\n"
            )

    def fake_urlopen(request, **kwargs):
        body = json.loads(request.data.decode("utf-8"))
        requests.append({"request": request, "body": body, "kwargs": kwargs})
        assert request.full_url == "https://api.example.test/v1/chat/completions"
        assert request.get_header("Accept") == "text/event-stream"
        assert body["stream"] is True
        return FakeResponse()

    monkeypatch.setattr("apps.core.tls.urlrequest.urlopen", fake_urlopen)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-http-multiline-sse-data",
            session_id="session-main-http-multiline-sse-data",
            user_goal="Use multiline native HTTP SSE data event",
        )
        result = service.call_main_chat_model(
            run["run_id"],
            [{"role": "user", "content": "Use multiline native HTTP SSE data event"}],
        )
        events = service.list_run_events(run["run_id"])["events"]
        output_events = [event for event in events if event["event_type"] == "model.output.completed"]

        assert result == "runtime multiline"
        assert len(requests) == 1
        assert output_events[-1]["payload"]["content"] == "runtime multiline"
        assert not any(str(event["event_type"]).endswith(".delta") for event in events)
    finally:
        service.close()


def test_main_chat_model_loop_executes_openai_compatible_sse_tool_calls(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("http sse tool content", encoding="utf-8")
    requests = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    class FakeResponse:
        def __init__(self, lines):
            self._lines = lines

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            for line in self._lines:
                yield line

    def event(payload: dict) -> bytes:
        return f"data: {json.dumps(payload)}\n\n".encode("utf-8")

    first_response = FakeResponse(
        [
            event(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_http_sse_read",
                                        "type": "function",
                                        "function": {"name": "workspace_", "arguments": '{"path": "READ'},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ),
            event(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"name": "read", "arguments": 'ME.md"}'}}
                                ]
                            }
                        }
                    ]
                }
            ),
            b"data: [DONE]\n\n",
        ]
    )
    second_response = FakeResponse(
        [
            event({"choices": [{"delta": {"content": "HTTP SSE tool call complete"}}]}),
            b"data: [DONE]\n\n",
        ]
    )
    responses = [first_response, second_response]

    def fake_urlopen(request, **kwargs):
        body = json.loads(request.data.decode("utf-8"))
        requests.append({"request": request, "body": body, "kwargs": kwargs})
        assert request.full_url == "https://api.example.test/v1/chat/completions"
        assert request.get_header("Accept") == "text/event-stream"
        assert body["stream"] is True
        return responses.pop(0)

    monkeypatch.setattr("apps.core.tls.urlrequest.urlopen", fake_urlopen)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-http-sse-tool-call",
            session_id="session-main-http-sse-tool-call",
            user_goal="Read README through HTTP SSE tool call",
        )
        updated = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README"}],
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        tool_event = next(event for event in events if event["event_type"] == "agent.tool.call")

        assert updated["result"] == "HTTP SSE tool call complete"
        assert len(requests) == 2
        assert "tools" in requests[0]["body"]
        assert requests[0]["body"]["tools"][0]["function"]["name"] == "workspace_read"
        assert requests[1]["body"]["messages"][-1]["role"] == "tool"
        assert requests[1]["body"]["messages"][-1]["tool_call_id"] == "call_http_sse_read"
        assert "http sse tool content" in requests[1]["body"]["messages"][-1]["content"]
        assert tool_event["payload"]["tool"] == "workspace.read"
        assert tool_event["payload"]["input_preview"]["path"] == "README.md"
        assert event_types.count("agent.tool.call") == 1
        assert event_types.count("model.output.completed") == 1
        assert not any(str(event_type).endswith(".delta") for event_type in event_types)
    finally:
        service.close()


def test_main_chat_model_loop_executes_split_openai_compatible_sse_tool_call_frames(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("split http sse tool content", encoding="utf-8")
    requests = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    class FakeResponse:
        def __init__(self, chunks):
            self._chunks = chunks

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            for chunk in self._chunks:
                yield chunk

    def event(payload: dict) -> bytes:
        return f"data: {json.dumps(payload)}\n\n".encode("utf-8")

    def split_frame(frame: bytes) -> list[bytes]:
        return [frame[:11], frame[11:47], frame[47:93], frame[93:]]

    first_tool_delta = event(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_http_sse_split_read",
                                "type": "function",
                                "function": {"name": "workspace_", "arguments": '{"path": "READ'},
                            }
                        ]
                    }
                }
            ]
        }
    )
    second_tool_delta = event(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"name": "read", "arguments": 'ME.md"}'}}
                        ]
                    }
                }
            ]
        }
    )
    first_response = FakeResponse([
        *split_frame(first_tool_delta),
        *split_frame(second_tool_delta),
        *split_frame(b"data: [DONE]\n\n"),
    ])
    second_response = FakeResponse(
        split_frame(event({"choices": [{"delta": {"content": "Split HTTP SSE tool call complete"}}]}))
        + [b"data: [DONE]\n\n"]
    )
    responses = [first_response, second_response]

    def fake_urlopen(request, **kwargs):
        body = json.loads(request.data.decode("utf-8"))
        requests.append({"request": request, "body": body, "kwargs": kwargs})
        assert request.full_url == "https://api.example.test/v1/chat/completions"
        assert request.get_header("Accept") == "text/event-stream"
        assert body["stream"] is True
        return responses.pop(0)

    monkeypatch.setattr("apps.core.tls.urlrequest.urlopen", fake_urlopen)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-split-http-sse-tool-call",
            session_id="session-main-split-http-sse-tool-call",
            user_goal="Read README through split HTTP SSE tool call",
        )
        updated = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README"}],
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        tool_event = next(event for event in events if event["event_type"] == "agent.tool.call")

        assert updated["result"] == "Split HTTP SSE tool call complete"
        assert len(requests) == 2
        assert requests[1]["body"]["messages"][-1]["role"] == "tool"
        assert requests[1]["body"]["messages"][-1]["tool_call_id"] == "call_http_sse_split_read"
        assert "split http sse tool content" in requests[1]["body"]["messages"][-1]["content"]
        assert tool_event["payload"]["tool"] == "workspace.read"
        assert tool_event["payload"]["input_preview"]["path"] == "README.md"
        assert event_types.count("agent.tool.call") == 1
        assert event_types.count("model.output.completed") == 1
        assert not any(str(event_type).endswith(".delta") for event_type in event_types)
    finally:
        service.close()


def test_main_chat_model_loop_fails_on_openai_compatible_sse_error(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    leaked_secret = "sk-http-sse-provider-error123456"
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            yield (
                "data: "
                + json.dumps(
                    {
                        "error": {
                            "message": f"provider stream rejected token={leaked_secret}",
                            "type": "rate_limit_error",
                            "code": "quota_exceeded",
                        }
                    }
                )
                + "\n\n"
            ).encode("utf-8")

    def fake_urlopen(request, **kwargs):
        body = json.loads(request.data.decode("utf-8"))
        assert request.full_url == "https://api.example.test/v1/chat/completions"
        assert request.get_header("Accept") == "text/event-stream"
        assert body["stream"] is True
        return FakeResponse()

    monkeypatch.setattr("apps.core.tls.urlrequest.urlopen", fake_urlopen)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-http-sse-error",
            session_id="session-main-http-sse-error",
            user_goal=f"Handle provider error token={leaked_secret}",
        )

        with pytest.raises(Exception, match="OpenAI-compatible Profile 调用失败"):
            service.execute_main_chat_model_loop(
                run["run_id"],
                [{"role": "user", "content": "Trigger SSE provider error"}],
            )

        failed = service.get_run(run["run_id"])
        events = service.list_run_events(run["run_id"])["events"]
        persisted_projection = json.dumps({"run": failed, "events": events}, ensure_ascii=False)

        assert failed["status"] == "failed"
        assert "rate_limit_error" in failed["result"]
        assert "quota_exceeded" in failed["result"]
        assert leaked_secret not in persisted_projection
        assert "[redacted]" in persisted_projection
        assert any(event["event_type"] == "model.request.failed" for event in events)
        assert not any(event["event_type"] == "model.output.completed" for event in events)
    finally:
        service.close()

    assert verify_secret_redaction(paths=[tmp_path]) == []


def test_main_chat_model_loop_coalesces_openai_sdk_object_stream_before_persisting(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    chunks = [f"sdk-object-chunk-{index};" for index in range(180)]
    expected = "".join(chunks)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        assert tools is not None

        def stream():
            for chunk in chunks:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=chunk),
                            finish_reason=None,
                        )
                    ]
                )
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=""))])

        return stream()

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-sdk-object-stream-batched-output",
            session_id="session-main-sdk-object-stream-batched-output",
            user_goal="请处理 OpenAI SDK 对象 streaming 输出",
        )
        updated = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "请处理 OpenAI SDK 对象 streaming 输出"}],
        )
        rows = service._conn.execute(
            "SELECT event_type, payload_json FROM run_events WHERE run_id=? ORDER BY sequence",
            (run["run_id"],),
        ).fetchall()
        output_rows = [row for row in rows if row["event_type"] == "model.output.completed"]

        assert updated["result"] == expected
        assert len(output_rows) == 1
        assert json.loads(output_rows[0]["payload_json"])["content"] == expected
        assert not any(str(row["event_type"]).endswith(".delta") for row in rows)
        assert len(rows) < 10
    finally:
        service.close()


def test_main_chat_model_loop_coalesces_streaming_tool_call_deltas(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("streamed tool call content", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert tools is not None

            def stream():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_stream_read",
                                        type="function",
                                        function=SimpleNamespace(name="workspace_", arguments=""),
                                    )
                                ]
                            )
                        )
                    ]
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        function=SimpleNamespace(name="read", arguments='{"path": "READ'),
                                    )
                                ]
                            )
                        )
                    ]
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        function=SimpleNamespace(arguments='ME.md"}'),
                                    )
                                ]
                            )
                        )
                    ]
                )

            return stream()
        assert messages[-1]["role"] == "tool"
        assert "streamed tool call content" in messages[-1]["content"]
        return {"content": "Streaming tool call complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-streaming-tool-call",
            session_id="session-main-streaming-tool-call",
            user_goal="Read README through streaming tool call",
        )
        updated = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README"}],
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        tool_event = next(event for event in events if event["event_type"] == "agent.tool.call")

        assert updated["result"] == "Streaming tool call complete"
        assert tool_event["payload"]["tool"] == "workspace.read"
        assert tool_event["payload"]["input_preview"]["path"] == "README.md"
        assert event_types.count("agent.tool.call") == 1
        assert event_types.count("model.output.completed") == 1
        assert not any(str(event_type).endswith(".delta") for event_type in event_types)
    finally:
        service.close()


def test_main_chat_model_loop_executes_legacy_streaming_function_call(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("legacy function call content", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert tools is not None

            def stream():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                function_call=SimpleNamespace(
                                    name="workspace_",
                                    arguments='{"path": "READ',
                                )
                            )
                        )
                    ]
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                function_call=SimpleNamespace(
                                    name="read",
                                    arguments='ME.md"}',
                                )
                            ),
                            finish_reason="function_call",
                        )
                    ]
                )

            return stream()
        assert messages[-1]["role"] == "tool"
        assert "legacy function call content" in messages[-1]["content"]
        return {"content": "Legacy streaming function call complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-legacy-streaming-function-call",
            session_id="session-main-legacy-streaming-function-call",
            user_goal="Read README through legacy streaming function_call",
        )
        updated = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README"}],
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        tool_event = next(event for event in events if event["event_type"] == "agent.tool.call")

        assert updated["result"] == "Legacy streaming function call complete"
        assert tool_event["payload"]["tool"] == "workspace.read"
        assert tool_event["payload"]["input_preview"]["path"] == "README.md"
        assert event_types.count("agent.tool.call") == 1
        assert event_types.count("model.output.completed") == 1
        assert not any(str(event_type).endswith(".delta") for event_type in event_types)
    finally:
        service.close()


def test_main_chat_model_loop_coalesces_interleaved_streaming_tool_call_deltas(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("readme streamed content", encoding="utf-8")
    (workdir / "NOTES.md").write_text("notes streamed content", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert tools is not None

            def stream():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_stream_readme",
                                        type="function",
                                        function=SimpleNamespace(
                                            name="workspace_read",
                                            arguments='{"path": "READ',
                                        ),
                                    ),
                                    SimpleNamespace(
                                        index=1,
                                        id="call_stream_notes",
                                        type="function",
                                        function=SimpleNamespace(
                                            name="workspace_",
                                            arguments='{"path": "NOT',
                                        ),
                                    ),
                                ]
                            )
                        )
                    ]
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=1,
                                        function=SimpleNamespace(
                                            name="read",
                                            arguments='ES.md"}',
                                        ),
                                    ),
                                    SimpleNamespace(
                                        index=0,
                                        function=SimpleNamespace(arguments='ME.md"}'),
                                    ),
                                ]
                            )
                        )
                    ]
                )

            return stream()
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert [message["tool_call_id"] for message in tool_messages] == [
            "call_stream_readme",
            "call_stream_notes",
        ]
        assert "readme streamed content" in tool_messages[0]["content"]
        assert "notes streamed content" in tool_messages[1]["content"]
        return {"content": "Interleaved streaming tool calls complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-interleaved-streaming-tool-calls",
            session_id="session-main-interleaved-streaming-tool-calls",
            user_goal="Read README and NOTES through streaming tool calls",
        )
        updated = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README and NOTES"}],
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        tool_events = [event for event in events if event["event_type"] == "agent.tool.call"]

        assert updated["result"] == "Interleaved streaming tool calls complete"
        assert [event["payload"]["tool"] for event in tool_events] == [
            "workspace.read",
            "workspace.read",
        ]
        assert [event["payload"]["input_preview"]["path"] for event in tool_events] == [
            "README.md",
            "NOTES.md",
        ]
        assert event_types.count("model.output.completed") == 1
        assert not any(str(event_type).endswith(".delta") for event_type in event_types)
    finally:
        service.close()


def test_main_chat_model_loop_keeps_multi_choice_same_index_streaming_tool_calls_separate(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("readme multi-choice content", encoding="utf-8")
    (workdir / "NOTES.md").write_text("notes multi-choice content", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert tools is not None

            def stream():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            index=0,
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_choice_readme",
                                        type="function",
                                        function=SimpleNamespace(
                                            name="workspace_",
                                            arguments='{"path": "READ',
                                        ),
                                    )
                                ]
                            ),
                        ),
                        SimpleNamespace(
                            index=1,
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_choice_notes",
                                        type="function",
                                        function=SimpleNamespace(
                                            name="workspace_",
                                            arguments='{"path": "NOT',
                                        ),
                                    )
                                ]
                            ),
                        ),
                    ]
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            index=0,
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        function=SimpleNamespace(
                                            name="read",
                                            arguments='ME.md"}',
                                        ),
                                    )
                                ]
                            ),
                        ),
                        SimpleNamespace(
                            index=1,
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        function=SimpleNamespace(
                                            name="read",
                                            arguments='ES.md"}',
                                        ),
                                    )
                                ]
                            ),
                        ),
                    ]
                )

            return stream()
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert [message["tool_call_id"] for message in tool_messages] == [
            "call_choice_readme",
            "call_choice_notes",
        ]
        assert "readme multi-choice content" in tool_messages[0]["content"]
        assert "notes multi-choice content" in tool_messages[1]["content"]
        return {"content": "Multi-choice same-index streaming tool calls complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-multi-choice-same-index-streaming-tool-calls",
            session_id="session-main-multi-choice-same-index-streaming-tool-calls",
            user_goal="Read README and NOTES through multi-choice streaming tool calls",
        )
        updated = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README and NOTES"}],
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        tool_events = [event for event in events if event["event_type"] == "agent.tool.call"]

        assert updated["result"] == "Multi-choice same-index streaming tool calls complete"
        assert [event["payload"]["input_preview"]["path"] for event in tool_events] == [
            "README.md",
            "NOTES.md",
        ]
        assert event_types.count("agent.tool.call") == 2
        assert event_types.count("model.output.completed") == 1
        assert not any(str(event_type).endswith(".delta") for event_type in event_types)
    finally:
        service.close()


def test_main_chat_model_loop_executes_provider_message_tool_calls(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("provider message tool content", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert tools is not None

            def stream():
                yield {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_provider_read",
                                        "type": "function",
                                        "function": {
                                            "name": "workspace_read",
                                            "arguments": '{"path": "README.md"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }

            return stream()

        assistant_tool_messages = [
            message for message in messages if message.get("role") == "assistant" and message.get("tool_calls")
        ]
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert assistant_tool_messages[-1]["tool_calls"][0]["id"] == "call_provider_read"
        assert tool_messages[-1]["tool_call_id"] == "call_provider_read"
        assert "provider message tool content" in tool_messages[-1]["content"]
        return {"role": "assistant", "content": "Provider message tool call complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-provider-message-tool-calls",
            session_id="session-main-provider-message-tool-calls",
            user_goal="Read README through provider message tool call",
        )
        updated = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README"}],
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        tool_event = next(event for event in events if event["event_type"] == "agent.tool.call")

        assert updated["result"] == "Provider message tool call complete"
        assert tool_event["payload"]["tool"] == "workspace.read"
        assert tool_event["payload"]["input_preview"]["path"] == "README.md"
        assert event_types.count("agent.tool.call") == 1
        assert event_types.count("model.output.completed") == 1
        assert not any(str(event_type).endswith(".delta") for event_type in event_types)
    finally:
        service.close()


def test_main_chat_model_loop_executes_openai_sdk_object_message_tool_calls(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("sdk object message tool content", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert tools is not None
            return SimpleNamespace(
                role="assistant",
                content="",
                tool_calls=[
                    SimpleNamespace(
                        id="call_sdk_object_read",
                        type="function",
                        function=SimpleNamespace(
                            name="workspace_read",
                            arguments='{"path": "README.md"}',
                        ),
                    )
                ],
            )

        assistant_tool_messages = [
            message for message in messages if message.get("role") == "assistant" and message.get("tool_calls")
        ]
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert assistant_tool_messages[-1]["tool_calls"][0]["id"] == "call_sdk_object_read"
        assert tool_messages[-1]["tool_call_id"] == "call_sdk_object_read"
        assert "sdk object message tool content" in tool_messages[-1]["content"]
        return {"role": "assistant", "content": "SDK object message tool call complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-sdk-object-message-tool-calls",
            session_id="session-main-sdk-object-message-tool-calls",
            user_goal="Read README through SDK object message tool call",
        )
        updated = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README"}],
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        tool_event = next(event for event in events if event["event_type"] == "agent.tool.call")

        assert updated["result"] == "SDK object message tool call complete"
        assert tool_event["payload"]["tool"] == "workspace.read"
        assert tool_event["payload"]["input_preview"]["path"] == "README.md"
        assert event_types.count("agent.tool.call") == 1
        assert event_types.count("model.output.completed") == 1
        assert not any(str(event_type).endswith(".delta") for event_type in event_types)
    finally:
        service.close()


def test_main_chat_provider_exception_is_redacted_from_run_events_and_storage(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    leaked_secret = "sk-provider-exception123456"
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        raise RuntimeError(f"provider failed api_key={leaked_secret}")

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-provider-leak",
            session_id="session-provider-leak",
            user_goal=f"handle request token={leaked_secret}",
        )

        with pytest.raises(RuntimeError):
            service.execute_main_chat_model_loop(
                run["run_id"],
                [{"role": "user", "content": "trigger provider failure"}],
            )

        failed = service.get_run(run["run_id"])
        events = service.list_run_events(run["run_id"])["events"]
        persisted_projection = json.dumps({"run": failed, "events": events}, ensure_ascii=False)

        assert failed["status"] == "failed"
        assert leaked_secret not in persisted_projection
        assert "[redacted]" in persisted_projection
        assert any(event["event_type"] == "model.request.failed" for event in events)
    finally:
        service.close()

    assert verify_secret_redaction(paths=[tmp_path]) == []


def test_main_chat_model_loop_executes_native_tool_call(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "out.txt").write_text("before\n", encoding="utf-8")
    (workdir / "README.md").write_text("hello main chat tools", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert any((tool.get("function") or {}).get("name") == "workspace_read" for tool in tools or [])
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "README.md"})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "hello main chat tools" in messages[-1]["content"]
        return {"content": "Main chat read complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(task_id="task-main-tools", session_id="session-main-tools", user_goal="Read")
        result = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README"}],
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )

        assert result["status"] == "running"
        assert result["result"] == "Main chat read complete"
        tool_event = next(event for event in result["timeline"] if event["event"] == "agent.tool.call")
        assert tool_event["detail"] == "workspace.read"
        assert tool_event["result"]["ok"] is True
    finally:
        service.close()


def test_main_chat_tool_exception_is_redacted_from_tool_messages_events_and_storage(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []
    leaked_secret = "sk-tool-exception123456"
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "README.md"})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert leaked_secret not in messages[-1]["content"]
        assert "[redacted]" in messages[-1]["content"]
        return {"content": "Recovered from redacted tool failure"}

    def failing_tool_call(self, name, payload, *, approved=False):
        assert name == "workspace.read"
        raise AgentRuntimeError(f"workspace failed token={leaked_secret}")

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    monkeypatch.setattr(ToolBroker, "call", failing_tool_call)
    try:
        run = service.start_main_chat_run(
            task_id="task-tool-exception-leak",
            session_id="session-tool-exception-leak",
            user_goal="Read README and recover",
        )
        result = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README"}],
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )

        events = service.list_run_events(run["run_id"])["events"]
        persisted_projection = json.dumps({"run": result, "events": events}, ensure_ascii=False)
        tool_event = next(event for event in events if event["event_type"] == "agent.tool.call")

        assert result["status"] == "running"
        assert result["result"] == "Recovered from redacted tool failure"
        assert tool_event["payload"]["result"]["ok"] is False
        assert leaked_secret not in persisted_projection
        assert "[redacted]" in persisted_projection
    finally:
        service.close()

    assert verify_secret_redaction(paths=[tmp_path]) == []


def test_main_chat_default_tools_use_trusted_product_workspace(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    product_workspace = tmp_path / "oha-workspace"
    projects = product_workspace / "projects"
    projects.mkdir(parents=True)
    (projects / "README.md").write_text("trusted product workspace", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_workspace_status",
        lambda: {
            "initialized": True,
            "workspace_path": str(product_workspace),
            "dirs": {"projects": str(projects)},
        },
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append({"messages": messages, "tools": tools or []})
        if len(calls) == 1:
            tool_names = {(tool.get("function") or {}).get("name") for tool in tools or []}
            assert {"workspace_list", "workspace_read", "artifact_write"} <= tool_names
            assert "workspace_write_patch" not in tool_names
            assert "terminal_run" not in tool_names
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "README.md"})},
                    }
                ],
            }
        assert "trusted product workspace" in messages[-1]["content"]
        return {"content": "Default workspace read complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(task_id="task-default-workspace", session_id="session-default-workspace", user_goal="Read")
        result = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Read README"}],
        )
        trusted = service.list_trusted_workspaces()["workspaces"]

        assert result["status"] == "running"
        assert result["result"] == "Default workspace read complete"
        assert any(item["path"] == str(projects.resolve()) and item["source"] == "main_chat" for item in trusted)
    finally:
        service.close()


def test_main_chat_model_loop_pauses_and_resumes_approved_tool(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    target = workdir / "out.txt"
    target.write_text("before\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_write",
                        "type": "function",
                        "function": {
                            "name": "workspace_write_patch",
                            "arguments": json.dumps(
                                {
                                    "path": "out.txt",
                                    "patch": "--- out.txt\n+++ out.txt\n@@ -1 +1 @@\n-before\n+approved\n",
                                }
                            ),
                        },
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "out.txt" in messages[-1]["content"]
        return {"content": "Main chat write complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        resume_contexts: list[ToolApprovalResumeContext] = []
        original_resume = service.approval_resume.execute_approved_tool

        def spy_resume(context: ToolApprovalResumeContext) -> None:
            resume_contexts.append(context)
            original_resume(context)

        monkeypatch.setattr(service.approval_resume, "execute_approved_tool", spy_resume)
        run = service.start_main_chat_run(task_id="task-main-approval", session_id="session-main-approval", user_goal="Write")
        waiting = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Write out.txt"}],
            tool_policy={"allowed_tools": ["workspace.write_patch"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."], "writable_scopes": ["."]},
        )

        assert waiting["status"] == "approval_required"
        assert waiting["pending_approval"]["tool"] == "workspace.write_patch"
        assert target.read_text(encoding="utf-8") == "before\n"

        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "running"
        assert resumed["pending_approval"] == {}
        assert resumed["result"] == "Main chat write complete"
        assert target.read_text(encoding="utf-8") == "approved\n"
        assert len(resume_contexts) == 1
        assert resume_contexts[0].run_id == run["run_id"]
        assert resume_contexts[0].tool_name == "workspace.write_patch"
        assert resume_contexts[0].input_preview["path"] == "out.txt"
        approval_row = service._conn.execute(
            "SELECT status FROM run_approvals WHERE run_id=?",
            (run["run_id"],),
        ).fetchone()
        assert approval_row["status"] == "approved"
    finally:
        service.close()


def test_main_chat_approval_timeout_records_replayable_fact_and_is_idempotent(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_write",
                    "type": "function",
                    "function": {
                        "name": "workspace_write_patch",
                        "arguments": json.dumps(
                            {
                                "path": "out.txt",
                                "patch": "--- out.txt\n+++ out.txt\n@@ -1 +1 @@\n-before\n+timed out\n",
                            }
                        ),
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-approval-timeout",
            session_id="session-main-approval-timeout",
            user_goal="Write",
        )
        waiting = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Write out.txt"}],
            tool_policy={"allowed_tools": ["workspace.write_patch"]},
            workspace_policy={
                "default_workdir": str(workdir),
                "readable_scopes": ["."],
                "writable_scopes": ["."],
            },
        )

        assert waiting["status"] == "approval_required"

        timed_out = service.timeout_run_approval(run["run_id"], reason="approval_wait_timeout")
        events_after_timeout = service.list_run_events(run["run_id"])["events"]
        timeout_events = [event for event in events_after_timeout if event["event_type"] == "approval.timeout"]

        assert timed_out["status"] == "cancelled"
        assert timed_out["pending_approval"] == {}
        assert "审批已超时" in timed_out["result"]
        assert any(event["event"] == "agent.tool.approval_timeout" for event in timed_out["timeline"])
        assert len(timeout_events) == 1
        assert timeout_events[0]["payload"]["tool"] == "workspace.write_patch"
        assert timeout_events[0]["payload"]["reason"] == "approval_wait_timeout"
        assert timeout_events[0]["payload"]["status"] == "cancelled"

        approval_row = service._conn.execute(
            "SELECT status FROM run_approvals WHERE run_id=?",
            (run["run_id"],),
        ).fetchone()
        assert approval_row["status"] == "cancelled"

        repeated = service.timeout_run_approval(run["run_id"], reason="approval_wait_timeout")
        events_after_repeat = service.list_run_events(run["run_id"])["events"]

        assert repeated["status"] == "cancelled"
        assert len([event for event in events_after_repeat if event["event_type"] == "approval.timeout"]) == 1
    finally:
        service.close()


def test_main_chat_repeated_approval_does_not_execute_tool_twice(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    workdir = tmp_path / "repo"
    (workdir / "src").mkdir(parents=True)
    target = workdir / "src" / "app.txt"
    target.write_text("before\n", encoding="utf-8")
    model_calls = 0
    resume_model_started = threading.Event()
    release_resume_model = threading.Event()

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_patch",
                        "type": "function",
                        "function": {
                            "name": "workspace_write_patch",
                            "arguments": json.dumps(
                                {
                                    "path": "src/app.txt",
                                    "patch": "--- src/app.txt\n+++ src/app.txt\n@@ -1 +1 @@\n-before\n+after\n",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
        resume_model_started.set()
        assert release_resume_model.wait(timeout=3)
        return {"role": "assistant", "content": "Patched once"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-approve-idempotent",
            session_id="session-main-approve-idempotent",
            user_goal="Patch once",
        )
        waiting = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Patch once"}],
            tool_policy={"allowed_tools": ["workspace.write_patch"]},
            workspace_policy={
                "default_workdir": str(workdir),
                "readable_scopes": ["."],
                "writable_scopes": ["."],
            },
        )

        assert waiting["status"] == "approval_required"

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.approve_run_approval, run["run_id"])
            assert resume_model_started.wait(timeout=3)
            second = pool.submit(service.approve_run_approval, run["run_id"]).result(timeout=3)
            assert second["run_id"] == run["run_id"]
            release_resume_model.set()
            first_result = first.result(timeout=3)

        repeated_after = service.approve_run_approval(run["run_id"])

        assert first_result["status"] == "running"
        assert repeated_after["run_id"] == run["run_id"]
        assert model_calls == 2
        assert target.read_text(encoding="utf-8") == "after\n"
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        assert event_types.count("agent.tool.approval_approved") == 1
        tool_calls = [
            event for event in events
            if event["event_type"] == "agent.tool.call"
            and event["payload"].get("tool") == "workspace.write_patch"
            and event["payload"].get("approved") is True
        ]
        assert len(tool_calls) == 1
    finally:
        release_resume_model.set()
        service.close()


def test_main_chat_durable_approval_claim_blocks_duplicate_execution(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    claiming_service = None
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    workdir = tmp_path / "repo"
    workdir.mkdir()
    target = workdir / "out.txt"
    target.write_text("before\n", encoding="utf-8")
    model_calls = 0

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_patch",
                        "type": "function",
                        "function": {
                            "name": "workspace_write_patch",
                            "arguments": json.dumps(
                                {
                                    "path": "out.txt",
                                    "patch": "--- out.txt\n+++ out.txt\n@@ -1 +1 @@\n-before\n+approved once\n",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
        raise AssertionError("durably claimed approval must not resume model again")

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.start_main_chat_run(
            task_id="task-main-approve-durable-claim",
            session_id="session-main-approve-durable-claim",
            user_goal="Patch once",
        )
        waiting = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Patch once"}],
            tool_policy={"allowed_tools": ["workspace.write_patch"]},
            workspace_policy={
                "default_workdir": str(workdir),
                "readable_scopes": ["."],
                "writable_scopes": ["."],
            },
        )

        assert waiting["status"] == "approval_required"
        pending = service._pending_approval_private(run["run_id"])
        claiming_service = make_service(tmp_path)
        assert claiming_service.run_approvals.claim_pending_approval(run["run_id"], pending) is True
        assert claiming_service.run_approvals.claim_pending_approval(run["run_id"], pending) is False

        duplicate = service.approve_run_approval(run["run_id"])

        assert duplicate["status"] == "approval_required"
        assert model_calls == 1
        assert target.read_text(encoding="utf-8") == "before\n"
        events = service.list_run_events(run["run_id"])["events"]
        assert "agent.tool.approval_approved" not in [event["event_type"] for event in events]
        approved_tool_calls = [
            event for event in events
            if event["event_type"] == "agent.tool.call"
            and event["payload"].get("tool") == "workspace.write_patch"
            and event["payload"].get("approved") is True
        ]
        assert approved_tool_calls == []
        approval_row = service._conn.execute(
            "SELECT status, resolved_at FROM run_approvals WHERE run_id=?",
            (run["run_id"],),
        ).fetchone()
        assert approval_row["status"] == "approved"
        assert approval_row["resolved_at"]
    finally:
        if claiming_service is not None:
            claiming_service.close()
        service.close()


def test_agent_explicit_workspace_is_recorded_as_trusted(tmp_path):
    service = make_service(tmp_path)
    workdir = tmp_path / "external-workspace"
    workdir.mkdir()
    try:
        agent = service.create_agent(
            {
                "name": "Trusted Writer",
                "workspace_policy": {
                    "default_workdir": str(workdir),
                    "readable_scopes": ["."],
                    "writable_scopes": [],
                },
            }
        )
        trusted = service.list_trusted_workspaces()["workspaces"]

        assert agent["workspace_policy"]["default_workdir"] == str(workdir)
        assert any(item["path"] == str(workdir.resolve()) and item["source"] == f"agent:{agent['agent_id']}" for item in trusted)
    finally:
        service.close()


def test_run_events_hide_internal_and_secret_by_default(tmp_path):
    service = make_service(tmp_path)
    try:
        run = service._insert_run(kind="main_chat_run", runnable_id="builtin:yachiyo-main", user_goal="test")
        service.append_run_event(run["run_id"], "user.visible", {"value": "ok"})
        service.append_run_event(run["run_id"], "user.token", {"token": "plain-token-value", "safe": "ok"})
        service.append_run_event(run["run_id"], "internal.fact", {"value": "hidden"}, visibility="internal")
        service.append_run_event(run["run_id"], "secret.fact", {"value": "sk-secret-value"}, sensitivity="secret")

        public = service.list_run_events(run["run_id"])["events"]
        debug = service.list_run_events(run["run_id"], include_internal=True)["events"]

        assert [event["event_type"] for event in public] == ["user.visible", "user.token"]
        assert [event["event_type"] for event in debug] == ["user.visible", "user.token", "internal.fact", "secret.fact"]
        assert public[1]["payload"]["token"] == "[redacted]"
        assert public[1]["payload"]["safe"] == "ok"
        assert debug[-1]["payload"]["value"] == "[redacted]"
    finally:
        service.close()


def test_run_event_repository_allocates_sequences_under_concurrent_writers(tmp_path):
    service = make_service(tmp_path)
    try:
        run = service._insert_run(kind="main_chat_run", runnable_id="builtin:yachiyo-main", user_goal="test")

        def append_event(index: int):
            return service.append_run_event(run["run_id"], "concurrent.fact", {"index": index})

        with ThreadPoolExecutor(max_workers=8) as pool:
            written = list(pool.map(append_event, range(40)))

        events = service.list_run_events(run["run_id"], limit=100)["events"]

        assert len(written) == 40
        assert [event["sequence"] for event in events] == list(range(1, 41))
        assert sorted(event["payload"]["index"] for event in events) == list(range(40))
    finally:
        service.close()


@pytest.mark.asyncio
async def test_run_events_route_paginates_user_visible_events(tmp_path, monkeypatch):
    from apps.bridge.routes import runs as run_routes

    service = make_service(tmp_path)
    monkeypatch.setattr(run_routes, "get_native_run_engine", lambda: service)
    try:
        run = service._insert_run(kind="main_chat_run", runnable_id="builtin:yachiyo-main", user_goal="test")
        service.append_run_event(run["run_id"], "first", {"value": 1})
        service.append_run_event(run["run_id"], "internal", {"value": 2}, visibility="internal")
        service.append_run_event(run["run_id"], "secret", {"value": "sk-secret-value"}, sensitivity="secret")
        service.append_run_event(run["run_id"], "third", {"value": 3})

        clamped = await run_routes.list_run_events(run["run_id"], after_sequence=-10, limit=5000)
        response = await run_routes.list_run_events(run["run_id"], after_sequence=1, limit=1)

        assert clamped["after_sequence"] == 0
        assert clamped["limit"] == 1000
        assert [event["event_type"] for event in clamped["events"]] == ["first", "third"]
        assert "sk-secret-value" not in json.dumps(clamped, ensure_ascii=False)
        assert response["limit"] == 1
        assert [event["event_type"] for event in response["events"]] == ["third"]
        assert response["events"][0]["sequence"] == 4
    finally:
        service.close()


@pytest.mark.asyncio
async def test_run_events_route_returns_404_for_missing_run(tmp_path, monkeypatch):
    from apps.bridge.routes import runs as run_routes

    service = make_service(tmp_path)
    monkeypatch.setattr(run_routes, "get_native_run_engine", lambda: service)
    try:
        with pytest.raises(run_routes.HTTPException) as exc_info:
            await run_routes.list_run_events("missing-run")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Run 不存在"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_post_runs_route_maps_idempotency_key_to_runnable_run(monkeypatch):
    from apps.bridge.routes import runs as run_routes

    recorded: dict[str, str] = {}

    class FakeRunEngine:
        def create_run_for_runnable(self, **kwargs):
            recorded.update({key: str(value) for key, value in kwargs.items()})
            return {
                "ok": True,
                "run_id": "run_post_runs",
                "client_request_id": kwargs.get("client_run_id") or kwargs.get("client_request_id") or "",
            }

    monkeypatch.setattr(run_routes, "get_native_run_engine", lambda: FakeRunEngine())

    response = await run_routes.create_run(
        run_routes.RunCreateRequest(runnable_id="agent_coding", user_goal="Run from generic API"),
        SimpleNamespace(headers={"idempotency-key": "post-runs-client-1"}),
    )

    assert response["run_id"] == "run_post_runs"
    assert response["client_request_id"] == "post-runs-client-1"
    assert recorded == {
        "runnable_id": "agent_coding",
        "name": "",
        "user_goal": "Run from generic API",
        "run_group_id": "",
        "upstream": "",
        "client_run_id": "post-runs-client-1",
        "client_request_id": "",
    }


def test_runtime_shutdown_cancels_active_runs_rejects_new_runs_and_records_fact(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    cancelled_process_groups = []
    monkeypatch.setattr("apps.shell.agent_runtime.cancel_terminal_process_groups", lambda: cancelled_process_groups.append(True))
    try:
        run = service._insert_run(kind="main_chat_run", runnable_id="builtin:yachiyo-main", user_goal="test")

        service.shutdown(close_db=False)

        assert cancelled_process_groups == [True]
        assert service.get_run(run["run_id"])["status"] == "cancelled"
        events = service.list_run_events(run["run_id"])["events"]
        assert events[-1]["event_type"] == "run.cancelled"
        with pytest.raises(AgentRuntimeError):
            service.start_main_chat_run(task_id="t2", session_id="s2", user_goal="blocked")
    finally:
        service.close()


def test_concurrent_cancel_run_is_idempotent(tmp_path):
    service = make_service(tmp_path)
    try:
        run = service._insert_run(kind="main_chat_run", runnable_id="builtin:yachiyo-main", user_goal="cancel once")

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _index: service.cancel_run(run["run_id"]), range(20)))

        stored = service.get_run(run["run_id"])
        events = service.list_run_events(run["run_id"])["events"]
        cancel_facts = [event for event in events if event["event_type"] == "run.cancelled"]
        cancel_timeline = [event for event in stored["timeline"] if event["event"] == "run.cancelled"]

        assert {result["run_id"] for result in results} == {run["run_id"]}
        assert {result["status"] for result in results} == {"cancelled"}
        assert stored["status"] == "cancelled"
        assert len(cancel_facts) == 1
        assert len(cancel_timeline) == 1
    finally:
        service.close()


def test_runtime_shutdown_close_db_closes_runtime_resources(tmp_path):
    service = make_service(tmp_path)

    service.shutdown(close_db=True)

    with pytest.raises(sqlite3.ProgrammingError):
        service._conn.execute("SELECT 1")


def test_agent_run_client_run_id_is_idempotent(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    model_calls = 0

    def fake_chat(*_args, **_kwargs):
        nonlocal model_calls
        model_calls += 1
        return {"content": "Done"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Idempotent Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )

        first = service.create_agent_run(
            {"agent_id": agent["agent_id"], "user_goal": "Finish", "client_run_id": "run-client-1"}
        )
        second = service.create_agent_run(
            {"agent_id": agent["agent_id"], "user_goal": "Finish", "client_run_id": "run-client-1"}
        )

        assert second["idempotent"] is True
        assert second["run_id"] == first["run_id"]
        assert model_calls == 1
        rows = service._conn.execute("SELECT run_id FROM runs WHERE client_request_id='run-client-1'").fetchall()
        assert len(rows) == 1
    finally:
        service.close()


def test_create_run_for_runnable_propagates_client_run_id(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    model_calls = 0

    def fake_chat(*_args, **_kwargs):
        nonlocal model_calls
        model_calls += 1
        return {"content": "Runnable done"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Runnable Idempotent Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )

        first = service.create_run_for_runnable(
            runnable_id=agent["agent_id"],
            user_goal="Finish through runnable",
            client_run_id="runnable-client-1",
        )
        second = service.create_run_for_runnable(
            runnable_id=agent["agent_id"],
            user_goal="Finish through runnable",
            client_run_id="runnable-client-1",
        )

        assert first["runnable"]["id"] == agent["agent_id"]
        assert second["idempotent"] is True
        assert second["run_id"] == first["run_id"]
        assert model_calls == 1
        rows = service._conn.execute("SELECT run_id FROM runs WHERE client_request_id='runnable-client-1'").fetchall()
        assert len(rows) == 1
    finally:
        service.close()


def test_run_repository_redacts_and_syncs_approval_projection(tmp_path):
    service = make_service(tmp_path)
    try:
        run = service.runs.insert(
            kind="main_chat_run",
            runnable_id="builtin:yachiyo-main",
            user_goal="Use sk-secret-value",
            client_request_id="repo-client-1",
        )
        pending = {
            "approval_id": "approval_repo_1",
            "tool": "terminal.run",
            "input_preview": {"command": "printf ok"},
            "requested_at": "2026-06-09T00:00:00+00:00",
        }

        updated = service.runs.update(
            run["run_id"],
            result="Done sk-secret-value",
            timeline=[{"event": "test", "detail": "sk-secret-value"}],
            pending_approval=pending,
        )
        by_client_id = service.runs.by_client_request_id("repo-client-1")
        approval = service._conn.execute(
            "SELECT status, tool, input_preview_json FROM run_approvals WHERE approval_id='approval_repo_1'"
        ).fetchone()

        assert run["user_goal"] == "Use [redacted]"
        assert updated["result"] == "Done [redacted]"
        assert updated["timeline"][0]["detail"] == "[redacted]"
        assert by_client_id is not None
        assert by_client_id["idempotent"] is True
        assert by_client_id["run_id"] == run["run_id"]
        assert approval is not None
        assert approval["status"] == "pending"
        assert approval["tool"] == "terminal.run"
        assert json.loads(approval["input_preview_json"])["command"] == "printf ok"
    finally:
        service.close()


def test_run_artifact_repository_redacts_projection_and_reads_files(tmp_path):
    service = make_service(tmp_path)
    try:
        run = service.runs.insert(
            kind="agent_run",
            runnable_id="agent_artifact_test",
            user_goal="Write artifact",
        )
        artifact_dir = service.agent_artifacts_dir / run["run_id"]
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "notes.md").write_text("artifact sk-secret-value", encoding="utf-8")

        service.runs.update(
            run["run_id"],
            artifacts=[
                {
                    "kind": "tool_artifact",
                    "path": "notes.md",
                    "source_run_id": "source_run_1",
                    "token": "sk-secret-value",
                }
            ],
        )
        row = service._conn.execute(
            "SELECT kind, path, source_run_id, payload_json FROM run_artifacts WHERE run_id=?",
            (run["run_id"],),
        ).fetchone()
        artifact = service.read_run_artifact(run["run_id"], "notes.md")

        assert row is not None
        assert row["kind"] == "tool_artifact"
        assert row["path"] == "notes.md"
        assert row["source_run_id"] == "source_run_1"
        assert json.loads(row["payload_json"])["token"] == "[redacted]"
        assert artifact["content"] == "artifact [redacted]"
    finally:
        service.close()


def test_run_group_repository_manages_membership_and_cleanup(tmp_path):
    service = make_service(tmp_path)
    try:
        group = service.run_groups.insert(title="Grouped Runs", source="agent")
        first = service.runs.insert(
            kind="agent_run",
            runnable_id="agent_group_first",
            user_goal="First",
            run_group_id=group["run_group_id"],
        )
        second = service.runs.insert(
            kind="agent_run",
            runnable_id="agent_group_second",
            user_goal="Second",
            run_group_id=group["run_group_id"],
        )

        service.run_groups.append_run(group["run_group_id"], first["run_id"])
        service.run_groups.update(group["run_group_id"], status="completed", summary="done")
        grouped = service.get_run_group(group["run_group_id"])
        listed = service.list_run_groups()["run_groups"]
        group_runs = service._runs_in_group(group["run_group_id"])

        assert grouped["source"] == "agent"
        assert grouped["status"] == "completed"
        assert grouped["summary"] == "done"
        assert grouped["child_run_ids"] == [first["run_id"], second["run_id"]]
        assert any(item["run_group_id"] == group["run_group_id"] for item in listed)
        assert [run["run_id"] for run in group_runs] == [first["run_id"], second["run_id"]]

        service.runs.update(first["run_id"], status="completed")
        service.runs.update(second["run_id"], status="completed")
        service.delete_run(first["run_id"])
        assert service.get_run_group(group["run_group_id"])["child_run_ids"] == [second["run_id"]]
        service.delete_run(second["run_id"])
        with pytest.raises(KeyError):
            service.get_run_group(group["run_group_id"])
    finally:
        service.close()


def test_agent_run_route_maps_idempotency_key_header():
    from apps.bridge.routes import agents as agent_routes

    payload = agent_routes._payload_with_idempotency(
        agent_routes.AgentRunRequest(agent_id="a1", user_goal="Run"),
        SimpleNamespace(headers={"idempotency-key": "header-run-1"}),
    )

    assert payload["client_run_id"] == "header-run-1"


def test_terminal_run_defaults_to_argv_and_requires_explicit_shell(tmp_path):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    marker = workdir / "shell-marker"
    broker = ToolBroker(
        {"default_workdir": str(workdir), "readable_scopes": ["."], "writable_scopes": ["."]},
        tmp_path / "artifacts",
    )

    argv_result = broker.terminal_run(f"printf safe; touch {marker}", approved=True)
    assert marker.exists() is False
    shell_result = broker.terminal_run(f"printf safe; touch {marker}", approved=True, shell=True)

    assert argv_result["shell"] is False
    assert marker.exists() is True
    assert shell_result["shell"] is True


def test_terminal_run_shell_mode_requires_approval_and_shows_full_command(tmp_path):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    marker = workdir / "shell-marker"
    command = f"printf safe; touch {marker}"
    broker = ToolBroker(
        {"default_workdir": str(workdir), "readable_scopes": ["."], "writable_scopes": ["."]},
        tmp_path / "artifacts",
    )

    result = broker.terminal_run(command, shell=True)

    assert result["approval_required"] is True
    assert result["tool"] == "terminal.run"
    assert result["input_preview"] == {"command": command, "shell": True}
    assert marker.exists() is False


def test_runtime_restores_row_factory_before_listing_runnables(tmp_path):
    service = make_service(tmp_path, seed_templates=True)
    try:
        service._conn.row_factory = None
        result = service.list_runnables()
        assert result["ok"] is True
        coding = next(item for item in result["runnables"] if item["id"] == "agent_coding")
        assert coding["output_contract"]
        assert "workspace.read" in coding["tool_policy"]["allowed_tools"]
        assert coding["tool_policy"]["approval_required"]["terminal.run"] is True
    finally:
        service.close()


def test_runtime_restores_row_factory_before_listing_agents(tmp_path):
    service = make_service(tmp_path, seed_templates=True)
    try:
        service._conn.row_factory = None
        service._ensure_row_factory = lambda: None  # type: ignore[method-assign]
        result = service.list_agents()
        assert result["ok"] is True
        assert any(agent["agent_id"] == "agent_coding" for agent in result["agents"])
    finally:
        service.close()


def test_runtime_agent_studio_reads_are_safe_under_parallel_refresh(tmp_path):
    service = make_service(tmp_path, seed_templates=True)
    try:
        def read_agent_studio_state(_index: int):
            return (
                service.list_agents()["agents"],
                service.list_skill_folders()["uncategorized"],
                service.list_runnables()["runnables"],
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(read_agent_studio_state, range(40)))

        assert results
        for agents, uncategorized, runnables in results:
            assert any(agent["agent_id"] == "agent_coding" for agent in agents)
            assert "skill_count" in uncategorized
            assert any(item["id"] == "agent_coding" for item in runnables)
    finally:
        service.close()


def test_builtin_yachiyo_main_is_virtual_system_agent_not_delegation_target(tmp_path):
    service = make_service(tmp_path, seed_templates=True)
    try:
        agents = service.list_agents()["agents"]
        main = next(agent for agent in agents if agent["agent_id"] == "builtin:yachiyo-main")

        assert main["name"] == "Yachiyo"
        assert main["system"] is True
        assert main["virtual"] is True
        assert main["deletable"] is False
        assert main["editable"] is False
        assert main["execution_backend"] == "native_profile"
        assert "workspace.read" in main["tool_policy"]["allowed_tools"]

        row = service._conn.execute(
            "SELECT 1 FROM agents WHERE agent_id=?",
            ("builtin:yachiyo-main",),
        ).fetchone()
        assert row is None
        assert service.get_agent("builtin:yachiyo-main")["system"] is True
        assert service.resolve_runnable(runnable_id="builtin:yachiyo-main")["id"] == "builtin:yachiyo-main"
        assert service.resolve_runnable(name="Yachiyo")["id"] == "builtin:yachiyo-main"
        assert any(item["id"] == "builtin:yachiyo-main" for item in service.list_runnables()["runnables"])
        assert all(
            item["id"] != "builtin:yachiyo-main"
            for item in service.list_delegation_targets()["agents"]
        )

        with pytest.raises(AgentRuntimeError, match="系统 Agent 不能删除"):
            service.delete_agent("builtin:yachiyo-main")
        with pytest.raises(AgentRuntimeError, match="系统 Agent 不能创建或覆盖"):
            service.create_agent({"agent_id": "builtin:yachiyo-main", "name": "Main"})
        with pytest.raises(AgentRuntimeError, match="系统 Agent 不能修改"):
            service.update_agent("builtin:yachiyo-main", {"description": "mutate"})
    finally:
        service.close()


def test_seed_templates_backfill_default_workflows_when_agents_exist(tmp_path):
    service = make_service(tmp_path)
    try:
        service.create_agent({"name": "Existing Agent"})
    finally:
        service.close()

    service = make_service(tmp_path, seed_templates=True)
    try:
        workflows = service.list_workflows()["workflows"]
        workflow_ids = {workflow["workflow_id"] for workflow in workflows}

        assert "workflow_web_idea_full" in workflow_ids
        assert "workflow_phase4_agent_line_smoke" in workflow_ids
        assert any(agent["agent_id"] == "agent_coding" for agent in service.list_agents()["agents"])
    finally:
        service.close()


def test_deleted_seed_templates_do_not_return_after_restart(tmp_path):
    service = make_service(tmp_path, seed_templates=True)
    try:
        service.delete_agent("agent_coding")
        service.delete_workflow("workflow_web_idea_full")
    finally:
        service.close()

    service = make_service(tmp_path, seed_templates=True)
    try:
        agent_ids = {agent["agent_id"] for agent in service.list_agents()["agents"]}
        workflow_ids = {workflow["workflow_id"] for workflow in service.list_workflows()["workflows"]}

        assert "agent_coding" not in agent_ids
        assert "workflow_web_idea_full" not in workflow_ids
    finally:
        service.close()


def test_phase4_seeded_workflow_executes_default_agent_line(tmp_path, monkeypatch):
    service = make_service(tmp_path, seed_templates=True)
    calls = []
    expected_step_tasks = [
        "拆解全局目标，明确后续 Agent 的交付边界、依赖关系、风险和验收口径。",
        "基于全局目标整理事实、约束、参考信息和不确定点，为设计与实现提供依据。",
        "基于研究结果提出信息架构、交互结构、视觉方向和需要交付的设计要点。",
        "根据上游设计与约束给出实现方案、必要代码或变更计划，并说明验证方式。",
        "审查上游实现或方案，列出问题优先级、风险、缺失测试和可验收结论。",
        "把整条流程的目标、关键决策、产物、风险和后续待办整理成最终汇报。",
    ]

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": f"Step {len(calls)} complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: FakeDefaultProfileService())
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.create_workflow_run(
            {
                "workflow_id": "workflow_phase4_agent_line_smoke",
                "user_goal": "跑一次 Phase 4 全线流通性测试",
            }
        )

        assert run["status"] == "completed"
        assert run["result"] == "Step 6 complete"
        assert len(calls) == 6
        for index, task in enumerate(expected_step_tasks):
            assert f"# User Goal\n{task}\n\nWorkflow Goal:\n跑一次 Phase 4 全线流通性测试" in calls[index][-1]["content"]
        assert [event["event"] for event in run["timeline"]].count("workflow.node.agent") == 6
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert [item.get("task") for item in started_event["workflow_path"] if item.get("kind") == "agent"] == expected_step_tasks
        assert [
            item.get("artifact_path")
            for item in started_event["workflow_path"]
            if item.get("kind") == "artifact"
        ] == ["reports/phase-4-flow-summary.md"]
        assert any(artifact.get("kind") == "workflow_artifact" for artifact in run["artifacts"])
        group = service.get_run_group(run["run_group_id"])
        assert group["status"] == "completed"
        assert len(group["child_run_ids"]) == 7
    finally:
        service.close()


def test_agent_crud_and_api_key_redaction(tmp_path):
    service = make_service(tmp_path)
    try:
        agent = service.create_agent(
            {
                "name": "Private Model",
                "nickname": "Private",
                "persona_prompt": "Keep a concise operator tone.",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-test-secret",
                },
            }
        )

        assert agent["model_config"]["api_key_configured"] is True
        assert "api_key" not in agent["model_config"]
        assert agent["nickname"] == "Private"
        assert agent["persona_prompt"] == "Keep a concise operator tone."

        updated = service.update_agent(
            agent["agent_id"],
            {
                "description": "updated",
                "nickname": "Private Ops",
                "model_config": {"base_url": "https://gateway.example.test/v1", "api_key": ""},
            },
        )
        assert updated["description"] == "updated"
        assert updated["nickname"] == "Private Ops"
        assert updated["model_config"]["base_url"] == "https://gateway.example.test/v1"
        assert updated["model_config"]["api_key_configured"] is True

        conn = sqlite3.connect(tmp_path / "agent-runtime.db")
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT model_api_key, model_credential_ref FROM agents WHERE agent_id=?",
                (agent["agent_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["model_api_key"] == ""
        assert row["model_credential_ref"] == f"agent:{agent['agent_id']}:model_api_key"
        assert verify_secret_redaction(paths=[tmp_path]) == []
    finally:
        service.close()


def test_legacy_agent_model_api_key_migration_vacuums_plaintext_secret(tmp_path):
    db_path = tmp_path / "agent-runtime.db"
    legacy_secret = "sk-legacy-agent-secret123456"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        f"""
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            nickname TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            avatar_url TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'custom',
            instructions TEXT NOT NULL DEFAULT '',
            persona_prompt TEXT NOT NULL DEFAULT '',
            model_mode TEXT NOT NULL DEFAULT 'custom_api',
            execution_backend TEXT NOT NULL DEFAULT 'native_profile',
            model_profile_id TEXT NOT NULL DEFAULT '',
            vision_model_profile_id TEXT NOT NULL DEFAULT '',
            model_provider TEXT NOT NULL DEFAULT 'openai_compatible',
            model_base_url TEXT NOT NULL DEFAULT 'https://api.example.test/v1',
            model_name TEXT NOT NULL DEFAULT 'demo-model',
            model_api_key TEXT NOT NULL DEFAULT '',
            tool_policy_json TEXT NOT NULL DEFAULT '{{}}',
            workspace_policy_json TEXT NOT NULL DEFAULT '{{}}',
            skill_ids_json TEXT NOT NULL DEFAULT '[]',
            output_contract TEXT NOT NULL DEFAULT 'chat',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO agents (
            agent_id, name, model_api_key, created_at, updated_at
        ) VALUES (
            'agent_legacy_secret', 'Legacy Secret Agent', '{legacy_secret}', 'now', 'now'
        );
        """
    )
    conn.close()
    credential_store = MemoryCredentialStore()

    service = AgentRuntimeService(
        db_path=db_path,
        workspace_dir=tmp_path / "runtime",
        credential_store=credential_store,
        seed_templates=False,
    )
    try:
        agent = service.get_agent("agent_legacy_secret")
        assert agent["model_config"]["api_key_configured"] is True
        assert credential_store.get("agent:agent_legacy_secret:model_api_key") == legacy_secret

        row = service._conn.execute(
            "SELECT model_api_key, model_credential_ref FROM agents WHERE agent_id=?",
            ("agent_legacy_secret",),
        ).fetchone()
        assert row["model_api_key"] == ""
        assert row["model_credential_ref"] == "agent:agent_legacy_secret:model_api_key"
        assert verify_secret_redaction(paths=[tmp_path]) == []
    finally:
        service.close()


def test_agents_receive_isolated_default_workdirs(tmp_path):
    service = make_service(tmp_path)
    try:
        coding = service.create_agent({"name": "Default Writer", "category": "coding"})
        reader = service.create_agent({"name": "Default Reader"})

        coding_workdir = Path(coding["workspace_policy"]["default_workdir"])
        reader_workdir = Path(reader["workspace_policy"]["default_workdir"])
        assert coding_workdir == service.agent_workspaces_dir / coding["agent_id"]
        assert reader_workdir == service.agent_workspaces_dir / reader["agent_id"]
        assert coding_workdir.is_dir()
        assert reader_workdir.is_dir()
        assert coding["workspace_policy"]["writable_scopes"] == ["."]
        assert reader["workspace_policy"]["writable_scopes"] == []
    finally:
        service.close()


def test_runtime_migrates_blank_agent_workdirs(tmp_path):
    service = make_service(tmp_path)
    try:
        agent = service.create_agent({"name": "Legacy Writer", "category": "coding"})
        service._conn.execute(
            "UPDATE agents SET workspace_policy_json=? WHERE agent_id=?",
            (json.dumps({"default_workdir": "", "readable_scopes": ["."], "writable_scopes": []}), agent["agent_id"]),
        )
        service._conn.commit()
    finally:
        service.close()

    service = make_service(tmp_path)
    try:
        migrated = service.get_agent(agent["agent_id"])
        assert Path(migrated["workspace_policy"]["default_workdir"]) == service.agent_workspaces_dir / agent["agent_id"]
        assert migrated["workspace_policy"]["writable_scopes"] == ["."]
    finally:
        service.close()


def test_explicit_agent_workdir_preserves_empty_writable_scopes(tmp_path):
    service = make_service(tmp_path)
    workdir = tmp_path / "custom-workdir"
    try:
        agent = service.create_agent(
            {
                "name": "Explicit Writer",
                "category": "coding",
                "workspace_policy": {
                    "default_workdir": str(workdir),
                    "readable_scopes": ["."],
                    "writable_scopes": [],
                },
            }
        )

        assert agent["workspace_policy"]["default_workdir"] == str(workdir)
        assert agent["workspace_policy"]["writable_scopes"] == []
        assert not workdir.exists()
    finally:
        service.close()


def test_agent_and_workflow_names_are_globally_unique(tmp_path):
    service = make_service(tmp_path)
    try:
        service.create_agent({"name": "Shared Name"})
        with pytest.raises(AgentRuntimeError):
            service.create_workflow(
                {
                    "name": "shared name",
                    "nodes": [{"id": "start", "type": "start", "data": {"label": "Start"}}],
                    "edges": [],
                }
            )
    finally:
        service.close()


def test_import_skill_directory_and_mount_to_agent(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    source = tmp_path / "demo-skill"
    (source / "assets").mkdir(parents=True)
    (source / "SKILL.md").write_text("# Demo Skill\n\nUseful instruction.", encoding="utf-8")
    (source / "assets" / "sample.txt").write_text("asset", encoding="utf-8")
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Demo Skill used"})
    try:
        skill = service.import_skill(str(source))
        agent = service.create_agent(
            {
                "name": "Skill Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        mounted = service.attach_skill(agent["agent_id"], skill["skill_id"])

        assert skill["name"] == "Demo Skill"
        assert skill["source_path"] == "local:demo-skill"
        assert skill["local_path"].endswith(skill["skill_id"])
        assert skill["enabled"] is True
        assert skill["asset_paths"] == ["assets/sample.txt"]
        assert mounted["skill_ids"] == [skill["skill_id"]]
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Use the skill"})
        assert run["result"] == "Demo Skill used"
        artifact = service.read_run_artifact(run["run_id"], "agent-context.md")
        assert artifact["ok"] is True
        assert "Useful instruction" in artifact["content"]
        assert run["run_group_id"]
        group = service.get_run_group(run["run_group_id"])
        assert group["source"] == "agent"
        assert group["child_run_ids"] == [run["run_id"]]
        disabled = service.update_skill(skill["skill_id"], {"enabled": False})
        assert disabled["enabled"] is False
        with pytest.raises(AgentRuntimeError, match="已停用"):
            service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Use disabled skill"})
        other_agent = service.create_agent({"name": "Other Skill Agent"})
        with pytest.raises(AgentRuntimeError, match="已停用"):
            service.attach_skill(other_agent["agent_id"], skill["skill_id"])
        with pytest.raises(AgentRuntimeError):
            service.read_run_artifact(run["run_id"], "../escape.md")
    finally:
        service.close()


def test_agent_context_includes_nickname_and_persona_prompt(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "ok"})
    try:
        agent = service.create_agent(
            {
                "name": "Context Agent",
                "nickname": "Ctx",
                "instructions": "Always inspect the local brief.",
                "persona_prompt": "Speak like a careful reviewer.",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Check context"})
        artifact = service.read_run_artifact(run["run_id"], "agent-context.md")

        assert "Nickname: Ctx" in artifact["content"]
        assert "# Functional Instructions" in artifact["content"]
        assert "Always inspect the local brief." in artifact["content"]
        assert "# Persona Prompt" in artifact["content"]
        assert "Speak like a careful reviewer." in artifact["content"]
    finally:
        service.close()


def test_agent_run_rejects_unrunnable_config_before_start(tmp_path):
    service = make_service(tmp_path)
    try:
        agent = service.create_agent(
            {
                "name": "Broken Standalone Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "provider": "openai_compatible",
                    "model": "demo-model",
                },
            }
        )

        with pytest.raises(AgentRuntimeError, match="Custom API 配置不完整"):
            service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run it"})
        assert service.list_runs()["runs"] == []
    finally:
        service.close()


def test_import_skill_rejects_missing_skill_md(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "bad-skill"
    source.mkdir()
    try:
        with pytest.raises(AgentRuntimeError):
            service.import_skill(str(source))
    finally:
        service.close()


def test_import_skill_zip_rejects_path_traversal(tmp_path):
    service = make_service(tmp_path)
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../SKILL.md", "# Bad")
    try:
        with pytest.raises(AgentRuntimeError):
            service.import_skill(str(archive))
    finally:
        service.close()


def test_import_skill_zip_uses_frontmatter_source_when_available(tmp_path):
    service = make_service(tmp_path)
    archive = tmp_path / "with-source.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "skill/SKILL.md",
            "---\nname: Source Skill\nrepository: https://example.test/source-skill\n---\n\n# Source Skill\n",
        )
    try:
        skill = service.import_skill(str(archive))
        assert skill["source_type"] == "local_zip"
        assert skill["source_ref"] == "https://example.test/source-skill"
    finally:
        service.close()


def test_sync_native_skills_imports_skips_and_updates(tmp_path):
    service = make_service(tmp_path)
    native_root = tmp_path / ".oha-yachiyo" / "skill-library" / "skills"
    skill_root = native_root / "research" / "demo-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: demo-sync\ndescription: Synced skill.\n---\n\n# Demo Sync\n\nUse carefully.",
        encoding="utf-8",
    )
    (native_root / "not-a-skill").mkdir(parents=True)
    try:
        first = service.sync_native_skills(roots=[{"path": str(native_root), "source_type": "native_global"}])
        assert first["summary"]["imported"] == 1
        assert first["summary"]["skipped"] == 1
        skill = service.list_skills()["skills"][0]
        assert skill["name"] == "demo-sync"
        assert skill["description"] == "Synced skill."
        assert skill["source_type"] == "native_global"
        assert skill["origin_path"] == str(skill_root.resolve())
        assert skill["local_path"] == str(skill_root.resolve())
        assert skill["source_ref"] == "research/demo-skill"
        assert skill["content_hash"]
        assert skill["last_synced_at"]

        second = service.sync_native_skills(roots=[{"path": str(native_root), "source_type": "native_global"}])
        assert second["summary"]["imported"] == 0
        assert second["summary"]["skipped"] >= 1
        assert len(service.list_skills()["skills"]) == 1

        (skill_root / "SKILL.md").write_text(
            "---\nname: demo-sync\ndescription: Updated skill.\n---\n\n# Demo Sync\n\nUpdated instruction.",
            encoding="utf-8",
        )
        updated = service.sync_native_skills(roots=[{"path": str(native_root), "source_type": "native_global"}])
        assert updated["summary"]["updated"] == 1
        skills = service.list_skills()["skills"]
        assert len(skills) == 1
        assert skills[0]["skill_id"] == skill["skill_id"]
        assert skills[0]["description"] == "Updated skill."
        assert "Updated instruction" in skills[0]["skill_markdown"]
        service.delete_skill(skill["skill_id"])
        assert skill_root.exists()
    finally:
        service.close()


def test_deleted_synced_skill_stays_deleted_after_restart_and_sync(tmp_path):
    native_root = tmp_path / ".oha-yachiyo" / "skill-library" / "skills"
    skill_root = native_root / "research" / "deleted-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# Deleted Skill\n\nDo not restore automatically.", encoding="utf-8")

    service = make_service(tmp_path)
    try:
        synced = service.sync_native_skills(
            roots=[{"path": str(native_root), "source_type": "native_global"}]
        )
        skill_id = synced["results"][0]["skill_id"]
        service.delete_skill(skill_id)
    finally:
        service.close()

    service = make_service(tmp_path, seed_templates=True)
    try:
        synced = service.sync_native_skills(
            roots=[{"path": str(native_root), "source_type": "native_global"}]
        )

        assert service.list_skills()["skills"] == []
        assert synced["summary"]["imported"] == 0
        assert synced["results"][0]["status"] == "skipped"
        assert "用户已删除" in synced["results"][0]["message"]
    finally:
        service.close()


def test_explicit_skill_import_restores_deleted_synced_skill(tmp_path):
    native_root = tmp_path / ".oha-yachiyo" / "skill-library" / "skills"
    skill_root = native_root / "research" / "restored-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# Restored Skill\n\nRestore explicitly.", encoding="utf-8")

    service = make_service(tmp_path)
    try:
        synced = service.sync_native_skills(
            roots=[{"path": str(native_root), "source_type": "native_global"}]
        )
        service.delete_skill(synced["results"][0]["skill_id"])

        restored = service.import_skill(str(skill_root))

        assert restored["name"] == "Restored Skill"
        assert service.get_skill(restored["skill_id"])["source_type"] == "local_dir"
    finally:
        service.close()


def test_failed_skill_reimport_keeps_deletion_record(tmp_path):
    native_root = tmp_path / ".oha-yachiyo" / "skill-library" / "skills"
    skill_root = native_root / "research" / "failed-restore-skill"
    skill_root.mkdir(parents=True)
    skill_md = skill_root / "SKILL.md"
    skill_md.write_text("# Failed Restore Skill\n\nKeep deletion.", encoding="utf-8")

    service = make_service(tmp_path)
    try:
        synced = service.sync_native_skills(
            roots=[{"path": str(native_root), "source_type": "native_global"}]
        )
        service.delete_skill(synced["results"][0]["skill_id"])
        skill_md.unlink()

        with pytest.raises(AgentRuntimeError, match="SKILL.md"):
            service.import_skill(str(skill_root))

        skill_md.write_text("# Failed Restore Skill\n\nKeep deletion.", encoding="utf-8")
        resynced = service.sync_native_skills(
            roots=[{"path": str(native_root), "source_type": "native_global"}]
        )

        assert resynced["summary"]["imported"] == 0
        assert service.list_skills()["skills"] == []
    finally:
        service.close()


def test_explicit_skill_reinstall_restores_deleted_installed_skill(tmp_path):
    service = make_service(tmp_path)
    skill_root = service.skill_installs_native_home / "skills" / "restored-installed-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "# Restored Installed Skill\n\nRestore through reinstall.",
        encoding="utf-8",
    )
    try:
        synced = service.sync_installed_skills()
        synced_skill = next(result for result in synced["results"] if result.get("skill_id"))
        service.delete_skill(synced_skill["skill_id"])

        skipped = service.sync_installed_skills()
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            "# Restored Installed Skill\n\nRestore through reinstall.",
            encoding="utf-8",
        )
        restored = service.sync_installed_skills(restore_deleted=True)

        assert skipped["summary"]["imported"] == 0
        assert restored["summary"]["imported"] == 1
        assert service.list_skills()["skills"][0]["name"] == "Restored Installed Skill"
    finally:
        service.close()


def test_skill_install_command_validation_rejects_shell_and_unknown_commands(tmp_path):
    service = make_service(tmp_path)
    try:
        with pytest.raises(AgentRuntimeError, match="shell"):
            service.install_skill_command("npx skills add owner/repo && rm -rf /")
        with pytest.raises(AgentRuntimeError, match="只允许"):
            service.install_skill_command("npm install owner/repo")
    finally:
        service.close()


def test_skill_install_command_validation_accepts_latest_and_source_shortcuts(tmp_path):
    service = make_service(tmp_path)
    try:
        argv, installer = service._validated_skill_install_argv("skills@latest add owner/repo")
        assert installer == "npx_skills"
        assert argv == ["npx", "skills@latest", "add", "owner/repo", "-a", "oha-yachiyo", "--copy", "-y"]

        argv, installer = service._validated_skill_install_argv("npx -y skills@latest add owner/repo")
        assert installer == "npx_skills"
        assert argv == ["npx", "-y", "skills@latest", "add", "owner/repo", "-a", "oha-yachiyo", "--copy"]

        argv, installer = service._validated_skill_install_argv("owner/repo --skill docs")
        assert installer == "npx_skills"
        assert argv == ["npx", "skills@latest", "add", "owner/repo", "--skill", "docs", "-a", "oha-yachiyo", "--copy", "-y"]

        with pytest.raises(AgentRuntimeError, match="oha-yachiyo"):
            service._validated_skill_install_argv("npx skills@latest add owner/repo -a codex")
    finally:
        service.close()


def test_skill_dedup_is_scoped_to_yachiyo_or_native_library(tmp_path):
    service = make_service(tmp_path)
    native_root = tmp_path / ".oha-yachiyo" / "skill-library" / "skills" / "dev" / "shared"
    yachiyo_root = tmp_path / "local-shared"
    content = "# Shared Skill\n\nSame instructions."
    native_root.mkdir(parents=True)
    yachiyo_root.mkdir()
    (native_root / "SKILL.md").write_text(content, encoding="utf-8")
    (yachiyo_root / "SKILL.md").write_text(content, encoding="utf-8")
    try:
        service.sync_native_skills(
            roots=[{"path": str(tmp_path / ".oha-yachiyo" / "skill-library" / "skills"), "source_type": "native_global"}]
        )
        service.import_skill(str(yachiyo_root))
        skills = service.list_skills()["skills"]
        assert len(skills) == 2
        assert {skill["source_type"] for skill in skills} == {"native_global", "local_dir"}
    finally:
        service.close()


def test_skill_folders_assign_move_and_delete_without_moving_files(tmp_path):
    service = make_service(tmp_path)
    skill_root = tmp_path / "laravel-skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("# Laravel Skill\n\nUse Laravel conventions.", encoding="utf-8")
    try:
        folder = service.create_skill_folder({"name": "Laravel"})
        skill = service.import_skill(str(skill_root), folder["folder_id"])
        assert skill["folder_id"] == folder["folder_id"]
        assert skill["folder_name"] == "Laravel"

        folders = service.list_skill_folders()
        listed = next(item for item in folders["folders"] if item["folder_id"] == folder["folder_id"])
        assert listed["skill_count"] == 1
        assert listed["installed_count"] == 1

        moved = service.update_skill(skill["skill_id"], {"folder_id": ""})
        assert moved["folder_id"] == ""
        assert moved["local_path"].startswith(str(service.skills_dir))

        service.update_skill(skill["skill_id"], {"folder_id": folder["folder_id"]})
        service.delete_skill_folder(folder["folder_id"])
        after_delete = service.get_skill(skill["skill_id"])
        assert after_delete["folder_id"] == ""
        assert after_delete["local_path"].startswith(str(service.skills_dir))
    finally:
        service.close()


def test_delete_skill_folder_can_delete_contained_skills(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    skill_root = tmp_path / "folder-delete-skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("# Folder Delete Skill\n\nDelete with folder.", encoding="utf-8")
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "ok"})
    try:
        folder = service.create_skill_folder({"name": "Disposable"})
        skill = service.import_skill(str(skill_root), folder["folder_id"])
        local_path = Path(skill["local_path"])
        agent = service.create_agent({"name": "Folder Delete Agent"})
        service.attach_skill(agent["agent_id"], skill["skill_id"])

        deleted = service.delete_skill_folder(folder["folder_id"], delete_skills=True)

        assert deleted["ok"] is True
        assert deleted["deleted_skill_count"] == 1
        with pytest.raises(KeyError):
            service.get_skill(skill["skill_id"])
        assert service.get_agent(agent["agent_id"])["skill_ids"] == []
        assert not local_path.exists()
    finally:
        service.close()


def test_skill_folder_validation_rejects_missing_folder(tmp_path):
    service = make_service(tmp_path)
    skill_root = tmp_path / "missing-folder-skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("# Missing Folder Skill\n\nDemo.", encoding="utf-8")
    try:
        with pytest.raises(AgentRuntimeError, match="文件夹不存在"):
            service.import_skill(str(skill_root), "folder_missing")
    finally:
        service.close()


def test_skill_folder_validation_rejects_duplicate_and_long_names(tmp_path):
    service = make_service(tmp_path)
    try:
        service.create_skill_folder({"name": "Design"})
        with pytest.raises(AgentRuntimeError, match="已存在"):
            service.create_skill_folder({"name": "design"})
        with pytest.raises(AgentRuntimeError, match="不能超过"):
            service.create_skill_folder({"name": "x" * 121})
    finally:
        service.close()


def test_native_skill_list_repairs_old_managed_copy_path(tmp_path):
    service = make_service(tmp_path)
    native_root = tmp_path / ".oha-yachiyo" / "skill-library" / "skills" / "productivity" / "powerpoint"
    native_root.mkdir(parents=True)
    (native_root / "SKILL.md").write_text("# Powerpoint\n\nCreate decks.", encoding="utf-8")
    try:
        skill = service.sync_native_skills(
            roots=[{"path": str(tmp_path / ".oha-yachiyo" / "skill-library" / "skills"), "source_type": "native_global"}]
        )["results"][0]
        skill_id = skill["skill_id"]
        old_copy = service.skills_dir / skill_id
        old_copy.mkdir(parents=True, exist_ok=True)
        (old_copy / "SKILL.md").write_text("# Old Copy\n\nold", encoding="utf-8")
        service._conn.execute("UPDATE skills SET local_path=? WHERE skill_id=?", (str(old_copy), skill_id))
        service._conn.commit()

        repaired = service.list_skills()["skills"][0]
        assert repaired["local_path"] == str(native_root.resolve())
        assert repaired["origin_path"] == str(native_root.resolve())
        assert not old_copy.exists()
    finally:
        service.close()


def test_skill_install_command_runs_whitelisted_npx_and_syncs(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    recorded: dict[str, object] = {}
    monkeypatch.setenv("SSH_AUTH_SOCK", "ssh-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_skill_secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-skill-secret")
    monkeypatch.setenv("CUSTOM_API_KEY", "custom-skill-secret")

    def fake_run(argv, **_kwargs):
        recorded["argv"] = list(argv)
        recorded["env"] = dict(_kwargs["env"])
        skill_root = Path(_kwargs["cwd"]) / ".skills" / "skills" / "dev" / "installed-skill"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text("# Installed Skill\n\nInstalled by npx.", encoding="utf-8")
        (Path(_kwargs["cwd"]) / "skills-lock.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "skills": {
                        "installed-skill": {
                            "source": "owner/repo",
                            "sourceType": "github",
                            "skillPath": "skills/dev/installed-skill/SKILL.md",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, stdout="installed", stderr="")

    monkeypatch.setattr("apps.shell.agent_runtime.subprocess.run", fake_run)
    try:
        result = service.install_skill_command("npx skills add owner/repo")
        assert result["ok"] is True
        assert result["installer"] == "npx_skills"
        assert recorded["argv"] == ["npx", "skills", "add", "owner/repo", "-a", "oha-yachiyo", "--copy", "-y"]
        env = recorded["env"]
        assert isinstance(env, dict)
        assert env["OHA_YACHIYO_HOME"] == str(service.skill_installs_native_home)
        assert "SSH_AUTH_SOCK" not in env
        assert "GITHUB_TOKEN" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "CUSTOM_API_KEY" not in env
        assert result["sync"]["summary"]["imported"] == 1
        skill = service.list_skills()["skills"][0]
        assert skill["name"] == "Installed Skill"
        assert skill["source_type"] == "npx_skills"
        assert skill["source_ref"] == "https://github.com/owner/repo/blob/main/skills/dev/installed-skill/SKILL.md"
        assert "/skill-installs/.skills/skills/" in skill["local_path"]
    finally:
        service.close()


def test_workflow_validation_rejects_branch_and_cycle(tmp_path):
    service = make_service(tmp_path)
    try:
        with pytest.raises(AgentRuntimeError, match="未知 Workflow 节点类型"):
            service.validate_workflow(
                [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "mystery", "type": "email", "data": {"label": "Email Step"}},
                ],
                [{"source": "start", "target": "mystery"}],
            )

        nodes = [
            {"id": "start", "type": "start", "data": {"label": "Start"}},
            {"id": "a", "type": "agent", "data": {"label": "A"}},
            {"id": "b", "type": "agent", "data": {"label": "B"}},
        ]
        with pytest.raises(AgentRuntimeError):
            service.validate_workflow(
                nodes,
                [
                    {"source": "start", "target": "a"},
                    {"source": "start", "target": "b"},
                ],
            )
        with pytest.raises(AgentRuntimeError):
            service.validate_workflow(
                nodes,
                [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "a"},
                ],
            )
    finally:
        service.close()


def test_workflow_run_rejects_start_only_draft(tmp_path):
    service = make_service(tmp_path)
    try:
        workflow = service.create_workflow(
            {
                "name": "Start Only Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                ],
                "edges": [],
            }
        )

        assert service.validate_workflow(workflow["nodes"], workflow["edges"]) == {"ok": True}
        with pytest.raises(AgentRuntimeError, match="至少需要一个可执行节点"):
            service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})
    finally:
        service.close()


def test_workflow_name_validation_and_update_trim(tmp_path):
    service = make_service(tmp_path)
    try:
        nodes = [{"id": "start", "type": "start", "data": {"label": "Start"}}]
        with pytest.raises(AgentRuntimeError, match="名称不能为空"):
            service.create_workflow({"name": "  ", "nodes": nodes, "edges": []})

        workflow = service.create_workflow({"name": "Name Trim Flow", "nodes": nodes, "edges": []})
        updated = service.update_workflow(workflow["workflow_id"], {"name": "  Renamed Flow  "})

        assert updated["name"] == "Renamed Flow"
        with pytest.raises(AgentRuntimeError, match="名称不能为空"):
            service.update_workflow(workflow["workflow_id"], {"name": "   "})
    finally:
        service.close()


def test_workflow_run_rejects_unrunnable_agent_config_before_start(tmp_path):
    service = make_service(tmp_path)
    try:
        agent = service.create_agent(
            {
                "name": "Broken Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.example.test/v1",
                },
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Broken Agent Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "agent", "type": "agent", "data": {"label": "Broken Agent", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )

        with pytest.raises(AgentRuntimeError, match="Custom API 配置不完整"):
            service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})
        assert service.list_runs()["runs"] == []
    finally:
        service.close()


def test_workflow_run_rejects_follow_main_agent_without_default_profile(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: FakeNoDefaultProfileService())
    try:
        agent = service.create_agent(
            {
                "name": "Follow Main Agent",
                "model_mode": "follow_main",
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Follow Main Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "agent", "type": "agent", "data": {"label": "Follow Main", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )

        with pytest.raises(AgentRuntimeError, match="缺少可运行的 Chat Profile"):
            service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})
        assert service.list_runs()["runs"] == []
    finally:
        service.close()


def test_linear_workflow_executes_agent_nodes_in_order(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Profile result"})
    try:
        continuation_calls: list[dict] = []
        original_continue = service.workflow_continuation.continue_run

        def spy_continue(run, workflow, **kwargs):
            continuation_calls.append({"run_id": run.get("run_id"), "workflow_id": workflow.get("workflow_id")})
            return original_continue(run, workflow, **kwargs)

        monkeypatch.setattr(service.workflow_continuation, "continue_run", spy_continue)
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Agent A", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "Agent B", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Linear Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Agent A", "agent_id": agent_a["agent_id"]}},
                    {"id": "b", "type": "agent", "data": {"label": "Agent B", "agent_id": agent_b["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        assert continuation_calls == [{"run_id": run["run_id"], "workflow_id": workflow["workflow_id"]}]
        assert run["status"] == "completed"
        assert run["run_group_id"]
        assert [event["event"] for event in run["timeline"]].count("workflow.node.agent") == 2
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"] == [
            {"id": "start", "kind": "start", "label": "Start"},
            {"id": "a", "kind": "agent", "label": "Agent A"},
            {"id": "b", "kind": "agent", "label": "Agent B"},
        ]
        assert run["result"] == "Profile result"
        group = service.get_run_group(run["run_group_id"])
        assert group["source"] == "workflow"
        assert len(group["child_run_ids"]) == 3
    finally:
        service.close()


def test_updated_workflow_run_uses_latest_saved_graph(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    contexts: list[str] = []
    responses = iter(["Fresh design", "Fresh code"])

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        contexts.append(messages[-1]["content"])
        return {"content": next(responses)}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        old_agent = service.create_agent({"name": "Old Agent", "model_mode": "custom_api", "model_config": model_config})
        design_agent = service.create_agent({"name": "Fresh Design", "model_mode": "custom_api", "model_config": model_config})
        coding_agent = service.create_agent({"name": "Fresh Coding", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Save And Run Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "old", "type": "agent", "data": {"label": "Old Agent", "agent_id": old_agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "old"}],
            }
        )
        service.update_workflow(
            workflow["workflow_id"],
            {
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Fresh Design", "agent_id": design_agent["agent_id"]}},
                    {"id": "coding", "type": "agent", "data": {"label": "Fresh Coding", "agent_id": coding_agent["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "coding"},
                ],
            },
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship latest graph"})

        assert run["status"] == "completed"
        assert run["result"] == "Fresh code"
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"] == [
            {"id": "start", "kind": "start", "label": "Start"},
            {"id": "design", "kind": "agent", "label": "Fresh Design"},
            {"id": "coding", "kind": "agent", "label": "Fresh Coding"},
        ]
        agent_events = [event for event in run["timeline"] if event["event"] == "workflow.node.agent"]
        assert [event["workflow_node_id"] for event in agent_events] == ["design", "coding"]
        assert [event["workflow_node_label"] for event in agent_events] == ["Fresh Design", "Fresh Coding"]
        group = service.get_run_group(run["run_group_id"])
        child_runs = [
            service.get_run(run_id)
            for run_id in group["child_run_ids"]
            if run_id != run["run_id"]
        ]
        assert [child["runnable_id"] for child in child_runs] == [design_agent["agent_id"], coding_agent["agent_id"]]
        assert len(contexts) == 2
        assert "Old Agent" not in "\n".join(contexts)
    finally:
        service.close()


def test_workflow_child_agents_keep_goal_and_receive_prior_result_as_upstream(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    contexts = []
    responses = iter(["Design output", "Code output"])

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        contexts.append(messages[-1]["content"])
        return {"content": next(responses)}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Design Agent", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "Coding Agent", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Context Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Design Agent", "agent_id": agent_a["agent_id"]}},
                    {"id": "b", "type": "agent", "data": {"label": "Coding Agent", "agent_id": agent_b["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        assert run["status"] == "completed"
        assert run["result"] == "Code output"
        assert "# User Goal\nShip it" in contexts[0]
        assert "# Upstream Context\nNone" in contexts[0]
        assert "# User Goal\nShip it" in contexts[1]
        assert "# Upstream Context\nDesign output" in contexts[1]
        assert "# User Goal\nDesign output" not in contexts[1]
        assert contexts[1].count("Design output") == 1

        group = service.get_run_group(run["run_group_id"])
        agent_runs = [
            service.get_run(run_id)
            for run_id in group["child_run_ids"]
            if run_id != run["run_id"]
        ]
        assert [child["user_goal"] for child in agent_runs] == ["Ship it", "Ship it"]
    finally:
        service.close()


def test_workflow_agent_nodes_can_define_step_tasks(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    contexts: list[str] = []
    responses = iter(["Research notes", "Implementation plan"])

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        contexts.append(messages[-1]["content"])
        return {"content": next(responses)}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        research_agent = service.create_agent({"name": "Research Agent", "model_mode": "custom_api", "model_config": model_config})
        coding_agent = service.create_agent({"name": "Coding Agent", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Step Task Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "research",
                        "type": "agent",
                        "data": {
                            "label": "Research",
                            "agent_id": research_agent["agent_id"],
                            "task": "Collect constraints and summarize the tradeoffs.",
                        },
                    },
                    {
                        "id": "coding",
                        "type": "agent",
                        "data": {
                            "label": "Coding",
                            "agent_id": coding_agent["agent_id"],
                            "instructions": "Turn the research notes into an implementation plan.",
                        },
                    },
                ],
                "edges": [
                    {"source": "start", "target": "research"},
                    {"source": "research", "target": "coding"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship feature X"})

        assert run["status"] == "completed"
        assert "# User Goal\nCollect constraints and summarize the tradeoffs.\n\nWorkflow Goal:\nShip feature X" in contexts[0]
        assert "# Upstream Context\nNone" in contexts[0]
        assert "# User Goal\nTurn the research notes into an implementation plan.\n\nWorkflow Goal:\nShip feature X" in contexts[1]
        assert "# Upstream Context\nResearch notes" in contexts[1]

        group = service.get_run_group(run["run_group_id"])
        agent_runs = [
            service.get_run(run_id)
            for run_id in group["child_run_ids"]
            if run_id != run["run_id"]
        ]
        assert [child["user_goal"] for child in agent_runs] == [
            "Collect constraints and summarize the tradeoffs.\n\nWorkflow Goal:\nShip feature X",
            "Turn the research notes into an implementation plan.\n\nWorkflow Goal:\nShip feature X",
        ]
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"][1]["task"] == "Collect constraints and summarize the tradeoffs."
        agent_events = [event for event in run["timeline"] if event["event"] == "workflow.node.agent"]
        assert [event["workflow_node_task"] for event in agent_events] == [
            "Collect constraints and summarize the tradeoffs.",
            "Turn the research notes into an implementation plan.",
        ]
    finally:
        service.close()


def test_workflow_rejects_missing_and_disabled_agent_nodes(tmp_path):
    service = make_service(tmp_path)
    try:
        with pytest.raises(AgentRuntimeError, match="没有选择 Agent"):
            service.create_workflow(
                {
                    "name": "Missing Agent Flow",
                    "nodes": [
                        {"id": "start", "type": "start", "data": {"label": "Start"}},
                        {"id": "agent", "type": "agent", "data": {"label": "Agent Step"}},
                    ],
                    "edges": [{"source": "start", "target": "agent"}],
                }
            )

        with pytest.raises(AgentRuntimeError, match="引用了不存在的 Agent"):
            service.create_workflow(
                {
                    "name": "Unknown Agent Flow",
                    "nodes": [
                        {"id": "start", "type": "start", "data": {"label": "Start"}},
                        {
                            "id": "agent",
                            "type": "agent",
                            "data": {"label": "Agent Step", "agent_id": "agent_missing"},
                        },
                    ],
                    "edges": [{"source": "start", "target": "agent"}],
                }
            )

        disabled = service.create_agent({"name": "Disabled Agent", "enabled": False})
        with pytest.raises(AgentRuntimeError, match="已停用"):
            service.create_workflow(
                {
                    "name": "Disabled Agent Flow",
                    "nodes": [
                        {"id": "start", "type": "start", "data": {"label": "Start"}},
                        {
                            "id": "agent",
                            "type": "agent",
                            "data": {"label": "Agent Step", "agent_id": disabled["agent_id"]},
                        },
                    ],
                    "edges": [{"source": "start", "target": "agent"}],
                }
            )
    finally:
        service.close()


def test_workflow_run_rejects_agent_disabled_after_save(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": "Should not run"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Later Disabled",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Later Disabled Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Agent Step", "agent_id": agent["agent_id"]},
                    },
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )
        service.update_agent(agent["agent_id"], {"enabled": False})

        with pytest.raises(AgentRuntimeError, match="已停用"):
            service.create_workflow_run(
                {"workflow_id": workflow["workflow_id"], "user_goal": "Run disabled agent"}
            )

        assert calls == []
    finally:
        service.close()


def test_workflow_approval_node_pauses_and_resumes(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": f"Agent {len(calls)} complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Before Approval", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "After Approval", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Human Gate Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Before Approval", "agent_id": agent_a["agent_id"]}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {
                            "label": "人工确认",
                            "criteria": "确认设计输出已经覆盖验收点，再继续编码。",
                        },
                    },
                    {"id": "b", "type": "agent", "data": {"label": "After Approval", "agent_id": agent_b["agent_id"]}},
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "gate"},
                    {"source": "gate", "target": "b"},
                    {"source": "b", "target": "summary"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        assert run["status"] == "approval_required"
        assert run["result"] == "等待审批：人工确认"
        assert run["pending_approval"]["tool"] == "workflow.approval"
        assert run["pending_approval"]["input_preview"]["checkpoint"] == "人工确认"
        assert run["pending_approval"]["input_preview"]["criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert run["pending_approval"]["input_preview"]["context"] == "Agent 1 complete"
        assert "workflow_context" not in run["pending_approval"]
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"][2]["criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert [event["event"] for event in run["timeline"] if event["event"] == "workflow.node.agent"] == [
            "workflow.node.agent",
        ]
        start_event = next(event for event in run["timeline"] if event["event"] == "workflow.node.start")
        assert start_event["workflow_node_id"] == "start"
        assert start_event["status"] == "completed"
        approval_event = next(event for event in run["timeline"] if event["event"] == "workflow.node.approval_required")
        assert approval_event["workflow_node_id"] == "gate"
        assert approval_event["workflow_node_approval_criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert approval_event["status"] == "approval_required"
        replay_before = service.list_run_events(run["run_id"])["events"]
        approval_required_fact = next(
            event for event in replay_before
            if event["event_type"] == "workflow.node.approval_required"
        )
        assert approval_required_fact["payload"]["workflow_node_id"] == "gate"
        assert approval_required_fact["payload"]["workflow_node_label"] == "人工确认"
        assert approval_required_fact["payload"]["workflow_node_approval_criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert approval_required_fact["payload"]["pending_approval"]["tool"] == "workflow.approval"
        assert service.get_run_group(run["run_group_id"])["status"] == "approval_required"

        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Agent 2 complete"
        assert resumed["pending_approval"] == {}
        assert len(calls) == 2
        approval_approved = next(event for event in resumed["timeline"] if event["event"] == "workflow.node.approval_approved")
        assert approval_approved["detail"] == "人工确认"
        assert approval_approved["workflow_node_id"] == "gate"
        assert approval_approved["workflow_node_approval_criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert approval_approved["input_preview"]["checkpoint"] == "人工确认"
        assert approval_approved["input_preview"]["criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert approval_approved["input_preview"]["context"] == "Agent 1 complete"
        assert approval_approved["status"] == "completed"
        assert [event["event"] for event in resumed["timeline"]].count("workflow.node.agent") == 2
        artifact_event = next(event for event in resumed["timeline"] if event["event"] == "workflow.node.artifact")
        assert artifact_event["workflow_node_id"] == "summary"
        assert artifact_event["status"] == "completed"
        assert artifact_event["artifact"]["path"] == "summary.md"
        assert any(artifact.get("kind") == "workflow_artifact" for artifact in resumed["artifacts"])
        replay_after_types = [
            event["event_type"] for event in service.list_run_events(run["run_id"])["events"]
        ]
        assert replay_after_types.count("workflow.node.approval_required") == 1
        assert "workflow.node.approval_approved" in replay_after_types
        assert "workflow.run.completed" in replay_after_types
        assert service.get_run_group(run["run_group_id"])["status"] == "completed"
    finally:
        service.close()


def test_cancel_workflow_approval_updates_group_and_step_info(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": f"Agent {len(calls)} complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({"name": "Before Approval", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Cancelable Gate Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Before Approval", "agent_id": agent["agent_id"]}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {
                            "label": "人工确认",
                            "criteria": "确认设计输出已经覆盖验收点，再继续编码。",
                        },
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "gate"},
                    {"source": "gate", "target": "summary"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})
        assert run["status"] == "approval_required"
        assert service.get_run_group(run["run_group_id"])["status"] == "approval_required"

        cancelled = service.cancel_run(run["run_id"])

        assert cancelled["status"] == "cancelled"
        assert cancelled["pending_approval"] == {}
        assert cancelled["result"] == "Workflow 已取消：人工确认"
        assert len(calls) == 1
        cancelled_event = next(event for event in cancelled["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["detail"] == "人工确认 cancelled"
        assert cancelled_event["workflow_node_id"] == "gate"
        assert cancelled_event["workflow_node_kind"] == "approval"
        assert cancelled_event["workflow_node_label"] == "人工确认"
        assert cancelled_event["status"] == "cancelled"
        run_events = service.list_run_events(run["run_id"])["events"]
        assert any(event["event_type"] == "workflow.run.started" for event in run_events)
        cancelled_fact = next(event for event in run_events if event["event_type"] == "workflow.run.cancelled")
        assert cancelled_fact["payload"]["kind"] == "workflow_run"
        assert cancelled_fact["payload"]["status"] == "cancelled"
        group = service.get_run_group(run["run_group_id"])
        assert group["status"] == "cancelled"
        assert group["summary"] == "Workflow 已取消：人工确认"
    finally:
        service.close()


def test_workflow_approval_resume_uses_runtime_snapshot_after_workflow_edit(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        context = str(messages[1]["content"])
        assert "Name: Original After Approval" in context
        assert "Name: Edited After Approval" not in context
        return {"content": "Original agent complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        original_agent = service.create_agent({"name": "Original After Approval", "model_mode": "custom_api", "model_config": model_config})
        edited_agent = service.create_agent({"name": "Edited After Approval", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Editable Paused Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "gate", "type": "approval", "data": {"label": "Manual Gate"}},
                    {"id": "after", "type": "agent", "data": {"label": "Original After Approval", "agent_id": original_agent["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "after"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Wait then run"})
        assert run["status"] == "approval_required"
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_snapshot"]["nodes"][2]["data"]["agent_id"] == original_agent["agent_id"]

        service.update_workflow(
            workflow["workflow_id"],
            {
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "gate", "type": "approval", "data": {"label": "Manual Gate"}},
                    {"id": "after", "type": "agent", "data": {"label": "Edited After Approval", "agent_id": edited_agent["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "after"},
                ],
            },
        )

        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Original agent complete"
        assert len(calls) == 1
        agent_event = next(event for event in resumed["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "after"
        assert agent_event["workflow_node_label"] == "Original After Approval"
    finally:
        service.close()


def test_workflow_approval_node_reject_cancels_run(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": "First step complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({"name": "Before Approval", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Reject Gate Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Before Approval", "agent_id": agent["agent_id"]}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {
                            "label": "人工确认",
                            "criteria": "确认设计输出已经覆盖验收点，再继续编码。",
                        },
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "gate"},
                    {"source": "gate", "target": "summary"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        rejected = service.reject_run_approval(run["run_id"], "先暂停")

        assert rejected["status"] == "cancelled"
        assert rejected["pending_approval"] == {}
        assert rejected["result"] == "Workflow 审批已拒绝：先暂停"
        assert len(calls) == 1
        rejected_event = next(event for event in rejected["timeline"] if event["event"] == "workflow.node.approval_rejected")
        assert rejected_event["detail"] == "先暂停"
        assert rejected_event["workflow_node_id"] == "gate"
        assert rejected_event["workflow_node_kind"] == "approval"
        assert rejected_event["workflow_node_label"] == "人工确认"
        assert rejected_event["workflow_node_approval_criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert rejected_event["input_preview"]["checkpoint"] == "人工确认"
        assert rejected_event["input_preview"]["criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert rejected_event["input_preview"]["context"] == "First step complete"
        assert rejected_event["status"] == "cancelled"
        cancelled_event = next(event for event in rejected["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["detail"] == "先暂停"
        assert cancelled_event["workflow_node_id"] == "gate"
        assert cancelled_event["workflow_node_kind"] == "approval"
        assert cancelled_event["workflow_node_label"] == "人工确认"
        assert cancelled_event["workflow_node_approval_criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert cancelled_event["input_preview"]["checkpoint"] == "人工确认"
        assert cancelled_event["status"] == "cancelled"
        group = service.get_run_group(run["run_group_id"])
        assert group["status"] == "cancelled"
        assert group["summary"] == "Workflow 审批已拒绝：先暂停"
    finally:
        service.close()


def test_workflow_duplicate_artifact_labels_write_unique_paths(tmp_path):
    service = make_service(tmp_path)
    try:
        workflow = service.create_workflow(
            {
                "name": "Duplicate Artifact Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "summary-a", "type": "artifact", "data": {"label": "Summary"}},
                    {"id": "summary-b", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "summary-a"},
                    {"source": "summary-a", "target": "summary-b"},
                ],
            }
        )

        run = service.create_workflow_run(
            {"workflow_id": workflow["workflow_id"], "user_goal": "Write duplicate artifacts"}
        )

        assert run["status"] == "completed"
        artifacts = [artifact for artifact in run["artifacts"] if artifact.get("kind") == "workflow_artifact"]
        assert [artifact["path"] for artifact in artifacts] == ["summary.md", "summary-2.md"]
        assert [artifact["workflow_node_id"] for artifact in artifacts] == ["summary-a", "summary-b"]
        artifact_rows = service._conn.execute(
            "SELECT kind, path, sequence, payload_json FROM run_artifacts WHERE run_id=? ORDER BY sequence",
            (run["run_id"],),
        ).fetchall()
        assert [(row["kind"], row["path"], row["sequence"]) for row in artifact_rows] == [
            ("workflow_artifact", "summary.md", 0),
            ("workflow_artifact", "summary-2.md", 1),
        ]
        assert json.loads(artifact_rows[0]["payload_json"])["workflow_node_id"] == "summary-a"
        assert service.read_run_artifact(run["run_id"], "summary.md")["content"] == "Write duplicate artifacts"
        assert service.read_run_artifact(run["run_id"], "summary-2.md")["content"] == "Write duplicate artifacts"
        artifact_events = [event for event in run["timeline"] if event["event"] == "workflow.node.artifact"]
        assert [event["artifact"]["path"] for event in artifact_events] == ["summary.md", "summary-2.md"]
        assert [event["workflow_node_id"] for event in artifact_events] == ["summary-a", "summary-b"]
        run_events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in run_events]
        assert "workflow.run.started" in event_types
        assert "workflow.run.completed" in event_types
    finally:
        service.close()


def test_workflow_artifact_nodes_can_use_configured_paths(tmp_path):
    service = make_service(tmp_path)
    try:
        workflow = service.create_workflow(
            {
                "name": "Configured Artifact Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "report-a",
                        "type": "artifact",
                        "data": {"label": "Report A", "artifact_path": "reports/final-report.md"},
                    },
                    {
                        "id": "report-b",
                        "type": "artifact",
                        "data": {"label": "Report B", "artifact_path": "reports/final-report.md"},
                    },
                    {
                        "id": "notes",
                        "type": "artifact",
                        "data": {"label": "Notes", "artifact_path": "reports/notes"},
                    },
                ],
                "edges": [
                    {"source": "start", "target": "report-a"},
                    {"source": "report-a", "target": "report-b"},
                    {"source": "report-b", "target": "notes"},
                ],
            }
        )

        run = service.create_workflow_run(
            {"workflow_id": workflow["workflow_id"], "user_goal": "Configured artifact content"}
        )

        assert run["status"] == "completed"
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert [item.get("artifact_path") for item in started_event["workflow_path"] if item.get("kind") == "artifact"] == [
            "reports/final-report.md",
            "reports/final-report-2.md",
            "reports/notes.md",
        ]
        artifacts = [artifact for artifact in run["artifacts"] if artifact.get("kind") == "workflow_artifact"]
        assert [artifact["path"] for artifact in artifacts] == [
            "reports/final-report.md",
            "reports/final-report-2.md",
            "reports/notes.md",
        ]
        assert service.read_run_artifact(run["run_id"], "reports/final-report.md")["content"] == "Configured artifact content"
        assert service.read_run_artifact(run["run_id"], "reports/final-report-2.md")["content"] == "Configured artifact content"
        assert service.read_run_artifact(run["run_id"], "reports/notes.md")["content"] == "Configured artifact content"
    finally:
        service.close()


def test_workflow_rejects_invalid_artifact_path(tmp_path):
    service = make_service(tmp_path)
    try:
        with pytest.raises(AgentRuntimeError, match="Artifact 节点 Report 的产物路径无效"):
            service.create_workflow(
                {
                    "name": "Bad Artifact Path",
                    "nodes": [
                        {"id": "start", "type": "start", "data": {"label": "Start"}},
                        {
                            "id": "report",
                            "type": "artifact",
                            "data": {"label": "Report", "artifact_path": "../escape.md"},
                        },
                    ],
                    "edges": [{"source": "start", "target": "report"}],
                }
            )
    finally:
        service.close()


def test_workflow_approval_resume_fails_if_next_agent_was_disabled(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": "Should not run"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Next Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Approval Then Agent",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "gate", "type": "approval", "data": {"label": "Manual Gate"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Next Agent", "agent_id": agent["agent_id"]},
                    },
                ],
                "edges": [
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "agent"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Wait first"})
        service.update_agent(agent["agent_id"], {"enabled": False})

        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "failed"
        assert "已停用" in resumed["result"]
        assert calls == []
        failed_event = next(event for event in resumed["timeline"] if event["event"] == "workflow.run.failed")
        assert failed_event["workflow_node_id"] == "agent"
        assert failed_event["workflow_node_kind"] == "agent"
        assert failed_event["workflow_node_label"] == "Next Agent"
        assert service.get_run_group(run["run_group_id"])["status"] == "failed"
    finally:
        service.close()


def test_workflow_canvas_spec_exposes_participants_and_executes(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    responses = iter(["Design brief", "Code patch"])

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {"content": next(responses)}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        design = service.create_agent({
            "name": "Design Agent",
            "nickname": "Design",
            "avatar_url": "https://example.test/design.png",
            "model_mode": "custom_api",
            "model_config": model_config,
        })
        coding = service.create_agent({
            "name": "Coding Agent",
            "nickname": "Code",
            "avatar_url": "https://example.test/code.png",
            "model_mode": "custom_api",
            "model_config": model_config,
        })
        workflow = service.create_workflow(
            {
                "name": "Web Design Chain",
                "nodes": [
                    {"id": "start", "type": "start", "position": {"x": 40, "y": 120}, "data": {"label": "Start", "kind": "start"}},
                    {"id": "design", "type": "agent", "position": {"x": 260, "y": 120}, "data": {"label": "Design", "kind": "agent", "agent_id": design["agent_id"]}},
                    {"id": "coding", "type": "agent", "position": {"x": 480, "y": 120}, "data": {"label": "Coding", "kind": "agent", "agent_id": coding["agent_id"]}},
                ],
                "edges": [
                    {"id": "edge-start-design", "source": "start", "target": "design"},
                    {"id": "edge-design-coding", "source": "design", "target": "coding"},
                ],
            }
        )

        runnable = next(item for item in service.list_runnables()["runnables"] if item["id"] == workflow["workflow_id"])
        run = service.create_run_for_runnable(runnable_id=workflow["workflow_id"], user_goal="Build a landing page")

        assert runnable["kind"] == "workflow"
        assert [participant["name"] for participant in runnable["participants"]] == ["Design Agent", "Coding Agent"]
        assert [participant["avatar_url"] for participant in runnable["participants"]] == [
            "https://example.test/design.png",
            "https://example.test/code.png",
        ]
        assert all("tool_policy" in participant for participant in runnable["participants"])
        assert all("artifact.write" in participant["tool_policy"]["allowed_tools"] for participant in runnable["participants"])
        assert run["status"] == "completed"
        assert run["result"] == "Code patch"
        assert [event["event"] for event in run["timeline"]].count("workflow.node.agent") == 2
        assert service.get_run_group(run["run_group_id"])["source"] == "workflow"
    finally:
        service.close()


def test_list_runs_returns_roots_and_standalone_agents_only(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "OK"})
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Workflow Agent A", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "Workflow Agent B", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "List Runs Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Agent A", "agent_id": agent_a["agent_id"]}},
                    {"id": "b", "type": "agent", "data": {"label": "Agent B", "agent_id": agent_b["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                ],
            }
        )

        workflow_run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})
        standalone_agent_run = service.create_agent_run({"agent_id": agent_a["agent_id"], "user_goal": "Run alone"})

        listed = service.list_runs(limit=20)["runs"]
        listed_ids = {run["run_id"] for run in listed}
        group = service.get_run_group(workflow_run["run_group_id"])
        workflow_child_run_ids = [
            run_id
            for run_id in group["child_run_ids"]
            if run_id != workflow_run["run_id"]
        ]

        assert workflow_run["run_id"] in listed_ids
        assert standalone_agent_run["run_id"] in listed_ids
        assert not any(run_id in listed_ids for run_id in workflow_child_run_ids)
        assert service.get_run(workflow_child_run_ids[0])["run_group_source"] == "workflow"
        assert service.get_run(standalone_agent_run["run_id"])["run_group_source"] == "agent"
    finally:
        service.close()


def test_list_runs_hides_workflow_child_agents_for_delegated_workflows(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "OK"})
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({"name": "Delegated Workflow Agent", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Delegated Workflow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "agent", "type": "agent", "data": {"label": "Agent", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )

        delegated = service.delegate_runnable(
            kind="workflow",
            runnable_id=workflow["workflow_id"],
            user_goal="Run delegated workflow",
        )
        group = service.get_run_group(delegated["run_group_id"])
        child_agent_run_ids = [
            run_id
            for run_id in group["child_run_ids"]
            if service.get_run(run_id)["kind"] == "agent_run"
        ]
        listed_ids = {run["run_id"] for run in service.list_runs(limit=20)["runs"]}

        assert service.get_run_group(delegated["run_group_id"])["source"] == "delegation"
        assert delegated["run_id"] in listed_ids
        assert child_agent_run_ids
        assert not any(run_id in listed_ids for run_id in child_agent_run_ids)
    finally:
        service.close()


def test_list_runs_hides_workflow_child_agents_for_custom_workflow_sources(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "OK"})
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({"name": "Custom Source Workflow Agent", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Custom Source Workflow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "agent", "type": "agent", "data": {"label": "Agent", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )

        workflow_run = service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Run workflow from a specific smoke source",
                "source": "workflow_child_artifact_smoke",
            }
        )
        group = service.get_run_group(workflow_run["run_group_id"])
        child_agent_run_ids = [
            run_id
            for run_id in group["child_run_ids"]
            if service.get_run(run_id)["kind"] == "agent_run"
        ]
        listed_ids = {run["run_id"] for run in service.list_runs(limit=20)["runs"]}

        assert group["source"] == "workflow_child_artifact_smoke"
        assert workflow_run["run_id"] in listed_ids
        assert child_agent_run_ids
        assert not any(run_id in listed_ids for run_id in child_agent_run_ids)
    finally:
        service.close()


def test_workflow_stops_when_child_agent_fails(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(*_args, **_kwargs):
        calls.append("called")
        raise RuntimeError("model exploded")

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Failing Agent", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "Skipped Agent", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Fail Fast Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Failing Agent", "agent_id": agent_a["agent_id"]}},
                    {"id": "b", "type": "agent", "data": {"label": "Skipped Agent", "agent_id": agent_b["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        assert run["status"] == "failed"
        assert run["result"] == "model exploded"
        assert calls == ["called"]
        assert [event["event"] for event in run["timeline"]].count("workflow.node.agent") == 1
        failed_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.failed")
        assert failed_event["workflow_node_id"] == "a"
        assert failed_event["workflow_node_kind"] == "agent"
        assert failed_event["workflow_node_label"] == "Failing Agent"
        assert service.get_run_group(run["run_group_id"])["status"] == "failed"
    finally:
        service.close()


def test_agent_execution_backend_legacy_values_normalize_to_native(tmp_path):
    service = make_service(tmp_path)
    try:
        native_agent = service.create_agent({"name": "Native Agent"})
        assert native_agent["execution_backend"] == "native_profile"
        run = service.create_agent_run({"agent_id": native_agent["agent_id"], "user_goal": "Plan"})
        assert run["status"] == "failed"
        assert "Chat Profile" in run["result"]

        external = service.create_agent({"name": "CLI Agent", "execution_backend": "external_cli"})
        assert external["execution_backend"] == "native_profile"
        external_run = service.create_agent_run({"agent_id": external["agent_id"], "user_goal": "Review"})
        assert external_run["status"] == "failed"
        assert "Chat Profile" in external_run["result"]

        with pytest.raises(AgentRuntimeError, match="不再支持 legacy"):
            service.create_agent({"name": "Legacy Agent", "execution_backend": "hermes_profile"})
    finally:
        service.close()


def test_delegation_targets_and_delegate_run(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Delegated result"})
    try:
        agent = service.create_agent(
            {
                "name": "Delegated Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        targets = service.list_delegation_targets()
        assert any(item["name"] == "Delegated Agent" for item in targets["agents"])

        result = service.delegate_runnable(kind="agent", name="Delegated Agent", user_goal="Do the work")
        assert result["ok"] is True
        assert result["runnable"]["id"] == agent["agent_id"]
        assert result["result"] == "Delegated result"
        run = service.get_run(result["run_id"])
        assert run["status"] == "completed"
        assert run["run_group_id"]
    finally:
        service.close()


def test_agent_run_executes_native_tool_call_and_continues(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("hello native tools", encoding="utf-8")
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert any((tool.get("function") or {}).get("name") == "workspace_read" for tool in tools or [])
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "README.md"})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "hello native tools" in messages[-1]["content"]
        return {"content": "Read complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Read README"})

        assert run["status"] == "completed"
        assert run["result"] == "Read complete"
        tool_event = next(event for event in run["timeline"] if event["event"] == "agent.tool.call" and event["detail"] == "workspace.read")
        assert tool_event["input_preview"]["path"] == "README.md"
        assert tool_event["result"]["ok"] is True
        run_events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in run_events]
        assert "agent.run.started" in event_types
        assert "agent.run.completed" in event_types
        tool_fact = next(event for event in run_events if event["event_type"] == "agent.tool.call")
        assert tool_fact["payload"]["tool"] == "workspace.read"
        assert tool_fact["payload"]["input_preview"]["path"] == "README.md"
        assert tool_fact["payload"]["result"]["ok"] is True
    finally:
        service.close()


def test_agent_tool_output_is_truncated_by_runtime_budget(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    service.runtime_limits = service.runtime_limits.__class__(max_tool_output_chars=30)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "long.txt").write_text("x" * 120, encoding="utf-8")
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "long.txt"})},
                    }
                ],
            }
        assert "[truncated]" in messages[-1]["content"]
        assert "x" * 60 not in messages[-1]["content"]
        return {"content": "Read truncated"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Truncating Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Read long file"})
        tool_event = next(event for event in run["timeline"] if event["event"] == "agent.tool.call")

        assert run["status"] == "completed"
        assert run["result"] == "Read truncated"
        assert tool_event["result"]["truncated"] is True
        assert len(tool_event["result"]["content"]) <= 30
    finally:
        service.close()


def test_agent_run_fails_when_tool_call_budget_is_exceeded(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    service.runtime_limits = service.runtime_limits.__class__(max_tool_calls=1)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_list_1",
                    "type": "function",
                    "function": {"name": "workspace_list", "arguments": json.dumps({"path": "."})},
                },
                {
                    "id": "call_list_2",
                    "type": "function",
                    "function": {"name": "workspace_list", "arguments": json.dumps({"path": "."})},
                },
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Budgeted Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.list"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "List twice"})

        assert run["status"] == "failed"
        assert "max_tool_calls=1" in run["result"]
        tool_events = [event for event in run["timeline"] if event["event"] == "agent.tool.call"]
        assert len(tool_events) == 1
    finally:
        service.close()


def test_agent_run_fails_when_model_call_budget_is_exceeded(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    service.runtime_limits = service.runtime_limits.__class__(max_model_calls=1)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_list",
                    "type": "function",
                    "function": {"name": "workspace_list", "arguments": json.dumps({"path": "."})},
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Model Budget Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.list"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Loop once"})

        assert run["status"] == "failed"
        assert "max_model_calls=1" in run["result"]
        assert len(calls) == 1
    finally:
        service.close()


def test_agent_run_fails_when_run_duration_budget_is_exceeded(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    service.runtime_limits = service.runtime_limits.__class__(max_run_duration_seconds=1)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    clock = {"now": 1000.0}
    calls = []

    def fake_time():
        return clock["now"]

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        clock["now"] = 1002.0
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_list",
                    "type": "function",
                    "function": {"name": "workspace_list", "arguments": json.dumps({"path": "."})},
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.time.time", fake_time)
    monkeypatch.setattr("apps.shell.agent_runtime._iso_epoch", lambda _value: 1000.0)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Duration Budget Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.list"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "List until timeout"})

        assert run["status"] == "failed"
        assert "max_run_duration_seconds=1" in run["result"]
        assert len(calls) == 1
        assert [event["event"] for event in run["timeline"]].count("agent.model.response") == 1
        assert [event["event"] for event in run["timeline"]].count("agent.tool.call") == 0
    finally:
        service.close()


def test_agent_run_fails_when_terminal_budget_is_exceeded_after_approval(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    service.runtime_limits = service.runtime_limits.__class__(max_terminal_calls=0)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {"name": "terminal_run", "arguments": json.dumps({"command": "printf blocked"})},
                }
            ],
        },
    )
    try:
        agent = service.create_agent(
            {
                "name": "Terminal Budget Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run command"})
        resumed = service.approve_run_approval(run["run_id"])

        assert run["status"] == "approval_required"
        assert resumed["status"] == "failed"
        assert "max_terminal_calls=0" in resumed["result"]
    finally:
        service.close()


def test_agent_run_can_recover_from_workspace_tool_shape_error(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("hello", encoding="utf-8")
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_bad_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "."})},
                    }
                ],
            }
        if len(calls) == 2:
            assert messages[-1]["role"] == "tool"
            assert "suggested_tool" in messages[-1]["content"]
            assert "workspace.list" in messages[-1]["content"]
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_list",
                        "type": "function",
                        "function": {"name": "workspace_list", "arguments": json.dumps({"path": "."})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "README.md" in messages[-1]["content"]
        return {"content": "Recovered and listed files"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Recovering Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read", "workspace.list"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Inspect repo"})

        assert run["status"] == "completed"
        assert run["result"] == "Recovered and listed files"
        tool_results = [
            event["result"]
            for event in run["timeline"]
            if event["event"] == "agent.tool.call" and isinstance(event.get("result"), dict)
        ]
        assert tool_results[0]["ok"] is False
        assert tool_results[0]["suggested_tool"] == "workspace.list"
        assert tool_results[1]["ok"] is True
    finally:
        service.close()


def test_agent_run_recovers_from_absolute_workspace_path_with_terminal(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    external_file = tmp_path / "external.txt"
    external_file.write_text("outside workspace", encoding="utf-8")
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert "Never pass absolute paths to workspace tools" in messages[0]["content"]
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_bad_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": str(external_file)})},
                    }
                ],
            }
        if len(calls) == 2:
            assert messages[-1]["role"] == "tool"
            assert "suggested_tool" in messages[-1]["content"]
            assert "terminal.run" in messages[-1]["content"]
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {"name": "terminal_run", "arguments": json.dumps({"command": f"cat {external_file}"})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "outside workspace" in messages[-1]["content"]
        return {"content": "Recovered with terminal"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "External Path Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read", "terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Read the external file"})

        assert run["status"] == "approval_required"
        workspace_event = next(
            event
            for event in run["timeline"]
            if event["event"] == "agent.tool.call" and event["detail"] == "workspace.read"
        )
        assert workspace_event["result"]["ok"] is False
        assert workspace_event["result"]["suggested_tool"] == "terminal.run"

        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Recovered with terminal"
    finally:
        service.close()


def test_agent_tool_loop_limit_includes_last_tool_detail(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_bad_read_{len(calls)}",
                    "type": "function",
                    "function": {"name": "workspace_read", "arguments": json.dumps({"path": "."})},
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Looping Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read", "workspace.list"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Inspect repo"})

        assert run["status"] == "failed"
        assert "工具循环超过上限" in run["result"]
        assert "最后一次工具调用：workspace.read" in run["result"]
        assert "建议工具：workspace.list" in run["result"]
    finally:
        service.close()


def test_agent_tool_loop_limit_after_artifact_write_completes_with_artifact(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {
            "content": json.dumps(
                {
                    "action": "tool",
                    "tool": "artifact.write",
                    "input": {"path": "done.md", "content": "done"},
                }
            )
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Looping Writer",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Write artifact"})

        assert run["status"] == "completed"
        assert "模型在工具循环上限前没有返回最终总结" in run["result"]
        assert "done.md" in run["result"]
        assert any(artifact.get("path") == "done.md" for artifact in run["artifacts"])
        assert service.read_run_artifact(run["run_id"], "done.md")["content"] == "done"
        assert any(event["event"] == "agent.tool.loop_limit_completed" for event in run["timeline"])
        assert len(calls) == 50
    finally:
        service.close()


def test_artifact_write_redacts_file_content_and_passes_secret_scan(tmp_path):
    artifact_root = tmp_path / "artifacts"
    broker = ToolBroker({}, artifact_root)

    result = broker.artifact_write("reports/secret-report.md", "api_key=sk-artifact-secret123456\nsafe")
    artifact_path = artifact_root / "reports" / "secret-report.md"
    content = artifact_path.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert "sk-artifact-secret123456" not in content
    assert "api_key=[redacted]" in content
    assert verify_secret_redaction(paths=[artifact_root]) == []


def test_agent_run_json_fallback_writes_artifact(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": json.dumps({"action": "tool", "tool": "artifact.write", "input": {"path": "notes.md", "content": "hello"}})}
        assert "Tool result for artifact.write" in messages[-1]["content"]
        return {"content": "Artifact done"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Artifact Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Write artifact"})

        assert run["status"] == "completed"
        assert any(artifact.get("path") == "notes.md" for artifact in run["artifacts"])
        assert service.read_run_artifact(run["run_id"], "notes.md")["content"] == "hello"
    finally:
        service.close()


def test_agent_output_contract_expands_diff_rules_in_runtime_context(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append({"messages": messages, "tools": tools})
        return {"content": "Inline code response"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Diff Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.write_patch", "artifact.write"]},
                "output_contract": "diff",
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Show a tiny function without changing files"})

        assert run["status"] == "completed"
        assert calls
        system_prompt = calls[0]["messages"][0]["content"]
        context = calls[0]["messages"][1]["content"]
        assert "Do not request a tool solely because of the output contract" in system_prompt
        assert "If the user asks not to create, save, write, or modify files" in system_prompt
        assert "If the user asks not to run or execute commands" in system_prompt
        assert "Contract: diff" in context
        assert "Do not call workspace.write_patch merely because the output contract is diff" in context
        assert "If no file change is requested, provide code inline." in context
    finally:
        service.close()


def test_agent_run_skips_write_tool_when_user_goal_forbids_file_changes(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append({"messages": messages, "tools": tools})
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_write",
                        "type": "function",
                        "function": {
                            "name": "workspace_write_patch",
                            "arguments": json.dumps(
                                {
                                    "path": "scripts/demo.py",
                                    "patch": "--- scripts/demo.py\n+++ scripts/demo.py\n@@ -1 +1 @@\n-print('old')\n+print('demo')\n",
                                }
                            ),
                        },
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        tool_result = json.loads(messages[-1]["content"])
        assert tool_result["blocked_by_user_goal"] is True
        assert tool_result["tool"] == "workspace.write_patch"
        assert "inline" in tool_result["hint"]
        return {"content": "Here is the code inline."}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "No File Writer",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.write_patch", "artifact.write"]},
                "output_contract": "diff",
            }
        )
        run = service.create_agent_run({
            "agent_id": agent["agent_id"],
            "user_goal": "Show a tiny function without changing files",
        })

        assert run["status"] == "completed"
        assert run["result"] == "Here is the code inline."
        assert run["pending_approval"] == {}
        skipped_event = next(event for event in run["timeline"] if event["event"] == "agent.tool.skipped" and event["detail"] == "workspace.write_patch")
        assert skipped_event["input_preview"]["path"] == "scripts/demo.py"
        assert skipped_event["result"]["blocked_by_user_goal"] is True
        assert not any(event["event"] == "agent.tool.approval_required" for event in run["timeline"])
    finally:
        service.close()


def test_agent_run_skips_artifact_tool_when_chinese_goal_says_inline_only(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": json.dumps({"action": "tool", "tool": "artifact.write", "input": {"path": "card.html", "content": "<div>card</div>"}})}
        assert "blocked_by_user_goal" in messages[-1]["content"]
        assert "inline" in messages[-1]["content"]
        return {"content": "完整代码如下：<div>card</div>"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Inline Design Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["artifact.write"]},
                "output_contract": "artifacts",
            }
        )
        run = service.create_agent_run({
            "agent_id": agent["agent_id"],
            "user_goal": "用纯 HTML + CSS 制作一个简单卡片组件，代码完整展示即可。",
        })

        assert run["status"] == "completed"
        assert run["result"] == "完整代码如下：<div>card</div>"
        assert not any(artifact.get("path") == "card.html" for artifact in run["artifacts"])
        assert not any(artifact.get("kind") == "tool_artifact" for artifact in run["artifacts"])
        assert run["pending_approval"] == {}
        assert any(event["event"] == "agent.tool.skipped" and event["detail"] == "artifact.write" for event in run["timeline"])
    finally:
        service.close()


def test_workflow_child_agent_no_run_goal_does_not_request_terminal_approval(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {"name": "terminal_run", "arguments": json.dumps({"command": "python3 demo.py"})},
                    }
                ],
            }
        assert "blocked_by_user_goal" in messages[-1]["content"]
        assert "不要运行命令或脚本" in messages[-1]["content"]
        return {"content": "代码示例已经 inline 展示。"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "No Run Coding Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "No Run Workflow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "code", "type": "agent", "data": {"label": "Code", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "code"}],
            }
        )
        run = service.create_workflow_run({
            "workflow_id": workflow["workflow_id"],
            "user_goal": "写一个 Python 示例即可，不需要运行命令或脚本。",
        })

        assert run["status"] == "completed"
        assert run["result"] == "代码示例已经 inline 展示。"
        assert run["pending_approval"] == {}
        assert service.get_run_group(run["run_group_id"])["status"] == "completed"
        child_run_id = next(run_id for run_id in service.get_run_group(run["run_group_id"])["child_run_ids"] if run_id != run["run_id"])
        child = service.get_run(child_run_id)
        assert child["status"] == "completed"
        assert child["pending_approval"] == {}
        assert any(event["event"] == "agent.tool.skipped" and event["detail"] == "terminal.run" for event in child["timeline"])
        assert not any(event["event"] == "agent.tool.approval_required" for event in child["timeline"])
    finally:
        service.close()


def test_agent_run_explicit_terminal_goal_not_blocked_by_downstream_no_execute_text(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf terminal-explicit-smoke; exit 7", "shell": True}),
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Explicit Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({
            "agent_id": agent["agent_id"],
            "user_goal": "必须请求 terminal.run 执行命令。不要执行后续 artifact 节点，只使用 terminal.run。",
        })

        assert run["status"] == "approval_required"
        assert run["pending_approval"]["tool"] == "terminal.run"
        assert not any(event["event"] == "agent.tool.skipped" and event["detail"] == "terminal.run" for event in run["timeline"])
    finally:
        service.close()


def test_agent_run_denies_unallowed_tool(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {"name": "terminal_run", "arguments": json.dumps({"command": "echo no"})},
                }
            ],
        },
    )
    try:
        agent = service.create_agent(
            {
                "name": "Denied Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run command"})

        assert run["status"] == "failed"
        assert "未授权工具" in run["result"]
        assert any(event["event"] == "agent.tool.denied" for event in run["timeline"])
    finally:
        service.close()


def test_workflow_parent_records_child_agent_artifact_refs(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": json.dumps({"action": "tool", "tool": "artifact.write", "input": {"path": "design.md", "content": "design artifact"}})}
        if len(calls) == 2:
            assert "Tool result for artifact.write" in messages[-1]["content"]
            return {"content": "Design done"}
        return {"content": "Code done"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        design_agent = service.create_agent(
            {
                "name": "Design Artifact Agent",
                "model_mode": "custom_api",
                "model_config": model_config,
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        coding_agent = service.create_agent(
            {
                "name": "Coding Summary Agent",
                "model_mode": "custom_api",
                "model_config": model_config,
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Artifact Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Design", "agent_id": design_agent["agent_id"]}},
                    {"id": "code", "type": "agent", "data": {"label": "Code", "agent_id": coding_agent["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "code"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship artifacts"})

        assert run["status"] == "completed"
        child_artifact_refs = [
            artifact
            for artifact in run["artifacts"]
            if artifact.get("kind") == "workflow_child_artifact"
        ]
        assert all(artifact.get("artifact_kind") != "context" for artifact in child_artifact_refs)
        design_ref = next(artifact for artifact in child_artifact_refs if artifact.get("path") == "design.md")
        assert design_ref["workflow_step_label"] == "Design"
        assert design_ref["source_runnable_name"] == "Design Artifact Agent"
        assert service.read_run_artifact(design_ref["source_run_id"], "design.md")["content"] == "design artifact"
        design_event = next(
            event
            for event in run["timeline"]
            if event["event"] == "workflow.node.agent" and event["detail"] == "Design"
        )
        assert design_event["status"] == "completed"
        assert design_event["result"] == "Design done"
        assert design_event["artifact_count"] >= 1
    finally:
        service.close()


def test_agent_run_pauses_for_terminal_approval_and_resumes(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf approved"}),
                        },
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "approved" in messages[-1]["content"]
        return {"content": "Command complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        resume_contexts: list[ToolApprovalResumeContext] = []
        original_resume = service.approval_resume.execute_approved_tool

        def spy_resume(context: ToolApprovalResumeContext) -> None:
            resume_contexts.append(context)
            original_resume(context)

        monkeypatch.setattr(service.approval_resume, "execute_approved_tool", spy_resume)
        agent = service.create_agent(
            {
                "name": "Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run command"})

        assert run["status"] == "approval_required"
        assert run["pending_approval"]["tool"] == "terminal.run"
        assert "messages" not in run["pending_approval"]
        approval_row = service._conn.execute(
            "SELECT status, tool, input_preview_json, payload_json FROM run_approvals WHERE run_id=?",
            (run["run_id"],),
        ).fetchone()
        assert approval_row is not None
        assert approval_row["status"] == "pending"
        assert approval_row["tool"] == "terminal.run"
        assert json.loads(approval_row["input_preview_json"])["command"] == "printf approved"
        assert "messages" not in json.loads(approval_row["payload_json"])
        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Command complete"
        assert len(resume_contexts) == 1
        assert resume_contexts[0].run_id == run["run_id"]
        assert resume_contexts[0].tool_name == "terminal.run"
        assert resume_contexts[0].input_preview["command"] == "printf approved"
        approval_after = service._conn.execute(
            "SELECT status, resolved_at FROM run_approvals WHERE run_id=?",
            (run["run_id"],),
        ).fetchone()
        assert approval_after is not None
        assert approval_after["status"] == "approved"
        assert approval_after["resolved_at"]
        approved_event = next(event for event in resumed["timeline"] if event["event"] == "agent.tool.approval_approved")
        assert approved_event["detail"] == "terminal.run"
        assert approved_event["input_preview"]["command"] == "printf approved"
        assert approved_event["status"] == "completed"
        run_events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in run_events]
        assert "agent.tool.approval_required" in event_types
        assert "agent.tool.approval_approved" in event_types
        approved_fact = next(event for event in run_events if event["event_type"] == "agent.tool.approval_approved")
        assert approved_fact["payload"]["tool"] == "terminal.run"
        assert approved_fact["payload"]["input_preview"]["command"] == "printf approved"
        tool_facts = [event for event in run_events if event["event_type"] == "agent.tool.call"]
        assert tool_facts[-1]["payload"]["tool"] == "terminal.run"
        assert tool_facts[-1]["payload"]["approved"] is True
        assert service.get_run_group(resumed["run_group_id"])["status"] == "completed"
    finally:
        service.close()


def test_agent_run_consecutive_terminal_approvals_update_pending_request(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_first_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf first-approved"}),
                        },
                    },
                    {
                        "id": "call_second_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf second-approved"}),
                        },
                    },
                ],
            }
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert any("first-approved" in message.get("content", "") for message in tool_messages)
        assert any("second-approved" in message.get("content", "") for message in tool_messages)
        return {"content": "Both terminal approvals completed"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Consecutive Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run both commands"})

        assert run["status"] == "approval_required"
        assert run["pending_approval"]["tool"] == "terminal.run"
        assert run["pending_approval"]["input_preview"]["command"] == "printf first-approved"

        after_first = service.approve_run_approval(run["run_id"])
        assert after_first["status"] == "approval_required"
        assert after_first["result"] == "等待审批：terminal.run"
        assert after_first["pending_approval"]["tool"] == "terminal.run"
        assert after_first["pending_approval"]["input_preview"]["command"] == "printf second-approved"
        assert len(calls) == 1

        after_second = service.approve_run_approval(run["run_id"])
        assert after_second["status"] == "completed"
        assert after_second["result"] == "Both terminal approvals completed"
        assert after_second["pending_approval"] == {}
        assert len(calls) == 2

        approved_events = [event for event in after_second["timeline"] if event["event"] == "agent.tool.approval_approved"]
        assert [event["input_preview"]["command"] for event in approved_events] == [
            "printf first-approved",
            "printf second-approved",
        ]
        assert service.get_run_group(after_second["run_group_id"])["status"] == "completed"
    finally:
        service.close()


def test_agent_run_supports_more_than_six_terminal_turns(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []
    terminal_turns = 8

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        turn = len(calls)
        if turn <= terminal_turns:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_terminal_{turn}",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": f"printf terminal-turn-{turn}"}),
                        },
                    }
                ],
            }
        return {"content": "All terminal turns completed"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Long Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run all terminal checks"})

        for turn in range(terminal_turns):
            assert run["status"] == "approval_required"
            assert run["pending_approval"]["input_preview"]["command"] == f"printf terminal-turn-{turn + 1}"
            run = service.approve_run_approval(run["run_id"])

        assert run["status"] == "completed"
        assert run["result"] == "All terminal turns completed"
        assert len(calls) == terminal_turns + 1
    finally:
        service.close()


def test_agent_run_fails_when_approved_terminal_returns_nonzero(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf terminal-failure-smoke; exit 7", "shell": True}),
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Failing Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run failing command"})

        assert run["status"] == "approval_required"
        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "failed"
        assert "terminal.run 执行失败" in resumed["result"]
        assert "退出码：7" in resumed["result"]
        assert "terminal-failure-smoke" in resumed["result"]
        assert len(calls) == 1
        failed_event = next(event for event in resumed["timeline"] if event["event"] == "agent.tool.failed")
        assert failed_event["status"] == "failed"
        assert failed_event["result"]["returncode"] == 7
        assert failed_event["result"]["stdout"] == "terminal-failure-smoke"
        assert service.get_run_group(resumed["run_group_id"])["status"] == "failed"
    finally:
        service.close()


def test_workflow_resumes_after_child_agent_approval(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []
    resuming_statuses = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {"name": "terminal_run", "arguments": json.dumps({"command": "printf approved"})},
                    }
                ],
            }
        if len(calls) == 2:
            assert messages[-1]["role"] == "tool"
            assert "approved" in messages[-1]["content"]
            parent_during_resume = service.get_run(run["run_id"])
            child_during_resume = service.get_run(child_run_ids[0])
            group_during_resume = service.get_run_group(run["run_group_id"])
            resuming_statuses.append(
                (
                    child_during_resume["status"],
                    parent_during_resume["status"],
                    group_during_resume["status"],
                    parent_during_resume["result"],
                )
            )
            return {"content": "Agent A complete"}
        return {"content": "Agent B complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent(
            {
                "name": "Needs Approval",
                "model_mode": "custom_api",
                "model_config": model_config,
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        agent_b = service.create_agent(
            {
                "name": "After Approval",
                "model_mode": "custom_api",
                "model_config": model_config,
            }
        )
        edited_agent = service.create_agent(
            {
                "name": "Edited After Approval",
                "model_mode": "custom_api",
                "model_config": model_config,
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Approval Resume Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "a",
                        "type": "agent",
                        "data": {
                            "label": "Needs Approval",
                            "agent_id": agent_a["agent_id"],
                        },
                    },
                    {
                        "id": "b",
                        "type": "agent",
                        "data": {
                            "label": "After Approval",
                            "agent_id": agent_b["agent_id"],
                        },
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "summary"},
                ],
            }
        )

        run = service.create_workflow_run(
            {"workflow_id": workflow["workflow_id"], "user_goal": "Run approval flow"}
        )

        assert run["status"] == "approval_required"
        group = service.get_run_group(run["run_group_id"])
        child_run_ids = [run_id for run_id in group["child_run_ids"] if run_id != run["run_id"]]
        assert len(child_run_ids) == 1
        child = service.get_run(child_run_ids[0])
        assert child["status"] == "approval_required"

        child_running_calls: list[str] = []
        parent_resume_calls: list[str] = []
        original_mark_child_running = service.workflow_parent_resume.mark_child_running
        original_resume_after_child_update = service.workflow_parent_resume.resume_after_child_update

        def spy_mark_child_running(child_run: dict) -> None:
            child_running_calls.append(str(child_run.get("run_id") or ""))
            original_mark_child_running(child_run)

        def spy_resume_after_child_update(child_run: dict) -> None:
            parent_resume_calls.append(str(child_run.get("run_id") or ""))
            original_resume_after_child_update(child_run)

        monkeypatch.setattr(service.workflow_parent_resume, "mark_child_running", spy_mark_child_running)
        monkeypatch.setattr(service.workflow_parent_resume, "resume_after_child_update", spy_resume_after_child_update)

        service.update_workflow(
            workflow["workflow_id"],
            {
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "a",
                        "type": "agent",
                        "data": {
                            "label": "Needs Approval",
                            "agent_id": agent_a["agent_id"],
                        },
                    },
                    {
                        "id": "b",
                        "type": "agent",
                        "data": {
                            "label": "Edited After Approval",
                            "agent_id": edited_agent["agent_id"],
                        },
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "summary"},
                ],
            },
        )
        approved_child = service.approve_run_approval(child["run_id"])

        assert resuming_statuses == [
            ("running", "running", "running", "Needs Approval 已批准，正在继续执行")
        ]
        assert child_running_calls == [child["run_id"]]
        assert parent_resume_calls == [child["run_id"]]
        assert approved_child["status"] == "completed"
        assert any(event["event"] == "agent.run.resumed" for event in approved_child["timeline"])
        resumed_parent = service.get_run(run["run_id"])
        assert resumed_parent["status"] == "completed"
        assert resumed_parent["result"] == "Agent B complete"
        agent_events = [
            event
            for event in resumed_parent["timeline"]
            if event["event"] == "workflow.node.agent"
        ]
        assert len(agent_events) == 2
        assert agent_events[0]["status"] == "completed"
        assert agent_events[0]["result"] == "Agent A complete"
        assert agent_events[1]["workflow_node_label"] == "After Approval"
        assert any(event["event"] == "workflow.run.child_resumed" for event in resumed_parent["timeline"])
        assert any(event["event"] == "workflow.run.resumed" for event in resumed_parent["timeline"])
        assert any(
            artifact.get("kind") == "workflow_artifact"
            for artifact in resumed_parent["artifacts"]
        )
        assert service.get_run_group(run["run_group_id"])["status"] == "completed"
    finally:
        service.close()


def test_workflow_fails_when_child_terminal_returns_nonzero_after_approval(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf workflow-child-failure-smoke; exit 7", "shell": True}),
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent(
            {
                "name": "Failing Child",
                "model_mode": "custom_api",
                "model_config": model_config,
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Child Terminal Failure Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Failing Child", "agent_id": agent["agent_id"]}},
                    {
                        "id": "artifact",
                        "type": "artifact",
                        "data": {"label": "Should Not Run", "artifact_path": "reports/should-not-run.md"},
                    },
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "artifact"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Run failing child"})

        assert run["status"] == "approval_required"
        group = service.get_run_group(run["run_group_id"])
        child_run_ids = [run_id for run_id in group["child_run_ids"] if run_id != run["run_id"]]
        assert len(child_run_ids) == 1
        child = service.get_run(child_run_ids[0])

        resumed_child = service.approve_run_approval(child["run_id"])
        resumed_parent = service.get_run(run["run_id"])

        assert resumed_child["status"] == "failed"
        assert resumed_parent["status"] == "failed"
        assert "workflow-child-failure-smoke" in resumed_parent["result"]
        assert not any(artifact.get("path") == "reports/should-not-run.md" for artifact in resumed_parent["artifacts"])
        failed_event = next(event for event in resumed_parent["timeline"] if event["event"] == "workflow.run.failed")
        assert failed_event["workflow_node_id"] == "a"
        assert failed_event["workflow_node_kind"] == "agent"
        assert failed_event["workflow_node_label"] == "Failing Child"
        assert failed_event["child_run_id"] == child["run_id"]
        assert service.get_run_group(run["run_group_id"])["status"] == "failed"
        assert len(calls) == 1
    finally:
        service.close()


def test_workflow_resume_failure_keeps_child_node_context(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    responses = iter(["approval", "Agent A complete"])

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        response = next(responses)
        if response == "approval":
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {"name": "terminal_run", "arguments": json.dumps({"command": "printf approved"})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        return {"content": response}

    def fail_resume(_run):
        raise AgentRuntimeError("workflow snapshot unavailable")

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Needs Approval",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Approval Resume Failure Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Needs Approval", "agent_id": agent["agent_id"]}},
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "summary"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Run approval flow"})
        group = service.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        monkeypatch.setattr(service, "_workflow_for_run_resume", fail_resume)

        approved_child = service.approve_run_approval(child_run_id)
        parent = service.get_run(run["run_id"])

        assert approved_child["status"] == "completed"
        assert parent["status"] == "failed"
        assert parent["result"] == "workflow snapshot unavailable"
        failed_event = next(event for event in parent["timeline"] if event["event"] == "workflow.run.failed")
        assert failed_event["workflow_node_id"] == "a"
        assert failed_event["workflow_node_kind"] == "agent"
        assert failed_event["workflow_node_label"] == "Needs Approval"
        assert failed_event["child_run_id"] == child_run_id
        assert failed_event["child_run_status"] == "completed"
        assert service.get_run_group(run["run_group_id"])["status"] == "failed"
    finally:
        service.close()


def test_workflow_parent_records_child_agent_rejection_node_info(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {"name": "terminal_run", "arguments": json.dumps({"command": "printf blocked"})},
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Needs Approval",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Rejected Child Approval Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Needs Approval", "agent_id": agent["agent_id"]}},
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "summary"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Run approval flow"})
        group = service.get_run_group(run["run_group_id"])
        child_run_ids = [run_id for run_id in group["child_run_ids"] if run_id != run["run_id"]]
        child = service.get_run(child_run_ids[0])

        rejected_child = service.reject_run_approval(child["run_id"], "not now")
        parent = service.get_run(run["run_id"])

        assert rejected_child["status"] == "cancelled"
        assert parent["status"] == "cancelled"
        assert service.get_run_group(run["run_group_id"])["status"] == "cancelled"
        agent_event = next(event for event in parent["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "a"
        assert agent_event["workflow_node_kind"] == "agent"
        assert agent_event["workflow_node_label"] == "Needs Approval"
        assert agent_event["status"] == "cancelled"
        cancelled_event = next(event for event in parent["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["workflow_node_id"] == "a"
        assert cancelled_event["workflow_node_kind"] == "agent"
        assert cancelled_event["workflow_node_label"] == "Needs Approval"
        assert cancelled_event["child_run_id"] == child["run_id"]
    finally:
        service.close()


def test_cancel_workflow_waiting_for_child_approval_cancels_child_run(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {"name": "terminal_run", "arguments": json.dumps({"command": "printf blocked"})},
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Needs Approval",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Cancelable Child Approval Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Needs Approval", "agent_id": agent["agent_id"]}},
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "summary"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Run approval flow"})
        group = service.get_run_group(run["run_group_id"])
        child_run_ids = [run_id for run_id in group["child_run_ids"] if run_id != run["run_id"]]
        child = service.get_run(child_run_ids[0])

        assert run["status"] == "approval_required"
        assert child["status"] == "approval_required"

        cancelled_parent = service.cancel_run(run["run_id"])
        cancelled_child = service.get_run(child["run_id"])

        assert cancelled_parent["status"] == "cancelled"
        assert cancelled_parent["result"] == "Workflow 已取消：Needs Approval"
        assert cancelled_child["status"] == "cancelled"
        assert cancelled_child["pending_approval"] == {}
        assert cancelled_child["result"] == "父 Workflow 已取消"
        assert service.get_run_group(run["run_group_id"])["status"] == "cancelled"
        agent_event = next(event for event in cancelled_parent["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "a"
        assert agent_event["workflow_node_kind"] == "agent"
        assert agent_event["workflow_node_label"] == "Needs Approval"
        assert agent_event["status"] == "cancelled"
        cancelled_event = next(event for event in cancelled_parent["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["workflow_node_id"] == "a"
        assert cancelled_event["workflow_node_kind"] == "agent"
        assert cancelled_event["workflow_node_label"] == "Needs Approval"
        assert cancelled_event["child_run_id"] == child["run_id"]
    finally:
        service.close()


def test_agent_run_rejects_pending_tool(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": json.dumps({"action": "tool", "tool": "terminal.run", "input": {"command": "echo blocked"}})
        },
    )
    try:
        agent = service.create_agent(
            {
                "name": "Reject Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run command"})
        leaked_secret = "sk-approval-reject-secret123456"
        rejected = service.reject_run_approval(run["run_id"], f"not now api_key={leaked_secret}")

        assert rejected["status"] == "cancelled"
        assert rejected["pending_approval"] == {}
        assert "not now" in rejected["result"]
        assert leaked_secret not in json.dumps(rejected, ensure_ascii=False)
        rejected_event = next(event for event in rejected["timeline"] if event["event"] == "agent.tool.approval_rejected")
        assert rejected_event["tool"] == "terminal.run"
        assert rejected_event["input_preview"]["command"] == "echo blocked"
        assert rejected_event["status"] == "cancelled"
        stored_run = service.get_run(run["run_id"])
        assert stored_run["status"] == "cancelled"
        assert "not now" in stored_run["result"]
        assert leaked_secret not in json.dumps(stored_run, ensure_ascii=False)
        run_events = service.list_run_events(run["run_id"])["events"]
        rejected_fact = next(event for event in run_events if event["event_type"] == "agent.tool.approval_rejected")
        assert rejected_fact["payload"]["tool"] == "terminal.run"
        assert rejected_fact["payload"]["input_preview"]["command"] == "echo blocked"
        assert rejected_fact["payload"]["status"] == "cancelled"
        cancelled_fact = next(event for event in run_events if event["event_type"] == "agent.run.cancelled")
        assert "not now" in cancelled_fact["payload"]["reason"]
        assert "not now" in cancelled_fact["payload"]["result"]
        assert leaked_secret not in json.dumps(run_events, ensure_ascii=False)
        assert verify_secret_redaction(paths=[tmp_path]) == []
    finally:
        service.close()


def test_tool_descriptor_schema_and_validation_share_patch_contract():
    schema = NativeRunEngine._tool_schemas(["workspace.write_patch"])[0]
    properties = schema["function"]["parameters"]["properties"]

    assert "patch" in properties
    assert "content" not in properties
    assert schema["function"]["parameters"]["required"] == ["path"]

    NativeRunEngine._validate_tool_payload("workspace.write_patch", {"path": "src/out.txt", "patch": "*** patch"})
    with pytest.raises(AgentRuntimeError, match="未声明字段：approved"):
        NativeRunEngine._validate_tool_payload("workspace.write_patch", {"path": "src/out.txt", "patch": "*** patch", "approved": True})
    with pytest.raises(AgentRuntimeError, match="未声明字段：content"):
        NativeRunEngine._validate_tool_payload("workspace.write_patch", {"path": "src/out.txt", "content": "bad"})
    with pytest.raises(AgentRuntimeError, match="patch 必须是非空字符串"):
        NativeRunEngine._validate_tool_payload("workspace.write_patch", {"path": "src/out.txt"})
    with pytest.raises(AgentRuntimeError, match="敏感凭据"):
        NativeRunEngine._validate_tool_payload("artifact.write", {"path": "notes.md", "content": "sk-secret-token"})


def test_model_payload_approved_flag_is_rejected_by_tool_schema(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    (workdir / "src").mkdir(parents=True)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_write",
                    "type": "function",
                    "function": {
                        "name": "workspace_write_patch",
                        "arguments": json.dumps(
                            {
                                "path": "src/out.txt",
                                "patch": "--- src/out.txt\n+++ src/out.txt\n@@ -1 +1 @@\n-before\n+bad\n",
                                "approved": True,
                            }
                        ),
                    },
                }
            ],
        },
    )
    try:
        agent = service.create_agent(
            {
                "name": "Writer",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.write_patch"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."], "writable_scopes": ["src"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Write file"})

        assert run["status"] == "failed"
        assert "未声明字段：approved" in run["result"]
        assert not (workdir / "src" / "out.txt").exists()
    finally:
        service.close()


def test_tool_broker_blocks_out_of_scope_and_unapproved_terminal(tmp_path):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("hello", encoding="utf-8")
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["src"],
        },
        tmp_path / "artifacts",
    )

    assert broker.workspace_read("README.md")["content"] == "hello"
    directory_read = broker.workspace_read(".")
    assert directory_read["ok"] is False
    assert directory_read["suggested_tool"] == "workspace.list"
    file_list = broker.workspace_list("README.md")
    assert file_list["ok"] is False
    assert file_list["suggested_tool"] == "workspace.read"
    with pytest.raises(AgentRuntimeError):
        broker.workspace_write_patch(
            "../escape.txt",
            patch="--- ../escape.txt\n+++ ../escape.txt\n@@ -1 +1 @@\n-old\n+bad\n",
            approved=True,
        )
    assert broker.terminal_run("echo should-not-run")["approval_required"] is True
    assert broker.call("terminal.run", {"command": "echo should-not-run", "approved": True})["approval_required"] is True


def test_agent_run_validates_write_patch_workspace_boundary_before_approval(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_escape_write",
                        "type": "function",
                        "function": {
                            "name": "workspace_write_patch",
                            "arguments": json.dumps(
                                {
                                    "path": "../outside.txt",
                                    "patch": "--- ../outside.txt\n+++ ../outside.txt\n@@ -1 +1 @@\n-outside\n+modified\n",
                                }
                            ),
                        },
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        tool_result = json.loads(messages[-1]["content"])
        assert tool_result["ok"] is False
        assert "越界" in tool_result["error"]
        assert "Workspace tools only accept relative paths" in tool_result["hint"]
        assert tool_result["suggested_tool"] == "terminal.run"
        return {"content": "Handled boundary refusal"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Boundary Writer",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.write_patch", "terminal.run"]},
                "workspace_policy": {
                    "default_workdir": str(workdir),
                    "readable_scopes": ["."],
                    "writable_scopes": ["."],
                },
            }
        )

        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Try outside write"})
        events = service.list_run_events(run["run_id"])["events"]

        assert run["status"] == "completed"
        assert run["result"] == "Handled boundary refusal"
        assert run["pending_approval"] == {}
        assert outside.read_text(encoding="utf-8") == "outside\n"
        assert not any(event["event"] == "agent.tool.approval_required" for event in run["timeline"])
        assert not any(event["event_type"] == "agent.tool.approval_required" for event in events)
        tool_event = next(event for event in events if event["event_type"] == "agent.tool.call")
        assert tool_event["payload"]["tool"] == "workspace.write_patch"
        assert tool_event["payload"]["result"]["ok"] is False
    finally:
        service.close()


def test_tool_broker_rejects_symlink_workspace_escape(tmp_path):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret_file = outside / "secret.txt"
    secret_file.write_text("secret", encoding="utf-8")
    outside_dir = outside / "nested"
    outside_dir.mkdir()
    try:
        (workdir / "secret-link.txt").symlink_to(secret_file)
        (workdir / "dir-link").symlink_to(outside_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable on this filesystem: {exc}")
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        tmp_path / "artifacts",
    )

    with pytest.raises(AgentRuntimeError, match="工作区范围"):
        broker.workspace_read("secret-link.txt")
    with pytest.raises(AgentRuntimeError, match="工作区范围"):
        broker.workspace_list("dir-link")
    with pytest.raises(AgentRuntimeError, match="工作区范围"):
        broker.workspace_write_patch(
            "secret-link.txt",
            patch="--- secret-link.txt\n+++ secret-link.txt\n@@ -1 +1 @@\n-secret\n+modified\n",
            approved=True,
        )
    assert secret_file.read_text(encoding="utf-8") == "secret"


def test_terminal_run_uses_workspace_argv_and_scrubbed_environment(tmp_path, monkeypatch):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setenv("SAFE_ENV", "kept")
    monkeypatch.setenv("SSH_AUTH_SOCK", "ssh-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secretsecretsecret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "google-secret")
    monkeypatch.setenv("AZURE_TOKEN", "azure-secret")
    monkeypatch.setenv("CUSTOM_API_KEY", "custom-secret")
    monkeypatch.setenv("CUSTOM_PASSWORD", "password-secret")

    class FakeProcess:
        pid = 4242
        returncode = 0

        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            captured.update(kwargs)

        def communicate(self, *, timeout):
            captured["timeout"] = timeout
            return (
                "OPENAI_API_KEY=sk-output-secret123456789",
                "Authorization: Bearer stderr-secret-123456",
            )

    monkeypatch.setattr("apps.shell.agent_runtime.subprocess.Popen", FakeProcess)
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        tmp_path / "artifacts",
    )

    result = broker.terminal_run("python -c 'print(123)'", approved=True, timeout_seconds=999)

    assert captured["argv"] == ["python", "-c", "print(123)"]
    assert captured["cwd"] == workdir
    assert captured["shell"] is False
    assert captured["start_new_session"] is True
    assert captured["timeout"] == 120
    env = captured["env"]
    assert env["SAFE_ENV"] == "kept"
    for key in (
        "SSH_AUTH_SOCK",
        "GITHUB_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "AZURE_TOKEN",
        "CUSTOM_API_KEY",
        "CUSTOM_PASSWORD",
    ):
        assert key not in env
    assert result["ok"] is True
    assert result["shell"] is False
    assert "sk-output-secret123456789" not in result["stdout"]
    assert "stderr-secret-123456" not in result["stderr"]


def test_terminal_run_startup_failure_returns_structured_sanitized_error(tmp_path, monkeypatch):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_should_not_leak_to_child")

    def fail_popen(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        raise FileNotFoundError("missing binary token=sk-startup-secret123456789")

    monkeypatch.setattr("apps.shell.agent_runtime.subprocess.Popen", fail_popen)
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        tmp_path / "artifacts",
    )

    result = broker.terminal_run("missing-native-tool --flag", approved=True)

    assert captured["argv"] == ["missing-native-tool", "--flag"]
    assert captured["cwd"] == workdir
    assert captured["shell"] is False
    assert "GITHUB_TOKEN" not in captured["env"]
    assert result["ok"] is False
    assert result["returncode"] is None
    assert result["timed_out"] is False
    assert result["stdout"] == ""
    assert "sk-startup-secret123456789" not in result["stderr"]
    assert "[redacted]" in result["stderr"]


def test_terminal_run_truncates_and_sanitizes_outputs(tmp_path, monkeypatch):
    workdir = tmp_path / "repo"
    workdir.mkdir()

    class FakeProcess:
        pid = 4243
        returncode = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def communicate(self, *, timeout):
            stdout = f"{'x' * 9000}OPENAI_API_KEY=sk-stdout-secret123456789\nstdout-tail"
            stderr = f"{'y' * 9000}Authorization: Bearer stderr-secret-123456\nstderr-tail"
            return stdout, stderr

    monkeypatch.setattr("apps.shell.agent_runtime.subprocess.Popen", FakeProcess)
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        tmp_path / "artifacts",
    )

    result = broker.terminal_run("printf long-output", approved=True)

    assert result["ok"] is True
    assert len(result["stdout"]) <= 8000
    assert len(result["stderr"]) <= 8000
    assert "sk-stdout-secret123456789" not in result["stdout"]
    assert "stderr-secret-123456" not in result["stderr"]
    assert result["stdout"].endswith("stdout-tail")
    assert result["stderr"].endswith("stderr-tail")


def test_terminal_run_timeout_kills_process_group(tmp_path, monkeypatch):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    killed: list[tuple[int, int]] = []

    class FakeProcess:
        pid = 4343
        returncode = -9

        def __init__(self, argv, **_kwargs):
            self.argv = argv
            self.calls = 0

        def communicate(self, *, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(self.argv, timeout)
            return ("late stdout", "late stderr")

    monkeypatch.setattr("apps.shell.agent_runtime.subprocess.Popen", FakeProcess)
    monkeypatch.setattr("apps.shell.agent_runtime.os.killpg", lambda pid, sig: killed.append((pid, sig)))
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        tmp_path / "artifacts",
    )

    result = broker.terminal_run("sleep 30", approved=True, timeout_seconds=1)

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["returncode"] == -9
    assert killed == [(4343, 9)]


def test_workspace_write_patch_applies_single_file_unified_diff_with_hash(tmp_path):
    workdir = tmp_path / "repo"
    (workdir / "src").mkdir(parents=True)
    target = workdir / "src" / "app.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["src"],
        },
        tmp_path / "artifacts",
    )
    patch = """--- a/src/app.txt
+++ b/src/app.txt
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
"""

    result = broker.call(
        "workspace.write_patch",
        {"path": "src/app.txt", "patch": patch, "expected_sha256": before_sha},
        approved=True,
    )

    assert result["ok"] is True
    assert result["mode"] == "patch"
    assert result["sha256_before"] == before_sha
    assert result["sha256_after"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert target.read_text(encoding="utf-8") == "one\nTWO\nthree\n"


def test_workspace_write_patch_rejects_hash_or_context_mismatch_without_writing(tmp_path):
    workdir = tmp_path / "repo"
    (workdir / "src").mkdir(parents=True)
    target = workdir / "src" / "app.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["src"],
        },
        tmp_path / "artifacts",
    )
    context_mismatch_patch = """--- a/src/app.txt
+++ b/src/app.txt
@@ -1,3 +1,3 @@
 one
-missing
+TWO
 three
"""

    hash_result = broker.call(
        "workspace.write_patch",
        {"path": "src/app.txt", "patch": context_mismatch_patch, "expected_sha256": "0" * 64},
        approved=True,
    )

    assert hash_result["ok"] is False
    assert "hash" in hash_result["error"]
    assert target.read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    with pytest.raises(AgentRuntimeError, match="hunk context"):
        broker.call(
            "workspace.write_patch",
            {"path": "src/app.txt", "patch": context_mismatch_patch},
            approved=True,
        )
    assert target.read_text(encoding="utf-8") == "one\ntwo\nthree\n"


def test_workspace_write_patch_rejects_multifile_or_binary_patch(tmp_path):
    workdir = tmp_path / "repo"
    (workdir / "src").mkdir(parents=True)
    (workdir / "src" / "app.txt").write_text("one\n", encoding="utf-8")
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["src"],
        },
        tmp_path / "artifacts",
    )
    multifile_patch = """--- a/src/app.txt
+++ b/src/app.txt
@@ -1 +1 @@
-one
+two
--- a/src/other.txt
+++ b/src/other.txt
@@ -1 +1 @@
-x
+y
"""

    with pytest.raises(AgentRuntimeError, match="单文件"):
        broker.call("workspace.write_patch", {"path": "src/app.txt", "patch": multifile_patch}, approved=True)
    with pytest.raises(AgentRuntimeError, match="二进制"):
        broker.call("workspace.write_patch", {"path": "src/app.txt", "patch": "GIT binary patch\n"}, approved=True)


def test_explicit_empty_tool_policy_disables_model_tools(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    captured = {}

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        captured["messages"] = messages
        captured["tools"] = tools
        return {"content": "No tools used"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "No Tools Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": []},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Answer only"})

        assert agent["tool_policy"]["allowed_tools"] == []
        assert run["status"] == "completed"
        assert captured["tools"] == []
        prompt = captured["messages"][0]["content"]
        assert "artifact.write" not in prompt
        compiled = next(event for event in run["timeline"] if event["event"] == "agent.runtime.compiled")
        assert compiled["allowed_tools"] == []
    finally:
        service.close()


@pytest.mark.asyncio
async def test_run_approval_routes_return_404_and_are_idempotent(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    model_calls = 0

    def fake_chat(*_args, **_kwargs):
        nonlocal model_calls
        model_calls += 1
        return {"content": "Done"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        with pytest.raises(HTTPException) as missing:
            await agent_routes.approve_run_approval("run_missing")
        assert missing.value.status_code == 404

        agent = service.create_agent(
            {
                "name": "Done Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Finish"})
        repeated = await agent_routes.approve_run_approval(run["run_id"])
        assert repeated["run_id"] == run["run_id"]
        assert repeated["status"] == "completed"
        assert model_calls == 1
    finally:
        service.close()


@pytest.mark.asyncio
async def test_run_approval_reject_route_is_idempotent(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)

    def fake_chat(*_args, **_kwargs):
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal_reject",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf should-not-run"}),
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Reject Route Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Request terminal then reject"})
        assert run["status"] == "approval_required"

        first = await agent_routes.reject_run_approval(
            run["run_id"],
            agent_routes.ApprovalRejectRequest(reason="not allowed"),
        )
        second = await agent_routes.reject_run_approval(
            run["run_id"],
            agent_routes.ApprovalRejectRequest(reason="not allowed again"),
        )
        events = service.list_run_events(run["run_id"])["events"]
        rejection_facts = [
            event
            for event in events
            if event["event_type"] == "agent.tool.approval_rejected"
        ]

        assert first["status"] == "cancelled"
        assert second["status"] == "cancelled"
        assert len(rejection_facts) == 1
        assert rejection_facts[0]["payload"]["reason"] == "not allowed"
        assert "should-not-run" in json.dumps(rejection_facts[0]["payload"], ensure_ascii=False)
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_routes_update_then_run_latest_graph(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    responses = iter(["Route design", "Route code"])

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {"content": next(responses)}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        old_agent = service.create_agent({"name": "Route Old", "model_mode": "custom_api", "model_config": model_config})
        design_agent = service.create_agent({"name": "Route Design", "model_mode": "custom_api", "model_config": model_config})
        coding_agent = service.create_agent({"name": "Route Coding", "model_mode": "custom_api", "model_config": model_config})

        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Save And Run",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "old", "type": "agent", "data": {"label": "Route Old", "agent_id": old_agent["agent_id"]}},
                ],
                edges=[{"source": "start", "target": "old"}],
            )
        )
        updated = await agent_routes.update_workflow(
            workflow["workflow_id"],
            agent_routes.WorkflowRequest(
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Route Design", "agent_id": design_agent["agent_id"]}},
                    {"id": "coding", "type": "agent", "data": {"label": "Route Coding", "agent_id": coding_agent["agent_id"]}},
                ],
                edges=[
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "coding"},
                ],
            ),
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(
                workflow_id=updated["workflow_id"],
                user_goal="Run latest route graph",
            )
        )

        assert run["status"] == "completed"
        assert run["result"] == "Route code"
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"] == [
            {"id": "start", "kind": "start", "label": "Start"},
            {"id": "design", "kind": "agent", "label": "Route Design"},
            {"id": "coding", "kind": "agent", "label": "Route Coding"},
        ]
        group = service.get_run_group(run["run_group_id"])
        child_runs = [
            service.get_run(run_id)
            for run_id in group["child_run_ids"]
            if run_id != run["run_id"]
        ]
        assert [child["runnable_id"] for child in child_runs] == [design_agent["agent_id"], coding_agent["agent_id"]]
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_routes_save_and_run_latest_canvas_with_step_approval_and_artifact(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    contexts: list[str] = []

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        contexts.append(messages[-1]["content"])
        return {"content": "Mobile acceptance risks ready"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        old_agent = service.create_agent({"name": "Canvas Old", "model_mode": "custom_api", "model_config": model_config})
        design_agent = service.create_agent({"name": "Canvas Design", "model_mode": "custom_api", "model_config": model_config})

        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Canvas Save And Run",
                nodes=[
                    {"id": "start", "type": "input", "data": {"label": "Start", "kind": "start"}},
                    {
                        "id": "old",
                        "type": "default",
                        "data": {"label": "Old Agent", "kind": "agent", "agent_id": old_agent["agent_id"]},
                    },
                ],
                edges=[{"source": "start", "target": "old"}],
            )
        )
        updated = await agent_routes.update_workflow(
            workflow["workflow_id"],
            agent_routes.WorkflowRequest(
                nodes=[
                    {"id": "start", "type": "input", "data": {"label": "Start", "kind": "start"}},
                    {
                        "id": "design",
                        "type": "default",
                        "data": {
                            "label": "Mobile Design",
                            "kind": "agent",
                            "agent_id": design_agent["agent_id"],
                            "step_task": "List mobile acceptance risks and the checks to verify them.",
                        },
                    },
                    {
                        "id": "gate",
                        "type": "default",
                        "data": {
                            "label": "Review Gate",
                            "kind": "approval",
                            "approval_criteria": "Confirm the mobile risks are specific enough before writing the report.",
                        },
                    },
                    {
                        "id": "report",
                        "type": "output",
                        "data": {
                            "label": "Risk Report",
                            "kind": "artifact",
                            "artifact_path": "reports/mobile-risk.md",
                        },
                    },
                ],
                edges=[
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "gate"},
                    {"source": "gate", "target": "report"},
                ],
            ),
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(
                workflow_id=updated["workflow_id"],
                user_goal="Prepare mobile release acceptance",
            )
        )

        assert run["status"] == "approval_required"
        assert len(contexts) == 1
        assert "# User Goal\nList mobile acceptance risks and the checks to verify them." in contexts[0]
        assert "Workflow Goal:\nPrepare mobile release acceptance" in contexts[0]
        assert "# Upstream Context\nNone" in contexts[0]
        assert "Old Agent" not in contexts[0]
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"] == [
            {"id": "start", "kind": "start", "label": "Start"},
            {
                "id": "design",
                "kind": "agent",
                "label": "Mobile Design",
                "task": "List mobile acceptance risks and the checks to verify them.",
            },
            {
                "id": "gate",
                "kind": "approval",
                "label": "Review Gate",
                "criteria": "Confirm the mobile risks are specific enough before writing the report.",
            },
            {
                "id": "report",
                "kind": "artifact",
                "label": "Risk Report",
                "artifact_path": "reports/mobile-risk.md",
            },
        ]
        assert run["pending_approval"]["input_preview"]["criteria"] == (
            "Confirm the mobile risks are specific enough before writing the report."
        )
        agent_event = next(event for event in run["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "design"
        assert agent_event["workflow_node_task"] == "List mobile acceptance risks and the checks to verify them."
        approval_event = next(event for event in run["timeline"] if event["event"] == "workflow.node.approval_required")
        assert approval_event["workflow_node_id"] == "gate"
        assert approval_event["workflow_node_approval_criteria"] == (
            "Confirm the mobile risks are specific enough before writing the report."
        )
        group = service.get_run_group(run["run_group_id"])
        child_runs = [
            service.get_run(run_id)
            for run_id in group["child_run_ids"]
            if run_id != run["run_id"]
        ]
        assert [child["runnable_id"] for child in child_runs] == [design_agent["agent_id"]]
        assert child_runs[0]["user_goal"] == (
            "List mobile acceptance risks and the checks to verify them.\n\n"
            "Workflow Goal:\n"
            "Prepare mobile release acceptance"
        )

        resumed = await agent_routes.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        artifact_event = next(event for event in resumed["timeline"] if event["event"] == "workflow.node.artifact")
        assert artifact_event["workflow_node_id"] == "report"
        assert artifact_event["artifact"]["path"] == "reports/mobile-risk.md"
        assert service.read_run_artifact(resumed["run_id"], "reports/mobile-risk.md")["content"] == "Mobile acceptance risks ready"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_routes_accept_reactflow_node_types(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {"content": "ReactFlow route done"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({"name": "Route Design", "model_mode": "custom_api", "model_config": model_config})

        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="ReactFlow Raw Types",
                nodes=[
                    {"id": "start", "type": "input", "data": {"label": "Start", "kind": "start"}},
                    {"id": "design", "type": "default", "data": {"label": "Route Design", "kind": "agent", "agent_id": agent["agent_id"]}},
                    {"id": "summary", "type": "output", "data": {"label": "Summary", "kind": "artifact"}},
                ],
                edges=[
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "summary"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(
                workflow_id=workflow["workflow_id"],
                user_goal="Run raw ReactFlow graph",
            )
        )

        assert run["status"] == "completed"
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"] == [
            {"id": "start", "kind": "start", "label": "Start"},
            {"id": "design", "kind": "agent", "label": "Route Design"},
            {"id": "summary", "kind": "artifact", "label": "Summary", "artifact_path": "summary.md"},
        ]
        assert service.read_run_artifact(run["run_id"], "summary.md")["content"] == "ReactFlow route done"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_run_route_rejects_start_only_saved_draft(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    try:
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Draft Only",
                nodes=[{"id": "start", "type": "start", "data": {"label": "Start"}}],
                edges=[],
            )
        )

        with pytest.raises(HTTPException) as invalid:
            await agent_routes.create_workflow_run(
                agent_routes.WorkflowRunRequest(
                    workflow_id=workflow["workflow_id"],
                    user_goal="Run empty draft",
                )
            )

        assert invalid.value.status_code == 400
        assert "至少需要一个可执行节点" in str(invalid.value.detail)
        assert service.list_runs()["runs"] == []
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_approval_route_resumes_runtime_snapshot_after_edit(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        calls.append(messages)
        context = str(messages[1]["content"])
        assert "Name: Original After Approval" in context
        assert "Name: Edited After Approval" not in context
        return {"content": "Original route agent complete"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        original_agent = service.create_agent(
            {"name": "Original After Approval", "model_mode": "custom_api", "model_config": model_config}
        )
        edited_agent = service.create_agent(
            {"name": "Edited After Approval", "model_mode": "custom_api", "model_config": model_config}
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Editable Paused Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "gate", "type": "approval", "data": {"label": "Manual Gate"}},
                    {
                        "id": "after",
                        "type": "agent",
                        "data": {"label": "Original After Approval", "agent_id": original_agent["agent_id"]},
                    },
                ],
                edges=[
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "after"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Wait then run")
        )
        assert run["status"] == "approval_required"

        await agent_routes.update_workflow(
            workflow["workflow_id"],
            agent_routes.WorkflowRequest(
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "gate", "type": "approval", "data": {"label": "Manual Gate"}},
                    {
                        "id": "after",
                        "type": "agent",
                        "data": {"label": "Edited After Approval", "agent_id": edited_agent["agent_id"]},
                    },
                ],
                edges=[
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "after"},
                ],
            ),
        )

        resumed = await agent_routes.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Original route agent complete"
        assert len(calls) == 1
        agent_event = next(event for event in resumed["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "after"
        assert agent_event["workflow_node_label"] == "Original After Approval"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_cancel_route_cancels_child_agent_approval(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf blocked"}),
                    },
                }
            ],
        }

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Route Needs Approval",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Cancel Child Approval Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Route Needs Approval", "agent_id": agent["agent_id"]},
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                edges=[
                    {"source": "start", "target": "agent"},
                    {"source": "agent", "target": "summary"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Run approval flow")
        )
        group = await agent_routes.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        child = await agent_routes.get_any_run(child_run_id)
        assert run["status"] == "approval_required"
        assert child["status"] == "approval_required"

        cancelled_parent = await agent_routes.cancel_run(run["run_id"])
        cancelled_child = await agent_routes.get_any_run(child_run_id)

        assert cancelled_parent["status"] == "cancelled"
        assert cancelled_parent["result"] == "Workflow 已取消：Route Needs Approval"
        assert cancelled_child["status"] == "cancelled"
        assert cancelled_child["pending_approval"] == {}
        assert cancelled_child["result"] == "父 Workflow 已取消"
        cancelled_group = await agent_routes.get_run_group(run["run_group_id"])
        assert cancelled_group["status"] == "cancelled"
        cancelled_event = next(event for event in cancelled_parent["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["workflow_node_id"] == "agent"
        assert cancelled_event["workflow_node_label"] == "Route Needs Approval"
        assert cancelled_event["child_run_id"] == child_run_id
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_child_approval_route_approve_resumes_parent_workflow(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes
    from apps.bridge.routes import runs as run_routes

    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf route-approved"}),
                        },
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "route-approved" in messages[-1]["content"]
        return {"content": "Route child approved result"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr(run_routes, "get_native_run_engine", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Route Approval Child",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Child Approval Resume Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Route Approval Child", "agent_id": agent["agent_id"]},
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                edges=[
                    {"source": "start", "target": "agent"},
                    {"source": "agent", "target": "summary"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Run route approval flow")
        )
        group = await agent_routes.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        child = await agent_routes.get_any_run(child_run_id)

        assert run["status"] == "approval_required"
        assert run["pending_approval"] == {}
        assert child["status"] == "approval_required"
        assert child["pending_approval"]["tool"] == "terminal.run"
        assert child["pending_approval"]["input_preview"]["command"] == "printf route-approved"

        listed = await agent_routes.list_runs(limit=20)
        parent_detail = await agent_routes.get_any_run(run["run_id"])
        child_detail = await agent_routes.get_any_run(child_run_id)
        parent_replay = await run_routes.list_run_events(run["run_id"], after_sequence=0, limit=200)
        child_replay = await run_routes.list_run_events(child_run_id, after_sequence=0, limit=200)
        parent_replay_types = [event["event_type"] for event in parent_replay["events"]]
        child_replay_types = [event["event_type"] for event in child_replay["events"]]

        assert any(item["run_id"] == run["run_id"] for item in listed["runs"])
        assert not any(item["run_id"] == child_run_id for item in listed["runs"])
        assert parent_detail["status"] == "approval_required"
        assert parent_detail["pending_approval"] == {}
        parent_wait_event = next(
            event for event in parent_detail["timeline"]
            if event["event"] == "workflow.run.approval_required"
        )
        assert parent_wait_event["child_run_id"] == child_run_id
        assert parent_wait_event["workflow_node_id"] == "agent"
        assert child_detail["status"] == "approval_required"
        assert child_detail["pending_approval"]["tool"] == "terminal.run"
        replay_agent_before = [
            event for event in parent_replay["events"]
            if event["event_type"] == "workflow.node.agent"
            and event["payload"].get("child_run_id") == child_run_id
        ]
        assert [event["payload"].get("status") for event in replay_agent_before] == ["approval_required"]
        assert replay_agent_before[0]["payload"]["workflow_node_id"] == "agent"
        assert "workflow.run.approval_required" in parent_replay_types
        replay_wait_event = next(
            event for event in parent_replay["events"]
            if event["event_type"] == "workflow.run.approval_required"
        )
        assert replay_wait_event["payload"]["child_run_id"] == child_run_id
        assert replay_wait_event["payload"]["workflow_node_id"] == "agent"
        assert "agent.tool.approval_required" in child_replay_types

        approved_child = await agent_routes.approve_run_approval(child_run_id)
        parent = await agent_routes.get_workflow_run(run["run_id"])
        completed_group = await agent_routes.get_run_group(run["run_group_id"])
        child_detail_after = await agent_routes.get_any_run(child_run_id)
        child_replay_after = await run_routes.list_run_events(child_run_id, after_sequence=0, limit=200)
        parent_replay_after = await run_routes.list_run_events(run["run_id"], after_sequence=0, limit=200)
        child_replay_after_types = [event["event_type"] for event in child_replay_after["events"]]
        parent_replay_after_types = [event["event_type"] for event in parent_replay_after["events"]]

        assert approved_child["status"] == "completed"
        assert approved_child["pending_approval"] == {}
        assert approved_child["result"] == "Route child approved result"
        assert child_detail_after["status"] == "completed"
        assert child_detail_after["pending_approval"] == {}
        assert child_detail_after["result"] == "Route child approved result"
        assert any(event["event"] == "agent.tool.approval_approved" for event in child_detail_after["timeline"])
        assert any(event["event"] == "agent.tool.call" and event["detail"] == "terminal.run" for event in child_detail_after["timeline"])
        assert child_replay_after_types.count("agent.tool.approval_required") == 1
        assert child_replay_after_types.count("agent.tool.approval_approved") == 1
        assert "agent.tool.call" in child_replay_after_types
        assert "agent.run.completed" in child_replay_after_types
        approved_fact = next(
            event for event in child_replay_after["events"]
            if event["event_type"] == "agent.tool.approval_approved"
        )
        tool_fact = next(
            event for event in child_replay_after["events"]
            if event["event_type"] == "agent.tool.call"
            and event["payload"].get("tool") == "terminal.run"
        )
        assert approved_fact["payload"]["tool"] == "terminal.run"
        assert "route-approved" in json.dumps(tool_fact["payload"].get("result", {}), ensure_ascii=False)
        assert parent["status"] == "completed"
        assert parent["result"] == "Route child approved result"
        assert completed_group["status"] == "completed"
        assert any(event["event"] == "workflow.run.child_resumed" for event in parent["timeline"])
        assert any(event["event"] == "workflow.run.resumed" for event in parent["timeline"])
        agent_event = next(event for event in parent["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "agent"
        assert agent_event["workflow_node_label"] == "Route Approval Child"
        assert agent_event["child_run_id"] == child_run_id
        assert agent_event["status"] == "completed"
        artifact_event = next(event for event in parent["timeline"] if event["event"] == "workflow.node.artifact")
        assert artifact_event["workflow_node_id"] == "summary"
        assert artifact_event["status"] == "completed"
        assert artifact_event["artifact"]["path"] == "summary.md"
        assert parent_replay_after_types.count("workflow.run.approval_required") == 1
        assert parent_replay_after_types.count("workflow.run.child_resumed") == 1
        assert parent_replay_after_types.count("workflow.run.resumed") == 1
        assert "workflow.run.completed" in parent_replay_after_types
        replay_agent_after = [
            event for event in parent_replay_after["events"]
            if event["event_type"] == "workflow.node.agent"
            and event["payload"].get("child_run_id") == child_run_id
        ]
        assert [event["payload"].get("status") for event in replay_agent_after] == [
            "approval_required",
            "running",
            "completed",
        ]
        assert replay_agent_after[-1]["payload"]["workflow_node_id"] == "agent"
        assert replay_agent_after[-1]["payload"]["artifact_count"] == 0
        assert replay_agent_after[-1]["payload"]["result"] == "Route child approved result"
        replay_resumed_event = next(
            event for event in parent_replay_after["events"]
            if event["event_type"] == "workflow.run.resumed"
        )
        assert replay_resumed_event["payload"]["child_run_id"] == child_run_id
        assert replay_resumed_event["payload"]["workflow_node_id"] == "agent"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_child_consecutive_approvals_keep_parent_waiting(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_first_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf workflow-first-approved"}),
                        },
                    },
                    {
                        "id": "call_second_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf workflow-second-approved"}),
                        },
                    },
                ],
            }
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert any("workflow-first-approved" in message.get("content", "") for message in tool_messages)
        assert any("workflow-second-approved" in message.get("content", "") for message in tool_messages)
        return {"content": "Workflow child consecutive approvals completed"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Route Consecutive Approval Child",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Child Consecutive Approval Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Route Consecutive Approval Child", "agent_id": agent["agent_id"]},
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                edges=[
                    {"source": "start", "target": "agent"},
                    {"source": "agent", "target": "summary"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Run two child approvals")
        )
        group = await agent_routes.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        child = await agent_routes.get_any_run(child_run_id)

        assert run["status"] == "approval_required"
        assert child["status"] == "approval_required"
        assert child["pending_approval"]["input_preview"]["command"] == "printf workflow-first-approved"

        after_first = await agent_routes.approve_run_approval(child_run_id)
        parent_after_first = await agent_routes.get_workflow_run(run["run_id"])
        group_after_first = await agent_routes.get_run_group(run["run_group_id"])

        assert after_first["status"] == "approval_required"
        assert after_first["pending_approval"]["input_preview"]["command"] == "printf workflow-second-approved"
        assert parent_after_first["status"] == "approval_required"
        assert parent_after_first["pending_approval"] == {}
        assert parent_after_first["result"] == "等待审批：terminal.run"
        assert group_after_first["status"] == "approval_required"
        assert group_after_first["summary"] == "等待审批：terminal.run"
        approval_events = [
            event for event in parent_after_first["timeline"]
            if event["event"] == "workflow.run.approval_required"
        ]
        assert len(approval_events) == 2
        assert approval_events[-1]["child_run_id"] == child_run_id
        assert approval_events[-1]["workflow_node_id"] == "agent"
        assert approval_events[-1]["workflow_node_label"] == "Route Consecutive Approval Child"
        agent_event = next(event for event in parent_after_first["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["status"] == "approval_required"
        assert agent_event["child_run_id"] == child_run_id

        after_second = await agent_routes.approve_run_approval(child_run_id)
        parent_after_second = await agent_routes.get_workflow_run(run["run_id"])
        group_after_second = await agent_routes.get_run_group(run["run_group_id"])

        assert after_second["status"] == "completed"
        assert after_second["pending_approval"] == {}
        assert after_second["result"] == "Workflow child consecutive approvals completed"
        assert parent_after_second["status"] == "completed"
        assert parent_after_second["result"] == "Workflow child consecutive approvals completed"
        assert group_after_second["status"] == "completed"
        completed_agent_event = next(
            event for event in parent_after_second["timeline"] if event["event"] == "workflow.node.agent"
        )
        assert completed_agent_event["status"] == "completed"
        approved_events = [
            event for event in after_second["timeline"] if event["event"] == "agent.tool.approval_approved"
        ]
        assert [event["input_preview"]["command"] for event in approved_events] == [
            "printf workflow-first-approved",
            "printf workflow-second-approved",
        ]
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_child_approval_route_reject_cancels_parent_workflow(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes
    from apps.bridge.routes import runs as run_routes

    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf route-blocked"}),
                    },
                }
            ],
        }

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr(run_routes, "get_native_run_engine", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Route Reject Child",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Child Approval Reject Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Route Reject Child", "agent_id": agent["agent_id"]},
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                edges=[
                    {"source": "start", "target": "agent"},
                    {"source": "agent", "target": "summary"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Run route rejection flow")
        )
        group = await agent_routes.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        child = await agent_routes.get_any_run(child_run_id)

        assert run["status"] == "approval_required"
        assert child["status"] == "approval_required"
        assert child["pending_approval"]["tool"] == "terminal.run"

        rejected_child = await agent_routes.reject_run_approval(
            child_run_id,
            agent_routes.ApprovalRejectRequest(reason="not now"),
        )
        parent = await agent_routes.get_workflow_run(run["run_id"])
        cancelled_group = await agent_routes.get_run_group(run["run_group_id"])
        child_detail_after = await agent_routes.get_any_run(child_run_id)
        child_replay_after = await run_routes.list_run_events(child_run_id, after_sequence=0, limit=200)
        parent_replay = await run_routes.list_run_events(run["run_id"], after_sequence=0, limit=200)
        child_replay_after_types = [event["event_type"] for event in child_replay_after["events"]]

        assert rejected_child["status"] == "cancelled"
        assert rejected_child["pending_approval"] == {}
        assert "not now" in rejected_child["result"]
        assert child_detail_after["status"] == "cancelled"
        assert child_detail_after["pending_approval"] == {}
        assert "not now" in child_detail_after["result"]
        assert any(event["event"] == "agent.tool.approval_rejected" for event in child_detail_after["timeline"])
        assert child_replay_after_types.count("agent.tool.approval_required") == 1
        assert child_replay_after_types.count("agent.tool.approval_rejected") == 1
        assert "agent.run.cancelled" in child_replay_after_types
        rejected_fact = next(
            event for event in child_replay_after["events"]
            if event["event_type"] == "agent.tool.approval_rejected"
        )
        cancelled_fact = next(
            event for event in child_replay_after["events"]
            if event["event_type"] == "agent.run.cancelled"
        )
        assert rejected_fact["payload"]["tool"] == "terminal.run"
        assert rejected_fact["payload"]["reason"] == "not now"
        assert "not now" in cancelled_fact["payload"]["result"]
        assert parent["status"] == "cancelled"
        assert cancelled_group["status"] == "cancelled"
        agent_event = next(event for event in parent["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "agent"
        assert agent_event["workflow_node_kind"] == "agent"
        assert agent_event["workflow_node_label"] == "Route Reject Child"
        assert agent_event["status"] == "cancelled"
        cancelled_event = next(event for event in parent["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["workflow_node_id"] == "agent"
        assert cancelled_event["workflow_node_kind"] == "agent"
        assert cancelled_event["workflow_node_label"] == "Route Reject Child"
        assert cancelled_event["child_run_id"] == child_run_id
        replay_agent_events = [
            event for event in parent_replay["events"]
            if event["event_type"] == "workflow.node.agent"
            and event["payload"].get("child_run_id") == child_run_id
        ]
        assert [event["payload"].get("status") for event in replay_agent_events] == [
            "approval_required",
            "cancelled",
        ]
        replay_cancelled = next(
            event for event in parent_replay["events"]
            if event["event_type"] == "workflow.run.cancelled"
        )
        assert replay_cancelled["payload"]["child_run_id"] == child_run_id
        assert replay_cancelled["payload"]["workflow_node_id"] == "agent"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_child_artifact_route_reads_source_run_artifact(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": json.dumps(
                    {
                        "action": "tool",
                        "tool": "artifact.write",
                        "input": {"path": "design.md", "content": "route design artifact"},
                    }
                )
            }
        if len(calls) == 2:
            assert "Tool result for artifact.write" in messages[-1]["content"]
            return {"content": "Design done"}
        return {"content": "Code done"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        design_agent = service.create_agent(
            {
                "name": "Route Design Artifact Agent",
                "model_mode": "custom_api",
                "model_config": model_config,
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        coding_agent = service.create_agent(
            {"name": "Route Coding Summary Agent", "model_mode": "custom_api", "model_config": model_config}
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Artifact Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Design", "agent_id": design_agent["agent_id"]}},
                    {"id": "code", "type": "agent", "data": {"label": "Code", "agent_id": coding_agent["agent_id"]}},
                ],
                edges=[
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "code"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Ship artifacts")
        )
        parent = await agent_routes.get_workflow_run(run["run_id"])
        design_ref = next(
            artifact
            for artifact in parent["artifacts"]
            if artifact.get("kind") == "workflow_child_artifact" and artifact.get("path") == "design.md"
        )

        artifact = await agent_routes.get_run_artifact(design_ref["source_run_id"], design_ref["path"])

        assert artifact["ok"] is True
        assert artifact["path"] == "design.md"
        assert artifact["content"] == "route design artifact"
        assert design_ref["source_runnable_name"] == "Route Design Artifact Agent"
        assert design_ref["workflow_step_label"] == "Design"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_artifact_review_route_exposes_outputs_and_reruns(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes
    from apps.bridge.routes import runs as run_routes

    service = make_service(tmp_path)
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        calls.append(messages)
        if len(calls) in {1, 4}:
            return {
                "content": json.dumps(
                    {
                        "action": "tool",
                        "tool": "artifact.write",
                        "input": {
                            "path": "design.md",
                            "content": f"design artifact run {1 if len(calls) == 1 else 2}",
                        },
                    }
                )
            }
        if len(calls) in {2, 5}:
            assert "Tool result for artifact.write" in messages[-1]["content"]
            return {"content": f"Design done run {1 if len(calls) == 2 else 2}"}
        return {"content": f"Code final result run {1 if len(calls) == 3 else 2}"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr(run_routes, "get_native_run_engine", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        design_agent = service.create_agent(
            {
                "name": "Route Design Artifact Agent",
                "model_mode": "custom_api",
                "model_config": model_config,
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        coding_agent = service.create_agent(
            {"name": "Route Coding Final Agent", "model_mode": "custom_api", "model_config": model_config}
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Artifact Review Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Design", "agent_id": design_agent["agent_id"]}},
                    {"id": "code", "type": "agent", "data": {"label": "Code", "agent_id": coding_agent["agent_id"]}},
                    {
                        "id": "report",
                        "type": "artifact",
                        "data": {"label": "Final Report", "artifact_path": "reports/final.md"},
                    },
                ],
                edges=[
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "code"},
                    {"source": "code", "target": "report"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Ship artifact review")
        )
        parent = await agent_routes.get_workflow_run(run["run_id"])

        assert parent["status"] == "completed"
        assert parent["result"] == "Code final result run 1"
        assert parent["runnable_id"] == workflow["workflow_id"]
        assert parent["user_goal"] == "Ship artifact review"
        child_ref = next(
            artifact
            for artifact in parent["artifacts"]
            if artifact.get("kind") == "workflow_child_artifact" and artifact.get("path") == "design.md"
        )
        workflow_ref = next(
            artifact
            for artifact in parent["artifacts"]
            if artifact.get("kind") == "workflow_artifact" and artifact.get("path") == "reports/final.md"
        )
        assert child_ref["workflow_step_label"] == "Design"
        assert child_ref["source_runnable_name"] == "Route Design Artifact Agent"
        assert workflow_ref["workflow_node_id"] == "report"
        assert workflow_ref["workflow_node_label"] == "Final Report"

        child_artifact = await agent_routes.get_run_artifact(child_ref["source_run_id"], child_ref["path"])
        workflow_artifact = await agent_routes.get_run_artifact(parent["run_id"], workflow_ref["path"])

        assert child_artifact["content"] == "design artifact run 1"
        assert workflow_artifact["content"] == "Code final result run 1"
        steps = [event for event in parent["timeline"] if str(event.get("event") or "").startswith("workflow.node.")]
        assert [(event["event"], event.get("workflow_node_id"), event.get("status")) for event in steps] == [
            ("workflow.node.start", "start", "completed"),
            ("workflow.node.agent", "design", "completed"),
            ("workflow.node.agent", "code", "completed"),
            ("workflow.node.artifact", "report", "completed"),
        ]
        replay = await run_routes.list_run_events(parent["run_id"], after_sequence=0, limit=200)
        replay_steps = [
            event for event in replay["events"]
            if str(event.get("event_type") or "").startswith("workflow.node.")
        ]
        assert [
            (
                event["event_type"],
                event["payload"].get("workflow_node_id"),
                event["payload"].get("status"),
            )
            for event in replay_steps
        ] == [
            ("workflow.node.start", "start", "completed"),
            ("workflow.node.agent", "design", "completed"),
            ("workflow.node.agent", "code", "completed"),
            ("workflow.node.artifact", "report", "completed"),
        ]
        replay_design = next(
            event for event in replay_steps
            if event["event_type"] == "workflow.node.agent"
            and event["payload"].get("workflow_node_id") == "design"
        )
        replay_artifact = next(
            event for event in replay_steps
            if event["event_type"] == "workflow.node.artifact"
        )
        assert replay_design["payload"]["child_run_id"] == child_ref["source_run_id"]
        assert replay_design["payload"]["artifact_count"] == 1
        assert replay_artifact["payload"]["artifact"]["path"] == "reports/final.md"

        rerun = await agent_routes.rerun_run(parent["run_id"])
        rerun_detail = await agent_routes.get_any_run(rerun["run_id"])
        rerun_replay = await run_routes.list_run_events(rerun["run_id"], after_sequence=0, limit=200)
        rerun_artifact = await agent_routes.get_run_artifact(rerun["run_id"], "reports/final.md")
        rerun_group = service.get_run_group(rerun["run_group_id"])
        rerun_event = rerun["timeline"][0]
        rerun_replay_types = [event["event_type"] for event in rerun_replay["events"]]
        rerun_replay_event = next(
            event for event in rerun_replay["events"]
            if event["event_type"] == "run.rerun.started"
        )

        assert rerun["run_id"] != parent["run_id"]
        assert rerun["status"] == "completed"
        assert rerun["result"] == "Code final result run 2"
        assert rerun["workflow_run_id"] == rerun["run_id"]
        assert rerun_detail["run_id"] == rerun["run_id"]
        assert rerun_detail["status"] == "completed"
        assert rerun_detail["run_group_source"] == "rerun"
        assert rerun_detail["timeline"][0]["event"] == "run.rerun.started"
        assert rerun_group["source"] == "rerun"
        assert rerun_event["event"] == "run.rerun.started"
        assert rerun_event["rerun_of_run_id"] == parent["run_id"]
        assert rerun_event["input_preview"]["original_status"] == "completed"
        assert rerun_event["input_preview"]["original_goal"] == parent["user_goal"]
        assert rerun_replay_types.count("run.rerun.started") == 1
        assert "workflow.node.artifact" in rerun_replay_types
        assert "workflow.run.completed" in rerun_replay_types
        assert rerun_replay_event["payload"]["rerun_of_run_id"] == parent["run_id"]
        assert rerun_replay_event["payload"]["input_preview"]["original_status"] == "completed"
        assert rerun_replay_event["payload"]["input_preview"]["original_goal"] == parent["user_goal"]
        assert rerun_artifact["content"] == "Code final result run 2"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_skill_update_route_toggles_enabled_and_returns_404(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    source = tmp_path / "route-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("# Route Skill\n\nRoute import.", encoding="utf-8")
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    try:
        skill = service.import_skill(str(source))
        updated = await agent_routes.update_skill(
            skill["skill_id"],
            agent_routes.SkillUpdateRequest(enabled=False),
        )
        assert updated["enabled"] is False

        with pytest.raises(HTTPException) as missing:
            await agent_routes.update_skill("missing", agent_routes.SkillUpdateRequest(enabled=True))
        assert missing.value.status_code == 404
    finally:
        service.close()


@pytest.mark.asyncio
async def test_skill_folder_routes_rename_delete_and_validate(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    source = tmp_path / "route-folder-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("# Route Folder Skill\n\nRoute folder.", encoding="utf-8")
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    try:
        folder = await agent_routes.create_skill_folder(agent_routes.SkillFolderRequest(name="Writing"))
        skill = service.import_skill(str(source), folder["folder_id"])

        renamed = await agent_routes.update_skill_folder(
            folder["folder_id"],
            agent_routes.SkillFolderRequest(name="Docs"),
        )
        assert renamed["name"] == "Docs"
        assert service.get_skill(skill["skill_id"])["folder_name"] == "Docs"

        duplicate = await agent_routes.create_skill_folder(agent_routes.SkillFolderRequest(name="Research"))
        with pytest.raises(HTTPException) as duplicate_name:
            await agent_routes.update_skill_folder(
                duplicate["folder_id"],
                agent_routes.SkillFolderRequest(name="docs"),
            )
        assert duplicate_name.value.status_code == 400

        deleted = await agent_routes.delete_skill_folder(folder["folder_id"])
        assert deleted["ok"] is True
        assert service.get_skill(skill["skill_id"])["folder_id"] == ""

        destructive_folder = await agent_routes.create_skill_folder(agent_routes.SkillFolderRequest(name="Temporary"))
        destructive_skill = service.import_skill(str(source), destructive_folder["folder_id"])
        deleted_with_skills = await agent_routes.delete_skill_folder(destructive_folder["folder_id"], delete_skills=True)
        assert deleted_with_skills["ok"] is True
        assert deleted_with_skills["deleted_skill_count"] == 1
        with pytest.raises(KeyError):
            service.get_skill(destructive_skill["skill_id"])

        with pytest.raises(HTTPException) as missing:
            await agent_routes.delete_skill_folder("folder_missing")
        assert missing.value.status_code == 404
    finally:
        service.close()


@pytest.mark.asyncio
async def test_skill_sync_and_install_routes(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    native_home = tmp_path / ".oha-yachiyo" / "skill-library"

    def fake_run(argv, **_kwargs):
        skill_root = Path(_kwargs["cwd"]) / ".skills" / "skills" / "office" / "route-installed"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text("# Route Installed\n\nRoute install.", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="installed", stderr="")

    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / ".oha-yachiyo"))
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.subprocess.run", fake_run)
    try:
        sources = await agent_routes.list_skill_sources()
        assert sources["roots"][0]["path"] == str(native_home / "skills")

        folder = await agent_routes.create_skill_folder(agent_routes.SkillFolderRequest(name="Office"))
        installed = await agent_routes.install_skill(
            agent_routes.SkillInstallRequest(command="skills@latest add owner/repo", folder_id=folder["folder_id"])
        )
        assert installed["ok"] is True
        assert installed["sync"]["summary"]["imported"] == 1
        skills = service.list_skills()["skills"]
        assert skills[0]["folder_id"] == folder["folder_id"]
        assert skills[0]["folder_name"] == "Office"

        synced = await agent_routes.sync_native_skills()
        assert synced["summary"]["skipped"] >= 1
    finally:
        service.close()
