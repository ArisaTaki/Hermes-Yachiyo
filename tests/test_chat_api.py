"""ChatAPI 测试 — 消息发送与任务状态同步"""

import base64
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from apps.core.activity_store import ActivityStore
from apps.core.chat_session import ChatMessage, ChatSession, MessageRole, MessageStatus
from apps.core.chat_store import ChatStore, StoredMessage
import apps.core.chat_store as _store_mod
from apps.core.special_sessions import PROACTIVE_CHAT_SESSION_ID
from apps.core.state import AppState
from apps.shell.agent.runtime.config import MAIN_CHAT_AGENT_ID
import apps.shell.chat_api as chat_api_mod
from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService
from apps.shell.chat_api import ChatAPI, GroupDispatchDirective
from apps.shell.credential_store import MemoryCredentialStore
from packages.protocol.enums import TaskStatus
from scripts.verify_secret_redaction import verify_secret_redaction


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


def _make_agent_runtime_service(tmp_path) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )


def _wait_for_agent_run(service: AgentRuntimeService, run_id: str, timeout: float = 5.0) -> dict:
    """等待 Agent Run 异步执行完成"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = service.get_run(run_id)
        if run["status"] in ("completed", "failed", "cancelled", "approval_required"):
            return run
        time.sleep(0.1)
    raise TimeoutError(f"Agent Run {run_id} 未在 {timeout} 秒内完成")


def _wait_for_assistant_content_contains(api: ChatAPI, content: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = api.get_messages()
        for message in payload["messages"]:
            if message["role"] == "assistant" and content in str(message["content"] or ""):
                return message
        time.sleep(0.05)
    raise TimeoutError(f"Assistant message containing {content!r} 未在 {timeout} 秒内写入")


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


def test_run_status_labels_are_user_facing_chinese():
    assert ChatAPI._workflow_status_label("running") == "进行中"
    assert ChatAPI._workflow_status_label("processing") == "进行中"
    assert ChatAPI._workflow_status_label("pending") == "等待中"
    assert ChatAPI._workflow_status_label("approval_required") == "等待审批"
    assert ChatAPI._workflow_status_label("") == "状态：未知状态"


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


def test_send_message_executes_direct_daily_desktop_music_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    runtime.agent_runtime_service = service
    control_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct desktop chat task should not call model")
        ),
    )

    def fake_apple_music_control(action: str) -> dict:
        control_calls.append(action)
        return {
            "ok": True,
            "action": "media.apple_music_control",
            "summary": f"Apple Music {action} executed",
            "data": {
                "control": action,
                "player_state": "playing",
                "track": "超时空辉夜姬",
                "artist": "Yachiyo",
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.apple_music_control",
        fake_apple_music_control,
    )
    try:
        result = api.send_message("能否帮我播放apple Music?")
        task = runtime.state.get_task(result["task_id"])
        link = service.get_task_run_link(result["task_id"])
        run = service.get_run(link["run_id"])
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        assistant = runtime.chat_session.get_assistant_message_for_task(result["task_id"])

        assert result["ok"] is True
        assert result["status"] == "completed"
        assert result["run_id"] == run["run_id"]
        assert result["agent_task"]["status"] == "completed"
        assert result["agent_task"]["summary"] == "已继续播放 Apple Music。当前：超时空辉夜姬 - Yachiyo。"
        assert result["agent_task"]["tool_calls"][-1]["tool_name"] == "media.apple_music_control"
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "已继续播放 Apple Music。当前：超时空辉夜姬 - Yachiyo。"
        assert assistant is not None
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == "已继续播放 Apple Music。当前：超时空辉夜姬 - Yachiyo。"
        assert control_calls == ["play"]
        assert run["status"] == "completed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_send_message_executes_direct_app_focus_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    runtime.agent_runtime_service = service
    focus_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct app focus task should not call model")
        ),
    )

    def fake_app_focus(app_name: str) -> dict:
        focus_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    try:
        result = api.send_message("切到微信")
        task = runtime.state.get_task(result["task_id"])
        link = service.get_task_run_link(result["task_id"])
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert result["ok"] is True
        assert result["status"] == "completed"
        assert result["agent_task"]["summary"] == "已切换到 WeChat。"
        assert result["agent_task"]["tool_calls"][-1]["tool_name"] == "app.focus"
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "已切换到 WeChat。"
        assert focus_calls == ["WeChat"]
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_send_message_executes_common_folder_with_reveal_path(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    runtime.agent_runtime_service = service
    reveal_calls: list[str] = []
    app_open_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct folder task should not call model")
        ),
    )

    def fake_reveal_path(path: str) -> dict:
        reveal_calls.append(path)
        return {
            "ok": True,
            "action": "desktop.reveal_path",
            "summary": f"Revealed {path}",
            "data": {
                "path": path,
                "open_target": "finder_reveal",
                "exists": True,
                "is_dir": True,
            },
        }

    def fake_app_open(app_name: str) -> dict:
        app_open_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.reveal_path", fake_reveal_path)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    try:
        result = api.send_message("可以帮我打开下载文件夹吗")
        task = runtime.state.get_task(result["task_id"])
        link = service.get_task_run_link(result["task_id"])
        run = service.get_run(link["run_id"])

        assert result["ok"] is True
        assert result["status"] == "completed"
        assert result["agent_task"]["summary"] == "已在 Finder 中显示：~/Downloads。"
        assert result["agent_task"]["tool_calls"][-1]["tool_name"] == "desktop.reveal_path"
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "已在 Finder 中显示：~/Downloads。"
        assert reveal_calls == ["~/Downloads"]
        assert app_open_calls == []
        assert run["status"] == "completed"
    finally:
        service.close()
        store.close()


def test_send_message_executes_direct_system_volume_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    runtime.agent_runtime_service = service
    volume_calls: list[tuple[str, object, object]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct volume task should not call model")
        ),
    )

    def fake_system_volume(action: str, *, level=None, step=None) -> dict:
        volume_calls.append((action, level, step))
        return {
            "ok": True,
            "action": "system.volume",
            "summary": "System volume set to 35%",
            "data": {
                "requested_action": action,
                "old_level": 20,
                "old_muted": False,
                "level": level,
                "muted": False,
                "changed": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.system_volume", fake_system_volume)
    try:
        result = api.send_message("把音量调到 35%")
        task = runtime.state.get_task(result["task_id"])
        link = service.get_task_run_link(result["task_id"])
        run = service.get_run(link["run_id"])

        assert result["ok"] is True
        assert result["status"] == "completed"
        assert result["agent_task"]["summary"] == "已把系统音量调到 35%。"
        assert result["agent_task"]["tool_calls"][-1]["tool_name"] == "system.volume"
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "已把系统音量调到 35%。"
        assert volume_calls == [("set", 35, None)]
        assert run["status"] == "completed"
    finally:
        service.close()
        store.close()


def test_send_message_executes_direct_screen_capture_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    runtime.agent_runtime_service = service
    capture_targets: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct screen task should not call model")
        ),
    )

    def fake_screen_capture(target_path) -> dict:
        capture_targets.append(str(target_path))
        return {
            "ok": True,
            "action": "screen.capture",
            "summary": "已截取当前屏幕。",
            "data": {
                "path": str(target_path),
                "mime_type": "image/png",
                "size_bytes": 10,
                "width": 100,
                "height": 80,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.screen_capture", fake_screen_capture)
    try:
        result = api.send_message("当前屏幕是什么")
        task = runtime.state.get_task(result["task_id"])
        link = service.get_task_run_link(result["task_id"])
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert result["ok"] is True
        assert result["status"] == "completed"
        assert result["agent_task"]["summary"] == "已截取当前屏幕。"
        assert result["agent_task"]["tool_calls"][-1]["tool_name"] == "screen.capture"
        assert result["agent_task"]["artifacts"][-1]["path"] == "screenshots/current-screen.png"
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "已截取当前屏幕。"
        assert capture_targets
        assert capture_targets[0].endswith("screenshots/current-screen.png")
        assert run["status"] == "completed"
        assert "artifact.created" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_send_message_projects_screen_capture_permission_recovery_actions(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    runtime.agent_runtime_service = service
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct screen permission failure should not call model")
        ),
    )

    class ScreenCapturePermissionError(RuntimeError):
        pass

    def fake_capture(_target):
        raise ScreenCapturePermissionError("screen recording permission denied")

    monkeypatch.setattr("apps.shell.agent.tools.desktop._desktop_platform", lambda: "macos")
    monkeypatch.setattr("apps.locald.screenshot.capture_screenshot_to_file", fake_capture)
    try:
        result = api.send_message("当前屏幕是什么")
        task = runtime.state.get_task(result["task_id"])
        link = service.get_task_run_link(result["task_id"])
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]
        tool_call = result["agent_task"]["tool_calls"][-1]

        assert result["ok"] is True
        assert result["status"] == "completed"
        assert "桌面操作未完成：screen recording permission denied" in result["agent_task"]["summary"]
        assert "缺少权限：screen_recording" in result["agent_task"]["summary"]
        assert tool_call["tool_name"] == "screen.capture"
        assert tool_call["status"] == "failed"
        assert tool_call["output_preview"]["permission_targets"] == ["screen_recording"]
        assert tool_call["output_preview"]["recovery_actions"] == [
            {
                "label": "打开屏幕录制权限",
                "tool": "app.open",
                "input": {"app_name": "屏幕录制权限"},
                "permission_target": "screen_recording",
                "risk_level": "low",
            }
        ]
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_send_message_requires_approval_for_direct_type_text_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    runtime.agent_runtime_service = service
    typed_texts: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct foreground input task should not call model")
        ),
    )

    def fake_type_text(text: str) -> dict:
        typed_texts.append(text)
        return {
            "ok": True,
            "action": "desktop.type_text",
            "summary": "Typed text",
            "data": {"text": text},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_type_text", fake_type_text)
    try:
        result = api.send_message("输入 你好八千代")
        task = runtime.state.get_task(result["task_id"])
        run = service.get_run(result["run_id"])
        assistant = runtime.chat_session.get_assistant_message_for_task(result["task_id"])

        assert result["ok"] is True
        assert result["status"] == "waiting_approval"
        assert result["agent_task"]["status"] == "waiting_approval"
        assert result["agent_task"]["needs_user_action"] is True
        assert result["agent_task"]["pending_approvals"][0]["tool_name"] == "desktop.type_text"
        assert task is not None
        assert task.status == TaskStatus.RUNNING
        assert assistant is not None
        assert assistant.status == MessageStatus.PROCESSING
        assert run["status"] == "approval_required"
        assert run["pending_approval"]["tool"] == "desktop.type_text"
        assert typed_texts == []
    finally:
        service.close()
        store.close()


def test_send_message_is_idempotent_for_client_message_id(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        first = api.send_message("你好", client_message_id="client-msg-1")
        second = api.send_message("你好", client_message_id="client-msg-1")

        assert first["ok"] is True
        assert second["ok"] is True
        assert second["idempotent"] is True
        assert second["message_id"] == first["message_id"]
        assert second["task_id"] == first["task_id"]
        assert len(runtime.state.list_tasks()) == 1
        assert len(runtime.chat_session.get_messages()) == 1
        assert runtime.chat_session.get_messages()[0].metadata["client_message_id"] == "client-msg-1"
    finally:
        store.close()


def test_send_message_rejects_sensitive_client_message_id_before_persistence(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    leaked_client_message_id = "sk-client-message-id-secret123456"
    try:
        result = api.send_message("你好", client_message_id=leaked_client_message_id)

        assert result["ok"] is False
        assert "client_message_id/idempotency_key" in result["error"]
        assert leaked_client_message_id not in result["error"]
        assert runtime.chat_session.get_messages() == []
        assert runtime.state.list_tasks() == []
        assert verify_secret_redaction(paths=[tmp_path]) == []
    finally:
        store.close()


def test_send_message_rejects_when_native_agent_unavailable(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    runtime.task_runner = SimpleNamespace(
        executor=SimpleNamespace(
            name="NativeAgentUnavailableExecutor",
            reason="Native Agent 当前未就绪，请先配置并选择默认对话模型。",
            code="native_agent_not_ready",
            reason_code="model_profile_required",
        )
    )
    try:
        result = api.send_message("你好")

        assert result == {
            "ok": False,
            "code": "native_agent_not_ready",
            "reason": "model_profile_required",
            "error": "Native Agent 当前未就绪，请先配置并选择默认对话模型。",
        }
        assert runtime.state.list_tasks() == []
        assert runtime.chat_session.get_messages() == []
    finally:
        store.close()


def test_running_main_chat_task_projects_native_tool_approval(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    task = runtime.state.create_task(
        "需要修改文件",
        chat_session_id=runtime.chat_session.session_id,
    )
    runtime.state.update_task_status(task.task_id, TaskStatus.RUNNING)
    user_message_id = runtime.chat_session.add_user_message("需要修改文件")
    runtime.chat_session.link_message_to_task(user_message_id, task.task_id)

    class FakeNativeRunService:
        def get_task_run_link(self, task_id):
            assert task_id == task.task_id
            return {"task_id": task_id, "run_id": "main_chat_run_approval", "session_id": runtime.chat_session.session_id}

        def get_run(self, run_id):
            assert run_id == "main_chat_run_approval"
            return {
                "run_id": run_id,
                "kind": "main_chat_run",
                "status": "approval_required",
                "run_group_id": "run_group_main",
                "result": "等待审批：workspace.write_patch",
                "pending_approval": {
                    "approval_id": "approval_patch",
                    "tool": "workspace.write_patch",
                    "input_preview": {"path": "src/app.py", "patch": "@@ demo"},
                },
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeNativeRunService())
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    try:
        payload = api.get_messages()

        assistant = next(message for message in payload["messages"] if message["role"] == "assistant")
        assert assistant["status"] == "processing"
        assert assistant["metadata"]["run_status"] == "approval_required"
        assert assistant["metadata"]["run_id"] == "main_chat_run_approval"
        assert assistant["metadata"]["pending_approval"]["tool"] == "workspace.write_patch"
        assert assistant["metadata"]["pending_approval"]["input_preview"]["path"] == "src/app.py"
        assert "需要你确认一次工具调用" in assistant["content"]
        assert "工具：workspace.write_patch" in assistant["content"]
        assert "关联任务：需要修改文件" in assistant["content"]
        assert "请求摘要" in assistant["content"]
        assert payload["approval_count"] == 1
        assert assistant["activity_events"][0]["event_id"] == f"{task.task_id}-main-chat-approval-required"
        assert assistant["activity_events"][0]["status"] == "approval_required"
        assert assistant["activity_events"][0]["metadata"]["pending_approval"]["tool"] == "workspace.write_patch"
    finally:
        activity_store.close()
        store.close()


def test_running_main_chat_task_clears_approval_projection_after_resume(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    task = runtime.state.create_task(
        "需要运行命令",
        chat_session_id=runtime.chat_session.session_id,
    )
    runtime.state.update_task_status(task.task_id, TaskStatus.RUNNING)
    user_message_id = runtime.chat_session.add_user_message("需要运行命令")
    runtime.chat_session.link_message_to_task(user_message_id, task.task_id)

    class FakeNativeRunService:
        status = "approval_required"

        def get_task_run_link(self, task_id):
            assert task_id == task.task_id
            return {"task_id": task_id, "run_id": "main_chat_run_resume", "session_id": runtime.chat_session.session_id}

        def get_run(self, run_id):
            assert run_id == "main_chat_run_resume"
            pending = (
                {
                    "approval_id": "approval_terminal",
                    "tool": "terminal.run",
                    "input_preview": {"command": "python -V"},
                }
                if self.status == "approval_required"
                else {}
            )
            return {
                "run_id": run_id,
                "kind": "main_chat_run",
                "status": self.status,
                "run_group_id": "run_group_main",
                "result": "等待审批：terminal.run" if pending else "",
                "pending_approval": pending,
            }

    service = FakeNativeRunService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    try:
        first = api.get_messages()
        approval = next(message for message in first["messages"] if message["role"] == "assistant")
        assert approval["metadata"]["run_status"] == "approval_required"
        assert approval["metadata"]["pending_approval"]["tool"] == "terminal.run"

        service.status = "running"
        resumed = api.get_messages()

        assistant = next(message for message in resumed["messages"] if message["role"] == "assistant")
        assert assistant["status"] == "processing"
        assert assistant["content"] == ""
        assert assistant["metadata"]["run_status"] == "processing"
        assert assistant["metadata"]["pending_approval"] == {}
        assert assistant["metadata"]["run_progress_title"] == "审批已通过"
        events = activity_store.list_events(task_id=task.task_id, limit=5, key_only=False)
        assert len(events) == 1
    finally:
        activity_store.close()
        store.close()


def test_agent_mention_creates_agent_run_without_general_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
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
    service = _make_agent_runtime_service(tmp_path)
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


def test_workflow_mention_creates_workflow_run_from_chat(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    responses = iter(["Design output", "Code output"])

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
        assert workflow_result["runnable_command"] is True
        assert workflow_result["workflow_run_id"]
        assert workflow_result["status"] == "processing"
        run = _wait_for_agent_run(service, workflow_result["workflow_run_id"])
        assert run["status"] == "completed"
        assert run["result"] == "Code output"
        workflow_message = _wait_for_assistant_content_contains(api, "Code output")
        assert workflow_message["metadata"]["runnable_kind"] == "workflow"
        assert workflow_message["metadata"]["workflow_run_id"] == workflow_result["workflow_run_id"]
        workflow_messages = api.get_messages()["messages"]
        child_messages = [
            message
            for message in workflow_messages
            if message["metadata"].get("workflow_parent_run_id") == workflow_result["workflow_run_id"]
        ]
        assert [message["metadata"]["sender"]["nickname"] for message in child_messages] == ["Design", "Code"]
        assert child_messages[0]["content"].startswith("Design 已完成 Workflow 节点。")
        assert child_messages[1]["content"].startswith("Code 已完成 Workflow 节点。")
        current = next(
            item for item in api.list_sessions()["sessions"]
            if item["session_id"] == runtime.chat_session.session_id
        )
        assert current["conversation_kind"] == "workflow"
        assert current["runnable_id"] == workflow["workflow_id"]
        group = service.get_run_group(run["run_group_id"])
        assert group["status"] == "completed"
        assert run["run_id"] in group["child_run_ids"]
        assert len(group["child_run_ids"]) == 3
        stored = store.get_session(runtime.chat_session.session_id)
        assert stored is not None
        assert stored.conversation_kind == "workflow"
    finally:
        service.close()
        store.close()


def test_workflow_chat_syncs_child_agents_as_group_timeline_messages(tmp_path, monkeypatch):
    api, _runtime, store = _make_api(tmp_path)
    workflow_run_id = "workflow_run_visible"
    run_group_id = "run_group_visible"
    design_run_id = "agent_run_design"
    coding_run_id = "agent_run_coding"
    manual_run_id = "agent_run_manual_followup"
    workflow = {"id": "workflow_visible", "name": "Visible Workflow", "nickname": "Visible Flow", "kind": "workflow"}
    design = {"id": "agent_design", "name": "Design Agent", "nickname": "Design", "kind": "agent"}
    coding = {"id": "agent_coding", "name": "Coding Agent", "nickname": "Code", "kind": "agent"}
    started_event = {
        "event": "workflow.run.started",
        "detail": workflow["name"],
        "workflow_path": [
            {"id": "start", "kind": "start", "label": "Start"},
            {"id": "design", "kind": "agent", "label": "设计方案", "task": "整理页面结构"},
            {"id": "coding", "kind": "agent", "label": "编码实现", "task": "实现并验证功能"},
        ],
    }

    class FakeWorkflowService:
        def __init__(self):
            self.runs = {
                workflow_run_id: {
                    "run_id": workflow_run_id,
                    "run_group_id": run_group_id,
                    "kind": "workflow_run",
                    "runnable_id": workflow["id"],
                    "runnable_name": workflow["name"],
                    "status": "processing",
                    "result": "",
                    "timeline": [
                        started_event,
                        {
                            "event": "workflow.node.agent",
                            "detail": "设计方案",
                            "workflow_node_id": "design",
                            "workflow_node_kind": "agent",
                            "workflow_node_label": "设计方案",
                            "workflow_node_task": "整理页面结构",
                            "child_run_id": design_run_id,
                            "status": "completed",
                        },
                    ],
                },
                design_run_id: {
                    "run_id": design_run_id,
                    "run_group_id": run_group_id,
                    "kind": "agent_run",
                    "runnable_id": design["id"],
                    "runnable_name": design["name"],
                    "user_goal": "整理页面结构",
                    "status": "completed",
                    "result": "页面结构已经整理完成。",
                    "timeline": [],
                    "artifacts": [],
                    "pending_approval": {},
                },
                coding_run_id: {
                    "run_id": coding_run_id,
                    "run_group_id": run_group_id,
                    "kind": "agent_run",
                    "runnable_id": coding["id"],
                    "runnable_name": coding["name"],
                    "user_goal": "实现并验证功能",
                    "status": "running",
                    "result": "",
                    "timeline": [{"event": "agent.run.started", "detail": coding["name"]}],
                    "artifacts": [],
                    "pending_approval": {},
                },
                manual_run_id: {
                    "run_id": manual_run_id,
                    "run_group_id": run_group_id,
                    "kind": "agent_run",
                    "runnable_id": coding["id"],
                    "runnable_name": coding["name"],
                    "user_goal": "这是后续手动任务，不属于 Workflow",
                    "status": "running",
                    "result": "",
                    "timeline": [],
                    "artifacts": [],
                    "pending_approval": {},
                },
            }

        def get_run(self, run_id):
            return self.runs[run_id]

        def get_run_group(self, group_id):
            assert group_id == run_group_id
            return {
                "run_group_id": run_group_id,
                "child_run_ids": [workflow_run_id, design_run_id, coding_run_id, manual_run_id],
            }

        def resolve_runnable(self, *, runnable_id="", name=""):
            return {workflow["id"]: workflow, design["id"]: design, coding["id"]: coding}.get(runnable_id)

    service = FakeWorkflowService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        initial_title, initial_detail = api._workflow_run_progress_from_timeline(
            api._participant_for_runnable(workflow),
            {**service.runs[workflow_run_id], "timeline": [started_event]},
        )
        assert initial_title == "Workflow 已开始"
        assert "设计方案 → 编码实现" in initial_detail

        workflow_message_id = api._session.add_assistant_message(
            "",
            metadata={
                "sender": api._participant_for_runnable(workflow),
                "runnable_kind": "workflow",
                "runnable_id": workflow["id"],
                "run_id": workflow_run_id,
                "workflow_run_id": workflow_run_id,
                "run_group_id": run_group_id,
                "run_status": "processing",
                "workflow_status": "processing",
            },
        )
        api._session.update_assistant_message(workflow_message_id, "", status=MessageStatus.PROCESSING)

        first = api.get_messages()["messages"]
        workflow_message = next(message for message in first if message["id"] == workflow_message_id)
        child_messages = [
            message for message in first
            if message["metadata"].get("workflow_parent_run_id") == workflow_run_id
        ]
        design_message = next(message for message in child_messages if message["metadata"]["run_id"] == design_run_id)
        coding_message = next(message for message in child_messages if message["metadata"]["run_id"] == coding_run_id)

        assert len(child_messages) == 2
        assert workflow_message["metadata"]["run_progress_title"] == "Workflow 正在执行 Agent"
        assert "节点「编码实现」：实现并验证功能" in workflow_message["metadata"]["run_progress_detail"]
        assert design_message["status"] == "completed"
        assert design_message["content"] == (
            "Design 已完成 Workflow 节点。\n"
            "节点：设计方案\n"
            "任务：整理页面结构\n\n"
            "页面结构已经整理完成。"
        )
        assert coding_message["status"] == "processing"
        assert coding_message["content"] == ""
        assert coding_message["metadata"]["run_progress_title"] == "Workflow 正在执行 Agent"
        assert "节点「编码实现」：实现并验证功能" in coding_message["metadata"]["run_progress_detail"]

        second = api.get_messages()["messages"]
        assert len([
            message for message in second
            if message["metadata"].get("workflow_parent_run_id") == workflow_run_id
        ]) == 2

        service.runs[coding_run_id] = {
            **service.runs[coding_run_id],
            "status": "completed",
            "result": "编码与验证完成。",
        }
        service.runs[workflow_run_id] = {
            **service.runs[workflow_run_id],
            "status": "completed",
            "result": "编码与验证完成。",
            "timeline": [
                *service.runs[workflow_run_id]["timeline"],
                {
                    "event": "workflow.node.agent",
                    "detail": "编码实现",
                    "workflow_node_id": "coding",
                    "workflow_node_kind": "agent",
                    "workflow_node_label": "编码实现",
                    "workflow_node_task": "实现并验证功能",
                    "child_run_id": coding_run_id,
                    "status": "completed",
                },
                {"event": "workflow.run.completed", "detail": workflow["name"]},
            ],
        }

        completed = api.get_messages()["messages"]
        completed_coding = next(message for message in completed if message["metadata"].get("run_id") == coding_run_id)
        completed_workflow = next(message for message in completed if message["id"] == workflow_message_id)

        assert completed_coding["status"] == "completed"
        assert completed_coding["content"].endswith("编码与验证完成。")
        assert completed_workflow["status"] == "completed"
        assert completed_workflow["content"].startswith("Visible Flow 已完成。")
    finally:
        store.close()


def test_workflow_cancelled_summary_message_is_terminal_failed(tmp_path):
    api, _runtime, store = _make_api(tmp_path)

    class FakeWorkflowService:
        def get_run(self, _run_id):
            raise KeyError(_run_id)

        def resolve_runnable(self, *, runnable_id="", name=""):
            return None

    try:
        run = {
            "run_id": "workflow_run_cancelled",
            "run_group_id": "run_group_cancelled",
            "kind": "workflow_run",
            "runnable_id": "workflow_demo",
            "status": "cancelled",
            "result": "Workflow 审批已拒绝：先暂停",
            "timeline": [
                {"event": "workflow.run.started", "detail": "Demo Workflow"},
                {"event": "workflow.node.approval_rejected", "detail": "先暂停", "status": "cancelled"},
                {"event": "workflow.run.cancelled", "detail": "先暂停", "status": "cancelled"},
            ],
        }
        runnable = {"id": "workflow_demo", "name": "Demo Workflow", "kind": "workflow"}

        assistant_ids = api._append_workflow_run_messages(FakeWorkflowService(), run, runnable)
        messages = api.get_messages()["messages"]
        summary = next(message for message in messages if message["id"] == assistant_ids[-1])

        assert summary["status"] == "failed"
        assert summary["content"] == "Demo Workflow 已取消。\n\nWorkflow 审批已拒绝：先暂停"
        assert summary["error"] == summary["content"]
        assert summary["metadata"]["workflow_status"] == "cancelled"
    finally:
        store.close()


def test_workflow_failed_summary_message_includes_failed_node_hint(tmp_path):
    api, _runtime, store = _make_api(tmp_path)

    class FakeWorkflowService:
        def get_run(self, _run_id):
            raise KeyError(_run_id)

        def resolve_runnable(self, *, runnable_id="", name=""):
            return None

    try:
        run = {
            "run_id": "workflow_run_failed",
            "run_group_id": "run_group_failed",
            "kind": "workflow_run",
            "runnable_id": "workflow_demo",
            "status": "failed",
            "result": "model exploded",
            "timeline": [
                {"event": "workflow.run.started", "detail": "Demo Workflow"},
                {
                    "event": "workflow.run.failed",
                    "detail": "Failing Agent: model exploded",
                    "workflow_node_id": "agent-a",
                    "workflow_node_kind": "agent",
                    "workflow_node_label": "Failing Agent",
                    "status": "failed",
                },
            ],
        }
        runnable = {"id": "workflow_demo", "name": "Demo Workflow", "kind": "workflow"}

        assistant_ids = api._append_workflow_run_messages(FakeWorkflowService(), run, runnable)
        messages = api.get_messages()["messages"]
        summary = next(message for message in messages if message["id"] == assistant_ids[-1])

        assert summary["status"] == "failed"
        assert summary["content"] == "Demo Workflow 执行失败。\n失败节点：Failing Agent（agent）\n\nmodel exploded"
        assert summary["error"] == summary["content"]
        assert summary["metadata"]["workflow_status"] == "failed"
    finally:
        store.close()


def test_workflow_tool_failure_writes_child_and_parent_failure_hints(tmp_path, monkeypatch):
    api, _runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        assert any((tool.get("function") or {}).get("name") == "workspace_read" for tool in tools or [])
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "python3 dangerous.py"}),
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Tool Failing Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["workspace.read"]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Tool Failure Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Tool Failing Agent", "agent_id": agent["agent_id"]},
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "agent"},
                    {"source": "agent", "target": "summary"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Run risky workflow"})
        runnable = service.resolve_runnable(runnable_id=workflow["workflow_id"]) or {}
        group = service.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        child = service.get_run(child_run_id)

        assert run["status"] == "failed"
        assert run["result"] == "Agent 试图调用未授权工具：terminal.run"
        failed_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.failed")
        assert failed_event["workflow_node_id"] == "agent"
        assert failed_event["workflow_node_kind"] == "agent"
        assert failed_event["workflow_node_label"] == "Tool Failing Agent"
        assert failed_event["child_run_id"] == child_run_id
        denied_event = next(event for event in child["timeline"] if event["event"] == "agent.tool.denied")
        assert denied_event["detail"] == "terminal.run"

        assistant_ids = api._append_workflow_run_messages(service, run, runnable)
        messages = api.get_messages()["messages"]
        child_message = next(
            message
            for message in messages
            if message["id"] in assistant_ids and message["metadata"].get("runnable_kind") == "agent"
        )
        workflow_message = next(
            message
            for message in messages
            if message["id"] in assistant_ids and message["metadata"].get("runnable_kind") == "workflow"
        )

        assert child_message["status"] == "failed"
        assert child_message["content"] == "Agent 试图调用未授权工具：terminal.run"
        assert child_message["error"] == child_message["content"]
        assert child_message["metadata"]["run_id"] == child_run_id
        assert child_message["metadata"]["workflow_run_id"] == run["run_id"]
        assert child_message["metadata"]["workflow_node"] == "Tool Failing Agent"
        assert child_message["metadata"]["run_status"] == "failed"
        assert workflow_message["status"] == "failed"
        assert workflow_message["content"] == (
            "Tool Failure Flow 执行失败。\n"
            "失败节点：Tool Failing Agent（agent）\n\n"
            "Agent 试图调用未授权工具：terminal.run"
        )
        assert workflow_message["error"] == workflow_message["content"]
        assert workflow_message["metadata"]["run_id"] == run["run_id"]
        assert workflow_message["metadata"]["run_status"] == "failed"
        assert workflow_message["metadata"]["workflow_status"] == "failed"
    finally:
        service.close()
        store.close()


def test_workflow_chat_messages_carry_artifact_metadata(tmp_path):
    api, _runtime, store = _make_api(tmp_path)

    class FakeWorkflowService:
        def get_run(self, run_id):
            assert run_id == "agent_run_design"
            return {
                "run_id": run_id,
                "run_group_id": "run_group_artifacts",
                "kind": "agent_run",
                "runnable_id": "agent_design",
                "status": "completed",
                "result": "Design Agent 完成草案。",
                "artifacts": [
                    {"kind": "context", "path": "agent-context.md"},
                    {"kind": "tool_artifact", "path": "design-draft.md"},
                ],
            }

        def resolve_runnable(self, *, runnable_id="", name=""):
            assert runnable_id == "agent_design"
            return {"id": "agent_design", "name": "Design Agent", "kind": "agent"}

    try:
        run = {
            "run_id": "workflow_run_artifacts",
            "run_group_id": "run_group_artifacts",
            "kind": "workflow_run",
            "runnable_id": "workflow_demo",
            "status": "completed",
            "result": "Workflow 已完成并生成交付物。",
            "artifacts": [
                {"kind": "workflow_artifact", "path": "reports/summary.md"},
            ],
            "timeline": [
                {"event": "workflow.run.started", "detail": "Demo Workflow"},
                {
                    "event": "workflow.node.agent",
                    "detail": "Design",
                    "child_run_id": "agent_run_design",
                    "status": "completed",
                },
                {"event": "workflow.run.completed", "detail": "Demo Workflow"},
            ],
        }
        runnable = {"id": "workflow_demo", "name": "Demo Workflow", "kind": "workflow"}

        assistant_ids = api._append_workflow_run_messages(FakeWorkflowService(), run, runnable)
        messages = api.get_messages()["messages"]
        child = next(message for message in messages if message["id"] == assistant_ids[0])
        summary = next(message for message in messages if message["id"] == assistant_ids[-1])

        assert child["content"] == "Design Agent 完成草案。\n产物：1 个，见运行详情。"
        assert child["metadata"]["run_artifact_count"] == 1
        assert child["metadata"]["run_artifacts"] == [{"path": "design-draft.md", "kind": "tool_artifact"}]
        assert summary["content"] == "Demo Workflow 已完成。\n产物：1 个，见运行详情。"
        assert summary["metadata"]["run_artifact_count"] == 1
        assert summary["metadata"]["run_artifacts"] == [{"path": "reports/summary.md", "kind": "workflow_artifact"}]
    finally:
        store.close()


def test_workflow_approval_chat_message_carries_pending_details(tmp_path, monkeypatch):
    api, _runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {"content": "Design checkpoint ready"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({
            "name": "Design Agent",
            "model_mode": "custom_api",
            "model_config": model_config,
        })
        workflow = service.create_workflow(
            {
                "name": "Human Gate Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Design", "agent_id": agent["agent_id"]}},
                    {"id": "gate", "type": "approval", "data": {"label": "人工确认"}},
                ],
                "edges": [
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "gate"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "确认设计后继续"})
        runnable = service.resolve_runnable(runnable_id=workflow["workflow_id"])

        assert run["status"] == "approval_required"
        api._append_workflow_run_messages(service, run, runnable or {})

        messages = api.get_messages()["messages"]
        workflow_message = next(message for message in messages if message["metadata"].get("runnable_kind") == "workflow")
        metadata = workflow_message["metadata"]

        assert "需要你确认一个 Workflow 审批节点" in workflow_message["content"]
        assert workflow_message["status"] == "processing"
        assert metadata["run_id"] == run["run_id"]
        assert metadata["workflow_run_id"] == run["run_id"]
        assert metadata["run_status"] == "approval_required"
        assert metadata["workflow_status"] == "approval_required"
        assert metadata["pending_approval"]["tool"] == "workflow.approval"
        assert metadata["pending_approval"]["input_preview"]["checkpoint"] == "人工确认"
        assert metadata["pending_approval"]["input_preview"]["context"] == "Design checkpoint ready"
    finally:
        service.close()
        store.close()


def test_workflow_waiting_for_child_agent_approval_counts_only_child(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    responses = iter(["approval", "Child Agent done"])

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        response = next(responses)
        if response == "approval":
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf waiting"}),
                        },
                    }
                ],
            }
        return {"content": response}

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent({
            "name": "Needs Approval",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
            "tool_policy": {"allowed_tools": ["terminal.run"]},
            "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
        })
        workflow = service.create_workflow(
            {
                "name": "Child Approval Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "agent", "type": "agent", "data": {"label": "Needs Approval", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "跑需要工具审批的流程"})
        runnable = service.resolve_runnable(runnable_id=workflow["workflow_id"])

        assert run["status"] == "approval_required"
        assert run["pending_approval"] == {}
        api._append_workflow_run_messages(service, run, runnable or {})

        payload = api.get_messages()
        session_info = api.get_session_info()
        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == runtime.chat_session.session_id)
        messages = payload["messages"]
        child_message = next(message for message in messages if message["metadata"].get("runnable_kind") == "agent")
        workflow_message = next(message for message in messages if message["metadata"].get("runnable_kind") == "workflow")

        assert payload["processing_count"] == 2
        assert payload["approval_count"] == 1
        assert session_info["approval_count"] == 1
        assert current["approval_count"] == 1
        assert child_message["status"] == "processing"
        assert child_message["metadata"]["run_status"] == "approval_required"
        assert child_message["metadata"]["pending_approval"]["tool"] == "terminal.run"
        assert workflow_message["status"] == "processing"
        assert "正在等待子 Agent 审批" in workflow_message["content"]
        assert "等待对象：Needs Approval" in workflow_message["content"]
        assert "Workflow 节点：Needs Approval（agent）" in workflow_message["content"]
        assert "审批工具：terminal.run" in workflow_message["content"]
        assert workflow_message["metadata"]["run_status"] == "processing"
        assert workflow_message["metadata"]["workflow_status"] == "approval_required"
        assert workflow_message["metadata"]["pending_approval"] == {}

        group = service.get_run_group(run["run_group_id"])
        child_run_ids = [run_id for run_id in group["child_run_ids"] if run_id != run["run_id"]]
        assert len(child_run_ids) == 1
        assert workflow_message["metadata"]["workflow_waiting_child_run_id"] == child_run_ids[0]
        assert workflow_message["metadata"]["workflow_waiting_node"] == "Needs Approval"
        assert workflow_message["metadata"]["workflow_waiting_tool"] == "terminal.run"
        assert workflow_message["metadata"]["workflow_waiting_pending_approval"]["tool"] == "terminal.run"
        assert workflow_message["metadata"]["workflow_waiting_pending_approval"]["input_preview"]["command"] == "printf waiting"

        approved_child = service.approve_run_approval(child_run_ids[0])
        parent_after = service.get_run(run["run_id"])

        assert approved_child["status"] == "completed"
        assert approved_child["result"] == "Child Agent done"
        assert parent_after["status"] == "completed"
        assert parent_after["result"] == "Child Agent done"

        payload_after = api.get_messages()
        messages_after = payload_after["messages"]
        child_after = next(
            message
            for message in messages_after
            if message["metadata"].get("runnable_kind") == "agent"
        )
        workflow_after = next(
            message
            for message in messages_after
            if message["metadata"].get("runnable_kind") == "workflow"
        )

        assert payload_after["processing_count"] == 0
        assert payload_after["approval_count"] == 0
        assert api.get_session_info()["approval_count"] == 0
        assert child_after["status"] == "completed"
        assert child_after["content"] == (
            "Needs Approval 已完成 Workflow 节点。\n"
            "节点：Needs Approval\n"
            "任务：跑需要工具审批的流程\n\n"
            "Child Agent done"
        )
        assert child_after["metadata"]["run_status"] == "completed"
        assert child_after["metadata"]["pending_approval"] == {}
        assert workflow_after["status"] == "completed"
        assert workflow_after["content"].startswith("Child Approval Flow 已完成。")
        assert "产物：" not in workflow_after["content"]
        assert workflow_after["content"].endswith("Child Agent done")
        assert workflow_after["metadata"]["run_status"] == "completed"
        assert workflow_after["metadata"]["workflow_status"] == "completed"
        assert workflow_after["metadata"]["pending_approval"] == {}
        assert workflow_after["metadata"]["run_artifact_count"] == 0
        assert workflow_after["metadata"]["run_artifacts"] == []
        assert "workflow_waiting_child_run_id" not in workflow_after["metadata"]
        assert "workflow_waiting_node" not in workflow_after["metadata"]
        assert "workflow_waiting_tool" not in workflow_after["metadata"]
        assert "workflow_waiting_pending_approval" not in workflow_after["metadata"]
    finally:
        service.close()
        store.close()


def test_workflow_child_consecutive_approvals_keep_chat_prompt_visible(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
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
                            "arguments": json.dumps({"command": "printf workflow-chat-first"}),
                        },
                    },
                    {
                        "id": "call_second_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf workflow-chat-second"}),
                        },
                    },
                ],
            }
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert any("workflow-chat-first" in message.get("content", "") for message in tool_messages)
        assert any("workflow-chat-second" in message.get("content", "") for message in tool_messages)
        return {"content": "Workflow child chat approvals completed"}

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent({
            "name": "Consecutive Approval Child",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
            "tool_policy": {"allowed_tools": ["terminal.run"]},
            "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
        })
        workflow = service.create_workflow(
            {
                "name": "Child Consecutive Approval Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Consecutive Approval Child", "agent_id": agent["agent_id"]},
                    },
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "跑两次工具审批"})
        runnable = service.resolve_runnable(runnable_id=workflow["workflow_id"])

        assert run["status"] == "approval_required"
        api._append_workflow_run_messages(service, run, runnable or {})
        group = service.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])

        first_payload = api.get_messages()
        first_workflow = next(
            message for message in first_payload["messages"]
            if message["metadata"].get("runnable_kind") == "workflow"
        )
        assert first_payload["approval_count"] == 1
        assert first_workflow["metadata"]["workflow_waiting_pending_approval"]["input_preview"]["command"] == (
            "printf workflow-chat-first"
        )

        after_first = service.approve_run_approval(child_run_id)
        assert after_first["status"] == "approval_required"
        second_payload = api.get_messages()
        second_messages = second_payload["messages"]
        second_child = next(
            message for message in second_messages
            if message["metadata"].get("runnable_kind") == "agent"
        )
        second_workflow = next(
            message for message in second_messages
            if message["metadata"].get("runnable_kind") == "workflow"
        )
        current = next(
            item for item in api.list_sessions()["sessions"]
            if item["session_id"] == runtime.chat_session.session_id
        )

        assert second_payload["processing_count"] == 2
        assert second_payload["approval_count"] == 1
        assert api.get_session_info()["approval_count"] == 1
        assert current["approval_count"] == 1
        assert second_child["status"] == "processing"
        assert second_child["metadata"]["run_status"] == "approval_required"
        assert second_child["metadata"]["pending_approval"]["input_preview"]["command"] == "printf workflow-chat-second"
        assert second_workflow["status"] == "processing"
        assert "正在等待子 Agent 审批" in second_workflow["content"]
        assert second_workflow["metadata"]["workflow_status"] == "approval_required"
        assert second_workflow["metadata"]["workflow_waiting_child_run_id"] == child_run_id
        assert second_workflow["metadata"]["workflow_waiting_pending_approval"]["input_preview"]["command"] == (
            "printf workflow-chat-second"
        )

        after_second = service.approve_run_approval(child_run_id)
        assert after_second["status"] == "completed"
        final_payload = api.get_messages()
        final_workflow = next(
            message for message in final_payload["messages"]
            if message["metadata"].get("runnable_kind") == "workflow"
        )

        assert final_payload["processing_count"] == 0
        assert final_payload["approval_count"] == 0
        assert final_workflow["status"] == "completed"
        assert final_workflow["metadata"]["workflow_status"] == "completed"
        assert "workflow_waiting_pending_approval" not in final_workflow["metadata"]
    finally:
        service.close()
        store.close()


def test_workflow_child_approval_counts_when_child_message_is_missing(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)

    class FakeRunnableService:
        def get_run(self, run_id):
            if run_id == "workflow_run_parent":
                return {
                    "run_id": run_id,
                    "run_group_id": "run_group_workflow",
                    "kind": "workflow_run",
                    "status": "approval_required",
                    "result": "",
                    "timeline": [
                        {"event": "workflow.run.started", "detail": "Demo Workflow"},
                        {
                            "event": "workflow.run.approval_required",
                            "detail": "Coding Agent",
                            "child_run_id": "child_run_waiting",
                            "workflow_node_id": "coding",
                            "workflow_node_kind": "agent",
                            "workflow_node_label": "Coding Agent",
                            "status": "approval_required",
                        },
                    ],
                    "pending_approval": {},
                    "runnable": {"id": "workflow_demo", "name": "Demo Workflow", "kind": "workflow"},
                }
            if run_id == "child_run_waiting":
                return {
                    "run_id": run_id,
                    "run_group_id": "run_group_workflow",
                    "kind": "agent_run",
                    "status": "approval_required",
                    "runnable_name": "Coding Agent",
                    "pending_approval": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "python -V"},
                    },
                }
            raise KeyError(run_id)

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("@Demo Workflow 跑一下")
        assistant_id = runtime.chat_session.add_assistant_message(
            "",
            metadata={
                "sender": {"name": "Demo Workflow", "kind": "workflow"},
                "runnable_kind": "workflow",
                "runnable_id": "workflow_demo",
                "run_id": "workflow_run_parent",
                "run_group_id": "run_group_workflow",
                "run_status": "processing",
                "workflow_status": "approval_required",
                "pending_approval": {},
            },
        )
        runtime.chat_session.update_assistant_message(
            assistant_id,
            "",
            status=MessageStatus.PROCESSING,
        )

        payload = api.get_messages()
        session_info = api.get_session_info()
        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)
        workflow_message = next(
            message
            for message in payload["messages"]
            if message["metadata"].get("runnable_kind") == "workflow"
        )

        assert payload["processing_count"] == 1
        assert payload["approval_count"] == 1
        assert session_info["approval_count"] == 1
        assert current["approval_count"] == 1
        assert workflow_message["status"] == "processing"
        assert "正在等待子 Agent 审批" in workflow_message["content"]
        assert workflow_message["metadata"]["run_status"] == "processing"
        assert workflow_message["metadata"]["workflow_status"] == "approval_required"
        assert workflow_message["metadata"]["pending_approval"] == {}
        assert workflow_message["metadata"]["workflow_waiting_child_run_id"] == "child_run_waiting"
        assert workflow_message["metadata"]["workflow_waiting_node"] == "Coding Agent"
        assert workflow_message["metadata"]["workflow_waiting_tool"] == "terminal.run"
        assert workflow_message["metadata"]["workflow_waiting_pending_approval"]["tool"] == "terminal.run"
        assert workflow_message["metadata"]["workflow_waiting_pending_approval"]["input_preview"]["command"] == "python -V"
    finally:
        store.close()


def test_agent_cancelled_message_is_terminal_failed(tmp_path):
    api, _runtime, store = _make_api(tmp_path)
    try:
        run = {
            "run_id": "agent_run_cancelled",
            "run_group_id": "run_group_cancelled",
            "status": "cancelled",
            "result": "工具审批已拒绝：先暂停",
        }
        runnable = {"id": "agent_demo", "name": "Demo Agent", "kind": "agent"}

        assistant_id = api._append_agent_run_message(run, runnable)
        messages = api.get_messages()["messages"]
        message = next(item for item in messages if item["id"] == assistant_id)

        assert message["status"] == "failed"
        assert message["content"] == "工具审批已拒绝：先暂停"
        assert message["error"] == message["content"]
        assert message["metadata"]["run_status"] == "cancelled"
    finally:
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
    service = _make_agent_runtime_service(tmp_path)
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


def test_main_chat_runnable_id_creates_normal_chat_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)

    def fail_agent_runtime_service():
        raise AssertionError("main chat entry must not resolve as a runnable command")

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", fail_agent_runtime_service)
    try:
        result = api.send_runnable_message_in_session(
            "s1",
            "打开 Apple Music",
            runnable_id=MAIN_CHAT_AGENT_ID,
            client_message_id="main-chat-entry-1",
            metadata={
                "source": "launcher",
                "launcher_mode": "bubble",
                "client_message_id": "untrusted-metadata-id",
            },
        )

        assert result["ok"] is True
        assert result["session_id"] == "s1"
        assert result["task_id"]
        assert "runnable_command" not in result
        assert "run_id" not in result
        tasks = runtime.state.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].task_id == result["task_id"]
        assert runtime.chat_session.get_messages()[0].task_id == result["task_id"]
        assert runtime.chat_session.get_messages()[0].metadata == {
            "source": "launcher",
            "launcher_mode": "bubble",
            "client_message_id": "main-chat-entry-1",
        }
    finally:
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

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
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
        "category": "design",
        "description": "负责 UI 方案、视觉验收和信息架构。",
        "output_contract": "markdown",
        "tool_policy": {
            "allowed_tools": ["workspace.list", "workspace.read", "artifact.write"],
            "approval_required": {"terminal.run": True, "workspace.write_patch": True},
        },
    }
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "Code",
        "kind": "agent",
        "enabled": True,
        "category": "coding",
        "description": "负责代码实现、补丁和验证脚本。",
        "output_contract": "diff",
        "tool_policy": {
            "allowed_tools": ["workspace.list", "workspace.read", "workspace.write_patch", "terminal.run", "artifact.write"],
            "approval_required": {"terminal.run": True, "workspace.write_patch": True},
        },
    }

    class FakeRunnableService:
        def __init__(self):
            self.responses = {
                design["id"]: "Design result",
                coding["id"]: "Code result",
            }
            self.run_index = 0

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
            if run_group_id:
                next_run_group_id = run_group_id
            else:
                self.run_index += 1
                next_run_group_id = f"run_group_manual_{self.run_index}"
            run = {
                "run_id": f"{runnable_id}_run",
                "run_group_id": next_run_group_id,
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

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
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
            "Design 已完成任务，已交给主模型整理。\n"
            "任务：做一版视觉方向\n\n"
            "Design result",
        )
        first_messages = api.get_messages()["messages"]
        first_agent = next(
            message
            for message in first_messages
            if message["role"] == "assistant"
            and message["metadata"].get("sender", {}).get("nickname") == "Design"
            and message["metadata"].get("source_message_id") == first["message_id"]
        )
        assert first_agent["metadata"]["group_agent_summary_pending"] is True
        first_summary = next(
            message
            for message in first_messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id") == first_agent["id"]
        )
        first_summary_task = runtime.state.get_task(first_summary["task_id"])
        assert first_summary_task is not None
        assert "[Oha-Yachiyo 群组直接 Agent 汇总]" in first_summary_task.description
        assert "用户原始请求：@Design 做一版视觉方向" in first_summary_task.description
        assert "Design：已完成" in first_summary_task.description
        assert "汇报：Design result" in first_summary_task.description
        runtime.state.update_task_status(first_summary["task_id"], TaskStatus.COMPLETED, result="Design summary done")
        updated_first_agent = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == first_agent["id"]
        )
        assert updated_first_agent["metadata"]["group_agent_summary_pending"] is False
        assert updated_first_agent["metadata"]["group_agent_summary_status"] == "completed"

        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert current["conversation_kind"] == "group"
        assert current["runnable_name"] == "demo Channel"
        assert current["run_group_id"] == first["run_group_id"]

        second = api.send_message("@Code 实现它")
        assert second["ok"] is True
        assert second["agent_run_id"]
        assert second["run_group_id"] != first["run_group_id"]
        _wait_for_assistant_content(
            runtime,
            "Code 已完成任务，已交给主模型整理。\n"
            "任务：实现它\n\n"
            "Code result",
        )
        second_messages = api.get_messages()["messages"]
        second_agent = next(
            message
            for message in second_messages
            if message["role"] == "assistant"
            and message["metadata"].get("sender", {}).get("nickname") == "Code"
            and message["metadata"].get("source_message_id") == second["message_id"]
        )
        assert second_agent["metadata"]["group_agent_summary_pending"] is True
        second_summary = next(
            message
            for message in second_messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id") == second_agent["id"]
        )
        second_summary_task = runtime.state.get_task(second_summary["task_id"])
        assert second_summary_task is not None
        assert "用户原始请求：@Code 实现它" in second_summary_task.description
        assert "Code：已完成" in second_summary_task.description
        assert "汇报：Code result" in second_summary_task.description
        runtime.state.update_task_status(second_summary["task_id"], TaskStatus.FAILED, error="主模型整理超时")
        updated_second_agent = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == second_agent["id"]
        )
        assert updated_second_agent["metadata"]["group_agent_summary_pending"] is False
        assert updated_second_agent["metadata"]["group_agent_summary_status"] == "failed"
        assert updated_second_agent["metadata"]["group_agent_summary_error"] == "主模型整理超时"
        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert current["run_group_id"] == second["run_group_id"]

        third = api.send_message("@Design 再做一版")
        assert third["ok"] is True
        _wait_for_assistant_content(
            runtime,
            "Design 已完成任务，已交给主模型整理。\n"
            "任务：做一版视觉方向\n\n"
            "Design result",
        )
        third_messages = api.get_messages()["messages"]
        third_agent = next(
            message
            for message in third_messages
            if message["role"] == "assistant"
            and message["metadata"].get("sender", {}).get("nickname") == "Design"
            and message["metadata"].get("source_message_id") == third["message_id"]
        )
        third_summary = next(
            message
            for message in third_messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id") == third_agent["id"]
        )
        runtime.state.update_task_status(third_summary["task_id"], TaskStatus.CANCELLED)
        updated_third_agent = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == third_agent["id"]
        )
        assert updated_third_agent["metadata"]["group_agent_summary_pending"] is False
        assert updated_third_agent["metadata"]["group_agent_summary_status"] == "cancelled"
        assert updated_third_agent["metadata"]["group_agent_summary_error"] == "任务已取消"
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
        assert "[Oha-Yachiyo 群组上下文]" in task.description
        assert "- 月見八千代（主模型" in task.description
        assert "- Design（Agent；Design Agent）" in task.description
        assert "- Design（Agent；Design Agent） - 类别：design；交付：markdown；职责：负责 UI 方案、视觉验收和信息架构。" in task.description
        assert "工具：列文件(workspace.list)、读文件(workspace.read)、产物(artifact.write)" in task.description
        assert "- Code（Agent；Coding Agent）" in task.description
        assert "- Code（Agent；Coding Agent） - 类别：coding；交付：diff；职责：负责代码实现、补丁和验证脚本。" in task.description
        assert "工具：列文件(workspace.list)、读文件(workspace.read)、写补丁(workspace.write_patch)、终端(terminal.run)、产物(artifact.write)" in task.description
        assert "审批：workspace.write_patch、terminal.run" in task.description
        assert "派发时请根据每个 Agent 的类别、职责、工具权限、审批边界和交付偏好选择最合适的成员" in task.description
        assert "不要默认派给所有 Agent" in task.description
        assert '"tool":"oha.group_dispatch"' in task.description
        assert '"tasks":[{"kind":"agent","target":"群成员昵称或名称","goal":"完整、可执行、不可省略的任务说明"}]' in task.description
        assert "完整、可执行、不可省略的任务说明" in task.description
        stored = store.get_session(runtime.chat_session.session_id)
        assert stored is not None
        assert stored.conversation_kind == "group"
    finally:
        store.close()


def test_direct_group_agent_summary_includes_user_followups(tmp_path, monkeypatch):
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
            self.runs: dict[str, dict] = {}

        def list_runnables(self):
            return {"runnables": [design]}

        def parse_known_chat_runnable(self, text):
            if "@Design" in text:
                return "Design", "做一版视觉方向"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            run = {
                "run_id": "agent_run_design",
                "run_group_id": run_group_id or "run_group_design",
                "status": "processing",
                "result": "",
                "runnable": design,
            }
            self.runs[run["run_id"]] = run
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("@Design 做一版视觉方向")
        assert sent["ok"] is True
        assert sent["agent_run_id"] == "agent_run_design"

        followup = api.send_message("补充：这版先按移动端优先，颜色不要太亮")
        assert followup["ok"] is True
        followup_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == followup["message_id"]
        )
        assert followup_message["metadata"]["group_followup_for_agent_message_ids"] == [sent["assistant_message_id"]]
        runtime.state.update_task_status(
            followup["task_id"],
            TaskStatus.COMPLETED,
            result="收到补充。",
        )
        natural_followup = api.send_message("@主模型 把最终说明改成按移动端验收点输出")
        assert natural_followup["ok"] is True
        natural_followup_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == natural_followup["message_id"]
        )
        assert natural_followup_message["metadata"]["group_followup_for_agent_message_ids"] == [sent["assistant_message_id"]]
        runtime.state.update_task_status(
            natural_followup["task_id"],
            TaskStatus.COMPLETED,
            result="收到自然补充。",
        )
        separate_goal = api.send_message("@主模型 另一个目标：再做一个 logo 方向")
        assert separate_goal["ok"] is True
        runtime.state.update_task_status(
            separate_goal["task_id"],
            TaskStatus.COMPLETED,
            result="另一个目标单独处理。",
        )
        new_main_request = api.send_message("@主模型 安排第二轮视觉目标")
        assert new_main_request["ok"] is True
        new_main_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == new_main_request["message_id"]
        )
        assert "group_followup_for_agent_message_ids" not in new_main_message["metadata"]
        runtime.state.update_task_status(
            new_main_request["task_id"],
            TaskStatus.COMPLETED,
            result="第二轮目标单独处理。",
        )

        service.runs["agent_run_design"] = {
            **service.runs["agent_run_design"],
            "status": "completed",
            "result": "设计方向已经整理完成。",
            "timeline": [
                {
                    "event": "agent.tool.call",
                    "detail": "artifact.write",
                    "input_preview": {"path": "design/mobile-direction.md", "kind": "markdown"},
                    "result": {"path": "design/mobile-direction.md"},
                }
            ],
            "pending_approval": {},
        }
        messages = api.get_messages()["messages"]
        agent_message = next(
            message
            for message in messages
            if message["metadata"].get("run_id") == "agent_run_design"
        )
        summary_message = next(
            message
            for message in messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id") == agent_message["id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])

        assert summary_task is not None
        assert "用户原始请求：@Design 做一版视觉方向" in summary_task.description
        assert "用户后续补充/纠偏：" in summary_task.description
        assert "- 补充：这版先按移动端优先，颜色不要太亮" in summary_task.description
        assert "- @主模型 把最终说明改成按移动端验收点输出" in summary_task.description
        assert "另一个目标：再做一个 logo 方向" not in summary_task.description
        assert "安排第二轮视觉目标" not in summary_task.description
        assert "汇报：设计方向已经整理完成。" in summary_task.description
        assert "执行线索：" in summary_task.description
        assert "工具调用：artifact.write" in summary_task.description
        assert "design/mobile-direction.md" in summary_task.description
    finally:
        store.close()


def test_direct_group_agent_followup_targets_latest_active_agent(tmp_path, monkeypatch):
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
        "nickname": "Coding",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def __init__(self):
            self.runs: dict[str, dict] = {}

        def list_runnables(self):
            return {"runnables": [design, coding]}

        def parse_known_chat_runnable(self, text):
            if "@Design" in text:
                return "Design", "做设计方向"
            if "@Coding" in text:
                return "Coding", "做代码方向"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (design, coding):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            agent = self.resolve_runnable(runnable_id=runnable_id, name=name)
            run_id = "agent_run_design" if agent and agent["id"] == design["id"] else "agent_run_coding"
            run = {
                "run_id": run_id,
                "run_group_id": run_group_id or f"run_group_{run_id}",
                "status": "processing",
                "result": "",
                "pending_approval": {},
                "runnable": agent,
            }
            self.runs[run_id] = run
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True
        design_sent = api.send_message("@Design 做设计方向")
        assert design_sent["ok"] is True
        coding_sent = api.send_message("@Coding 做代码方向")
        assert coding_sent["ok"] is True

        followup = api.send_message("补充：这条只给 Coding 的汇总")
        assert followup["ok"] is True
        followup_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == followup["message_id"]
        )
        assert followup_message["metadata"]["group_followup_for_agent_message_ids"] == [coding_sent["assistant_message_id"]]
        runtime.state.update_task_status(
            followup["task_id"],
            TaskStatus.COMPLETED,
            result="收到补充。",
        )

        service.runs["agent_run_design"] = {
            **service.runs["agent_run_design"],
            "status": "completed",
            "result": "设计方向已经完成。",
            "pending_approval": {},
        }
        service.runs["agent_run_coding"] = {
            **service.runs["agent_run_coding"],
            "status": "completed",
            "result": "代码方向已经完成。",
            "pending_approval": {},
        }
        messages = api.get_messages()["messages"]
        summary_messages = [
            message
            for message in messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id")
        ]
        summaries_by_parent = {
            message["metadata"]["group_direct_agent_summary_for_message_id"]: runtime.state.get_task(message["task_id"])
            for message in summary_messages
        }
        design_summary = summaries_by_parent[design_sent["assistant_message_id"]]
        coding_summary = summaries_by_parent[coding_sent["assistant_message_id"]]

        assert design_summary is not None
        assert coding_summary is not None
        assert "补充：这条只给 Coding 的汇总" not in design_summary.description
        assert "- 补充：这条只给 Coding 的汇总" in coding_summary.description
    finally:
        store.close()


def test_direct_group_agent_command_flushes_previous_completed_agent_summary(tmp_path, monkeypatch):
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
        "nickname": "Coding",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def __init__(self):
            self.runs: dict[str, dict] = {}

        def list_runnables(self):
            return {"runnables": [design, coding]}

        def parse_known_chat_runnable(self, text):
            if "@Design" in text:
                return "Design", "做一版视觉方向"
            if "@Coding" in text:
                return "Coding", "写一个验证脚本"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            for agent in (design, coding):
                if runnable_id == agent["id"] or name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            runnable = self.resolve_runnable(runnable_id=runnable_id, name=name) or {}
            run_id = "agent_run_design" if runnable_id == design["id"] else "agent_run_coding"
            run = {
                "run_id": run_id,
                "run_group_id": run_group_id or f"run_group_{run_id}",
                "status": "processing",
                "result": "",
                "runnable": runnable,
            }
            self.runs[run_id] = run
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True

        design_sent = api.send_message("@Design 做一版视觉方向")
        assert design_sent["ok"] is True
        service.runs["agent_run_design"] = {
            **service.runs["agent_run_design"],
            "status": "completed",
            "result": "设计方向完成。",
            "pending_approval": {},
        }

        coding_sent = api.send_message("@Coding 写一个验证脚本")
        assert coding_sent["ok"] is True

        assistant_messages = [
            message
            for message in runtime.chat_session.get_messages()
            if message.role == MessageRole.ASSISTANT
        ]
        summary = next(
            message
            for message in assistant_messages
            if message.metadata.get("group_direct_agent_summary_for_message_id") == design_sent["assistant_message_id"]
        )
        summary_task = runtime.state.get_task(summary.task_id)
        assert summary_task is not None
        assert "用户原始请求：@Design 做一版视觉方向" in summary_task.description
        assert "汇报：设计方向完成。" in summary_task.description
        assert "写一个验证脚本" not in summary_task.description

        coding_message = next(
            message
            for message in runtime.chat_session.get_messages()
            if message.message_id == coding_sent["assistant_message_id"]
        )
        assert coding_message.metadata.get("run_status") == "processing"
        assert not coding_message.metadata.get("group_agent_summary_task_id")
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

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
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


def test_manual_group_agent_error_flushes_previous_completed_agent_summary(tmp_path, monkeypatch):
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
            self.runs: dict[str, dict] = {}

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
            run = {
                "run_id": "agent_run_design",
                "run_group_id": run_group_id or "run_group_design",
                "status": "processing",
                "result": "",
                "runnable": design,
            }
            self.runs[run["run_id"]] = run
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        design_sent = api.send_message("@Design 做一版视觉方向")
        assert design_sent["ok"] is True
        service.runs["agent_run_design"] = {
            **service.runs["agent_run_design"],
            "status": "completed",
            "result": "设计方向完成。",
            "pending_approval": {},
        }

        error_result = api.send_message("@Code 实现它")
        assert error_result["ok"] is True
        assert error_result["error"] == "Code 不在当前群组中。请先在群组设置中加入后再 @。"

        messages = api.get_messages()["messages"]
        summary = next(
            message
            for message in messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id") == design_sent["assistant_message_id"]
        )
        summary_task = runtime.state.get_task(summary["task_id"])
        assert summary_task is not None
        assert "用户原始请求：@Design 做一版视觉方向" in summary_task.description
        assert "汇报：设计方向完成。" in summary_task.description
        assert "实现它" not in summary_task.description
    finally:
        store.close()


def test_manual_group_workflow_run_flushes_previous_completed_agent_summary(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    workflow = {
        "id": "workflow_demo",
        "name": "Demo Workflow",
        "nickname": "Flow",
        "kind": "workflow",
        "enabled": True,
    }

    class FakeRunnableService:
        def __init__(self):
            self.runs: dict[str, dict] = {}

        def parse_known_chat_runnable(self, text):
            if "@Design" in text:
                return "Design", "做一版视觉方向"
            if "@Flow" in text:
                return "Flow", "跑一下流程"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            if runnable_id == workflow["id"] or name in {workflow["name"], workflow["nickname"]}:
                return workflow
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            if runnable_id == workflow["id"]:
                run = {
                    "run_id": "workflow_run_demo",
                    "run_group_id": run_group_id or "run_group_workflow",
                    "kind": "workflow_run",
                    "runnable_id": workflow["id"],
                    "runnable_name": workflow["name"],
                    "status": "completed",
                    "result": "流程完成。",
                    "timeline": [
                        {"event": "workflow.run.started", "detail": workflow["name"]},
                        {"event": "workflow.run.completed", "detail": workflow["name"]},
                    ],
                    "runnable": workflow,
                }
                self.runs[run["run_id"]] = run
                if on_complete:
                    on_complete(run)
                return {**run, "status": "processing"}
            run = {
                "run_id": "agent_run_design",
                "run_group_id": run_group_id or "run_group_design",
                "status": "processing",
                "result": "",
                "runnable": design,
            }
            self.runs[run["run_id"]] = run
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        design_sent = api.send_message("@Design 做一版视觉方向")
        assert design_sent["ok"] is True
        service.runs["agent_run_design"] = {
            **service.runs["agent_run_design"],
            "status": "completed",
            "result": "设计方向完成。",
            "pending_approval": {},
        }

        workflow_result = api.send_message("@Flow 跑一下流程")
        assert workflow_result["ok"] is True
        assert workflow_result["status"] == "processing"
        assert workflow_result["workflow_run_id"] == "workflow_run_demo"

        messages = api.get_messages()["messages"]
        workflow_message = next(
            message
            for message in messages
            if message["id"] == workflow_result["assistant_message_id"]
        )
        assert workflow_message["metadata"]["runnable_kind"] == "workflow"
        assert "Flow 已完成" in workflow_message["content"]

        summary = next(
            message
            for message in messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id") == design_sent["assistant_message_id"]
        )
        summary_task = runtime.state.get_task(summary["task_id"])
        assert summary_task is not None
        assert "用户原始请求：@Design 做一版视觉方向" in summary_task.description
        assert "汇报：设计方向完成。" in summary_task.description
        assert "@Flow 跑一下流程" not in summary_task.description
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
        assert "[Oha-Yachiyo 群组上下文]" in task.description
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


def test_manual_group_generic_workflow_mention_stays_plain_message(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    design = service.create_agent(
        {
            "agent_id": "agent_design",
            "name": "Design Agent",
            "nickname": "Design",
            "model_mode": "follow_main",
        }
    )
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["agent_id"]])
        assert created["ok"] is True

        result = api.send_message("普通说明：这次不使用 @Workflow，只说明应该去 Workflow Studio 运行。")

        assert result["ok"] is True
        assert "runnable_command" not in result
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert "普通说明：这次不使用 @Workflow" in task.description
        assert "[Oha-Yachiyo 群组上下文]" in task.description
        messages = api.get_messages()["messages"]
        assert not any(message.get("content") == "未找到指定 Agent 或 Workflow" for message in messages)
    finally:
        service.close()
        store.close()


def test_group_session_rejects_workflow_participants(tmp_path, monkeypatch):
    api, _runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    workflow = {
        "id": "workflow_demo",
        "name": "Demo Workflow",
        "kind": "workflow",
        "enabled": True,
    }

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            for runnable in (design, workflow):
                if runnable_id == runnable["id"] or name in {runnable["name"], runnable.get("nickname")}:
                    return runnable
            return None

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[workflow["id"]])

        assert created["ok"] is False
        assert created["error"] == "群组成员必须是已启用的 Agent"

        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        updated = api.update_group_session(
            created["session_id"],
            name="demo Channel",
            participant_ids=[design["id"], workflow["id"]],
        )

        assert updated["ok"] is False
        assert updated["error"] == "群组成员必须是已启用的 Agent"
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
        assert "[Oha-Yachiyo 群组执行约定]" in calls[0]["upstream"]
        assert "你在群内身份是：Design" in calls[0]["upstream"]
        assert "- Design（Agent；Design Agent）" in calls[0]["upstream"]
    finally:
        store.close()


def test_manual_group_agent_creation_failure_reports_to_main_model(tmp_path, monkeypatch):
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
            if "@Design" in text:
                return "Design", "做一版视觉方向"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, **kwargs):
            raise AgentRuntimeError("工具配置缺失")

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        result = api.send_message("@Design 做一版视觉方向")

        assert result["ok"] is True
        assert result["error"] == (
            "Design 执行失败，已把失败原因交给主模型整理。\n"
            "任务：做一版视觉方向\n\n"
            "工具配置缺失"
        )
        messages = api.get_messages()["messages"]
        agent_message = next(
            message
            for message in messages
            if message["role"] == "assistant"
            and message["metadata"].get("sender", {}).get("nickname") == "Design"
        )
        assert agent_message["status"] == "failed"
        assert agent_message["metadata"]["agent_report_status"] == "failed"
        assert agent_message["metadata"]["agent_report"] == "工具配置缺失"
        assert agent_message["metadata"]["group_agent_summary_pending"] is True
        summary_message = next(
            message
            for message in messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id") == agent_message["id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "用户原始请求：@Design 做一版视觉方向" in summary_task.description
        assert "Design：执行失败" in summary_task.description
        assert "汇报：工具配置缺失" in summary_task.description
    finally:
        store.close()


def test_manual_group_agent_run_failure_reports_to_main_model(tmp_path, monkeypatch):
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
            if "@Design" in text:
                return "Design", "做一版视觉方向"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            run = {
                "run_id": "agent_design_failed",
                "run_group_id": run_group_id or "run_group_manual_failed",
                "status": "processing",
                "result": "",
                "runnable": design,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "failed",
                    "result": "模型调用超时。",
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        sent = api.send_message("@Design 做一版视觉方向")
        assert sent["ok"] is True

        messages = api.get_messages()["messages"]
        agent_message = next(
            message
            for message in messages
            if message["role"] == "assistant"
            and message["metadata"].get("sender", {}).get("nickname") == "Design"
        )
        assert agent_message["status"] == "failed"
        assert agent_message["content"] == (
            "Design 执行失败，已把失败原因交给主模型整理。\n"
            "任务：做一版视觉方向\n\n"
            "模型调用超时。"
        )
        assert agent_message["metadata"]["run_status"] == "failed"
        assert agent_message["metadata"]["agent_report_status"] == "failed"
        assert agent_message["metadata"]["agent_report"] == "模型调用超时。"
        assert agent_message["metadata"]["group_agent_summary_pending"] is True
        summary_message = next(
            message
            for message in messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id") == agent_message["id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "用户原始请求：@Design 做一版视觉方向" in summary_task.description
        assert "Design：执行失败" in summary_task.description
        assert "汇报：模型调用超时。" in summary_task.description
    finally:
        store.close()


def test_manual_group_agent_completion_after_session_switch_writes_back_original_group(tmp_path, monkeypatch):
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
            self.on_complete = None

        def parse_known_chat_runnable(self, text):
            if "@Design" in text:
                return "Design", "做一版视觉方向"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            self.on_complete = on_complete
            return {
                "run_id": "agent_design_completed",
                "run_group_id": run_group_id or "run_group_manual_completed",
                "status": "processing",
                "result": "",
                "runnable": design,
            }

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        original_session_id = created["session_id"]

        sent = api.send_message("@Design 做一版视觉方向")
        assert sent["ok"] is True
        assert callable(service.on_complete)

        runtime.start_new_session()
        current_session_id = runtime.chat_session.session_id
        service.on_complete({
            "run_id": "agent_design_completed",
            "run_group_id": "run_group_manual_completed",
            "status": "completed",
            "result": "视觉方向已经完成。",
            "timeline": [],
            "runnable": design,
        })

        assert runtime.chat_session.session_id == current_session_id
        stored_messages = store.load_messages(original_session_id)
        agent_message = next(
            message
            for message in stored_messages
            if json.loads(message.metadata_json).get("run_id") == "agent_design_completed"
        )
        agent_metadata = json.loads(agent_message.metadata_json)
        assert agent_message.status == MessageStatus.COMPLETED.value
        assert agent_message.content == (
            "Design 已完成任务，已交给主模型整理。\n"
            "任务：做一版视觉方向\n\n"
            "视觉方向已经完成。"
        )
        assert agent_metadata["agent_report"] == "视觉方向已经完成。"
        assert agent_metadata["agent_report_status"] == "completed"

        summary_message = next(
            message
            for message in stored_messages
            if json.loads(message.metadata_json).get("group_direct_agent_summary_for_message_id") == agent_message.message_id
        )
        summary_task = runtime.state.get_task(summary_message.task_id)
        assert summary_message.status == MessageStatus.PROCESSING.value
        assert summary_task is not None
        assert summary_task.chat_session_id == original_session_id
        assert "用户原始请求：@Design 做一版视觉方向" in summary_task.description
        assert "汇报：视觉方向已经完成。" in summary_task.description
    finally:
        store.close()


def test_manual_group_agent_approval_completion_reports_to_main_model(tmp_path, monkeypatch):
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
                "run_id": "agent_design_waiting",
                "run_group_id": "run_group_manual_approval",
                "status": "processing",
                "result": "",
                "runnable": design,
            }

        def parse_known_chat_runnable(self, text):
            if "@Design" in text:
                return "Design", "做一版视觉方向"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            self.run = {
                **self.run,
                "run_group_id": run_group_id or self.run["run_group_id"],
            }
            if on_complete:
                self.run = {
                    **self.run,
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "approval_id": "approval_terminal",
                        "tool": "terminal.run",
                        "input_preview": {"command": "python3 preview.py"},
                    },
                }
                on_complete(self.run)
            return self.run

        def get_run(self, run_id):
            assert run_id == "agent_design_waiting"
            return self.run

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        sent = api.send_message("@Design 做一版视觉方向")
        assert sent["ok"] is True

        waiting_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        approval_message = next(
            message
            for message in waiting_messages
            if message["metadata"].get("sender", {}).get("nickname") == "Design"
        )
        assert approval_message["status"] == "processing"
        assert approval_message["metadata"]["run_status"] == "approval_required"
        assert approval_message["metadata"]["source_message_id"] == sent["message_id"]
        assert "Design 需要你确认一次工具调用" in approval_message["content"]
        assert "工具：terminal.run" in approval_message["content"]
        assert "关联任务：做一版视觉方向" in approval_message["content"]
        assert not any(message["metadata"].get("group_direct_agent_summary_for_message_id") == approval_message["id"] for message in waiting_messages)

        service.run = {
            **service.run,
            "status": "completed",
            "result": "视觉方向已经完成。",
            "pending_approval": {},
        }
        completed_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        completed_agent = next(message for message in completed_messages if message["id"] == approval_message["id"])
        assert completed_agent["status"] == "completed"
        assert completed_agent["content"] == (
            "Design 已完成任务，已交给主模型整理。\n"
            "任务：做一版视觉方向\n\n"
            "视觉方向已经完成。"
        )
        assert completed_agent["metadata"]["group_agent_summary_pending"] is True
        summary_message = next(
            message
            for message in completed_messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id") == approval_message["id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "用户原始请求：@Design 做一版视觉方向" in summary_task.description
        assert "Design：已完成" in summary_task.description
        assert "汇报：视觉方向已经完成。" in summary_task.description
    finally:
        store.close()


def test_manual_group_agent_approval_rejection_reports_to_main_model(tmp_path, monkeypatch):
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
                "run_id": "agent_design_waiting",
                "run_group_id": "run_group_manual_rejected",
                "status": "processing",
                "result": "",
                "runnable": design,
            }

        def parse_known_chat_runnable(self, text):
            if "@Design" in text:
                return "Design", "做一版视觉方向"
            return None

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            self.run = {
                **self.run,
                "run_group_id": run_group_id or self.run["run_group_id"],
            }
            if on_complete:
                self.run = {
                    **self.run,
                    "status": "approval_required",
                    "result": "等待审批：workspace.write_patch",
                    "pending_approval": {
                        "approval_id": "approval_patch",
                        "tool": "workspace.write_patch",
                        "input_preview": {"path": "draft.md"},
                    },
                }
                on_complete(self.run)
            return self.run

        def get_run(self, run_id):
            assert run_id == "agent_design_waiting"
            return self.run

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        sent = api.send_message("@Design 做一版视觉方向")
        assert sent["ok"] is True

        waiting_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        approval_message = next(
            message
            for message in waiting_messages
            if message["metadata"].get("sender", {}).get("nickname") == "Design"
        )
        assert approval_message["metadata"]["run_status"] == "approval_required"
        assert "工具：workspace.write_patch" in approval_message["content"]
        assert not any(message["metadata"].get("group_direct_agent_summary_for_message_id") == approval_message["id"] for message in waiting_messages)

        service.run = {
            **service.run,
            "status": "cancelled",
            "result": "工具审批已拒绝：不需要写文件。",
            "pending_approval": {},
        }
        cancelled_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        cancelled_agent = next(message for message in cancelled_messages if message["id"] == approval_message["id"])
        assert cancelled_agent["status"] == "failed"
        assert cancelled_agent["content"] == (
            "Design 任务已取消，已把当前状态交给主模型整理。\n"
            "任务：做一版视觉方向\n\n"
            "工具审批已拒绝：不需要写文件。"
        )
        assert cancelled_agent["metadata"]["run_status"] == "cancelled"
        assert cancelled_agent["metadata"]["agent_report_status"] == "cancelled"
        assert cancelled_agent["metadata"]["agent_report"] == "工具审批已拒绝：不需要写文件。"
        assert cancelled_agent["metadata"]["group_agent_summary_pending"] is True
        summary_message = next(
            message
            for message in cancelled_messages
            if message["metadata"].get("group_direct_agent_summary_for_message_id") == approval_message["id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "用户原始请求：@Design 做一版视觉方向" in summary_task.description
        assert "Design：已取消" in summary_task.description
        assert "汇报：工具审批已拒绝：不需要写文件。" in summary_task.description
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
                artifacts = [
                    {"kind": "context", "path": "agent-context.md"},
                ]
                if runnable_id == "agent_design":
                    artifacts.extend(
                        {"kind": "tool_artifact", "path": f"design-{index:02d}.md"}
                        for index in range(1, 11)
                    )
                on_complete({
                    **run,
                    "status": "completed",
                    "result": f"{runnable.get('nickname')} done",
                    "artifacts": artifacts,
                })
            return run

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
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
            '{"action":"runohaagent","agent":"@Design","goal":"做视觉测试"}\n'
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
        assert "runohaagent" not in assistant_messages[0]["content"]
        assert "dispatch_group_agent" not in assistant_messages[0]["content"]
        assert assistant_messages[0]["metadata"]["group_dispatch_handled"] is True
        assert [message["metadata"]["sender"]["nickname"] for message in assistant_messages[1:3]] == [
            "Design",
            "Code",
        ]
        assert [message["content"] for message in assistant_messages[1:3]] == [
            "Design 已完成，并把结果交给主模型汇总。\n任务：做视觉测试\n产物：10 个，见运行详情。\n\nDesign done",
            "Code 已完成，并把结果交给主模型汇总。\n任务：做代码测试\n\nCode done",
        ]
        assert assistant_messages[1]["metadata"]["agent_report"] == "Design done"
        assert assistant_messages[2]["metadata"]["agent_report"] == "Code done"
        assert assistant_messages[1]["metadata"]["run_artifact_count"] == 10
        assert len(assistant_messages[1]["metadata"]["run_artifacts"]) == 8
        assert assistant_messages[1]["metadata"]["run_artifacts"][0] == {
            "path": "design-01.md",
            "kind": "tool_artifact",
        }
        assert assistant_messages[2]["metadata"]["run_artifact_count"] == 0
        assert assistant_messages[2]["metadata"]["run_artifacts"] == []
        summary_message = assistant_messages[3]
        assert summary_message["status"] == "processing"
        assert summary_message["content"] == ""
        assert summary_message["metadata"]["sender"]["kind"] == "main"
        assert summary_message["metadata"]["group_agent_summary_for_task_id"] == sent["task_id"]
        assert assistant_messages[0]["metadata"]["group_agent_summary_pending"] is True
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "[Oha-Yachiyo 群组 Agent 汇总]" in summary_task.description
        assert "不要再派发新的 Agent 任务" in summary_task.description
        assert "汇报：Design done" in summary_task.description
        assert "产物：design-01.md (tool_artifact)" in summary_task.description
        assert "另有 2 个产物见 Run Detail" in summary_task.description
        assert "汇报：Code done" in summary_task.description

        runtime.state.update_task_status(
            summary_message["task_id"],
            TaskStatus.COMPLETED,
            result="我已经整理好两个 Agent 的结果。",
        )
        completed_payload = api.get_messages()
        completed_parent = next(
            message
            for message in completed_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )
        completed_summary = next(
            message
            for message in completed_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == summary_message["task_id"]
        )
        assert "group_agent_summary_pending" not in completed_parent["metadata"]
        assert completed_parent["metadata"]["group_agent_summary_status"] == "completed"
        assert completed_summary["status"] == "completed"
        assert completed_summary["content"] == "我已经整理好两个 Agent 的结果。"
        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert current["run_group_id"] == "run_group_dispatch"

        second_sent = api.send_message("@主模型 再派一个失败汇总测试")
        assert second_sent["ok"] is True
        runtime.state.update_task_status(
            second_sent["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"做失败汇总测试"}',
        )
        failed_summary_payload = api.get_messages()
        second_parent = next(
            message
            for message in failed_summary_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == second_sent["task_id"]
        )
        second_summary = next(
            message
            for message in failed_summary_payload["messages"]
            if message["metadata"].get("group_agent_summary_for_task_id") == second_sent["task_id"]
        )
        assert second_parent["metadata"]["group_agent_summary_pending"] is True
        runtime.state.update_task_status(second_summary["task_id"], TaskStatus.FAILED, error="主模型汇总失败")
        failed_completed_payload = api.get_messages()
        failed_parent = next(
            message
            for message in failed_completed_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == second_sent["task_id"]
        )
        failed_summary = next(
            message
            for message in failed_completed_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == second_summary["task_id"]
        )
        assert "group_agent_summary_pending" not in failed_parent["metadata"]
        assert failed_parent["metadata"]["group_agent_summary_status"] == "failed"
        assert failed_parent["metadata"]["group_agent_summary_error"] == "主模型汇总失败"
        assert failed_summary["status"] == "failed"
        assert failed_summary["error"] == "主模型汇总失败"
    finally:
        store.close()


def test_group_dispatch_resolves_member_short_alias_and_category(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "编码Agent Iroha",
        "kind": "agent",
        "enabled": True,
        "category": "coding",
    }
    calls: list[dict] = []

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            if runnable_id == coding["id"] or clean_name in {coding["name"], coding["nickname"]}:
                return coding
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
            })
            run = {
                "run_id": f"{runnable_id}_run_{len(calls)}",
                "run_group_id": run_group_id or "run_group_alias",
                "status": "processing",
                "result": "",
                "runnable": coding,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": "alias matched",
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[coding["id"]])
        assert created["ok"] is True

        sent = api.send_message("@主模型 安排别名解析测试")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                '{"action":"dispatch_group_agent","agent":"Iroha","goal":"请求终端审批"}\n'
                '{"action":"dispatch_group_agent","agent":"coding","goal":"再做一次"}'
            ),
        )

        payload = api.get_messages()

        assert [call["runnable_id"] for call in calls] == ["agent_coding", "agent_coding"]
        assert [call["user_goal"] for call in calls] == ["请求终端审批", "再做一次"]
        parent = next(
            message
            for message in payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )
        assert parent["metadata"]["group_dispatch_count"] == 2
        assert "未找到群组 Agent" not in parent["content"]
        assert parent["metadata"]["group_dispatch_skipped"] == []
    finally:
        store.close()


def test_group_dispatch_hides_protocol_meta_intro_lines(tmp_path, monkeypatch):
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
                "run_id": f"{runnable_id}_run",
                "run_group_id": run_group_id or "run_group_dispatch",
                "status": "processing",
                "result": "",
                "runnable": design,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": "Design done",
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
            result=(
                "好，我来安排。\n"
                "看来派活协议需要直接在回复里输出。让我重新来——\n"
                '{"action":"dispatch_group_agent","agent":"Design","goal":"做视觉测试"}'
            ),
        )

        payload = api.get_messages()

        parent = next(
            message
            for message in payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )
        assert "好，我来安排。" in parent["content"]
        assert "我把这个任务派给 Design 了。" in parent["content"]
        assert "派活协议" not in parent["content"]
        assert "让我重新来" not in parent["content"]
        assert "dispatch_group_agent" not in parent["content"]
    finally:
        store.close()


def test_plain_group_message_can_dispatch_agents_via_main_model_result(tmp_path, monkeypatch):
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
            clean_name = str(name or "").lstrip("@")
            if runnable_id == design["id"] or clean_name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "upstream": upstream,
            })
            run = {
                "run_id": "agent_design_run",
                "run_group_id": run_group_id or "run_group_plain_dispatch",
                "status": "processing",
                "result": "",
                "runnable": design,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": "视觉方案已经整理好。",
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        sent = api.send_message("我想让群里合适的 Agent 做个视觉测试")
        assert sent["ok"] is True
        main_task = runtime.state.get_task(sent["task_id"])
        assert main_task is not None
        assert main_task.description.startswith("我想让群里合适的 Agent 做个视觉测试")
        assert "[Oha-Yachiyo 群组上下文]" in main_task.description
        assert '"tool":"oha.group_dispatch"' in main_task.description

        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"做视觉测试"}',
        )

        payload = api.get_messages()
        assistant_messages = [message for message in payload["messages"] if message["role"] == "assistant"]
        assert len(calls) == 1
        assert calls[0]["runnable_id"] == "agent_design"
        assert calls[0]["user_goal"] == "做视觉测试"
        assert "你在群内身份是：Design" in calls[0]["upstream"]
        parent_message = next(message for message in assistant_messages if message["task_id"] == sent["task_id"])
        assert parent_message["metadata"]["group_dispatch_handled"] is True
        assert parent_message["metadata"]["group_dispatch_count"] == 1
        assert "Design" in parent_message["content"]
        delegated = next(
            message
            for message in assistant_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        )
        assert delegated["content"] == (
            "Design 已完成，并把结果交给主模型汇总。\n"
            "任务：做视觉测试\n\n"
            "视觉方案已经整理好。"
        )
        summary_message = next(
            message
            for message in assistant_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "用户原始请求：我想让群里合适的 Agent 做个视觉测试" in summary_task.description
        assert "Design：已完成" in summary_task.description
        assert "汇报：视觉方案已经整理好。" in summary_task.description
    finally:
        store.close()


def test_plain_group_goal_dispatches_two_agents_and_summarizes(tmp_path, monkeypatch):
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
        "nickname": "Coding",
        "kind": "agent",
        "enabled": True,
    }
    results = {
        "agent_design": "设计验收点已经整理好。",
        "agent_coding": "验证脚本方案已经整理好。",
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
            run_group = run_group_id or "run_group_plain_acceptance"
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "actual_run_group_id": run_group,
                "upstream": upstream,
            })
            runnable = design if runnable_id == design["id"] else coding
            run = {
                "run_id": f"{runnable_id}_run",
                "run_group_id": run_group,
                "status": "processing",
                "result": "",
                "runnable": runnable,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": results[runnable_id],
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True

        sent = api.send_message("我想让群里合适的 Agent 分别做 UI 验收和验证脚本方案")
        assert sent["ok"] is True
        main_task = runtime.state.get_task(sent["task_id"])
        assert main_task is not None
        assert main_task.description.startswith("我想让群里合适的 Agent 分别做 UI 验收和验证脚本方案")
        assert "[Oha-Yachiyo 群组上下文]" in main_task.description
        assert "Design Agent" in main_task.description
        assert "Coding Agent" in main_task.description

        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我会把 UI 验收交给 Design，把验证脚本方案交给 Coding。\n"
                "<oha_group_dispatch>\n"
                '{"tasks":['
                '{"action":"dispatch_group_agent","agent":"Design","goal":"整理 UI 验收点"},'
                '{"action":"dispatch_group_agent","agent":"Coding","goal":"整理验证脚本方案"}'
                "]}\n"
                "</oha_group_dispatch>"
            ),
        )

        payload = api.get_messages()
        assistant_messages = [message for message in payload["messages"] if message["role"] == "assistant"]
        parent = next(message for message in assistant_messages if message["task_id"] == sent["task_id"])
        delegated = [
            message
            for message in assistant_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        ]
        summary_message = next(
            message
            for message in assistant_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )

        assert [call["runnable_id"] for call in calls] == ["agent_design", "agent_coding"]
        assert [call["user_goal"] for call in calls] == ["整理 UI 验收点", "整理验证脚本方案"]
        assert calls[0]["run_group_id"] == ""
        assert calls[1]["run_group_id"] == "run_group_plain_acceptance"
        assert all("[Oha-Yachiyo 群组执行约定]" in call["upstream"] for call in calls)
        assert parent["metadata"]["group_dispatch_handled"] is True
        assert parent["metadata"]["group_dispatch_count"] == 2
        assert parent["metadata"]["group_agent_summary_pending"] is True
        assert "我把 2 个任务分别派给 Design、Coding 了。" in parent["content"]
        assert "oha_group_dispatch" not in parent["content"]
        assert "dispatch_group_agent" not in parent["content"]
        assert [message["metadata"]["delegated_goal"] for message in delegated] == [
            "整理 UI 验收点",
            "整理验证脚本方案",
        ]
        assert [message["metadata"]["agent_report"] for message in delegated] == [
            "设计验收点已经整理好。",
            "验证脚本方案已经整理好。",
        ]

        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert summary_message["status"] == "processing"
        assert "用户原始请求：我想让群里合适的 Agent 分别做 UI 验收和验证脚本方案" in summary_task.description
        assert "Design：已完成" in summary_task.description
        assert "Coding：已完成" in summary_task.description
        assert "汇报：设计验收点已经整理好。" in summary_task.description
        assert "汇报：验证脚本方案已经整理好。" in summary_task.description
        assert "不要再派发新的 Agent 任务" in summary_task.description

        runtime.state.update_task_status(
            summary_message["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我已经整合好 Design 和 Coding 的结果。\n"
                '{"tasks":[{"action":"dispatch_group_agent","agent":"Design","goal":"重复派发"}]}'
            ),
        )
        completed_payload = api.get_messages()
        completed_parent = next(
            message
            for message in completed_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )
        completed_summary = next(
            message
            for message in completed_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == summary_message["task_id"]
        )
        assert "group_agent_summary_pending" not in completed_parent["metadata"]
        assert completed_parent["metadata"]["group_agent_summary_status"] == "completed"
        assert "我已经整合好 Design 和 Coding 的结果。" in completed_summary["content"]
        assert "dispatch_group_agent" not in completed_summary["content"]
        assert "重复派发" not in completed_summary["content"]
        assert "内部派发协议，已隐藏" in completed_summary["content"]
    finally:
        store.close()


def test_plain_group_goal_mixed_agent_outcomes_waits_and_summarizes(tmp_path, monkeypatch):
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
        "nickname": "Coding",
        "kind": "agent",
        "enabled": True,
    }
    calls: list[dict] = []

    class FakeRunnableService:
        def __init__(self):
            self.runs = {
                "agent_run_design": {
                    "run_id": "agent_run_design",
                    "run_group_id": "run_group_plain_mixed",
                    "status": "approval_required",
                    "result": "等待审批：artifact.write",
                    "pending_approval": {
                        "approval_id": "approval_design",
                        "tool": "artifact.write",
                        "input_preview": {"path": "design/plain-mixed.md"},
                    },
                    "timeline": [
                        {
                            "event": "agent.tool.call",
                            "detail": "artifact.write",
                            "input_preview": {"path": "design/plain-mixed.md"},
                            "result": {"ok": True, "path": "design/plain-mixed.md"},
                        }
                    ],
                    "runnable": design,
                },
                "agent_run_coding": {
                    "run_id": "agent_run_coding",
                    "run_group_id": "run_group_plain_mixed",
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "approval_id": "approval_coding",
                        "tool": "terminal.run",
                        "input_preview": {"command": "python3 verify_plain_group.py"},
                    },
                    "timeline": [
                        {
                            "event": "agent.tool.call",
                            "detail": "terminal.run",
                            "input_preview": {"command": "python3 verify_plain_group.py"},
                            "result": {"ok": False, "exit_code": 2, "stderr": "plain group verify failed"},
                        }
                    ],
                    "runnable": coding,
                },
            }

        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (design, coding):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            run_id = "agent_run_design" if runnable_id == design["id"] else "agent_run_coding"
            run_group = run_group_id or self.runs[run_id]["run_group_id"]
            calls.append({
                "runnable_id": runnable_id,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "actual_run_group_id": run_group,
                "upstream": upstream,
            })
            run = {
                **self.runs[run_id],
                "run_group_id": run_group,
            }
            self.runs[run_id] = run
            if on_complete:
                on_complete(run)
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True

        sent = api.send_message("请让群里合适的 Agent 分别整理 UI 验收点和运行验证脚本")
        assert sent["ok"] is True
        assert runtime.state.get_task(sent["task_id"]) is not None
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我会让 Design 整理验收点，让 Coding 运行验证脚本。\n"
                "<oha_group_dispatch>\n"
                '{"tasks":['
                '{"action":"dispatch_group_agent","agent":"Design","goal":"整理 UI 验收点"},'
                '{"action":"dispatch_group_agent","agent":"Coding","goal":"运行验证脚本"}'
                "]}\n"
                "</oha_group_dispatch>"
            ),
        )

        approval_payload = api.get_messages()
        approval_messages = [message for message in approval_payload["messages"] if message["role"] == "assistant"]
        parent = next(message for message in approval_messages if message["task_id"] == sent["task_id"])
        delegated = {
            message["metadata"].get("sender", {}).get("nickname"): message
            for message in approval_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        }
        assert [call["runnable_id"] for call in calls] == ["agent_design", "agent_coding"]
        assert calls[0]["run_group_id"] == ""
        assert calls[1]["run_group_id"] == "run_group_plain_mixed"
        assert all("[Oha-Yachiyo 群组执行约定]" in call["upstream"] for call in calls)
        assert parent["metadata"]["group_dispatch_count"] == 2
        assert "dispatch_group_agent" not in parent["content"]
        assert approval_payload["approval_count"] == 2
        assert delegated["Design"]["metadata"]["run_status"] == "approval_required"
        assert delegated["Coding"]["metadata"]["run_status"] == "approval_required"
        assert not any(
            message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
            for message in approval_messages
        )

        service.runs["agent_run_design"] = {
            **service.runs["agent_run_design"],
            "status": "completed",
            "result": "UI 验收点已经整理完成。",
            "pending_approval": {},
        }
        partial_payload = api.get_messages()
        partial_messages = [message for message in partial_payload["messages"] if message["role"] == "assistant"]
        partial_delegated = {
            message["metadata"].get("sender", {}).get("nickname"): message
            for message in partial_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        }
        assert partial_payload["approval_count"] == 1
        assert partial_delegated["Design"]["status"] == "completed"
        assert partial_delegated["Coding"]["metadata"]["run_status"] == "approval_required"
        assert not any(
            message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
            for message in partial_messages
        )

        service.runs["agent_run_coding"] = {
            **service.runs["agent_run_coding"],
            "status": "failed",
            "result": "验证脚本失败：plain group verify failed",
            "pending_approval": {},
        }
        final_payload = api.get_messages()
        final_messages = [message for message in final_payload["messages"] if message["role"] == "assistant"]
        final_delegated = {
            message["metadata"].get("sender", {}).get("nickname"): message
            for message in final_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        }
        summary_message = next(
            message
            for message in final_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert final_payload["approval_count"] == 0
        assert final_delegated["Design"]["metadata"]["agent_report_status"] == "completed"
        assert final_delegated["Coding"]["metadata"]["agent_report_status"] == "failed"
        assert "用户原始请求：请让群里合适的 Agent 分别整理 UI 验收点和运行验证脚本" in summary_task.description
        assert "Design：已完成" in summary_task.description
        assert "汇报：UI 验收点已经整理完成。" in summary_task.description
        assert "Coding：执行失败" in summary_task.description
        assert "汇报：验证脚本失败：plain group verify failed" in summary_task.description
        assert "执行线索：" in summary_task.description
        assert "terminal.run" in summary_task.description
        assert "python3 verify_plain_group.py" in summary_task.description
        assert "plain group verify failed" in summary_task.description
        assert "回复必须明确区分：成功项、失败/取消/拒绝项、失败原因、未执行派活、可验收内容/产物、用户下一步可选动作。" in summary_task.description

        runtime.state.update_task_status(
            summary_message["task_id"],
            TaskStatus.COMPLETED,
            result="最终汇总：Design 完成；Coding 失败，原因是验证脚本失败。",
        )
        settled_payload = api.get_messages()
        settled_parent = next(
            message
            for message in settled_payload["messages"]
            if message["role"] == "assistant" and message.get("task_id") == sent["task_id"]
        )
        settled_summary = next(
            message
            for message in settled_payload["messages"]
            if message["role"] == "assistant" and message.get("task_id") == summary_message["task_id"]
        )
        assert "group_agent_summary_pending" not in settled_parent["metadata"]
        assert settled_parent["metadata"]["group_agent_summary_status"] == "completed"
        assert settled_summary["content"] == "最终汇总：Design 完成；Coding 失败，原因是验证脚本失败。"
        assert settled_payload["approval_count"] == 0
        assert settled_payload["processing_count"] == 0
        assert settled_payload["is_processing"] is False
    finally:
        store.close()


def test_group_delegated_agent_failure_mentions_visible_artifacts(tmp_path, monkeypatch):
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
            clean_name = str(name or "").lstrip("@")
            if runnable_id == design["id"] or clean_name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            run = {
                "run_id": f"{runnable_id}_run",
                "run_group_id": run_group_id or "run_group_dispatch",
                "status": "processing",
                "result": "",
                "runnable": design,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "failed",
                    "result": "模型超时，但已写出草稿。",
                    "artifacts": [
                        {"kind": "context", "path": "agent-context.md"},
                        {"kind": "tool_artifact", "path": "design-draft.md"},
                    ],
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        sent = api.send_message("@主模型 请 Design 做一个草稿")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"做视觉草稿"}',
        )

        payload = api.get_messages()
        delegated = next(
            message
            for message in payload["messages"]
            if message["role"] == "assistant" and message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        )
        assert delegated["status"] == "failed"
        assert "产物：1 个，见运行详情。" in delegated["content"]
        assert delegated["metadata"]["run_artifact_count"] == 1
        assert delegated["metadata"]["run_artifacts"] == [{"path": "design-draft.md", "kind": "tool_artifact"}]
    finally:
        store.close()


def test_group_dispatch_uses_fresh_run_group_for_each_user_goal(tmp_path, monkeypatch):
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
        def __init__(self):
            self.run_group_index = 0

        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (design, coding):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            if run_group_id:
                next_run_group_id = run_group_id
            else:
                self.run_group_index += 1
                next_run_group_id = f"run_group_dispatch_{self.run_group_index}"
            calls.append({
                "runnable_id": runnable_id,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "actual_run_group_id": next_run_group_id,
            })
            runnable = self.resolve_runnable(runnable_id=runnable_id, name=name) or {}
            run = {
                "run_id": f"{runnable_id}_run_{len(calls)}",
                "run_group_id": next_run_group_id,
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

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(
            name="demo Channel",
            participant_ids=[design["id"], coding["id"]],
        )
        assert created["ok"] is True

        first = api.send_message("@主模型 第一轮安排")
        runtime.state.update_task_status(
            first["task_id"],
            TaskStatus.COMPLETED,
            result=(
                '{"action":"dispatch_group_agent","agent":"Design","goal":"第一轮设计"}\n'
                '{"action":"dispatch_group_agent","agent":"Code","goal":"第一轮编码"}'
            ),
        )
        first_payload = api.get_messages()
        assert [call["run_group_id"] for call in calls[:2]] == ["", "run_group_dispatch_1"]
        assert [call["actual_run_group_id"] for call in calls[:2]] == [
            "run_group_dispatch_1",
            "run_group_dispatch_1",
        ]
        first_parent = next(
            message
            for message in first_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == first["task_id"]
        )
        assert first_parent["metadata"]["group_dispatch_run_group_id"] == "run_group_dispatch_1"

        second = api.send_message("@主模型 第二轮安排")
        runtime.state.update_task_status(
            second["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Code","goal":"第二轮编码"}',
        )
        second_payload = api.get_messages()
        assert calls[2]["run_group_id"] == ""
        assert calls[2]["actual_run_group_id"] == "run_group_dispatch_2"
        second_parent = next(
            message
            for message in second_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == second["task_id"]
        )
        assert second_parent["metadata"]["group_dispatch_run_group_id"] == "run_group_dispatch_2"
        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert current["run_group_id"] == "run_group_dispatch_2"
    finally:
        store.close()


def test_group_dispatch_reports_skipped_agent_not_in_group(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    outsider = {
        "id": "agent_outside",
        "name": "Outside Agent",
        "nickname": "Ghost",
        "kind": "agent",
        "enabled": True,
    }
    calls: list[str] = []

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (design, outsider):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            calls.append(runnable_id)
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
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        sent = api.send_message("@主模型 你来安排测试任务")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                '{"action":"dispatch_group_agent","agent":"Design","goal":"做视觉测试"}\n'
                '{"action":"dispatch_group_agent","agent":"Ghost","goal":"做不存在成员测试"}'
            ),
        )

        payload = api.get_messages()
        assistant_messages = [message for message in payload["messages"] if message["role"] == "assistant"]

        assert calls == ["agent_design"]
        assert "我把这个任务派给 Design 了。" in assistant_messages[0]["content"]
        assert "以下派活没有执行：" in assistant_messages[0]["content"]
        assert "- Ghost: 不在当前群组中" in assistant_messages[0]["content"]
        assert assistant_messages[0]["metadata"]["group_dispatch_count"] == 1
        assert assistant_messages[0]["metadata"]["group_dispatch_skipped"] == [
            "Ghost: 不在当前群组中",
        ]
        summary_message = next(
            message
            for message in assistant_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "未执行派活" in summary_task.description
        assert "未执行派活：" in summary_task.description
        assert "- Ghost: 不在当前群组中" in summary_task.description
        assert "汇报：Design done" in summary_task.description
    finally:
        store.close()


def test_group_dispatch_all_skipped_still_creates_main_summary(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    outsider = {
        "id": "agent_outside",
        "name": "Outside Agent",
        "nickname": "Ghost",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (design, outsider):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, **_kwargs):
            raise AssertionError("skipped-only dispatch must not create an Agent run")

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 你来安排测试任务")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Ghost","goal":"做群外成员测试"}',
        )

        payload = api.get_messages()
        assistant_messages = [message for message in payload["messages"] if message["role"] == "assistant"]
        parent = next(message for message in assistant_messages if message["task_id"] == sent["task_id"])

        assert "我没能找到可以接这个任务的群组 Agent。" in parent["content"]
        assert "- Ghost: 不在当前群组中" in parent["content"]
        assert parent["metadata"]["group_dispatch_count"] == 0
        assert parent["metadata"]["group_dispatch_skipped"] == ["Ghost: 不在当前群组中"]
        assert parent["metadata"]["group_agent_summary_pending"] is True
        summary_message = next(
            message
            for message in assistant_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        assert summary_message["status"] == "processing"
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "未执行派活：" in summary_task.description
        assert "- Ghost: 不在当前群组中" in summary_task.description
        assert "没有 Agent 实际执行" in summary_task.description
    finally:
        store.close()


def test_group_dispatch_workflow_request_guides_to_studio(tmp_path, monkeypatch):
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
    }

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for runnable in (design, workflow):
                if runnable_id == runnable["id"] or clean_name in {runnable["name"], runnable.get("nickname")}:
                    return runnable
            return None

        def create_run_for_runnable_async(self, **_kwargs):
            raise AssertionError("group Workflow dispatch must not create a Run")

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 帮我跑一下流程")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "<oha_group_dispatch>"
                '{"tasks":[{"action":"dispatch_group_workflow","workflow":"Web Flow","goal":"运行发布流程"}]}'
                "</oha_group_dispatch>"
            ),
        )

        payload = api.get_messages()
        assistant_messages = [message for message in payload["messages"] if message["role"] == "assistant"]
        parent = next(message for message in assistant_messages if message["task_id"] == sent["task_id"])

        assert "我没能找到可以接这个任务的群组 Agent。" in parent["content"]
        assert "Workflow Studio" in parent["content"]
        assert "未找到群组 Agent" not in parent["content"]
        assert parent["metadata"]["group_dispatch_count"] == 0
        assert parent["metadata"]["group_dispatch_skipped"] == [
            "Web Flow: Workflow 不能在群聊派发中直接执行，请到 Agent Studio 的 Workflow Studio 或 Runs 面板运行",
        ]
        summary_message = next(
            message
            for message in assistant_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "Workflow Studio" in summary_task.description
        assert "没有 Agent 实际执行" in summary_task.description
    finally:
        store.close()


def test_group_dispatch_run_creation_failure_reports_to_main_summary(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "Code",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            if runnable_id == coding["id"] or clean_name in {coding["name"], coding["nickname"]}:
                return coding
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            raise AgentRuntimeError("Agent 模型配置不可用")

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[coding["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 安排一下")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Code","goal":"写一个测试脚本"}',
        )

        messages = api.get_messages()["messages"]
        assistant_messages = [message for message in messages if message["role"] == "assistant"]
        failed_agent = next(
            message
            for message in assistant_messages
            if message["metadata"].get("sender", {}).get("nickname") == "Code"
        )
        assert failed_agent["status"] == "failed"
        assert failed_agent["content"] == (
            "Code 执行失败，已把失败原因交给主模型整理。\n"
            "任务：写一个测试脚本\n\n"
            "Agent 模型配置不可用"
        )
        assert failed_agent["metadata"]["agent_report"] == "Agent 模型配置不可用"
        assert failed_agent["metadata"]["agent_report_status"] == "failed"

        summary_message = next(
            message
            for message in assistant_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        assert summary_message["status"] == "processing"
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "Code：执行失败" in summary_task.description
        assert "任务：写一个测试脚本" in summary_task.description
        assert "汇报：Agent 模型配置不可用" in summary_task.description
    finally:
        store.close()


def test_group_main_model_dispatch_tagged_tasks_block_is_hidden_and_dispatched(tmp_path, monkeypatch):
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
            clean_name = str(name or "").lstrip("@")
            if runnable_id == design["id"] or clean_name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "upstream": upstream,
            })
            run = {
                "run_id": "agent_design_run",
                "run_group_id": run_group_id or "run_group_dispatch",
                "status": "processing",
                "result": "",
                "runnable": design,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": "视觉测试完成。",
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
            result=(
                "我会先让 Design 做视觉测试。\n"
                "<oha_group_dispatch>\n"
                '{"tasks":[{"action":"dispatch_group_agent","agent":"Design","goal":"做视觉测试"}]}\n'
                "</oha_group_dispatch>"
            ),
        )

        messages = api.get_messages()["messages"]
        assistant_messages = [message for message in messages if message["role"] == "assistant"]

        assert len(calls) == 1
        assert calls[0]["runnable_id"] == "agent_design"
        assert calls[0]["user_goal"] == "做视觉测试"
        assert assistant_messages[0]["content"] == "我会先让 Design 做视觉测试。\n\n我把这个任务派给 Design 了。"
        assert "oha_group_dispatch" not in assistant_messages[0]["content"]
        assert "dispatch_group_agent" not in assistant_messages[0]["content"]
        assert assistant_messages[1]["content"] == (
            "Design 已完成，并把结果交给主模型汇总。\n"
            "任务：做视觉测试\n\n"
            "视觉测试完成。"
        )
    finally:
        store.close()


def test_group_main_model_dispatch_bare_json_block_is_hidden_and_dispatched(tmp_path, monkeypatch):
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
            clean_name = str(name or "").lstrip("@")
            if runnable_id == design["id"] or clean_name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
            })
            run = {
                "run_id": "agent_design_bare_json_run",
                "run_group_id": run_group_id or "run_group_dispatch",
                "status": "processing",
                "result": "",
                "runnable": design,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": "视觉测试完成。",
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
            result=(
                "我会先让 Design 做视觉测试。\n"
                '{"action":"dispatch_group_agent","agent":"Design","goal":"做视觉测试"}'
            ),
        )

        messages = api.get_messages()["messages"]
        assistant_messages = [message for message in messages if message["role"] == "assistant"]

        assert len(calls) == 1
        assert calls[0]["runnable_id"] == "agent_design"
        assert calls[0]["user_goal"] == "做视觉测试"
        assert assistant_messages[0]["content"] == "我会先让 Design 做视觉测试。\n\n我把这个任务派给 Design 了。"
        assert "dispatch_group_agent" not in assistant_messages[0]["content"]
        assert '"action"' not in assistant_messages[0]["content"]
        assert '{"action"' not in assistant_messages[0]["content"]
        assert assistant_messages[1]["content"] == (
            "Design 已完成，并把结果交给主模型汇总。\n"
            "任务：做视觉测试\n\n"
            "视觉测试完成。"
        )
    finally:
        store.close()


def test_group_main_model_dispatch_multiple_tagged_blocks_are_all_dispatched(tmp_path, monkeypatch):
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
            run_group = run_group_id or "run_group_dispatch"
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "actual_run_group_id": run_group,
                "upstream": upstream,
            })
            runnable = design if runnable_id == design["id"] else coding
            run = {
                "run_id": f"{runnable_id}_run",
                "run_group_id": run_group,
                "status": "processing",
                "result": "",
                "runnable": runnable,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": f"{runnable['nickname']} done",
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 这次分两段派活")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我来分两段派活。\n"
                "<oha_group_dispatch>\n"
                '{"action":"dispatch_group_agent","agent":"Design","goal":"整理界面验收点"}\n'
                "</oha_group_dispatch>\n"
                "然后再安排编码。\n"
                "<oha_group_dispatch>\n"
                '{"action":"dispatch_group_agent","agent":"Code","goal":"写验证脚本"}\n'
                "</oha_group_dispatch>"
            ),
        )

        messages = api.get_messages()["messages"]
        assistant_messages = [message for message in messages if message["role"] == "assistant"]
        parent = next(message for message in assistant_messages if message["task_id"] == sent["task_id"])

        assert [call["runnable_id"] for call in calls] == ["agent_design", "agent_coding"]
        assert [call["user_goal"] for call in calls] == ["整理界面验收点", "写验证脚本"]
        assert calls[0]["run_group_id"] == ""
        assert calls[1]["run_group_id"] == "run_group_dispatch"
        assert parent["metadata"]["group_dispatch_count"] == 2
        assert parent["metadata"]["group_dispatch_run_group_id"] == "run_group_dispatch"
        assert "我把 2 个任务分别派给 Design、Code 了。" in parent["content"]
        assert "oha_group_dispatch" not in parent["content"]
        assert "dispatch_group_agent" not in parent["content"]
        delegated = [
            message
            for message in assistant_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        ]
        assert [message["metadata"]["delegated_goal"] for message in delegated] == ["整理界面验收点", "写验证脚本"]
    finally:
        store.close()


def test_group_dispatch_parser_exposes_structured_directives_and_legacy_requests():
    content = (
        "我会按工具输入格式安排。\n"
        "<oha_group_dispatch>\n"
        '{"tool":"dispatch_group_agent","input":{"agent":"Design","goal":"整理验收点"}}\n'
        "</oha_group_dispatch>\n"
        "<oha_group_dispatch>\n"
        '{"action":"oha.group_dispatch","input":{"kind":"agent","target":"Code","goal":"写验证脚本"}}\n'
        "</oha_group_dispatch>"
    )

    directives = ChatAPI._parse_group_dispatch_directives(content)
    legacy_requests = ChatAPI._parse_group_dispatch_requests(content)
    native_directives = ChatAPI._parse_group_dispatch_directives(
        '{"tool":"oha.group_dispatch","input":{"tasks":[{"kind":"agent","target":"QA","goal":"列验收清单"}]}}'
    )
    old_tag_directives = ChatAPI._parse_group_dispatch_directives(
        '<yachiyo_group_dispatch>{"tool":"oha.group_dispatch","input":{"tasks":[{"target":"Legacy","goal":"旧协议"}]}}</yachiyo_group_dispatch>'
    )
    old_tag_visible = ChatAPI._strip_group_dispatch_payloads(
        '旧协议块前缀\n<yachiyo_group_dispatch>{"tool":"oha.group_dispatch","input":{"tasks":[{"target":"Legacy","goal":"旧协议"}]}}</yachiyo_group_dispatch>\n旧协议块后缀'
    )

    assert all(isinstance(directive, GroupDispatchDirective) for directive in directives)
    assert [directive.target for directive in directives] == ["Design", "Code"]
    assert [directive.goal for directive in directives] == ["整理验收点", "写验证脚本"]
    assert [directive.target for directive in native_directives] == ["QA"]
    assert [directive.goal for directive in native_directives] == ["列验收清单"]
    assert old_tag_directives == []
    assert "Legacy" not in old_tag_visible
    assert "旧协议块前缀" in old_tag_visible
    assert "旧协议块后缀" in old_tag_visible
    assert legacy_requests == [directive.as_request() for directive in directives]
    assert all(isinstance(request, dict) for request in legacy_requests)


def test_group_dispatch_context_markers_use_oha_yachiyo_and_keep_legacy_read_compatibility():
    current = (
        "请安排 Design 做验收\n\n"
        "[Oha-Yachiyo 群组上下文]\n"
        "- Design（Agent；Design Agent）\n"
    )
    legacy = (
        "请安排 Design 做验收\n\n"
        "[Yachiyo 群组上下文]\n"
        "- Design（Agent；Design Agent）\n"
    )

    assert ChatAPI._group_dispatch_user_request_from_task(current) == "请安排 Design 做验收"
    assert ChatAPI._group_dispatch_user_request_from_task(legacy) == "请安排 Design 做验收"
    assert ChatAPI._group_dispatch_agent_names_from_task(current) == ["Design"]
    assert ChatAPI._group_dispatch_agent_names_from_task(legacy) == ["Design"]
    assert ChatAPI._is_group_followup_task_description("[Oha-Yachiyo 群组补充/纠偏]\n补充上下文")
    assert ChatAPI._is_group_followup_task_description("[Yachiyo 群组补充/纠偏]\n旧补充上下文")


def test_group_main_model_dispatch_accepts_model_field_variants(tmp_path, monkeypatch):
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
            run_group = run_group_id or "run_group_dispatch"
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "actual_run_group_id": run_group,
            })
            runnable = design if runnable_id == design["id"] else coding
            run = {
                "run_id": f"{runnable_id}_run",
                "run_group_id": run_group,
                "status": "processing",
                "result": "",
                "runnable": runnable,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": f"{runnable['nickname']} done",
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 字段名可能不完全标准，也要安排出去")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我会分别安排设计和编码。\n"
                "<oha_group_dispatch>\n"
                '{"Delegations":['
                '{"type":"agent","agentName":"Design","taskGoal":"整理验收点"},'
                '{"kind":"agent","runnableId":"agent_coding","objective":"写验证脚本"}'
                "]}\n"
                "</oha_group_dispatch>"
            ),
        )

        messages = api.get_messages()["messages"]
        assistant_messages = [message for message in messages if message["role"] == "assistant"]
        parent = next(message for message in assistant_messages if message["task_id"] == sent["task_id"])

        assert [call["runnable_id"] for call in calls] == ["agent_design", "agent_coding"]
        assert [call["user_goal"] for call in calls] == ["整理验收点", "写验证脚本"]
        assert calls[0]["run_group_id"] == ""
        assert calls[1]["run_group_id"] == "run_group_dispatch"
        assert parent["metadata"]["group_dispatch_count"] == 2
        assert "我把 2 个任务分别派给 Design、Code 了。" in parent["content"]
        assert "Delegations" not in parent["content"]
        assert "agentName" not in parent["content"]
    finally:
        store.close()


def test_group_main_model_dispatch_accepts_tool_input_envelopes(tmp_path, monkeypatch):
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
            run_group = run_group_id or "run_group_dispatch"
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "actual_run_group_id": run_group,
            })
            runnable = design if runnable_id == design["id"] else coding
            run = {
                "run_id": f"{runnable_id}_run",
                "run_group_id": run_group,
                "status": "processing",
                "result": "",
                "runnable": runnable,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": f"{runnable['nickname']} done",
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 用工具输入格式派活")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我会按工具输入格式安排。\n"
                '{"tool":"oha.group_dispatch","input":{"tasks":['
                '{"kind":"agent","target":"Design","goal":"整理验收点"},'
                '{"type":"agent","target":"Code","goal":"写验证脚本"}'
                "]}}"
            ),
        )

        messages = api.get_messages()["messages"]
        assistant_messages = [message for message in messages if message["role"] == "assistant"]
        parent = next(message for message in assistant_messages if message["task_id"] == sent["task_id"])

        assert [call["runnable_id"] for call in calls] == ["agent_design", "agent_coding"]
        assert [call["user_goal"] for call in calls] == ["整理验收点", "写验证脚本"]
        assert calls[0]["run_group_id"] == ""
        assert calls[1]["run_group_id"] == "run_group_dispatch"
        assert parent["metadata"]["group_dispatch_count"] == 2
        assert "我把 2 个任务分别派给 Design、Code 了。" in parent["content"]
        assert "oha.group_dispatch" not in parent["content"]
        assert "tasks" not in parent["content"]
    finally:
        store.close()


def test_group_main_model_dispatch_accepts_agent_target_lists(tmp_path, monkeypatch):
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
            run_group = run_group_id or f"run_group_dispatch_{len(calls) // 2 + 1}"
            calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "actual_run_group_id": run_group,
            })
            runnable = design if runnable_id == design["id"] else coding
            run = {
                "run_id": f"{runnable_id}_run_{len(calls)}",
                "run_group_id": run_group,
                "status": "processing",
                "result": "",
                "runnable": runnable,
            }
            if on_complete:
                on_complete({
                    **run,
                    "status": "completed",
                    "result": f"{runnable['nickname']} done",
                })
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 用 Agent 列表派活")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我会把同一个目标交给两个 Agent。\n"
                "<oha_group_dispatch>\n"
                '{"action":"dispatch_group_agent","agents":["Design","Code"],"goal":"分别给出验收建议"}\n'
                "</oha_group_dispatch>"
            ),
        )

        messages = api.get_messages()["messages"]
        parent = next(
            message
            for message in messages
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )

        assert [call["runnable_id"] for call in calls] == ["agent_design", "agent_coding"]
        assert [call["user_goal"] for call in calls] == ["分别给出验收建议", "分别给出验收建议"]
        assert calls[0]["run_group_id"] == ""
        assert calls[1]["run_group_id"] == calls[0]["actual_run_group_id"]
        assert parent["metadata"]["group_dispatch_count"] == 2
        assert "我把 2 个任务分别派给 Design、Code 了。" in parent["content"]

        second = api.send_message("@主模型 用中文分隔符再派一次")
        assert second["ok"] is True
        runtime.state.update_task_status(
            second["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agents":"Design、Code","goal":"整理第二轮建议"}',
        )

        api.get_messages()
        assert [call["user_goal"] for call in calls[-2:]] == ["整理第二轮建议", "整理第二轮建议"]
        assert calls[-2]["actual_run_group_id"] != calls[0]["actual_run_group_id"]
        assert calls[-2]["actual_run_group_id"] == calls[-1]["actual_run_group_id"]

        third = api.send_message("@主模型 给每个 Agent 不同任务")
        assert third["ok"] is True
        runtime.state.update_task_status(
            third["task_id"],
            TaskStatus.COMPLETED,
            result=(
                '{"action":"dispatch_group_agent","agents":["Design","Code"],'
                '"goals":["整理设计验收点","写验证脚本"]}'
            ),
        )

        api.get_messages()
        assert [call["runnable_id"] for call in calls[-2:]] == ["agent_design", "agent_coding"]
        assert [call["user_goal"] for call in calls[-2:]] == ["整理设计验收点", "写验证脚本"]
        assert calls[-2]["actual_run_group_id"] != calls[-4]["actual_run_group_id"]
        assert calls[-2]["actual_run_group_id"] == calls[-1]["actual_run_group_id"]

        fourth = api.send_message("@主模型 用映射格式派活")
        assert fourth["ok"] is True
        runtime.state.update_task_status(
            fourth["task_id"],
            TaskStatus.COMPLETED,
            result=(
                '{"assignments":{"Design":"整理映射设计点","Code":"实现映射脚本"}}'
            ),
        )

        api.get_messages()
        assert [call["runnable_id"] for call in calls[-2:]] == ["agent_design", "agent_coding"]
        assert [call["user_goal"] for call in calls[-2:]] == ["整理映射设计点", "实现映射脚本"]
        assert calls[-2]["actual_run_group_id"] != calls[-4]["actual_run_group_id"]
        assert calls[-2]["actual_run_group_id"] == calls[-1]["actual_run_group_id"]

        fifth = api.send_message("@主模型 用 agents 映射格式派活")
        assert fifth["ok"] is True
        runtime.state.update_task_status(
            fifth["task_id"],
            TaskStatus.COMPLETED,
            result=(
                '{"agents":{"Design":{"goal":"整理 agents 映射设计点"},"Code":{"task":"实现 agents 映射脚本"}}}'
            ),
        )

        api.get_messages()
        assert [call["runnable_id"] for call in calls[-2:]] == ["agent_design", "agent_coding"]
        assert [call["user_goal"] for call in calls[-2:]] == ["整理 agents 映射设计点", "实现 agents 映射脚本"]
        assert calls[-2]["actual_run_group_id"] != calls[-4]["actual_run_group_id"]
        assert calls[-2]["actual_run_group_id"] == calls[-1]["actual_run_group_id"]
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


def test_group_main_model_dispatch_stream_hides_partial_json_without_rewind(tmp_path, monkeypatch):
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
        intro = "我会先交给 Design 做测试。"
        runtime.chat_session.upsert_assistant_message(
            sent["task_id"],
            f'{intro}\n{{"action":"dispatch_group_agent","agent":"Design","goal"',
            MessageStatus.PROCESSING,
        )

        first_payload = api.get_messages()
        first_assistant = next(message for message in first_payload["messages"] if message["role"] == "assistant")
        assert first_assistant["content"] == intro
        assert "dispatch_group_agent" not in first_assistant["content"]
        assert first_assistant["metadata"]["group_dispatch_stream_visible_content"] == intro

        runtime.chat_session.upsert_assistant_message(
            sent["task_id"],
            '{"action":"dispatch_group_agent","agent":"Design","goal":"做测试"}',
            MessageStatus.PROCESSING,
        )
        second_assistant = next(message for message in api.get_messages()["messages"] if message["role"] == "assistant")
        assert second_assistant["content"] == intro
    finally:
        activity_store.close()
        store.close()


def test_group_main_model_dispatch_stream_hides_open_json_fence_prefix(tmp_path, monkeypatch):
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
        intro = "我会先交给 Design 做测试。"
        runtime.chat_session.upsert_assistant_message(
            sent["task_id"],
            f"{intro}\n```json\n{{",
            MessageStatus.PROCESSING,
        )

        assistant = next(message for message in api.get_messages()["messages"] if message["role"] == "assistant")

        assert assistant["content"] == intro
        assert "```" not in assistant["content"]
        assert "{" not in assistant["content"]
        assert assistant["metadata"]["group_dispatch_stream_visible_content"] == intro
    finally:
        activity_store.close()
        store.close()


def test_group_dispatch_pending_clears_when_final_message_has_no_dispatch(tmp_path, monkeypatch):
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

        def create_run_for_runnable_async(self, **_kwargs):
            raise AssertionError("final non-dispatch response must not create an Agent run")

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 安排一下")
        assert sent["ok"] is True
        runtime.state.update_task_status(sent["task_id"], TaskStatus.RUNNING)
        runtime.chat_session.upsert_assistant_message(
            sent["task_id"],
            '我先想一下。\n{"action":"dispatch_group_agent","agent":"Design","goal"',
            MessageStatus.PROCESSING,
        )
        pending = next(message for message in api.get_messages()["messages"] if message["role"] == "assistant")
        assert pending["content"] == "我先想一下。"
        assert pending["metadata"]["group_dispatch_pending"] is True

        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result="我想了一下，这个问题我可以直接回答，不需要派给其他 Agent。",
        )
        completed = next(message for message in api.get_messages()["messages"] if message["role"] == "assistant")

        assert completed["status"] == "completed"
        assert completed["content"] == "我想了一下，这个问题我可以直接回答，不需要派给其他 Agent。"
        assert "group_dispatch_pending" not in completed["metadata"]
        assert "group_dispatch_stream_visible_content" not in completed["metadata"]
    finally:
        activity_store.close()
        store.close()


def test_group_dispatch_expected_request_falls_back_to_explicit_agent_mention(tmp_path, monkeypatch):
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
        def __init__(self):
            self.calls = []
            self.runs = {}

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(
            self,
            *,
            runnable_id="",
            name="",
            user_goal="",
            run_group_id="",
            upstream="",
            on_complete=None,
        ):
            self.calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "upstream": upstream,
            })
            run = {
                "run_id": "agent_run_design_fallback",
                "run_group_id": run_group_id or "run_group_fallback",
                "status": "completed",
                "result": "设计任务已经真实完成。",
                "runnable": design,
            }
            self.runs[run["run_id"]] = run
            if on_complete:
                on_complete(run)
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 帮我把这个目标安排给 Design 做")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result="我会安排 Design Agent 处理这个目标。",
        )

        messages = api.get_messages()["messages"]
        completed = next(
            message
            for message in messages
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )
        delegated = next(
            message
            for message in messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        )

        assert service.calls
        assert service.calls[0]["runnable_id"] == design["id"]
        assert "主模型说明了分工但没有生成机器派发请求" in service.calls[0]["user_goal"]
        assert "帮我把这个目标安排给 Design 做" in service.calls[0]["user_goal"]
        assert completed["status"] == "completed"
        assert "我已根据用户明确提到的群内 Agent 创建真实任务" in completed["content"]
        assert "我把这个任务派给 Design 了。" in completed["content"]
        assert "这次没有实际派出 Agent" not in completed["content"]
        assert completed["metadata"]["group_dispatch_handled"] is True
        assert completed["metadata"]["group_dispatch_count"] == 1
        assert completed["metadata"]["group_dispatch_run_group_id"] == "run_group_fallback"
        assert completed["metadata"]["group_dispatch_skipped"] == []
        assert completed["activity_events"][0]["title"] == "群组任务已派发"
        assert delegated["status"] == "completed"
        assert delegated["metadata"]["run_id"] == "agent_run_design_fallback"
        assert delegated["metadata"]["delegated_goal"] == service.calls[0]["user_goal"]
        assert delegated["content"].startswith("Design 已完成，并把结果交给主模型汇总。")
        assert "这是群组自然目标的兜底派发" in delegated["content"]
        assert "你的身份：Design" in delegated["content"]
        assert "帮我把这个目标安排给 Design 做" in delegated["content"]
        assert "设计任务已经真实完成。" in delegated["content"]
    finally:
        activity_store.close()
        store.close()


def test_group_dispatch_partial_request_falls_back_to_missing_explicit_agent(tmp_path, monkeypatch):
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
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "furina",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def __init__(self):
            self.calls = []
            self.runs = {}

        def resolve_runnable(self, *, runnable_id="", name=""):
            for runnable in (design, coding):
                if runnable_id == runnable["id"] or name in {runnable["name"], runnable["nickname"]}:
                    return runnable
            return None

        def create_run_for_runnable_async(
            self,
            *,
            runnable_id="",
            name="",
            user_goal="",
            run_group_id="",
            upstream="",
            on_complete=None,
        ):
            self.calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "upstream": upstream,
            })
            run = {
                "run_id": f"agent_run_{runnable_id}",
                "run_group_id": run_group_id or "run_group_partial",
                "status": "completed",
                "result": f"{runnable_id} 完成。",
                "runnable": design if runnable_id == design["id"] else coding,
            }
            self.runs[run["run_id"]] = run
            if on_complete:
                on_complete(run)
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True
        sent = api.send_message("Design Agent 和 Coding Agent 适合怎么分工做一个小项目？")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我先让 Design Agent 出规格，然后让 Coding Agent 基于规格实现。\n"
                '{"tasks":[{"action":"dispatch_group_agent","agent":"Design","goal":"产出项目规格"}]}'
            ),
        )

        messages = api.get_messages()["messages"]
        completed = next(
            message
            for message in messages
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )
        delegated = [
            message
            for message in messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        ]

        assert [call["runnable_id"] for call in service.calls] == [design["id"], coding["id"]]
        assert service.calls[0]["run_group_id"] == ""
        assert service.calls[1]["run_group_id"] == "run_group_partial"
        assert service.calls[0]["user_goal"] == "产出项目规格"
        assert "这是群组自然目标的兜底派发" in service.calls[1]["user_goal"]
        assert "Design Agent 和 Coding Agent 适合怎么分工做一个小项目？" in service.calls[1]["user_goal"]
        assert completed["status"] == "completed"
        assert "主模型只生成了部分群组派发请求" in completed["content"]
        assert "我把 2 个任务分别派给 Design、furina 了。" in completed["content"]
        assert completed["metadata"]["group_dispatch_handled"] is True
        assert completed["metadata"]["group_dispatch_count"] == 2
        assert completed["metadata"]["group_dispatch_run_group_id"] == "run_group_partial"
        assert len(delegated) == 2
        assert {message["metadata"]["run_id"] for message in delegated} == {
            "agent_run_agent_design",
            "agent_run_agent_coding",
        }
    finally:
        activity_store.close()
        store.close()


def test_group_explicit_agent_goal_dispatches_directly_without_main_model(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
        "category": "design",
        "description": "负责设计说明。",
    }
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "furina",
        "kind": "agent",
        "enabled": True,
        "category": "coding",
        "description": "负责实现代码。",
    }

    class FakeRunnableService:
        def __init__(self):
            self.calls = []
            self.runs = {}

        def resolve_runnable(self, *, runnable_id="", name=""):
            for runnable in (design, coding):
                if runnable_id == runnable["id"] or name in {runnable["name"], runnable["nickname"]}:
                    return runnable
            return None

        def create_run_for_runnable_async(
            self,
            *,
            runnable_id="",
            name="",
            user_goal="",
            run_group_id="",
            upstream="",
            on_complete=None,
        ):
            self.calls.append({
                "runnable_id": runnable_id,
                "name": name,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "upstream": upstream,
            })
            run = {
                "run_id": f"agent_run_{runnable_id}",
                "run_group_id": run_group_id or "run_group_direct",
                "status": "completed",
                "result": f"{runnable_id} 完成。",
                "runnable": design if runnable_id == design["id"] else coding,
            }
            self.runs[run["run_id"]] = run
            if on_complete:
                on_complete(run)
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True
        sent = api.send_message("请 Design Agent 和 Coding Agent 一起做一个小项目")
        assert sent["ok"] is True
        assert sent["status"] == "completed"

        parent_task = runtime.state.get_task(sent["task_id"])
        assert parent_task.status == TaskStatus.COMPLETED
        assert [call["runnable_id"] for call in service.calls] == [design["id"], coding["id"]]
        assert service.calls[0]["run_group_id"] == ""
        assert service.calls[1]["run_group_id"] == "run_group_direct"
        assert "这是群组用户消息的直接派发" in service.calls[0]["user_goal"]
        assert "请 Design Agent 和 Coding Agent 一起做一个小项目" in service.calls[1]["user_goal"]

        messages = api.get_messages()["messages"]
        parent = next(
            message
            for message in messages
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )
        delegated = [
            message
            for message in messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        ]
        assert parent["status"] == "completed"
        assert parent["metadata"]["group_dispatch_direct"] is True
        assert parent["metadata"]["group_dispatch_count"] == 2
        assert parent["metadata"]["group_dispatch_run_group_id"] == "run_group_direct"
        assert "用户已明确点名群内 Agent" in parent["content"]
        assert "我把 2 个任务分别派给 Design、furina 了。" in parent["content"]
        assert len(delegated) == 2
        assert {message["metadata"]["run_id"] for message in delegated} == {
            "agent_run_agent_design",
            "agent_run_agent_coding",
        }
    finally:
        activity_store.close()
        store.close()


def test_group_agent_capability_question_does_not_dispatch_directly(tmp_path, monkeypatch):
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
            self.calls = []

        def resolve_runnable(self, **_kwargs):
            return design

        def create_run_for_runnable_async(self, **kwargs):
            self.calls.append(kwargs)
            raise AssertionError("capability question must not dispatch directly")

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("Design Agent 是谁？能做什么？")
        assert sent["ok"] is True
        assert sent["status"] == "pending"
        assert service.calls == []
        assert runtime.state.get_task(sent["task_id"]).status == TaskStatus.PENDING
    finally:
        store.close()


def test_group_dispatch_missing_request_does_not_flag_plain_arrangement(tmp_path, monkeypatch):
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

        def create_run_for_runnable_async(self, **_kwargs):
            raise AssertionError("plain arrangement must not create an Agent run")

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 帮我安排一下今天的计划")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result="今天可以先整理目标，再确认优先级，最后留出复盘时间。",
        )

        completed = next(message for message in api.get_messages()["messages"] if message["role"] == "assistant")

        assert completed["status"] == "completed"
        assert completed["content"] == "今天可以先整理目标，再确认优先级，最后留出复盘时间。"
        assert "group_dispatch_handled" not in completed["metadata"]
        assert completed["activity_events"] == []
    finally:
        activity_store.close()
        store.close()


def test_group_main_model_dispatch_stream_hides_compact_tag_and_smart_quotes(tmp_path, monkeypatch):
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
            (
                "好~又来啦！\n\n"
                "<yachiyogroupdispatch>\n"
                "{”tasks”:[{”action”:”dispatchgroupagent”,”agent”:”Design”,”goal”:”做测试”}]}"
            ),
            MessageStatus.PROCESSING,
            metadata={
                "group_dispatch_stream_visible_content": (
                    "好~又来啦！\n\n"
                    "<yachiyogroupdispatch>\n"
                    "{”tasks”:[{”action”:”dispatchgroupagent”,”agent”:”Design”,”goal”:”做测试”}]}"
                )
            },
        )

        assistant = next(message for message in api.get_messages()["messages"] if message["role"] == "assistant")

        assert assistant["content"] == "好~又来啦！"
        assert "yachiyogroupdispatch" not in assistant["content"]
        assert "dispatchgroupagent" not in assistant["content"]
        assert assistant["metadata"]["group_dispatch_stream_visible_content"] == "好~又来啦！"
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
        assert "[Oha-Yachiyo 群组执行约定]" in calls[0]["upstream"]
        assert "你在群内身份是：Design" in calls[0]["upstream"]
        assert "- Design（Agent；Design Agent）" in calls[0]["upstream"]
        messages_payload = api.get_messages()
        assert messages_payload["is_processing"] is True
        assert messages_payload["processing_count"] == 1
        current = next(
            item for item in api.list_sessions()["sessions"]
            if item["session_id"] == runtime.chat_session.session_id
        )
        assert current["is_processing"] is True
        assert current["processing_count"] == 1
    finally:
        store.close()


def test_group_dispatch_agent_completion_after_session_switch_writes_back_original_group(tmp_path, monkeypatch):
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
            self.on_complete = None

        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            self.on_complete = on_complete
            return {
                "run_id": "agent_run_design",
                "run_group_id": run_group_id or "run_group_dispatch",
                "status": "processing",
                "result": "",
                "runnable": design,
            }

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        original_session_id = created["session_id"]
        sent = api.send_message("@主模型 安排一下")
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"做视觉测试"}',
        )
        api.get_messages()
        assert callable(service.on_complete)

        runtime.start_new_session()
        current_session_id = runtime.chat_session.session_id
        service.on_complete({
            "run_id": "agent_run_design",
            "run_group_id": "run_group_dispatch",
            "status": "completed",
            "result": "视觉测试已经完成。",
            "timeline": [],
            "runnable": design,
        })

        assert runtime.chat_session.session_id == current_session_id
        stored_messages = store.load_messages(original_session_id)
        agent_message = next(
            message
            for message in stored_messages
            if json.loads(message.metadata_json).get("run_id") == "agent_run_design"
        )
        agent_metadata = json.loads(agent_message.metadata_json)
        assert agent_message.status == MessageStatus.COMPLETED.value
        assert "Design 已完成，并把结果交给主模型汇总。" in agent_message.content
        assert agent_metadata["agent_report"] == "视觉测试已经完成。"
        assert agent_metadata["agent_report_status"] == "completed"

        summary_message = next(
            message
            for message in stored_messages
            if json.loads(message.metadata_json).get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = runtime.state.get_task(summary_message.task_id)
        assert summary_message.status == MessageStatus.PROCESSING.value
        assert summary_task is not None
        assert summary_task.chat_session_id == original_session_id
        assert "汇报：视觉测试已经完成。" in summary_task.description
    finally:
        store.close()


def test_group_agent_running_status_keeps_typing_placeholder(tmp_path, monkeypatch):
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
            return {
                "run_id": "agent_run_running",
                "run_group_id": run_group_id or "run_group_dispatch",
                "status": "running",
                "result": "",
                "runnable": design,
            }

        def get_run(self, run_id):
            assert run_id == "agent_run_running"
            return {
                "run_id": "agent_run_running",
                "run_group_id": "run_group_dispatch",
                "status": "running",
                "result": "",
                "runnable": design,
                "timeline": [
                    {"event": "agent.run.started", "detail": "Design Agent started"},
                    {"event": "agent.runtime.compiled", "detail": "Runtime compiled"},
                    {"event": "agent.tool.call", "detail": "workspace.read"},
                ],
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

        agent_message = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant" and message["metadata"].get("sender", {}).get("nickname") == "Design"
        ][0]
        assert agent_message["status"] == "processing"
        assert agent_message["content"] == ""
        assert agent_message["metadata"]["run_status"] == "processing"
        assert agent_message["metadata"]["run_progress_title"] == "正在处理工具结果"
        assert "workspace.read" in agent_message["metadata"]["run_progress_detail"]
    finally:
        store.close()


def test_group_agent_running_progress_hides_internal_model_json(tmp_path, monkeypatch):
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
            return {
                "run_id": "agent_run_model_json",
                "run_group_id": run_group_id or "run_group_dispatch",
                "status": "running",
                "result": "",
                "runnable": design,
            }

        def get_run(self, run_id):
            assert run_id == "agent_run_model_json"
            return {
                "run_id": "agent_run_model_json",
                "run_group_id": "run_group_dispatch",
                "status": "running",
                "result": "",
                "runnable": design,
                "timeline": [
                    {"event": "agent.run.started", "detail": "Design Agent started"},
                    {"event": "agent.model.response", "detail": '{"action":"tool","tool":"terminal.run","input":{"command":"python3 demo.py"}}'},
                ],
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

        agent_message = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant" and message["metadata"].get("sender", {}).get("nickname") == "Design"
        ][0]
        assert agent_message["status"] == "processing"
        assert agent_message["content"] == ""
        assert agent_message["metadata"]["run_progress_title"] == "正在解析模型响应"
        detail = agent_message["metadata"]["run_progress_detail"]
        assert "正在读取模型返回" in detail
        assert "action" not in detail
        assert "terminal.run" not in detail
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
        assert payload["processing_count"] == 1
        assert payload["approval_count"] == 1
        session_info = api.get_session_info()
        assert session_info["processing_count"] == 1
        assert session_info["approval_count"] == 1
        current = next(
            item for item in api.list_sessions()["sessions"]
            if item["session_id"] == runtime.chat_session.session_id
        )
        assert current["processing_count"] == 1
        assert current["approval_count"] == 1
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
                self.run = {
                    **self.run,
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "approval_id": "approval_fake",
                        "tool": "terminal.run",
                        "input_preview": {"command": "pytest tests/test_chat_api.py -q"},
                    },
                }
                on_complete(self.run)
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
        assert agent_message["content"] == (
            "Design 已完成，并把结果交给主模型汇总。\n"
            "任务：运行测试\n\n"
            "测试已经通过，覆盖群组派发和审批恢复。"
        )
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


def test_plain_group_goal_approval_flow_continues_to_main_summary(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "Coding",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def __init__(self):
            self.run = {
                "run_id": "agent_run_coding_waiting",
                "run_group_id": "run_group_dispatch",
                "status": "processing",
                "result": "",
                "runnable": coding,
            }

        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            if runnable_id == coding["id"] or clean_name in {coding["name"], coding["nickname"]}:
                return coding
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            self.run = {
                **self.run,
                "run_group_id": run_group_id or "run_group_dispatch",
            }
            if on_complete:
                self.run = {
                    **self.run,
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "approval_id": "approval_terminal",
                        "tool": "terminal.run",
                        "input_preview": {
                            "command": "python3 scripts/verify_group.py",
                            "cwd": "/workspace/demo",
                        },
                    },
                }
                on_complete(self.run)
            return self.run

        def get_run(self, run_id):
            assert run_id == "agent_run_coding_waiting"
            return self.run

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[coding["id"]])
        assert created["ok"] is True
        sent = api.send_message("请让群里合适的 Agent 跑一下验证脚本")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我会让 Coding 运行验证脚本。\n"
                "<oha_group_dispatch>\n"
                '{"action":"dispatch_group_agent","agent":"Coding","goal":"运行验证脚本"}\n'
                "</oha_group_dispatch>"
            ),
        )

        approval_payload = api.get_messages()
        approval_messages = [message for message in approval_payload["messages"] if message["role"] == "assistant"]
        parent = next(message for message in approval_messages if message["task_id"] == sent["task_id"])
        agent_message = next(
            message
            for message in approval_messages
            if message["metadata"].get("sender", {}).get("nickname") == "Coding"
        )
        assert parent["metadata"]["group_dispatch_count"] == 1
        assert "group_agent_summary_pending" not in parent["metadata"]
        assert not any(
            message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
            for message in approval_messages
        )
        assert "oha_group_dispatch" not in parent["content"]
        assert agent_message["status"] == "processing"
        assert agent_message["metadata"]["run_status"] == "approval_required"
        assert agent_message["metadata"]["pending_approval"]["tool"] == "terminal.run"
        assert agent_message["metadata"]["pending_approval"]["input_preview"]["command"] == "python3 scripts/verify_group.py"
        assert agent_message["content"] == (
            "Coding 需要你确认一次工具调用，批准后会继续执行当前任务。\n"
            "工具：terminal.run\n"
            "关联任务：运行验证脚本\n"
            "请求摘要：命令：python3 scripts/verify_group.py"
        )
        assert approval_payload["approval_count"] == 1
        assert api.get_session_info()["approval_count"] == 1
        current = next(
            item for item in api.list_sessions()["sessions"]
            if item["session_id"] == runtime.chat_session.session_id
        )
        assert current["approval_count"] == 1

        service.run = {
            **service.run,
            "status": "processing",
            "result": "",
            "pending_approval": {},
        }
        processing_payload = api.get_messages()
        processing_agent = next(
            message
            for message in processing_payload["messages"]
            if message["metadata"].get("sender", {}).get("nickname") == "Coding"
        )
        assert processing_payload["approval_count"] == 0
        assert processing_agent["id"] == agent_message["id"]
        assert processing_agent["status"] == "processing"
        assert processing_agent["content"] == ""
        assert processing_agent["metadata"]["run_status"] == "processing"
        assert processing_agent["metadata"]["pending_approval"] == {}
        assert processing_agent["metadata"]["run_progress_title"] == "已批准工具调用"
        assert "正在继续执行当前任务" in processing_agent["metadata"]["run_progress_detail"]
        assert not any(
            message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
            for message in processing_payload["messages"]
            if message["role"] == "assistant"
        )

        service.run = {
            **service.run,
            "status": "completed",
            "result": "验证脚本运行通过。",
            "pending_approval": {},
        }
        completed_payload = api.get_messages()
        completed_messages = [message for message in completed_payload["messages"] if message["role"] == "assistant"]
        completed_agent = next(
            message
            for message in completed_messages
            if message["metadata"].get("sender", {}).get("nickname") == "Coding"
        )
        summary_message = next(
            message
            for message in completed_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert completed_payload["approval_count"] == 0
        assert completed_agent["status"] == "completed"
        assert completed_agent["metadata"]["agent_report"] == "验证脚本运行通过。"
        assert completed_agent["content"] == (
            "Coding 已完成，并把结果交给主模型汇总。\n"
            "任务：运行验证脚本\n\n"
            "验证脚本运行通过。"
        )
        assert summary_task is not None
        assert "Coding：已完成" in summary_task.description
        assert "汇报：验证脚本运行通过。" in summary_task.description

        runtime.state.update_task_status(
            summary_message["task_id"],
            TaskStatus.COMPLETED,
            result="验证脚本已经跑完，可以继续下一步。",
        )
        final_payload = api.get_messages()
        final_parent = next(
            message
            for message in final_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )
        final_summary = next(
            message
            for message in final_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == summary_message["task_id"]
        )
        assert "group_agent_summary_pending" not in final_parent["metadata"]
        assert final_parent["metadata"]["group_agent_summary_status"] == "completed"
        assert final_summary["content"] == "验证脚本已经跑完，可以继续下一步。"
    finally:
        store.close()


def test_group_direct_agent_summary_concurrent_calls_create_one_followup(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    runtime.store.update_session_context(
        runtime.chat_session.session_id,
        conversation_kind="group",
        runnable_name="Concurrent Group",
        participants_json=json.dumps(
            [
                {"kind": "main", "id": "main", "name": "Yachiyo"},
                {"kind": "agent", "id": "agent_design", "name": "Design Agent", "nickname": "Design"},
            ],
            ensure_ascii=False,
        ),
    )
    source_message_id = runtime.chat_session.add_user_message("@Design 做并发整理")
    agent_message_id = runtime.chat_session.add_assistant_message(
        "Design 并发整理完成",
        metadata={
            "sender": {"kind": "agent", "id": "agent_design", "name": "Design Agent", "nickname": "Design"},
            "conversation_kind": "group",
            "runnable_kind": "agent",
            "runnable_id": "agent_design",
            "run_status": "completed",
            "agent_report": "Design 并发整理完成",
            "group_goal": "做并发整理",
            "source_message_id": source_message_id,
        },
    )

    original_create_task = runtime.state.create_task
    create_task_entered = threading.Event()
    release_create_task = threading.Event()
    create_task_calls = 0
    create_task_calls_lock = threading.Lock()

    def slow_create_task(*args, **kwargs):
        nonlocal create_task_calls
        with create_task_calls_lock:
            create_task_calls += 1
            call_index = create_task_calls
        if call_index == 1:
            create_task_entered.set()
            assert release_create_task.wait(timeout=2)
        return original_create_task(*args, **kwargs)

    runtime.state.create_task = slow_create_task

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(api._maybe_create_group_direct_agent_summary_task, agent_message_id)
            assert create_task_entered.wait(timeout=2)
            second = pool.submit(api._maybe_create_group_direct_agent_summary_task, agent_message_id)
            release_create_task.set()
            first.result(timeout=2)
            second.result(timeout=2)

        messages = runtime.chat_session.get_all_messages()
        agent_message = next(message for message in messages if message.message_id == agent_message_id)
        summary_messages = [
            message for message in messages
            if message.metadata.get("group_direct_agent_summary_for_message_id") == agent_message_id
        ]
        summary_task_id = agent_message.metadata["group_agent_summary_task_id"]
        summary_task = runtime.state.get_task(summary_task_id)

        assert create_task_calls == 1
        assert len(summary_messages) == 1
        assert agent_message.metadata["group_agent_summary_pending"] is True
        assert summary_task is not None
        assert summary_task.chat_session_id == runtime.chat_session.session_id
        assert "[Oha-Yachiyo 群组直接 Agent 汇总]" in summary_task.description
        assert "用户原始请求：@Design 做并发整理" in summary_task.description
    finally:
        runtime.state.create_task = original_create_task
        release_create_task.set()
        store.close()


def test_group_dispatch_uses_runtime_native_service_end_to_end(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    runtime.agent_runtime_service = service
    captured_contexts: list[str] = []

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        context = str(messages[-1]["content"])
        captured_contexts.append(context)
        assert "# Agent\nName: Coding Agent" in context
        assert "# User Goal\n做真实 Native 群聊派发验证" in context
        assert "[Oha-Yachiyo 群组执行约定]" in context
        assert "你在群内身份是：Coding" in context
        return {"content": "Coding native dispatch result"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        coding = service.create_agent(
            {
                "name": "Coding Agent",
                "nickname": "Coding",
                "description": "runs native group dispatch tests",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )

        created = api.create_group_session(name="Native Dispatch Group", participant_ids=[coding["agent_id"]])
        assert created["ok"] is True
        assert created["session_context"]["conversation_kind"] == "group"
        assert created["session_context"]["participants"][1]["id"] == coding["agent_id"]

        sent = api.send_message("@主模型 请安排 Coding 做真实 Native 群聊派发验证")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我会让 Coding 处理这件事。\n"
                '{"tool":"oha.group_dispatch","input":{"tasks":[{"kind":"agent","target":"Coding",'
                '"goal":"做真实 Native 群聊派发验证"}]}}'
            ),
        )

        dispatch_payload = api.get_messages()
        parent = next(
            message
            for message in dispatch_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )
        agent_message = next(
            message
            for message in dispatch_payload["messages"]
            if message["role"] == "assistant"
            and message["metadata"].get("sender", {}).get("nickname") == "Coding"
        )
        run_id = agent_message["metadata"]["run_id"]
        assert parent["metadata"]["group_dispatch_count"] == 1
        assert parent["metadata"]["group_dispatch_run_group_id"] == agent_message["metadata"]["run_group_id"]
        assert agent_message["status"] == "processing"
        assert agent_message["metadata"]["runnable_id"] == coding["agent_id"]
        assert agent_message["metadata"]["delegated_by_task_id"] == sent["task_id"]
        assert agent_message["metadata"]["delegated_goal"] == "做真实 Native 群聊派发验证"

        run = _wait_for_agent_run(service, run_id)
        assert run["status"] == "completed"
        assert run["runnable_id"] == coding["agent_id"]
        assert run["result"] == "Coding native dispatch result"
        assert captured_contexts

        completed_agent = _wait_for_assistant_content_contains(api, "Coding native dispatch result")
        assert completed_agent["metadata"]["run_id"] == run_id
        assert completed_agent["metadata"]["run_status"] == "completed"
        assert completed_agent["metadata"]["agent_report"] == "Coding native dispatch result"

        final_payload = api.get_messages()
        summary_message = next(
            message
            for message in final_payload["messages"]
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_message["status"] == "processing"
        assert summary_task is not None
        assert summary_task.chat_session_id == runtime.chat_session.session_id
        assert "Coding：已完成" in summary_task.description
        assert "汇报：Coding native dispatch result" in summary_task.description
    finally:
        service.close()
        store.close()


def test_group_agent_consecutive_approval_updates_pending_request(tmp_path, monkeypatch):
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
                self.run = {
                    **self.run,
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "approval_id": "approval_first",
                        "tool": "terminal.run",
                        "input_preview": {"command": "python3 first.py"},
                    },
                }
                on_complete(self.run)
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
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"运行连续审批"}',
        )

        first_message = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant" and message["metadata"].get("sender", {}).get("nickname") == "Design"
        ][0]
        assert api.get_messages()["approval_count"] == 1
        assert api.get_session_info()["approval_count"] == 1
        assert first_message["metadata"]["pending_approval"]["approval_id"] == "approval_first"
        assert first_message["metadata"]["pending_approval"]["input_preview"]["command"] == "python3 first.py"
        assert "python3 first.py" in first_message["content"]

        service.run = {
            **service.run,
            "status": "approval_required",
            "result": "等待审批：terminal.run",
            "pending_approval": {
                "approval_id": "approval_second",
                "tool": "terminal.run",
                "input_preview": {"command": "python3 second.py && python3 verify.py"},
            },
        }

        second_message = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant" and message["metadata"].get("sender", {}).get("nickname") == "Design"
        ][0]
        assert api.get_messages()["approval_count"] == 1
        assert api.get_session_info()["approval_count"] == 1
        assert second_message["id"] == first_message["id"]
        assert second_message["metadata"]["pending_approval"]["approval_id"] == "approval_second"
        assert second_message["metadata"]["pending_approval"]["input_preview"]["command"] == "python3 second.py && python3 verify.py"
        assert "python3 second.py" in second_message["content"]
        assert "python3 first.py" not in second_message["content"]
    finally:
        store.close()


def test_group_direct_agent_completion_keeps_full_goal_in_chat(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
    }
    long_goal = (
        "请做一个很长的移动端验收方案，包含信息架构、状态层级、审批提醒、"
        "失败提示、运行详情入口、产物入口、连续审批提示、长文本完整展示、"
        "主模型最终整理和用户下一步动作，并保留结尾标记 long-goal-tail-marker-917263"
    )

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            if runnable_id == design["id"] or str(name or "").lstrip("@") in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            run = {
                "run_id": "agent_run_long_goal",
                "run_group_id": run_group_id or "run_group_direct_long_goal",
                "status": "completed",
                "result": "长目标验收方案已经整理完成。",
                "pending_approval": {},
                "runnable": design,
            }
            if on_complete:
                on_complete(run)
            return run

        def get_run(self, run_id):
            assert run_id == "agent_run_long_goal"
            return {
                "run_id": "agent_run_long_goal",
                "run_group_id": "run_group_direct_long_goal",
                "status": "completed",
                "result": "长目标验收方案已经整理完成。",
                "pending_approval": {},
                "runnable": design,
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        sent = api.send_message(long_goal, runnable_id=design["id"])
        assert sent["ok"] is True
        payload = api.get_messages()
        agent_message = next(
            message
            for message in payload["messages"]
            if message["role"] == "assistant" and message["metadata"].get("sender", {}).get("nickname") == "Design"
        )

        assert agent_message["status"] == "completed"
        assert "任务：" in agent_message["content"]
        assert long_goal in agent_message["content"]
        assert "long-goal-tail-marker-917263" in agent_message["content"]
        assert "任务：请做一个很长的移动端验收方案" in agent_message["content"]
        assert "..." not in agent_message["content"].split("长目标验收方案已经整理完成。", 1)[0]
        assert agent_message["metadata"]["agent_report"] == "长目标验收方案已经整理完成。"
        assert agent_message["metadata"]["group_agent_summary_pending"] is True
        summary_message = next(
            message
            for message in payload["messages"]
            if message["role"] == "assistant"
            and message["metadata"].get("group_direct_agent_summary_for_message_id") == agent_message["id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert long_goal in summary_task.description
    finally:
        store.close()


def test_group_agent_approval_processing_clears_approval_card(tmp_path, monkeypatch):
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
                self.run = {
                    **self.run,
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "approval_id": "approval_first",
                        "tool": "terminal.run",
                        "input_preview": {"command": "python3 first.py"},
                    },
                }
                on_complete(self.run)
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
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"运行审批后进度"}',
        )

        approval_message = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant" and message["metadata"].get("sender", {}).get("nickname") == "Design"
        ][0]
        assert approval_message["metadata"]["run_status"] == "approval_required"

        service.run = {
            **service.run,
            "status": "processing",
            "result": "",
            "pending_approval": {},
        }
        processing_message = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant" and message["metadata"].get("sender", {}).get("nickname") == "Design"
        ][0]

        assert processing_message["id"] == approval_message["id"]
        assert processing_message["status"] == "processing"
        assert processing_message["content"] == ""
        assert processing_message["metadata"]["run_status"] == "processing"
        assert processing_message["metadata"]["pending_approval"] == {}
        assert processing_message["metadata"]["run_progress_title"] == "已批准工具调用"
        assert "正在继续执行当前任务" in processing_message["metadata"]["run_progress_detail"]
    finally:
        store.close()


def test_group_agent_approval_rejection_creates_main_summary(tmp_path, monkeypatch):
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
                self.run = {
                    **self.run,
                    "status": "approval_required",
                    "result": "等待审批：workspace.write_patch",
                    "pending_approval": {
                        "approval_id": "approval_write",
                        "tool": "workspace.write_patch",
                        "input_preview": {"path": "src/demo.py"},
                    },
                }
                on_complete(self.run)
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
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"写一个小组件"}',
        )

        approval_message = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant" and message["metadata"].get("sender", {}).get("nickname") == "Design"
        ][0]
        assert approval_message["metadata"]["run_status"] == "approval_required"

        service.run = {
            **service.run,
            "status": "cancelled",
            "result": "工具审批已拒绝：Rejected from chat",
            "pending_approval": {},
        }
        payload = api.get_messages()

        assistant_messages = [message for message in payload["messages"] if message["role"] == "assistant"]
        agent_message = next(
            message
            for message in assistant_messages
            if message["metadata"].get("sender", {}).get("nickname") == "Design"
        )
        assert agent_message["status"] == "failed"
        assert agent_message["content"] == (
            "Design 已取消，已把当前状态交给主模型整理。\n"
            "任务：写一个小组件\n\n"
            "工具审批已拒绝：Rejected from chat"
        )
        assert agent_message["error"] == agent_message["content"]
        assert agent_message["metadata"]["agent_report_status"] == "cancelled"
        assert agent_message["metadata"]["agent_report"] == "工具审批已拒绝：Rejected from chat"
        summary_message = next(
            message
            for message in assistant_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        assert summary_message["status"] == "processing"
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "Design：已取消" in summary_task.description
        assert "汇报：工具审批已拒绝：Rejected from chat" in summary_task.description
    finally:
        store.close()


def test_group_agent_approval_waits_for_all_delegates_before_summary(tmp_path, monkeypatch):
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
        "nickname": "Coding",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def __init__(self):
            self.runs = {
                "agent_run_design": {
                    "run_id": "agent_run_design",
                    "run_group_id": "run_group_dispatch",
                    "status": "completed",
                    "result": "设计稿已经完成。",
                    "runnable": design,
                },
                "agent_run_coding": {
                    "run_id": "agent_run_coding",
                    "run_group_id": "run_group_dispatch",
                    "status": "approval_required",
                    "result": "等待审批：workspace.write_patch",
                    "pending_approval": {
                        "approval_id": "approval_coding",
                        "tool": "workspace.write_patch",
                        "input_preview": {"file": "scripts/demo.py"},
                    },
                    "runnable": coding,
                },
            }

        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (design, coding):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            run_id = "agent_run_design" if runnable_id == design["id"] else "agent_run_coding"
            run = {
                **self.runs[run_id],
                "run_group_id": run_group_id or self.runs[run_id]["run_group_id"],
            }
            self.runs[run_id] = run
            if on_complete:
                on_complete(run)
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 安排一下")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                '{"action":"dispatch_group_agent","agent":"Design","goal":"画月牙图标"}\n'
                '{"action":"dispatch_group_agent","agent":"Coding","goal":"写字符计数"}'
            ),
        )

        waiting_payload = api.get_messages()
        waiting_messages = [message for message in waiting_payload["messages"] if message["role"] == "assistant"]
        delegated = {
            message["metadata"].get("sender", {}).get("nickname"): message
            for message in waiting_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        }
        assert delegated["Design"]["status"] == "completed"
        assert delegated["Design"]["content"] == "Design 已完成，并把结果交给主模型汇总。\n任务：画月牙图标\n\n设计稿已经完成。"
        assert delegated["Coding"]["status"] == "processing"
        assert delegated["Coding"]["metadata"]["run_status"] == "approval_required"
        assert not any(message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"] for message in waiting_messages)

        service.runs["agent_run_coding"] = {
            **service.runs["agent_run_coding"],
            "status": "completed",
            "result": "字符计数脚本已经完成。",
            "pending_approval": {},
        }
        completed_payload = api.get_messages()
        completed_messages = [message for message in completed_payload["messages"] if message["role"] == "assistant"]
        summary_message = next(
            message
            for message in completed_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        assert summary_message["status"] == "processing"
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "汇报：设计稿已经完成。" in summary_task.description
        assert "汇报：字符计数脚本已经完成。" in summary_task.description
    finally:
        store.close()


def test_group_multiple_agent_approvals_wait_until_every_delegate_terminal(tmp_path, monkeypatch):
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
        "nickname": "Coding",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def __init__(self):
            self.runs = {
                "agent_run_design": {
                    "run_id": "agent_run_design",
                    "run_group_id": "run_group_dispatch",
                    "status": "approval_required",
                    "result": "等待审批：artifact.write",
                    "pending_approval": {
                        "approval_id": "approval_design",
                        "tool": "artifact.write",
                        "input_preview": {"path": "design.md"},
                    },
                    "timeline": [
                        {
                            "event": "agent.tool.call",
                            "detail": "artifact.write",
                            "input_preview": {"path": "design.md"},
                            "result": {"ok": True, "path": "design.md"},
                        }
                    ],
                    "runnable": design,
                },
                "agent_run_coding": {
                    "run_id": "agent_run_coding",
                    "run_group_id": "run_group_dispatch",
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "approval_id": "approval_coding",
                        "tool": "terminal.run",
                        "input_preview": {"command": "python3 verify.py"},
                    },
                    "timeline": [
                        {
                            "event": "agent.tool.call",
                            "detail": "terminal.run",
                            "input_preview": {"command": "python3 verify.py"},
                            "result": {"ok": False, "exit_code": 1, "stderr": "Missing dependency"},
                        }
                    ],
                    "runnable": coding,
                },
            }

        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (design, coding):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            run_id = "agent_run_design" if runnable_id == design["id"] else "agent_run_coding"
            run = {
                **self.runs[run_id],
                "run_group_id": run_group_id or self.runs[run_id]["run_group_id"],
            }
            self.runs[run_id] = run
            if on_complete:
                on_complete(run)
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True
        sent = api.send_message("@主模型 安排一下")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                '{"action":"dispatch_group_agent","agent":"Design","goal":"整理 UI 验收点"}\n'
                '{"action":"dispatch_group_agent","agent":"Coding","goal":"运行验证脚本"}'
            ),
        )

        waiting_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        delegated = {
            message["metadata"].get("sender", {}).get("nickname"): message
            for message in waiting_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        }
        assert delegated["Design"]["metadata"]["run_status"] == "approval_required"
        assert delegated["Coding"]["metadata"]["run_status"] == "approval_required"
        assert not any(message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"] for message in waiting_messages)

        service.runs["agent_run_design"] = {
            **service.runs["agent_run_design"],
            "status": "completed",
            "result": "UI 验收点已经整理完成。",
            "pending_approval": {},
        }
        partial_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        delegated_after_one = {
            message["metadata"].get("sender", {}).get("nickname"): message
            for message in partial_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        }
        assert delegated_after_one["Design"]["status"] == "completed"
        assert delegated_after_one["Coding"]["metadata"]["run_status"] == "approval_required"
        assert not any(message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"] for message in partial_messages)

        followup = api.send_message("补充：最终整理时请把失败项和可验收项分开说")
        assert followup["ok"] is True
        followup_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == followup["message_id"]
        )
        assert followup_message["metadata"]["group_followup_for_task_ids"] == [sent["task_id"]]
        runtime.state.update_task_status(
            followup["task_id"],
            TaskStatus.COMPLETED,
            result="收到补充。",
        )
        natural_followup = api.send_message("@主模型 把验收说明改成按成功、失败、待确认三段输出")
        assert natural_followup["ok"] is True
        natural_followup_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == natural_followup["message_id"]
        )
        assert natural_followup_message["metadata"]["group_followup_for_task_ids"] == [sent["task_id"]]
        runtime.state.update_task_status(
            natural_followup["task_id"],
            TaskStatus.COMPLETED,
            result="收到自然补充。",
        )
        separate_goal = api.send_message("@主模型 另一个目标：再开一个按钮动效方案")
        assert separate_goal["ok"] is True
        runtime.state.update_task_status(
            separate_goal["task_id"],
            TaskStatus.COMPLETED,
            result="另一个目标单独处理。",
        )
        new_main_request = api.send_message("@主模型 安排第二轮测试目标")
        assert new_main_request["ok"] is True
        new_main_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == new_main_request["message_id"]
        )
        assert "group_followup_for_task_ids" not in new_main_message["metadata"]
        runtime.state.update_task_status(
            new_main_request["task_id"],
            TaskStatus.COMPLETED,
            result="第二轮目标单独处理。",
        )

        service.runs["agent_run_coding"] = {
            **service.runs["agent_run_coding"],
            "status": "failed",
            "result": "验证脚本失败：缺少依赖。",
            "pending_approval": {},
        }
        final_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        final_delegated = {
            message["metadata"].get("sender", {}).get("nickname"): message
            for message in final_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        }
        assert final_delegated["Design"]["metadata"]["agent_report_status"] == "completed"
        assert final_delegated["Coding"]["metadata"]["agent_report_status"] == "failed"
        summary_message = next(
            message
            for message in final_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "回复必须明确区分：成功项、失败/取消/拒绝项、失败原因、未执行派活、可验收内容/产物、用户下一步可选动作。" in summary_task.description
        assert "如果有的 Agent 成功、有的 Agent 失败或被拒绝，不要把整轮任务说成单纯成功或单纯失败" in summary_task.description
        assert "用户后续补充/纠偏：" in summary_task.description
        assert "- 补充：最终整理时请把失败项和可验收项分开说" in summary_task.description
        assert "- @主模型 把验收说明改成按成功、失败、待确认三段输出" in summary_task.description
        assert "另一个目标：再开一个按钮动效方案" not in summary_task.description
        assert "安排第二轮测试目标" not in summary_task.description
        assert "Design：已完成" in summary_task.description
        assert "汇报：UI 验收点已经整理完成。" in summary_task.description
        assert "Coding：执行失败" in summary_task.description
        assert "汇报：验证脚本失败：缺少依赖。" in summary_task.description
        assert "执行线索：" in summary_task.description
        assert "terminal.run" in summary_task.description
        assert "python3 verify.py" in summary_task.description
        assert "Missing dependency" in summary_task.description

        runtime.state.update_task_status(
            summary_message["task_id"],
            TaskStatus.COMPLETED,
            result="最终汇总：Design 完成；Coding 失败，原因是缺少依赖。",
        )
        settled_payload = api.get_messages()
        settled_parent = next(
            message
            for message in settled_payload["messages"]
            if message["role"] == "assistant" and message.get("task_id") == sent["task_id"]
        )
        settled_summary = next(
            message
            for message in settled_payload["messages"]
            if message["role"] == "assistant" and message.get("task_id") == summary_message["task_id"]
        )
        assert settled_summary["status"] == "completed"
        assert settled_summary["content"] == "最终汇总：Design 完成；Coding 失败，原因是缺少依赖。"
        assert "group_agent_summary_pending" not in settled_parent["metadata"]
        assert settled_parent["metadata"]["group_agent_summary_status"] == "completed"
        assert settled_payload["approval_count"] == 0
        assert settled_payload["processing_count"] == 0
        assert settled_payload["is_processing"] is False
    finally:
        store.close()


def test_group_followup_targets_latest_active_delegated_batch(tmp_path, monkeypatch):
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
        "nickname": "Coding",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def __init__(self):
            self.runs = {
                "agent_run_design": {
                    "run_id": "agent_run_design",
                    "run_group_id": "run_group_first",
                    "status": "approval_required",
                    "result": "等待审批：artifact.write",
                    "pending_approval": {
                        "approval_id": "approval_design",
                        "tool": "artifact.write",
                        "input_preview": {"path": "design.md"},
                    },
                    "runnable": design,
                },
                "agent_run_coding": {
                    "run_id": "agent_run_coding",
                    "run_group_id": "run_group_second",
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "approval_id": "approval_coding",
                        "tool": "terminal.run",
                        "input_preview": {"command": "python3 verify.py"},
                    },
                    "runnable": coding,
                },
            }

        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (design, coding):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            run_id = "agent_run_design" if runnable_id == design["id"] else "agent_run_coding"
            run = {
                **self.runs[run_id],
                "run_group_id": run_group_id or self.runs[run_id]["run_group_id"],
            }
            self.runs[run_id] = run
            if on_complete:
                on_complete(run)
            return run

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True

        first = api.send_message("@主模型 安排第一批设计任务")
        assert first["ok"] is True
        runtime.state.update_task_status(
            first["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"做图标方案"}',
        )
        assert not any(
            message["metadata"].get("group_agent_summary_for_task_id") == first["task_id"]
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        )

        second = api.send_message("@主模型 安排第二批代码任务")
        assert second["ok"] is True
        second_user_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == second["message_id"]
        )
        assert "group_followup_for_task_ids" not in second_user_message["metadata"]
        runtime.state.update_task_status(
            second["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Coding","goal":"写验证脚本"}',
        )

        followup = api.send_message("补充：这条只给第二批汇总")
        assert followup["ok"] is True
        followup_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == followup["message_id"]
        )
        assert followup_message["metadata"]["group_followup_for_task_ids"] == [second["task_id"]]
        runtime.state.update_task_status(
            followup["task_id"],
            TaskStatus.COMPLETED,
            result="收到补充。",
        )

        service.runs["agent_run_design"] = {
            **service.runs["agent_run_design"],
            "status": "completed",
            "result": "图标方案完成。",
            "pending_approval": {},
        }
        first_done_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        first_summary = next(
            message
            for message in first_done_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == first["task_id"]
        )
        first_summary_task = runtime.state.get_task(first_summary["task_id"])
        assert first_summary_task is not None
        assert "图标方案完成。" in first_summary_task.description
        assert "这条只给第二批汇总" not in first_summary_task.description

        service.runs["agent_run_coding"] = {
            **service.runs["agent_run_coding"],
            "status": "completed",
            "result": "验证脚本完成。",
            "pending_approval": {},
        }
        final_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        second_summary = next(
            message
            for message in final_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == second["task_id"]
        )
        second_summary_task = runtime.state.get_task(second_summary["task_id"])
        assert second_summary_task is not None
        assert "- 补充：这条只给第二批汇总" in second_summary_task.description
        assert "验证脚本完成。" in second_summary_task.description
    finally:
        store.close()


def test_group_followup_after_unsynced_completed_dispatch_enters_summary(tmp_path, monkeypatch):
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
        "nickname": "Coding",
        "kind": "agent",
        "enabled": True,
    }

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            for agent in (design, coding):
                if runnable_id == agent["id"] or clean_name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            runnable = self.resolve_runnable(runnable_id=runnable_id, name=name) or {}
            if runnable_id == design["id"]:
                run = {
                    "run_id": "agent_run_design",
                    "run_group_id": run_group_id or "run_group_first",
                    "status": "approval_required",
                    "result": "等待审批：artifact.write",
                    "pending_approval": {
                        "approval_id": "approval_design",
                        "tool": "artifact.write",
                        "input_preview": {"path": "design.md"},
                    },
                    "runnable": runnable,
                }
            else:
                run = {
                    "run_id": "agent_run_coding",
                    "run_group_id": run_group_id or "run_group_second",
                    "status": "completed",
                    "result": "验证脚本完成。",
                    "pending_approval": {},
                    "runnable": runnable,
                }
            if on_complete:
                on_complete(run)
            return run

        def get_run(self, run_id):
            if run_id == "agent_run_design":
                return {
                    "run_id": "agent_run_design",
                    "run_group_id": "run_group_first",
                    "status": "approval_required",
                    "result": "等待审批：artifact.write",
                    "pending_approval": {
                        "approval_id": "approval_design",
                        "tool": "artifact.write",
                        "input_preview": {"path": "design.md"},
                    },
                    "runnable": design,
                }
            return {
                "run_id": "agent_run_coding",
                "run_group_id": "run_group_second",
                "status": "completed",
                "result": "验证脚本完成。",
                "pending_approval": {},
                "runnable": coding,
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"], coding["id"]])
        assert created["ok"] is True

        first = api.send_message("@主模型 安排第一批设计任务")
        assert first["ok"] is True
        runtime.state.update_task_status(
            first["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Design","goal":"做图标方案"}',
        )
        api.get_messages()

        second = api.send_message("@主模型 安排第二批代码任务")
        assert second["ok"] is True
        runtime.state.update_task_status(
            second["task_id"],
            TaskStatus.COMPLETED,
            result='{"action":"dispatch_group_agent","agent":"Coding","goal":"写验证脚本"}',
        )

        followup = api.send_message("补充：第二批汇总时请说明怎么验收")
        assert followup["ok"] is True
        messages = api.get_messages()["messages"]
        followup_message = next(message for message in messages if message["id"] == followup["message_id"])
        assert followup_message["metadata"]["group_followup_for_task_ids"] == [second["task_id"]]

        assert not any(
            message["metadata"].get("group_agent_summary_for_task_id") == first["task_id"]
            for message in messages
            if message["role"] == "assistant"
        )
        second_summary = next(
            message
            for message in messages
            if message["metadata"].get("group_agent_summary_for_task_id") == second["task_id"]
        )
        summary_task = runtime.state.get_task(second_summary["task_id"])
        assert summary_task is not None
        assert "验证脚本完成。" in summary_task.description
        assert "- 补充：第二批汇总时请说明怎么验收" in summary_task.description
    finally:
        store.close()


def test_group_followup_dispatch_payload_is_ignored_and_stays_in_current_summary(tmp_path, monkeypatch):
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
            self.created_goals: list[str] = []
            self.run = {
                "run_id": "agent_run_design_followup_ignore",
                "run_group_id": "run_group_followup_ignore",
                "status": "processing",
                "result": "",
                "pending_approval": {},
                "runnable": design,
            }

        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            if runnable_id == design["id"] or clean_name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            self.created_goals.append(user_goal)
            self.run = {
                **self.run,
                "run_group_id": run_group_id or self.run["run_group_id"],
            }
            return self.run

        def get_run(self, run_id):
            assert run_id == "agent_run_design_followup_ignore"
            return self.run

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        sent = api.send_message("请让群里合适的 Agent 做移动端验收方案")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我会交给 Design 做移动端验收方案。\n"
                "<oha_group_dispatch>\n"
                '{"action":"dispatch_group_agent","agent":"Design","goal":"整理移动端验收方案"}\n'
                "</oha_group_dispatch>"
            ),
        )
        api.get_messages()
        assert service.created_goals == ["整理移动端验收方案"]

        followup = api.send_message("补充：最终整理时请强调不要暴露 JSON")
        assert followup["ok"] is True
        followup_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == followup["message_id"]
        )
        assert followup_message["metadata"]["group_followup_for_task_ids"] == [sent["task_id"]]
        followup_task = runtime.state.get_task(followup["task_id"])
        assert followup_task is not None
        assert "[Oha-Yachiyo 群组补充/纠偏]" in followup_task.description
        runtime.state.update_task_status(
            followup["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "明白，我把补充重新派给 Design。\n"
                "<oha_group_dispatch>\n"
                '{"action":"dispatch_group_agent","agent":"Design","goal":"补充不要暴露 JSON"}\n'
                "</oha_group_dispatch>"
            ),
        )
        followup_payload = api.get_messages()
        followup_assistant = next(
            message
            for message in followup_payload["messages"]
            if message["role"] == "assistant" and message.get("task_id") == followup["task_id"]
        )
        assert service.created_goals == ["整理移动端验收方案"]
        assert followup_assistant["content"] == ChatAPI._group_followup_ack_content()
        assert followup_assistant["metadata"]["group_followup_dispatch_ignored"] is True
        assert followup_assistant["metadata"]["group_dispatch_count"] == 0
        assert not any(
            message["metadata"].get("delegated_by_task_id") == followup["task_id"]
            for message in followup_payload["messages"]
            if message["role"] == "assistant"
        )

        service.run = {
            **service.run,
            "status": "completed",
            "result": "移动端验收方案已经完成。",
            "pending_approval": {},
        }
        final_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        summary_message = next(
            message
            for message in final_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "- 补充：最终整理时请强调不要暴露 JSON" in summary_task.description
        assert "补充不要暴露 JSON" not in summary_task.description
    finally:
        store.close()


def test_plain_group_followup_during_running_agent_enters_main_summary(tmp_path, monkeypatch):
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
                "run_id": "agent_run_design_followup",
                "run_group_id": "run_group_plain_followup",
                "status": "processing",
                "result": "",
                "pending_approval": {},
                "runnable": design,
            }

        def resolve_runnable(self, *, runnable_id="", name=""):
            clean_name = str(name or "").lstrip("@")
            if runnable_id == design["id"] or clean_name in {design["name"], design["nickname"]}:
                return design
            return None

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            self.run = {
                **self.run,
                "run_group_id": run_group_id or self.run["run_group_id"],
            }
            return self.run

        def get_run(self, run_id):
            assert run_id == "agent_run_design_followup"
            return self.run

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(name="demo Channel", participant_ids=[design["id"]])
        assert created["ok"] is True

        sent = api.send_message("请让群里合适的 Agent 做移动端验收方案")
        assert sent["ok"] is True
        runtime.state.update_task_status(
            sent["task_id"],
            TaskStatus.COMPLETED,
            result=(
                "我会交给 Design 做移动端验收方案。\n"
                "<oha_group_dispatch>\n"
                '{"action":"dispatch_group_agent","agent":"Design","goal":"整理移动端验收方案"}\n'
                "</oha_group_dispatch>"
            ),
        )
        running_payload = api.get_messages()
        running_messages = [message for message in running_payload["messages"] if message["role"] == "assistant"]
        agent_message = next(
            message
            for message in running_messages
            if message["metadata"].get("delegated_by_task_id") == sent["task_id"]
        )
        assert agent_message["metadata"]["run_status"] == "processing"
        assert not any(
            message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
            for message in running_messages
        )

        followup = api.send_message("补充：最终整理时请优先列出移动端验收风险")
        assert followup["ok"] is True
        followup_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == followup["message_id"]
        )
        assert followup_message["metadata"]["group_followup_for_task_ids"] == [sent["task_id"]]
        runtime.state.update_task_status(
            followup["task_id"],
            TaskStatus.COMPLETED,
            result="收到补充。",
        )

        separate_goal = api.send_message("@主模型 另一个目标：再做桌面端验收方案")
        assert separate_goal["ok"] is True
        separate_message = next(
            message
            for message in api.get_messages()["messages"]
            if message["id"] == separate_goal["message_id"]
        )
        assert "group_followup_for_task_ids" not in separate_message["metadata"]
        runtime.state.update_task_status(
            separate_goal["task_id"],
            TaskStatus.COMPLETED,
            result="桌面端目标单独处理。",
        )

        service.run = {
            **service.run,
            "status": "completed",
            "result": "移动端验收方案已经完成。",
            "pending_approval": {},
        }
        final_messages = [
            message
            for message in api.get_messages()["messages"]
            if message["role"] == "assistant"
        ]
        summary_message = next(
            message
            for message in final_messages
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = runtime.state.get_task(summary_message["task_id"])
        assert summary_task is not None
        assert "用户原始请求：请让群里合适的 Agent 做移动端验收方案" in summary_task.description
        assert "用户后续补充/纠偏：" in summary_task.description
        assert "- 补充：最终整理时请优先列出移动端验收风险" in summary_task.description
        assert "另一个目标：再做桌面端验收方案" not in summary_task.description
        assert "Design：已完成" in summary_task.description
        assert "任务：整理移动端验收方案" in summary_task.description
        assert "汇报：移动端验收方案已经完成。" in summary_task.description
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
            "任务：做测试\n\n"
            "furina retry done"
        )
        assert furina_messages[-1]["metadata"]["agent_report"] == "furina retry done"
        assert furina_messages[-1]["status"] == "completed"
    finally:
        store.close()


def test_manual_group_workflow_mention_runs_workflow_and_stays_in_group(tmp_path, monkeypatch):
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
        def __init__(self):
            self.runs: dict[str, dict] = {}

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

        def create_run_for_runnable_async(self, *, runnable_id="", name="", user_goal="", run_group_id="", upstream="", on_complete=None):
            assert runnable_id == workflow["id"]
            run = {
                "run_id": "workflow_run_web",
                "run_group_id": run_group_id or "run_group_web",
                "kind": "workflow_run",
                "runnable_id": workflow["id"],
                "runnable_name": workflow["name"],
                "status": "completed",
                "result": "Web Flow done",
                "timeline": [
                    {"event": "workflow.run.started", "detail": workflow["name"]},
                    {"event": "workflow.run.completed", "detail": workflow["name"]},
                ],
                "runnable": workflow,
            }
            self.runs[run["run_id"]] = run
            if on_complete:
                on_complete(run)
            return {**run, "status": "processing"}

        def get_run(self, run_id):
            return self.runs[run_id]

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        created = api.create_group_session(
            name="demo Channel",
            participant_ids=[design["id"]],
        )
        assert created["ok"] is True
        result = api.send_message("@Web Flow 做一个网页链路")
        assert result["ok"] is True
        assert result["runnable_command"] is True
        assert result["status"] == "processing"
        assert result["workflow_run_id"] == "workflow_run_web"

        current = next(item for item in api.list_sessions()["sessions"] if item["session_id"] == runtime.chat_session.session_id)
        assert current["conversation_kind"] == "group"
        assert current["runnable_id"] == ""
        assert current["runnable_name"] == "demo Channel"
        participant_names = [item["name"] for item in current["participants"]]
        assert "Design Agent" in participant_names
        assert "Web Flow" not in participant_names
        messages = api.get_messages()["messages"]
        assistant_messages = [message for message in messages if message["role"] == "assistant"]
        assert assistant_messages[-1]["metadata"]["runnable_kind"] == "workflow"
        assert assistant_messages[-1]["metadata"]["workflow_run_id"] == "workflow_run_web"
        assert "Web Flow" in assistant_messages[-1]["content"]
    finally:
        store.close()


def test_agent_mention_supports_multiword_names(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
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
    service = _make_agent_runtime_service(tmp_path)
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
            metadata={"run_id": "agent_run_activity", "run_status": "processing"},
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
        assert assistant["activity_events"][0]["metadata"]["run_id"] == "agent_run_activity"
        assert assistant["activity_events"][0]["metadata"]["run_status"] == "processing"

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


def test_summarize_delegated_run_creates_main_followup_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)

    run = {
        "run_id": "agent_run_delegated",
        "run_group_id": "run_group_delegated",
        "kind": "agent_run",
        "runnable_id": "agent_coding",
        "runnable_name": "Coding Agent",
        "status": "completed",
        "user_goal": "写一个 CLI 工具",
        "result": "CLI 工具已经完成。",
        "timeline": [
            {
                "event": "agent.tool.call",
                "detail": "artifact.write",
                "input_preview": {"path": "scripts/tool.py"},
                "result": {"ok": True, "path": "scripts/tool.py"},
            }
        ],
        "artifacts": [
            {"path": "scripts/tool.py", "kind": "code"},
            {"path": "agent-context.md", "kind": "context"},
        ],
    }

    class FakeAgentRuntimeService:
        def get_run(self, run_id: str):
            assert run_id == "agent_run_delegated"
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeAgentRuntimeService())

    try:
        sent = api.send_message("帮我派一个 Agent 写脚本")
        task_id = sent["task_id"]
        runtime.chat_session.upsert_assistant_message(
            task_id=task_id,
            content=(
                "我会交给 Coding Agent 处理。\n"
                '<oha_delegation>{"action":"run_oha_agent","agent":"Coding Agent","goal":"写一个 CLI 工具"}</oha_delegation>'
            ),
            status=MessageStatus.COMPLETED,
        )
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="oha.delegation",
            phase="subagent",
            title="Coding Agent 等待审批",
            detail="Status: approval_required",
            status="approval_required",
            metadata={
                "run_id": "agent_run_delegated",
                "run_group_id": "run_group_delegated",
                "run_status": "approval_required",
                "pending_approval": {"tool": "terminal.run"},
            },
        )

        result = api.summarize_delegated_run("agent_run_delegated")
        repeat = api.summarize_delegated_run("agent_run_delegated")
        summary_message = next(
            message for message in runtime.chat_session.get_all_messages()
            if message.metadata.get("delegated_run_summary_for_run_id") == "agent_run_delegated"
        )
        summary_task = runtime.state.get_task(result["task_id"])

        assert result["ok"] is True
        assert result["summary_created"] is True
        assert result["message_id"] == summary_message.message_id
        assert result["run_group_id"] == "run_group_delegated"
        assert result["run_status"] == "completed"
        assert result["source_task_id"] == task_id
        assert repeat["summary_created"] is False
        assert repeat["message_id"] == summary_message.message_id
        assert repeat["task_id"] == result["task_id"]
        assert repeat["run_group_id"] == "run_group_delegated"
        assert repeat["run_status"] == "completed"
        assert repeat["source_task_id"] == task_id
        assert summary_message.status == MessageStatus.PROCESSING
        assert summary_message.metadata["sender"]["kind"] == "main"
        assert summary_message.metadata["delegated_run_source_task_id"] == task_id
        assert summary_task is not None
        assert "[Oha-Yachiyo 自动委派 Run 汇总]" in summary_task.description
        assert "用户原始请求：帮我派一个 Agent 写脚本" in summary_task.description
        assert "我会交给 Coding Agent 处理。" in summary_task.description
        assert "run_oha_agent" not in summary_task.description
        assert "Coding Agent：已完成" in summary_task.description
        assert "任务：写一个 CLI 工具" in summary_task.description
        assert "汇报：CLI 工具已经完成。" in summary_task.description
        assert "执行线索：" in summary_task.description
        assert "artifact.write" in summary_task.description
        assert "scripts/tool.py" in summary_task.description
        assert "产物：scripts/tool.py (code)" in summary_task.description
    finally:
        activity_store.close()
        store.close()


def test_summarize_delegated_run_uses_native_run_projection(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    native_service = _make_agent_runtime_service(tmp_path)
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: native_service)

    try:
        run_group = native_service._insert_run_group(
            title="Native delegated summary",
            source="delegation",
        )
        run = native_service._insert_run(
            kind="agent_run",
            runnable_id="agent_native_coding",
            user_goal="整理 NativeRunEngine evidence",
            run_group_id=run_group["run_group_id"],
        )
        native_service._update_run(
            run["run_id"],
            status="completed",
            result="NativeRunEngine delegation finished.",
            timeline=[
                {
                    "event": "agent.tool.call",
                    "detail": "artifact.write",
                    "input_preview": {"path": "reports/native-summary.md"},
                    "result": {"ok": True, "path": "reports/native-summary.md"},
                },
                {
                    "event": "agent.run.completed",
                    "detail": "done",
                    "result": "NativeRunEngine delegation finished.",
                },
            ],
            artifacts=[
                {"path": "agent-context.md", "kind": "context"},
                {"path": "reports/native-summary.md", "kind": "report"},
            ],
        )

        sent = api.send_message("请自动委派一个 Agent 整理 evidence")
        task_id = sent["task_id"]
        runtime.chat_session.upsert_assistant_message(
            task_id=task_id,
            content=(
                "我会交给 Native Coding Agent 处理。\n"
                '<oha_delegation>{"action":"run_oha_agent","agent":"Native Coding Agent","goal":"整理 evidence"}</oha_delegation>'
            ),
            status=MessageStatus.COMPLETED,
        )
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="oha.delegation",
            phase="subagent",
            title="Native Coding Agent completed",
            detail=f"run_id={run['run_id']}",
            status="completed",
            metadata={
                "run_id": run["run_id"],
                "run_group_id": run_group["run_group_id"],
                "run_status": "completed",
            },
        )

        result = api.summarize_delegated_run(run["run_id"])
        summary_message = next(
            message for message in runtime.chat_session.get_all_messages()
            if message.metadata.get("delegated_run_summary_for_run_id") == run["run_id"]
        )
        summary_task = runtime.state.get_task(result["task_id"])

        assert result["ok"] is True
        assert result["summary_created"] is True
        assert result["run_id"] == run["run_id"]
        assert result["run_group_id"] == run_group["run_group_id"]
        assert result["run_status"] == "completed"
        assert result["source_task_id"] == task_id
        assert summary_message.metadata["run_id"] == run["run_id"]
        assert summary_message.metadata["run_group_id"] == run_group["run_group_id"]
        assert summary_message.metadata["delegated_run_source_task_id"] == task_id
        assert summary_task is not None
        assert "[Oha-Yachiyo 自动委派 Run 汇总]" in summary_task.description
        assert "用户原始请求：请自动委派一个 Agent 整理 evidence" in summary_task.description
        assert "run_oha_agent" not in summary_task.description
        assert "agent_native_coding：已完成" in summary_task.description
        assert "任务：整理 NativeRunEngine evidence" in summary_task.description
        assert "汇报：NativeRunEngine delegation finished." in summary_task.description
        assert "执行线索：" in summary_task.description
        assert "artifact.write" in summary_task.description
        assert "reports/native-summary.md" in summary_task.description
        assert "产物：reports/native-summary.md (report)" in summary_task.description
        assert "agent-context.md" not in summary_task.description
    finally:
        native_service.close()
        activity_store.close()
        store.close()


def test_summarize_delegated_run_concurrent_calls_create_one_followup(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)

    run = {
        "run_id": "agent_run_concurrent_summary",
        "run_group_id": "run_group_concurrent_summary",
        "kind": "agent_run",
        "runnable_id": "agent_concurrent",
        "runnable_name": "Concurrent Agent",
        "status": "completed",
        "user_goal": "整理并发 summary evidence",
        "result": "Concurrent delegated run completed.",
        "timeline": [],
        "artifacts": [],
    }

    class FakeAgentRuntimeService:
        def get_run(self, run_id: str):
            assert run_id == run["run_id"]
            return run

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeAgentRuntimeService())
    original_create_task = runtime.state.create_task
    release_create_task: threading.Event | None = None

    try:
        sent = api.send_message("请自动委派一个 Agent 做并发 summary 验证")
        runtime.chat_session.upsert_assistant_message(
            task_id=sent["task_id"],
            content="我会交给 Concurrent Agent 处理。",
            status=MessageStatus.COMPLETED,
        )
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=sent["task_id"],
            tool_name="oha.delegation",
            phase="subagent",
            title="Concurrent Agent completed",
            detail=f"run_id={run['run_id']}",
            status="completed",
            metadata={
                "run_id": run["run_id"],
                "run_group_id": run["run_group_id"],
                "run_status": "completed",
            },
        )

        create_task_entered = threading.Event()
        release_create_task = threading.Event()
        create_task_calls = 0
        create_task_calls_lock = threading.Lock()

        def slow_create_task(*args, **kwargs):
            nonlocal create_task_calls
            with create_task_calls_lock:
                create_task_calls += 1
                call_index = create_task_calls
            if call_index == 1:
                create_task_entered.set()
                assert release_create_task.wait(timeout=2)
            return original_create_task(*args, **kwargs)

        runtime.state.create_task = slow_create_task

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(api.summarize_delegated_run, run["run_id"])
            assert create_task_entered.wait(timeout=2)
            second = pool.submit(api.summarize_delegated_run, run["run_id"])
            release_create_task.set()
            results = [first.result(timeout=2), second.result(timeout=2)]

        created = [result for result in results if result.get("summary_created") is True]
        reused = [result for result in results if result.get("summary_created") is False]
        summary_messages = [
            message for message in runtime.chat_session.get_all_messages()
            if message.metadata.get("delegated_run_summary_for_run_id") == run["run_id"]
        ]

        assert len(created) == 1
        assert len(reused) == 1
        assert reused[0]["reason"] == "already_exists"
        assert reused[0]["task_id"] == created[0]["task_id"]
        assert reused[0]["run_group_id"] == run["run_group_id"]
        assert reused[0]["run_status"] == "completed"
        assert reused[0]["source_task_id"] == sent["task_id"]
        assert create_task_calls == 1
        assert len(summary_messages) == 1
        assert reused[0]["message_id"] == summary_messages[0].message_id
        assert len(runtime.state.list_tasks()) == 2
        assert runtime.state.get_task(created[0]["task_id"]) is not None
    finally:
        runtime.state.create_task = original_create_task
        if release_create_task is not None:
            release_create_task.set()
        activity_store.close()
        store.close()


def test_summarize_delegated_run_uses_runtime_injected_activity_store(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    runtime.activity_store = activity_store

    run = {
        "run_id": "agent_run_injected_activity",
        "run_group_id": "run_group_injected_activity",
        "kind": "agent_run",
        "runnable_id": "agent_injected",
        "runnable_name": "Injected Agent",
        "status": "completed",
        "user_goal": "整理 runtime-injected activity evidence",
        "result": "Injected activity store was used.",
        "timeline": [],
        "artifacts": [],
    }

    class FakeAgentRuntimeService:
        def get_run(self, run_id: str):
            assert run_id == run["run_id"]
            return run

    runtime.agent_runtime_service = FakeAgentRuntimeService()

    try:
        sent = api.send_message("请自动委派一个 Agent 检查 activity store")
        task_id = sent["task_id"]
        runtime.chat_session.upsert_assistant_message(
            task_id=task_id,
            content="我会交给 Injected Agent 处理。",
            status=MessageStatus.COMPLETED,
        )
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="oha.delegation",
            phase="subagent",
            title="Injected Agent completed",
            detail=f"run_id={run['run_id']}",
            status="completed",
            metadata={
                "run_id": run["run_id"],
                "run_group_id": run["run_group_id"],
                "run_status": "completed",
            },
        )
        monkeypatch.setattr(
            chat_api_mod,
            "get_activity_store",
            lambda: (_ for _ in ()).throw(AssertionError("global activity store must not be used")),
        )
        monkeypatch.setattr(
            chat_api_mod,
            "get_agent_runtime_service",
            lambda: (_ for _ in ()).throw(AssertionError("global runtime service must not be used")),
        )

        result = api.summarize_delegated_run(run["run_id"])
        summary_task = runtime.state.get_task(result["task_id"])

        assert result["ok"] is True
        assert result["summary_created"] is True
        assert result["run_group_id"] == run["run_group_id"]
        assert result["source_task_id"] == task_id
        assert summary_task is not None
        assert "Injected Agent：已完成" in summary_task.description
        assert "Injected activity store was used." in summary_task.description
    finally:
        activity_store.close()
        store.close()


def test_summarize_delegated_run_waits_for_terminal_status(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)

    class FakeAgentRuntimeService:
        def get_run(self, _run_id: str):
            return {
                "run_id": "agent_run_waiting",
                "run_group_id": "run_group_waiting",
                "kind": "agent_run",
                "runnable_id": "agent_coding",
                "runnable_name": "Coding Agent",
                "status": "approval_required",
                "user_goal": "写一个 CLI 工具",
                "result": "",
                "artifacts": [],
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeAgentRuntimeService())

    try:
        sent = api.send_message("帮我派一个 Agent 写脚本")
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=sent["task_id"],
            tool_name="oha.delegation",
            phase="subagent",
            title="Coding Agent 等待审批",
            status="approval_required",
            metadata={"run_id": "agent_run_waiting", "run_status": "approval_required"},
        )

        result = api.summarize_delegated_run("agent_run_waiting")

        assert result["ok"] is True
        assert result["summary_created"] is False
        assert result["reason"] == "not_terminal"
        assert result["run_group_id"] == "run_group_waiting"
        assert result["run_status"] == "approval_required"
        assert not any(
            message.metadata.get("delegated_run_summary_for_run_id") == "agent_run_waiting"
            for message in runtime.chat_session.get_all_messages()
        )
    finally:
        activity_store.close()
        store.close()


def test_summarize_delegated_run_redacts_runtime_errors(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    leaked_secret = "sk-delegated-summary-secret123456"

    class FakeAgentRuntimeService:
        def get_run(self, run_id: str):
            assert run_id == "agent_run_secret"
            raise AgentRuntimeError(f"provider rejected api_key={leaked_secret}")

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeAgentRuntimeService())

    try:
        result = api.summarize_delegated_run("agent_run_secret")

        assert result["ok"] is False
        assert leaked_secret not in result["error"]
        assert "api_key=[redacted]" in result["error"]
        assert not any(
            message.metadata.get("delegated_run_summary_for_run_id") == "agent_run_secret"
            for message in runtime.chat_session.get_all_messages()
        )
    finally:
        store.close()


def test_get_messages_hides_internal_reasoning_activity(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    try:
        result = api.send_message("普通回复")
        task_id = result["task_id"]
        runtime.state.update_task_progress(task_id, "Native Agent 正在推理")
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="",
            phase="reasoning",
            title="Native Agent 正在推理",
            detail="内部思考片段",
            status="running",
        )
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="native_agent",
            phase="task_start",
            title="Yachiyo 开始处理",
            detail="普通回复",
            status="running",
        )
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="send_message",
            phase="tool_start",
            title="正在调用send message",
            detail='to ?: "<oha_group_dispatch>{\\"tasks\\":[]}"',
            status="running",
        )
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="send_message",
            phase="tool_complete",
            title="send message调用完成",
            detail='{"error":"Both target and message are required"}',
            status="completed",
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


def test_list_sessions_repairs_stale_processing_without_live_task(tmp_path, monkeypatch):
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
        assert current["processing_count"] == 0
        assert current["latest_message_preview"] == "已经完成的问题"
        assert current["latest_message_status"] == "failed"
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


def test_list_sessions_limit_zero_returns_all_search_matches(tmp_path, monkeypatch):
    api, _runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        for index in range(3):
            session_id = f"search-{index}"
            store.create_session(session_id)
            store.save_message(StoredMessage(
                message_id=f"search-message-{index}",
                session_id=session_id,
                role="user",
                content=f"共同搜索词 {index}",
                status="completed",
                task_id=None,
                error=None,
                created_at=f"2026-01-01T00:00:0{index}+00:00",
            ))

        sessions = api.list_sessions(limit=0, query="共同搜索词")["sessions"]

        assert len(sessions) == 3
    finally:
        store.close()


def test_chat_payloads_include_estimated_token_counts(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("你好 world")
        runtime.chat_session.add_assistant_message("收到，开始处理。")

        messages_payload = api.get_messages()
        assert messages_payload["token_count"] > 0
        assert all(message["token_count"] > 0 for message in messages_payload["messages"])

        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)
        assert current["token_count"] == messages_payload["token_count"]
    finally:
        store.close()


def test_get_messages_refreshes_current_session_from_store(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("同步测试")
        background_session = ChatSession(session_id=session_id)
        background_session.attach_store(store, load_existing=True, fail_active_messages=False)
        background_session.add_assistant_message("后台写回的回复")

        assert all(message.content != "后台写回的回复" for message in runtime.chat_session.get_messages(limit=0))

        messages = api.get_messages()["messages"]

        assert any(message["content"] == "后台写回的回复" for message in messages)
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
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_URL", "http://127.0.0.1:9999")
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


def test_send_message_with_only_image_attachment_uses_default_image_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_URL", "http://127.0.0.1:9999")
    api, runtime, store = _make_api(tmp_path)
    try:
        data_url = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")

        result = api.send_message(
            "",
            attachments=[{
                "name": "screen.png",
                "data_url": data_url,
            }],
        )

        assert result["ok"] is True
        assert result["status"] == "pending"
        assert len(result["attachments"]) == 1
        assert result["attachments"][0]["url"].startswith("http://127.0.0.1:9999/ui/chat/attachments/")
        assert "path" not in result["attachments"][0]

        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.description == "请识别并分析这张图片。"
        assert len(task.attachments) == 1
        assert task.attachments[0]["kind"] == "image"
        assert task.attachments[0]["path"].endswith(".png")

        user = runtime.chat_session.get_messages()[0]
        assert user.content == "请识别并分析这张图片。"
        assert len(user.attachments) == 1
        assert user.attachments[0]["kind"] == "image"

        messages = api.get_messages()["messages"]
        assert messages[0]["content"] == "请识别并分析这张图片。"
        assert messages[0]["attachments"][0]["url"].startswith("http://127.0.0.1:9999/ui/chat/attachments/")
        assert "path" not in messages[0]["attachments"][0]
    finally:
        store.close()


def test_proactive_session_followup_attaches_fresh_desktop_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
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
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
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


def test_user_requested_desktop_snapshot_permission_error_is_structured(tmp_path, monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
    captures = []
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    leaked_secret = "sk-screen-secret123456"

    def fake_capture(target_path: Path):
        captures.append(target_path)
        raise chat_api_mod.ScreenCapturePermissionError(f"没有屏幕录制权限，请授权 api_key={leaked_secret}")

    monkeypatch.setattr(chat_api_mod, "capture_screenshot_to_file", fake_capture)
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("帮我看看我的桌面情况", client_message_id="screen-permission-1")
        replay = api.send_message("帮我看看我的桌面情况", client_message_id="screen-permission-1")

        assert result["ok"] is True
        assert len(captures) == 1
        assert result["attachments"] == []
        error = result["desktop_snapshot_error"]
        assert error["code"] == "screen_capture_permission_denied"
        assert error["permission_denied"] is True
        assert "系统设置" in error["message"]
        assert "授权" in error["detail"]
        assert leaked_secret not in json.dumps(result, ensure_ascii=False)
        assert "api_key=[redacted]" in error["detail"]
        assert replay["idempotent"] is True
        assert replay["desktop_snapshot_error"] == error
        assert leaked_secret not in json.dumps(replay, ensure_ascii=False)

        user = runtime.chat_session.get_messages()[0]
        assert user.attachments == []
        assert user.metadata["desktop_snapshot_error"] == error
        user_payload = {
            "content": user.content,
            "metadata": user.metadata,
            "attachments": user.attachments,
            "error": user.error,
        }
        assert leaked_secret not in json.dumps(user_payload, ensure_ascii=False)
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments == []
        assert "无法读取桌面截图" in task.description
        assert "没有屏幕录制权限" in task.description
        assert leaked_secret not in task.description
        assert "api_key=[redacted]" in task.description
        events = activity_store.list_events(task_id=result["task_id"], limit=5, key_only=False)
        assert len(events) == 1
        activity = events[0].to_dict()
        assert activity["tool_name"] == "desktop_snapshot"
        assert activity["phase"] == "desktop_snapshot"
        assert activity["title"] == "无法读取桌面截图"
        assert activity["status"] == "failed"
        assert activity["metadata"]["desktop_snapshot_error"] == error
        assert leaked_secret not in json.dumps(activity, ensure_ascii=False)
        assert verify_secret_redaction(paths=[tmp_path]) == []
    finally:
        activity_store.close()
        store.close()


def test_user_implicit_current_activity_request_does_not_attach_desktop_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
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
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
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
    oha_home = tmp_path / "oha-yachiyo-home"
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(oha_home))
    monkeypatch.setattr("apps.shell.chat_api._MAX_ATTACHMENT_CACHE_AGE_SECONDS", 1)
    monkeypatch.setattr("apps.shell.chat_api._MAX_ATTACHMENT_CACHE_BYTES", 1024 * 1024)
    old_dir = oha_home / "attachments" / "deadbeef"
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
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
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
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_URL", "http://127.0.0.1:9999")
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


def test_retry_failed_message_rejects_when_native_agent_unavailable(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        sent = api.send_message("失败任务")
        runtime.state.update_task_status(sent["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(sent["task_id"], TaskStatus.FAILED, error="boom")
        failed_messages = api.get_messages()["messages"]
        runtime.task_runner = SimpleNamespace(
            executor=SimpleNamespace(
                name="NativeAgentUnavailableExecutor",
                reason="Native Agent 当前未就绪，请先配置并选择默认对话模型。",
                code="native_agent_not_ready",
                reason_code="model_profile_required",
            )
        )

        retry = api.retry_message(failed_messages[1]["id"])

        assert retry == {
            "ok": False,
            "code": "native_agent_not_ready",
            "reason": "model_profile_required",
            "error": "Native Agent 当前未就绪，请先配置并选择默认对话模型。",
        }
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


def test_completing_multiple_overlapping_messages_pairs_each_reply(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        first = api.send_message("任务一")
        second = api.send_message("任务二")

        runtime.state.update_task_status(first["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(second["task_id"], TaskStatus.RUNNING)
        assert api.get_session_info()["is_processing"] is True

        runtime.state.update_task_status(
            second["task_id"], TaskStatus.COMPLETED, result="任务二完成"
        )
        runtime.state.update_task_status(
            first["task_id"], TaskStatus.COMPLETED, result="任务一完成"
        )

        messages = api.get_messages()["messages"]

        assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant"]
        assert [message["content"] for message in messages] == ["任务一", "任务一完成", "任务二", "任务二完成"]
        assert [message["status"] for message in messages] == ["completed", "completed", "completed", "completed"]
        assert api.get_session_info()["is_processing"] is False
    finally:
        store.close()


def test_list_sessions_counts_overlapping_processing_tasks(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        first = api.send_message("任务一")
        second = api.send_message("任务二")
        runtime.state.update_task_status(first["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(second["task_id"], TaskStatus.RUNNING)

        current = next(
            item for item in api.list_sessions()["sessions"]
            if item["session_id"] == runtime.chat_session.session_id
        )
        assert current["is_processing"] is True
        assert current["processing_count"] == 2
        messages_payload = api.get_messages()
        assert messages_payload["is_processing"] is True
        assert messages_payload["processing_count"] == 2
        assert api.get_session_info()["processing_count"] == 2

        runtime.state.update_task_status(first["task_id"], TaskStatus.COMPLETED, result="任务一完成")
        messages_payload = api.get_messages()
        assert messages_payload["is_processing"] is True
        assert messages_payload["processing_count"] == 1
        current = next(
            item for item in api.list_sessions()["sessions"]
            if item["session_id"] == runtime.chat_session.session_id
        )
        assert current["is_processing"] is True
        assert current["processing_count"] == 1

        runtime.state.update_task_status(second["task_id"], TaskStatus.COMPLETED, result="任务二完成")
        messages_payload = api.get_messages()
        assert messages_payload["is_processing"] is False
        assert messages_payload["processing_count"] == 0
        current = next(
            item for item in api.list_sessions()["sessions"]
            if item["session_id"] == runtime.chat_session.session_id
        )
        assert current["is_processing"] is False
        assert current["processing_count"] == 0
    finally:
        store.close()


def test_list_sessions_syncs_current_agent_run_result(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    sender = {"name": "Design Agent", "nickname": "Design"}

    class FakeRunnableService:
        def get_run(self, run_id):
            assert run_id == "agent_run_completed"
            return {
                "run_id": run_id,
                "run_group_id": "run_group_design",
                "status": "completed",
                "result": "Design 已完成视觉方案。",
                "timeline": [],
                "runnable": {"id": "agent_design", "name": "Design Agent", "kind": "agent"},
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("请 Design 做个方案")
        assistant_id = runtime.chat_session.add_assistant_message(
            "",
            metadata={
                "sender": sender,
                "runnable_kind": "agent",
                "runnable_id": "agent_design",
                "run_id": "agent_run_completed",
                "run_group_id": "run_group_design",
                "run_status": "processing",
            },
        )
        runtime.chat_session.update_assistant_message(
            assistant_id,
            "",
            status=MessageStatus.PROCESSING,
        )

        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)
        stored_messages = store.load_messages(session_id)
        assistant = next(message for message in stored_messages if message.role == MessageRole.ASSISTANT.value)

        assert current["is_processing"] is False
        assert current["processing_count"] == 0
        assert current["latest_message_status"] == "completed"
        assert assistant.status == MessageStatus.COMPLETED.value
        assert assistant.content == "Design 已完成视觉方案。"
    finally:
        store.close()


def test_list_sessions_syncs_legacy_running_run_metadata(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    sender = {"name": "Design Agent", "nickname": "Design"}

    class FakeRunnableService:
        def get_run(self, run_id):
            assert run_id == "agent_run_legacy_running"
            return {
                "run_id": run_id,
                "run_group_id": "run_group_design",
                "kind": "agent_run",
                "status": "completed",
                "result": "旧 running metadata 已同步。",
                "timeline": [],
                "runnable": {"id": "agent_design", "name": "Design Agent", "kind": "agent"},
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("请 Design 做个方案")
        runtime.chat_session.add_assistant_message(
            "旧的完成态占位",
            metadata={
                "sender": sender,
                "runnable_kind": "agent",
                "runnable_id": "agent_design",
                "run_id": "agent_run_legacy_running",
                "run_group_id": "run_group_design",
                "run_status": "running",
            },
        )

        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)
        stored_messages = store.load_messages(session_id)
        assistant = next(message for message in stored_messages if message.role == MessageRole.ASSISTANT.value)
        metadata = json.loads(assistant.metadata_json)

        assert current["is_processing"] is False
        assert current["processing_count"] == 0
        assert current["latest_message_status"] == "completed"
        assert assistant.status == MessageStatus.COMPLETED.value
        assert assistant.content == "旧 running metadata 已同步。"
        assert metadata["run_status"] == "completed"
    finally:
        store.close()


def test_list_sessions_syncs_current_workflow_run_result(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)

    class FakeRunnableService:
        def get_run(self, run_id):
            assert run_id == "workflow_run_completed"
            return {
                "run_id": run_id,
                "run_group_id": "run_group_workflow",
                "kind": "workflow_run",
                "status": "completed",
                "result": "Workflow 已完成并生成交付物。",
                "timeline": [
                    {"event": "workflow.run.started", "detail": "Demo Workflow"},
                    {"event": "workflow.run.completed", "detail": "Demo Workflow"},
                ],
                "runnable": {"id": "workflow_demo", "name": "Demo Workflow", "kind": "workflow"},
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("@Demo Workflow 跑一下")
        assistant_id = runtime.chat_session.add_assistant_message(
            "",
            metadata={
                "sender": {"name": "Demo Workflow", "kind": "workflow"},
                "runnable_kind": "workflow",
                "runnable_id": "workflow_demo",
                "run_id": "workflow_run_completed",
                "run_group_id": "run_group_workflow",
                "workflow_status": "processing",
            },
        )
        runtime.chat_session.update_assistant_message(
            assistant_id,
            "",
            status=MessageStatus.PROCESSING,
        )

        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)
        stored_messages = store.load_messages(session_id)
        assistant = next(message for message in stored_messages if message.role == MessageRole.ASSISTANT.value)
        metadata = json.loads(assistant.metadata_json)

        assert current["is_processing"] is False
        assert current["processing_count"] == 0
        assert current["latest_message_status"] == "completed"
        assert assistant.status == MessageStatus.COMPLETED.value
        assert assistant.content == "Workflow 已完成并生成交付物。"
        assert metadata["run_status"] == "completed"
        assert metadata["workflow_status"] == "completed"
    finally:
        store.close()


def test_list_sessions_syncs_current_workflow_failure_with_node_hint(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)

    class FakeRunnableService:
        def get_run(self, run_id):
            assert run_id == "workflow_run_failed"
            return {
                "run_id": run_id,
                "run_group_id": "run_group_workflow",
                "kind": "workflow_run",
                "status": "failed",
                "result": "model exploded",
                "timeline": [
                    {"event": "workflow.run.started", "detail": "Demo Workflow"},
                    {
                        "event": "workflow.run.failed",
                        "detail": "Failing Agent: model exploded",
                        "workflow_node_id": "agent-a",
                        "workflow_node_kind": "agent",
                        "workflow_node_label": "Failing Agent",
                        "status": "failed",
                    },
                ],
                "runnable": {"id": "workflow_demo", "name": "Demo Workflow", "kind": "workflow"},
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("@Demo Workflow 跑一下")
        assistant_id = runtime.chat_session.add_assistant_message(
            "",
            metadata={
                "sender": {"name": "Demo Workflow", "kind": "workflow"},
                "runnable_kind": "workflow",
                "runnable_id": "workflow_demo",
                "run_id": "workflow_run_failed",
                "run_group_id": "run_group_workflow",
                "workflow_status": "processing",
            },
        )
        runtime.chat_session.update_assistant_message(
            assistant_id,
            "",
            status=MessageStatus.PROCESSING,
        )

        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)
        stored_messages = store.load_messages(session_id)
        assistant = next(message for message in stored_messages if message.role == MessageRole.ASSISTANT.value)
        metadata = json.loads(assistant.metadata_json)

        assert current["is_processing"] is False
        assert current["processing_count"] == 0
        assert current["latest_message_status"] == "failed"
        assert assistant.status == MessageStatus.FAILED.value
        assert assistant.content == "Demo Workflow 执行失败。\n失败节点：Failing Agent（agent）\n\nmodel exploded"
        assert assistant.error == assistant.content
        assert metadata["run_status"] == "failed"
        assert metadata["workflow_status"] == "failed"
    finally:
        store.close()


def test_list_sessions_counts_workflow_approval_required(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)

    class FakeRunnableService:
        def get_run(self, run_id):
            assert run_id == "workflow_run_waiting"
            return {
                "run_id": run_id,
                "run_group_id": "run_group_workflow",
                "kind": "workflow_run",
                "status": "approval_required",
                "result": "Workflow 等待人工确认。",
                "timeline": [
                    {"event": "workflow.run.started", "detail": "Demo Workflow"},
                    {"event": "workflow.node.approval_required", "detail": "人工审批", "status": "approval_required"},
                ],
                "pending_approval": {
                    "approval_id": "workflow_approval",
                    "tool": "workflow.approval",
                    "input_preview": {"checkpoint": "人工审批"},
                },
                "runnable": {"id": "workflow_demo", "name": "Demo Workflow", "kind": "workflow"},
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("@Demo Workflow 跑一下")
        assistant_id = runtime.chat_session.add_assistant_message(
            "",
            metadata={
                "sender": {"name": "Demo Workflow", "kind": "workflow"},
                "runnable_kind": "workflow",
                "runnable_id": "workflow_demo",
                "run_id": "workflow_run_waiting",
                "run_group_id": "run_group_workflow",
                "workflow_status": "approval_required",
            },
        )
        runtime.chat_session.update_assistant_message(
            assistant_id,
            "",
            status=MessageStatus.PROCESSING,
        )

        payload = api.get_messages()
        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)
        session_info = api.get_session_info()
        stored_messages = store.load_messages(session_id)
        assistant = next(message for message in stored_messages if message.role == MessageRole.ASSISTANT.value)
        metadata = json.loads(assistant.metadata_json)

        assert payload["processing_count"] == 1
        assert payload["approval_count"] == 1
        assert session_info["approval_count"] == 1
        assert current["processing_count"] == 1
        assert current["approval_count"] == 1
        assert current["latest_message_status"] == "processing"
        assert assistant.status == MessageStatus.PROCESSING.value
        assert "Demo Workflow 需要你确认一个 Workflow 审批节点" in assistant.content
        assert metadata["run_status"] == "approval_required"
        assert metadata["workflow_status"] == "approval_required"
        assert metadata["pending_approval"]["tool"] == "workflow.approval"
    finally:
        store.close()


def test_list_sessions_clears_workflow_child_approval_after_parent_resumes(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)

    class FakeRunnableService:
        def get_run(self, run_id):
            assert run_id == "workflow_run_resumed"
            return {
                "run_id": run_id,
                "run_group_id": "run_group_workflow",
                "kind": "workflow_run",
                "status": "processing",
                "result": "",
                "timeline": [
                    {"event": "workflow.run.started", "detail": "Demo Workflow"},
                    {"event": "workflow.node.agent", "detail": "Coding Agent"},
                ],
                "pending_approval": {},
                "runnable": {"id": "workflow_demo", "name": "Demo Workflow", "kind": "workflow"},
            }

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("@Demo Workflow 继续跑")
        assistant_id = runtime.chat_session.add_assistant_message(
            "Demo Workflow 正在等待子 Agent 审批。",
            metadata={
                "sender": {"name": "Demo Workflow", "kind": "workflow"},
                "runnable_kind": "workflow",
                "runnable_id": "workflow_demo",
                "run_id": "workflow_run_resumed",
                "run_group_id": "run_group_workflow",
                "run_status": "processing",
                "workflow_status": "approval_required",
                "pending_approval": {},
                "workflow_waiting_child_run_id": "child_run_waiting",
                "workflow_waiting_node": "Coding Agent",
                "workflow_waiting_tool": "terminal.run",
            },
        )
        runtime.chat_session.update_assistant_message(
            assistant_id,
            "Demo Workflow 正在等待子 Agent 审批。",
            status=MessageStatus.PROCESSING,
        )

        payload = api.get_messages()
        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)
        stored_messages = store.load_messages(session_id)
        assistant = next(message for message in stored_messages if message.role == MessageRole.ASSISTANT.value)
        metadata = json.loads(assistant.metadata_json)

        assert payload["processing_count"] == 1
        assert payload["approval_count"] == 0
        assert current["processing_count"] == 1
        assert current["approval_count"] == 0
        assert assistant.status == MessageStatus.PROCESSING.value
        assert assistant.content == ""
        assert metadata["run_status"] == "processing"
        assert metadata["workflow_status"] == "processing"
        assert metadata["pending_approval"] == {}
        assert metadata["run_progress_title"]
        assert "workflow_waiting_child_run_id" not in metadata
        assert "workflow_waiting_node" not in metadata
        assert "workflow_waiting_tool" not in metadata
        assert "workflow_waiting_pending_approval" not in metadata
    finally:
        store.close()


def test_cancel_current_tasks_cancels_active_agent_runs(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    sender = {"name": "Design Agent", "nickname": "Design"}

    class FakeRunnableService:
        def __init__(self):
            self.cancelled: list[str] = []
            self.runs = {
                "agent_run_processing": {
                    "run_id": "agent_run_processing",
                    "run_group_id": "run_group_dispatch",
                    "status": "processing",
                    "result": "",
                    "timeline": [],
                }
            }

        def get_run(self, run_id):
            return self.runs[run_id]

        def cancel_run(self, run_id):
            self.cancelled.append(run_id)
            run = {
                **self.runs[run_id],
                "status": "cancelled",
                "result": "用户已停止当前 Agent Run。",
            }
            self.runs[run_id] = run
            return run

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        runtime.chat_session.add_user_message("请 Design 做个测试")
        assistant_id = runtime.chat_session.add_assistant_message(
            "",
            metadata={
                "sender": sender,
                "runnable_kind": "agent",
                "runnable_id": "agent_design",
                "run_id": "agent_run_processing",
                "run_group_id": "run_group_dispatch",
                "run_status": "processing",
                "conversation_kind": "group",
                "group_goal": "做视觉测试",
            },
        )
        runtime.chat_session.update_assistant_message(
            assistant_id,
            "",
            status=MessageStatus.PROCESSING,
        )

        assert api.get_messages()["processing_count"] == 1

        cancelled = api.cancel_current_tasks()

        assert cancelled["ok"] is True
        assert cancelled["cancelled_tasks"] == 1
        assert cancelled["processing_count"] == 0
        assert cancelled["is_processing"] is False
        assert service.cancelled == ["agent_run_processing"]
        assert runtime.state.list_tasks() == []

        agent_message = next(
            message for message in cancelled["messages"]
            if message["metadata"].get("run_id") == "agent_run_processing"
        )
        assert agent_message["status"] == "failed"
        assert agent_message["metadata"]["run_status"] == "cancelled"
        assert agent_message["content"].startswith("Design 任务已取消。")
        assert "主模型整理" not in agent_message["content"]
    finally:
        store.close()


def test_cancel_current_tasks_cancels_active_workflow_runs(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)

    class FakeRunnableService:
        def __init__(self):
            self.cancelled: list[str] = []
            self.runs = {
                "workflow_run_processing": {
                    "run_id": "workflow_run_processing",
                    "run_group_id": "run_group_workflow",
                    "status": "approval_required",
                    "result": "",
                    "timeline": [],
                    "kind": "workflow_run",
                }
            }

        def get_run(self, run_id):
            return self.runs[run_id]

        def cancel_run(self, run_id):
            self.cancelled.append(run_id)
            run = {
                **self.runs[run_id],
                "status": "cancelled",
                "result": "Workflow 已取消：用户停止生成",
            }
            self.runs[run_id] = run
            return run

    service = FakeRunnableService()
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    try:
        runtime.chat_session.add_user_message("@Demo Flow 跑一下")
        assistant_id = runtime.chat_session.add_assistant_message(
            "Demo Flow 等待审批。",
            metadata={
                "sender": {"name": "Demo Flow", "kind": "workflow"},
                "runnable_kind": "workflow",
                "runnable_id": "workflow_demo",
                "run_id": "workflow_run_processing",
                "run_group_id": "run_group_workflow",
                "workflow_status": "approval_required",
            },
        )
        runtime.chat_session.update_assistant_message(
            assistant_id,
            "Demo Flow 等待审批。",
            status=MessageStatus.PROCESSING,
        )

        assert api.get_messages()["processing_count"] == 1

        cancelled = api.cancel_current_tasks()

        assert cancelled["ok"] is True
        assert cancelled["cancelled_tasks"] == 1
        assert cancelled["processing_count"] == 0
        assert service.cancelled == ["workflow_run_processing"]

        workflow_message = next(
            message for message in cancelled["messages"]
            if message["metadata"].get("run_id") == "workflow_run_processing"
        )
        assert workflow_message["status"] == "failed"
        assert workflow_message["content"] == "Workflow 已取消：用户停止生成"
        assert workflow_message["metadata"]["run_status"] == "cancelled"
        assert workflow_message["metadata"]["workflow_status"] == "cancelled"
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
