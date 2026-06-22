"""Legacy Studio group persistence adapter tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from apps.shell.yachiyo_agent.legacy_groups import chat_group_snapshot, chat_group_snapshots
from apps.shell.yachiyo_agent.legacy_ports import LegacyStudioPort


def test_legacy_studio_port_persists_groups_in_existing_chat_store(monkeypatch) -> None:
    store = _FakeChatStore()
    runtime = _FakeRuntime()
    monkeypatch.setattr("apps.core.chat_store.get_chat_store", lambda: store)

    port = LegacyStudioPort(runtime)
    saved = port.save_group(
        {
            "name": "Studio Dispatch",
            "description": "Multi-agent review group",
            "mode": "pipeline",
            "moderator_agent_id": "agent-reviewer",
            "default_model": "gpt-review",
            "memory_scope": "hybrid",
            "tool_policy_id": "policy-review",
            "members": [
                {"agent_id": "agent-writer", "role": "writer"},
                {"agent_id": "agent-reviewer", "role": "moderator"},
            ],
        }
    )
    listed = port.list_groups()
    fetched = port.get_group(saved["group_id"])
    stored_participants = json.loads(store.sessions[saved["group_id"]].participants_json)
    stored_config = [
        item for item in stored_participants if item.get("kind") == "group_config"
    ]

    assert saved["group_id"].startswith("agent_group_")
    assert saved["name"] == "Studio Dispatch"
    assert saved["description"] == "Multi-agent review group"
    assert saved["mode"] == "pipeline"
    assert saved["moderator_agent_id"] == "agent-reviewer"
    assert saved["default_model"] == "gpt-review"
    assert saved["memory_scope"] == "hybrid"
    assert saved["tool_policy_id"] == "policy-review"
    assert [item["agent_id"] for item in saved["members"]] == [
        "agent-writer",
        "agent-reviewer",
    ]
    assert [item["role"] for item in saved["members"]] == ["writer", "moderator"]
    assert listed["groups"][0]["group_id"] == saved["group_id"]
    assert listed["groups"][0]["mode"] == "pipeline"
    assert listed["groups"][0]["memory_scope"] == "hybrid"
    assert fetched["members"][1]["name"] == "Reviewer"
    assert fetched["members"][1]["role"] == "moderator"
    assert fetched["tool_policy_id"] == "policy-review"
    assert store.sessions[saved["group_id"]].conversation_kind == "group"
    assert len(stored_config) == 1
    assert stored_config[0]["mode"] == "pipeline"
    assert stored_config[0]["memory_scope"] == "hybrid"


def test_legacy_group_adapters_read_chat_group_snapshots_directly(monkeypatch) -> None:
    store = _FakeChatStore()
    runtime = _FakeRuntime()
    monkeypatch.setattr("apps.core.chat_store.get_chat_store", lambda: store)

    saved = LegacyStudioPort(runtime).save_group(
        {
            "name": "Direct Adapter Group",
            "participant_ids": ["agent-writer"],
        }
    )
    snapshots = chat_group_snapshots(runtime)
    fetched = chat_group_snapshot(saved["group_id"], runtime)

    assert snapshots[0]["group_id"] == saved["group_id"]
    assert snapshots[0]["members"][0]["agent_id"] == "agent-writer"
    assert fetched is not None
    assert fetched["name"] == "Direct Adapter Group"


def test_legacy_studio_port_updates_existing_chat_group_and_starts_member_runs(
    monkeypatch,
) -> None:
    store = _FakeChatStore()
    runtime = _FakeRuntime()
    monkeypatch.setattr("apps.core.chat_store.get_chat_store", lambda: store)
    port = LegacyStudioPort(runtime)

    created = port.save_group(
        {
            "name": "Original",
            "mode": "debate",
            "moderator_agent_id": "agent-writer",
            "memory_scope": "per_agent",
            "tool_policy_id": "policy-original",
            "participant_ids": ["agent-writer"],
        }
    )
    updated = port.save_group(
        {
            "group_id": created["group_id"],
            "name": "Updated Studio Group",
            "members": [{"agent_id": "agent-reviewer"}],
        }
    )
    started = port.start_group_run(
        {
            "group_id": created["group_id"],
            "objective": "Compare the implementation plan",
        }
    )

    assert updated["name"] == "Updated Studio Group"
    assert updated["mode"] == "debate"
    assert updated["moderator_agent_id"] == "agent-reviewer"
    assert updated["memory_scope"] == "per_agent"
    assert updated["tool_policy_id"] == "policy-original"
    assert [item["agent_id"] for item in updated["members"]] == ["agent-reviewer"]
    assert started["group_id"] == created["group_id"]
    assert started["run_group_id"] == "run-group-1"
    assert started["participants"][0]["agent_id"] == "agent-reviewer"
    assert [call[0] for call in runtime.calls].count("create_run_for_runnable_async") == 1
    event_calls = [call for call in runtime.calls if call[0] == "append_run_event"]
    assert event_calls[0][1]["event_type"] == "group.run.started"
    assert event_calls[0][1]["payload"]["group_id"] == created["group_id"]
    assert event_calls[0][1]["payload"]["group_run_id"] == "run-group-1"
    member_started = next(
        call[1] for call in event_calls if call[1]["event_type"] == "group.member.started"
    )
    assert member_started["payload"]["group_id"] == created["group_id"]
    assert member_started["payload"]["agent_id"] == "agent-reviewer"
    assert member_started["payload"]["group_mode"] == "debate"
    assert member_started["payload"]["group_memory_scope"] == "per_agent"
    assert member_started["payload"]["group_moderator_agent_id"] == "agent-reviewer"
    assert member_started["payload"]["group_tool_policy_id"] == "policy-original"

    runtime.complete_run(started["runs"][0]["run_id"], status="completed")
    event_calls = [call for call in runtime.calls if call[0] == "append_run_event"]
    assert event_calls[-1][1]["event_type"] == "group.member.completed"
    assert event_calls[-1][1]["payload"]["agent_id"] == "agent-reviewer"
    assert event_calls[-1][1]["payload"]["group_mode"] == "debate"


def test_legacy_group_run_inherits_builtin_desktop_policy_for_member_runs(
    monkeypatch,
) -> None:
    store = _FakeChatStore()
    runtime = _FakeRuntime()
    monkeypatch.setattr("apps.core.chat_store.get_chat_store", lambda: store)
    port = LegacyStudioPort(runtime)

    group = port.save_group(
        {
            "name": "Desktop Team",
            "tool_policy_id": "desktop_execution",
            "participant_ids": ["agent-reviewer"],
        }
    )
    started = port.start_group_run(
        {
            "group_id": group["group_id"],
            "objective": "Read the screen and open Music",
        }
    )
    create_call = next(
        call[1]
        for call in runtime.calls
        if call[0] == "create_run_for_runnable_async"
    )
    member_started = next(
        call[1]
        for call in runtime.calls
        if call[0] == "append_run_event"
        and call[1]["event_type"] == "group.member.started"
    )

    inherited_policy = create_call["agent_override"]["tool_policy"]
    allowed_tools = inherited_policy["allowed_tools"]
    assert create_call["agent_override"]["agent_id"] == "agent-reviewer"
    assert create_call["agent_override"]["inherited_tool_policy_id"] == "desktop_execution"
    assert "workspace.read" in allowed_tools
    assert "screen.capture" in allowed_tools
    assert "media.apple_music_play" in allowed_tools
    assert "desktop.type_text" in allowed_tools
    assert "desktop.click" in allowed_tools
    assert "browser.click" in allowed_tools
    assert "terminal.run" not in allowed_tools
    assert started["participants"][0]["inherited_tool_policy_id"] == "desktop_execution"
    assert member_started["payload"]["inherited_tool_policy_id"] == "desktop_execution"
    assert member_started["payload"]["member_allowed_tools"] == allowed_tools
    assert runtime.private_agents["agent-reviewer"]["tool_policy"]["allowed_tools"] == [
        "workspace.read",
    ]


def test_legacy_group_run_keeps_unknown_group_policy_id_as_metadata_only(
    monkeypatch,
) -> None:
    store = _FakeChatStore()
    runtime = _FakeRuntime()
    monkeypatch.setattr("apps.core.chat_store.get_chat_store", lambda: store)
    port = LegacyStudioPort(runtime)

    group = port.save_group(
        {
            "name": "Metadata Policy Team",
            "tool_policy_id": "policy-review",
            "participant_ids": ["agent-reviewer"],
        }
    )
    port.start_group_run(
        {
            "group_id": group["group_id"],
            "objective": "Review the plan",
        }
    )
    create_call = next(
        call[1]
        for call in runtime.calls
        if call[0] == "create_run_for_runnable_async"
    )
    member_started = next(
        call[1]
        for call in runtime.calls
        if call[0] == "append_run_event"
        and call[1]["event_type"] == "group.member.started"
    )

    assert "agent_override" not in create_call
    assert member_started["payload"]["group_tool_policy_id"] == "policy-review"
    assert "member_allowed_tools" not in member_started["payload"]


def test_legacy_group_run_fallback_records_mode_specific_orchestration(
    monkeypatch,
) -> None:
    store = _FakeChatStore()
    runtime = _FakeRuntime()
    monkeypatch.setattr("apps.core.chat_store.get_chat_store", lambda: store)
    port = LegacyStudioPort(runtime)

    debate_group = port.save_group(
        {
            "name": "Debate Team",
            "mode": "debate",
            "moderator_agent_id": "agent-writer",
            "members": [
                {"agent_id": "agent-writer", "role": "moderator", "sort_order": 0},
                {"agent_id": "agent-reviewer", "role": "critic", "sort_order": 1},
            ],
        }
    )
    debate_run = port.start_group_run(
        {
            "group_id": debate_group["group_id"],
            "objective": "Debate the plan",
        }
    )
    create_calls = [
        call[1]
        for call in runtime.calls
        if call[0] == "create_run_for_runnable_async"
    ]
    event_calls = [call for call in runtime.calls if call[0] == "append_run_event"]
    plan_event = next(call for call in event_calls if call[1]["event_type"] == "group.run.plan")
    member_events = [
        call[1]["payload"]
        for call in event_calls
        if call[1]["event_type"] == "group.member.started"
    ]

    assert [call["runnable_id"] for call in create_calls] == [
        "agent-reviewer",
        "agent-writer",
    ]
    assert [member["agent_id"] for member in debate_run["participants"]] == [
        "agent-reviewer",
        "agent-writer",
    ]
    assert debate_run["active_speaker_agent_id"] == "agent-reviewer"
    assert plan_event[1]["payload"]["group_execution_mode"] == "debate"
    assert plan_event[1]["payload"]["group_execution_strategy"] == "participants_then_moderator"
    assert plan_event[1]["payload"]["group_member_order"] == [
        "agent-reviewer",
        "agent-writer",
    ]
    assert member_events[0]["group_member_phase"] == "debate_argument"
    assert member_events[0]["group_member_turn"] == 1
    assert member_events[0]["group_member_is_moderator"] is False
    assert member_events[1]["group_member_phase"] == "moderator_summary"
    assert member_events[1]["group_member_turn"] == 2
    assert member_events[1]["group_member_is_moderator"] is True

    runtime.calls.clear()
    parallel_group = port.save_group(
        {
            "name": "Parallel Team",
            "mode": "parallel",
            "members": [
                {"agent_id": "agent-writer", "role": "writer", "sort_order": 0},
                {"agent_id": "agent-reviewer", "role": "reviewer", "sort_order": 1},
            ],
        }
    )
    port.start_group_run(
        {
            "group_id": parallel_group["group_id"],
            "objective": "Fan out the plan",
        }
    )
    event_calls = [call for call in runtime.calls if call[0] == "append_run_event"]
    plan_event = next(call for call in event_calls if call[1]["event_type"] == "group.run.plan")
    member_events = [
        call[1]["payload"]
        for call in event_calls
        if call[1]["event_type"] == "group.member.started"
    ]

    assert plan_event[1]["payload"]["group_execution_mode"] == "parallel"
    assert plan_event[1]["payload"]["group_execution_strategy"] == "fan_out"
    assert plan_event[1]["payload"]["group_parallel"] is True
    assert [payload["group_member_phase"] for payload in member_events] == [
        "parallel_branch",
        "parallel_branch",
    ]
    assert {payload["group_member_parallel"] for payload in member_events} == {True}


class _FakeChatStore:
    def __init__(self) -> None:
        self.sessions: dict[str, SimpleNamespace] = {}

    def create_session(self, session_id: str, title: str = "") -> None:
        self.sessions.setdefault(
            session_id,
            SimpleNamespace(
                session_id=session_id,
                title=title,
                created_at="2026-06-14T00:00:00Z",
                message_count=0,
                execution_session_id=None,
                conversation_kind="main",
                runnable_id="",
                runnable_name="",
                run_group_id="",
                participants_json="[]",
                avatar_url="",
            ),
        )

    def list_sessions(self, limit: int = 20) -> list[SimpleNamespace]:
        return [
            session
            for session in self.sessions.values()
            if session.conversation_kind == "group"
        ][:limit]

    def get_session(self, session_id: str) -> SimpleNamespace | None:
        return self.sessions.get(session_id)

    def update_session_title(self, session_id: str, title: str) -> None:
        self.sessions[session_id].title = title

    def update_session_context(self, session_id: str, **context: Any) -> None:
        for key, value in context.items():
            setattr(self.sessions[session_id], key, value)


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.completion_callbacks: dict[str, Any] = {}
        self.runnables = {
            "agent-writer": {
                "kind": "agent",
                "id": "agent-writer",
                "name": "Writer",
                "nickname": "Writer",
                "enabled": True,
            },
            "agent-reviewer": {
                "kind": "agent",
                "id": "agent-reviewer",
                "name": "Reviewer",
                "enabled": True,
            },
        }
        self.private_agents = {
            agent_id: {
                "agent_id": agent_id,
                "kind": "agent",
                "name": str(agent.get("name") or agent_id),
                "enabled": True,
                "model_mode": "profile",
                "execution_backend": "native_profile",
                "tool_policy": {
                    "allowed_tools": ["workspace.read"],
                    "approval_required": {},
                },
                "workspace_policy": {},
                "skill_ids": [],
            }
            for agent_id, agent in self.runnables.items()
        }

    def resolve_runnable(self, *, runnable_id: str) -> dict[str, Any]:
        self.calls.append(("resolve_runnable", runnable_id))
        return self.runnables[runnable_id]

    def _get_agent_private(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("_get_agent_private", agent_id))
        return dict(self.private_agents[agent_id])

    def create_run_for_runnable_async(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(("create_run_for_runnable_async", payload))
        run_group_id = payload.get("run_group_id") or "run-group-1"
        run_id = f"run-{len(self.calls)}"
        if callable(payload.get("on_complete")):
            self.completion_callbacks[run_id] = payload["on_complete"]
        return {
            "run_id": run_id,
            "run_group_id": run_group_id,
            "runnable_id": payload["runnable_id"],
            "runnable_name": self.runnables[payload["runnable_id"]]["name"],
            "user_goal": payload["user_goal"],
            "status": "running",
            "timeline": [],
            "artifacts": [],
        }

    def complete_run(self, run_id: str, *, status: str = "completed") -> None:
        callback = self.completion_callbacks[run_id]
        callback(
            {
                "run_id": run_id,
                "run_group_id": "run-group-1",
                "runnable_id": "agent-reviewer",
                "runnable_name": "Reviewer",
                "status": status,
            }
        )

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_group", run_group_id))
        return {
            "run_group_id": run_group_id,
            "title": "Group run",
            "source": "delegation",
            "status": "running",
            "child_run_ids": ["run-1"],
            "created_at": "2026-06-14T00:00:00Z",
            "updated_at": "2026-06-14T00:00:01Z",
        }

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "append_run_event",
                {
                    "run_id": run_id,
                    "event_type": event_type,
                    "payload": payload,
                },
            )
        )
        return {"event_type": event_type, "run_id": run_id, "payload": payload}
