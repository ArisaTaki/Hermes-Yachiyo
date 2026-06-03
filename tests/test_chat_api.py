"""ChatAPI 测试 — 消息发送与任务状态同步"""

import base64
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from apps.core.activity_store import ActivityStore
from apps.core.chat_session import ChatMessage, ChatSession, MessageRole, MessageStatus
from apps.core.chat_store import ChatStore, StoredMessage
import apps.core.chat_store as _store_mod
from apps.core.special_sessions import PROACTIVE_CHAT_SESSION_ID
from apps.core.state import AppState
import apps.shell.chat_api as chat_api_mod
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.chat_api import ChatAPI
from packages.protocol.enums import TaskStatus


class _RuntimeStub:
    def __init__(self, store: ChatStore) -> None:
        self.store = store
        self.state = AppState()
        self.chat_session = ChatSession(session_id="s1")
        self.chat_session.attach_store(store, load_existing=False)
        self.cancelled_runner_tasks: list[str] = []

    def cancel_task_runner_task(self, task_id: str) -> bool:
        self.cancelled_runner_tasks.append(task_id)
        return True

    def switch_session(self, session_id: str) -> None:
        self.chat_session = ChatSession(session_id=session_id)
        self.chat_session.attach_store(
            self.store,
            load_existing=True,
            fail_active_messages=False,
        )

    def start_new_session(self) -> str:
        self.chat_session = ChatSession()
        self.chat_session.attach_store(self.store, load_existing=False)
        return self.chat_session.session_id


