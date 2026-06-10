import asyncio
import base64
import json
import time
from types import SimpleNamespace

import pytest

import apps.core.activity_store as activity_store_mod
import apps.core.chat_store as chat_store_mod
import apps.shell.chat_api as chat_api_mod
from apps.core.activity_store import ActivityStore
from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.executor import NativeAgentExecutor
from apps.core.state import AppState
from apps.core.task_runner import TaskRunner
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.chat_api import ChatAPI
from apps.shell.credential_store import MemoryCredentialStore
from packages.protocol.enums import TaskStatus, TaskType


class _InstantExecutor:
    @property
    def name(self) -> str:
        return "InstantExecutor"

    async def run(self, task):
        return f"done:{task.description}"


class _FakeDefaultProfileService:
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


async def _wait_for(condition, *, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = condition()
        except Exception as exc:
            last = exc
            await asyncio.sleep(0.02)
            continue
        if last:
            return last
        await asyncio.sleep(0.02)
    raise TimeoutError(f"condition not met; last={last!r}")


@pytest.mark.asyncio
async def test_stop_awaits_in_progress_task_cancellation():
    runner = TaskRunner(AppState())
    child = asyncio.create_task(asyncio.sleep(60))
    runner._in_progress["task1"] = child

    await runner.stop()

    assert child.done()
    assert runner._in_progress == {}


@pytest.mark.asyncio
async def test_task_runner_writes_final_reply_to_original_background_session(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_store_mod, "get_chat_store", lambda: store)
    monkeypatch.setattr(activity_store_mod, "get_activity_store", lambda: activity_store)
    state = AppState()
    task = state.create_task(
        task_type=TaskType.GENERAL,
        description="后台任务",
        chat_session_id="background-session",
    )
    runner = TaskRunner(state, executor=_InstantExecutor())  # type: ignore[arg-type]
    try:
        await runner._execute_with_state(task.task_id)

        updated = state.get_task(task.task_id)
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        messages = store.load_messages("background-session", limit=10)
        assistant = next(message for message in messages if message.role == "assistant")
        assert assistant.task_id == task.task_id
        assert assistant.status == "completed"
        assert assistant.content == "done:后台任务"
        activity_titles = [event.title for event in activity_store.latest_for_task(task.task_id, limit=5)]
        assert "Yachiyo 回复完成" in activity_titles
    finally:
        activity_store.close()
        store.close()


@pytest.mark.asyncio
async def test_task_runner_main_chat_native_tool_approval_roundtrip(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    workdir = tmp_path / "workspace"
    (workdir / "src").mkdir(parents=True)
    (workdir / "src" / "app.txt").write_text("before\n", encoding="utf-8")
    session = ChatSession(session_id="main-chat-approval-session")
    session.attach_store(store, load_existing=False)
    state = AppState()
    task = state.create_task(
        task_type=TaskType.GENERAL,
        description="请把 src/app.txt 改成 after",
        chat_session_id=session.session_id,
    )
    user_message_id = session.add_user_message(task.description)
    session.link_message_to_task(user_message_id, task.task_id)
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert any((tool.get("function") or {}).get("name") == "workspace_write_patch" for tool in tools or [])
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
        return {"role": "assistant", "content": "已完成修改。"}

    monkeypatch.setattr(chat_store_mod, "get_chat_store", lambda: store)
    monkeypatch.setattr(activity_store_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: _FakeDefaultProfileService())
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    executor = NativeAgentExecutor(
        chat_session=session,
        runtime_service_getter=lambda: service,
        tool_policy_getter=lambda: {
            "allowed_tools": ["workspace.read", "workspace.write_patch"],
            "approval_required": {"workspace.write_patch": True},
        },
        workspace_policy_getter=lambda: {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
    )
    runner = TaskRunner(state, executor=executor)
    api = ChatAPI(SimpleNamespace(state=state, chat_session=session, store=store))
    runner_task: asyncio.Task | None = None
    try:
        runner_task = asyncio.create_task(runner._execute_with_state(task.task_id))
        run = await _wait_for(
            lambda: service.get_run(service.get_task_run_link(task.task_id)["run_id"])
        )
        assert run["status"] == "approval_required"
        assert state.get_task(task.task_id).status == TaskStatus.RUNNING

        waiting_payload = api.get_messages()
        assistant = next(message for message in waiting_payload["messages"] if message["role"] == "assistant")
        assert waiting_payload["approval_count"] == 1
        assert assistant["status"] == "processing"
        assert assistant["metadata"]["run_status"] == "approval_required"
        assert assistant["metadata"]["run_id"] == run["run_id"]
        assert assistant["metadata"]["pending_approval"]["tool"] == "workspace.write_patch"
        assert assistant["activity_events"][0]["status"] == "approval_required"

        approved = await asyncio.to_thread(service.approve_run_approval, run["run_id"])
        assert approved["status"] == "running"
        await runner_task

        updated = state.get_task(task.task_id)
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result == "已完成修改。"
        assert (workdir / "src" / "app.txt").read_text(encoding="utf-8") == "after\n"
        final_messages = store.load_messages(session.session_id, limit=10)
        final_assistant = next(message for message in final_messages if message.role == "assistant")
        assert final_assistant.status == "completed"
        assert final_assistant.content == "已完成修改。"
        event_types = [event["event_type"] for event in service.list_run_events(run["run_id"])["events"]]
        assert "agent.tool.approval_required" in event_types
        assert "agent.tool.approval_approved" in event_types
        assert "model.output.completed" in event_types
        assert "run.completed" in event_types
    finally:
        if runner_task is not None and not runner_task.done():
            runner_task.cancel()
            await asyncio.gather(runner_task, return_exceptions=True)
        service.close()
        activity_store.close()
        store.close()


@pytest.mark.asyncio
async def test_task_runner_main_chat_auto_delegation_uses_native_runtime(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="main-chat-delegation-session")
    session.attach_store(store, load_existing=False)
    state = AppState()
    task = state.create_task(
        task_type=TaskType.GENERAL,
        description="请让 Research Agent 调研 Native 委派链路，然后给我结论",
        chat_session_id=session.session_id,
    )
    user_message_id = session.add_user_message(task.description)
    session.link_message_to_task(user_message_id, task.task_id)
    model_calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        model_calls.append(messages)
        last_content = str(messages[-1]["content"])
        if "# Agent\nName: Research Agent" in last_content:
            assert "# User Goal\n调研 Native 委派链路" in last_content
            return {"role": "assistant", "content": "Research Agent native delegation result"}
        if "[OHA 委派结果]" in last_content:
            assert "Research Agent native delegation result" in last_content
            return {"role": "assistant", "content": "最终结论：Native 委派链路已闭环。"}
        return {
            "role": "assistant",
            "content": json.dumps(
                {
                    "action": "run_oha_agent",
                    "agent": "Research Agent",
                    "goal": "调研 Native 委派链路",
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(chat_store_mod, "get_chat_store", lambda: store)
    monkeypatch.setattr(activity_store_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: _FakeDefaultProfileService())
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    agent = service.create_agent(
        {
            "name": "Research Agent",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
    executor = NativeAgentExecutor(
        chat_session=session,
        runtime_service_getter=lambda: service,
        tool_policy_getter=lambda: {"allowed_tools": []},
        workspace_policy_getter=lambda: {},
    )
    runner = TaskRunner(state, executor=executor)
    try:
        await runner._execute_with_state(task.task_id)

        updated = state.get_task(task.task_id)
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result == "最终结论：Native 委派链路已闭环。"
        assert len(model_calls) == 3

        assistant = next(message for message in store.load_messages(session.session_id, limit=10) if message.role == "assistant")
        assert assistant.task_id == task.task_id
        assert assistant.status == "completed"
        assert assistant.content == "最终结论：Native 委派链路已闭环。"

        link = service.get_task_run_link(task.task_id)
        main_run = service.get_run(link["run_id"])
        assert main_run["kind"] == "main_chat_run"
        assert main_run["status"] == "completed"
        assert main_run["result"] == "最终结论：Native 委派链路已闭环。"
        main_event_types = [event["event_type"] for event in service.list_run_events(main_run["run_id"])["events"]]
        assert main_event_types.count("model.output.completed") == 2
        assert "run.completed" in main_event_types

        delegated_runs = [
            run for run in service.list_runs(limit=20)["runs"]
            if run["kind"] == "agent_run" and run["runnable_id"] == agent["agent_id"]
        ]
        assert len(delegated_runs) == 1
        delegated = delegated_runs[0]
        assert delegated["status"] == "completed"
        assert delegated["result"] == "Research Agent native delegation result"
        assert service.get_run_group(delegated["run_group_id"])["source"] == "delegation"

        activity_events = [event.to_dict() for event in activity_store.latest_for_task(task.task_id, limit=10)]
        activity_summary = [
            (event["title"], event["status"], event["tool_name"], event["phase"])
            for event in activity_events
        ]
        assert any(
            event["title"] == "正在委派给 Research Agent"
            and event["tool_name"] == "oha.delegation"
            and event["phase"] == "subagent"
            for event in activity_events
        ), activity_summary
        completed_activity = next(event for event in activity_events if event["title"] == "Research Agent 委派完成")
        assert completed_activity["status"] == "completed"
        assert completed_activity["metadata"]["run_id"] == delegated["run_id"]
        assert completed_activity["metadata"]["run_group_id"] == delegated["run_group_id"]
    finally:
        service.close()
        activity_store.close()
        store.close()


@pytest.mark.asyncio
async def test_task_runner_main_chat_image_attachment_reaches_native_model(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes
    from apps.bridge.routes import runs as run_routes

    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_URL", "http://127.0.0.1:9999")
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="main-chat-image-session")
    session.attach_store(store, load_existing=False)
    state = AppState()
    captured_messages: list[list[dict]] = []
    image_bytes = b"fake-native-image"
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        captured_messages.append(messages)
        content = messages[-1]["content"]
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "看一下这张图"}
        image_parts = [part for part in content if part.get("type") == "image_url"]
        assert len(image_parts) == 1
        assert image_parts[0]["image_url"]["url"] == data_url
        return {"role": "assistant", "content": "这是一张测试图片。"}

    monkeypatch.setattr(chat_store_mod, "get_chat_store", lambda: store)
    monkeypatch.setattr(activity_store_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr(run_routes, "get_native_run_engine", lambda: service)
    monkeypatch.setattr(
        "apps.shell.native_capabilities.get_native_image_input_capability",
        lambda: {"can_attach_images": True, "route": "chat"},
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeDefaultProfileService(),
    )
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    executor = NativeAgentExecutor(
        chat_session=session,
        runtime_service_getter=lambda: service,
        tool_policy_getter=lambda: {"allowed_tools": []},
        workspace_policy_getter=lambda: {},
    )
    runner = TaskRunner(state, executor=executor)
    api = ChatAPI(SimpleNamespace(state=state, chat_session=session, store=store))
    try:
        sent = api.send_message(
            "看一下这张图",
            attachments=[{"name": "screen.png", "data_url": data_url}],
            client_message_id="image-client-1",
        )

        assert sent["ok"] is True
        assert len(sent["attachments"]) == 1
        task = state.get_task(sent["task_id"])
        assert task is not None
        assert task.attachments[0]["kind"] == "image"
        await runner._execute_with_state(task.task_id)

        assert len(captured_messages) == 1
        updated = state.get_task(task.task_id)
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result == "这是一张测试图片。"
        messages = api.get_messages()["messages"]
        user_message = next(message for message in messages if message["role"] == "user")
        assistant_message = next(message for message in messages if message["role"] == "assistant")
        assert user_message["attachments"][0]["url"].startswith("http://127.0.0.1:9999/ui/chat/attachments/")
        assert "path" not in user_message["attachments"][0]
        assert assistant_message["content"] == "这是一张测试图片。"
        assert assistant_message["status"] == "completed"
        run = service.get_run(service.get_task_run_link(task.task_id)["run_id"])
        event_types = [event["event_type"] for event in service.list_run_events(run["run_id"])["events"]]
        assert run["status"] == "completed"
        assert "task.linked" in event_types
        assert "model.output.completed" in event_types
        assert "run.completed" in event_types

        listed_runs = await agent_routes.list_runs(limit=20)
        detail = await agent_routes.get_any_run(run["run_id"])
        replay = await run_routes.list_run_events(run["run_id"], after_sequence=0, limit=200)
        page = await run_routes.list_run_events(run["run_id"], after_sequence=1, limit=1)

        assert any(item["run_id"] == run["run_id"] for item in listed_runs["runs"])
        assert detail["run_id"] == run["run_id"]
        assert detail["kind"] == "main_chat_run"
        assert detail["status"] == "completed"
        assert detail["result"] == "这是一张测试图片。"
        assert any(event.get("event") == "run.completed" for event in detail["timeline"])
        assert [event["sequence"] for event in replay["events"]] == list(range(1, len(replay["events"]) + 1))
        assert [event["event_type"] for event in replay["events"]] == event_types
        assert page["after_sequence"] == 1
        assert page["limit"] == 1
        assert len(page["events"]) == 1
        assert page["events"][0]["sequence"] == 2
    finally:
        service.close()
        activity_store.close()
        store.close()
