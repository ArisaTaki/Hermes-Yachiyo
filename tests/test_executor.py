"""Executor 测试 — Native Agent TaskRunner adapter and executor helpers."""

import asyncio
import base64
import types

import pytest

from apps.core.executor import (
    NativeAgentError,
    NativeAgentExecutor,
    NativeAgentUnavailableExecutor,
    SimulatedExecutor,
    format_environment_context,
    _build_session_title_prompt,
    _sanitize_generated_session_title,
    _should_refresh_generated_title,
    build_cross_session_memory_context,
    format_persona_description,
    select_executor,
    user_task_unavailable_reason,
)
import apps.core.executor as executor_mod
from apps.core.chat_session import ChatSession, MessageStatus
from apps.core.activity_store import ActivityStore
from apps.core.chat_store import ChatStore
from packages.protocol.enums import RiskLevel, TaskStatus, TaskType
from packages.protocol.schemas import TaskInfo
from datetime import datetime, timezone


def _make_task(desc: str = "test", attachments: list[dict] | None = None) -> TaskInfo:
    now = datetime.now(timezone.utc)
    return TaskInfo(
        task_id="test001",
        description=desc,
        task_type=TaskType.GENERAL,
        status=TaskStatus.PENDING,
        risk_level=RiskLevel.LOW,
        created_at=now,
        updated_at=now,
        attachments=list(attachments or []),
    )


class TestSimulatedExecutor:
    @pytest.mark.asyncio
    async def test_run_returns_result(self):
        """SimulatedExecutor 应返回模拟结果字符串"""
        executor = SimulatedExecutor()
        task = _make_task("测试模拟任务")
        # 为加速测试，monkey-patch 延迟
        import apps.core.executor as mod
        original_run = mod._SIM_RUN_DELAY
        original_complete = mod._SIM_COMPLETE_DELAY
        mod._SIM_RUN_DELAY = 0.01
        mod._SIM_COMPLETE_DELAY = 0.01
        try:
            result = await executor.run(task)
            assert "[模拟结果]" in result
            assert "测试模拟任务" in result
        finally:
            mod._SIM_RUN_DELAY = original_run
            mod._SIM_COMPLETE_DELAY = original_complete


class TestNativeAgentUnavailableExecutor:
    @pytest.mark.asyncio
    async def test_run_fails_without_simulated_result(self):
        executor = NativeAgentUnavailableExecutor("Native Agent 当前未就绪", reason="model_profile_required")

        with pytest.raises(NativeAgentError, match="Native Agent 当前未就绪") as excinfo:
            await executor.run(_make_task("测试任务"))

        assert "[模拟结果]" not in excinfo.value.to_error_string()
        assert excinfo.value.code == "native_agent_not_ready"
        assert excinfo.value.reason == "model_profile_required"

    def test_user_task_unavailable_reason_allows_model_capable_executor(self):
        runtime = types.SimpleNamespace(
            task_runner=types.SimpleNamespace(
                executor=types.SimpleNamespace(
                    name="NativeAgentExecutor",
                    capabilities={"model": True, "image_input": True, "tools": False, "approval": False},
                )
            )
        )

        assert user_task_unavailable_reason(runtime) is None

    def test_user_task_unavailable_reason_returns_executor_reason(self):
        runtime = types.SimpleNamespace(
            task_runner=types.SimpleNamespace(
                executor=types.SimpleNamespace(
                    name="NativeAgentUnavailableExecutor",
                    reason="Native Agent 当前未就绪",
                )
            )
        )

        assert user_task_unavailable_reason(runtime) == "Native Agent 当前未就绪"

    def test_select_executor_returns_native_unavailable_when_runtime_not_ready(self):
        runtime = types.SimpleNamespace(
            native_agent_readiness=lambda: {
                "ready": False,
                "reason": "model_profile_required",
                "message": "请先配置默认对话模型",
            },
        )

        executor = select_executor(runtime)

        assert isinstance(executor, NativeAgentUnavailableExecutor)
        assert executor.reason_code == "model_profile_required"


