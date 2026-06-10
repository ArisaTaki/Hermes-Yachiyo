"""Task execution strategies.

TaskRunner owns the product Task lifecycle. ExecutionStrategy implementations
only decide how a Task is executed; the default product path is Native Agent.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import mimetypes
import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, Optional

from packages.protocol.schemas import TaskInfo
from packages.security import redact_api_error_text
from apps.core.special_sessions import is_proactive_chat_session
from apps.core.title_generator import (
    build_session_title_prompt as build_direct_session_title_prompt,
    generate_title_with_direct_api,
    looks_like_title_prompt_echo,
)

if TYPE_CHECKING:
    from apps.core.activity_store import ActivityStore
    from apps.core.chat_session import ChatSession
    from apps.core.runtime import AppRuntime

logger = logging.getLogger(__name__)

NATIVE_AGENT_NOT_READY_MESSAGE = "Native Agent 当前未就绪，请先配置并选择默认对话模型。"


class NativeAgentError(RuntimeError):
    """Native Agent execution failure with a stable machine-readable reason."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "native_agent_error",
        reason: str = "execution_failed",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason

    def to_error_string(self) -> str:
        return str(self)


@dataclass(frozen=True)
class DelegationDirective:
    """Structured internal contract for Native Agent delegation."""

    kind: str
    name: str = ""
    runnable_id: str = ""
    goal: str = ""

    @property
    def target_label(self) -> str:
        return self.name or self.runnable_id or "Yachiyo Agent"

    def as_request(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "name": self.name,
            "runnable_id": self.runnable_id,
            "goal": self.goal,
        }


_TITLE_GENERATION_ENABLED_ENV = "OHA_YACHIYO_TITLE_GENERATION"
_TITLE_CONTEXT_MESSAGES_ENV = "OHA_YACHIYO_TITLE_CONTEXT_MESSAGES"
_TITLE_INTERVAL_TURNS_ENV = "OHA_YACHIYO_TITLE_INTERVAL_TURNS"
_TITLE_INTERVAL_MESSAGES_ENV = "OHA_YACHIYO_TITLE_INTERVAL_MESSAGES"
_TITLE_TIMEOUT_ENV = "OHA_YACHIYO_TITLE_TIMEOUT_SECONDS"
_DEFAULT_TITLE_CONTEXT_MESSAGES = 8
_DEFAULT_TITLE_INTERVAL_TURNS = 4
_DEFAULT_TITLE_TIMEOUT_SECONDS = 8.0
_GENERATED_TITLE_MAX_CHARS = 28
_TITLE_REFRESH_TASKS: dict[str, asyncio.Task[None]] = {}
_MEMORY_CONTEXT_MAX_ITEMS = 8
_MEMORY_CONTEXT_MAX_SESSIONS = 200
_MEMORY_CONTEXT_ITEM_MAX_CHARS = 180
_MEMORY_CONTEXT_TOTAL_MAX_CHARS = 1400
_MEMORY_MARKERS = (
    "记住",
    "记忆",
    "长期",
    "以后",
    "今后",
    "偏好",
    "我喜欢",
    "我不喜欢",
    "不要",
    "别",
    "必须",
    "先问",
    "许可",
    "允许",
    "未经",
    "擅自",
    "always",
    "never",
    "remember",
    "preference",
    "permission",
)


_WEEKDAY_NAMES = (
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
)

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_MAIN_CHAT_HISTORY_MESSAGE_LIMIT = 20
_MAIN_CHAT_HISTORY_CHAR_LIMIT = 32_000
_MAIN_CHAT_IMAGE_ATTACHMENT_LIMIT = 4
_MAIN_CHAT_IMAGE_MAX_BYTES = 12 * 1024 * 1024


def format_persona_description(
    description: str,
    persona_prompt: str = "",
    user_address: str = "",
    environment_context: str = "",
    profile_context: str = "",
) -> str:
    """按共享助手资料包装用户请求，资料为空时保持原始描述。"""
    persona = (persona_prompt or "").strip()
    address = (user_address or "").strip()
    environment = (environment_context or "").strip()
    profile = (profile_context or "").strip()
    if not environment and not persona and not address and not profile:
        return description
    parts: list[str] = []
    if environment:
        parts.append(environment)
    if profile:
        parts.append(profile)
    if persona:
        parts.append(f"[人设设定]\n{persona}")
    if address:
        parts.append(f"[用户称呼]\n请称呼用户为：{address}")
    parts.append(f"[用户请求]\n{description}")
    return "\n\n".join(parts)


def _oha_delegation_catalog_context() -> str:
    try:
        from apps.shell.agent_runtime import get_agent_runtime_service

        targets = get_agent_runtime_service().list_delegation_targets()
    except Exception:
        logger.debug("读取 OHA 委派目标失败", exc_info=True)
        return ""
    entries: list[str] = []
    for agent in targets.get("agents") or []:
        entries.append(
            "- Agent: "
            f"{agent.get('name')} | category={agent.get('category') or 'custom'} | "
            f"output={agent.get('output_contract') or 'chat'} | "
            f"description={agent.get('description') or ''}"
        )
    for workflow in targets.get("workflows") or []:
        entries.append(
            "- Workflow: "
            f"{workflow.get('name')} | nodes={workflow.get('nodes') or 0} | "
            f"description={workflow.get('description') or ''}"
        )
    if not entries:
        return ""
    return (
        "[Oha-Yachiyo 持久 Agent 委派]\n"
        "你可以把明确的子任务委派给 Agent Studio 中已保存的持久 Agent 或 Workflow。"
        "这些不是一次性临时 delegate_task 子 Agent，而是有固定职责、Skills、模型和审计记录的岗位。\n"
        "当你需要委派时，只输出一个 JSON 对象，不要附加其他正文：\n"
        '{"action":"run_oha_agent","agent":"Agent 名称","goal":"自包含任务目标"}\n'
        "或：\n"
        '{"action":"run_oha_workflow","workflow":"Workflow 名称","goal":"自包含任务目标"}\n'
        "委派结果会返回给你，然后你再继续整合最终回复。每轮最多委派 3 次。\n"
        "可用目标：\n"
        + "\n".join(entries[:40])
    )


