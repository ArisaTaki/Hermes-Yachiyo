"""Executor 测试 — SimulatedExecutor、HermesCallError、HermesInvokeResult"""

import asyncio
import json

import pytest

from apps.core.executor import (
    HermesCallError,
    HermesExecutor,
    HermesInvokeResult,
    SimulatedExecutor,
    _HERMES_CMD,
    _HERMES_FLAGS,
    _humanize_bridge_error,
    _parse_bridge_event,
    _parse_hermes_output,
    _parse_hermes_title,
    _resolve_hermes_python,
    format_persona_description,
)
import apps.core.executor as executor_mod
import apps.core.hermes_stream_bridge as bridge_mod
from packages.protocol.enums import RiskLevel, TaskStatus, TaskType
from packages.protocol.schemas import TaskInfo
from datetime import datetime, timezone


def _make_task(desc: str = "test") -> TaskInfo:
    now = datetime.now(timezone.utc)
    return TaskInfo(
        task_id="test001",
        description=desc,
        task_type=TaskType.GENERAL,
        status=TaskStatus.PENDING,
        risk_level=RiskLevel.LOW,
        created_at=now,
        updated_at=now,
    )


class TestHermesCallError:
    def test_hermes_cmd_uses_chat_subcommand(self):
        """CLI 命令应使用 hermes chat -q 而非 hermes run --prompt"""
        assert _HERMES_CMD == ["hermes", "chat", "-q"]
        assert "-Q" in _HERMES_FLAGS
        assert "--source" in _HERMES_FLAGS
        assert "tool" in _HERMES_FLAGS

    def test_basic_error(self):
        exc = HermesCallError("命令失败")
        assert str(exc) == "命令失败"
        assert exc.returncode == -1
        assert exc.stderr == ""

    def test_with_returncode_and_stderr(self):
        exc = HermesCallError("失败", returncode=1, stderr="error output")
        s = exc.to_error_string()
        assert "失败" in s
        assert "exit=1" in s
        assert "error output" in s

    def test_long_stderr_truncated(self):
        long_stderr = "x" * 200
        exc = HermesCallError("err", stderr=long_stderr)
        s = exc.to_error_string()
        # stderr 截断到 120 字符
        assert len(s) < len(long_stderr) + 50


class TestHermesInvokeResult:
    def test_success_result(self):
        r = HermesInvokeResult(success=True, stdout="ok output", returncode=0)
        assert r.output == "ok output"

    def test_failure_result(self):
        r = HermesInvokeResult(
            success=False,
            stdout="",
            stderr="error",
            returncode=1,
            error_message="执行失败",
        )
        assert r.output == ""
        err = r.to_task_error()
        assert "执行失败" in err
        assert "exit=1" in err

    def test_empty_failure(self):
        r = HermesInvokeResult(success=False)
        assert r.to_task_error() == "未知错误"


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


class TestHermesExecutor:
    def test_set_chat_session_updates_reference(self):
        executor = HermesExecutor()
        session = object()

        executor.set_chat_session(session)  # type: ignore[arg-type]

        assert executor._chat_session is session

    def test_format_persona_description_keeps_empty_prompt_compatible(self):
        assert format_persona_description("原请求", "") == "原请求"

    def test_format_persona_description_wraps_prompt(self):
        wrapped = format_persona_description("帮我总结", "你是八千代。")

        assert "[人设设定]" in wrapped
        assert "你是八千代。" in wrapped
        assert "[用户请求]" in wrapped
        assert wrapped.endswith("帮我总结")