class TestNativeAgentExecutor:
    def test_record_activity_uses_injected_activity_store(self, tmp_path, monkeypatch):
        activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))

        def fail_global_activity_store():
            raise AssertionError("NativeAgentExecutor should use the injected ActivityStore")

        monkeypatch.setattr("apps.core.activity_store.get_activity_store", fail_global_activity_store)
        executor = NativeAgentExecutor(activity_store_getter=lambda: activity_store)
        task = _make_task("委派 activity")
        try:
            executor._record_activity(
                task,
                "正在委派给 Research Agent",
                "检查 Native 委派链路",
                "running",
                metadata={"run_id": "run_1"},
            )

            events = [event.to_dict() for event in activity_store.latest_for_task(task.task_id, limit=5)]
            assert len(events) == 1
            assert events[0]["title"] == "正在委派给 Research Agent"
            assert events[0]["tool_name"] == "oha.delegation"
            assert events[0]["phase"] == "subagent"
            assert events[0]["metadata"]["run_id"] == "run_1"
        finally:
            activity_store.close()

    def test_select_executor_passes_runtime_activity_store(self, tmp_path, monkeypatch):
        activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
        runtime = types.SimpleNamespace(
            native_agent_readiness=lambda: {"ready": True},
            chat_session=None,
            activity_store=activity_store,
        )

        def fail_global_activity_store():
            raise AssertionError("select_executor should inject the runtime ActivityStore")

        monkeypatch.setattr("apps.core.activity_store.get_activity_store", fail_global_activity_store)
        try:
            executor = select_executor(runtime)
            assert isinstance(executor, NativeAgentExecutor)

            task = _make_task("委派 activity")
            executor._record_activity(task, "委派开始", "通过 runtime store", "running")

            events = [event.to_dict() for event in activity_store.latest_for_task(task.task_id, limit=5)]
            assert len(events) == 1
            assert events[0]["title"] == "委派开始"
            assert events[0]["tool_name"] == "oha.delegation"
        finally:
            activity_store.close()

    @pytest.mark.asyncio
    async def test_run_uses_native_run_and_returns_task_result(self, monkeypatch):
        calls: list[tuple[str, object]] = []

        class FakeRuntimeService:
            def start_main_chat_run(self, **payload):
                calls.append(("start", payload))
                return {"run_id": "main_chat_run_1"}

            def call_main_chat_model(self, run_id, messages, **_kwargs):
                calls.append(("model", {"run_id": run_id, "messages": messages}))
                return "Native 回复"

            def complete_main_chat_run(self, run_id, result):
                calls.append(("complete", {"run_id": run_id, "result": result}))
                return {"run_id": run_id, "status": "completed", "result": result}

            def fail_main_chat_run(self, run_id, error):
                calls.append(("fail", {"run_id": run_id, "error": str(error)}))

        monkeypatch.setattr(
            executor_mod,
            "_append_oha_delegation_context",
            lambda context, **_kwargs: context,
        )
        executor = NativeAgentExecutor(runtime_service_getter=FakeRuntimeService)

        result = await executor.run(_make_task("原生任务"))

        assert result == "Native 回复"
        assert [name for name, _payload in calls] == ["start", "model", "complete"]
        model_messages = calls[1][1]["messages"]
        assert model_messages[-1] == {"role": "user", "content": "原生任务"}

    def test_run_uses_injected_runtime_service_for_delegation_catalog(self, monkeypatch):
        calls: list[tuple[str, object]] = []

        class FakeRuntimeService:
            def list_delegation_targets(self):
                calls.append(("catalog", {}))
                return {
                    "agents": [
                        {
                            "name": "Injected Agent",
                            "category": "research",
                            "output_contract": "chat",
                            "description": "uses injected runtime service",
                        }
                    ],
                    "workflows": [],
                }

            def start_main_chat_run(self, **payload):
                calls.append(("start", payload))
                return {"run_id": "main_chat_run_injected_catalog"}

            def call_main_chat_model(self, run_id, messages, **_kwargs):
                calls.append(("model", {"run_id": run_id, "messages": messages}))
                return "Native injected catalog reply"

            def complete_main_chat_run(self, run_id, result):
                calls.append(("complete", {"run_id": run_id, "result": result}))
                return {"status": "completed", "result": result}

            def fail_main_chat_run(self, _run_id, _error):
                raise AssertionError("should not fail")

        service = FakeRuntimeService()
        monkeypatch.setattr(
            "apps.shell.agent_runtime.get_agent_runtime_service",
            lambda: (_ for _ in ()).throw(AssertionError("delegation catalog should use injected runtime service")),
        )
        executor = NativeAgentExecutor(runtime_service_getter=lambda: service)

        result = asyncio.run(executor.run(_make_task("需要读取委派目录")))

        assert result == "Native injected catalog reply"
        assert [name for name, _payload in calls] == ["start", "catalog", "model", "complete"]
        model_messages = calls[2][1]["messages"]
        system_prompt = model_messages[0]["content"]
        assert "Injected Agent" in system_prompt
        assert "uses injected runtime service" in system_prompt

    @pytest.mark.asyncio
    async def test_run_passes_recent_chat_history_and_excludes_current_task(self, monkeypatch):
        calls: list[tuple[str, object]] = []
        session = ChatSession(session_id="context-test")
        for index in range(12):
            session.add_user_message(f"old user {index}")
            session.add_assistant_message(f"old assistant {index}")
        current_message_id = session.add_user_message("current linked user")
        session.link_message_to_task(current_message_id, "test001")
        session.add_assistant_message("current assistant should be excluded", task_id="test001")

        class FakeRuntimeService:
            def start_main_chat_run(self, **payload):
                calls.append(("start", payload))
                return {"run_id": "main_chat_run_context"}

            def call_main_chat_model(self, run_id, messages, **_kwargs):
                calls.append(("model", {"run_id": run_id, "messages": messages}))
                return "Native context reply"

            def complete_main_chat_run(self, run_id, result):
                calls.append(("complete", {"run_id": run_id, "result": result}))
                return {"status": "completed", "result": result}

            def fail_main_chat_run(self, _run_id, _error):
                raise AssertionError("should not fail")

        monkeypatch.setattr(
            executor_mod,
            "_append_oha_delegation_context",
            lambda context, **_kwargs: context,
        )
        executor = NativeAgentExecutor(
            chat_session=session,
            runtime_service_getter=FakeRuntimeService,
        )

        result = await executor.run(_make_task("new user task"))

        assert result == "Native context reply"
        messages = calls[1][1]["messages"]
        history = messages[1:-1]
        assert len(history) == 20
        assert history[0] == {"role": "user", "content": "old user 2"}
        assert history[-1] == {"role": "assistant", "content": "old assistant 11"}
        assert messages[-1] == {"role": "user", "content": "new user task"}
        contents = [message.get("content") for message in messages]
        assert "old user 0" not in contents
        assert "old assistant 1" not in contents
        assert "current linked user" not in contents
        assert "current assistant should be excluded" not in contents

    @pytest.mark.asyncio
    async def test_run_limits_chat_history_by_context_chars(self, monkeypatch):
        calls: list[tuple[str, object]] = []
        session = ChatSession(session_id="context-char-limit-test")
        session.add_user_message("short kept")
        session.add_assistant_message("short assistant kept")
        session.add_user_message("x" * 33_000)

        class FakeRuntimeService:
            def start_main_chat_run(self, **payload):
                calls.append(("start", payload))
                return {"run_id": "main_chat_run_context_chars"}

            def call_main_chat_model(self, run_id, messages, **_kwargs):
                calls.append(("model", {"run_id": run_id, "messages": messages}))
                return "Native char limit reply"

            def complete_main_chat_run(self, run_id, result):
                calls.append(("complete", {"run_id": run_id, "result": result}))
                return {"status": "completed", "result": result}

            def fail_main_chat_run(self, _run_id, _error):
                raise AssertionError("should not fail")

        monkeypatch.setattr(
            executor_mod,
            "_append_oha_delegation_context",
            lambda context, **_kwargs: context,
        )
        executor = NativeAgentExecutor(
            chat_session=session,
            runtime_service_getter=FakeRuntimeService,
        )

        await executor.run(_make_task("new user task"))

        messages = calls[1][1]["messages"]
        assert messages[1:-1] == []
        assert messages[-1] == {"role": "user", "content": "new user task"}

    @pytest.mark.asyncio
    async def test_run_passes_image_attachments_as_limited_data_urls(self, tmp_path, monkeypatch):
        calls: list[tuple[str, object]] = []
        image_paths = []
        for index in range(5):
            path = tmp_path / f"image-{index}.png"
            path.write_bytes(f"fake-png-{index}".encode("ascii"))
            image_paths.append(path)
        missing = tmp_path / "missing.png"

        class FakeRuntimeService:
            def start_main_chat_run(self, **payload):
                calls.append(("start", payload))
                return {"run_id": "main_chat_run_images"}

            def call_main_chat_model(self, run_id, messages, **_kwargs):
                calls.append(("model", {"run_id": run_id, "messages": messages}))
                return "Native image reply"

            def complete_main_chat_run(self, run_id, result):
                calls.append(("complete", {"run_id": run_id, "result": result}))
                return {"status": "completed", "result": result}

            def fail_main_chat_run(self, _run_id, _error):
                raise AssertionError("should not fail")

        monkeypatch.setattr(
            executor_mod,
            "_append_oha_delegation_context",
            lambda context, **_kwargs: context,
        )
        monkeypatch.setattr(
            "apps.shell.native_capabilities.get_native_image_input_capability",
            lambda: {"can_attach_images": True, "route": "chat"},
        )
        executor = NativeAgentExecutor(runtime_service_getter=FakeRuntimeService)
        task = _make_task(
            "describe images",
            attachments=[
                {"kind": "image", "path": str(path)}
                for path in [*image_paths, missing]
            ],
        )

        result = await executor.run(task)

        assert result == "Native image reply"
        messages = calls[1][1]["messages"]
        content = messages[-1]["content"]
        assert content[0] == {"type": "text", "text": "describe images"}
        image_parts = [part for part in content if part.get("type") == "image_url"]
        assert len(image_parts) == 4
        assert image_parts[0]["image_url"]["url"] == (
            "data:image/png;base64," + base64.b64encode(b"fake-png-0").decode("ascii")
        )
        assert all("fake-png-4" not in part["image_url"]["url"] for part in image_parts)

    def test_select_executor_uses_native_when_ready(self, monkeypatch):
        runtime_service = object()
        runtime = types.SimpleNamespace(
            native_agent_readiness=lambda: {"ready": True},
            chat_session=None,
            agent_runtime_service=runtime_service,
            main_chat_tool_policy=lambda: {
                "allowed_tools": ["workspace.write_patch"],
                "approval_required": {"workspace.write_patch": True},
            },
            main_chat_workspace_policy=lambda: {
                "default_workdir": "/tmp/oha-main",
                "readable_scopes": ["."],
                "writable_scopes": ["."],
            },
        )
        monkeypatch.setattr(
            "apps.shell.agent_runtime.get_native_run_engine",
            lambda: (_ for _ in ()).throw(AssertionError("select_executor should inject AppRuntime service")),
        )

        executor = select_executor(runtime)

        assert isinstance(executor, NativeAgentExecutor)
        assert executor._runtime_service() is runtime_service
        assert executor.capabilities["model"] is True
        assert executor.capabilities["tools"] is True
        assert executor.capabilities["approval"] is True
        assert executor._main_chat_runtime_policy_kwargs() == {
            "tool_policy": {
                "allowed_tools": ["workspace.write_patch"],
                "approval_required": {"workspace.write_patch": True},
            },
            "workspace_policy": {
                "default_workdir": "/tmp/oha-main",
                "readable_scopes": ["."],
                "writable_scopes": ["."],
            },
        }

    @pytest.mark.asyncio
    async def test_run_waits_for_main_chat_tool_approval_resolution(self, monkeypatch):
        calls: list[str] = []

        class FakeRuntimeService:
            def start_main_chat_run(self, **_payload):
                calls.append("start")
                return {"run_id": "main_chat_run_waiting"}

            def execute_main_chat_model_loop(self, _run_id, _messages):
                calls.append("execute_loop")
                return {
                    "run_id": "main_chat_run_waiting",
                    "status": "approval_required",
                    "result": "等待审批：workspace.write_patch",
                    "pending_approval": {
                        "tool": "workspace.write_patch",
                        "input_preview": {"path": "out.txt"},
                    },
                }

            def get_run(self, _run_id):
                calls.append("get_run")
                return {
                    "run_id": "main_chat_run_waiting",
                    "status": "running",
                    "result": "审批后回复",
                    "pending_approval": {},
                }

            def complete_main_chat_run(self, _run_id, result):
                calls.append("complete")
                return {"status": "completed", "result": result}

            def fail_main_chat_run(self, _run_id, _error):
                raise AssertionError("should not fail")

        monkeypatch.setattr(
            executor_mod,
            "_append_oha_delegation_context",
            lambda context, **_kwargs: context,
        )
        executor = NativeAgentExecutor(runtime_service_getter=FakeRuntimeService)

        result = await executor.run(_make_task("需要审批"))

        assert result == "审批后回复"
        assert calls == ["start", "execute_loop", "get_run", "complete"]

    @pytest.mark.asyncio
    async def test_run_times_out_main_chat_approval_through_runtime_boundary(self, monkeypatch):
        calls: list[str] = []
        real_sleep = asyncio.sleep

        async def fast_sleep(_seconds):
            await real_sleep(0)

        class FakeRuntimeService:
            status = "approval_required"

            def start_main_chat_run(self, **_payload):
                calls.append("start")
                return {"run_id": "main_chat_run_timeout"}

            def execute_main_chat_model_loop(self, _run_id, _messages):
                calls.append("execute_loop")
                return {
                    "run_id": "main_chat_run_timeout",
                    "status": "approval_required",
                    "result": "等待审批：terminal.run",
                    "pending_approval": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "printf waiting"},
                    },
                }

            def get_run(self, _run_id):
                calls.append("get_run")
                return {
                    "run_id": "main_chat_run_timeout",
                    "status": self.status,
                    "result": (
                        "工具审批已超时：approval_wait_timeout"
                        if self.status == "cancelled"
                        else "等待审批：terminal.run"
                    ),
                    "pending_approval": {} if self.status == "cancelled" else {
                        "tool": "terminal.run",
                        "input_preview": {"command": "printf waiting"},
                    },
                }

            def timeout_run_approval(self, _run_id, reason):
                calls.append(f"timeout:{reason}")
                self.status = "cancelled"
                return {
                    "run_id": "main_chat_run_timeout",
                    "status": "cancelled",
                    "result": "工具审批已超时：approval_wait_timeout",
                    "pending_approval": {},
                }

            def cancel_run(self, _run_id):
                raise AssertionError("timeout should use timeout_run_approval when available")

            def complete_main_chat_run(self, _run_id, _result):
                raise AssertionError("timed-out run should not complete")

            def fail_main_chat_run(self, _run_id, _error):
                raise AssertionError("approval timeout is already finalized by the runtime")

        monkeypatch.setattr(
            executor_mod,
            "_append_oha_delegation_context",
            lambda context, **_kwargs: context,
        )
        monkeypatch.setattr(executor_mod.asyncio, "sleep", fast_sleep)
        monkeypatch.setattr(
            NativeAgentExecutor,
            "_approval_wait_timeout_seconds",
            staticmethod(lambda: 0.001),
        )
        executor = NativeAgentExecutor(runtime_service_getter=FakeRuntimeService)

        with pytest.raises(NativeAgentError) as excinfo:
            await executor.run(_make_task("需要审批但无人处理"))

        assert excinfo.value.reason == "approval_timeout"
        assert str(excinfo.value) == "工具审批已超时：approval_wait_timeout"
        assert calls[0:2] == ["start", "execute_loop"]
        assert "timeout:approval_wait_timeout" in calls
        assert not any(call == "cancel" for call in calls)

    @pytest.mark.asyncio
    async def test_run_delegates_oha_agent_before_final_reply(self, monkeypatch):
        calls: list[list[dict]] = []

        class FakeRuntimeService:
            def start_main_chat_run(self, **_payload):
                return {"run_id": "main_chat_run_1"}

            def call_main_chat_model(self, _run_id, messages, **_kwargs):
                calls.append(messages)
                if len(calls) == 1:
                    return '{"action":"run_oha_agent","agent":"Research Agent","goal":"核对事实"}'
                return "最终回复"

            def complete_main_chat_run(self, _run_id, result):
                return {"status": "completed", "result": result}

            def fail_main_chat_run(self, _run_id, _error):
                raise AssertionError("should not fail")

        monkeypatch.setattr(executor_mod, "_oha_delegation_catalog_context", lambda *_args, **_kwargs: "catalog")
        monkeypatch.setattr(
            executor_mod,
            "_run_oha_delegation",
            lambda request, _service=None: {
                "ok": True,
                "runnable": {"kind": request.kind, "name": request.name, "id": "agent_research"},
                "run_id": "agent_run_1",
                "run_group_id": "run_group_1",
                "status": "completed",
                "result": "事实核对完成",
            },
        )

        executor = NativeAgentExecutor(runtime_service_getter=FakeRuntimeService)
        result = await executor.run(_make_task("需要研究"))

        assert result == "最终回复"
        assert len(calls) == 2
        assert "catalog" in calls[0][0]["content"]
        assert "事实核对完成" in calls[1][-1]["content"]

    @pytest.mark.asyncio
    async def test_group_mode_returns_dispatch_for_chat_layer(self, monkeypatch):
        calls: list[list[dict]] = []
        dispatch = '{"action":"run_oha_agent","agent":"Research Agent","goal":"核对事实"}'

        class FakeRuntimeService:
            def start_main_chat_run(self, **_payload):
                return {"run_id": "main_chat_run_1"}

            def call_main_chat_model(self, _run_id, messages, **_kwargs):
                calls.append(messages)
                return dispatch

            def complete_main_chat_run(self, _run_id, result):
                return {"status": "completed", "result": result}

            def fail_main_chat_run(self, _run_id, _error):
                raise AssertionError("should not fail")

        delegated: list[dict] = []
        monkeypatch.setattr(
            executor_mod,
            "_oha_delegation_catalog_context",
            lambda *_args, **_kwargs: "single chat catalog",
        )
        monkeypatch.setattr(
            executor_mod,
            "_run_oha_delegation",
            lambda request, _service=None: delegated.append(request),
        )

        executor = NativeAgentExecutor(runtime_service_getter=FakeRuntimeService)
        result = await executor.run(
            _make_task("[Oha-Yachiyo 群组上下文]\n群成员包括：\n- Research Agent（Agent）\n\n请安排")
        )

        system_prompt = calls[0][0]["content"]
        assert result == dispatch
        assert "群组派活" in system_prompt
        assert "先用自然语言向用户说明你的安排" in system_prompt
        assert "oha.group_dispatch" in system_prompt
        assert "<yachiyo_group_dispatch>" not in system_prompt
        assert "只输出 JSON" not in system_prompt
        assert "single chat catalog" not in system_prompt
        assert delegated == []