def _is_yachiyo_group_coordinator_task(description: str) -> bool:
    return "[Yachiyo 群组上下文]" in (description or "")


def _oha_group_dispatch_context() -> str:
    return (
        "[Oha-Yachiyo 群组派活]\n"
        "当前会话是群组。你是默认协调者，不要默认让所有 Agent 参与。"
        "如果用户没有明确 @ 某个 Agent，请先判断应该由你直接回答，还是派给群组上下文里列出的一个或多个 Agent。"
        "只有当用户表达“大家/所有人/分别做”等意图时，才派给多个 Agent。\n"
        "派活不是终端命令，也不是工具调用；不要调用 shell/terminal 来 echo、模拟或包装派活指令。\n"
        "如果需要派活，请先用自然语言向用户说明你的安排，再附加一个机器可读 native 派活 JSON，格式如下：\n"
        '{"tool":"oha.group_dispatch","input":{"tasks":[{"kind":"agent","target":"Agent 名称或昵称","goal":"自包含任务目标"}]}}\n'
        "可以一次派给多个 Agent，但每个 goal 都要独立完整，不能用“同上”“继续”等省略说法。\n"
        "不要使用旧委派 action 或旧标签；不要把 JSON 包进 Markdown 代码块。"
        "群组派活会由聊天层接管、隐藏内部 JSON，并显示各 Agent 的执行状态。"
    )


def _append_oha_delegation_context(profile_context: str, *, group_coordinator: bool = False) -> str:
    catalog = _oha_group_dispatch_context() if group_coordinator else _oha_delegation_catalog_context()
    if not catalog:
        return profile_context
    base = (profile_context or "").strip()
    return f"{base}\n\n{catalog}" if base else catalog


def _payload_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    normalized_keys = {
        re.sub(r"[\s_-]+", "", str(key or "")).lower()
        for key in keys
        if str(key or "").strip()
    }
    for raw_key, value in payload.items():
        if value in (None, ""):
            continue
        normalized = re.sub(r"[\s_-]+", "", str(raw_key or "")).lower()
        if normalized in normalized_keys:
            return value
    return None


def _json_candidate_texts(text: str) -> list[str]:
    candidates = [text]
    normalized = (
        text.replace("“", '"')
        .replace("”", '"')
        .replace("„", '"')
        .replace("＂", '"')
    )
    if normalized != text:
        candidates.append(normalized)
    return candidates


