"""Tests for tool-loop projection helpers split out of the legacy runtime."""

from __future__ import annotations

import json

from apps.shell import agent_runtime
from apps.shell.agent.runtime.tool_loop import (
    RuntimeToolLoopProjectionBuilder,
    append_tool_result_message,
    assistant_message_for_history,
    fatal_tool_failure_detail,
    stage_tool_result_messages,
    tool_loop_limit_artifact_completion,
    tool_loop_limit_detail,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_tool_loop_limit_detail_projects_last_tool_failure() -> None:
    timeline = [
        {"event": "agent.tool.call", "detail": "workspace.read", "result": {"ok": True}},
        {
            "event": "agent.tool.call",
            "detail": "terminal.run",
            "result": {
                "error": "command failed",
                "returncode": 2,
                "hint": "check argv",
                "suggested_tool": "workspace.read",
                "stderr": "ignored when error exists",
            },
        },
    ]

    detail = tool_loop_limit_detail(timeline)

    assert detail == (
        "最后一次工具调用：terminal.run；错误：command failed；退出码：2；"
        "建议：check argv；建议工具：workspace.read"
    )
    assert agent_runtime.NativeRunEngine._tool_loop_limit_detail(timeline) == detail
    assert tool_loop_limit_detail([]) == "没有可用的工具调用详情"


def test_tool_loop_artifact_completion_uses_written_artifacts_and_fallback_path() -> None:
    timeline = [
        {
            "event": "agent.tool.call",
            "detail": "artifact.write",
            "result": {"ok": True, "path": "fallback.md"},
        }
    ]
    artifacts = [
        {"kind": "context", "path": "agent-context.md"},
        {"kind": "report", "path": "report.md"},
        {"kind": "report", "path": "report.md"},
    ]

    completion = tool_loop_limit_artifact_completion(timeline, artifacts)

    assert completion is not None
    assert "已写入产物" in completion
    assert "产物：report.md" in completion
    assert "最后一次工具调用：artifact.write" in completion
    assert agent_runtime.NativeRunEngine._tool_loop_limit_artifact_completion(
        timeline,
        artifacts,
    ) == completion

    fallback_completion = tool_loop_limit_artifact_completion(timeline, [])
    assert fallback_completion is not None
    assert "产物：fallback.md" in fallback_completion
    assert tool_loop_limit_artifact_completion(
        [{"event": "agent.tool.call", "detail": "workspace.read", "result": {"ok": True}}],
        artifacts,
    ) is None


def test_fatal_tool_failure_detail_only_projects_terminal_failures() -> None:
    request = {"input": {"command": "npm test"}}
    result = {
        "ok": False,
        "returncode": 1,
        "error": "failed",
        "stdout": "short stdout",
        "stderr": "short stderr",
    }

    detail = fatal_tool_failure_detail("terminal.run", request, result)

    assert detail == (
        "terminal.run 执行失败；命令：npm test；退出码：1；"
        "错误：failed；stdout：short stdout；stderr：short stderr"
    )
    assert agent_runtime.NativeRunEngine._fatal_tool_failure_detail(
        "terminal.run",
        request,
        result,
    ) == detail
    assert fatal_tool_failure_detail("workspace.read", request, result) == ""
    assert fatal_tool_failure_detail("terminal.run", request, {"ok": True}) == ""
    assert fatal_tool_failure_detail(
        "terminal.run",
        request,
        {"ok": False, "approval_required": True},
    ) == ""
    assert fatal_tool_failure_detail(
        "terminal.run",
        request,
        {"ok": False, "blocked_by_user_goal": True},
    ) == ""


def test_tool_loop_message_projection_helpers_preserve_protocol_shapes() -> None:
    assistant = assistant_message_for_history(
        {"content": "", "tool_calls": [{"id": "call-1"}]},
    )
    assert assistant == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "call-1"}],
    }
    assert agent_runtime.NativeRunEngine._assistant_message_for_history(
        {"content": "", "tool_calls": [{"id": "call-1"}]},
    ) == assistant

    tool_messages: list[dict] = []
    append_tool_result_message(
        tool_messages,
        {"protocol": "tool_calls", "tool_call_id": "call-1", "tool": "workspace.read"},
        {"ok": True, "content": "done"},
    )
    assert tool_messages == [
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"ok": true, "content": "done"}',
        }
    ]

    fallback_messages: list[dict] = []
    append_tool_result_message(
        fallback_messages,
        {"tool": "workspace.read"},
        {"ok": True},
    )
    assert fallback_messages == [
        {"role": "user", "content": 'Tool result for workspace.read: {"ok": true}'}
    ]


def test_tool_loop_stages_complete_native_batch_before_internal_recovery_messages() -> None:
    messages = [
        assistant_message_for_history(
            {
                "content": "",
                "tool_calls": [
                    {"id": "call-1", "function": {"name": "app_open", "arguments": "{}"}},
                    {"id": "call-2", "function": {"name": "app_type", "arguments": "{}"}},
                ],
            }
        )
    ]

    stage_tool_result_messages(messages)
    append_tool_result_message(
        messages,
        {"protocol": "tool_calls", "tool_call_id": "call-1", "tool": "app.open"},
        {"ok": False, "status": "blocked"},
    )
    append_tool_result_message(
        messages,
        {"protocol": "json_fallback", "tool": "desktop.permissions"},
        {"ok": True},
    )

    assert [message["role"] for message in messages] == [
        "assistant",
        "tool",
        "tool",
        "user",
    ]
    assert [message["tool_call_id"] for message in messages[1:3]] == [
        "call-1",
        "call-2",
    ]
    assert json.loads(messages[1]["content"]) == {"ok": False, "status": "blocked"}
    assert json.loads(messages[2]["content"])["error"] == (
        "tool_batch_interrupted_before_execution"
    )


def test_native_runtime_uses_split_tool_loop_projection_builder(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeToolLoopProjectionBuilder is RuntimeToolLoopProjectionBuilder
        assert isinstance(service.tool_loop_projection, RuntimeToolLoopProjectionBuilder)
    finally:
        service.close()
