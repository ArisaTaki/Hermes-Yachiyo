"""Executor 测试 — SimulatedExecutor、HermesCallError、HermesInvokeResult"""

import asyncio
import json
from pathlib import Path
import sys
import types

import pytest

from apps.core.executor import (
    HermesCallError,
    HermesExecutor,
    HermesInvokeResult,
    HermesUnavailableExecutor,
    SimulatedExecutor,
    _HERMES_CMD,
    _HERMES_FLAGS,
    _DEFAULT_EXEC_TIMEOUT,
    _humanize_bridge_error,
    _format_exec_timeout,
    format_environment_context,
    _parse_bridge_event,
    _parse_hermes_output,
    _parse_hermes_title,
    _read_exec_timeout,
    _resolve_hermes_python,
    _build_session_title_prompt,
    _sanitize_generated_session_title,
    _should_refresh_generated_title,
    build_cross_session_memory_context,
    resolve_hermes_stream_bridge_script,
    select_executor,
    format_persona_description,
)
import apps.core.executor as executor_mod
import apps.core.hermes_stream_bridge as bridge_mod
from apps.core.chat_session import ChatSession, MessageStatus
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


class TestHermesExecutionTimeout:
    def test_default_timeout_allows_agent_work(self, monkeypatch):
        monkeypatch.delenv("HERMES_YACHIYO_EXEC_TIMEOUT_SECONDS", raising=False)

        assert _DEFAULT_EXEC_TIMEOUT == 30 * 60.0
        assert _read_exec_timeout() == _DEFAULT_EXEC_TIMEOUT
        assert _format_exec_timeout(_DEFAULT_EXEC_TIMEOUT) == "30min"

    def test_exec_timeout_env_override(self, monkeypatch):
        monkeypatch.setenv("HERMES_YACHIYO_EXEC_TIMEOUT_SECONDS", "120")

        assert _read_exec_timeout() == 120.0
        assert _format_exec_timeout(120.0) == "2min"

    def test_invalid_exec_timeout_uses_default(self, monkeypatch):
        monkeypatch.setenv("HERMES_YACHIYO_EXEC_TIMEOUT_SECONDS", "bad")

        assert _read_exec_timeout() == _DEFAULT_EXEC_TIMEOUT


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


class TestHermesUnavailableExecutor:
    @pytest.mark.asyncio
    async def test_run_fails_without_simulated_result(self):
        executor = HermesUnavailableExecutor("Hermes Agent 当前不可用")

        with pytest.raises(HermesCallError) as excinfo:
            await executor.run(_make_task("测试任务"))

        assert "Hermes Agent 当前不可用" in str(excinfo.value)
        assert "[模拟结果]" not in excinfo.value.to_error_string()

    def test_select_executor_returns_unavailable_when_runtime_not_ready(self):
        runtime = types.SimpleNamespace(
            is_hermes_ready=lambda: False,
            hermes_install_info=types.SimpleNamespace(
                status="not_installed",
                error_message="missing hermes",
            ),
        )

        executor = select_executor(runtime)

        assert isinstance(executor, HermesUnavailableExecutor)
        assert "missing hermes" in executor.reason