def _json_objects_from_text(text: str) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return []
    text = re.sub(
        r"<\s*(?!oha[\s_-]*delegation\b)[a-z][\w\s_-]*delegation\b[^>]*>.*?</\s*[a-z][\w\s_-]*delegation\s*>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()
    match = re.search(r"<oha_delegation>\s*(.*?)\s*</oha_delegation>", text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()

    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in _json_candidate_texts(text):
        candidate = candidate.strip()
        decoder = json.JSONDecoder()
        index = 0
        while index < len(candidate):
            if candidate[index] != "{":
                index += 1
                continue
            try:
                payload, offset = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                index += 1
                continue
            if isinstance(payload, dict):
                key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
                if key not in seen:
                    payloads.append(payload)
                    seen.add(key)
            index += max(offset, 1)
    return payloads


def _normalize_oha_delegation_action(value: str) -> str:
    compact = re.sub(r"[\s_\-./]+", "", str(value or "").strip().lower())
    if compact in {
        "agent",
        "agentrun",
        "runagent",
        "delegateagent",
        "delegatetoagent",
        "assignagent",
        "runohaagent",
        "ohaagent",
        "runnativeagent",
        "nativeagent",
    }:
        return "agent"
    if compact in {
        "workflow",
        "workflowrun",
        "runworkflow",
        "delegateworkflow",
        "delegatetoworkflow",
        "assignworkflow",
        "runohaworkflow",
        "ohaworkflow",
        "runnativeworkflow",
        "nativeworkflow",
    }:
        return "workflow"
    return ""


def _parse_oha_delegation_directive(content: str) -> DelegationDirective | None:
    for payload in _json_objects_from_text(content):
        directive = _oha_delegation_directive_from_payload(payload)
        if directive:
            return directive
    return None


def _parse_oha_delegation_request(content: str) -> dict[str, str] | None:
    directive = _parse_oha_delegation_directive(content)
    return directive.as_request() if directive else None


def _oha_delegation_directive_from_payload(payload: dict[str, Any]) -> DelegationDirective | None:
    action = _normalize_oha_delegation_action(str(
        _payload_value(payload, "action", "tool", "kind", "type", "target_kind", "runnable_kind")
        or ""
    ))
    if action not in {"agent", "workflow"}:
        return None
    goal = str(
        _payload_value(
            payload,
            "goal",
            "user_goal",
            "userGoal",
            "task",
            "task_goal",
            "taskGoal",
            "objective",
            "instruction",
            "instructions",
            "prompt",
        )
        or ""
    ).strip()
    if not goal:
        return None
    if action == "agent":
        name = str(
            _payload_value(
                payload,
                "agent",
                "agent_name",
                "agentName",
                "name",
                "target",
                "target_name",
                "targetName",
                "runnable",
                "runnable_name",
                "runnableName",
            )
            or ""
        ).strip()
        runnable_id = str(_payload_value(payload, "agent_id", "agentId", "runnable_id", "runnableId", "id") or "").strip()
        kind = "agent"
    else:
        name = str(
            _payload_value(
                payload,
                "workflow",
                "workflow_name",
                "workflowName",
                "name",
                "target",
                "target_name",
                "targetName",
                "runnable",
                "runnable_name",
                "runnableName",
            )
            or ""
        ).strip()
        runnable_id = str(_payload_value(payload, "workflow_id", "workflowId", "runnable_id", "runnableId", "id") or "").strip()
        kind = "workflow"
    if not name and not runnable_id:
        return None
    return DelegationDirective(kind=kind, name=name, runnable_id=runnable_id, goal=goal)


def _coerce_oha_delegation_directive(value: DelegationDirective | dict[str, str]) -> DelegationDirective:
    if isinstance(value, DelegationDirective):
        return value
    return DelegationDirective(
        kind=str(value.get("kind") or ""),
        name=str(value.get("name") or ""),
        runnable_id=str(value.get("runnable_id") or ""),
        goal=str(value.get("goal") or ""),
    )


def _run_oha_delegation(request: DelegationDirective | dict[str, str], service: Any | None = None) -> dict[str, Any]:
    directive = _coerce_oha_delegation_directive(request)
    if service is None:
        from apps.shell.agent_runtime import get_agent_runtime_service

        service = get_agent_runtime_service()
    return service.delegate_runnable(
        kind=directive.kind,
        name=directive.name,
        runnable_id=directive.runnable_id,
        user_goal=directive.goal,
    )


def _format_oha_delegation_result(result: dict[str, Any]) -> str:
    runnable = result.get("runnable") or {}
    lines = [
        f"Runnable: {runnable.get('kind') or ''} {runnable.get('name') or runnable.get('id') or ''}",
        f"Run: {result.get('run_id') or ''}",
        f"Status: {result.get('status') or ''}",
    ]
    pending = result.get("pending_approval") if isinstance(result.get("pending_approval"), dict) else {}
    if pending:
        lines.append("Pending approval:")
        tool = str(pending.get("tool") or "").strip()
        if tool:
            lines.append(f"- Tool: {tool}")
        preview = pending.get("input_preview")
        if preview:
            try:
                preview_text = json.dumps(preview, ensure_ascii=False, indent=2)
            except TypeError:
                preview_text = str(preview)
            lines.append(f"- Request:\n{preview_text[:2000]}")
    lines.append(f"Result:\n{result.get('result') or ''}")
    return "\n".join(lines).strip()


def _oha_delegation_activity_status(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "").strip()
    if status == "approval_required":
        return "approval_required"
    return "completed" if result.get("ok") else "failed"


def _oha_delegation_activity_title(target: str, result: dict[str, Any]) -> str:
    status = str(result.get("status") or "").strip()
    if status == "approval_required":
        return f"{target} 等待审批"
    return f"{target} 委派完成" if result.get("ok") else f"{target} 委派失败"


def _build_oha_delegation_followup(
    original_prompt: str,
    delegation_request_text: str,
    delegation_result: str,
) -> str:
    return (
        f"{original_prompt}\n\n"
        "[OHA 委派请求]\n"
        f"{delegation_request_text.strip()[:4000]}\n\n"
        "[OHA 委派结果]\n"
        f"{delegation_result[:12000]}\n\n"
        "请基于以上委派结果继续处理用户请求。若仍需委派，可再次输出同样 JSON；"
        "否则直接给出最终回复，不要重复委派 JSON。"
    )


def _task_image_paths(task: TaskInfo) -> list[str]:
    paths: list[str] = []
    for attachment in getattr(task, "attachments", []) or []:
        if not isinstance(attachment, dict):
            continue
        if str(attachment.get("kind") or "image") != "image":
            continue
        path = str(attachment.get("path") or "").strip()
        if path:
            paths.append(path)
    return paths


def _describe_day_period(hour: int) -> str:
    if 5 <= hour < 9:
        return "早上"
    if 9 <= hour < 12:
        return "上午"
    if 12 <= hour < 14:
        return "中午"
    if 14 <= hour < 18:
        return "下午"
    if 18 <= hour < 23:
        return "晚上"
    return "深夜"


def format_environment_context(now: Optional[datetime] = None) -> str:
    """生成每轮对话的本地环境上下文。"""
    current = now.astimezone() if now is not None else datetime.now().astimezone()
    offset = current.strftime("%z")
    timezone_label = f"UTC{offset[:3]}:{offset[3:]}" if offset else "本地时区"
    weekday = _WEEKDAY_NAMES[current.weekday()]
    period = _describe_day_period(current.hour)
    return (
        "[当前环境]\n"
        f"当前本地时间：{current.strftime('%Y-%m-%d %H:%M:%S')}"
        f"（{timezone_label}，{weekday}，{period}）\n"
        "请结合当前时间、日期与时段理解问候、计划和相对时间表达。"
    )


def build_cross_session_memory_context(
    current_session_id: str = "",
    *,
    store: Any | None = None,
    max_items: int = _MEMORY_CONTEXT_MAX_ITEMS,
) -> str:
    """Build lightweight durable memory from explicit user statements in chat history."""
    max_items = max(0, min(int(max_items or 0), 20))
    if max_items <= 0:
        return ""
    try:
        if store is None:
            from apps.core.chat_store import get_chat_store

            store = get_chat_store()
        sessions = store.list_sessions(limit=_MEMORY_CONTEXT_MAX_SESSIONS)
    except Exception:
        logger.debug("读取长期记忆候选会话失败", exc_info=True)
        return ""

    current_session_id = str(current_session_id or "").strip()
    candidates: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for session in sessions:
        session_id = str(getattr(session, "session_id", "") or "")
        try:
            messages = store.load_messages(
                session_id,
                limit=0,
            )
        except Exception:
            logger.debug("读取长期记忆候选消息失败: %s", session_id, exc_info=True)
            continue
        for message in reversed(messages):
            if str(getattr(message, "role", "") or "") != "user":
                continue
            memory = _extract_memory_statement(str(getattr(message, "content", "") or ""))
            if not memory:
                continue
            key = memory.lower()
            if key in seen:
                continue
            seen.add(key)
            created_at = str(getattr(message, "created_at", "") or getattr(session, "created_at", "") or "")
            candidates.append((created_at, session_id, memory))
            if len(candidates) >= max_items:
                return _format_memory_context(candidates, current_session_id)
    return _format_memory_context(candidates, current_session_id)


def build_runtime_profile_context(runtime: "AppRuntime") -> str:
    """Combine configured profile fields with lightweight cross-session memory."""
    parts: list[str] = []
    try:
        configured = runtime.config.assistant.prompt_profile_context()
        if configured:
            parts.append(configured)
    except Exception:
        logger.debug("读取配置资料上下文失败", exc_info=True)
    try:
        current_session_id = str(getattr(runtime.chat_session, "session_id", "") or "")
        memory_context = build_cross_session_memory_context(current_session_id)
        if memory_context:
            parts.append(memory_context)
    except Exception:
        logger.debug("构建长期记忆上下文失败", exc_info=True)
    return "\n\n".join(parts)


def _extract_memory_statement(text: str) -> str:
    value = " ".join(str(text or "").replace("\r", "\n").split())
    if len(value) < 4:
        return ""
    lowered = value.lower()
    if not any(marker in value or marker in lowered for marker in _MEMORY_MARKERS):
        return ""
    for prefix in (
        "请记住",
        "帮我记住",
        "记住：",
        "记住:",
        "记忆：",
        "记忆:",
        "以后请",
        "今后请",
    ):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    value = value.strip(" ：:，,。.;；")
    if not value:
        return ""
    if len(value) > _MEMORY_CONTEXT_ITEM_MAX_CHARS:
        value = value[: _MEMORY_CONTEXT_ITEM_MAX_CHARS - 1].rstrip() + "…"
    return value


def _format_memory_context(candidates: list[tuple[str, str, str]], current_session_id: str) -> str:
    if not candidates:
        return ""
    lines = [
        "[长期记忆]",
        "以下是用户在历史会话中明确表达的偏好、约束和长期说明；除非本轮明确更新，请持续遵守。",
    ]
    for created_at, session_id, memory in candidates:
        source = "当前会话" if session_id and session_id == current_session_id else "历史会话"
        date = _memory_context_date(created_at)
        label = f"{source} {date}".strip()
        lines.append(f"- {label}：{memory}" if label else f"- {memory}")
    context = "\n".join(lines)
    if len(context) > _MEMORY_CONTEXT_TOTAL_MAX_CHARS:
        context = context[: _MEMORY_CONTEXT_TOTAL_MAX_CHARS - 1].rstrip() + "…"
    return context


def _memory_context_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value[:10] if len(value) >= 10 else ""
    return parsed.date().isoformat()


def _read_title_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r 不是有效整数，使用默认值 %d", name, raw, default)
        return default
    return max(minimum, min(value, maximum))


def _read_title_timeout() -> float:
    raw = os.getenv(_TITLE_TIMEOUT_ENV, "").strip()
    if not raw:
        return _DEFAULT_TITLE_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r 不是有效数字，使用默认值 %.0fs", _TITLE_TIMEOUT_ENV, raw, _DEFAULT_TITLE_TIMEOUT_SECONDS)
        return _DEFAULT_TITLE_TIMEOUT_SECONDS
    return max(3.0, min(value, 90.0))


def _session_title_generation_enabled() -> bool:
    raw = os.getenv(_TITLE_GENERATION_ENABLED_ENV, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _read_title_interval_turns() -> int:
    raw = os.getenv(_TITLE_INTERVAL_TURNS_ENV, "").strip()
    if not raw:
        raw = os.getenv(_TITLE_INTERVAL_MESSAGES_ENV, "").strip()
    if not raw:
        return _DEFAULT_TITLE_INTERVAL_TURNS
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r 不是有效整数，使用默认值 %d", _TITLE_INTERVAL_TURNS_ENV, raw, _DEFAULT_TITLE_INTERVAL_TURNS)
        return _DEFAULT_TITLE_INTERVAL_TURNS
    return max(1, min(value, 20))


def _completed_assistant_turn_count(chat_session: "ChatSession", *, include_pending_completion: bool = False) -> int:
    count = 1 if include_pending_completion else 0
    for message in chat_session.get_all_messages():
        role_value = getattr(getattr(message, "role", ""), "value", getattr(message, "role", ""))
        status_value = getattr(getattr(message, "status", ""), "value", getattr(message, "status", ""))
        if role_value == "assistant" and status_value == "completed":
            count += 1
    return count


def _should_refresh_generated_title(chat_session: "ChatSession", *, assistant_text: str = "") -> bool:
    if not _session_title_generation_enabled():
        return False
    turn_count = _completed_assistant_turn_count(
        chat_session,
        include_pending_completion=bool((assistant_text or "").strip()),
    )
    if turn_count >= 1 and looks_like_title_prompt_echo(_stored_session_title(chat_session)):
        return True
    interval = _read_title_interval_turns()
    return turn_count >= interval and turn_count % interval == 0


def _build_session_title_prompt(
    chat_session: "ChatSession",
    *,
    assistant_text: str = "",
) -> str:
    context_limit = _read_title_int_env(
        _TITLE_CONTEXT_MESSAGES_ENV,
        _DEFAULT_TITLE_CONTEXT_MESSAGES,
        minimum=2,
        maximum=24,
    )
    messages = chat_session.get_all_messages()
    assistant_text = assistant_text.strip()
    if assistant_text and not _message_list_already_ends_with_assistant_text(messages, assistant_text):
        messages = [
            *messages,
            SimpleNamespace(role="assistant", content=assistant_text),
        ]
    return build_direct_session_title_prompt(
        messages,
        current_title=_current_session_title(chat_session),
        context_limit=context_limit,
    )


def _message_list_already_ends_with_assistant_text(messages: list[Any], assistant_text: str) -> bool:
    for message in reversed(messages):
        role_value = getattr(getattr(message, "role", ""), "value", getattr(message, "role", ""))
        if role_value not in {"user", "assistant"}:
            continue
        return role_value == "assistant" and str(getattr(message, "content", "") or "").strip() == assistant_text
    return False


def _current_session_title(chat_session: "ChatSession") -> str:
    title = _stored_session_title(chat_session)
    if looks_like_title_prompt_echo(title):
        return ""
    return title


def _stored_session_title(chat_session: "ChatSession") -> str:
    store = getattr(chat_session, "_store", None)
    if store is None:
        return ""
    try:
        stored = store.get_session(chat_session.session_id)
    except Exception:
        logger.debug("读取当前会话标题失败", exc_info=True)
        return ""
    return str(getattr(stored, "title", "") or "") if stored is not None else ""


def _first_user_session_title(chat_session: "ChatSession") -> str:
    from apps.core.chat_store import make_session_title

    for message in chat_session.get_all_messages():
        role_value = getattr(getattr(message, "role", ""), "value", getattr(message, "role", ""))
        if role_value != "user":
            continue
        title = make_session_title(str(getattr(message, "content", "") or ""))
        if title:
            return title
    return ""


def _sanitize_generated_session_title(value: str | None) -> str:
    title = _ANSI_RE.sub("", value or "")
    title = re.sub(r"^(?:标题|会话标题)\s*[:：]\s*", "", title.strip(), flags=re.IGNORECASE)
    title = title.strip(" \t\r\n\"'“”‘’`*_#：:。.!！?？")
    title = re.sub(r"\s+", " ", title)
    title = title.splitlines()[0].strip() if title else ""
    if not title:
        return ""
    if looks_like_title_prompt_echo(title):
        return ""
    if len(title) > _GENERATED_TITLE_MAX_CHARS:
        title = title[:_GENERATED_TITLE_MAX_CHARS].rstrip()
    return title.strip(" \t\r\n\"'“”‘’`*_#：:。.!！?？")


async def _generate_session_title(prompt: str) -> str:
    """Generate a compact chat title with direct model API.

    Title generation is a product projection, so it must use the configured
    native model path and must not invoke an external execution kernel.
    """
    title = await generate_title_with_direct_api(prompt, timeout=_read_title_timeout())
    return _sanitize_generated_session_title(title)


async def _refresh_session_title_from_recent_messages(
    chat_session: "ChatSession",
    *,
    assistant_text: str = "",
) -> None:
    if is_proactive_chat_session(chat_session.session_id):
        return
    prompt = _build_session_title_prompt(chat_session, assistant_text=assistant_text)
    title = await _generate_session_title(prompt)
    if title:
        chat_session.set_session_title(title)
        return
    if looks_like_title_prompt_echo(_stored_session_title(chat_session)):
        fallback_title = _first_user_session_title(chat_session)
        if fallback_title:
            chat_session.set_session_title(fallback_title)


def _schedule_session_title_refresh(
    chat_session: "ChatSession | None",
    *,
    assistant_text: str = "",
) -> None:
    if chat_session is None or not _should_refresh_generated_title(chat_session, assistant_text=assistant_text):
        return
    existing = _TITLE_REFRESH_TASKS.get(chat_session.session_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(
        _refresh_session_title_from_recent_messages(chat_session, assistant_text=assistant_text),
        name=f"chat-title-{chat_session.session_id}",
    )
    _TITLE_REFRESH_TASKS[chat_session.session_id] = task

    def _log_title_task(done: asyncio.Task[None]) -> None:
        if _TITLE_REFRESH_TASKS.get(chat_session.session_id) is done:
            _TITLE_REFRESH_TASKS.pop(chat_session.session_id, None)
        try:
            done.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("会话标题生成任务失败", exc_info=True)

    task.add_done_callback(_log_title_task)


# ── 抽象接口 ─────────────────────────────────────────────────────────────────

class ExecutionStrategy(ABC):
    """任务执行策略抽象接口"""

    @abstractmethod
    async def run(self, task: TaskInfo) -> str:
        """执行任务，返回结果字符串。失败则抛出异常（TaskRunner 负责捕获）。"""
        ...

    @property
    def name(self) -> str:
        return type(self).__name__


def execution_capabilities(executor: Any) -> dict[str, bool]:
    """Normalize executor capabilities behind the TaskRunner boundary."""
    capabilities = getattr(executor, "capabilities", None)
    if isinstance(capabilities, dict):
        return {
            "model": bool(capabilities.get("model")),
            "image_input": bool(capabilities.get("image_input")),
            "tools": bool(capabilities.get("tools")),
            "approval": bool(capabilities.get("approval")),
        }
    return {
        "model": False,
        "image_input": False,
        "tools": False,
        "approval": False,
    }


# ── MVP 模拟执行器 ────────────────────────────────────────────────────────────

_SIM_RUN_DELAY: float = 2.0
_SIM_COMPLETE_DELAY: float = 5.0


class SimulatedExecutor(ExecutionStrategy):
    """MVP 模拟执行器（sleep + 占位结果，离线可用）"""

    async def run(self, task: TaskInfo) -> str:
        logger.debug("[Simulated] 开始执行: %s", task.task_id)
        await asyncio.sleep(_SIM_RUN_DELAY)
        await asyncio.sleep(_SIM_COMPLETE_DELAY)
        return f"[模拟结果] {task.description[:80]}"


class NativeAgentUnavailableExecutor(ExecutionStrategy):
    """Explicitly rejects user tasks until the native main model is ready."""

    def __init__(
        self,
        message: str | None = None,
        *,
        reason: str = "model_profile_required",
    ) -> None:
        self.reason = str(message or NATIVE_AGENT_NOT_READY_MESSAGE)
        self.code = "native_agent_not_ready"
        self.reason_code = str(reason or "model_profile_required")

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "model": False,
            "image_input": False,
            "tools": False,
            "approval": False,
        }

    async def run(self, task: TaskInfo) -> str:
        logger.warning("[NativeAgentUnavailable] 拒绝执行任务: %s | %s", task.task_id, self.reason)
        raise NativeAgentError(
            self.reason,
            code=self.code,
            reason=self.reason_code,
        )


class NativeAgentExecutor(ExecutionStrategy):
    """TaskRunner adapter for the persistent native Agent runtime."""

    def __init__(
        self,
        chat_session: Optional["ChatSession"] = None,
        persona_prompt_getter: Optional[Callable[[], str]] = None,
        user_address_getter: Optional[Callable[[], str]] = None,
        profile_context_getter: Optional[Callable[[], str]] = None,
        runtime_service_getter: Optional[Callable[[], Any]] = None,
        tool_policy_getter: Optional[Callable[[], dict[str, Any]]] = None,
        workspace_policy_getter: Optional[Callable[[], dict[str, Any]]] = None,
        activity_store_getter: Optional[Callable[[], "ActivityStore"]] = None,
    ) -> None:
        self._chat_session = chat_session
        self._persona_prompt_getter = persona_prompt_getter
        self._user_address_getter = user_address_getter
        self._profile_context_getter = profile_context_getter
        self._runtime_service_getter = runtime_service_getter
        self._tool_policy_getter = tool_policy_getter
        self._workspace_policy_getter = workspace_policy_getter
        self._activity_store_getter = activity_store_getter

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "model": True,
            "image_input": True,
            "tools": True,
            "approval": True,
        }

    def set_chat_session(self, chat_session: Optional["ChatSession"]) -> None:
        self._chat_session = chat_session

    def is_available(self) -> bool:
        return True

    def _runtime_service(self) -> Any:
        if self._runtime_service_getter is not None:
            return self._runtime_service_getter()
        from apps.shell.agent_runtime import get_native_run_engine

        return get_native_run_engine()

    async def run(self, task: TaskInfo) -> str:
        service = self._runtime_service()
        chat_session = self._chat_session_for_task(task)
        run_id = ""
        try:
            run = await asyncio.to_thread(
                service.start_main_chat_run,
                task_id=task.task_id,
                session_id=str(getattr(task, "chat_session_id", "") or ""),
                user_goal=task.description,
            )
            run_id = str(run.get("run_id") or "")
            image_paths = _task_image_paths(task)
            messages = self._messages_for_task(task, chat_session, image_paths=image_paths)
            if image_paths:
                from apps.shell.native_capabilities import get_native_image_input_capability

                image_capability = get_native_image_input_capability()
                if not image_capability.get("can_attach_images"):
                    raise NativeAgentError(
                        str(image_capability.get("reason") or "Native Agent 图片输入不可用"),
                        reason="vision_model_profile_required",
                    )
                if image_capability.get("route") == "vision_text":
                    vision_result = await asyncio.to_thread(
                        service.call_main_chat_model,
                        run_id,
                        [
                            {
                                "role": "user",
                                "content": self._task_user_content(
                                    "请准确分析这些图片，并输出供另一个对话模型继续回答用户请求的详细文字描述。",
                                    image_paths,
                                ),
                            }
                        ],
                        profile_id=str(image_capability.get("profile_id") or ""),
                        capability="vision",
                    )
                    messages = self._messages_for_task(task, chat_session, image_paths=[])
                    messages[-1]["content"] = (
                        f"{task.description}\n\n[图片识别结果]\n{vision_result}"
                    )
            group_coordinator = _is_yachiyo_group_coordinator_task(task.description)
            delegation_count = 0
            while True:
                output = await self._call_main_chat_model_loop(
                    service,
                    run_id,
                    messages,
                    chat_session,
                    task,
                )
                self._update_processing_message(chat_session, task.task_id, output)
                delegation_directive = None if group_coordinator else _parse_oha_delegation_directive(output)
                if delegation_directive is None:
                    await asyncio.to_thread(service.complete_main_chat_run, run_id, output)
                    _schedule_session_title_refresh(chat_session, assistant_text=output)
                    return output
                if delegation_count >= 3:
                    result = "OHA 自动委派已达到 3 次上限，已停止以避免循环调用。"
                    self._record_activity(
                        task,
                        "OHA 委派已停止",
                        "单轮自动委派超过 3 次上限",
                        "failed",
                    )
                    await asyncio.to_thread(service.complete_main_chat_run, run_id, result)
                    return result
                delegation_count += 1
                target = delegation_directive.target_label
                self._record_activity(
                    task,
                    f"正在委派给 {target}",
                    delegation_directive.goal,
                    "running",
                )
                try:
                    delegated = await asyncio.to_thread(_run_oha_delegation, delegation_directive, service)
                    delegated_text = _format_oha_delegation_result(delegated)
                    self._record_activity(
                        task,
                        _oha_delegation_activity_title(target, delegated),
                        delegated_text[:500],
                        _oha_delegation_activity_status(delegated),
                        metadata={
                            "run_id": delegated.get("run_id", ""),
                            "run_group_id": delegated.get("run_group_id", ""),
                            "run_status": delegated.get("status", ""),
                            "pending_approval": delegated.get("pending_approval", {}),
                        },
                    )
                except Exception as exc:
                    safe_error = redact_api_error_text(exc)
                    delegated_text = f"OHA delegation failed: {safe_error}"
                    self._record_activity(task, f"{target} 委派失败", safe_error, "failed")
                messages.append({"role": "assistant", "content": output})
                messages.append(
                    {
                        "role": "user",
                        "content": _build_oha_delegation_followup(
                            task.description,
                            output,
                            delegated_text,
                        ),
                    }
                )
        except asyncio.CancelledError:
            if run_id:
                try:
                    service.cancel_run(run_id)
                except Exception:
                    logger.debug("取消 Native Run 失败: %s", run_id, exc_info=True)
            raise
        except Exception as exc:
            skip_run_failure = False
            if isinstance(exc, NativeAgentError) and exc.reason == "approval_timeout" and run_id:
                try:
                    current_run = await asyncio.to_thread(service.get_run, run_id)
                    skip_run_failure = str(current_run.get("status") or "") in {
                        "cancelled",
                        "failed",
                        "completed",
                    }
                except Exception:
                    logger.debug("检查 Native Run 超时终态失败: %s", run_id, exc_info=True)
            if run_id and not skip_run_failure:
                try:
                    await asyncio.to_thread(service.fail_main_chat_run, run_id, exc)
                except Exception:
                    logger.debug("记录 Native Run 失败状态失败: %s", run_id, exc_info=True)
            if isinstance(exc, NativeAgentError):
                raise
            raise NativeAgentError(redact_api_error_text(exc)) from exc

    def _messages_for_task(
        self,
        task: TaskInfo,
        chat_session: Optional["ChatSession"],
        *,
        image_paths: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        persona_prompt = self._safe_get(self._persona_prompt_getter)
        user_address = self._safe_get(self._user_address_getter)
        profile_context = self._safe_get(self._profile_context_getter)
        profile_context = _append_oha_delegation_context(
            profile_context,
            group_coordinator=_is_yachiyo_group_coordinator_task(task.description),
        )
        system_prompt = format_persona_description(
            "请直接处理当前用户请求，并返回适合展示给用户的最终回复。",
            persona_prompt,
            user_address,
            format_environment_context(),
            profile_context,
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        history_chars = 0
        if chat_session is not None:
            history: list[dict[str, str]] = []
            for message in reversed(chat_session.get_all_messages()):
                if str(getattr(message, "task_id", "") or "") == task.task_id:
                    continue
                role = str(getattr(getattr(message, "role", ""), "value", getattr(message, "role", "")))
                content = str(getattr(message, "content", "") or "").strip()
                if role not in {"user", "assistant"} or not content:
                    continue
                if history_chars + len(content) > _MAIN_CHAT_HISTORY_CHAR_LIMIT:
                    break
                history.append({"role": role, "content": content})
                history_chars += len(content)
                if len(history) >= _MAIN_CHAT_HISTORY_MESSAGE_LIMIT:
                    break
            messages.extend(reversed(history))
        messages.append(
            {
                "role": "user",
                "content": self._task_user_content(
                    task.description,
                    _task_image_paths(task) if image_paths is None else image_paths,
                ),
            }
        )
        return messages

    @staticmethod
    def _safe_get(getter: Optional[Callable[[], str]]) -> str:
        if getter is None:
            return ""
        try:
            return str(getter() or "")
        except Exception:
            logger.debug("读取 Native Agent 上下文失败", exc_info=True)
            return ""

    async def _call_main_chat_model_loop(
        self,
        service: Any,
        run_id: str,
        messages: list[dict[str, Any]],
        chat_session: Optional["ChatSession"],
        task: TaskInfo,
    ) -> str:
        execute_loop = getattr(service, "execute_main_chat_model_loop", None)
        if not callable(execute_loop):
            return await asyncio.to_thread(service.call_main_chat_model, run_id, messages)
        kwargs = self._main_chat_runtime_policy_kwargs()
        run = await asyncio.to_thread(execute_loop, run_id, messages, **kwargs)
        status = str(run.get("status") or "").strip()
        result = str(run.get("result") or "").strip()
        if status == "approval_required":
            self._update_processing_message(
                chat_session,
                task.task_id,
                self._approval_required_content(run),
            )
            return await self._wait_for_main_chat_run_output(
                service,
                run_id,
                chat_session,
                task,
                previous_result=result,
            )
        if status in {"failed", "cancelled"}:
            raise NativeAgentError(
                result or f"Native Run {status}",
                reason=status,
            )
        if result:
            return result
        return await asyncio.to_thread(service.call_main_chat_model, run_id, messages)

    def _main_chat_runtime_policy_kwargs(self) -> dict[str, dict[str, Any]]:
        kwargs: dict[str, dict[str, Any]] = {}
        tool_policy = self._safe_policy_get(self._tool_policy_getter)
        if tool_policy is not None:
            kwargs["tool_policy"] = tool_policy
        workspace_policy = self._safe_policy_get(self._workspace_policy_getter)
        if workspace_policy is not None:
            kwargs["workspace_policy"] = workspace_policy
        return kwargs

    @staticmethod
    def _safe_policy_get(getter: Optional[Callable[[], dict[str, Any]]]) -> dict[str, Any] | None:
        if getter is None:
            return None
        try:
            value = getter()
        except Exception:
            logger.debug("读取 Native Agent runtime policy 失败", exc_info=True)
            return None
        return dict(value) if isinstance(value, dict) else None

    async def _wait_for_main_chat_run_output(
        self,
        service: Any,
        run_id: str,
        chat_session: Optional["ChatSession"],
        task: TaskInfo,
        *,
        previous_result: str = "",
    ) -> str:
        timeout_seconds = self._approval_wait_timeout_seconds()
        deadline = time.monotonic() + timeout_seconds
        last_status = ""
        while time.monotonic() < deadline:
            run = await asyncio.to_thread(service.get_run, run_id)
            status = str(run.get("status") or "").strip()
            result = str(run.get("result") or "").strip()
            if status != last_status:
                last_status = status
                if status == "approval_required":
                    self._update_processing_message(
                        chat_session,
                        task.task_id,
                        self._approval_required_content(run),
                    )
            if status == "approval_required":
                await asyncio.sleep(0.5)
                continue
            if status in {"failed", "cancelled"}:
                raise NativeAgentError(result or f"Native Run {status}", reason=status)
            if status in {"running", "processing"} and result and result != previous_result and not result.startswith("已批准，"):
                return result
            if status == "completed" and result:
                return result
            await asyncio.sleep(0.5)
        try:
            timeout_approval = getattr(service, "timeout_run_approval", None)
            if callable(timeout_approval):
                await asyncio.to_thread(timeout_approval, run_id, reason="approval_wait_timeout")
            else:
                await asyncio.to_thread(service.cancel_run, run_id)
        except Exception:
            logger.debug("Native Run 审批等待超时后取消失败: %s", run_id, exc_info=True)
        raise NativeAgentError("Native Agent 等待工具审批超时", reason="approval_timeout")

    @staticmethod
    def _approval_wait_timeout_seconds() -> float:
        raw = os.getenv("OHA_YACHIYO_MAIN_CHAT_APPROVAL_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return 600.0
        try:
            value = float(raw)
        except ValueError:
            return 600.0
        return max(1.0, value)

    @staticmethod
    def _approval_required_content(run: dict[str, Any]) -> str:
        pending = run.get("pending_approval") if isinstance(run.get("pending_approval"), dict) else {}
        tool = str(pending.get("tool") or "tool").strip()
        lines = [f"等待审批：{tool}"]
        preview = pending.get("input_preview")
        if preview:
            try:
                preview_text = json.dumps(preview, ensure_ascii=False, indent=2)
            except TypeError:
                preview_text = str(preview)
            lines.append(preview_text[:2000])
        return "\n".join(lines).strip()

    @staticmethod
    def _task_user_content(description: str, image_paths: list[str]) -> Any:
        if not image_paths:
            return description
        content: list[dict[str, Any]] = [{"type": "text", "text": description}]
        for raw_path in image_paths[:_MAIN_CHAT_IMAGE_ATTACHMENT_LIMIT]:
            path = Path(raw_path)
            try:
                data = path.read_bytes()
            except OSError:
                logger.debug("Native Agent 无法读取图片附件: %s", path, exc_info=True)
                continue
            if len(data) > _MAIN_CHAT_IMAGE_MAX_BYTES:
                logger.warning("Native Agent 跳过过大图片附件: %s", path)
                continue
            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            encoded = base64.b64encode(data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                }
            )
        return content

    @staticmethod
    def _update_processing_message(
        chat_session: Optional["ChatSession"],
        task_id: str,
        content: str,
    ) -> None:
        if chat_session is None:
            return
        try:
            from apps.core.chat_session import MessageStatus

            chat_session.upsert_assistant_message(
                task_id=task_id,
                content=content,
                status=MessageStatus.PROCESSING,
            )
        except Exception:
            logger.debug("Native Agent processing 消息更新失败", exc_info=True)

    def _record_activity(
        self,
        task: TaskInfo,
        title: str,
        detail: str,
        status: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._activity_store().record_event(
                session_id=str(getattr(task, "chat_session_id", "") or ""),
                task_id=task.task_id,
                tool_name="oha.delegation",
                phase="subagent",
                title=title,
                detail=detail,
                status=status,
                metadata=metadata or {},
            )
        except Exception:
            logger.debug("Native Agent 委派活动写入失败", exc_info=True)

    def _activity_store(self) -> "ActivityStore":
        if self._activity_store_getter is not None:
            return self._activity_store_getter()
        from apps.core.activity_store import get_activity_store

        return get_activity_store()

    def _chat_session_for_task(self, task: TaskInfo) -> Optional["ChatSession"]:
        session_id = str(getattr(task, "chat_session_id", "") or "")
        current = self._chat_session
        if not session_id:
            return current
        if current is not None and current.session_id == session_id:
            return current
        try:
            from apps.core.chat_session import ChatSession
            from apps.core.chat_store import get_chat_store

            session = ChatSession(session_id=session_id)
            session.attach_store(
                get_chat_store(),
                load_existing=True,
                fail_active_messages=False,
            )
            return session
        except Exception:
            logger.debug("无法为 Native Agent 任务加载聊天会话: %s", session_id, exc_info=True)
            return current


def _is_key_activity_event(event: dict[str, Any]) -> bool:
    """Keep the durable activity log to meaningful task/tool milestones."""
    phase = str(event.get("phase") or "").strip()
    status = str(event.get("status") or "").strip()
    tool_name = str(event.get("tool_name") or "").strip()
    if phase in {"thinking", "reasoning", "tool_progress"}:
        return False
    if status in {"completed", "failed", "error", "cancelled"}:
        return True
    if phase in {"task_start", "task_complete", "task_failed", "task_cancelled"}:
        return True
    if phase == "subagent":
        return True
    if phase in {"tool_start", "tool_complete"}:
        return bool(tool_name)
    return False


# ── 执行器选择工厂 ────────────────────────────────────────────────────────────

def select_executor(runtime: "AppRuntime | None" = None) -> ExecutionStrategy:
    """Select the native TaskRunner adapter."""
    try:
        if runtime is not None and hasattr(runtime, "native_agent_readiness"):
            readiness = runtime.native_agent_readiness()
        else:
            from apps.shell.agent_runtime import get_native_agent_readiness

            readiness = get_native_agent_readiness()
    except Exception as exc:
        logger.warning("select_executor: Native Agent readiness 检查失败: %s", exc)
        readiness = {
            "ready": False,
            "reason": "model_profile_unavailable",
            "message": redact_api_error_text(exc),
        }

    if readiness.get("ready"):
        logger.info("select_executor: 选用 NativeAgentExecutor")
        return NativeAgentExecutor(
            chat_session=getattr(runtime, "chat_session", None),
            persona_prompt_getter=(
                (lambda: runtime.config.assistant.persona_prompt)
                if runtime is not None and hasattr(runtime, "config")
                else None
            ),
            user_address_getter=(
                (lambda: runtime.config.assistant.user_address)
                if runtime is not None and hasattr(runtime, "config")
                else None
            ),
            profile_context_getter=(
                (lambda: build_runtime_profile_context(runtime))
                if runtime is not None and hasattr(runtime, "config")
                else None
            ),
            runtime_service_getter=(
                (lambda: runtime.agent_runtime_service)
                if runtime is not None and hasattr(runtime, "agent_runtime_service")
                else None
            ),
            tool_policy_getter=(
                (lambda: runtime.main_chat_tool_policy())
                if runtime is not None and hasattr(runtime, "main_chat_tool_policy")
                else None
            ),
            workspace_policy_getter=(
                (lambda: runtime.main_chat_workspace_policy())
                if runtime is not None and hasattr(runtime, "main_chat_workspace_policy")
                else None
            ),
            activity_store_getter=(
                (lambda: runtime.activity_store)
                if runtime is not None and hasattr(runtime, "activity_store")
                else None
            ),
        )

    return NativeAgentUnavailableExecutor(
        str(readiness.get("message") or NATIVE_AGENT_NOT_READY_MESSAGE),
        reason=str(readiness.get("reason") or "model_profile_required"),
    )


def describe_native_agent_unavailable(runtime: "AppRuntime | None" = None) -> str:
    """返回适合展示给用户的 Native Agent 未就绪原因。"""
    if runtime is not None and hasattr(runtime, "native_agent_readiness"):
        try:
            readiness = runtime.native_agent_readiness()
            message = str(readiness.get("message") or "").strip()
            if message:
                return message
        except Exception:
            logger.debug("读取 Native Agent readiness 失败", exc_info=True)
    return NATIVE_AGENT_NOT_READY_MESSAGE


def user_task_unavailable_reason(runtime: Any) -> str | None:
    """用户任务入口是否应拒绝创建任务；可用时返回 None。"""
    if not hasattr(runtime, "task_runner"):
        return None
    runner = getattr(runtime, "task_runner", None)
    executor = getattr(runner, "executor", None)
    if execution_capabilities(executor).get("model"):
        return None
    reason = str(getattr(executor, "reason", "") or "").strip()
    if reason:
        return reason
    return NATIVE_AGENT_NOT_READY_MESSAGE


def user_task_unavailable_payload(runtime: Any) -> dict[str, str] | None:
    reason = user_task_unavailable_reason(runtime)
    if reason is None:
        return None
    runner = getattr(runtime, "task_runner", None)
    executor = getattr(runner, "executor", None)
    return {
        "code": str(getattr(executor, "code", "") or "native_agent_not_ready"),
        "reason": str(getattr(executor, "reason_code", "") or "model_profile_required"),
        "error": reason,
    }