class TestParseHermesOutput:
    def test_parse_with_session_id(self):
        stdout = "ok\n\nsession_id: 20260416_212134_893a8f"
        content, sid = _parse_hermes_output(stdout)
        assert content == "ok"
        assert sid == "20260416_212134_893a8f"

    def test_parse_multiline_content(self):
        stdout = "line1\nline2\nline3\n\nsession_id: abc123"
        content, sid = _parse_hermes_output(stdout)
        assert content == "line1\nline2\nline3"
        assert sid == "abc123"

    def test_parse_no_session_id(self):
        stdout = "just a normal output"
        content, sid = _parse_hermes_output(stdout)
        assert content == "just a normal output"
        assert sid is None

    def test_parse_quiet_output_preserves_code_indentation(self):
        stdout = "```python\n    print('ok')\n```\n\nsession_id: code_sess"
        content, sid = _parse_hermes_output(stdout)
        assert content == "```python\n    print('ok')\n```"
        assert sid == "code_sess"

    def test_parse_empty_output(self):
        content, sid = _parse_hermes_output("")
        assert content == ""
        assert sid is None

    def test_parse_nonquiet_output_strips_hermes_chrome(self):
        stdout = (
            "╭─ $ Hermes ─╮\n"
            "│ Hello from Hermes │\n"
            "╰────────────╯\n"
            "Session: sess_456\n"
            "Title: Greeting summary\n"
            "Duration: 1.2s\n"
        )

        content, sid = _parse_hermes_output(stdout)

        assert content == "Hello from Hermes"
        assert sid == "sess_456"
        assert _parse_hermes_title(stdout) == "Greeting summary"

    def test_parse_deduplicates_repeated_paragraphs(self):
        stdout = (
            "Hi! I'm Hermes.\n\n"
            "Hi! I'm Hermes.\n\n"
            "What would you like to work on today?\n"
            "session_id: sess_dup\n"
        )

        content, sid = _parse_hermes_output(stdout)

        assert content == "Hi! I'm Hermes.\n\nWhat would you like to work on today?"
        assert sid == "sess_dup"

    def test_hermes_invoke_result_with_session_id(self):
        r = HermesInvokeResult(
            success=True, stdout="ok", returncode=0,
            hermes_session_id="sess_123",
            hermes_title="Test title",
        )
        assert r.hermes_session_id == "sess_123"
        assert r.hermes_title == "Test title"
        assert r.output == "ok"


class TestHermesStreamBridgeHelpers:
    def test_parse_bridge_event(self):
        event = _parse_bridge_event('{"type":"delta","delta":"hi"}')
        assert event == {"type": "delta", "delta": "hi"}

    def test_parse_bridge_event_ignores_non_json(self):
        assert _parse_bridge_event("Available Tools") is None

    def test_resolve_hermes_python_from_launcher(self, tmp_path):
        py = tmp_path / "python"
        py.write_text("")
        launcher = tmp_path / "hermes"
        launcher.write_text(f"#!{py}\n")

        assert _resolve_hermes_python(str(launcher)) == str(py)

    @pytest.mark.asyncio
    async def test_invoke_falls_back_to_cli_when_stream_bridge_unavailable(
        self,
        monkeypatch,
    ):
        async def fake_stream_bridge(description, hermes_session_id, on_update):
            return HermesInvokeResult(
                success=False,
                returncode=-1,
                error_message="无法定位 Hermes Python 解释器，不能启用流式 bridge",
            )

        class FakeProcess:
            returncode = 0

            async def communicate(self):
                return (b"fallback output\nsession_id: fallback_sess\n", b"")

        calls = []

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            calls.append(cmd)
            return FakeProcess()

        monkeypatch.setattr(
            executor_mod,
            "_invoke_hermes_stream_bridge",
            fake_stream_bridge,
        )
        monkeypatch.setattr(
            executor_mod.asyncio,
            "create_subprocess_exec",
            fake_create_subprocess_exec,
        )
        updates = []

        result = await executor_mod.invoke_hermes_cli("hello", on_update=updates.append)

        assert result.success is True
        assert result.output == "fallback output"
        assert result.hermes_session_id == "fallback_sess"
        assert len(calls) == 1
        assert calls[0][:3] == tuple(_HERMES_CMD)
        assert "hello" in calls[0]
        assert updates == []

    @pytest.mark.asyncio
    async def test_invoke_does_not_fallback_for_task_level_stream_failure(
        self,
        monkeypatch,
    ):
        async def fake_stream_bridge(description, hermes_session_id, on_update):
            return HermesInvokeResult(
                success=False,
                returncode=1,
                error_message="Hermes runtime credentials are not available",
            )

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            raise AssertionError("non-stream fallback should not run")

        monkeypatch.setattr(
            executor_mod,
            "_invoke_hermes_stream_bridge",
            fake_stream_bridge,
        )
        monkeypatch.setattr(
            executor_mod.asyncio,
            "create_subprocess_exec",
            fake_create_subprocess_exec,
        )

        result = await executor_mod.invoke_hermes_cli("hello", on_update=lambda _: None)

        assert result.success is False
        assert result.error_message == "Hermes runtime credentials are not available"


