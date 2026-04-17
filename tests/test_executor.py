"""Executor 测试 — SimulatedExecutor、HermesCallError、HermesInvokeResult"""

import asyncio

import pytest

from apps.core.executor import (
    HermesCallError,
    HermesExecutor,
    HermesInvokeResult,
    SimulatedExecutor,
    _HERMES_CMD,
    _HERMES_FLAGS,
    _parse_bridge_event,
    _parse_hermes_output,
    _parse_hermes_title,
    _resolve_hermes_python,
)
import apps.core.executor as executor_mod
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