def test_group_coordinator_detection_accepts_current_and_legacy_context_markers():
    assert executor_mod._is_oha_yachiyo_group_coordinator_task("[Oha-Yachiyo 群组上下文]\n请安排")
    assert executor_mod._is_oha_yachiyo_group_coordinator_task("[Yachiyo 群组上下文]\n请安排")
    assert not executor_mod._is_oha_yachiyo_group_coordinator_task("普通聊天任务")


class TestExecutorHelpers:
    def test_set_chat_session_updates_reference(self):
        executor = NativeAgentExecutor()
        session = object()

        executor.set_chat_session(session)  # type: ignore[arg-type]

        assert executor._chat_session is session

    def test_format_persona_description_keeps_empty_prompt_compatible(self):
        assert format_persona_description("原请求", "") == "原请求"
        assert format_persona_description("原请求", "", "") == "原请求"

    def test_format_persona_description_wraps_prompt(self):
        wrapped = format_persona_description("帮我总结", "你是八千代。")

        assert "[人设设定]" in wrapped
        assert "你是八千代。" in wrapped
        assert "[用户请求]" in wrapped
        assert wrapped.endswith("帮我总结")

    def test_format_persona_description_wraps_user_address(self):
        wrapped = format_persona_description("帮我总结", user_address="老师")

        assert "[用户称呼]" in wrapped
        assert "请称呼用户为：老师" in wrapped
        assert "[用户请求]" in wrapped
        assert wrapped.endswith("帮我总结")

    def test_format_persona_description_wraps_persona_and_user_address(self):
        wrapped = format_persona_description("帮我总结", "你是八千代。", "老师")

        assert wrapped.index("[人设设定]") < wrapped.index("[用户称呼]")
        assert wrapped.index("[用户称呼]") < wrapped.index("[用户请求]")
        assert "你是八千代。" in wrapped
        assert "请称呼用户为：老师" in wrapped

    def test_format_persona_description_wraps_profile_context(self):
        wrapped = format_persona_description(
            "帮我总结",
            "你是八千代。",
            "老师",
            profile_context="[用户资料]\n偏好：回答简洁",
        )

        assert wrapped.index("[用户资料]") < wrapped.index("[人设设定]")
        assert "偏好：回答简洁" in wrapped
        assert wrapped.endswith("帮我总结")

    def test_cross_session_memory_context_collects_explicit_preferences(self):
        session = types.SimpleNamespace(session_id="old", created_at="2026-05-20T10:00:00+00:00")
        store = types.SimpleNamespace(
            list_sessions=lambda limit=80: [session],
            load_messages=lambda _session_id, limit=80: [
                types.SimpleNamespace(
                    role="user",
                    content="请记住：不要擅自推送 github，需要获得许可再推送。",
                    created_at="2026-05-20T10:01:00+00:00",
                ),
                types.SimpleNamespace(
                    role="assistant",
                    content="记住了",
                    created_at="2026-05-20T10:01:05+00:00",
                ),
            ],
        )

        context = build_cross_session_memory_context("new", store=store)

        assert "[长期记忆]" in context
        assert "不要擅自推送 github，需要获得许可再推送" in context
        assert "历史会话 2026-05-20" in context

    def test_cross_session_memory_context_scans_full_long_sessions(self):
        session = types.SimpleNamespace(session_id="long", created_at="2026-05-20T10:00:00+00:00")
        old_memory = types.SimpleNamespace(
            role="user",
            content="请记住：以后不要擅自推送 GitHub，必须先获得许可。",
            created_at="2026-05-20T10:01:00+00:00",
        )
        later_messages = [
            types.SimpleNamespace(
                role="user",
                content=f"普通后续消息 {index}",
                created_at=f"2026-05-20T10:{index % 60:02d}:00+00:00",
            )
            for index in range(100)
        ]
        requested_limits: list[int] = []

        def load_messages(_session_id, limit=80):
            requested_limits.append(limit)
            messages = [old_memory, *later_messages]
            return messages if limit <= 0 else messages[-limit:]

        store = types.SimpleNamespace(
            list_sessions=lambda limit=80: [session],
            load_messages=load_messages,
        )

        context = build_cross_session_memory_context("new", store=store)

        assert requested_limits == [0]
        assert "不要擅自推送 GitHub，必须先获得许可" in context

    def test_format_environment_context_includes_local_time_period(self):
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 4, 27, 15, 20, tzinfo=local_tz)

        context = format_environment_context(now)

        assert "[当前环境]" in context
        assert "当前本地时间：2026-04-27 15:20:00" in context
        assert "UTC" in context
        assert "星期一" in context
        assert "下午" in context

    def test_format_persona_description_places_environment_first(self):
        wrapped = format_persona_description(
            "帮我总结",
            "你是八千代。",
            "老师",
            "[当前环境]\n当前本地时间：2026-04-27 15:20:00（UTC+09:00，星期一，下午）",
        )

        assert wrapped.index("[当前环境]") < wrapped.index("[人设设定]")
        assert wrapped.index("[人设设定]") < wrapped.index("[用户称呼]")
        assert wrapped.index("[用户称呼]") < wrapped.index("[用户请求]")

    def test_parse_oha_delegation_request(self):
        request = executor_mod._parse_oha_delegation_request(
            '{"action":"run_oha_agent","agent":"Research Agent","goal":"核对事实"}'
        )
        directive = executor_mod._parse_oha_delegation_directive(
            '{"action":"run_oha_agent","agent":"Research Agent","goal":"核对事实"}'
        )

        assert request == {
            "kind": "agent",
            "name": "Research Agent",
            "runnable_id": "",
            "goal": "核对事实",
        }
        assert directive == executor_mod.DelegationDirective(
            kind="agent",
            name="Research Agent",
            runnable_id="",
            goal="核对事实",
        )
        assert directive.target_label == "Research Agent"
        assert directive.as_request() == request
        assert executor_mod._parse_oha_delegation_request(
            '{"action":"run_yachiyo_agent","agent":"Legacy Agent","goal":"旧协议"}'
        ) is None
        assert executor_mod._parse_oha_delegation_request(
            '<yachiyo_delegation>{"action":"run_oha_agent","agent":"Legacy Agent","goal":"旧标签"}</yachiyo_delegation>'
        ) is None

    def test_parse_oha_delegation_request_accepts_model_field_variants(self):
        agent_request = executor_mod._parse_oha_delegation_request(
            "<oha_delegation>"
            "{”type”:”agent”,”agentName”:”Research Agent”,”userGoal”:”核对事实”}"
            "</oha_delegation>"
        )
        workflow_request = executor_mod._parse_oha_delegation_request(
            "我会先跑流程："
            '{"note":"先说明一下"}'
            '{"kind":"workflow","runnableId":"workflow_release","objective":"执行发布检查"}'
        )

        assert agent_request == {
            "kind": "agent",
            "name": "Research Agent",
            "runnable_id": "",
            "goal": "核对事实",
        }
        assert workflow_request == {
            "kind": "workflow",
            "name": "",
            "runnable_id": "workflow_release",
            "goal": "执行发布检查",
        }

    def test_run_oha_delegation_accepts_structured_directive(self, monkeypatch):
        calls: list[dict[str, str]] = []

        class FakeService:
            def delegate_runnable(self, **kwargs):
                calls.append(kwargs)
                return {"ok": True, "status": "completed", "result": "done"}

        monkeypatch.setattr(
            "apps.shell.agent_runtime.get_agent_runtime_service",
            lambda: FakeService(),
        )
        directive = executor_mod.DelegationDirective(
            kind="workflow",
            runnable_id="workflow_release",
            goal="执行发布检查",
        )

        result = executor_mod._run_oha_delegation(directive)

        assert result["ok"] is True
        assert calls == [
            {
                "kind": "workflow",
                "name": "",
                "runnable_id": "workflow_release",
                "user_goal": "执行发布检查",
            }
        ]

    def test_format_oha_delegation_result_includes_pending_approval(self):
        result = executor_mod._format_oha_delegation_result({
            "ok": False,
            "runnable": {"kind": "agent", "name": "Coding Agent"},
            "run_id": "agent_run_waiting",
            "status": "approval_required",
            "result": "",
            "pending_approval": {
                "tool": "terminal.run",
                "input_preview": {"command": "python3 fibonacci.py 5"},
            },
        })

        assert "Status: approval_required" in result
        assert "Pending approval:" in result
        assert "- Tool: terminal.run" in result
        assert "python3 fibonacci.py 5" in result

