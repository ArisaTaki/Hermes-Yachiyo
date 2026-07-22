"""Tool loop projection helpers for Agent runtime execution."""

from __future__ import annotations

import json
from typing import Any


_INTERRUPTED_TOOL_RESULT = {
    "ok": False,
    "status": "skipped",
    "skipped": True,
    "error": "tool_batch_interrupted_before_execution",
    "summary": "The tool call was not reached before this tool batch stopped.",
}


def tool_loop_limit_detail(timeline: list[dict[str, Any]]) -> str:
    for event in reversed(timeline):
        if event.get("event") != "agent.tool.call":
            continue
        tool_name = str(event.get("detail") or "unknown tool")
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        parts = [f"最后一次工具调用：{tool_name}"]
        error = str(result.get("error") or "").strip()
        if error:
            parts.append(f"错误：{error}")
        returncode = result.get("returncode")
        if returncode not in (None, 0, "0"):
            parts.append(f"退出码：{returncode}")
        hint = str(result.get("hint") or "").strip()
        if hint:
            parts.append(f"建议：{hint}")
        suggested_tool = str(result.get("suggested_tool") or "").strip()
        if suggested_tool:
            parts.append(f"建议工具：{suggested_tool}")
        stderr = str(result.get("stderr") or "").strip()
        if stderr and not error:
            parts.append(f"stderr：{stderr[:500]}")
        return "；".join(parts)
    return "没有可用的工具调用详情"


def tool_loop_limit_artifact_completion(
    timeline: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> str | None:
    last_tool_event = next(
        (event for event in reversed(timeline) if event.get("event") == "agent.tool.call"),
        None,
    )
    if not last_tool_event or str(last_tool_event.get("detail") or "") != "artifact.write":
        return None
    result = last_tool_event.get("result") if isinstance(last_tool_event.get("result"), dict) else {}
    if not result.get("ok"):
        return None
    paths: list[str] = []
    for artifact in artifacts:
        if artifact.get("kind") == "context":
            continue
        path = str(artifact.get("path") or "").strip()
        if path and path not in paths:
            paths.append(path)
    if not paths:
        path = str(result.get("path") or "").strip()
        if path:
            paths.append(path)
    if not paths:
        return None
    return (
        "已写入产物，但模型在工具循环上限前没有返回最终总结。\n"
        f"产物：{', '.join(paths)}\n"
        f"{tool_loop_limit_detail(timeline)}"
    )


def fatal_tool_failure_detail(
    tool_name: str,
    tool_request: dict[str, Any],
    tool_result: dict[str, Any],
) -> str:
    if tool_name != "terminal.run":
        return ""
    if (
        tool_result.get("ok")
        or tool_result.get("approval_required")
        or tool_result.get("blocked_by_user_goal")
    ):
        return ""
    payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
    command = str(payload.get("command") or "").strip()
    parts = ["terminal.run 执行失败"]
    if command:
        parts.append(f"命令：{command}")
    returncode = tool_result.get("returncode")
    if returncode not in (None, ""):
        parts.append(f"退出码：{returncode}")
    error = str(tool_result.get("error") or "").strip()
    if error:
        parts.append(f"错误：{error}")
    stdout = str(tool_result.get("stdout") or "").strip()
    if stdout:
        parts.append(f"stdout：{stdout[:1000]}")
    stderr = str(tool_result.get("stderr") or "").strip()
    if stderr:
        parts.append(f"stderr：{stderr[:1000]}")
    return "；".join(parts)


def assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    history = {
        "role": "assistant",
        "content": content if content not in (None, "") else None,
    }
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        history["tool_calls"] = tool_calls
    return history


def _assistant_tool_call_ids(message: dict[str, Any]) -> list[str]:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    call_ids: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        call_id = ""
        for key in ("tool_call_id", "call_id", "id"):
            call_id = str(call.get(key) or "").strip()
            if call_id:
                break
        if call_id and call_id not in call_ids:
            call_ids.append(call_id)
    return call_ids


def stage_tool_result_messages(messages: list[dict[str, Any]]) -> None:
    """Reserve one contiguous tool result for every native assistant tool call.

    The runner may stop a batch early or execute internal recovery requests in
    between model-authored calls. Reserving the full native result group keeps
    OpenAI-compatible histories valid; completed calls replace their staged
    result in place.
    """

    if not messages:
        return
    assistant = messages[-1]
    if assistant.get("role") != "assistant":
        return
    tool_call_ids = _assistant_tool_call_ids(assistant)
    if not tool_call_ids:
        return
    content = json.dumps(_INTERRUPTED_TOOL_RESULT, ensure_ascii=False)
    for tool_call_id in tool_call_ids:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }
        )


def _replace_staged_tool_result_message(
    messages: list[dict[str, Any]],
    tool_call_id: str,
    content: str,
) -> bool:
    assistant_index = -1
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") != "assistant":
            continue
        if tool_call_id in _assistant_tool_call_ids(message):
            assistant_index = index
            break
    if assistant_index < 0:
        return False
    for message in messages[assistant_index + 1 :]:
        if (
            message.get("role") == "tool"
            and str(message.get("tool_call_id") or "").strip() == tool_call_id
        ):
            message["content"] = content
            return True
    return False


def append_tool_result_message(
    messages: list[dict[str, Any]],
    tool_request: dict[str, Any],
    tool_result: dict[str, Any],
) -> None:
    content = json.dumps(tool_result, ensure_ascii=False)
    if tool_request.get("protocol") == "tool_calls":
        tool_call_id = str(tool_request.get("tool_call_id") or "").strip()
        if tool_call_id and _replace_staged_tool_result_message(
            messages,
            tool_call_id,
            content,
        ):
            return
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }
        )
        return
    messages.append(
        {"role": "user", "content": f"Tool result for {tool_request['tool']}: {content}"}
    )


class RuntimeToolLoopProjectionBuilder:
    """Builds tool-loop projection details without owning run state."""

    def loop_limit_detail(self, timeline: list[dict[str, Any]]) -> str:
        return tool_loop_limit_detail(timeline)

    def artifact_completion(
        self,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> str | None:
        return tool_loop_limit_artifact_completion(timeline, artifacts)

    def fatal_failure_detail(
        self,
        tool_name: str,
        tool_request: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> str:
        return fatal_tool_failure_detail(tool_name, tool_request, tool_result)

    def assistant_message_for_history(self, message: dict[str, Any]) -> dict[str, Any]:
        return assistant_message_for_history(message)

    def append_tool_result_message(
        self,
        messages: list[dict[str, Any]],
        tool_request: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> None:
        append_tool_result_message(messages, tool_request, tool_result)
