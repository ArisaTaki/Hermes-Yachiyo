"""Agent Desk local store tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.yachiyo_agent.desk import (
    DESK_METADATA_PATH,
    DESK_NOTES_PATH,
    LocalAgentDeskStore,
    agent_desk_snapshot_from_payload,
)


class _FakeRuntime:
    def __init__(self, root: Path) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.agent_workspaces_dir = root / "workspaces"
        self.agent_root = root / "planner-desk"

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("get_agent", agent_id))
        return {
            "agent_id": agent_id,
            "name": "Planner",
            "workspace_policy": {"default_workdir": str(self.agent_root)},
        }

    def schedule_future_task(
        self,
        payload: dict[str, Any],
        *,
        source_run_id: str = "",
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "schedule_future_task",
                {"payload": payload, "source_run_id": source_run_id},
            )
        )
        return {
            "ok": True,
            "future_task": {
                "future_task_id": "future-desk-1",
                "title": payload["title"],
                "prompt": payload["prompt"],
                "runnable_id": payload["runnable_id"],
                "status": "scheduled",
                "scheduled_at_epoch": 1781433600.0,
                "source_run_id": source_run_id,
                "created_at": "2026-06-22T00:00:00Z",
                "updated_at": "2026-06-22T00:00:01Z",
            },
        }


def test_local_agent_desk_store_writes_notes_files_and_metadata(tmp_path: Path) -> None:
    runtime = _FakeRuntime(tmp_path)
    store = LocalAgentDeskStore(runtime=runtime)

    note_snapshot = store.write_agent_desk_note("agent-1", "# Desk Notes")
    file_snapshot = store.write_agent_desk_file("agent-1", "inputs/brief.md", "Brief body")
    desk = agent_desk_snapshot_from_payload(file_snapshot)

    assert (runtime.agent_root / DESK_NOTES_PATH).read_text(encoding="utf-8") == "# Desk Notes"
    assert (runtime.agent_root / "inputs" / "brief.md").read_text(encoding="utf-8") == "Brief body"
    metadata = json.loads((runtime.agent_root / DESK_METADATA_PATH).read_text(encoding="utf-8"))
    assert metadata["schema_version"] == 1
    assert metadata["agent_id"] == "agent-1"
    assert {item.path for item in desk.items} >= {
        DESK_NOTES_PATH,
        "inputs",
        "inputs/brief.md",
    }
    notes = next(item for item in desk.items if item.path == DESK_NOTES_PATH)
    brief = next(item for item in desk.items if item.path == "inputs/brief.md")
    assert notes.kind == "note"
    assert notes.preview_text == "# Desk Notes"
    assert brief.kind == "file"
    assert brief.preview_text == "Brief body"
    assert desk.root_path == str(runtime.agent_root)
    assert note_snapshot["agent_id"] == "agent-1"
    assert ("get_agent", "agent-1") in runtime.calls


def test_local_agent_desk_store_rejects_unsafe_file_paths(tmp_path: Path) -> None:
    store = LocalAgentDeskStore(runtime=_FakeRuntime(tmp_path))

    for path in ("", "/tmp/secret.md", "../secret.md", "safe/../secret.md", "."):
        with pytest.raises(AgentRuntimeError):
            store.write_agent_desk_file("agent-1", path, "secret")


def test_local_agent_desk_store_schedules_low_risk_file_event_task(tmp_path: Path) -> None:
    runtime = _FakeRuntime(tmp_path)
    store = LocalAgentDeskStore(runtime=runtime)

    result = store.trigger_agent_desk_file_event(
        "agent-1",
        {"path": "inputs/brief.md", "event_type": "modified", "delay_seconds": 0},
    )

    assert result["future_task"]["future_task_id"] == "future-desk-1"
    assert result["future_task"]["title"] == "Review Agent Desk file: inputs/brief.md"
    assert result["future_task"]["runnable_id"] == "agent-1"
    assert (
        "schedule_future_task",
        {
            "payload": {
                "title": "Review Agent Desk file: inputs/brief.md",
                "prompt": (
                    "Agent Desk file event for agent-1: modified inputs/brief.md\n\n"
                    "Review the Agent Desk notes and file list, then decide whether "
                    "a short follow-up is useful. Use read-only tools first. Do not "
                    "modify files, send messages, or run terminal commands unless "
                    "the user explicitly asks and approval policy allows it."
                ),
                "runnable_id": "agent-1",
                "delay_seconds": 0,
            },
            "source_run_id": "agent_desk_file_event",
        },
    ) in runtime.calls


def test_local_agent_desk_store_rejects_unsafe_file_event_paths(tmp_path: Path) -> None:
    store = LocalAgentDeskStore(runtime=_FakeRuntime(tmp_path))

    with pytest.raises(AgentRuntimeError):
        store.trigger_agent_desk_file_event("agent-1", {"path": "../secret.md"})


def test_local_agent_desk_store_uses_sanitized_default_workspace(tmp_path: Path) -> None:
    class _RuntimeWithoutPolicy:
        agent_workspaces_dir = tmp_path / "workspaces"

        def get_agent(self, agent_id: str) -> dict[str, Any]:
            return {"agent_id": agent_id, "name": "Desk Agent"}

    store = LocalAgentDeskStore(runtime=_RuntimeWithoutPolicy())

    desk = store.write_agent_desk_note("agent with spaces/and/slash", "note")

    root_path = Path(desk["root_path"])
    assert root_path.parent == tmp_path / "workspaces"
    assert " " not in root_path.name
    assert "/" not in root_path.name
    assert (root_path / DESK_NOTES_PATH).exists()