class TestGeneratedTitle:
    def test_generated_title_is_sanitized_and_limited(self):
        assert _sanitize_generated_session_title("标题：潮汕牛肉饭。") == "潮汕牛肉饭"
        assert _sanitize_generated_session_title("“重复播放 Ray 版本”") == "重复播放 Ray 版本"
        assert len(_sanitize_generated_session_title("这是一个非常非常非常非常非常长的标题需要被截断")) <= 28
        assert _sanitize_generated_session_title("首先，用户要求为这段持续对话生成一个会话列表标题。") == ""

    @pytest.mark.asyncio
    async def test_generated_title_uses_direct_api_without_external_kernel_fallback(self, monkeypatch):
        async def fake_direct_api(_prompt, *, timeout):
            assert timeout > 0
            return ""

        monkeypatch.setattr(executor_mod, "generate_title_with_direct_api", fake_direct_api)

        assert await executor_mod._generate_session_title("生成标题") == ""

    def test_generated_title_refresh_is_periodic(self, monkeypatch):
        monkeypatch.setenv("OHA_YACHIYO_TITLE_GENERATION", "1")
        monkeypatch.setenv("OHA_YACHIYO_TITLE_INTERVAL_TURNS", "2")
        session = ChatSession(session_id="title-test")

        session.add_user_message("第一轮")
        assert _should_refresh_generated_title(session) is False

        session.upsert_assistant_message("t1", "回复", MessageStatus.COMPLETED)
        assert _should_refresh_generated_title(session) is False

        session.add_user_message("第二轮")
        assert _should_refresh_generated_title(session) is False

        session.upsert_assistant_message("t2", "回复", MessageStatus.COMPLETED)
        assert _should_refresh_generated_title(session) is True

    def test_generated_title_refresh_counts_pending_completed_reply(self, monkeypatch):
        monkeypatch.setenv("OHA_YACHIYO_TITLE_GENERATION", "1")
        monkeypatch.setenv("OHA_YACHIYO_TITLE_INTERVAL_TURNS", "2")
        session = ChatSession(session_id="title-test")
        session.add_user_message("第一轮")
        session.upsert_assistant_message("t1", "回复", MessageStatus.COMPLETED)
        session.add_user_message("第二轮")

        assert _should_refresh_generated_title(session, assistant_text="第二轮回复") is True

    def test_generated_title_refresh_waits_for_interval_by_default(self, monkeypatch):
        monkeypatch.delenv("OHA_YACHIYO_TITLE_GENERATION", raising=False)
        monkeypatch.delenv("OHA_YACHIYO_TITLE_INTERVAL_TURNS", raising=False)
        monkeypatch.delenv("OHA_YACHIYO_TITLE_INTERVAL_MESSAGES", raising=False)
        session = ChatSession(session_id="title-test")
        session.add_user_message("第一轮")
        session.upsert_assistant_message("t1", "回复", MessageStatus.COMPLETED)
        session.add_user_message("第二轮")
        session.upsert_assistant_message("t2", "回复", MessageStatus.COMPLETED)

        assert _should_refresh_generated_title(session) is False

    def test_generated_title_refresh_repairs_prompt_echo_before_interval(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OHA_YACHIYO_TITLE_GENERATION", raising=False)
        monkeypatch.delenv("OHA_YACHIYO_TITLE_INTERVAL_TURNS", raising=False)
        monkeypatch.delenv("OHA_YACHIYO_TITLE_INTERVAL_MESSAGES", raising=False)
        store = ChatStore(db_path=str(tmp_path / "chat.db"))
        try:
            session = ChatSession(session_id="title-test")
            session.attach_store(store, load_existing=False)
            session.add_user_message("第一轮")
            store.update_session_title("title-test", "首先，用户要求为这段持续对话生成一个会话列表标题。")

            assert _should_refresh_generated_title(session, assistant_text="第一轮回复") is True
        finally:
            store.close()

    def test_generated_title_prompt_uses_current_title_and_recent_context(self, monkeypatch):
        monkeypatch.setenv("OHA_YACHIYO_TITLE_CONTEXT_MESSAGES", "4")
        session = ChatSession(session_id="title-test")
        session.add_user_message("第一句打招呼")
        session.upsert_assistant_message("t1", "第一轮回复", MessageStatus.COMPLETED)
        session.add_user_message("继续聊 V2EX 热门帖子")

        prompt = _build_session_title_prompt(session, assistant_text="找到一些帖子")

        assert "第一条用户消息：\n第一句打招呼" in prompt
        assert "用户: 继续聊 V2EX 热门帖子" in prompt
        assert "Yachiyo: 找到一些帖子" in prompt

    def test_generated_title_prompt_ignores_prompt_echo_current_title(self, tmp_path):
        store = ChatStore(db_path=str(tmp_path / "chat.db"))
        try:
            session = ChatSession(session_id="title-test")
            session.attach_store(store, load_existing=False)
            session.add_user_message("帮我确认 Chrome 登录态")
            store.update_session_title("title-test", "首先，用户要求为这段持续对话生成一个会话列表标题。")

            prompt = _build_session_title_prompt(session, assistant_text="已经进入后台")

            assert "当前标题：\n暂无" in prompt
            assert "第一条用户消息：\n帮我确认 Chrome 登录态" in prompt
        finally:
            store.close()

    @pytest.mark.asyncio
    async def test_generated_title_refresh_falls_back_from_prompt_echo_title(self, tmp_path, monkeypatch):
        async def fake_generate(_prompt):
            return ""

        monkeypatch.setattr(executor_mod, "_generate_session_title", fake_generate)
        store = ChatStore(db_path=str(tmp_path / "chat.db"))
        try:
            session = ChatSession(session_id="title-test")
            session.attach_store(store, load_existing=False)
            session.add_user_message("帮我确认 Chrome 登录态")
            store.update_session_title("title-test", "首先，用户要求为这段持续对话生成一个会话列表标题。")

            await executor_mod._refresh_session_title_from_recent_messages(session, assistant_text="已经进入后台")

            stored = store.get_session("title-test")
            assert stored is not None
            assert stored.title == "帮我确认 Chrome 登录态"
        finally:
            store.close()