def _make_api(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    return ChatAPI(runtime), runtime, store


def _wait_for_agent_run(service: AgentRuntimeService, run_id: str, timeout: float = 5.0) -> dict:
    """等待 Agent Run 异步执行完成"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = service.get_run(run_id)
        if run["status"] in ("completed", "failed", "approval_required"):
            return run
        time.sleep(0.1)
    raise TimeoutError(f"Agent Run {run_id} 未在 {timeout} 秒内完成")


def _wait_for_assistant_content(runtime: _RuntimeStub, content: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if any(
            message.role == MessageRole.ASSISTANT and message.content == content
            for message in runtime.chat_session.get_messages()
        ):
            return
        time.sleep(0.05)
    raise TimeoutError(f"Assistant message {content!r} 未在 {timeout} 秒内写入")


def _chat_message(
    message_id: str,
    role: MessageRole,
    content: str = "",
    task_id: str | None = None,
    status: MessageStatus = MessageStatus.COMPLETED,
) -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        role=role,
        content=content,
        status=status,
        created_at=datetime.now(timezone.utc),
        task_id=task_id,
    )


def test_send_message_creates_task_and_links_user_message(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("  你好  ")

        assert result["ok"] is True
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.description == "你好"
        assert task.chat_session_id == runtime.chat_session.session_id

        user = runtime.chat_session.get_messages()[0]
        assert user.role == MessageRole.USER
        assert user.content == "你好"
        assert user.task_id == task.task_id
        assert user.status == MessageStatus.PENDING
        assert api.get_session_info()["is_processing"] is True
    finally:
        store.close()


def test_send_message_rejects_when_hermes_unavailable(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    runtime.task_runner = SimpleNamespace(
        executor=SimpleNamespace(
            name="HermesUnavailableExecutor",
            reason="Hermes Agent 当前不可用",
        )
    )
    try:
        result = api.send_message("你好")

        assert result == {"ok": False, "error": "Hermes Agent 当前不可用"}
        assert runtime.state.list_tasks() == []
        assert runtime.chat_session.get_messages() == []
    finally:
        store.close()


def test_agent_mention_creates_agent_run_without_general_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        seed_templates=False,
    )
    agent = service.create_agent(
        {
            "name": "Helper",
            "description": "test helper",
            "instructions": "Summarize requests.",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Agent result"})
    try:
        result = api.send_message("@Helper 做个总结")
        assert result["ok"] is True
        assert result["runnable_command"] is True
        assert result["agent_run_id"]
        assert result["run_group_id"]
        assert result["status"] == "processing"  # 异步执行，立即返回 processing
        assert runtime.state.list_tasks() == []

        # 等待异步执行完成
        run = _wait_for_agent_run(service, result["agent_run_id"])
        assert run["status"] == "completed"
        assert run["run_group_id"] == result["run_group_id"]
        assert run["runnable_id"] == agent["agent_id"]
        _wait_for_assistant_content(runtime, "Agent result")
        messages = runtime.chat_session.get_messages()
        assert messages[0].status == MessageStatus.COMPLETED
        assert messages[1].role == MessageRole.ASSISTANT
        assert messages[1].content == "Agent result"
        assert messages[1].metadata["sender"]["name"] == "Helper"
        stored = store.get_session(runtime.chat_session.session_id)
        assert stored is not None
        assert stored.conversation_kind == "agent"
        assert stored.runnable_id == agent["agent_id"]
        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == runtime.chat_session.session_id)
        assert current["conversation_kind"] == "agent"
        assert current["runnable_name"] == "Helper"
        assert current["participants"][0]["name"] == "Helper"
    finally:
        service.close()
        store.close()


def test_agent_scoped_session_continues_without_new_mention(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        seed_templates=False,
    )
    agent = service.create_agent(
        {
            "name": "Helper",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
    responses = iter(["First agent result", "Second agent result"])
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {"content": next(responses)},
    )
    try:
        first = api.send_message("@Helper 第一轮")
        # 等待第一个 Agent Run 完成
        _wait_for_agent_run(service, first["agent_run_id"])
        _wait_for_assistant_content(runtime, "First agent result")

        second = api.send_message("继续处理")
        # 等待第二个 Agent Run 完成
        _wait_for_agent_run(service, second["agent_run_id"])
        _wait_for_assistant_content(runtime, "Second agent result")

        assert first["ok"] is True
        assert second["ok"] is True
        assert second["runnable_command"] is True
        assert runtime.state.list_tasks() == []
        assert second["run_group_id"] == first["run_group_id"]
        second_run = service.get_run(second["agent_run_id"])
        assert second_run["runnable_id"] == agent["agent_id"]
        assert second_run["run_group_id"] == first["run_group_id"]
        messages = api.get_messages()["messages"]
        assert [message["content"] for message in messages if message["role"] == "assistant"] == [
            "First agent result",
            "Second agent result",
        ]
        assert messages[-1]["metadata"]["sender"]["name"] == "Helper"
    finally:
        service.close()
        store.close()


def test_workflow_mention_creates_group_with_agent_reports_and_intervention(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        seed_templates=False,
    )
    responses = iter(["Design output", "Code output", "Design intervention"])

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {"content": next(responses)}

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
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
            "model_mode": "custom_api",
            "model_config": model_config,
        })
        workflow = service.create_workflow(
            {
                "name": "Web Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Design", "agent_id": design["agent_id"]}},
                    {"id": "coding", "type": "agent", "data": {"label": "Coding", "agent_id": coding["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "coding"},
                ],
            }
        )

        workflow_result = api.send_message("@Web Flow 做一个网页设计链路")

        assert workflow_result["ok"] is True
        assert workflow_result["workflow_run_id"]
        assert workflow_result["run_group_id"]
        messages = api.get_messages()["messages"]
        assistant_messages = [message for message in messages if message["role"] == "assistant"]
        assert [message["content"] for message in assistant_messages] == [
            "Design output",
            "Code output",
            "Web Flow 已完成。",
        ]
        assert [message["metadata"]["sender"]["name"] for message in assistant_messages] == [
            "Design Agent",
            "Coding Agent",
            "Web Flow",
        ]
        current = next(
            item for item in api.list_sessions()["sessions"]
            if item["session_id"] == runtime.chat_session.session_id
        )
        assert current["conversation_kind"] == "workflow"
        assert current["runnable_id"] == workflow["workflow_id"]
        assert current["run_group_id"] == workflow_result["run_group_id"]
        assert [participant["name"] for participant in current["participants"]] == [
            "Design Agent",
            "Coding Agent",
        ]
        listed_ids = {run["run_id"] for run in service.list_runs(limit=20)["runs"]}
        group = service.get_run_group(workflow_result["run_group_id"])
        child_ids = [run_id for run_id in group["child_run_ids"] if run_id != workflow_result["workflow_run_id"]]
        assert workflow_result["workflow_run_id"] in listed_ids
        assert not any(run_id in listed_ids for run_id in child_ids)

        intervention = api.send_message("@Design 再收紧一下视觉方向")

        assert intervention["ok"] is True
        assert intervention["agent_run_id"]
        assert intervention["run_group_id"] == workflow_result["run_group_id"]
        # 等待异步执行完成
        _wait_for_agent_run(service, intervention["agent_run_id"])
        _wait_for_assistant_content(runtime, "Design intervention")
        intervention_run = service.get_run(intervention["agent_run_id"])
        assert intervention_run["runnable_id"] == design["agent_id"]
        assert intervention_run["run_group_id"] == workflow_result["run_group_id"]
        after = api.get_messages()["messages"]
        assert after[-1]["content"] == "Design intervention"
        assert after[-1]["metadata"]["sender"]["name"] == "Design Agent"
        stored = store.get_session(runtime.chat_session.session_id)
        assert stored is not None
        assert stored.conversation_kind == "workflow"

        main = api.send_message("@主模型 总结一下当前工作流状态")
        assert main["ok"] is True
        assert "runnable_command" not in main
        task = runtime.state.get_task(main["task_id"])
        assert task is not None
        assert task.chat_session_id == runtime.chat_session.session_id
        stored = store.get_session(runtime.chat_session.session_id)
        assert stored is not None
        assert stored.conversation_kind == "workflow"
    finally:
        service.close()
        store.close()


def test_get_messages_limit_zero_returns_complete_current_session(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        for index in range(90):
            runtime.chat_session.add_system_message(f"系统消息 {index}")

        messages = api.get_messages(limit=0)["messages"]

        assert len(messages) == 90
        assert messages[0]["content"] == "系统消息 0"
        assert messages[-1]["content"] == "系统消息 89"
    finally:
        store.close()


def test_selected_runnable_creates_agent_run_without_mention(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        seed_templates=False,
    )
    agent = service.create_agent(
        {
            "name": "Draft Agent",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Agent result"})
    try:
        result = api.send_message("整理需求", runnable_id=agent["agent_id"])
        assert result["ok"] is True
        assert result["runnable_command"] is True
        assert result["agent_run_id"]
        _wait_for_agent_run(service, result["agent_run_id"])
        _wait_for_assistant_content(runtime, "Agent result")
        assert runtime.state.list_tasks() == []
        session = store.get_session(runtime.chat_session.session_id)
        assert session is not None
        assert session.conversation_kind == "agent"
        assert session.runnable_id == agent["agent_id"]
    finally:
        service.close()
        store.close()


def test_agent_mention_session_title_uses_goal_without_mention(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    agent = {
        "id": "agent_draft",
        "name": "Draft Agent",
        "nickname": "Draft Agent",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def list_runnables(self):
            return {"runnables": [agent]}

        def parse_known_chat_runnable(self, _text):
            return "Draft Agent", "整理需求"

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == agent["id"] or name == agent["name"] or name == agent["nickname"]:
                return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            run = {
                "run_id": "agent_run_fake",
                "run_group_id": run_group_id or "run_group_fake",
                "status": "processing",
                "result": "",
                "runnable": agent,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": "Agent result",
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        result = api.send_message("@Draft Agent 整理需求")
        assert result["ok"] is True
        _wait_for_assistant_content(runtime, "Agent result")

        stored = store.get_session(runtime.chat_session.session_id)
        assert stored is not None
        assert stored.title == "整理需求"
        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert current["title"] == "整理需求"
        assert stored.runnable_id == agent["id"]
    finally:
        store.close()


def test_manual_group_session_keeps_context_for_agent_mentions(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "Code",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def __init__(self):
            self.responses = {
                design["id"]: "Design result",
                coding["id"]: "Code result",
            }

        def list_runnables(self):
            return {"runnables": [design, coding]}

        def parse_known_chat_runnable(self, text):
            if "@Design" in text:
                return "Design", "做一版视觉方向"
            if "@Code" in text:
                return "Code", "实现它"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            for agent in (design, coding):
                if runnable_id == agent["id"] or name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            runnable = self.resolve_runnable(runnable_id=runnable_id, name=name)
            run = {
                "run_id": f"{runnable_id}_run",
                "run_group_id": run_group_id or "run_group_manual",
                "status": "processing",
                "result": "",
                "runnable": runnable,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": self.responses.get(runnable_id, "Agent result"),
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(
            name="demo Channel",
            participant_ids=[design["id"], coding["id"]],
        )
        assert created["ok"] is True
        assert created["session_context"]["conversation_kind"] == "group"
        assert [item["kind"] for item in created["session_context"]["participants"]] == ["main", "agent", "agent"]

        first = api.send_message("@Design 做一版视觉方向")
        assert first["ok"] is True
        assert first["agent_run_id"]
        _wait_for_assistant_content(
            runtime,
            "Design 已完成任务，请主模型和用户验收。\n"
            "任务：做一版视觉方向\n\n"
            "Design result",
        )

        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert current["conversation_kind"] == "group"
        assert current["runnable_name"] == "demo Channel"
        assert current["run_group_id"] == first["run_group_id"]

        second = api.send_message("@Code 实现它")
        assert second["ok"] is True
        assert second["agent_run_id"]
        assert second["run_group_id"] == first["run_group_id"]
        _wait_for_assistant_content(
            runtime,
            "Code 已完成任务，请主模型和用户验收。\n"
            "任务：实现它\n\n"
            "Code result",
        )
        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert [item["name"] for item in current["participants"] if item["kind"] == "agent"] == [
            "Design Agent",
            "Coding Agent",
        ]

        main = api.send_message("@主模型 总结一下群组状态")
        assert main["ok"] is True
        assert "runnable_command" not in main
        task = runtime.state.get_task(main["task_id"])
        assert task is not None
        assert task.description.startswith("总结一下群组状态")
        assert "[Yachiyo 群组上下文]" in task.description
        assert "- 月見八千代（主模型" in task.description
        assert "- Design（Agent；Design Agent）" in task.description
        assert "- Code（Agent；Coding Agent）" in task.description
        assert "<yachiyo_group_dispatch>" in task.description
        assert '"action":"dispatch_group_agent"' in task.description
        assert "完整、可执行、不可省略的任务说明" in task.description
        stored = store.get_session(runtime.chat_session.session_id)
        assert stored is not None
        assert stored.conversation_kind == "group"
    finally:
        store.close()


def test_manual_group_agent_mention_rejects_non_member(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "Code",
        "kind": "agent",
        "enabled": True,
    }
    calls: list[dict] = []

    class FakeRunnableService:
        def parse_known_chat_runnable(self, text):
            if "@Code" in text:
                return "Code", "实现它"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            for agent in (design, coding):
                if runnable_id == agent["id"] or name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, **kwargs):
            calls.append(kwargs)
            return {"run_id": "unexpected", "run_group_id": "", "status": "processing", "runnable": coding}

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        result = api.send_message("@Code 实现它")

        assert result["ok"] is True
        assert result["error"] == "Code 不在当前群组中。请先在群组设置中加入后再 @。"
        assert calls == []
        messages = api.get_messages()["messages"]
        assistant = [message for message in messages if message["role"] == "assistant"][-1]
        assert assistant["content"] == "Code 不在当前群组中。请先在群组设置中加入后再 @。"
        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert [item["name"] for item in current["participants"] if item["kind"] == "agent"] == ["Design Agent"]
    finally:
        store.close()


def test_manual_group_plain_message_routes_to_main_model(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def parse_known_chat_runnable(self, text):
            raise AssertionError(f"plain group message should not parse runnable mention: {text}")

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        result = api.send_message("总结一下现在的方案")

        assert result["ok"] is True
        assert "runnable_command" not in result
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.description.startswith("总结一下现在的方案")
        assert "[Yachiyo 群组上下文]" in task.description
        assert "当用户没有 @ 指定其他成员时" in task.description
        assert "- Design（Agent；Design Agent）" in task.description
    finally:
        store.close()


def test_create_group_session_default_name_uses_main_and_agent_nicknames(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    runtime.config = SimpleNamespace(
        assistant=SimpleNamespace(
            agent_name="月見八千代",
            agent_nickname="月夜",
            agent_avatar_path="",
        )
    )
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "Code",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            for agent in (design, coding):
                if runnable_id == agent["id"] or name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        avatar_url = "data:image/png;base64," + ("a" * 1200)
        created = api.create_group_session(
            avatar_url=avatar_url,
            participant_ids=[design["id"], coding["id"]],
        )

        assert created["ok"] is True
        assert created["session_context"]["runnable_name"] == "月夜、Design、Code"
        assert created["session_context"]["avatar_url"] == avatar_url
        assert [item["nickname"] for item in created["session_context"]["participants"]] == [
            "月夜",
            "Design",
            "Code",
        ]
        stored = store.get_session(created["session_id"])
        assert stored is not None
        assert stored.title == "月夜、Design、Code"
        assert stored.runnable_name == "月夜、Design、Code"
        assert stored.avatar_url == avatar_url
    finally:
        store.close()


def test_manual_group_agent_mention_posts_visible_progress(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    calls: list[dict] = []

    class FakeRunnableService:
        def parse_known_chat_runnable(self, text):
            if "@Design" in text:
                return "Design", "做一版视觉方向"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            calls.append({
                "runnable_id": runnable_id,
                "user_goal": user_goal,
                "upstream": upstream,
            })
            return {
                "run_id": "design_run_processing",
                "run_group_id": run_group_id or "run_group_manual",
                "status": "processing",
                "result": "",
                "runnable": design,
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        sent = api.send_message("@Design 做一版视觉方向")

        assert sent["ok"] is True
        assistant = [message for message in api.get_messages()["messages"] if message["role"] == "assistant"][-1]
        assert assistant["status"] == "processing"
        assert assistant["content"] == ""
        assert assistant["metadata"]["sender"]["nickname"] == "Design"
        assert assistant["metadata"]["run_id"] == "design_run_processing"
        assert assistant["metadata"]["run_group_id"] == "run_group_manual"
        assert calls[0]["user_goal"] == "做一版视觉方向"
        assert "[Yachiyo 群组执行约定]" in calls[0]["upstream"]
        assert "你在群内身份是：Design" in calls[0]["upstream"]
        assert "- Design（Agent；Design Agent）" in calls[0]["upstream"]
    finally:
        store.close()


def test_update_group_session_edits_name_avatar_and_agents(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    runtime.config = SimpleNamespace(
        assistant=SimpleNamespace(
            agent_name="月見八千代",
            agent_nickname="月夜",
            agent_avatar_path="",
        )
    )
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "Code",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            for agent in (design, coding):
                if runnable_id == agent["id"] or name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="旧群组", participant_ids=[design["id"]])
        assert created["ok"] is True

        updated = api.update_group_session(
            created["session_id"],
            name="新群组",
            avatar_url="https://example.test/new.png",
            participant_ids=[design["id"], coding["id"]],
        )

        assert updated["ok"] is True
        assert updated["session_context"]["runnable_name"] == "新群组"
        assert updated["session_context"]["avatar_url"] == "https://example.test/new.png"
        assert [item["nickname"] for item in updated["session_context"]["participants"]] == [
            "月夜",
            "Design",
            "Code",
        ]
        stored = store.get_session(created["session_id"])
        assert stored is not None
        assert stored.title == "新群组"
        assert stored.runnable_name == "新群组"
        assert stored.avatar_url == "https://example.test/new.png"
        listed = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == created["session_id"])
        assert listed["runnable_name"] == "新群组"
        assert listed["avatar_url"] == "https://example.test/new.png"
        assert [item["id"] for item in listed["participants"] if item["kind"] == "agent"] == [
            design["id"],
            coding["id"],
        ]
    finally:
        store.close()


def test_group_main_model_dispatch_result_creates_agent_run_messages(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "Code",
        "kind": "agent",
        "enabled": True,
    }
    calls: list[dict] = []

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (design, coding):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "upstream": upstream,
            })
            runnable = self.resolve_runnable(runnable_id=runnable_id, name=name) or {}
            run = {
                "run_id": f"{runnable_id}_run",
                "run_group_id": run_group_id or "run_group_dispatch",
                "status": "processing",
                "result": "",
                "runnable": runnable,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": f"{runnable.get('nickname')} done",
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(
            name="demo Channel",
            participant_ids=[design["id"], coding["id"]],
        )
        assert created["ok"] is True

        sent = api.send_message("@主模型 你来安排测试任务")
        assert sent["ok"] is True
        result_text = (
            "我来派活。\n"
            '{"action":"runyachiyoagent","agent":"@Design","goal":"做视觉测试"}\n'
            '{"action":"dispatch_group_agent","agent":"Code","goal":"做代码测试"}'
        )
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=result_text,
        )

        payload = api.get_messages()

        assert len(calls) == 2
        assert [call["runnable_id"] for call in calls] == ["agent_design", "agent_coding"]
        assert [call["user_goal"] for call in calls] == ["做视觉测试", "做代码测试"]
        messages = payload["messages"]
        assistant_messages = [message for message in messages if message["role"] == "assistant"]
        assert assistant_messages[0]["content"] == "我来派活。\n\n我把 2 个任务分别派给 Design、Code 了。"
        assert "runyachiyoagent" not in assistant_messages[0]["content"]
        assert "dispatch_group_agent" not in assistant_messages[0]["content"]
        assert assistant_messages[0]["metadata"]["group_dispatch_handled"] is True
        assert [message["metadata"]["sender"]["nickname"] for message in assistant_messages[1:3]] == [
            "Design",
            "Code",
        ]
        assert [message["content"] for message in assistant_messages[1:3]] == [
            "Design 已完成，并把结果交给主模型汇总。\n任务：做视觉测试",
            "Code 已完成，并把结果交给主模型汇总。\n任务：做代码测试",
        ]
        assert assistant_messages[1]["metadata"]["agent_report"] == "Design done"
        assert assistant_messages[2]["metadata"]["agent_report"] == "Code done"
        summary_message = assistant_messages[3]
        assert summary_message["status"] == "processing"
        assert summary_message["content"] == ""
        assert summary_message["metadata"]["sender"]["kind"] == "main"
        assert summary_message["metadata"]["group_agent_summary_for_task_id"] == sent["task_id"]
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "[Yachiyo 群组 Agent 汇总]" in summary_task.description
        assert "不要再派发新的 Agent 任务" in summary_task.description
        assert "汇报：Design done" in summary_task.description
        assert "汇报：Code done" in summary_task.description
        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert current["run_group_id"] == "run_group_dispatch"
    finally:
        store.close()


def test_group_main_model_dispatch_stream_stays_loading(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 安排一下")
        assert sent["ok"] is True
        runtime.state.update_task_status(sent["task_id"], TaskStatus.RUNNING)
        runtime.chat_session.upsert_assistant_message(
            sent["task_id"],
            '我会先交给 Design 做测试。\n{"action":"dispatch_group_agent","agent":"Design","goal":"做测试"}',
            MessageStatus.PROCESSING,
        )

        payload = api.get_messages()

        assistant = next(message for message in payload["messages"] if message["role"] == "assistant")
        assert assistant["status"] == "processing"
        assert assistant["content"] == "我会先交给 Design 做测试。"
        assert assistant["metadata"]["group_dispatch_pending"] is True
        assert assistant["metadata"]["group_dispatch_stream_visible_content"] == "我会先交给 Design 做测试。"
        assert assistant["activity_events"][0]["title"] == "正在派发群组任务"
        assert payload["is_processing"] is True
    finally:
        activity_store.close()
        store.close()


def test_group_main_model_dispatch_posts_agent_progress(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    calls: list[dict] = []

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            calls.append({
                "runnable_id": runnable_id,
                "user_goal": user_goal,
                "upstream": upstream,
            })
            return {
                "run_id": "agent_run_processing",
                "run_group_id": run_group_id or "run_group_dispatch",
                "status": "processing",
                "result": "",
                "runnable": design,
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 安排一下")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"做视觉测试"}',
        )

        assistant_messages = [message for message in api.get_messages()["messages"] if message["role"] == "assistant"]

        assert assistant_messages[0]["content"] == "我把这个任务派给 Design 了。"
        agent_message = assistant_messages[-1]
        assert agent_message["status"] == "processing"
        assert agent_message["content"] == ""
        assert agent_message["metadata"]["sender"]["nickname"] == "Design"
        assert agent_message["metadata"]["run_id"] == "agent_run_processing"
        assert agent_message["metadata"]["run_group_id"] == "run_group_dispatch"
        assert agent_message["metadata"]["delegated_goal"] == "做视觉测试"
        assert calls[0]["user_goal"] == "做视觉测试"
        assert "[Yachiyo 群组执行约定]" in calls[0]["upstream"]
        assert "你在群内身份是：Design" in calls[0]["upstream"]
        assert "- Design（Agent；Design Agent）" in calls[0]["upstream"]
        assert api.get_messages()["is_processing"] is True
    finally:
        store.close()


def test_group_agent_approval_required_remains_processing(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            run = {
                "run_id": "agent_run_waiting",
                "run_group_id": run_group_id or "run_group_dispatch",
                "status": "processing",
                "result": "",
                "runnable": design,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "approval_id": "approval_fake",
                        "tool": "terminal.run",
                        "input_preview": {
                            "command": "pytest tests/test_chat_api.py -q",
                            "timeout_seconds": 30,
                        },
                    },
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 安排一下")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"运行测试"}',
        )

        payload = api.get_messages()

        assistant_messages = [message for message in payload["messages"] if message["role"] == "assistant"]
        agent_message = assistant_messages[-1]
        assert agent_message["content"] == (
            "Design 需要你确认一次工具调用，批准后会继续执行当前任务。\n"
            "工具：terminal.run\n"
            "关联任务：运行测试\n"
            "请求摘要：命令：pytest tests/test_chat_api.py -q"
        )
        assert agent_message["status"] == "processing"
        assert agent_message["metadata"]["run_status"] == "approval_required"
        assert agent_message["metadata"]["pending_approval"]["tool"] == "terminal.run"
        assert payload["is_processing"] is True
    finally:
        store.close()


def test_group_agent_approval_completion_creates_main_summary(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def __init__(self):
            self.run = {
                "run_id": "agent_run_waiting",
                "run_group_id": "run_group_dispatch",
                "status": "processing",
                "result": "",
                "runnable": design,
            }

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            self.run = {
                **self.run,
                "run_group_id": run_group_id or "run_group_dispatch",
            }
            if on_complete:
                on_complete({
                    **self.run,
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "approval_id": "approval_fake",
                        "tool": "terminal.run",
                        "input_preview": {"command": "pytest tests/test_chat_api.py -q"},
                    },
                })
            return self.run

        def get_run(self, run_id):
            assert run_id == "agent_run_waiting"
            return self.run

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 安排一下")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"运行测试"}',
        )
        api.get_messages()

        service.run = {
            **service.run,
            "status": "completed",
            "result": "测试已经通过，覆盖群组派发和审批恢复。",
            "pending_approval": {},
        }
        payload = api.get_messages()

        assistant_messages = [message for message in payload["messages"] if message["role"] == "assistant"]
        agent_message = next(
            message
            for message in assistant_messages
            if message["metadata"].get("sender", {}).get("nickname") == "Design"
        )
        assert agent_message["status"] == "completed"
        assert agent_message["content"] == "Design 已完成，并把结果交给主模型汇总。\n任务：运行测试"
        assert agent_message["metadata"]["agent_report"] == "测试已经通过，覆盖群组派发和审批恢复。"
        summary_message = assistant_messages[-1]
        assert summary_message["status"] == "processing"
        assert summary_message["metadata"]["sender"]["kind"] == "main"
        assert summary_message["metadata"]["group_agent_summary_for_task_id"] == sent["task_id"]
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "汇报：测试已经通过，覆盖群组派发和审批恢复。" in summary_task.description
        assert payload["is_processing"] is True
    finally:
        store.close()


def test_retry_delegated_agent_failure_reruns_same_agent(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    furina = {
        "id": "agent_furina",
        "name": "Coding Agent",
        "nickname": "furina",
        "kind": "agent",
        "enabled": True,
    }
    demo = {
        "id": "agent_demo",
        "name": "Demo Coding Agent",
        "nickname": "demo Channel",
        "kind": "agent",
        "enabled": True,
    }
    calls: list[dict] = []

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (furina, demo):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
            })
            runnable = self.resolve_runnable(runnable_id=runnable_id, name=name) or {}
            status = "failed" if len(calls) == 1 else "completed"
            result = "OpenAI-compatible Profile 调用失败：timeout" if status == "failed" else "furina retry done"
            run = {
                "run_id": f"{runnable_id}_run_{len(calls)}",
                "run_group_id": run_group_id or "run_group_retry",
                "status": "processing",
                "result": "",
                "runnable": runnable,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": status,
                    "result": result,
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[furina["id"], demo["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 安排一下")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"furina","goal":"做测试"}',
        )
        failed_payload = api.get_messages()
        failed_agent = [
            message
            for message in failed_payload["messages"]
            if message["role"] == "assistant" and message["metadata"].get("sender", {}).get("nickname") == "furina"
        ][0]
        assert failed_agent["status"] == "failed"

        retry = api.retry_message(failed_agent["id"])

        assert retry["ok"] is True
        assert retry["runnable_command"] is True
        assert retry["task_id"] == ""
        assert len(runtime.state.list_tasks()) == 2
        assert [call["runnable_id"] for call in calls] == ["agent_furina", "agent_furina"]
        assert [call["user_goal"] for call in calls] == ["做测试", "做测试"]
        messages = api.get_messages()["messages"]
        furina_messages = [
            message
            for message in messages
            if message["role"] == "assistant" and message["metadata"].get("sender", {}).get("nickname") == "furina"
        ]
        assert furina_messages[-1]["content"] == (
            "furina 已完成，并把结果交给主模型汇总。\n"
            "任务：做测试"
        )
        assert furina_messages[-1]["metadata"]["agent_report"] == "furina retry done"
        assert furina_messages[-1]["status"] == "completed"
    finally:
        store.close()


def test_manual_group_workflow_mention_switches_to_workflow_context(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    workflow = {
        "id": "workflow_web",
        "name": "Web Flow",
        "kind": "workflow",
        "enabled": True,
        "participants": [design],
    }

    class FakeRunnableService:
        def list_runnables(self):
            return {"runnables": [design, workflow]}

        def parse_known_chat_runnable(self, text):
            if "@Web Flow" in text:
                return "Web Flow", "做一个网页链路"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            for runnable in (design, workflow):
                if runnable_id == runnable["id"] or name == runnable["name"] or name == runnable.get("nickname"):
                    return runnable
            return None

        def create_run_for_runnable(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream=""):
            return {
                "run_id": "workflow_run_fake",
                "run_group_id": run_group_id or "run_group_workflow",
                "status": "completed",
                "result": "Workflow result",
                "timeline": [],
                "runnable": workflow,
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(
            name="demo Channel",
            participant_ids=[design["id"]],
        )
        assert created["ok"] is True
        result = api.send_message("@Web Flow 做一个网页链路")
        assert result["ok"] is True
        assert result["workflow_run_id"] == "workflow_run_fake"

        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert current["conversation_kind"] == "workflow"
        assert current["runnable_id"] == workflow["id"]
        assert current["runnable_name"] == "Web Flow"
        assert [item["name"] for item in current["participants"]] == ["Design Agent"]
    finally:
        store.close()


def test_agent_mention_supports_multiword_names(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        seed_templates=False,
    )
    agent = service.create_agent(
        {
            "name": "Draft Agent",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Agent result"})
    try:
        result = api.send_message("@Draft Agent 整理需求")
        assert result["ok"] is True
        assert result["agent_run_id"]
        # 等待异步执行完成
        _wait_for_agent_run(service, result["agent_run_id"])
        _wait_for_assistant_content(runtime, "Agent result")
        run = service.get_run(result["agent_run_id"])
        assert run["runnable_id"] == agent["agent_id"]
        assert runtime.state.list_tasks() == []
    finally:
        service.close()
        store.close()


def test_agent_mention_can_appear_inline_without_catching_email(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        seed_templates=False,
    )
    agent = service.create_agent(
        {
            "name": "Design Agent",
            "nickname": "Design",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Design result"})
    try:
        normal = api.send_message("我的邮箱是 demo@example.com")

        assert normal["ok"] is True
        assert "runnable_command" not in normal
        assert runtime.state.get_task(normal["task_id"]) is not None

        runtime.start_new_session()
        result = api.send_message("请 @Design 做一版视觉方向")

        assert result["ok"] is True
        assert result["agent_run_id"]
        # 等待异步执行完成
        _wait_for_agent_run(service, result["agent_run_id"])
        _wait_for_assistant_content(runtime, "Design result")
        run = service.get_run(result["agent_run_id"])
        assert run["runnable_id"] == agent["agent_id"]
        assert run["user_goal"] == "请 做一版视觉方向"
    finally:
        service.close()
        store.close()


def test_get_messages_and_sessions_include_activity_events(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        result = api.send_message("跑一下脚本")
        task_id = result["task_id"]
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="terminal",
            phase="tool_start",
            title="正在运行脚本",
            detail="python build.py",
            status="running",
        )
        runtime.chat_session.upsert_assistant_message(
            task_id=task_id,
            content="",
            status=MessageStatus.PROCESSING,
        )

        messages = api.get_messages()["messages"]
        user = messages[0]
        assistant = messages[1]
        assert user["progress_label"] == ""
        assert user["activity_events"] == []
        assert assistant["activity_events"][0]["title"] == "正在运行脚本"

        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == runtime.chat_session.session_id)
        assert current["is_processing"] is True
        assert current["latest_activity"]["tool_name"] == "terminal"
        assert current["latest_activity"]["title"] == "正在运行脚本"
        assert current["latest_message_preview"] == "跑一下脚本"
        assert current["latest_message_status"] == "processing"
    finally:
        activity_store.close()
        store.close()


def test_get_messages_hides_internal_reasoning_activity(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    try:
        result = api.send_message("普通回复")
        task_id = result["task_id"]
        runtime.state.update_task_progress(task_id, "Hermes 正在推理")
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="",
            phase="reasoning",
            title="Hermes 正在推理",
            detail="内部思考片段",
            status="running",
        )
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="hermes",
            phase="task_start",
            title="Yachiyo 开始处理",
            detail="普通回复",
            status="running",
        )
        runtime.chat_session.upsert_assistant_message(
            task_id=task_id,
            content="",
            status=MessageStatus.PROCESSING,
        )

        assistant = api.get_messages()["messages"][1]

        assert assistant["activity_events"] == []
        assert assistant["progress_label"] == ""
    finally:
        activity_store.close()
        store.close()


def test_list_sessions_ignores_stale_stored_processing_without_live_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("已经完成的问题")
        runtime.chat_session.upsert_assistant_message(
            task_id="stale-task",
            content="旧的处理中占位",
            status=MessageStatus.PROCESSING,
        )

        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)

        assert current["is_processing"] is False
        assert current["latest_message_preview"] == "已经完成的问题"
        assert current["latest_message_status"] == "processing"
    finally:
        store.close()


def test_session_title_ignores_prompt_echo_stored_title():
    messages = [
        SimpleNamespace(role=MessageRole.USER.value, content="测试1"),
        SimpleNamespace(role=MessageRole.ASSISTANT.value, content="收到"),
    ]

    assert ChatAPI._session_title("首先，用户要求为这段持续对话生成一个会话列表标题。", messages) == "测试1"


def test_list_sessions_search_includes_message_match(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("这里有聊天搜索关键词")

        sessions = api.list_sessions(query="聊天")["sessions"]

        assert len(sessions) == 1
        assert sessions[0]["session_id"] == session_id
        assert sessions[0]["search_match"]["message_id"]
        assert "聊天" in sessions[0]["search_match"]["snippet"]
    finally:
        store.close()


def test_get_messages_can_load_around_search_anchor(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        session_id = runtime.chat_session.session_id
        for index in range(6):
            store.save_message(StoredMessage(
                message_id=f"m{index}",
                session_id=session_id,
                role="user",
                content=f"消息 {index}",
                status="completed",
                task_id=None,
                error=None,
                created_at=f"2026-01-01T00:00:0{index}+00:00",
            ))

        messages = api.get_messages(limit=3, anchor_message_id="m3")["messages"]

        assert "m3" in [message["id"] for message in messages]
    finally:
        store.close()


def test_sort_messages_keeps_assistant_only_task_in_timeline():
    proactive = _chat_message("proactive", MessageRole.ASSISTANT, "主动提醒", task_id="tp")
    user = _chat_message("user", MessageRole.USER, "收到", task_id="tu")
    assistant = _chat_message("assistant", MessageRole.ASSISTANT, "继续回复", task_id="tu")

    sorted_messages = ChatAPI._sort_messages_by_task([proactive, user, assistant])

    assert [message.message_id for message in sorted_messages] == [
        "proactive",
        "user",
        "assistant",
    ]


def test_sort_messages_dedupes_repeated_assistant_for_same_user_task():
    user = _chat_message("user", MessageRole.USER, "早上好", task_id="t1")
    completed = _chat_message("assistant-done", MessageRole.ASSISTANT, "早上好呀", task_id="t1")
    stale_processing = _chat_message(
        "assistant-stale",
        MessageRole.ASSISTANT,
        "早上好呀",
        task_id="t1",
        status=MessageStatus.PROCESSING,
    )

    sorted_messages = ChatAPI._sort_messages_by_task([user, completed, stale_processing])

    assert [message.message_id for message in sorted_messages] == ["user", "assistant-done"]


def test_send_message_accepts_pasted_image_attachment(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_YACHIYO_BRIDGE_URL", "http://127.0.0.1:9999")
    api, runtime, store = _make_api(tmp_path)
    try:
        data_url = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")

        result = api.send_message(
            "看一下这张图",
            attachments=[{
                "name": "screen.png",
                "data_url": data_url,
            }],
        )

        assert result["ok"] is True
        assert len(result["attachments"]) == 1
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments[0]["kind"] == "image"
        assert task.attachments[0]["path"].endswith(".png")

        messages = api.get_messages()["messages"]
        assert messages[0]["attachments"][0]["url"].startswith("http://127.0.0.1:9999/ui/chat/attachments/")
        assert "path" not in messages[0]["attachments"][0]
    finally:
        store.close()


def test_proactive_session_followup_attaches_fresh_desktop_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    captures = []

    def fake_capture(target_path: Path):
        captures.append(target_path)
        target_path.write_bytes(b"fake-proactive-png")
        return {"width": 3024, "height": 1964, "size": target_path.stat().st_size}

    monkeypatch.setattr(chat_api_mod, "capture_screenshot_to_file", fake_capture)
    api, runtime, store = _make_api(tmp_path)
    runtime.chat_session = ChatSession(session_id=PROACTIVE_CHAT_SESSION_ID)
    runtime.chat_session.attach_store(store, load_existing=False)
    try:
        result = api.send_message("你可以主动看一下桌面吗？")

        assert result["ok"] is True
        assert len(captures) == 1
        assert len(result["attachments"]) == 1
        assert result["attachments"][0]["source"] == "proactive_desktop_followup"
        user = runtime.chat_session.get_messages()[0]
        assert user.content == "你可以主动看一下桌面吗？"
        assert user.attachments[0]["source"] == "proactive_desktop_followup"
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments[0]["source"] == "proactive_desktop_followup"
        assert "附加当前桌面截图" in task.description
    finally:
        store.close()


def test_user_requested_desktop_snapshot_attaches_in_normal_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    captures = []

    def fake_capture(target_path: Path):
        captures.append(target_path)
        target_path.write_bytes(b"fake-screen-png")
        return {"width": 1920, "height": 1080, "size": target_path.stat().st_size}

    monkeypatch.setattr(chat_api_mod, "capture_screenshot_to_file", fake_capture)
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("帮我看看我的桌面情况")

        assert result["ok"] is True
        assert len(captures) == 1
        assert result["attachments"][0]["source"] == "user_requested_desktop_snapshot"
        user = runtime.chat_session.get_messages()[0]
        assert user.content == "帮我看看我的桌面情况"
        assert user.attachments[0]["source"] == "user_requested_desktop_snapshot"
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments[0]["source"] == "user_requested_desktop_snapshot"
        assert "附加当前桌面截图" in task.description
    finally:
        store.close()


def test_user_implicit_current_activity_request_does_not_attach_desktop_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    captures = []

    def fake_capture(target_path: Path):
        captures.append(target_path)
        target_path.write_bytes(b"fake-current-activity-png")
        return {"width": 1920, "height": 1080, "size": target_path.stat().st_size}

    monkeypatch.setattr(chat_api_mod, "capture_screenshot_to_file", fake_capture)
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("你能看看我现在在做什么不")

        assert result["ok"] is True
        assert captures == []
        assert result["attachments"] == []
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments == []
        assert task.description == "你能看看我现在在做什么不"
    finally:
        store.close()


def test_design_feedback_with_plain_screen_word_does_not_attach_desktop_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        chat_api_mod,
        "capture_screenshot_to_file",
        lambda _target_path: (_ for _ in ()).throw(AssertionError("should not capture")),
    )
    api, runtime, store = _make_api(tmp_path)
    try:
        text = (
            '我看了一下当前桌面，class="plan-dropdown-item" 的显示有问题，'
            "plan 的名字的显示区域被挤压到显示不出来文字，需要修改成能够显示每个 plan 的名字。\n\n"
            "除功能以外，设计风格想要麻烦再出一版新的设计看一下。要求：\n"
            "1. 仅对画面元素和 UI 进行调整，保持现有功能 100% 不变。\n"
            "2. 风格修改为多巴胺风格，通过高饱和度、鲜艳明亮的色彩搭配以营造愉悦、快乐情绪和氛围的风格\n"
            "3. 请不要覆盖原文件，生成一个新的 html 文件"
        )

        result = api.send_message(text)

        assert result["ok"] is True
        assert result["attachments"] == []
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments == []
        assert task.description == text.strip()
    finally:
        store.close()


def test_explicit_agent_desktop_request_still_attaches_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    captures = []

    def fake_capture(target_path: Path):
        captures.append(target_path)
        target_path.write_bytes(b"fake-explicit-screen-png")
        return {"width": 1920, "height": 1080, "size": target_path.stat().st_size}

    monkeypatch.setattr(chat_api_mod, "capture_screenshot_to_file", fake_capture)
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("请你看一下当前桌面，帮我判断窗口里有什么问题")

        assert result["ok"] is True
        assert len(captures) == 1
        assert result["attachments"][0]["source"] == "user_requested_desktop_snapshot"
    finally:
        store.close()


def test_plain_message_does_not_attach_desktop_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        chat_api_mod,
        "capture_screenshot_to_file",
        lambda _target_path: (_ for _ in ()).throw(AssertionError("should not capture")),
    )
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("你好，今天聊点别的")

        assert result["ok"] is True
        assert result["attachments"] == []
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments == []
        assert task.description == "你好，今天聊点别的"
    finally:
        store.close()


def test_attachment_cache_cleanup_prunes_old_files(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr("apps.shell.chat_api._MAX_ATTACHMENT_CACHE_AGE_SECONDS", 1)
    monkeypatch.setattr("apps.shell.chat_api._MAX_ATTACHMENT_CACHE_BYTES", 1024 * 1024)
    old_dir = hermes_home / "yachiyo" / "attachments" / "deadbeef"
    old_dir.mkdir(parents=True)
    old_file = old_dir / "old.png"
    old_file.write_bytes(b"old")
    old_time = time.time() - 10
    os.utime(old_file, (old_time, old_time))

    api, runtime, store = _make_api(tmp_path)
    try:
        data_url = "data:image/png;base64," + base64.b64encode(b"new-png").decode("ascii")

        result = api.send_message("看一下这张图", attachments=[{"name": "screen.png", "data_url": data_url}])

        assert result["ok"] is True
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        new_path = Path(task.attachments[0]["path"])
        assert new_path.exists()
        assert not old_file.exists()
    finally:
        store.close()


def test_delete_current_session_removes_attachment_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    api, runtime, store = _make_api(tmp_path)
    runtime.chat_session = ChatSession(session_id="deadbeef")
    runtime.chat_session.attach_store(store, load_existing=False)
    original_get_store = _store_mod.get_chat_store
    _store_mod.get_chat_store = lambda: store
    try:
        data_url = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")
        result = api.send_message("删除这张图", attachments=[{"name": "screen.png", "data_url": data_url}])
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        attachment_dir = Path(task.attachments[0]["path"]).parent
        assert attachment_dir.exists()

        deleted = api.delete_current_session()

        assert deleted["ok"] is True
        assert deleted["deleted_session_id"] == "deadbeef"
        assert not attachment_dir.exists()
    finally:
        _store_mod.get_chat_store = original_get_store
        store.close()


def test_running_task_marks_message_processing(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("执行任务")
        runtime.state.update_task_status(result["task_id"], TaskStatus.RUNNING)

        messages = api.get_messages()["messages"]

        assert len(messages) == 2  # user + assistant placeholder
        assert messages[0]["status"] == "processing"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["status"] == "processing"
        assert api.get_session_info()["is_processing"] is True
    finally:
        store.close()


def test_completed_task_adds_single_assistant_reply(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("完成任务")
        task_id = result["task_id"]
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        runtime.state.update_task_status(task_id, TaskStatus.COMPLETED, result="完成输出")

        first = api.get_messages()["messages"]
        second = api.get_messages()["messages"]

        assert len(first) == 2
        assert len(second) == 2
        assert first[0]["status"] == "completed"
        assert first[1]["role"] == "assistant"
        assert first[1]["content"] == "完成输出"
        assert api.get_session_info()["is_processing"] is False
    finally:
        store.close()


def test_failed_task_marks_user_failed_and_adds_error_reply(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("失败任务")
        task_id = result["task_id"]
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        runtime.state.update_task_status(task_id, TaskStatus.FAILED, error="boom")

        messages = api.get_messages()["messages"]

        assert len(messages) == 2
        assert messages[0]["status"] == "failed"
        assert messages[0]["error"] == "boom"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["status"] == "failed"
        assert "boom" in messages[1]["content"]
        assert api.get_session_info()["is_processing"] is False
    finally:
        store.close()


def test_retry_failed_message_reuses_saved_image_attachments(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_YACHIYO_BRIDGE_URL", "http://127.0.0.1:9999")
    api, runtime, store = _make_api(tmp_path)
    try:
        data_url = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")
        sent = api.send_message("再看一下这张图", attachments=[{"name": "screen.png", "data_url": data_url}])
        original_task = runtime.state.get_task(sent["task_id"])
        assert original_task is not None
        original_path = original_task.attachments[0]["path"]
        runtime.state.update_task_status(sent["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(sent["task_id"], TaskStatus.FAILED, error="vision failed")
        failed_messages = api.get_messages()["messages"]

        retry = api.retry_message(failed_messages[1]["id"])

        assert retry["ok"] is True
        retried_task = runtime.state.get_task(retry["task_id"])
        assert retried_task is not None
        assert retried_task.description == "再看一下这张图"
        assert retried_task.attachments[0]["path"] == original_path
        assert retried_task.chat_session_id == runtime.chat_session.session_id
        retried_user = runtime.chat_session.get_messages()[-1]
        assert retried_user.content == "再看一下这张图"
        assert retried_user.attachments[0]["path"] == original_path
        assert retried_user.status == MessageStatus.PENDING
    finally:
        store.close()


def test_retry_failed_message_rejects_when_hermes_unavailable(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        sent = api.send_message("失败任务")
        runtime.state.update_task_status(sent["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(sent["task_id"], TaskStatus.FAILED, error="boom")
        failed_messages = api.get_messages()["messages"]
        runtime.task_runner = SimpleNamespace(
            executor=SimpleNamespace(
                name="HermesUnavailableExecutor",
                reason="Hermes Agent 当前不可用",
            )
        )

        retry = api.retry_message(failed_messages[1]["id"])

        assert retry == {"ok": False, "error": "Hermes Agent 当前不可用"}
        assert len(runtime.state.list_tasks()) == 1
    finally:
        store.close()


def test_cancelled_task_marks_user_failed_and_adds_cancel_reply(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("取消任务")
        task_id = result["task_id"]
        runtime.state.cancel_task(task_id)

        messages = api.get_messages()["messages"]

        assert len(messages) == 2
        assert messages[0]["status"] == "failed"
        assert messages[0]["error"] == "任务已取消"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["status"] == "failed"
        assert "任务已取消" in messages[1]["content"]
        assert api.get_session_info()["is_processing"] is False
    finally:
        store.close()


def test_clear_session_starts_new_session_and_preserves_active_task(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("清空前仍在执行")
        task_id = result["task_id"]
        old_session_id = runtime.chat_session.session_id
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        old_session_object = runtime.chat_session

        cleared = api.clear_session()

        assert cleared["ok"] is True
        assert cleared["cancelled_tasks"] == 0
        assert cleared["session_id"] != old_session_id
        assert runtime.state.get_task(task_id).status == TaskStatus.RUNNING
        assert runtime.cancelled_runner_tasks == []
        assert runtime.chat_session is not old_session_object
        assert old_session_object.session_id == old_session_id
        assert api.get_messages()["messages"] == []

        old_messages = store.load_messages(old_session_id)
        assert len(old_messages) == 2
        assert old_messages[0].status == "processing"
        assert old_messages[0].error is None
        assert old_messages[1].role == "assistant"
        assert old_messages[1].status == "processing"
        assert old_messages[1].error is None

        old_session_object.upsert_assistant_message(task_id, "旧任务完成", MessageStatus.COMPLETED)
        old_messages = store.load_messages(old_session_id)
        assert old_messages[1].content == "旧任务完成"
        assert old_messages[1].status == "completed"
    finally:
        store.close()


def test_discard_empty_current_session_switches_back_to_recent_session(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        api.send_message("保留的旧会话")
        old_session_id = runtime.chat_session.session_id
        cleared = api.clear_session()
        empty_session_id = cleared["session_id"]

        discarded = api.discard_empty_current_session()

        assert discarded["ok"] is True
        assert discarded["discarded"] is True
        assert discarded["deleted_session_id"] == empty_session_id
        assert runtime.chat_session.session_id == old_session_id
        assert store.get_session(empty_session_id) is None
        assert api.get_messages()["messages"][0]["content"] == "保留的旧会话"
    finally:
        store.close()


def test_discard_empty_current_session_keeps_nonempty_current_session(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        api.send_message("不要删除")
        current_session_id = runtime.chat_session.session_id

        discarded = api.discard_empty_current_session()

        assert discarded["ok"] is True
        assert discarded["discarded"] is False
        assert discarded["session_id"] == current_session_id
        assert runtime.chat_session.session_id == current_session_id
        assert store.get_session(current_session_id) is not None
    finally:
        store.close()


def test_discard_empty_current_session_keeps_empty_group_session(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        current_session_id = runtime.chat_session.session_id
        runtime.chat_session.set_session_title("demo Channel")
        store.update_session_context(
            current_session_id,
            conversation_kind="group",
            runnable_name="demo Channel",
            participants_json='[{"kind":"main","id":"main"},{"kind":"agent","id":"a1","name":"Agent One"}]',
        )

        discarded = api.discard_empty_current_session()

        assert discarded["ok"] is True
        assert discarded["discarded"] is False
        assert discarded["session_id"] == current_session_id
        assert runtime.chat_session.session_id == current_session_id
        session = store.get_session(current_session_id)
        assert session is not None
        assert session.conversation_kind == "group"
        assert session.message_count == 0
    finally:
        store.close()


def test_delete_current_session_removes_session_and_cancels_active_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    original_get_store = _store_mod.get_chat_store
    _store_mod.get_chat_store = lambda: store
    try:
        result = api.send_message("删除前仍在执行")
        task_id = result["task_id"]
        old_session_id = runtime.chat_session.session_id
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)

        deleted = api.delete_current_session()

        assert deleted["ok"] is True
        assert deleted["deleted_session_id"] == old_session_id
        assert deleted["session_id"] != old_session_id
        assert deleted["cancelled_tasks"] == 1
        assert deleted["remaining_sessions"] == 0
        assert deleted["empty"] is True
        assert runtime.state.get_task(task_id).status == TaskStatus.CANCELLED
        assert runtime.cancelled_runner_tasks == [task_id]
        assert store.get_session(old_session_id) is None
        assert store.load_messages(old_session_id) == []
        assert api.get_messages()["messages"] == []
        events = activity_store.list_events(task_id=task_id, limit=5, key_only=False)
        cancel_events = [event for event in events if event.phase == "task_cancelled"]
        assert len(cancel_events) == 1
        assert cancel_events[0].detail == "删除会话前取消仍在执行的任务"
        assert "删除前仍在执行" not in cancel_events[0].detail
    finally:
        _store_mod.get_chat_store = original_get_store
        activity_store.close()
        store.close()


def test_cancel_current_tasks_records_neutral_activity_detail(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    try:
        result = api.send_message("删除这张图")
        task_id = result["task_id"]
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)

        cancelled = api.cancel_current_tasks()

        assert cancelled["ok"] is True
        assert cancelled["cancelled_tasks"] == 1
        events = activity_store.list_events(task_id=task_id, limit=5, key_only=False)
        cancel_events = [event for event in events if event.phase == "task_cancelled"]
        assert len(cancel_events) == 1
        assert cancel_events[0].detail == "用户停止生成"
        assert "删除这张图" not in cancel_events[0].detail
    finally:
        activity_store.close()
        store.close()


def test_cancel_current_tasks_does_not_log_already_cancelled_stale_message(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(api, "_sync_task_status_to_messages", lambda: None)
    try:
        result = api.send_message("已经取消但消息状态还没刷新")
        task_id = result["task_id"]
        runtime.state.cancel_task(task_id)

        cancelled = api.cancel_current_tasks()

        assert cancelled["ok"] is True
        assert cancelled["cancelled_tasks"] == 0
        events = activity_store.list_events(task_id=task_id, limit=5, key_only=False)
        assert [event for event in events if event.phase == "task_cancelled"] == []
        assert runtime.cancelled_runner_tasks == []
    finally:
        activity_store.close()
        store.close()


def test_delete_current_session_switches_to_remaining_recent_session(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    original_get_store = _store_mod.get_chat_store
    _store_mod.get_chat_store = lambda: store
    try:
        other = ChatSession(session_id="s2")
        other.attach_store(store, load_existing=False)
        other.add_user_message("保留的会话")
        another = ChatSession(session_id="s3")
        another.attach_store(store, load_existing=False)
        another.add_user_message("另一个保留会话")

        deleted = api.delete_current_session()

        assert deleted["ok"] is True
        assert deleted["deleted_session_id"] == "s1"
        assert deleted["session_id"] in {"s2", "s3"}
        assert deleted["remaining_sessions"] == 2
        assert deleted["empty"] is False
        assert runtime.chat_session.session_id == deleted["session_id"]
        assert api.get_messages()["messages"][0]["content"] in {
            "保留的会话",
            "另一个保留会话",
        }
    finally:
        _store_mod.get_chat_store = original_get_store
        store.close()


def test_completing_one_of_multiple_messages_keeps_processing_true(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        first = api.send_message("任务一")
        second = api.send_message("任务二")
        runtime.state.update_task_status(first["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(
            first["task_id"], TaskStatus.COMPLETED, result="任务一完成"
        )

        messages = api.get_messages()["messages"]

        # 排序后: user1(completed) → assistant1(completed) → user2(pending)
        assert len(messages) == 3
        assert messages[0]["status"] == "completed"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "任务一完成"
        assert messages[2]["task_id"] == second["task_id"]
        assert messages[2]["status"] == "pending"
        assert api.get_session_info()["is_processing"] is True
    finally:
        store.close()


def test_get_messages_idempotent_no_duplicate_assistant(tmp_path):
    """多次 get_messages 不会生成重复 assistant 消息"""
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("幂等测试")
        task_id = result["task_id"]
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        runtime.state.update_task_status(task_id, TaskStatus.COMPLETED, result="结果")

        # 调用多次 get_messages
        for _ in range(5):
            msgs = api.get_messages()["messages"]

        assert len(msgs) == 2
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "结果"
    finally:
        store.close()


def test_processing_to_completed_updates_same_message(tmp_path):
    """processing 占位 → completed 应更新同一条消息，而非新增"""
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("状态迁移")
        task_id = result["task_id"]

        # RUNNING → 产生 processing placeholder
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        msgs_processing = api.get_messages()["messages"]
        assert len(msgs_processing) == 2
        placeholder_id = msgs_processing[1]["id"]
        assert msgs_processing[1]["status"] == "processing"

        # COMPLETED → 更新同一条 assistant 消息
        runtime.state.update_task_status(task_id, TaskStatus.COMPLETED, result="最终回复")
        msgs_completed = api.get_messages()["messages"]
        assert len(msgs_completed) == 2
        assert msgs_completed[1]["id"] == placeholder_id  # 同一条消息
        assert msgs_completed[1]["status"] == "completed"
        assert msgs_completed[1]["content"] == "最终回复"
    finally:
        store.close()


def test_processing_to_failed_updates_same_message(tmp_path):
    """processing 占位 → failed 应更新同一条消息"""
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("失败迁移")
        task_id = result["task_id"]

        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        msgs_processing = api.get_messages()["messages"]
        placeholder_id = msgs_processing[1]["id"]

        runtime.state.update_task_status(task_id, TaskStatus.FAILED, error="崩溃")
        msgs_failed = api.get_messages()["messages"]
        assert len(msgs_failed) == 2
        assert msgs_failed[1]["id"] == placeholder_id
        assert msgs_failed[1]["status"] == "failed"
        assert "崩溃" in msgs_failed[1]["content"]
    finally:
        store.close()


def test_running_task_preserves_streamed_assistant_content(tmp_path):
    """RUNNING 状态轮询不应清空执行器已经写入的流式内容。"""
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("流式任务")
        task_id = result["task_id"]
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        runtime.chat_session.upsert_assistant_message(
            task_id,
            "部分流式输出",
            MessageStatus.PROCESSING,
        )

        messages = api.get_messages()["messages"]

        assert len(messages) == 2
        assert messages[1]["role"] == "assistant"
        assert messages[1]["status"] == "processing"
        assert messages[1]["content"] == "部分流式输出"
    finally:
        store.close()


def test_assistant_only_task_syncs_without_visible_user_prompt(tmp_path):
    """主动关怀这类内部任务可以只显示 assistant 状态消息。"""
    api, runtime, store = _make_api(tmp_path)
    try:
        task = runtime.state.create_task("主动桌面观察：内部执行 prompt")
        runtime.chat_session.upsert_assistant_message(
            task.task_id,
            "正在查看当前状态。",
            MessageStatus.PROCESSING,
        )

        runtime.state.update_task_status(task.task_id, TaskStatus.COMPLETED, result="周末上午过得怎么样？")
        messages = api.get_messages()["messages"]

        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"
        assert messages[0]["task_id"] == task.task_id
        assert messages[0]["status"] == "completed"
        assert messages[0]["content"] == "周末上午过得怎么样？"
        assert "主动桌面观察" not in messages[0]["content"]
    finally:
        store.close()


def test_message_sorting_pairs_user_with_assistant(tmp_path):
    """消息排序：user 消息后紧跟其关联的 assistant 回复"""
    api, runtime, store = _make_api(tmp_path)
    try:
        r1 = api.send_message("任务一")
        r2 = api.send_message("任务二")

        # 任务二先完成
        runtime.state.update_task_status(r2["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(r2["task_id"], TaskStatus.COMPLETED, result="二完成")
        # 任务一后完成
        runtime.state.update_task_status(r1["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(r1["task_id"], TaskStatus.COMPLETED, result="一完成")

        msgs = api.get_messages()["messages"]
        assert len(msgs) == 4  # 2 user + 2 assistant

        # user1 → assistant1, user2 → assistant2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["task_id"] == r1["task_id"]
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "一完成"
        assert msgs[2]["role"] == "user"
        assert msgs[2]["task_id"] == r2["task_id"]
        assert msgs[3]["role"] == "assistant"
        assert msgs[3]["content"] == "二完成"
    finally:
        store.close()


def test_message_sorting_keeps_unpaired_task_assistant():
    """分页截断 user 消息时，带 task_id 的 assistant 仍应返回给前端。"""
    assistant = _chat_message(
        "a1",
        MessageRole.ASSISTANT,
        content="分页截断后仍可见的回复",
        task_id="t1",
    )

    sorted_msgs = ChatAPI._sort_messages_by_task([assistant])

    assert sorted_msgs == [assistant]


def test_message_sorting_does_not_duplicate_untracked_assistant():
    """无 task_id 的 assistant 消息保持原始位置且不会被重复追加。"""
    system = _chat_message("s1", MessageRole.SYSTEM, content="系统提示")
    assistant = _chat_message("a1", MessageRole.ASSISTANT, content="旧回复")

    sorted_msgs = ChatAPI._sort_messages_by_task([system, assistant])

    assert [msg.message_id for msg in sorted_msgs] == ["s1", "a1"]