class TestHumanizeBridgeError:
    """_humanize_bridge_error 把 bridge 原始异常前缀转为用户可读描述。"""

    def test_keyerror_label_is_humanized(self):
        msg = _humanize_bridge_error("KeyError: 'label'")
        assert "KeyError: 'label'" in msg
        assert "Hermes provider 配置字段缺失" in msg
        # 不能原样暴露原始异常给用户
        assert msg != "KeyError: 'label'"

    def test_attribute_error_is_humanized(self):
        msg = _humanize_bridge_error("AttributeError: 'NoneType' object has no attribute 'run'")
        assert "Hermes API 结构不兼容" in msg

    def test_type_error_is_humanized(self):
        msg = _humanize_bridge_error("TypeError: unexpected keyword argument")
        assert "Hermes API 参数不兼容" in msg

    def test_non_exception_message_unchanged(self):
        msg = _humanize_bridge_error("Hermes runtime credentials are not available")
        assert msg == "Hermes runtime credentials are not available"

    def test_empty_message_unchanged(self):
        assert _humanize_bridge_error("") == ""

    def test_unknown_exception_unchanged(self):
        msg = _humanize_bridge_error("ZeroDivisionError: division by zero")
        assert msg == "ZeroDivisionError: division by zero"


class TestConsumeStreamBridgeRobustness:
    """_consume_stream_bridge 对 provider 差异事件结构的鲁棒性测试。"""

    def _make_proc_from_lines(self, lines: list[str]):
        """构造一个返回指定行序列的假进程。"""
        encoded = b"\n".join(line.encode() for line in lines) + b"\n"

        class FakeStream:
            def __init__(self, data: bytes):
                self._data = data
                self._pos = 0

            async def readline(self) -> bytes:
                if self._pos >= len(self._data):
                    return b""
                end = self._data.find(b"\n", self._pos)
                if end == -1:
                    chunk = self._data[self._pos:]
                    self._pos = len(self._data)
                    return chunk
                chunk = self._data[self._pos : end + 1]
                self._pos = end + 1
                return chunk

            async def read(self) -> bytes:
                return b""

        class FakeStdin:
            def write(self, data: bytes): pass
            async def drain(self): pass
            def close(self): pass

        class FakeProc:
            returncode = 0
            stdin = FakeStdin()

            def __init__(self, stdout_data: bytes):
                self.stdout = FakeStream(stdout_data)
                self.stderr = FakeStream(b"")

            async def wait(self) -> int:
                return 0

        return FakeProc(encoded)

    @pytest.mark.asyncio
    async def test_error_event_with_keyerror_label_is_humanized(self):
        """bridge 输出 KeyError: 'label' 时，error_message 应是用户友好描述。"""
        lines = [json.dumps({"type": "error", "message": "KeyError: 'label'"})]
        proc = self._make_proc_from_lines(lines)
        updates = []

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            updates.append,
        )

        assert result.success is False
        assert "KeyError" in result.error_message
        assert "Hermes provider 配置字段缺失" in result.error_message

    @pytest.mark.asyncio
    async def test_unknown_event_type_does_not_crash(self):
        """未知事件类型只记录日志，不崩溃，不影响最终结果。"""
        lines = [
            json.dumps({"type": "unknown_future_event", "data": "something"}),
            json.dumps({"type": "done", "response": "hello world", "session_id": "s1"}),
        ]
        proc = self._make_proc_from_lines(lines)
        updates = []

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            updates.append,
        )

        assert result.success is True
        assert result.stdout == "hello world"

    @pytest.mark.asyncio
    async def test_boundary_event_does_not_affect_result(self):
        """boundary 事件被静默忽略，不产生内容也不导致失败。"""
        lines = [
            json.dumps({"type": "delta", "delta": "partial"}),
            json.dumps({"type": "boundary"}),
            json.dumps({"type": "done", "response": "full response", "session_id": "s2"}),
        ]
        proc = self._make_proc_from_lines(lines)
        updates = []

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            updates.append,
        )

        assert result.success is True
        assert result.stdout == "full response"

    @pytest.mark.asyncio
    async def test_done_event_without_streaming_yields_final_response(self):
        """只有 done 事件（无 delta），应降级为最终完整回复，不失败。"""
        lines = [
            json.dumps({"type": "done", "response": "完整回复", "session_id": "s3"}),
        ]
        proc = self._make_proc_from_lines(lines)

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            lambda _: None,
        )

        assert result.success is True
        assert result.stdout == "完整回复"
        assert result.hermes_session_id == "s3"

    @pytest.mark.asyncio
    async def test_done_event_with_failed_flag_marks_failure(self):
        """done 事件中 failed=True 时，result 应为失败。"""
        lines = [
            json.dumps({"type": "done", "response": "", "failed": True}),
        ]
        proc = self._make_proc_from_lines(lines)

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            lambda _: None,
        )

        assert result.success is False