class TestHermesExecutor:
    def test_set_chat_session_updates_reference(self):
        executor = HermesExecutor()
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

    @pytest.mark.asyncio
    async def test_call_hermes_injects_user_address(self, monkeypatch):
        captured: dict[str, str] = {}

        async def fake_invoke(description, **_kwargs):
            captured["description"] = description
            return HermesInvokeResult(success=True, stdout="ok")

        monkeypatch.setattr(executor_mod, "invoke_hermes_cli", fake_invoke)
        executor = HermesExecutor(
            persona_prompt_getter=lambda: "你是八千代。",
            user_address_getter=lambda: "老师",
        )

        result = await executor._call_hermes(_make_task("帮我总结"))

        assert result == "ok"
        assert "[当前环境]" in captured["description"]
        assert "当前本地时间" in captured["description"]
        assert "[人设设定]\n你是八千代。" in captured["description"]
        assert "[用户称呼]\n请称呼用户为：老师" in captured["description"]
        assert captured["description"].endswith("帮我总结")

    @pytest.mark.asyncio
    async def test_call_hermes_passes_image_attachments(self, monkeypatch, tmp_path):
        image_path = tmp_path / "screen.png"
        image_path.write_bytes(b"png")
        captured: dict[str, list[str]] = {}

        async def fake_invoke(_description, **kwargs):
            captured["image_paths"] = kwargs["image_paths"]
            return HermesInvokeResult(success=True, stdout="ok")

        monkeypatch.setattr(executor_mod, "invoke_hermes_cli", fake_invoke)
        executor = HermesExecutor()

        result = await executor._call_hermes(_make_task(
            "看图",
            attachments=[{"kind": "image", "path": str(image_path)}],
        ))

        assert result == "ok"
        assert captured["image_paths"] == [str(image_path)]


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

    def test_generated_title_is_sanitized_and_limited(self):
        assert _sanitize_generated_session_title("标题：潮汕牛肉饭。") == "潮汕牛肉饭"
        assert _sanitize_generated_session_title("“重复播放 Ray 版本”") == "重复播放 Ray 版本"
        assert len(_sanitize_generated_session_title("这是一个非常非常非常非常非常长的标题需要被截断")) <= 28
        assert _sanitize_generated_session_title("首先，用户要求为这段持续对话生成一个会话列表标题。") == ""

    @pytest.mark.asyncio
    async def test_generated_title_uses_direct_api_without_hermes_cli_fallback(self, monkeypatch):
        async def fake_direct_api(_prompt, *, timeout):
            assert timeout > 0
            return ""

        monkeypatch.setattr(executor_mod, "generate_title_with_direct_api", fake_direct_api)
        monkeypatch.setattr(executor_mod.shutil, "which", lambda _cmd: "/bin/hermes")
        monkeypatch.setattr(executor_mod, "_generate_session_title_with_hermes_cli", lambda _prompt: "不应调用")

        assert await executor_mod._generate_session_title("生成标题") == ""

    def test_generated_title_refresh_is_periodic(self, monkeypatch):
        monkeypatch.setenv("HERMES_YACHIYO_TITLE_GENERATION", "1")
        monkeypatch.setenv("HERMES_YACHIYO_TITLE_INTERVAL_TURNS", "2")
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
        monkeypatch.setenv("HERMES_YACHIYO_TITLE_GENERATION", "1")
        monkeypatch.setenv("HERMES_YACHIYO_TITLE_INTERVAL_TURNS", "2")
        session = ChatSession(session_id="title-test")
        session.add_user_message("第一轮")
        session.upsert_assistant_message("t1", "回复", MessageStatus.COMPLETED)
        session.add_user_message("第二轮")

        assert _should_refresh_generated_title(session, assistant_text="第二轮回复") is True

    def test_generated_title_refresh_waits_for_interval_by_default(self, monkeypatch):
        monkeypatch.delenv("HERMES_YACHIYO_TITLE_GENERATION", raising=False)
        monkeypatch.delenv("HERMES_YACHIYO_TITLE_INTERVAL_TURNS", raising=False)
        monkeypatch.delenv("HERMES_YACHIYO_TITLE_INTERVAL_MESSAGES", raising=False)
        session = ChatSession(session_id="title-test")
        session.add_user_message("第一轮")
        session.upsert_assistant_message("t1", "回复", MessageStatus.COMPLETED)
        session.add_user_message("第二轮")
        session.upsert_assistant_message("t2", "回复", MessageStatus.COMPLETED)

        assert _should_refresh_generated_title(session) is False

    def test_generated_title_refresh_repairs_prompt_echo_before_interval(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HERMES_YACHIYO_TITLE_GENERATION", raising=False)
        monkeypatch.delenv("HERMES_YACHIYO_TITLE_INTERVAL_TURNS", raising=False)
        monkeypatch.delenv("HERMES_YACHIYO_TITLE_INTERVAL_MESSAGES", raising=False)
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
        monkeypatch.setenv("HERMES_YACHIYO_TITLE_CONTEXT_MESSAGES", "4")
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


class TestHermesStreamBridgeHelpers:
    def test_utf8_subprocess_env_repairs_sparse_gui_locale(self, monkeypatch):
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("LANG", "C")
        monkeypatch.delenv("LC_CTYPE", raising=False)
        monkeypatch.setattr(executor_mod.sys, "platform", "darwin")

        env = executor_mod._utf8_subprocess_env()

        assert env["PYTHONUTF8"] == "1"
        assert env["PYTHONIOENCODING"] == "utf-8"
        assert env["LANG"] == "en_US.UTF-8"
        assert env["LC_CTYPE"] == "UTF-8"
        assert "LC_ALL" not in env

    def test_stream_bridge_repairs_sparse_gui_locale(self, monkeypatch):
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("LANG", "C")
        monkeypatch.delenv("LC_CTYPE", raising=False)
        monkeypatch.setattr(bridge_mod.sys, "platform", "darwin")

        bridge_mod._configure_utf8_stdio()

        assert bridge_mod.os.environ["PYTHONUTF8"] == "1"
        assert bridge_mod.os.environ["PYTHONIOENCODING"] == "utf-8"
        assert bridge_mod.os.environ["LANG"] == "en_US.UTF-8"
        assert bridge_mod.os.environ["LC_CTYPE"] == "UTF-8"
        assert "LC_ALL" not in bridge_mod.os.environ

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

    def test_resolve_hermes_python_from_env_shebang(self, tmp_path):
        launcher = tmp_path / "hermes"
        launcher.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

        resolved = _resolve_hermes_python(str(launcher))

        assert resolved
        assert Path(resolved).name.startswith("python")

    def test_resolve_hermes_python_rejects_env_bash_wrapper(self, tmp_path):
        launcher = tmp_path / "hermes"
        launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

        assert _resolve_hermes_python(str(launcher)) is None

    def test_resolve_hermes_python_from_bash_wrapper_exec_target(self, tmp_path):
        venv_bin = tmp_path / "hermes-agent" / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        py = venv_bin / "python3"
        py.write_text("", encoding="utf-8")
        target = venv_bin / "hermes"
        target.write_text(f"#!{py}\n", encoding="utf-8")
        launcher = tmp_path / "hermes"
        launcher.write_text(
            "#!/usr/bin/env bash\n"
            "unset PYTHONPATH\n"
            f"exec \"{target}\" \"$@\"\n",
            encoding="utf-8",
        )

        assert _resolve_hermes_python(str(launcher)) == str(py)

    def test_resolve_hermes_python_searches_path_for_command_name(self, tmp_path, monkeypatch):
        py = tmp_path / "python"
        py.write_text("", encoding="utf-8")
        launcher = tmp_path / "hermes"
        launcher.write_text(f"#!{py}\n", encoding="utf-8")
        launcher.chmod(0o755)
        monkeypatch.setenv("PATH", str(tmp_path))

        assert _resolve_hermes_python("hermes") == str(py)

    def test_resolve_stream_bridge_script_prefers_pyinstaller_meipass(self, monkeypatch, tmp_path):
        bridge = tmp_path / "apps" / "core" / "hermes_stream_bridge.py"
        bridge.parent.mkdir(parents=True)
        bridge.write_text("# bridge", encoding="utf-8")
        monkeypatch.setattr(executor_mod.sys, "_MEIPASS", str(tmp_path), raising=False)

        assert resolve_hermes_stream_bridge_script() == bridge

    @pytest.mark.asyncio
    async def test_invoke_falls_back_to_cli_when_stream_bridge_unavailable(
        self,
        monkeypatch,
        tmp_path,
    ):
        image_path = tmp_path / "screen.png"
        image_path.write_bytes(b"png")

        async def fake_stream_bridge(description, hermes_session_id, on_update, **_kwargs):
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
            assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
            assert kwargs["env"]["PYTHONUTF8"] == "1"
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

        result = await executor_mod.invoke_hermes_cli(
            "hello",
            on_update=updates.append,
            image_paths=[str(image_path)],
        )

        assert result.success is True
        assert result.output == "fallback output"
        assert result.hermes_session_id == "fallback_sess"
        assert len(calls) == 1
        assert calls[0][:3] == tuple(_HERMES_CMD)
        assert any("hello" in part for part in calls[0])
        assert any("可以继续调用" in part for part in calls[0])
        assert not any("不要调用桌面截图" in part for part in calls[0])
        assert "--image" in calls[0]
        assert str(image_path) in calls[0]
        assert updates == []

    @pytest.mark.asyncio
    async def test_stream_bridge_uses_utf8_environment(self, monkeypatch, tmp_path):
        bridge_script = tmp_path / "hermes_stream_bridge.py"
        bridge_script.write_text("# bridge", encoding="utf-8")
        captured_kwargs = {}

        async def fake_create_subprocess_exec(*_cmd, **kwargs):
            captured_kwargs.update(kwargs)
            raise RuntimeError("boom")

        monkeypatch.setattr(executor_mod, "_resolve_hermes_python", lambda: sys.executable)
        monkeypatch.setattr(executor_mod, "_BRIDGE_SCRIPT", bridge_script)
        monkeypatch.setattr(
            executor_mod.asyncio,
            "create_subprocess_exec",
            fake_create_subprocess_exec,
        )

        result = await executor_mod._invoke_hermes_stream_bridge("hello", None, lambda _: None)

        assert result.success is False
        assert captured_kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        assert captured_kwargs["env"]["PYTHONUTF8"] == "1"

    @pytest.mark.asyncio
    async def test_invoke_does_not_fallback_for_task_level_stream_failure(
        self,
        monkeypatch,
    ):
        async def fake_stream_bridge(description, hermes_session_id, on_update, **_kwargs):
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

    @pytest.mark.asyncio
    async def test_invoke_falls_back_when_stream_bridge_process_crashes_with_partial_output(
        self,
        monkeypatch,
    ):
        async def fake_stream_bridge(description, hermes_session_id, on_update, **_kwargs):
            on_update("partial")
            return HermesInvokeResult(
                success=False,
                stdout="partial",
                stderr="Traceback...\nRuntimeError: bridge crashed",
                returncode=1,
                error_message=(
                    "Hermes streaming bridge 执行失败（exit=1）\n"
                    "RuntimeError: bridge crashed"
                ),
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
        assert updates == ["partial"]


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

    def _make_proc_from_lines(
        self,
        lines: list[str],
        *,
        returncode: int = 0,
        stderr: str = "",
        hang_after_output: bool = False,
    ):
        """构造一个返回指定行序列的假进程。"""
        encoded = b"\n".join(line.encode() for line in lines) + b"\n"
        stderr_encoded = stderr.encode()

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
                chunk = self._data[self._pos :]
                self._pos = len(self._data)
                return chunk

        class FakeStdin:
            def write(self, data: bytes): pass
            async def drain(self): pass
            def close(self): pass

        class FakeProc:
            stdin = FakeStdin()

            def __init__(self, stdout_data: bytes):
                self.returncode = None if hang_after_output else returncode
                self.stdout = FakeStream(stdout_data)
                self.stderr = FakeStream(stderr_encoded)
                self._exit_event = asyncio.Event()

            async def wait(self) -> int:
                if self.returncode is None:
                    await self._exit_event.wait()
                return self.returncode if self.returncode is not None else returncode

            def terminate(self) -> None:
                self.returncode = returncode
                self._exit_event.set()

            def kill(self) -> None:
                self.returncode = returncode
                self._exit_event.set()

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
    async def test_partial_done_response_does_not_discard_streamed_answer(self):
        """done.response 若只是流式完整回复的尾部，不应覆盖已流出的前文。"""
        lines = [
            json.dumps({"type": "delta", "delta": "第一问：完整回答。\n\n"}),
            json.dumps({"type": "delta", "delta": "第二问：完整回答。\n\n"}),
            json.dumps({"type": "delta", "delta": "第三问：完整回答。"}),
            json.dumps({"type": "done", "response": "第二问：完整回答。\n\n第三问：完整回答。", "session_id": "s-partial"}),
        ]
        proc = self._make_proc_from_lines(lines)
        updates = []

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            updates.append,
        )

        assert result.success is True
        assert result.stdout == "第一问：完整回答。\n\n第二问：完整回答。\n\n第三问：完整回答。"

    @pytest.mark.asyncio
    async def test_activity_event_is_forwarded_without_affecting_tokens(self):
        """activity 事件应独立转发，不污染 assistant token 流。"""
        lines = [
            json.dumps({"type": "delta", "delta": "hello"}),
            json.dumps({"type": "activity", "phase": "tool_start", "tool_name": "terminal", "title": "正在运行脚本"}),
            json.dumps({"type": "done", "response": "hello", "session_id": "s-activity"}),
        ]
        proc = self._make_proc_from_lines(lines)
        updates = []
        activities = []

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            updates.append,
            activities.append,
        )

        assert result.success is True
        assert updates == ["hello"]
        assert activities == [{"type": "activity", "phase": "tool_start", "tool_name": "terminal", "title": "正在运行脚本"}]

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
    async def test_done_event_finishes_even_if_bridge_process_hangs(self, monkeypatch):
        """done 事件已经给出最终回复时，不再让子进程清理卡住聊天完成态。"""
        monkeypatch.setattr(executor_mod, "_STREAM_BRIDGE_DONE_EXIT_GRACE", 0.01)
        lines = [
            json.dumps({"type": "done", "response": "已经完成", "session_id": "s-done"}),
        ]
        proc = self._make_proc_from_lines(lines, hang_after_output=True)

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            lambda _: None,
        )

        assert result.success is True
        assert result.stdout == "已经完成"
        assert result.hermes_session_id == "s-done"

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

    @pytest.mark.asyncio
    async def test_process_exit_failure_uses_stderr_summary(self):
        """bridge 无 error 事件但进程失败时，应把 stderr 摘要放进错误消息。"""
        proc = self._make_proc_from_lines(
            [],
            returncode=1,
            stderr=(
                "Traceback (most recent call last):\n"
                "  File \"bridge.py\", line 1, in <module>\n"
                "RuntimeError: bridge crashed"
            ),
        )

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            lambda _: None,
        )

        assert result.success is False
        assert "Hermes streaming bridge 执行失败（exit=1）" in result.error_message
        assert "RuntimeError: bridge crashed" in result.error_message

    @pytest.mark.asyncio
    async def test_done_failed_uses_response_as_task_error(self):
        """done.failed 是 agent 层失败，不应伪装成 bridge 进程崩溃。"""
        lines = [
            json.dumps({"type": "done", "response": "模型请求失败", "failed": True}),
        ]
        proc = self._make_proc_from_lines(lines, returncode=1)

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            lambda _: None,
        )

        assert result.success is False
        assert "Hermes 对话执行失败" in result.error_message
        assert "模型请求失败" in result.error_message
        assert "Hermes streaming bridge 执行失败" not in result.error_message

    @pytest.mark.asyncio
    async def test_done_failed_uses_error_field_before_empty_response(self):
        """done.failed 的 error 字段应优先于空响应。"""
        lines = [
            json.dumps(
                {
                    "type": "done",
                    "response": "None",
                    "error": "provider api key missing",
                    "failed": True,
                }
            ),
        ]
        proc = self._make_proc_from_lines(lines, returncode=1)

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            lambda _: None,
        )

        assert result.success is False
        assert "provider api key missing" in result.error_message
        assert "：None" not in result.error_message

    @pytest.mark.asyncio
    async def test_done_failed_without_detail_guides_configuration_check(self):
        """Hermes 返回 failed=True 但没有错误详情时，应给出配置排查提示。"""
        lines = [
            json.dumps({"type": "done", "response": "None", "failed": True}),
        ]
        proc = self._make_proc_from_lines(lines, returncode=1)

        result = await executor_mod._consume_stream_bridge(
            proc,  # type: ignore[arg-type]
            {"description": "test"},
            lambda _: None,
        )

        assert result.success is False
        assert "没有返回错误详情" in result.error_message
        assert "模型/provider 配置" in result.error_message
        assert "：None" not in result.error_message