class TestBuildInitAgentKwargs:
    """_build_init_agent_kwargs 根据 _init_agent 签名动态过滤参数。"""

    def _call(self, fn, **kw):
        from apps.core.hermes_stream_bridge import _build_init_agent_kwargs
        return _build_init_agent_kwargs(fn, **kw)

    def _defaults(self):
        return dict(
            model_override="deepseek",
            runtime_override="openai",
            route_label="my-label",
            request_overrides=None,
        )

    def test_route_label_excluded_when_not_in_signature(self):
        """函数签名无 route_label 时，kwargs 中不应含该键。"""
        def fake_init(self, model_override=None, runtime_override=None):
            pass

        result = self._call(fake_init, **self._defaults())
        assert "route_label" not in result
        assert result.get("model_override") == "deepseek"

    def test_route_label_included_when_in_signature(self):
        """函数签名含 route_label 时，kwargs 中应包含该键。"""
        def fake_init(self, model_override=None, runtime_override=None, route_label=None):
            pass

        result = self._call(fake_init, **self._defaults())
        assert "route_label" in result
        assert result["route_label"] == "my-label"

    def test_request_overrides_excluded_when_not_in_signature(self):
        """函数签名无 request_overrides 时，kwargs 中不应含该键。"""
        def fake_init(self, model_override=None, runtime_override=None):
            pass

        kw = {**self._defaults(), "request_overrides": {"key": "val"}}
        result = self._call(fake_init, **kw)
        assert "request_overrides" not in result

    def test_var_keyword_function_gets_all_nonnull_candidates(self):
        """函数接受 **kwargs 时，所有非 None 候选均可传入。"""
        def fake_init(self, **kwargs):
            pass

        result = self._call(fake_init, **self._defaults())
        assert "model_override" in result
        assert "runtime_override" in result
        assert "route_label" in result

    def test_signature_inspection_failure_returns_safe_defaults(self):
        """inspect.signature 失败时，只返回 model_override 和 runtime_override。"""
        # C 内置函数通常无法获取 Python signature
        result = self._call(len, **self._defaults())
        assert set(result.keys()) <= {"model_override", "runtime_override"}

    def test_route_label_none_excluded_even_when_var_keyword(self):
        """route_label=None 时，即便函数接受 **kwargs，也不传入 None 值。"""
        def fake_init(self, **kwargs):
            pass

        kw = {**self._defaults(), "route_label": None}
        result = self._call(fake_init, **kw)
        assert "route_label" not in result

    def test_error_event_with_route_label_typeerror_is_humanized(self):
        """bridge emit 的 TypeError: route_label 错误消息应被人性化。"""
        msg = _humanize_bridge_error(
            "TypeError: _init_agent() got an unexpected keyword argument 'route_label'"
        )
        assert "Hermes API 参数不兼容" in msg
        assert "route_label" in msg

    def test_debug_route_is_disabled_by_default(self, monkeypatch, capsys):
        """默认不输出 route 诊断日志，避免把配置写入 stderr。"""
        monkeypatch.delenv("HERMES_YACHIYO_DEBUG_ROUTE", raising=False)

        bridge_mod._debug_route({"api_key": "secret-token", "model": "m"})

        assert capsys.readouterr().err == ""

    def test_debug_route_logs_keys_only_when_enabled(self, monkeypatch, capsys):
        """显式开启诊断时只输出 key，不输出敏感 value。"""
        monkeypatch.setenv("HERMES_YACHIYO_DEBUG_ROUTE", "1")

        bridge_mod._debug_route({
            "api_key": "secret-token",
            "endpoint": "https://internal.example",
            "request_overrides": {"Authorization": "Bearer abc"},
        })
        err = capsys.readouterr().err

        assert "api_key" in err
        assert "endpoint" in err
        assert "request_overrides" in err
        assert "secret-token" not in err
        assert "internal.example" not in err
        assert "Bearer abc" not in err