class TestHermesStreamBridgeResultFormatting:
    """bridge 对 Hermes run_conversation 结果的清洗。"""

    def test_detail_text_treats_none_values_as_empty(self):
        assert bridge_mod._detail_text(None) == ""
        assert bridge_mod._detail_text("None") == ""
        assert bridge_mod._detail_text("null") == ""
        assert bridge_mod._detail_text("None", drop_empty_literals=False) == "None"

    def test_failure_message_prefers_explicit_error_fields(self):
        result = {
            "failed": True,
            "final_response": None,
            "error": "",
            "message": "model route is invalid",
        }

        assert bridge_mod._failure_message_from_result(result) == "model route is invalid"

    def test_failure_message_serializes_structured_details(self):
        result = {
            "failed": True,
            "details": {"provider": "openai", "reason": "missing key"},
        }

        assert "missing key" in bridge_mod._failure_message_from_result(result)


class TestHermesStreamBridgeImageRouting:
    def _install_fake_image_routing(self, monkeypatch, cfg):
        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = []  # type: ignore[attr-defined]
        image_routing = types.ModuleType("agent.image_routing")
        def fake_decide_image_input_mode(_provider, _model, loaded_cfg):
            mode = (loaded_cfg.get("agent") or {}).get("image_input_mode") or "auto"
            return "text" if mode == "text" else "native"

        image_routing.decide_image_input_mode = fake_decide_image_input_mode
        image_routing.build_native_content_parts = lambda text, _paths: ([
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ], [])
        hermes_pkg = types.ModuleType("hermes_cli")
        hermes_pkg.__path__ = []  # type: ignore[attr-defined]
        config_mod = types.ModuleType("hermes_cli.config")
        config_mod.load_config = lambda: cfg
        monkeypatch.setitem(sys.modules, "agent", agent_pkg)
        monkeypatch.setitem(sys.modules, "agent.image_routing", image_routing)
        monkeypatch.setitem(sys.modules, "hermes_cli", hermes_pkg)
        monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)

    def test_xiaomi_native_mode_still_uses_yachiyo_vision_preprocessor(self, monkeypatch, tmp_path):
        self._install_fake_image_routing(monkeypatch, {"agent": {"image_input_mode": "native"}})
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        monkeypatch.setattr(
            bridge_mod,
            "_preprocess_images_with_vision",
            lambda text, images: f"vision::{text}::{len(images)}",
        )

        class FakeCli:
            provider = "xiaomi"
            model = "mimo-v2.5"

        routed = bridge_mod._route_images(FakeCli(), "看图", [image])

        assert routed.startswith("vision::[Yachiyo 附件图片上下文]")
        assert "可以继续调用" in routed
        assert "不要调用桌面截图" not in routed
        assert "看图::1" in routed

    def test_xiaomi_pro_auto_uses_vision_preprocessor(self, monkeypatch, tmp_path):
        self._install_fake_image_routing(monkeypatch, {"agent": {"image_input_mode": "auto"}})
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        monkeypatch.setattr(
            bridge_mod,
            "_preprocess_images_with_vision",
            lambda text, images: f"vision::{text}::{len(images)}",
        )

        class FakeCli:
            provider = "xiaomi"
            model = "mimo-v2.5-pro"

        routed = bridge_mod._route_images(FakeCli(), "看图", [image])

        assert routed.startswith("vision::[Yachiyo 附件图片上下文]")
        assert "看图::1" in routed

    def test_auto_with_auxiliary_vision_uses_vision_preprocessor(self, monkeypatch, tmp_path):
        self._install_fake_image_routing(
            monkeypatch,
            {
                "agent": {"image_input_mode": "auto"},
                "auxiliary": {"vision": {"provider": "xiaomi", "model": "mimo-v2.5-pro"}},
            },
        )
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        monkeypatch.setattr(
            bridge_mod,
            "_preprocess_images_with_vision",
            lambda text, images: f"vision::{text}::{len(images)}",
        )

        class FakeCli:
            provider = "xiaomi"
            model = "mimo-v2.5-pro"

        routed = bridge_mod._route_images(FakeCli(), "看图", [image])

        assert routed.startswith("vision::[Yachiyo 附件图片上下文]")
        assert "看图::1" in routed

    def test_auto_openrouter_uses_yachiyo_vision_preprocessor(self, monkeypatch, tmp_path):
        cache_dir = tmp_path / ".hermes"
        cache_dir.mkdir()
        (cache_dir / "models_dev_cache.json").write_text(
            json.dumps(
                {
                    "openrouter": {
                        "models": {
                            "anthropic/claude-opus-4.6": {
                                "attachment": True,
                                "modalities": {"input": ["text", "image"]},
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(bridge_mod.Path, "home", lambda: tmp_path)

        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = []  # type: ignore[attr-defined]
        image_routing = types.ModuleType("agent.image_routing")
        image_routing.decide_image_input_mode = lambda *_args, **_kwargs: "text"
        image_routing.build_native_content_parts = lambda text, _paths: ([
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ], [])
        hermes_pkg = types.ModuleType("hermes_cli")
        hermes_pkg.__path__ = []  # type: ignore[attr-defined]
        config_mod = types.ModuleType("hermes_cli.config")
        config_mod.load_config = lambda: {
            "model": {
                "provider": "auto",
                "default": "anthropic/claude-opus-4.6",
                "base_url": "https://openrouter.ai/api/v1",
            },
            "agent": {"image_input_mode": "auto"},
        }
        monkeypatch.setitem(sys.modules, "agent", agent_pkg)
        monkeypatch.setitem(sys.modules, "agent.image_routing", image_routing)
        monkeypatch.setitem(sys.modules, "hermes_cli", hermes_pkg)
        monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)

        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        monkeypatch.setattr(
            bridge_mod,
            "_preprocess_images_with_vision",
            lambda text, images: f"vision::{text}::{len(images)}",
        )

        class FakeCli:
            provider = "auto"
            model = "anthropic/claude-opus-4.6"

        routed = bridge_mod._route_images(FakeCli(), "看图", [image])

        assert routed.startswith("vision::[Yachiyo 附件图片上下文]")
        assert "看图::1" in routed

    def test_text_mode_uses_vision_preprocessor(self, monkeypatch, tmp_path):
        self._install_fake_image_routing(monkeypatch, {"agent": {"image_input_mode": "text"}})
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        monkeypatch.setattr(
            bridge_mod,
            "_preprocess_images_with_vision",
            lambda text, images: f"vision::{text}::{len(images)}",
        )

        class FakeCli:
            provider = "xiaomi"
            model = "mimo-v2.5-pro"

        routed = bridge_mod._route_images(FakeCli(), "看图", [image])

        assert routed.startswith("vision::[Yachiyo 附件图片上下文]")
        assert "可以继续调用" in routed
        assert "不要调用桌面截图" not in routed
        assert "看图::1" in routed

    def test_text_mode_overrides_native_decision_for_text_provider(self, monkeypatch, tmp_path):
        self._install_fake_image_routing(monkeypatch, {"agent": {"image_input_mode": "text"}})
        import agent.image_routing as image_routing

        image_routing.decide_image_input_mode = lambda *_args, **_kwargs: "native"
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        monkeypatch.setattr(
            bridge_mod,
            "_preprocess_images_with_vision",
            lambda text, images: f"vision::{text}::{len(images)}",
        )

        class FakeCli:
            provider = "deepseek"
            model = "deepseek-chat"

        routed = bridge_mod._route_images(FakeCli(), "看图", [image])

        assert routed.startswith("vision::[Yachiyo 附件图片上下文]")
        assert "看图::1" in routed

    def test_strict_vision_preprocessor_does_not_emit_tool_retry_hint(self, monkeypatch, tmp_path):
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        monkeypatch.setattr(
            bridge_mod,
            "_configured_auxiliary_vision_override",
            lambda: {"model": "vision-model", "base_url": "https://vision.example/v1", "api_key": "test-key"},
        )

        async def fake_run_direct_vision_analysis(*_args, **_kwargs):
            return "一张图片"

        monkeypatch.setattr(bridge_mod, "_run_direct_vision_analysis", fake_run_direct_vision_analysis)

        routed = bridge_mod._preprocess_images_with_vision("请看图", [image])

        assert "一张图片" in routed
        assert "请看图" in routed
        assert "vision_analyze" not in routed

    def test_strict_vision_preprocessor_raises_on_failed_analysis(self, monkeypatch, tmp_path):
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        monkeypatch.setattr(
            bridge_mod,
            "_configured_auxiliary_vision_override",
            lambda: {"model": "vision-model", "base_url": "https://vision.example/v1", "api_key": "test-key"},
        )

        async def fake_run_direct_vision_analysis(*_args, **_kwargs):
            raise RuntimeError("missing key")

        monkeypatch.setattr(bridge_mod, "_run_direct_vision_analysis", fake_run_direct_vision_analysis)

        with pytest.raises(bridge_mod.ImagePreprocessError, match="missing key"):
            bridge_mod._preprocess_images_with_vision("请看图", [image])

    def test_xiaomi_text_model_vision_fallback_inherits_configured_base_url(self, monkeypatch, tmp_path):
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        captured = {}

        hermes_pkg = types.ModuleType("hermes_cli")
        hermes_pkg.__path__ = []  # type: ignore[attr-defined]
        config_mod = types.ModuleType("hermes_cli.config")
        config_mod.load_config = lambda: {
            "model": {
                "provider": "xiaomi",
                "default": "mimo-v2-pro",
                "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            }
        }
        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = []  # type: ignore[attr-defined]
        auxiliary_mod = types.ModuleType("agent.auxiliary_client")
        auxiliary_mod.resolve_provider_client = lambda *_args, **_kwargs: (
            types.SimpleNamespace(api_key="tp-test"),
            "mimo-v2.5-pro",
        )

        async def fake_async_call_llm(**kwargs):
            captured.update(kwargs)
            return object()

        auxiliary_mod.async_call_llm = fake_async_call_llm
        auxiliary_mod.extract_content_or_reasoning = lambda _response: "一张图片"

        tools_pkg = types.ModuleType("tools")
        tools_pkg.__path__ = []  # type: ignore[attr-defined]
        vision_mod = types.ModuleType("tools.vision_tools")
        vision_mod._MAX_BASE64_BYTES = 20_000_000
        vision_mod._RESIZE_TARGET_BYTES = 5_000_000
        vision_mod._detect_image_mime_type = lambda _path: "image/png"
        vision_mod._image_to_base64_data_url = lambda _path, mime_type: f"data:{mime_type};base64,AAAA"
        vision_mod._resize_image_for_vision = lambda _path, mime_type: f"data:{mime_type};base64,BBBB"
        vision_mod._is_image_size_error = lambda _exc: False

        monkeypatch.setitem(sys.modules, "hermes_cli", hermes_pkg)
        monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)
        monkeypatch.setitem(sys.modules, "agent", agent_pkg)
        monkeypatch.setitem(sys.modules, "agent.auxiliary_client", auxiliary_mod)
        monkeypatch.setitem(sys.modules, "tools", tools_pkg)
        monkeypatch.setitem(sys.modules, "tools.vision_tools", vision_mod)

        result = bridge_mod._run_vision_analysis(image, "请看图")

        assert result == "一张图片"
        assert captured["provider"] == "custom"
        assert captured["model"] == "mimo-v2.5"
        assert captured["base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"
        assert captured["api_key"] == "tp-test"

    def test_auxiliary_vision_config_uses_configured_provider(self, monkeypatch, tmp_path):
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        captured = {}

        hermes_pkg = types.ModuleType("hermes_cli")
        hermes_pkg.__path__ = []  # type: ignore[attr-defined]
        config_mod = types.ModuleType("hermes_cli.config")
        config_mod.load_config = lambda: {
            "model": {
                "provider": "deepseek",
                "default": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
            },
            "auxiliary": {
                "vision": {
                    "provider": "xiaomi",
                    "model": "mimo-v2.5",
                    "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                }
            },
        }
        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = []  # type: ignore[attr-defined]
        auxiliary_mod = types.ModuleType("agent.auxiliary_client")
        auxiliary_mod.resolve_provider_client = lambda provider, model: (
            types.SimpleNamespace(api_key=f"{provider}-vision-key"),
            model,
        )

        async def fake_async_call_llm(**kwargs):
            captured.update(kwargs)
            return object()

        auxiliary_mod.async_call_llm = fake_async_call_llm
        auxiliary_mod.extract_content_or_reasoning = lambda _response: "辅助视觉结果"

        tools_pkg = types.ModuleType("tools")
        tools_pkg.__path__ = []  # type: ignore[attr-defined]
        vision_mod = types.ModuleType("tools.vision_tools")
        vision_mod._MAX_BASE64_BYTES = 20_000_000
        vision_mod._RESIZE_TARGET_BYTES = 5_000_000
        vision_mod._detect_image_mime_type = lambda _path: "image/png"
        vision_mod._image_to_base64_data_url = lambda _path, mime_type: f"data:{mime_type};base64,AAAA"
        vision_mod._resize_image_for_vision = lambda _path, mime_type: f"data:{mime_type};base64,BBBB"
        vision_mod._is_image_size_error = lambda _exc: False

        monkeypatch.setitem(sys.modules, "hermes_cli", hermes_pkg)
        monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)
        monkeypatch.setitem(sys.modules, "agent", agent_pkg)
        monkeypatch.setitem(sys.modules, "agent.auxiliary_client", auxiliary_mod)
        monkeypatch.setitem(sys.modules, "tools", tools_pkg)
        monkeypatch.setitem(sys.modules, "tools.vision_tools", vision_mod)

        result = bridge_mod._run_vision_analysis(image, "请看图")

        assert result == "辅助视觉结果"
        assert captured["provider"] == "custom"
        assert captured["model"] == "mimo-v2.5"
        assert captured["base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"
        assert captured["api_key"] == "xiaomi-vision-key"

    def test_auxiliary_vision_infers_openrouter_when_provider_is_auto(self, monkeypatch, tmp_path):
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        captured = {}

        hermes_pkg = types.ModuleType("hermes_cli")
        hermes_pkg.__path__ = []  # type: ignore[attr-defined]
        config_mod = types.ModuleType("hermes_cli.config")
        config_mod.load_config = lambda: {
            "model": {
                "provider": "auto",
                "default": "anthropic/claude-opus-4.6",
                "base_url": "https://openrouter.ai/api/v1",
            },
            "auxiliary": {
                "vision": {
                    "provider": "auto",
                    "model": "google/gemini-3-flash-preview",
                }
            },
        }
        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = []  # type: ignore[attr-defined]
        auxiliary_mod = types.ModuleType("agent.auxiliary_client")
        auxiliary_mod.resolve_provider_client = lambda provider, model: (
            types.SimpleNamespace(api_key=f"{provider}-vision-key"),
            model,
        )

        async def fake_async_call_llm(**kwargs):
            captured.update(kwargs)
            return object()

        auxiliary_mod.async_call_llm = fake_async_call_llm
        auxiliary_mod.extract_content_or_reasoning = lambda _response: "OpenRouter 辅助视觉结果"

        tools_pkg = types.ModuleType("tools")
        tools_pkg.__path__ = []  # type: ignore[attr-defined]
        vision_mod = types.ModuleType("tools.vision_tools")
        vision_mod._MAX_BASE64_BYTES = 20_000_000
        vision_mod._RESIZE_TARGET_BYTES = 5_000_000
        vision_mod._detect_image_mime_type = lambda _path: "image/png"
        vision_mod._image_to_base64_data_url = lambda _path, mime_type: f"data:{mime_type};base64,AAAA"
        vision_mod._resize_image_for_vision = lambda _path, mime_type: f"data:{mime_type};base64,BBBB"
        vision_mod._is_image_size_error = lambda _exc: False

        monkeypatch.setitem(sys.modules, "hermes_cli", hermes_pkg)
        monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)
        monkeypatch.setitem(sys.modules, "agent", agent_pkg)
        monkeypatch.setitem(sys.modules, "agent.auxiliary_client", auxiliary_mod)
        monkeypatch.setitem(sys.modules, "tools", tools_pkg)
        monkeypatch.setitem(sys.modules, "tools.vision_tools", vision_mod)

        result = bridge_mod._run_vision_analysis(image, "请看图")

        assert result == "OpenRouter 辅助视觉结果"
        assert captured["provider"] == "custom"
        assert captured["model"] == "google/gemini-3-flash-preview"
        assert captured["base_url"] == "https://openrouter.ai/api/v1"
        assert captured["api_key"] == "openrouter-vision-key"

    def test_auxiliary_xiaomi_vision_config_replaces_text_model(self, monkeypatch, tmp_path):
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        captured = {}

        hermes_pkg = types.ModuleType("hermes_cli")
        hermes_pkg.__path__ = []  # type: ignore[attr-defined]
        config_mod = types.ModuleType("hermes_cli.config")
        config_mod.load_config = lambda: {
            "model": {
                "provider": "deepseek",
                "default": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
            },
            "auxiliary": {
                "vision": {
                    "provider": "xiaomi",
                    "model": "mimo-v2-pro",
                    "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                }
            },
        }
        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = []  # type: ignore[attr-defined]
        auxiliary_mod = types.ModuleType("agent.auxiliary_client")
        auxiliary_mod.resolve_provider_client = lambda provider, model: (
            types.SimpleNamespace(api_key=f"{provider}-vision-key"),
            model,
        )

        async def fake_async_call_llm(**kwargs):
            captured.update(kwargs)
            return object()

        auxiliary_mod.async_call_llm = fake_async_call_llm
        auxiliary_mod.extract_content_or_reasoning = lambda _response: "辅助视觉结果"

        tools_pkg = types.ModuleType("tools")
        tools_pkg.__path__ = []  # type: ignore[attr-defined]
        vision_mod = types.ModuleType("tools.vision_tools")
        vision_mod._MAX_BASE64_BYTES = 20_000_000
        vision_mod._RESIZE_TARGET_BYTES = 5_000_000
        vision_mod._detect_image_mime_type = lambda _path: "image/png"
        vision_mod._image_to_base64_data_url = lambda _path, mime_type: f"data:{mime_type};base64,AAAA"
        vision_mod._resize_image_for_vision = lambda _path, mime_type: f"data:{mime_type};base64,BBBB"
        vision_mod._is_image_size_error = lambda _exc: False

        monkeypatch.setitem(sys.modules, "hermes_cli", hermes_pkg)
        monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)
        monkeypatch.setitem(sys.modules, "agent", agent_pkg)
        monkeypatch.setitem(sys.modules, "agent.auxiliary_client", auxiliary_mod)
        monkeypatch.setitem(sys.modules, "tools", tools_pkg)
        monkeypatch.setitem(sys.modules, "tools.vision_tools", vision_mod)

        result = bridge_mod._run_vision_analysis(image, "请看图")

        assert result == "辅助视觉结果"
        assert captured["model"] == "mimo-v2.5"

    def test_image_turn_preserves_agent_tools_for_pure_image_request(self, tmp_path):
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        agent = types.SimpleNamespace(
            tools=[{"function": {"name": "terminal"}}],
            valid_tool_names={"terminal", "vision_analyze"},
        )

        with bridge_mod._disable_agent_tools_for_image_turn(agent, [image]):
            assert agent.tools == [{"function": {"name": "terminal"}}]
            assert agent.valid_tool_names == {"terminal", "vision_analyze"}

        assert agent.tools == [{"function": {"name": "terminal"}}]
        assert agent.valid_tool_names == {"terminal", "vision_analyze"}

    def test_image_turn_preserves_agent_tools_for_screenshot_policy_request(self, tmp_path):
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")
        agent = types.SimpleNamespace(
            tools=[{"function": {"name": "browser_cdp"}}],
            valid_tool_names={"browser_cdp"},
        )

        with bridge_mod._disable_agent_tools_for_image_turn(agent, [image]):
            assert agent.tools == [{"function": {"name": "browser_cdp"}}]
            assert agent.valid_tool_names == {"browser_cdp"}

    def test_attached_image_guard_allows_agent_tools(self, tmp_path):
        image = tmp_path / "screen.png"
        image.write_bytes(b"png")

        guarded = bridge_mod._with_attached_image_guard(
            "不要截除了 hermes-yachiyo 以外的图，现在思考对策。",
            [image],
        )

        assert "可以继续调用" in guarded
        assert "不要调用桌面截图" not in guarded
        assert "hermes-yachiyo" in guarded

    def test_activity_text_hides_raw_tool_call_drafts(self):
        text = (
            "让我检查 <tool_call><function=browser_cdp>"
            "<parameter=method>Runtime.evaluate</parameter></function></tool_call>"
        )

        redacted = bridge_mod._redact_activity_text(text)

        assert "tool_call" not in redacted
        assert "browser_cdp" not in redacted
        assert "工具调用草稿已隐藏" in redacted


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
