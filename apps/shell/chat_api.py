"""聊天 WebView API

为 Chat Window、Control Center、Bubble、Live2D 提供统一的聊天消息接口。
通过 ChatSession 管理消息状态，通过 AppState 创建任务。

职责：
  - send_message(): 发送用户消息并创建任务
  - get_messages(): 获取消息列表（含任务状态同步）
  - get_session_info(): 获取会话元信息
  - clear_session(): 清空会话
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List
from uuid import uuid4

from apps.core.chat_session import (
    ChatMessage,
    ChatSession,
    MessageRole,
    MessageStatus,
)
from apps.core.activity_store import get_activity_store
from apps.core.executor import user_task_unavailable_reason
from apps.core.special_sessions import is_proactive_chat_session
from apps.locald.screenshot import capture_screenshot_to_file
from apps.shell.agent_runtime import AgentRuntimeError, get_agent_runtime_service
from apps.shell.hermes_capabilities import get_current_hermes_image_input_capability
from packages.protocol.enums import TaskStatus, TaskType

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime

logger = logging.getLogger(__name__)

_MAX_CHAT_ATTACHMENTS = 4
_MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
_MAX_ATTACHMENT_CACHE_BYTES = int(os.getenv("HERMES_YACHIYO_ATTACHMENT_CACHE_BYTES", str(512 * 1024 * 1024)))
_MAX_ATTACHMENT_CACHE_AGE_SECONDS = int(
    os.getenv("HERMES_YACHIYO_ATTACHMENT_CACHE_AGE_SECONDS", str(30 * 24 * 60 * 60))
)
_DATA_URL_RE = re.compile(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.*)$", re.DOTALL)
_IMAGE_EXTENSIONS_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}
_AUDIO_MIME_BY_EXTENSION = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}
_DESKTOP_SNAPSHOT_REQUEST_RE = re.compile(
    r"("
    r"(?:^|[\s，。！？、；;,.!?])"
    r"(?:请你?|麻烦你?|劳烦你?|帮我|帮忙|你(?:(?:可以|能不能|能否|能|帮我|来)|(?=(?:看|看看|查看|瞧|识别|分析|读|读取|扫一眼|检查|截)))|Yachiyo|八千代|Agent|agent|助手)"
    r".{0,18}(?:看|看看|查看|瞧|识别|分析|读|读取|扫一眼|检查|能看到|能看见|看得到)"
    r".{0,18}(?:桌面|屏幕|当前窗口|当前画面|截图|截屏)"
    r"|"
    r"(?:^|[\s，。！？、；;,.!?])"
    r"(?:请你?|麻烦你?|劳烦你?|帮我|帮忙|你(?:(?:可以|能不能|能否|能|帮我|来)|(?=(?:看|看看|查看|瞧|识别|分析|读|读取|扫一眼|检查|截)))|Yachiyo|八千代|Agent|agent|助手)"
    r".{0,18}(?:桌面|屏幕|当前窗口|当前画面|截图|截屏)"
    r".{0,18}(?:看|看看|查看|瞧|识别|分析|读|读取|检查|有什么|是什么|情况|状态|能看到|能看见|看得到)"
    r"|"
    r"(?:^|[\s，。！？、；;,.!?])"
    r"(?:请你?|麻烦你?|劳烦你?|帮我|帮忙|你(?:(?:可以|能不能|能否|能|帮我|来)|(?=(?:看|看看|查看|瞧|识别|分析|读|读取|扫一眼|检查|截)))|Yachiyo|八千代|Agent|agent|助手)"
    r".{0,18}(?:截(?:个|一张|一下)?图|截(?:个|一下)?屏|截图|截屏)"
    r"|"
    r"(?:please|can you|could you|would you|help me|agent|assistant|yachiyo)"
    r".{0,24}(?:look|see|view|read|analy[sz]e|inspect|screenshot|screen shot)"
    r".{0,24}(?:screen|desktop|window|screenshot)"
    r"|"
    r"(?:please|can you|could you|would you|help me|agent|assistant|yachiyo)"
    r".{0,24}(?:screen|desktop|window|screenshot)"
    r".{0,24}(?:look|see|view|read|analy[sz]e|inspect)"
    r"|"
    r"(?:screen|desktop|window|screenshot)"
    r".{0,12}(?:please|can you|could you|would you)"
    r".{0,24}(?:look|see|view|read|analy[sz]e|inspect)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_CHAT_VISIBLE_ACTIVITY_PHASES = {"tool_start", "tool_complete"}
_MAIN_MODEL_ALIASES = (
    "hermes chat",
    "main model",
    "main-model",
    "main",
    "主模型",
    "主助手",
    "八千代",
    "月見八千代",
    "月见八千代",
    "yachiyo",
    "hermes",
)
_MAIN_MODEL_ALIAS_SEPARATORS = set(" \t\r\n:：,，、;；")


def _compact_preview(value: Any, limit: int = 72) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _search_snippet(value: str, query: str, *, limit: int = 96) -> str:
    text = " ".join(str(value or "").split())
    needle = " ".join(str(query or "").split()).strip()
    if not text:
        return ""
    if not needle:
        return _compact_preview(text, limit)
    index = text.lower().find(needle.lower())
    if index < 0:
        return _compact_preview(text, limit)
    side = max(12, (limit - len(needle)) // 2)
    start = max(0, index - side)
    end = min(len(text), index + len(needle) + side)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = f"...{snippet}"
    if end < len(text):
        snippet = f"{snippet}..."
    return snippet


def _is_chat_visible_activity(event: dict[str, Any]) -> bool:
    phase = str(event.get("phase") or "")
    tool_name = str(event.get("tool_name") or "")
    return phase in _CHAT_VISIBLE_ACTIVITY_PHASES and bool(tool_name)


def _attachment_root() -> Path:
    hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
    root = Path(hermes_home) / "yachiyo" / "attachments"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _attachment_public_url(attachment_id: str) -> str:
    bridge_url = os.getenv("HERMES_YACHIYO_BRIDGE_URL", "http://127.0.0.1:8420").rstrip("/")
    return f"{bridge_url}/ui/chat/attachments/{attachment_id}"


def allocate_chat_attachment_path(session_id: str, suffix: str) -> tuple[str, Path]:
    """Allocate a stable attachment path under the chat attachment cache."""
    attachment_id = uuid4().hex
    normalized_suffix = suffix if str(suffix or "").startswith(".") else f".{suffix or 'bin'}"
    safe_suffix = re.sub(r"[^A-Za-z0-9.]+", "", normalized_suffix) or ".bin"
    session_dir = _attachment_root() / (session_id or "default")
    session_dir.mkdir(parents=True, exist_ok=True)
    return attachment_id, session_dir / f"{attachment_id}{safe_suffix}"


def chat_attachment_record(
    attachment_id: str,
    path: Path | str,
    *,
    kind: str,
    name: str,
    mime_type: str,
) -> dict[str, Any]:
    resolved = Path(path)
    return {
        "id": attachment_id,
        "kind": kind,
        "name": name or resolved.name,
        "mime_type": mime_type,
        "size": resolved.stat().st_size if resolved.exists() else 0,
        "path": str(resolved),
    }


def audio_mime_type_for_suffix(suffix: str) -> str:
    return _AUDIO_MIME_BY_EXTENSION.get(str(suffix or "").lower(), "audio/wav")


def _sanitize_attachment_name(value: str) -> str:
    name = Path(value or "image").name.strip() or "image"
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name)[:96] or "image"


def _cleanup_attachment_cache(protected_paths: set[Path] | None = None) -> None:
    """Keep image attachment storage bounded.

    Attachments live on disk for chat history previews.  This cleanup only runs
    after new attachments are saved, removes files older than the retention
    window first, then trims oldest files if the cache still exceeds the cap.
    """
    root = _attachment_root()
    protected = {path.resolve() for path in protected_paths or set()}
    now = time.time()
    files: list[tuple[float, int, Path]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
            stat = path.stat()
        except OSError:
            continue
        if resolved in protected:
            continue
        files.append((stat.st_mtime, stat.st_size, path))

    for mtime, _size, path in files:
        if _MAX_ATTACHMENT_CACHE_AGE_SECONDS > 0 and now - mtime > _MAX_ATTACHMENT_CACHE_AGE_SECONDS:
            try:
                path.unlink()
            except OSError:
                pass

    if _MAX_ATTACHMENT_CACHE_BYTES <= 0:
        return

    remaining: list[tuple[float, int, Path]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
            stat = path.stat()
        except OSError:
            continue
        if resolved in protected:
            continue
        remaining.append((stat.st_mtime, stat.st_size, path))

    total = sum(size for _mtime, size, _path in remaining)
    for _mtime, size, path in sorted(remaining, key=lambda item: item[0]):
        if total <= _MAX_ATTACHMENT_CACHE_BYTES:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            pass


def _remove_attachment_session_dir(session_id: str) -> None:
    session_id = (session_id or "").strip()
    if not re.fullmatch(r"[a-f0-9]{8}", session_id):
        return
    target = _attachment_root() / session_id
    try:
        resolved = target.resolve()
        root = _attachment_root().resolve()
    except OSError:
        return
    if root not in resolved.parents or not resolved.exists():
        return
    shutil.rmtree(resolved, ignore_errors=True)


class ChatAPI:
    """聊天 API（供 WebView JavaScript 调用）"""

    def __init__(self, runtime: "HermesRuntime") -> None:
        self._runtime = runtime

    @property
    def _session(self) -> ChatSession:
        return self._runtime.chat_session

    @property
    def _state(self):
        return self._runtime.state

    def _chat_store(self):
        store = getattr(self._runtime, "store", None)
        if store is not None:
            return store
        from apps.core.chat_store import get_chat_store

        return get_chat_store()

    def send_message(
        self,
        text: str,
        attachments: list[dict] | None = None,
        *,
        runnable_id: str = "",
    ) -> Dict[str, Any]:
        """发送用户消息并创建对应任务

        流程：
          1. 添加用户消息到 ChatSession
          2. 创建任务到 AppState（触发 TaskRunner 执行）
          3. 关联消息与任务
          4. 返回 message_id 和 task_id

        Args:
            text: 用户消息内容

        Returns:
            {"ok": True, "message_id": str, "task_id": str, "status": "pending"}
            或 {"ok": False, "error": str}
        """
        text = (text or "").strip()
        raw_attachments = attachments or []
        if not text and not raw_attachments:
            return {"ok": False, "error": "消息内容不能为空"}

        try:
            runnable_command = self._handle_runnable_command(text, raw_attachments, runnable_id=runnable_id)
            if runnable_command is not None:
                return runnable_command

            unavailable_reason = user_task_unavailable_reason(self._runtime)
            if unavailable_reason:
                return {"ok": False, "error": unavailable_reason}

            current_context = self._session_context()
            task_text = self._main_model_goal_text(text)

            if raw_attachments and self._should_enforce_image_capability():
                image_input = get_current_hermes_image_input_capability()
                if image_input.get("can_attach_images") is False:
                    return {
                        "ok": False,
                        "error": str(image_input.get("reason") or "当前 Hermes 模型暂不支持图片输入"),
                        "image_input": image_input,
                    }
            saved_attachments = self._save_attachments(raw_attachments)
            if not text and saved_attachments:
                text = "请识别并分析这张图片。"
                task_text = text
            should_attach_desktop_snapshot = self._should_attach_desktop_snapshot(task_text, saved_attachments)
            if should_attach_desktop_snapshot and self._should_enforce_image_capability():
                image_input = get_current_hermes_image_input_capability()
                if image_input.get("can_attach_images") is False:
                    return {
                        "ok": False,
                        "error": str(image_input.get("reason") or "当前 Hermes 模型暂不支持图片输入"),
                        "image_input": image_input,
                    }
            task_description, saved_attachments = self._attach_desktop_snapshot_if_needed(
                task_text,
                saved_attachments,
                should_attach=should_attach_desktop_snapshot,
            )
            task_description = self._with_group_context_for_main_model(task_description, current_context)
            if saved_attachments and not raw_attachments and self._should_enforce_image_capability():
                image_input = get_current_hermes_image_input_capability()
                if image_input.get("can_attach_images") is False:
                    return {
                        "ok": False,
                        "error": str(image_input.get("reason") or "当前 Hermes 模型暂不支持图片输入"),
                        "image_input": image_input,
                    }

            # 1. 添加用户消息
            message_id = self._session.add_user_message(text, saved_attachments)

            # 2. 创建任务
            task = self._state.create_task(
                task_type=TaskType.GENERAL,
                description=task_description,
                attachments=saved_attachments,
                chat_session_id=self._session.session_id,
            )
            task_id = task.task_id

            # 3. 关联消息与任务
            self._session.link_message_to_task(message_id, task_id)

            logger.info(
                "消息已发送: message_id=%s, task_id=%s, len=%d, attachments=%d",
                message_id,
                task_id,
                len(task_description),
                len(saved_attachments),
            )

            return {
                "ok": True,
                "message_id": message_id,
                "task_id": task_id,
                "status": "pending",
                "attachments": self._serialize_attachments(saved_attachments),
            }

        except Exception as exc:
            logger.error("发送消息失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def _handle_runnable_command(
        self,
        text: str,
        raw_attachments: list[dict],
        *,
        runnable_id: str = "",
    ) -> Dict[str, Any] | None:
        text = (text or "").strip()
        if not runnable_id and self._parse_main_model_mention(text) is not None:
            return None

        current_context = self._session_context()
        explicit_target = bool(str(runnable_id or "").strip())
        if (
            not explicit_target
            and not self._has_chat_mention(text)
            and current_context.get("conversation_kind") != "agent"
        ):
            return None

        service = get_agent_runtime_service()
        name = ""
        user_goal = text
        runnable: dict[str, Any] | None = None

        try:
            if explicit_target:
                runnable = service.resolve_runnable(runnable_id=str(runnable_id or "").strip())
            elif self._has_chat_mention(text):
                parsed = service.parse_known_chat_runnable(text)
                if parsed is None:
                    return None
                name, user_goal = parsed
                explicit_target = True
                runnable = service.resolve_runnable(name=name)
            elif current_context.get("conversation_kind") == "agent":
                runnable = service.resolve_runnable(runnable_id=str(current_context.get("runnable_id") or ""))
                user_goal = text
        except AgentRuntimeError as exc:
            return self._record_runnable_error(text, str(exc), context=current_context)

        if runnable is None:
            return self._record_runnable_error(text, "未找到指定 Agent 或 Workflow", context=current_context)

        keep_workflow_group = (
            explicit_target
            and current_context.get("conversation_kind") == "workflow"
            and runnable.get("kind") == "agent"
            and bool(current_context.get("run_group_id"))
        )
        keep_manual_group = (
            explicit_target
            and current_context.get("conversation_kind") == "group"
            and runnable.get("kind") == "agent"
        )
        if keep_manual_group:
            if not self._group_context_contains_runnable(
                current_context,
                runnable,
                {
                    "target": name,
                    "runnable_id": str(runnable.get("id") or ""),
                },
            ):
                display_name = str(runnable.get("nickname") or runnable.get("name") or "Agent").strip() or "Agent"
                return self._record_runnable_error(
                    text,
                    f"{display_name} 不在当前群组中。请先在群组设置中加入后再 @。",
                    runnable=runnable,
                    context=current_context,
                )
        if not keep_workflow_group and not keep_manual_group:
            self._prepare_runnable_session(
                runnable,
                explicit_target=explicit_target,
                current_context=current_context,
            )
            current_context = self._session_context()

        if raw_attachments:
            content = "Agent/Workflow 运行入口暂不支持附件。请把附件内容先整理成文字，或使用普通对话发送图片。"
            return self._record_runnable_error(text, content, runnable=runnable, context=current_context)
        if not user_goal:
            content = "运行目标不能为空。请在 Agent/Workflow 名称后写明需求。"
            return self._record_runnable_error(text, content, runnable=runnable, context=current_context)

        target = self._participant_for_runnable(runnable)
        run_group_id = ""
        if current_context.get("conversation_kind") in {"agent", "workflow", "group"}:
            run_group_id = str(current_context.get("run_group_id") or "")
        user_metadata = {
            "target": target,
            "runnable_kind": runnable.get("kind") or "",
            "runnable_id": runnable.get("id") or "",
            "run_group_id": run_group_id,
        }
        message_content = text or user_goal
        should_set_runnable_title = (
            current_context.get("conversation_kind") != "group"
            and self._session.message_count() == 0
            and bool(user_goal)
        )
        message_id = self._session.add_user_message(message_content, [], metadata=user_metadata)
        if should_set_runnable_title:
            self._set_session_title_from_message(user_goal)
        upstream = self._chat_upstream_context()
        if current_context.get("conversation_kind") == "group" and runnable.get("kind") == "agent":
            upstream = self._with_group_context_for_agent_upstream(upstream, current_context, target)

        # 判断是否为 Workflow（同步执行）
        is_workflow = runnable.get("kind") == "workflow"

        if is_workflow:
            # Workflow 保持同步执行
            try:
                run = service.create_run_for_runnable(
                    runnable_id=str(runnable.get("id") or ""),
                    name=name,
                    user_goal=user_goal,
                    run_group_id=run_group_id,
                    upstream=upstream,
                )
            except AgentRuntimeError as exc:
                content = str(exc)
                self._session.mark_message_completed(message_id)
                assistant_id = self._session.add_assistant_message(
                    content,
                    metadata={"sender": self._main_model_sender(), "runnable_kind": "workflow"},
                )
                return {
                    "ok": True,
                    "runnable_command": True,
                    "message_id": message_id,
                    "assistant_message_id": assistant_id,
                    "task_id": "",
                    "status": "completed",
                    "error": content,
                }

            self._session.mark_message_completed(message_id)
            runnable = run.get("runnable") or runnable
            if current_context.get("conversation_kind") == "group":
                self._bind_group_session_context(current_context, run_group_id=str(run.get("run_group_id") or ""))
            else:
                self._bind_session_context("workflow", runnable, run_group_id=str(run.get("run_group_id") or ""))
            assistant_ids = self._append_workflow_run_messages(service, run, runnable)

            return {
                "ok": True,
                "runnable_command": True,
                "message_id": message_id,
                "assistant_message_id": assistant_ids[-1] if assistant_ids else "",
                "assistant_message_ids": assistant_ids,
                "task_id": "",
                "status": "completed",
                "run_id": run["run_id"],
                "run_group_id": run.get("run_group_id", ""),
                "run_status": run["status"],
                "workflow_run_id": run["run_id"],
            }

        # Agent Run - 异步执行
        sender = self._participant_for_runnable(runnable)
        initial_content = ""
        is_group_context = current_context.get("conversation_kind") == "group"
        assistant_id = self._session.add_assistant_message(
            initial_content,
            metadata={
                "sender": sender,
                "runnable_kind": "agent",
                "runnable_id": runnable.get("id") or "",
                "run_group_id": run_group_id,
                "run_status": "processing",
                "conversation_kind": "group" if is_group_context else "",
                "group_goal": user_goal if is_group_context else "",
            },
        )
        # 标记为 processing 状态
        from apps.core.chat_session import MessageStatus
        self._session.update_assistant_message(
            assistant_id,
            initial_content,
            status=MessageStatus.PROCESSING,
        )

        def _on_run_complete(run_result: dict[str, Any]) -> None:
            """Agent Run 完成后的回调"""
            self._update_agent_run_message_from_result(assistant_id, sender, run_result)
            logger.info("Agent Run 异步完成: run_id=%s, status=%s", run_result.get("run_id"), run_result.get("status"))

        try:
            run = service.create_run_for_runnable_async(
                runnable_id=str(runnable.get("id") or ""),
                name=name,
                user_goal=user_goal,
                run_group_id=run_group_id,
                upstream=upstream,
                on_complete=_on_run_complete,
            )
        except AgentRuntimeError as exc:
            content = str(exc)
            self._session.update_assistant_message(
                assistant_id,
                content,
                status=MessageStatus.FAILED,
                error=content,
            )
            self._session.mark_message_completed(message_id)
            return {
                "ok": True,
                "runnable_command": True,
                "message_id": message_id,
                "assistant_message_id": assistant_id,
                "task_id": "",
                "status": "completed",
                "error": content,
            }

        self._session.mark_message_completed(message_id)
        runnable = run.get("runnable") or runnable
        self._attach_processing_agent_run_metadata(assistant_id, initial_content, run)

        if current_context.get("conversation_kind") == "group":
            self._bind_group_session_context(current_context, run_group_id=str(run.get("run_group_id") or ""))
        elif current_context.get("conversation_kind") != "workflow":
            self._bind_session_context("agent", runnable, run_group_id=str(run.get("run_group_id") or ""))

        return {
            "ok": True,
            "runnable_command": True,
            "message_id": message_id,
            "assistant_message_id": assistant_id,
            "assistant_message_ids": [assistant_id],
            "task_id": "",
            "status": "processing",
            "run_id": run["run_id"],
            "run_group_id": run.get("run_group_id", ""),
            "run_status": "processing",
            "agent_run_id": run["run_id"],
        }

    def _prepare_runnable_session(
        self,
        runnable: dict[str, Any],
        *,
        explicit_target: bool,
        current_context: dict[str, Any],
    ) -> None:
        if not explicit_target:
            return
        if (
            current_context.get("conversation_kind") == "agent"
            and runnable.get("kind") == "agent"
            and current_context.get("runnable_id") == runnable.get("id")
        ):
            return

        if self._current_session_has_messages():
            start_new_session = getattr(self._runtime, "start_new_session", None)
            if callable(start_new_session):
                start_new_session()
            else:
                self._session.clear()

        if runnable.get("kind") == "agent":
            self._bind_session_context("agent", runnable, run_group_id="")
        elif runnable.get("kind") == "workflow":
            self._bind_session_context("workflow", runnable, run_group_id="")

    def _record_runnable_error(
        self,
        text: str,
        content: str,
        *,
        runnable: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        target = self._participant_for_runnable(runnable) if runnable else self._main_model_sender()
        context = context or self._session_context()
        message_content = (text or "").strip() or "（附件暂未发送给 Agent/Workflow）"
        message_id = self._session.add_user_message(
            message_content,
            [],
            metadata={
                "target": target,
                "runnable_kind": runnable.get("kind") if runnable else "",
                "run_group_id": context.get("run_group_id") or "",
            },
        )
        self._session.mark_message_completed(message_id)
        assistant_id = self._session.add_assistant_message(
            content,
            error=content,
            metadata={
                "sender": self._main_model_sender(),
                "runnable_kind": runnable.get("kind") if runnable else "",
                "run_group_id": context.get("run_group_id") or "",
            },
        )
        return {
            "ok": True,
            "runnable_command": True,
            "message_id": message_id,
            "assistant_message_id": assistant_id,
            "assistant_message_ids": [assistant_id],
            "task_id": "",
            "status": "completed",
            "error": content,
        }

    def _append_agent_run_message(self, run: dict[str, Any], runnable: dict[str, Any]) -> str:
        sender = self._participant_for_runnable(runnable)
        status = str(run.get("status") or "")
        content = str(run.get("result") or "").strip()
        if status == "approval_required":
            content = self._approval_required_content(sender, run)
        if not content:
            content = self._run_status_sentence(sender.get("name") or "Agent", status)
        return self._session.add_assistant_message(
            content,
            error=content if status == "failed" else None,
            metadata={
                "sender": sender,
                "runnable_kind": "agent",
                "runnable_id": runnable.get("id") or run.get("runnable_id") or "",
                "run_id": run.get("run_id") or "",
                "run_group_id": run.get("run_group_id") or "",
                "run_status": status,
                "pending_approval": run.get("pending_approval") if isinstance(run.get("pending_approval"), dict) else {},
            },
        )

    def _append_workflow_run_messages(
        self,
        service: Any,
        run: dict[str, Any],
        runnable: dict[str, Any],
    ) -> list[str]:
        assistant_ids: list[str] = []
        for event in run.get("timeline") or []:
            if not isinstance(event, dict) or event.get("event") != "workflow.node.agent":
                continue
            child_run_id = str(event.get("child_run_id") or "").strip()
            if not child_run_id:
                continue
            try:
                child = service.get_run(child_run_id)
                child_runnable = service.resolve_runnable(runnable_id=str(child.get("runnable_id") or "")) or {}
            except Exception:
                logger.debug("读取 Workflow 子 Agent 运行失败: %s", child_run_id, exc_info=True)
                continue
            sender = self._participant_for_runnable(child_runnable)
            status = str(child.get("status") or "")
            content = str(child.get("result") or "").strip()
            if status == "approval_required":
                content = self._approval_required_content(sender, child)
            if not content:
                content = self._run_status_sentence(sender.get("name") or "Agent", status)
            assistant_ids.append(
                self._session.add_assistant_message(
                    content,
                    error=content if status == "failed" else None,
                    metadata={
                        "sender": sender,
                        "runnable_kind": "agent",
                        "runnable_id": child_runnable.get("id") or child.get("runnable_id") or "",
                        "run_id": child.get("run_id") or child_run_id,
                        "run_group_id": run.get("run_group_id") or child.get("run_group_id") or "",
                        "workflow_run_id": run.get("run_id") or "",
                        "workflow_node": event.get("detail") or "",
                        "run_status": status,
                        "pending_approval": child.get("pending_approval") if isinstance(child.get("pending_approval"), dict) else {},
                    },
                )
            )

        workflow_status = str(run.get("status") or "")
        workflow_name = str(runnable.get("name") or run.get("runnable_name") or "Workflow")
        result_text = str(run.get("result") or "").strip()
        if workflow_status == "completed" and assistant_ids:
            summary = f"{workflow_name} 已完成。"
        elif result_text:
            summary = f"{workflow_name} {self._workflow_status_label(workflow_status)}。\n\n{result_text}"
        else:
            summary = f"{workflow_name} {self._workflow_status_label(workflow_status)}。"
        assistant_ids.append(
            self._session.add_assistant_message(
                summary,
                error=summary if workflow_status == "failed" else None,
                metadata={
                    "sender": self._participant_for_runnable(runnable),
                    "runnable_kind": "workflow",
                    "runnable_id": runnable.get("id") or run.get("runnable_id") or "",
                    "run_id": run.get("run_id") or "",
                    "run_group_id": run.get("run_group_id") or "",
                    "workflow_status": workflow_status,
                },
            )
        )
        return assistant_ids

    @staticmethod
    def _run_status_sentence(name: str, status: str) -> str:
        if status == "completed":
            return f"{name} 已完成，但没有返回内容。"
        if status == "approval_required":
            return f"{name} 等待工具审批。"
        if status == "cancelled":
            return f"{name} 已取消。"
        if status == "failed":
            return f"{name} 执行失败。"
        return f"{name} 状态：{status or 'unknown'}。"

    @staticmethod
    def _workflow_status_label(status: str) -> str:
        if status == "completed":
            return "已完成"
        if status == "approval_required":
            return "等待审批"
        if status == "cancelled":
            return "已取消"
        if status == "failed":
            return "执行失败"
        return f"状态：{status or 'unknown'}"

    def _update_agent_run_message_from_result(
        self,
        message_id: str,
        sender: dict[str, Any],
        run_result: dict[str, Any],
    ) -> None:
        status = str(run_result.get("status") or "completed")
        existing_metadata = self._message_metadata(message_id)
        is_group_message = self._is_group_agent_message(existing_metadata)
        is_delegated_group_agent = is_group_message and bool(existing_metadata.get("delegated_by_task_id"))
        goal = str(existing_metadata.get("group_goal") or existing_metadata.get("delegated_goal") or "").strip()
        content = str(run_result.get("result") or "").strip()
        if status == "approval_required":
            content = self._approval_required_content(sender, run_result, goal=goal if is_group_message else "")
        if not content:
            content = self._run_status_sentence(sender.get("name") or "Agent", status)
        agent_report = content
        if is_delegated_group_agent and status in {"completed", "failed", "cancelled"}:
            content = self._group_delegated_agent_terminal_content(sender, status, goal)
        elif is_group_message and status in {"completed", "failed", "cancelled"}:
            content = self._group_agent_terminal_content(sender, status, content, goal)
        is_failed = status == "failed"
        message_status = self._message_status_for_run_status(status)
        pending_approval = run_result.get("pending_approval") if isinstance(run_result.get("pending_approval"), dict) else {}
        metadata_update = {
            "run_status": status,
            "run_id": run_result.get("run_id") or "",
            "run_group_id": run_result.get("run_group_id") or "",
            "pending_approval": pending_approval,
        }
        if is_delegated_group_agent and status in {"completed", "failed", "cancelled"}:
            metadata_update.update({
                "agent_report": agent_report,
                "agent_report_status": status,
            })
        self._session.update_assistant_message(
            message_id,
            content,
            status=message_status,
            error=content if is_failed else None,
            metadata=metadata_update,
        )
        if is_delegated_group_agent and status in {"completed", "failed", "cancelled"}:
            self._maybe_create_group_agent_summary_task(str(existing_metadata.get("delegated_by_task_id") or ""))

    def _message_metadata(self, message_id: str) -> dict[str, Any]:
        current = next(
            (msg for msg in self._session.get_all_messages() if msg.message_id == message_id),
            None,
        )
        metadata = current.metadata if current is not None and isinstance(current.metadata, dict) else {}
        return dict(metadata)

    @staticmethod
    def _is_group_agent_message(metadata: dict[str, Any]) -> bool:
        return (
            metadata.get("conversation_kind") == "group"
            or bool(metadata.get("delegated_by_task_id"))
            or bool(metadata.get("group_goal"))
        )

    @classmethod
    def _group_agent_terminal_content(
        cls,
        sender: dict[str, Any],
        status: str,
        content: str,
        goal: str,
    ) -> str:
        name = str(sender.get("nickname") or sender.get("name") or "Agent").strip() or "Agent"
        if status == "failed":
            intro = f"{name} 执行任务失败，需要主模型和用户查看。"
        elif status == "cancelled":
            intro = f"{name} 任务已取消。"
        else:
            intro = f"{name} 已完成任务，请主模型和用户验收。"
        lines = [intro]
        goal_text = _compact_preview(goal, 140)
        if goal_text:
            lines.append(f"任务：{goal_text}")
        body = str(content or "").strip()
        if body:
            lines.extend(["", body])
        return "\n".join(lines)

    @classmethod
    def _group_delegated_agent_terminal_content(
        cls,
        sender: dict[str, Any],
        status: str,
        goal: str,
    ) -> str:
        name = str(sender.get("nickname") or sender.get("name") or "Agent").strip() or "Agent"
        if status == "failed":
            intro = f"{name} 执行失败，已把失败原因交给主模型整理。"
        elif status == "cancelled":
            intro = f"{name} 任务已取消，已通知主模型。"
        else:
            intro = f"{name} 已完成，并把结果交给主模型汇总。"
        goal_text = _compact_preview(goal, 140)
        if goal_text:
            return f"{intro}\n任务：{goal_text}"
        return intro

    def _attach_processing_agent_run_metadata(self, message_id: str, content: str, run: dict[str, Any]) -> None:
        current = next(
            (msg for msg in self._session.get_all_messages() if msg.message_id == message_id),
            None,
        )
        if current is None or current.status != MessageStatus.PROCESSING:
            return
        metadata = current.metadata if isinstance(current.metadata, dict) else {}
        run_status = str(metadata.get("run_status") or "processing")
        if run_status not in {"", "pending", "processing"} or current.content != content:
            return
        self._session.update_assistant_message(
            message_id,
            content,
            status=MessageStatus.PROCESSING,
            metadata={
                "run_status": str(run.get("status") or "processing"),
                "run_id": run.get("run_id") or "",
                "run_group_id": run.get("run_group_id") or "",
            },
        )

    @classmethod
    def _approval_required_content(cls, sender: dict[str, Any], run_result: dict[str, Any], *, goal: str = "") -> str:
        name = str(
            sender.get("nickname")
            or sender.get("name")
            or run_result.get("runnable_name")
            or "Agent"
        ).strip()
        pending = run_result.get("pending_approval") if isinstance(run_result.get("pending_approval"), dict) else {}
        tool = str(pending.get("tool") or "").strip()
        if not tool:
            match = re.search(r"等待审批[:：]\s*(?P<tool>[A-Za-z0-9_.-]+)", str(run_result.get("result") or ""))
            tool = match.group("tool") if match else "tool"
        preview = cls._approval_input_preview_text(tool, pending.get("input_preview"))
        lines = [
            f"{name} 需要你确认一次工具调用，批准后会继续执行当前任务。",
            f"工具：{tool}",
        ]
        goal_text = _compact_preview(goal, 140)
        if goal_text:
            lines.append(f"关联任务：{goal_text}")
        if preview:
            lines.append(f"请求摘要：{preview}")
        return "\n".join(lines)

    @staticmethod
    def _approval_input_preview_text(tool: str, preview: Any) -> str:
        if isinstance(preview, dict):
            command = str(preview.get("command") or "").strip()
            if tool == "terminal.run" and command:
                return f"命令：{_compact_preview(command, 160)}"
            if tool == "workspace.write_patch":
                path = str(preview.get("path") or "").strip()
                content = str(preview.get("content") or "").strip()
                parts: list[str] = []
                if path:
                    parts.append(f"文件：{_compact_preview(path, 120)}")
                if content:
                    parts.append(f"写入内容：{_compact_preview(content, 160)}")
                if parts:
                    return "；".join(parts)
            parts = []
            for key, value in preview.items():
                if key in {"messages", "tool_request", "remaining_tool_requests"}:
                    continue
                text = _compact_preview(value, 80)
                if text:
                    parts.append(f"{key}={text}")
                if len(parts) >= 3:
                    break
            return "；".join(parts)
        if isinstance(preview, list):
            text = _compact_preview(json.dumps(preview, ensure_ascii=False), 180)
            return text
        return _compact_preview(preview, 180)

    @staticmethod
    def _message_status_for_run_status(status: str) -> MessageStatus:
        if status == "failed":
            return MessageStatus.FAILED
        if status in {"approval_required", "processing", "pending"}:
            return MessageStatus.PROCESSING
        return MessageStatus.COMPLETED

    def _bind_session_context(self, kind: str, runnable: dict[str, Any], *, run_group_id: str = "") -> None:
        conversation_kind = kind if kind in {"agent", "workflow", "group"} else "main"
        participants = [self._participant_for_runnable(runnable)] if conversation_kind == "agent" else self._workflow_participants(runnable)
        runnable_name = str(
            runnable.get("nickname")
            or runnable.get("name")
            or runnable.get("id")
            or ""
        )
        self._chat_store().update_session_context(
            self._session.session_id,
            conversation_kind=conversation_kind,
            runnable_id=str(runnable.get("id") or ""),
            runnable_name=runnable_name,
            run_group_id=str(run_group_id or ""),
            participants_json=json.dumps(participants, ensure_ascii=False),
            avatar_url="",
        )

    def _bind_group_session_context(self, context: dict[str, Any], *, run_group_id: str = "") -> None:
        participants = [
            item
            for item in (context.get("participants") or [])
            if isinstance(item, dict)
        ]
        name = str(context.get("runnable_name") or "群组").strip() or "群组"
        self._chat_store().update_session_context(
            self._session.session_id,
            conversation_kind="group",
            runnable_id=str(context.get("runnable_id") or ""),
            runnable_name=name,
            run_group_id=str(run_group_id or context.get("run_group_id") or ""),
            participants_json=json.dumps(participants, ensure_ascii=False),
            avatar_url=self._clean_group_avatar_url(str(context.get("avatar_url") or "")),
        )

    def _set_session_title_from_message(self, content: str) -> None:
        from apps.core.chat_store import make_session_title

        title = make_session_title(content)
        if title:
            self._session.set_session_title(title)

    def _session_context(self, record: Any | None = None) -> dict[str, Any]:
        if record is None:
            try:
                record = self._chat_store().get_session(self._session.session_id)
            except Exception:
                record = None
        kind = str(getattr(record, "conversation_kind", "") or "main")
        if kind not in {"main", "agent", "workflow", "group"}:
            kind = "main"
        participants = self._parse_participants_json(getattr(record, "participants_json", "[]") if record else "[]")
        return {
            "conversation_kind": kind,
            "runnable_id": str(getattr(record, "runnable_id", "") or ""),
            "runnable_name": str(getattr(record, "runnable_name", "") or ""),
            "run_group_id": str(getattr(record, "run_group_id", "") or ""),
            "avatar_url": str(getattr(record, "avatar_url", "") or ""),
            "participants": participants,
        }

    @staticmethod
    def _main_model_goal_text(text: str) -> str:
        value = (text or "").strip()
        if not value.startswith("@"):
            return value
        parsed = ChatAPI._parse_main_model_mention(value)
        if parsed is None:
            return value
        _, remainder = parsed
        return remainder.strip() or value

    @staticmethod
    def _participant_context_line(participant: dict[str, Any]) -> str:
        kind = str(participant.get("kind") or "").strip()
        display_name = str(
            participant.get("nickname")
            or participant.get("name")
            or participant.get("id")
            or ""
        ).strip()
        if not display_name:
            return ""
        role = {
            "main": "主模型",
            "agent": "Agent",
            "workflow": "Workflow",
        }.get(kind, kind or "成员")
        details = [role]
        full_name = str(participant.get("name") or "").strip()
        if full_name and full_name != display_name:
            details.append(full_name)
        return f"- {display_name}（{'；'.join(details)}）"

    def _with_group_context_for_main_model(self, task_description: str, context: dict[str, Any]) -> str:
        if context.get("conversation_kind") != "group":
            return task_description
        participants = [
            item
            for item in (context.get("participants") or [])
            if isinstance(item, dict)
        ]
        lines = [line for line in (self._participant_context_line(item) for item in participants) if line]
        if not lines:
            return task_description
        member_lines = "\n".join(lines)
        note = (
            "[Yachiyo 群组上下文]\n"
            "当前会话是群组，群成员包括：\n"
            f"{member_lines}\n"
            "当用户没有 @ 指定其他成员时，用户正在对你（主模型/Yachiyo）说话；你可以直接回答，也可以作为团队调度者拆分任务。\n"
            "当用户提到“群里”“群组里”的其他模型或 Agent 时，请只基于上述成员理解，不能派给不在群里的 Agent。\n"
            "如果你决定把任务交给群内 Agent，请先用自然语言说明你的计划，然后附加一个机器可读派活块，格式如下：\n"
            "<yachiyo_group_dispatch>\n"
            '{"tasks":[{"action":"dispatch_group_agent","agent":"群成员昵称或名称","goal":"完整、可执行、不可省略的任务说明"}]}\n'
            "</yachiyo_group_dispatch>\n"
            "可以一次派给多个 Agent，但每个 goal 都要独立完整，不能用“同上”“继续”等省略说法。\n"
            "被派出的 Agent 会在群聊里发布接收任务、执行结果、失败原因或待审批内容；你不要把派活 JSON 当作给用户阅读的正文。"
        )
        base = (task_description or "").strip()
        return f"{base}\n\n{note}" if base else note

    def _with_group_context_for_agent_upstream(
        self,
        upstream: str,
        context: dict[str, Any],
        participant: dict[str, Any],
    ) -> str:
        if context.get("conversation_kind") != "group":
            return upstream
        participants = [
            item
            for item in (context.get("participants") or [])
            if isinstance(item, dict)
        ]
        lines = [line for line in (self._participant_context_line(item) for item in participants) if line]
        name = str(participant.get("nickname") or participant.get("name") or "Agent").strip() or "Agent"
        member_lines = "\n".join(lines) if lines else "- 群成员信息暂不可用"
        note = (
            "[Yachiyo 群组执行约定]\n"
            f"当前任务来自群聊，你在群内身份是：{name}。\n"
            "请把输出写成可以直接发到群里的进度、结果、失败原因或待审批说明；不要把过程省略成只有一句“完成”。\n"
            "如果需要用户批准工具调用，请明确写出工具名称、为什么需要、将要执行/读取/修改的关键输入摘要。\n"
            "当前群成员包括：\n"
            f"{member_lines}"
        )
        base = (upstream or "").strip()
        return f"{base}\n\n{note}" if base else note

    def _current_session_has_messages(self) -> bool:
        try:
            return bool(self._chat_store().load_messages(self._session.session_id, limit=1))
        except Exception:
            return self._session.message_count() > 0

    def _chat_upstream_context(self, limit: int = 12) -> str:
        messages = self._session.get_messages(limit)
        lines: list[str] = []
        for msg in messages:
            text = " ".join(str(msg.content or "").split())
            if not text:
                continue
            label = "系统"
            if msg.role == MessageRole.USER:
                label = "用户"
            elif msg.role == MessageRole.ASSISTANT:
                sender = (msg.metadata or {}).get("sender") if isinstance(msg.metadata, dict) else {}
                label = str((sender or {}).get("nickname") or (sender or {}).get("name") or "Yachiyo")
            lines.append(f"{label}: {_compact_preview(text, 180)}")
        return "\n".join(lines[-limit:])

    @staticmethod
    def _participant_for_runnable(runnable: dict[str, Any] | None) -> dict[str, Any]:
        if not runnable:
            return {}
        kind = str(runnable.get("kind") or "agent")
        participant = {
            "kind": kind,
            "id": str(runnable.get("id") or ""),
            "name": str(runnable.get("name") or runnable.get("id") or ""),
        }
        if runnable.get("nickname"):
            participant["nickname"] = str(runnable.get("nickname") or "")
        if runnable.get("description"):
            participant["description"] = str(runnable.get("description") or "")
        if runnable.get("avatar_url"):
            participant["avatar_url"] = str(runnable.get("avatar_url") or "")
        if runnable.get("category"):
            participant["category"] = str(runnable.get("category") or "")
        if kind == "workflow":
            participant["participants"] = ChatAPI._workflow_participants(runnable)
        return participant

    @staticmethod
    def _workflow_participants(runnable: dict[str, Any] | None) -> list[dict[str, Any]]:
        participants = (runnable or {}).get("participants") or []
        if not isinstance(participants, list):
            return []
        return [
            ChatAPI._participant_for_runnable(item)
            for item in participants
            if isinstance(item, dict)
        ]

    @staticmethod
    def _main_model_sender() -> dict[str, Any]:
        return {
            "kind": "main",
            "id": "main",
            "name": "Yachiyo",
            "nickname": "月見八千代",
        }

    def _main_model_sender_from_runtime(self) -> dict[str, Any]:
        assistant = getattr(getattr(self._runtime, "config", None), "assistant", None)
        sender: dict[str, Any] = {
            "kind": "main",
            "id": "main",
            "name": str(getattr(assistant, "agent_name", "") or "Yachiyo"),
            "nickname": str(getattr(assistant, "agent_nickname", "") or "月見八千代"),
        }
        avatar_path = str(getattr(assistant, "agent_avatar_path", "") or "")
        if avatar_path:
            sender["avatar_path"] = avatar_path
        return sender

    @staticmethod
    def _parse_participants_json(value: str | None) -> list[dict[str, Any]]:
        if not value:
            return []
        try:
            data = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def _parse_main_model_mention(text: str) -> tuple[str, str] | None:
        value = (text or "").strip()
        match = re.search(r"(^|[\s，。！？、；;,.!?])@(?P<body>.+)$", value.splitlines()[0] if value else "")
        if not match:
            return None
        body = match.group("body").lstrip()
        body_lower = body.lower()
        for alias in sorted(_MAIN_MODEL_ALIASES, key=len, reverse=True):
            alias_lower = alias.lower()
            if body_lower == alias_lower:
                return alias, ""
            if not body_lower.startswith(alias_lower):
                continue
            remainder = body[len(alias):]
            if remainder and remainder[0] not in _MAIN_MODEL_ALIAS_SEPARATORS:
                continue
            return alias, remainder.lstrip(" \t\r\n:：,，、;；")
        return None

    @staticmethod
    def _has_chat_mention(text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        return bool(re.search(r"(^|[\s，。！？、；;,.!?])@.+", value.splitlines()[0]))

    @staticmethod
    def _clean_group_avatar_url(value: str) -> str:
        return " ".join(str(value or "").split()).strip()[:2_000_000]

    @staticmethod
    def _group_name_from_participants(participants: list[dict[str, Any]]) -> str:
        participant_names: list[str] = []
        for item in participants:
            display_name = str(item.get("nickname") or item.get("name") or "").strip()
            if display_name:
                participant_names.append(display_name)
        return "、".join(participant_names) or "新群组"

    def _group_participants_from_ids(self, participant_ids: list[str] | None) -> tuple[list[dict[str, Any]], str]:
        clean_ids: list[str] = []
        seen: set[str] = set()
        for raw_id in participant_ids or []:
            participant_id = str(raw_id or "").strip()
            if not participant_id or participant_id == "main" or participant_id in seen:
                continue
            seen.add(participant_id)
            clean_ids.append(participant_id)

        if not clean_ids:
            return [], "请选择至少一个 Agent"

        service = get_agent_runtime_service()
        participants = [self._main_model_sender_from_runtime()]
        try:
            for participant_id in clean_ids:
                runnable = service.resolve_runnable(runnable_id=participant_id)
                if runnable is None or runnable.get("kind") != "agent":
                    return [], "群组成员必须是已启用的 Agent"
                if not runnable.get("enabled", True):
                    return [], "群组成员包含已停用 Agent"
                participants.append(self._participant_for_runnable(runnable))
        except AgentRuntimeError as exc:
            return [], str(exc)
        return participants, ""

    def create_group_session(
        self,
        *,
        name: str = "",
        avatar_url: str = "",
        participant_ids: list[str] | None = None,
    ) -> Dict[str, Any]:
        """Create a manual group chat session with the main model and selected agents."""
        participants, error = self._group_participants_from_ids(participant_ids)
        if error:
            return {"ok": False, "error": error}

        group_name = " ".join(str(name or "").split()).strip()
        if not group_name:
            group_name = self._group_name_from_participants(participants)

        start_new_session = getattr(self._runtime, "start_new_session", None)
        if callable(start_new_session):
            start_new_session()
        else:
            self._session.clear()

        self._session.set_session_title(group_name)
        self._chat_store().update_session_context(
            self._session.session_id,
            conversation_kind="group",
            runnable_id="",
            runnable_name=group_name,
            run_group_id="",
            participants_json=json.dumps(participants, ensure_ascii=False),
            avatar_url=self._clean_group_avatar_url(avatar_url),
        )
        context = self._session_context()
        return {
            "ok": True,
            "session_id": self._session.session_id,
            "session_context": context,
        }

    def update_group_session(
        self,
        session_id: str,
        *,
        name: str = "",
        avatar_url: str = "",
        participant_ids: list[str] | None = None,
    ) -> Dict[str, Any]:
        """Update an existing manual group chat session profile."""
        session_id = str(session_id or "").strip()
        if not session_id:
            return {"ok": False, "error": "session_id 不能为空"}

        store = self._chat_store()
        stored = store.get_session(session_id)
        if stored is None:
            return {"ok": False, "error": "群组不存在"}
        if stored.conversation_kind != "group":
            return {"ok": False, "error": "只能修改手动群组"}

        participants, error = self._group_participants_from_ids(participant_ids)
        if error:
            return {"ok": False, "error": error}

        group_name = " ".join(str(name or "").split()).strip() or self._group_name_from_participants(participants)
        clean_avatar_url = self._clean_group_avatar_url(avatar_url)
        store.update_session_title(session_id, group_name)
        store.update_session_context(
            session_id,
            conversation_kind="group",
            runnable_id=stored.runnable_id,
            runnable_name=group_name,
            run_group_id=stored.run_group_id,
            participants_json=json.dumps(participants, ensure_ascii=False),
            avatar_url=clean_avatar_url,
        )
        context = self._session_context(store.get_session(session_id))
        return {
            "ok": True,
            "session_id": session_id,
            "session_context": context,
        }

    def retry_message(self, message_id: str) -> Dict[str, Any]:
        """重新发送当前会话中的失败消息，复用已保存的附件文件。"""
        message_id = str(message_id or "").strip()
        if not message_id:
            return {"ok": False, "error": "message_id 不能为空"}

        try:
            self._sync_task_status_to_messages()
            target = next(
                (msg for msg in self._session.get_all_messages() if msg.message_id == message_id),
                None,
            )
            delegated_retry = self._retry_delegated_agent_message(target)
            if delegated_retry is not None:
                return delegated_retry

            source = self._find_retry_source_message(message_id)
            if source is None:
                return {"ok": False, "error": "没有找到可重试的失败消息"}

            saved_attachments = [dict(attachment) for attachment in source.attachments or []]
            missing_attachments = self._missing_retry_attachments(saved_attachments)
            if missing_attachments:
                return {
                    "ok": False,
                    "error": f"附件缓存不存在，无法重试：{', '.join(missing_attachments)}",
                }

            if saved_attachments and self._should_enforce_image_capability():
                image_input = get_current_hermes_image_input_capability()
                if image_input.get("can_attach_images") is False:
                    return {
                        "ok": False,
                        "error": str(image_input.get("reason") or "当前 Hermes 模型暂不支持图片输入"),
                        "image_input": image_input,
                    }

            text = (source.content or "").strip()
            if not text and saved_attachments:
                text = "请识别并分析这张图片。"
            if not text:
                return {"ok": False, "error": "原消息内容为空，无法重试"}

            unavailable_reason = user_task_unavailable_reason(self._runtime)
            if unavailable_reason:
                return {"ok": False, "error": unavailable_reason}

            new_message_id = self._session.add_user_message(text, saved_attachments)
            task = self._state.create_task(
                task_type=TaskType.GENERAL,
                description=text,
                attachments=saved_attachments,
                chat_session_id=self._session.session_id,
            )
            self._session.link_message_to_task(new_message_id, task.task_id)

            logger.info(
                "消息已重试: source_message_id=%s, message_id=%s, task_id=%s, attachments=%d",
                message_id,
                new_message_id,
                task.task_id,
                len(saved_attachments),
            )
            return {
                "ok": True,
                "message_id": new_message_id,
                "source_message_id": message_id,
                "task_id": task.task_id,
                "status": "pending",
                "attachments": self._serialize_attachments(saved_attachments),
            }
        except Exception as exc:
            logger.error("重试消息失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def _retry_delegated_agent_message(self, target: ChatMessage | None) -> Dict[str, Any] | None:
        if target is None or target.role != MessageRole.ASSISTANT or target.status != MessageStatus.FAILED:
            return None
        metadata = target.metadata if isinstance(target.metadata, dict) else {}
        if not metadata.get("delegated_by_task_id"):
            return None
        if str(metadata.get("runnable_kind") or "") != "agent":
            return None

        runnable_id = str(metadata.get("runnable_id") or "").strip()
        user_goal = str(metadata.get("delegated_goal") or "").strip()
        if not runnable_id or not user_goal:
            return {"ok": False, "error": "这条 Agent 消息缺少可重试的派活信息"}

        context = self._session_context()
        run_group_id = str(metadata.get("run_group_id") or context.get("run_group_id") or "")
        service = get_agent_runtime_service()
        try:
            runnable = service.resolve_runnable(runnable_id=runnable_id)
        except AgentRuntimeError as exc:
            return {"ok": False, "error": str(exc)}
        if runnable is None or runnable.get("kind") != "agent":
            return {"ok": False, "error": "没有找到可重试的 Agent"}

        sender = self._participant_for_runnable(runnable)
        initial_content = ""
        assistant_id = self._session.add_assistant_message(
            initial_content,
            metadata={
                "sender": sender,
                "runnable_kind": "agent",
                "runnable_id": runnable_id,
                "run_group_id": run_group_id,
                "run_status": "processing",
                "conversation_kind": "group" if context.get("conversation_kind") == "group" else "",
                "group_goal": user_goal if context.get("conversation_kind") == "group" else "",
                "delegated_by_task_id": metadata.get("delegated_by_task_id") or "",
                "delegated_goal": user_goal,
                "retry_of_message_id": target.message_id,
            },
        )
        self._session.update_assistant_message(
            assistant_id,
            initial_content,
            status=MessageStatus.PROCESSING,
        )

        def _on_run_complete(run_result: dict[str, Any]) -> None:
            self._update_agent_run_message_from_result(assistant_id, sender, run_result)

        try:
            run = service.create_run_for_runnable_async(
                runnable_id=runnable_id,
                name=str(sender.get("nickname") or sender.get("name") or ""),
                user_goal=user_goal,
                run_group_id=run_group_id,
                upstream=self._with_group_context_for_agent_upstream(
                    self._chat_upstream_context(),
                    context,
                    sender,
                ),
                on_complete=_on_run_complete,
            )
        except AgentRuntimeError as exc:
            content = str(exc)
            self._session.update_assistant_message(
                assistant_id,
                content,
                status=MessageStatus.FAILED,
                error=content,
                metadata={"run_status": "failed"},
            )
            return {"ok": False, "error": content}

        next_run_group_id = str(run.get("run_group_id") or run_group_id)
        self._attach_processing_agent_run_metadata(assistant_id, initial_content, run)
        if next_run_group_id:
            self._bind_group_session_context(context, run_group_id=next_run_group_id)
        return {
            "ok": True,
            "runnable_command": True,
            "message_id": assistant_id,
            "assistant_message_id": assistant_id,
            "assistant_message_ids": [assistant_id],
            "task_id": "",
            "status": "processing",
            "run_id": run["run_id"],
            "run_group_id": next_run_group_id,
            "run_status": "processing",
            "agent_run_id": run["run_id"],
        }

    def _find_retry_source_message(self, message_id: str) -> ChatMessage | None:
        messages = self._session.get_all_messages()
        target_index = next(
            (index for index, msg in enumerate(messages) if msg.message_id == message_id),
            -1,
        )
        if target_index < 0:
            return None

        target = messages[target_index]
        if target.status != MessageStatus.FAILED:
            return None
        if target.role == MessageRole.USER:
            return target

        if target.task_id:
            for msg in reversed(messages[:target_index]):
                if msg.role == MessageRole.USER and msg.task_id == target.task_id:
                    return msg

        for msg in reversed(messages[:target_index]):
            if msg.role == MessageRole.USER:
                return msg
        return None

    @staticmethod
    def _missing_retry_attachments(attachments: list[dict]) -> list[str]:
        missing: list[str] = []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            if str(attachment.get("kind") or "image") == "audio":
                continue
            path = Path(str(attachment.get("path") or ""))
            if not path or not path.exists() or not path.is_file():
                missing.append(str(attachment.get("name") or attachment.get("id") or "image"))
        return missing

    def _should_enforce_image_capability(self) -> bool:
        runner = getattr(self._runtime, "task_runner", None)
        if runner is None:
            return False
        executor = getattr(runner, "executor", None)
        return getattr(executor, "name", "") == "HermesExecutor"

    @staticmethod
    def _should_attach_desktop_snapshot(text: str, saved_attachments: list[dict]) -> bool:
        if saved_attachments:
            return False
        value = (text or "").strip()
        if not value:
            return False
        return bool(_DESKTOP_SNAPSHOT_REQUEST_RE.search(value))

    def _attach_desktop_snapshot_if_needed(
        self,
        text: str,
        saved_attachments: list[dict],
        *,
        should_attach: bool,
    ) -> tuple[str, list[dict]]:
        """Attach a fresh desktop screenshot when the user explicitly asks Yachiyo to look."""
        if saved_attachments or not should_attach:
            return text, saved_attachments

        attachment_id, target_path = allocate_chat_attachment_path(self._session.session_id, ".png")
        proactive_session = is_proactive_chat_session(self._session.session_id)
        source = "proactive_desktop_followup" if proactive_session else "user_requested_desktop_snapshot"
        note_subject = "这条主动关怀追问" if proactive_session else "这条消息"
        try:
            meta = capture_screenshot_to_file(target_path)
            attachment = chat_attachment_record(
                attachment_id,
                target_path,
                kind="image",
                name="主动关怀即时桌面截图.png" if proactive_session else "当前桌面截图.png",
                mime_type="image/png",
            )
            attachment["source"] = source
            _cleanup_attachment_cache({Path(str(attachment["path"]))})
            logger.info(
                "用户请求查看桌面，已附加即时截图: session=%s path=%s (%sx%s)",
                self._session.session_id,
                target_path,
                meta.get("width") if isinstance(meta, dict) else "?",
                meta.get("height") if isinstance(meta, dict) else "?",
            )
            task_description = (
                f"{text}\n\n"
                f"[Yachiyo 已为{note_subject}附加当前桌面截图；"
                "请优先基于附件图片回答用户问题。]"
            )
            return task_description, [attachment]
        except Exception as exc:
            try:
                target_path.unlink(missing_ok=True)
            except OSError:
                logger.debug("清理按需桌面截图失败: %s", target_path, exc_info=True)
            logger.warning("按需桌面截图捕获失败: %s", exc)
            task_description = (
                f"{text}\n\n"
                f"[Yachiyo 尝试为{note_subject}捕获当前桌面截图，但失败：{exc}。"
                "请向用户说明当前无法读取桌面截图。]"
            )
            return task_description, saved_attachments

    def get_messages(self, limit: int = 0, anchor_message_id: str = "") -> Dict[str, Any]:
        """获取消息列表，同时同步任务状态到消息

        此方法会检查每条 user 消息关联的任务状态：
          - 任务 COMPLETED → 若无对应 assistant 回复，自动添加
          - 任务 FAILED → 标记消息失败
          - 任务 RUNNING → 更新消息状态为 processing

        消息排序：保证每条 user 消息紧跟其关联的 assistant 回复，
        避免并发任务完成顺序不一致导致消息错位。

        Returns:
            {"ok": True, "session_id": str, "messages": [...], "is_processing": bool}
        """
        try:
            # 同步任务状态到消息
            self._sync_task_status_to_messages()
            self._sync_agent_run_status_to_messages()

            anchor_message_id = str(anchor_message_id or "").strip()
            if anchor_message_id:
                messages = self._load_messages_around_anchor(anchor_message_id, limit=limit)
                anchor_found = any(m.message_id == anchor_message_id for m in messages)
                if not anchor_found:
                    messages = self._session.get_messages(limit)
            else:
                messages = self._session.get_messages(limit)
            sorted_msgs = self._sort_messages_by_task(messages)
            task_ids = [m.task_id for m in sorted_msgs if m.task_id]
            activity_by_task = self._activity_events_by_task(task_ids, limit_per_task=5)
            serialized_messages = self._serialize_chat_messages(sorted_msgs, activity_by_task)
            return {
                "ok": True,
                "session_id": self._session.session_id,
                "session_context": self._session_context(),
                "is_processing": self._session.is_processing(),
                "messages": serialized_messages,
                "anchor_message_id": anchor_message_id,
            }

        except Exception as exc:
            logger.error("获取消息列表失败: %s", exc)
            return {"ok": False, "error": str(exc), "messages": []}

    def _load_messages_around_anchor(self, message_id: str, *, limit: int) -> list[ChatMessage]:
        context = max(20, min(int(limit or 80), 400))
        before = max(10, int(context * 0.65))
        after = max(10, context - before - 1)
        stored_messages = self._chat_store().load_messages_around(
            self._session.session_id,
            message_id,
            before=before,
            after=after,
        )
        return self._stored_messages_to_chat_messages(stored_messages)

    def _stored_messages_to_chat_messages(self, stored_messages: list[Any]) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        for stored in stored_messages:
            try:
                role = MessageRole(str(getattr(stored, "role", "")))
                status = MessageStatus(str(getattr(stored, "status", "")))
                created_at = datetime.fromisoformat(str(getattr(stored, "created_at", "")))
            except ValueError:
                logger.debug("跳过无法序列化的聊天消息: %s", getattr(stored, "message_id", ""), exc_info=True)
                continue
            attachments_json = str(getattr(stored, "attachments_json", "") or "[]")
            try:
                parsed_attachments = json.loads(attachments_json)
                attachments = parsed_attachments if isinstance(parsed_attachments, list) else []
            except json.JSONDecodeError:
                attachments = []
            metadata_json = str(getattr(stored, "metadata_json", "") or "{}")
            try:
                parsed_metadata = json.loads(metadata_json)
                metadata = parsed_metadata if isinstance(parsed_metadata, dict) else {}
            except json.JSONDecodeError:
                metadata = {}
            messages.append(
                ChatMessage(
                    message_id=str(getattr(stored, "message_id", "")),
                    role=role,
                    content=str(getattr(stored, "content", "") or ""),
                    status=status,
                    created_at=created_at,
                    task_id=getattr(stored, "task_id", None),
                    error=getattr(stored, "error", None),
                    attachments=attachments,
                    metadata=metadata,
                )
            )
        return messages

    def _serialize_chat_messages(
        self,
        messages: list[ChatMessage],
        activity_by_task: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        serialized_messages = []
        for m in messages:
            show_activity = m.role == MessageRole.ASSISTANT
            activity_events = activity_by_task.get(m.task_id or "", []) if show_activity else []
            serialized_messages.append(
                {
                    "id": m.message_id,
                    "role": m.role.value,
                    "content": m.content,
                    "status": m.status.value,
                    "task_id": m.task_id,
                    "error": m.error,
                    "created_at": m.created_at.isoformat(),
                    "attachments": self._serialize_attachments(m.attachments),
                    "metadata": m.metadata or {},
                    "progress_label": self._task_progress_label(m.task_id) if activity_events else "",
                    "activity_events": activity_events,
                }
            )
        return serialized_messages

    @staticmethod
    def _sort_messages_by_task(messages: List[ChatMessage]) -> List[ChatMessage]:
        """按 task 关联重排消息，保证 user 消息紧跟其 assistant 回复。

        算法：遍历消息列表，将 assistant 消息按 task_id 索引。
        输出时，每条 user 消息后立即插入对应 assistant 消息。
        system 消息和无 task_id 的消息保持原始顺序。
        """
        user_task_ids = {
            msg.task_id
            for msg in messages
            if msg.role == MessageRole.USER and msg.task_id
        }

        # 建立 task_id → assistant 消息的映射。只有同页存在 user
        # 消息的 task 才做配对重排；主动关怀这类 assistant-only
        # 消息保持原本时间线位置。若历史库里已经有重复 assistant，
        # 只取最可信的一条，避免 UI 再把脏数据渲染成重复回复。
        assistant_by_task: dict[str, ChatMessage] = {}
        for msg in messages:
            if msg.role == MessageRole.ASSISTANT and msg.task_id in user_task_ids:
                current = assistant_by_task.get(msg.task_id)
                if current is None or ChatAPI._prefer_assistant_for_sort(msg, current):
                    assistant_by_task[msg.task_id] = msg

        result: list[ChatMessage] = []
        inserted_assistant_ids: set[str] = set()

        for msg in messages:
            if msg.role == MessageRole.ASSISTANT and msg.task_id in user_task_ids:
                # assistant 消息由 user 消息触发插入，跳过
                continue
            result.append(msg)
            # user 消息后紧跟其关联的 assistant 回复
            if msg.role == MessageRole.USER and msg.task_id:
                assistant = assistant_by_task.get(msg.task_id)
                if assistant is not None:
                    result.append(assistant)
                    inserted_assistant_ids.add(assistant.message_id)

        # 兜底：分页/limit 截断时 user 可能不在当前列表，
        # 不能丢弃这条 canonical assistant。
        for msg in assistant_by_task.values():
            if msg.message_id not in inserted_assistant_ids:
                result.append(msg)

        return result

    @staticmethod
    def _prefer_assistant_for_sort(candidate: ChatMessage, current: ChatMessage) -> bool:
        status_rank = {
            MessageStatus.COMPLETED: 0,
            MessageStatus.FAILED: 1,
            MessageStatus.PROCESSING: 2,
            MessageStatus.PENDING: 3,
        }
        candidate_rank = status_rank.get(candidate.status, 9)
        current_rank = status_rank.get(current.status, 9)
        if candidate_rank != current_rank:
            return candidate_rank < current_rank
        return candidate.created_at > current.created_at

    def get_attachment_file(self, attachment_id: str) -> Dict[str, Any]:
        """返回聊天附件文件信息，供 HTTP 路由发送预览图。"""
        attachment_id = (attachment_id or "").strip()
        if not attachment_id or not re.fullmatch(r"[a-f0-9]{32}", attachment_id):
            return {"ok": False, "error": "附件 ID 无效"}

        for msg in self._session.get_all_messages():
            for attachment in msg.attachments or []:
                if str(attachment.get("id") or "") != attachment_id:
                    continue
                path = Path(str(attachment.get("path") or ""))
                root = _attachment_root().resolve()
                try:
                    resolved = path.resolve()
                except OSError:
                    return {"ok": False, "error": "附件路径无效"}
                if root not in resolved.parents:
                    return {"ok": False, "error": "附件路径越界"}
                if not resolved.exists() or not resolved.is_file():
                    return {"ok": False, "error": "附件文件不存在"}
                return {
                    "ok": True,
                    "path": str(resolved),
                    "mime_type": str(attachment.get("mime_type") or "image/png"),
                    "name": str(attachment.get("name") or resolved.name),
                }
        return {"ok": False, "error": "附件不存在或不属于当前会话"}

    def _save_attachments(self, attachments: list[dict]) -> list[dict]:
        if not attachments:
            return []
        if len(attachments) > _MAX_CHAT_ATTACHMENTS:
            raise ValueError(f"最多一次发送 {_MAX_CHAT_ATTACHMENTS} 张图片")

        session_dir = _attachment_root() / self._session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        saved: list[dict] = []
        for index, item in enumerate(attachments, start=1):
            saved.append(self._save_attachment(item, session_dir, index))
        _cleanup_attachment_cache(
            {Path(str(attachment["path"])) for attachment in saved if attachment.get("path")}
        )
        return saved

    def _save_attachment(self, item: dict, session_dir: Path, index: int) -> dict:
        if not isinstance(item, dict):
            raise ValueError("附件格式无效")
        data_url = str(item.get("data_url") or item.get("dataUrl") or "")
        match = _DATA_URL_RE.match(data_url)
        if not match:
            raise ValueError("只支持粘贴图片附件")

        mime_type = match.group(1).lower()
        extension = _IMAGE_EXTENSIONS_BY_MIME.get(mime_type)
        if not extension:
            raise ValueError(f"暂不支持此图片格式：{mime_type}")

        try:
            raw = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("图片数据无法解析") from exc

        if not raw:
            raise ValueError("图片内容为空")
        if len(raw) > _MAX_ATTACHMENT_BYTES:
            limit_mb = _MAX_ATTACHMENT_BYTES // (1024 * 1024)
            raise ValueError(f"单张图片不能超过 {limit_mb} MB")

        attachment_id = uuid4().hex
        safe_name = _sanitize_attachment_name(str(item.get("name") or f"image-{index}{extension}"))
        if not Path(safe_name).suffix:
            safe_name += extension
        target = session_dir / f"{attachment_id}{extension}"
        target.write_bytes(raw)
        return {
            "id": attachment_id,
            "kind": "image",
            "name": safe_name,
            "mime_type": mime_type,
            "size": len(raw),
            "path": str(target),
        }

    @staticmethod
    def _serialize_attachments(attachments: list[dict] | None) -> list[dict]:
        result: list[dict] = []
        for attachment in attachments or []:
            if not isinstance(attachment, dict):
                continue
            attachment_id = str(attachment.get("id") or "")
            if not attachment_id:
                continue
            item = {
                "id": attachment_id,
                "kind": str(attachment.get("kind") or "image"),
                "name": str(attachment.get("name") or "image"),
                "mime_type": str(attachment.get("mime_type") or "image/png"),
                "size": int(attachment.get("size") or 0),
                "url": _attachment_public_url(attachment_id),
            }
            if attachment.get("source"):
                item["source"] = str(attachment.get("source") or "")
            if attachment.get("spoken_text"):
                item["spoken_text"] = str(attachment.get("spoken_text") or "")
            result.append(item)
        return result

    def _sync_task_status_to_messages(self) -> None:
        """将任务状态同步到关联的消息

        使用 upsert_assistant_message() 保证幂等：
          - RUNNING: 创建/更新 assistant 占位消息（PROCESSING）
          - COMPLETED: 更新 assistant 消息为最终结果
          - FAILED: 更新 assistant 消息为错误信息
          - CANCELLED: 更新 assistant 消息为取消提示

        同一个 task_id 永远只对应一条 assistant 消息，
        无论此方法被并发调用多少次都不会产生重复。
        """
        synced_task_ids: set[str] = set()
        current_context = self._session_context()
        for msg in self._session.get_all_messages():
            if msg.role not in (MessageRole.USER, MessageRole.ASSISTANT):
                continue
            if msg.task_id is None:
                continue
            if msg.task_id in synced_task_ids:
                continue
            if msg.status in (MessageStatus.COMPLETED, MessageStatus.FAILED):
                continue

            task = self._state.get_task(msg.task_id)
            if task is None:
                if msg.status in (MessageStatus.PENDING, MessageStatus.PROCESSING):
                    self._session.mark_message_failed(msg.message_id, "任务状态不可恢复")
                continue
            synced_task_ids.add(msg.task_id)

            if task.status == TaskStatus.COMPLETED:
                result = task.result or "[任务已完成，无输出]"
                self._session.upsert_assistant_message(
                    task_id=msg.task_id,
                    content=result,
                    status=MessageStatus.COMPLETED,
                )

            elif task.status == TaskStatus.FAILED:
                error = task.error or "任务执行失败"
                self._session.upsert_assistant_message(
                    task_id=msg.task_id,
                    content=f"❌ {error}",
                    status=MessageStatus.FAILED,
                    error=error,
                )

            elif task.status == TaskStatus.CANCELLED:
                error = "任务已取消"
                self._session.upsert_assistant_message(
                    task_id=msg.task_id,
                    content=f"⚠️ {error}",
                    status=MessageStatus.FAILED,
                    error=error,
                )

            elif task.status == TaskStatus.RUNNING:
                assistant = self._session.get_assistant_message_for_task(msg.task_id)
                if assistant is None:
                    self._session.upsert_assistant_message(
                        task_id=msg.task_id,
                        content="",
                        status=MessageStatus.PROCESSING,
                    )
                elif self._should_hide_group_dispatch_stream(task.description, assistant.content, current_context):
                    visible_content = self._group_dispatch_stream_visible_content(
                        assistant.content,
                        assistant.metadata if isinstance(assistant.metadata, dict) else {},
                    )
                    self._record_group_dispatch_activity(
                        task_id=msg.task_id,
                        title="正在派发群组任务",
                        detail="Yachiyo 正在解析需要交给哪些 Agent。",
                        status="running",
                        event_id=f"{msg.task_id}-group-dispatch-start",
                    )
                    metadata = dict(assistant.metadata or {})
                    metadata.update({
                        "sender": metadata.get("sender") or self._main_model_sender_from_runtime(),
                        "group_dispatch_pending": True,
                        "group_dispatch_stream_visible_content": visible_content,
                    })
                    self._session.upsert_assistant_message(
                        task_id=msg.task_id,
                        content=visible_content,
                        status=MessageStatus.PROCESSING,
                        error=assistant.error,
                        attachments=assistant.attachments,
                        metadata=metadata,
                    )
                elif assistant.status != MessageStatus.PROCESSING:
                    self._session.upsert_assistant_message(
                        task_id=msg.task_id,
                        content=assistant.content,
                        status=MessageStatus.PROCESSING,
                        error=assistant.error,
                    )

        self._sync_group_dispatches_from_completed_tasks()

    def _sync_agent_run_status_to_messages(self) -> None:
        candidates: list[tuple[ChatMessage, dict[str, Any]]] = []
        for msg in self._session.get_all_messages():
            if msg.role != MessageRole.ASSISTANT:
                continue
            metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
            if metadata.get("runnable_kind") != "agent":
                continue
            run_id = str(metadata.get("run_id") or "").strip()
            if not run_id:
                continue
            run_status = str(metadata.get("run_status") or "").strip()
            if msg.status != MessageStatus.PROCESSING and run_status not in {"processing", "approval_required"}:
                continue
            candidates.append((msg, metadata))
        if not candidates:
            return

        try:
            service = get_agent_runtime_service()
        except Exception:
            logger.debug("读取 Agent Run 状态失败", exc_info=True)
            return
        for msg, metadata in candidates:
            run_id = str(metadata.get("run_id") or "").strip()
            try:
                run = service.get_run(run_id)
            except Exception:
                logger.debug("读取 Agent Run 失败: %s", run_id, exc_info=True)
                continue
            status = str(run.get("status") or "").strip()
            if status in {"", "processing", "pending"}:
                continue
            sender = metadata.get("sender") if isinstance(metadata.get("sender"), dict) else {}
            self._update_agent_run_message_from_result(msg.message_id, sender, run)

    def _sync_group_dispatches_from_completed_tasks(self) -> None:
        context = self._session_context()
        if context.get("conversation_kind") != "group":
            return
        for msg in self._session.get_all_messages():
            if msg.role != MessageRole.ASSISTANT or not msg.task_id:
                continue
            if msg.status != MessageStatus.COMPLETED:
                continue
            metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
            if metadata.get("group_dispatch_handled"):
                continue
            sender = metadata.get("sender") if isinstance(metadata.get("sender"), dict) else {}
            if sender.get("kind") in {"agent", "workflow"}:
                continue
            task = self._state.get_task(msg.task_id)
            if task is None or task.status != TaskStatus.COMPLETED:
                continue
            source_text = task.result or msg.content
            requests = self._parse_group_dispatch_requests(source_text)
            if not requests:
                continue
            self._dispatch_group_agent_requests(msg, requests, context, source_text=source_text)

    @classmethod
    def _parse_group_dispatch_requests(cls, content: str) -> list[dict[str, str]]:
        requests: list[dict[str, str]] = []
        for payload in cls._json_payloads_from_text(content):
            requests.extend(cls._group_dispatch_requests_from_payload(payload))
        deduped: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in requests:
            key = (item.get("kind", ""), item.get("target", ""), item.get("goal", ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:3]

    def _should_hide_group_dispatch_stream(
        self,
        task_description: str,
        content: str,
        context: dict[str, Any],
    ) -> bool:
        if context.get("conversation_kind") != "group":
            return False
        if "[Yachiyo 群组上下文]" not in (task_description or ""):
            return False
        text = (content or "").strip()
        if not text:
            return False
        if self._parse_group_dispatch_requests(text):
            return True
        lowered = text.lower()
        compact = re.sub(r"[\s_-]+", "", lowered)
        if "dispatchgroupagent" in compact or "runyachiyoagent" in compact:
            return True
        if re.match(r"^[\\[{]\\s*(?:\"(?:action|tasks|agents|dispatches)|\\{)", text, re.DOTALL):
            return True
        return False

    @classmethod
    def _group_dispatch_stream_visible_content(cls, content: str, metadata: dict[str, Any]) -> str:
        visible = cls._strip_group_dispatch_payloads(content)
        visible = cls._normalize_group_dispatch_intro(visible)
        if visible:
            return visible
        previous = str(metadata.get("group_dispatch_stream_visible_content") or "").strip()
        if previous:
            return previous
        return ""

    @staticmethod
    def _json_payloads_from_text(content: str) -> list[Any]:
        text = (content or "").strip()
        if not text:
            return []
        tag_match = re.search(
            r"<yachiyo_group_dispatch>\s*(.*?)\s*</yachiyo_group_dispatch>",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if tag_match:
            text = tag_match.group(1).strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()

        try:
            return [json.loads(text)]
        except (TypeError, json.JSONDecodeError):
            pass

        decoder = json.JSONDecoder()
        payloads: list[Any] = []
        index = 0
        while index < len(text):
            char = text[index]
            if char not in "{[":
                index += 1
                continue
            try:
                payload, offset = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                index += 1
                continue
            payloads.append(payload)
            index += max(offset, 1)
        return payloads

    @classmethod
    def _group_dispatch_requests_from_payload(cls, payload: Any) -> list[dict[str, str]]:
        if isinstance(payload, list):
            result: list[dict[str, str]] = []
            for item in payload:
                result.extend(cls._group_dispatch_requests_from_payload(item))
            return result
        if not isinstance(payload, dict):
            return []
        nested = payload.get("tasks") or payload.get("agents") or payload.get("dispatches")
        if isinstance(nested, list):
            result = []
            for item in nested:
                if isinstance(item, dict):
                    merged = {**payload, **item}
                    for key in ("tasks", "agents", "dispatches"):
                        merged.pop(key, None)
                    result.extend(cls._group_dispatch_requests_from_payload(merged))
            return result

        action = cls._normalize_group_dispatch_action(str(payload.get("action") or payload.get("tool") or ""))
        if action not in {"agent", "workflow"}:
            return []
        goal = str(payload.get("goal") or payload.get("user_goal") or payload.get("task") or "").strip()
        if not goal:
            return []
        if action == "agent":
            target = str(
                payload.get("agent")
                or payload.get("name")
                or payload.get("agent_name")
                or payload.get("target")
                or ""
            )
            target_id = str(payload.get("agent_id") or payload.get("runnable_id") or "")
        else:
            target = str(
                payload.get("workflow")
                or payload.get("name")
                or payload.get("workflow_name")
                or payload.get("target")
                or ""
            )
            target_id = str(payload.get("workflow_id") or payload.get("runnable_id") or "")
        target = cls._clean_group_dispatch_target(target)
        target_id = cls._clean_group_dispatch_target(target_id)
        if not target and not target_id:
            return []
        return [{"kind": action, "target": target, "runnable_id": target_id, "goal": goal}]

    @staticmethod
    def _normalize_group_dispatch_action(action: str) -> str:
        normalized = re.sub(r"[\s-]+", "_", (action or "").strip().lower())
        compact = normalized.replace("_", "")
        if compact in {
            "dispatchgroupagent",
            "rungroupagent",
            "runyachiyoagent",
            "yachiyoagent",
        }:
            return "agent"
        if compact in {
            "dispatchgroupworkflow",
            "rungroupworkflow",
            "runyachiyoworkflow",
            "yachiyoworkflow",
        }:
            return "workflow"
        return ""

    @staticmethod
    def _clean_group_dispatch_target(value: str) -> str:
        text = " ".join(str(value or "").split()).strip()
        text = text.strip("\"'“”‘’")
        if text.startswith("@"):
            text = text[1:].strip()
        return text.strip("\"'“”‘’")

    def _dispatch_group_agent_requests(
        self,
        assistant_message: ChatMessage,
        requests: list[dict[str, str]],
        context: dict[str, Any],
        *,
        source_text: str = "",
    ) -> None:
        service = get_agent_runtime_service()
        resolved: list[tuple[dict[str, str], dict[str, Any]]] = []
        skipped: list[str] = []
        for request in requests:
            try:
                runnable = service.resolve_runnable(
                    runnable_id=request.get("runnable_id", ""),
                    name=request.get("target", ""),
                )
            except AgentRuntimeError as exc:
                skipped.append(f"{request.get('target') or request.get('runnable_id')}: {exc}")
                continue
            if runnable is None or runnable.get("kind") != "agent":
                skipped.append(f"{request.get('target') or request.get('runnable_id')}: 未找到群组 Agent")
                continue
            if not self._group_context_contains_runnable(context, runnable, request):
                skipped.append(f"{request.get('target') or runnable.get('name')}: 不在当前群组中")
                continue
            resolved.append((request, runnable))

        summary = self._format_group_dispatch_summary(resolved, skipped)
        visible_content = self._format_group_dispatch_visible_content(source_text or assistant_message.content, summary)
        resolved_names = [
            str(runnable.get("nickname") or runnable.get("name") or request.get("target") or "Agent").strip()
            for request, runnable in resolved
        ]
        resolved_names = [name for name in resolved_names if name]
        self._record_group_dispatch_activity(
            task_id=assistant_message.task_id or "",
            title="群组任务已派发" if resolved else "群组任务派发失败",
            detail="、".join(resolved_names) if resolved_names else "没有找到可接收任务的 Agent",
            status="completed" if resolved else "failed",
            event_id=f"{assistant_message.task_id or assistant_message.message_id}-group-dispatch-complete",
        )
        self._session.update_assistant_message(
            assistant_message.message_id,
            visible_content,
            status=MessageStatus.COMPLETED,
            metadata={
                "sender": self._main_model_sender_from_runtime(),
                "group_dispatch_handled": True,
                "group_dispatch_count": len(resolved),
                "group_dispatch_skipped": skipped,
            },
        )
        if not resolved:
            return

        run_group_id = str(context.get("run_group_id") or "")
        next_context = dict(context)
        for request, runnable in resolved:
            sender = self._participant_for_runnable(runnable)
            initial_content = ""
            assistant_id = self._session.add_assistant_message(
                initial_content,
                metadata={
                    "sender": sender,
                    "runnable_kind": "agent",
                    "runnable_id": runnable.get("id") or "",
                    "run_group_id": run_group_id,
                    "run_status": "processing",
                    "conversation_kind": "group",
                    "group_goal": request.get("goal") or "",
                    "delegated_by_task_id": assistant_message.task_id or "",
                    "delegated_goal": request.get("goal") or "",
                },
            )
            self._session.update_assistant_message(
                assistant_id,
                initial_content,
                status=MessageStatus.PROCESSING,
            )

            def _on_run_complete(
                run_result: dict[str, Any],
                *,
                message_id: str = assistant_id,
                current_sender: dict[str, Any] = sender,
            ) -> None:
                self._update_agent_run_message_from_result(message_id, current_sender, run_result)

            try:
                run = service.create_run_for_runnable_async(
                    runnable_id=str(runnable.get("id") or ""),
                    name=request.get("target", ""),
                    user_goal=request.get("goal", ""),
                    run_group_id=run_group_id,
                    upstream=self._with_group_context_for_agent_upstream(
                        self._chat_upstream_context(),
                        next_context,
                        sender,
                    ),
                    on_complete=_on_run_complete,
                )
            except AgentRuntimeError as exc:
                content = str(exc)
                self._session.update_assistant_message(
                    assistant_id,
                    content,
                    status=MessageStatus.FAILED,
                    error=content,
                    metadata={"run_status": "failed"},
                )
                self._maybe_create_group_agent_summary_task(assistant_message.task_id or "")
                continue

            run_group_id = str(run.get("run_group_id") or run_group_id)
            self._attach_processing_agent_run_metadata(assistant_id, initial_content, run)
            if run_group_id:
                next_context["run_group_id"] = run_group_id
                self._bind_group_session_context(next_context, run_group_id=run_group_id)

    def _maybe_create_group_agent_summary_task(self, parent_task_id: str) -> None:
        parent_task_id = str(parent_task_id or "").strip()
        if not parent_task_id:
            return
        context = self._session_context()
        if context.get("conversation_kind") != "group":
            return
        parent = self._session.get_assistant_message_for_task(parent_task_id)
        if parent is None:
            return
        parent_metadata = parent.metadata if isinstance(parent.metadata, dict) else {}
        if parent_metadata.get("group_agent_summary_task_id"):
            return
        children = self._delegated_group_agent_children(parent_task_id)
        expected_count = int(parent_metadata.get("group_dispatch_count") or 0)
        if not children or (expected_count and len(children) < expected_count):
            return
        if any(not self._is_terminal_delegated_agent_message(child) for child in children):
            return

        task = self._state.create_task(
            task_type=TaskType.GENERAL,
            description=self._group_agent_summary_task_description(parent, children),
            chat_session_id=self._session.session_id,
        )
        self._session.upsert_assistant_message(
            task_id=task.task_id,
            content="",
            status=MessageStatus.PROCESSING,
            metadata={
                "sender": self._main_model_sender_from_runtime(),
                "group_agent_summary_for_task_id": parent_task_id,
                "group_dispatch_handled": True,
            },
        )
        self._session.update_assistant_message(
            parent.message_id,
            parent.content,
            status=parent.status,
            error=parent.error,
            metadata={
                "group_agent_summary_task_id": task.task_id,
                "group_agent_summary_pending": True,
            },
        )

    def _delegated_group_agent_children(self, parent_task_id: str) -> list[ChatMessage]:
        return [
            msg
            for msg in self._session.get_all_messages()
            if msg.role == MessageRole.ASSISTANT
            and isinstance(msg.metadata, dict)
            and msg.metadata.get("delegated_by_task_id") == parent_task_id
            and msg.metadata.get("runnable_kind") == "agent"
        ]

    @staticmethod
    def _is_terminal_delegated_agent_message(message: ChatMessage) -> bool:
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        status = str(metadata.get("run_status") or "").strip()
        return status in {"completed", "failed", "cancelled"}

    def _group_agent_summary_task_description(self, parent: ChatMessage, children: list[ChatMessage]) -> str:
        user_request = ""
        for msg in reversed(self._session.get_all_messages()):
            if msg.role == MessageRole.USER and msg.task_id == parent.task_id:
                user_request = str(msg.content or "").strip()
                break
        lines = [
            "[Yachiyo 群组 Agent 汇总]",
            "你是这个群组的主模型。群内 Agent 已把执行结果交给你，请由你整合后回复用户。",
            "不要再派发新的 Agent 任务，不要输出 yachiyo_group_dispatch 或任何机器可读派活 JSON。",
            "回复需要说明：完成了什么、各 Agent 的关键结论、是否需要用户验收或继续批准下一步。",
        ]
        if user_request:
            lines.extend(["", f"用户原始请求：{user_request}"])
        parent_content = self._strip_group_dispatch_payloads(parent.content)
        parent_content = self._normalize_group_dispatch_intro(parent_content)
        if parent_content:
            lines.extend(["", f"你之前对用户说明的计划：{parent_content}"])
        lines.append("")
        lines.append("Agent 汇报：")
        for child in children:
            metadata = child.metadata if isinstance(child.metadata, dict) else {}
            sender = metadata.get("sender") if isinstance(metadata.get("sender"), dict) else {}
            name = str(sender.get("nickname") or sender.get("name") or "Agent").strip() or "Agent"
            status = str(metadata.get("agent_report_status") or metadata.get("run_status") or child.status.value).strip()
            goal = _compact_preview(str(metadata.get("delegated_goal") or metadata.get("group_goal") or ""), 180)
            report = str(metadata.get("agent_report") or child.error or child.content or "").strip()
            lines.append(f"- {name}：{self._workflow_status_label(status)}")
            if goal:
                lines.append(f"  任务：{goal}")
            if report:
                lines.append(f"  汇报：{report}")
        return "\n".join(lines)

    @staticmethod
    def _group_context_contains_runnable(
        context: dict[str, Any],
        runnable: dict[str, Any],
        request: dict[str, str],
    ) -> bool:
        participants = [
            item
            for item in (context.get("participants") or [])
            if isinstance(item, dict) and item.get("kind") == "agent"
        ]
        if not participants:
            return True
        runnable_values = {
            str(runnable.get("id") or "").strip().lower(),
            str(runnable.get("name") or "").strip().lower(),
            str(runnable.get("nickname") or "").strip().lower(),
            str(request.get("target") or "").strip().lower(),
            str(request.get("runnable_id") or "").strip().lower(),
        }
        runnable_values.discard("")
        for participant in participants:
            participant_values = {
                str(participant.get("id") or "").strip().lower(),
                str(participant.get("name") or "").strip().lower(),
                str(participant.get("nickname") or "").strip().lower(),
            }
            participant_values.discard("")
            if participant_values & runnable_values:
                return True
        return False

    @staticmethod
    def _format_group_dispatch_summary(
        resolved: list[tuple[dict[str, str], dict[str, Any]]],
        skipped: list[str],
    ) -> str:
        if not resolved:
            if skipped:
                return "我没能找到可以接这个任务的群组 Agent。\n\n" + "\n".join(f"- {item}" for item in skipped)
            return "我暂时没有派出任务。"
        names = [
            str(runnable.get("nickname") or runnable.get("name") or request.get("target") or "Agent").strip()
            for request, runnable in resolved
        ]
        names = [name for name in names if name]
        if len(names) == 1:
            text = f"我把这个任务派给 {names[0]} 了。"
        else:
            joined_names = "、".join(names)
            text = f"我把 {len(names)} 个任务分别派给 {joined_names} 了。"
        if skipped:
            text += "\n\n以下派活没有执行：\n" + "\n".join(f"- {item}" for item in skipped)
        return text

    @classmethod
    def _format_group_dispatch_visible_content(cls, source_text: str, summary: str) -> str:
        intro = cls._strip_group_dispatch_payloads(source_text)
        intro = cls._normalize_group_dispatch_intro(intro)
        if intro and summary:
            return f"{intro}\n\n{summary}"
        return summary or intro

    @classmethod
    def _strip_group_dispatch_payloads(cls, content: str) -> str:
        text = str(content or "")
        if not text.strip():
            return ""
        spans = cls._group_dispatch_payload_spans(text)
        if not spans:
            return text
        output: list[str] = []
        cursor = 0
        for start, end in spans:
            output.append(text[cursor:start])
            cursor = end
        output.append(text[cursor:])
        return "".join(output)

    @classmethod
    def _group_dispatch_payload_spans(cls, text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        for match in re.finditer(
            r"<yachiyo_group_dispatch>\s*(.*?)\s*</yachiyo_group_dispatch>",
            text,
            re.DOTALL | re.IGNORECASE,
        ):
            if cls._parse_group_dispatch_requests(match.group(1)):
                spans.append(match.span())
        for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE):
            if cls._parse_group_dispatch_requests(match.group(1)):
                spans.append(match.span())

        decoder = json.JSONDecoder()
        index = 0
        while index < len(text):
            if text[index] not in "{[":
                index += 1
                continue
            try:
                payload, offset = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                index += 1
                continue
            if cls._group_dispatch_requests_from_payload(payload):
                spans.append((index, index + max(offset, 1)))
            index += max(offset, 1)
        return cls._merge_spans(spans)

    @staticmethod
    def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not spans:
            return []
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        return merged

    @staticmethod
    def _normalize_group_dispatch_intro(content: str) -> str:
        lines = []
        for line in str(content or "").splitlines():
            clean = line.strip()
            if not clean:
                lines.append("")
                continue
            if clean in {"```", "```json"}:
                continue
            if clean.lower() in {"<yachiyo_group_dispatch>", "</yachiyo_group_dispatch>"}:
                continue
            lines.append(line.rstrip())
        text = "\n".join(lines).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    def _record_group_dispatch_activity(
        self,
        *,
        task_id: str,
        title: str,
        detail: str,
        status: str,
        event_id: str,
    ) -> None:
        task_id = str(task_id or "").strip()
        if not task_id:
            return
        try:
            get_activity_store().record_event(
                session_id=self._session.session_id,
                task_id=task_id,
                tool_name="yachiyo.group_dispatch",
                phase="tool_complete" if status in {"completed", "failed"} else "tool_start",
                title=title,
                detail=detail,
                status=status,
                event_id=event_id,
            )
        except Exception:
            logger.debug("记录群组派活活动失败: %s", task_id, exc_info=True)

    def get_session_info(self) -> Dict[str, Any]:
        """获取会话元信息"""
        return {
            "session_id": self._session.session_id,
            "session_context": self._session_context(),
            "message_count": self._session.message_count(),
            "is_processing": self._session.is_processing(),
            "pending_message_id": self._session.get_pending_message_id(),
        }

    def get_executor_info(self) -> Dict[str, Any]:
        image_input = get_current_hermes_image_input_capability()
        runner = getattr(self._runtime, "task_runner", None)
        if runner is None:
            return {
                "executor": "none",
                "available": False,
                "image_input": image_input,
                "reason": user_task_unavailable_reason(self._runtime),
            }
        executor_name = runner.executor.name
        available = executor_name == "HermesExecutor"
        payload = {
            "executor": executor_name,
            "available": available,
            "image_input": image_input,
        }
        if not available:
            payload["reason"] = user_task_unavailable_reason(self._runtime)
        return payload

    def list_sessions(self, limit: int = 20, query: str = "") -> Dict[str, Any]:
        """列出最近会话，包含当前空白会话。"""
        store = self._chat_store()
        normalized_query = " ".join(str(query or "").split()).strip()
        current_session = self._runtime.chat_session
        current_session_id = current_session.session_id
        search_results = store.search_sessions(normalized_query, limit=max(limit, 50)) if normalized_query else []
        sessions = [] if normalized_query else store.list_sessions(limit=limit)
        session_items = []
        iterable_sessions = [result.session for result in search_results] if normalized_query else sessions
        search_by_session = {
            result.session.session_id: result
            for result in search_results
        }
        for session in iterable_sessions:
            messages = store.load_messages(session.session_id, limit=240)
            search_result = search_by_session.get(session.session_id)
            session_items.append({
                "session_id": session.session_id,
                "title": self._session_title(session.title, messages),
                **self._serialize_session_context(session),
                "created_at": session.created_at,
                "updated_at": self._session_updated_at(session.session_id, session.created_at, messages=messages),
                "message_count": session.message_count,
                "is_processing": self._session_is_processing(session.session_id),
                "latest_activity": self._latest_activity_for_session(session.session_id),
                "latest_message_preview": self._session_latest_user_turn(messages),
                "latest_message_status": self._session_latest_status(messages),
                "search_match": self._session_search_match(search_result, normalized_query),
            })
        if not normalized_query and not any(item["session_id"] == current_session_id for item in session_items):
            stored_current = store.get_session(current_session_id)
            current_messages = store.load_messages(current_session_id, limit=240)
            current_title = self._session_title(stored_current.title if stored_current else "", current_messages)
            current_context = self._serialize_session_context(stored_current) if stored_current else self._session_context()
            session_items.insert(
                0,
                {
                    "session_id": current_session_id,
                    "title": current_title or "新对话",
                    **current_context,
                    "created_at": stored_current.created_at if stored_current else "",
                    "updated_at": self._session_updated_at(
                        current_session_id,
                        stored_current.created_at if stored_current else "",
                        messages=current_messages,
                    ),
                    "message_count": stored_current.message_count if stored_current else 0,
                    "is_processing": self._session_is_processing(current_session_id),
                    "latest_activity": self._latest_activity_for_session(current_session_id),
                    "latest_message_preview": self._session_latest_user_turn(current_messages),
                    "latest_message_status": self._session_latest_status(current_messages),
                    "search_match": None,
                },
            )
        return {
            "ok": True,
            "current_session_id": current_session_id,
            "sessions": session_items,
            "query": normalized_query,
        }

    def _serialize_session_context(self, session: Any | None) -> dict[str, Any]:
        context = self._session_context(session)
        return {
            "conversation_kind": context["conversation_kind"],
            "runnable_id": context["runnable_id"],
            "runnable_name": context["runnable_name"],
            "run_group_id": context["run_group_id"],
            "avatar_url": context["avatar_url"],
            "participants": context["participants"],
        }

    @staticmethod
    def _session_search_match(search_result: Any, query: str) -> dict[str, Any] | None:
        if search_result is None or not query:
            return None
        snippet = _search_snippet(str(getattr(search_result, "match_content", "") or ""), query)
        match_message_id = getattr(search_result, "match_message_id", None)
        if not snippet and not match_message_id:
            return {
                "kind": "session",
                "query": query,
                "snippet": "会话标题或 Session ID 匹配",
                "match_count": int(getattr(search_result, "match_count", 0) or 0),
            }
        return {
            "kind": "message" if match_message_id else "session",
            "query": query,
            "message_id": match_message_id,
            "role": getattr(search_result, "match_role", "") or "",
            "snippet": snippet,
            "created_at": getattr(search_result, "match_created_at", "") or "",
            "match_count": int(getattr(search_result, "match_count", 0) or 0),
        }

    @staticmethod
    def _session_title(stored_title: str, messages: list[Any]) -> str:
        from apps.core.chat_store import make_session_title, strip_leading_session_mentions
        from apps.core.title_generator import looks_like_title_prompt_echo

        title = (stored_title or "").strip()
        if title and not ChatAPI._looks_like_session_id_title(title) and not looks_like_title_prompt_echo(title):
            return strip_leading_session_mentions(title) or title
        for msg in messages:
            if getattr(msg, "role", "") == MessageRole.USER.value:
                generated = make_session_title(str(getattr(msg, "content", "") or ""))
                if generated:
                    return generated
        return ""

    @staticmethod
    def _looks_like_session_id_title(value: str) -> bool:
        return bool(re.fullmatch(r"[a-f0-9]{8,32}", (value or "").strip(), flags=re.IGNORECASE))

    def load_session(self, session_id: str) -> Dict[str, Any]:
        """切换到指定历史会话。"""
        if not session_id:
            return {"ok": False, "error": "session_id 不能为空"}
        try:
            self._runtime.switch_session(session_id)
            return {
                "ok": True,
                "session_id": session_id,
                "message_count": self._runtime.chat_session.message_count(),
            }
        except Exception as exc:
            logger.error("切换会话失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def clear_session(self) -> Dict[str, Any]:
        """创建新会话；旧会话的后台任务继续写回原 session。"""
        try:
            self._sync_task_status_to_messages()
            previous_session_id = self._session.session_id
            start_new_session = getattr(self._runtime, "start_new_session", None)
            if callable(start_new_session):
                session_id = start_new_session()
            else:
                self._session.clear()
                session_id = self._session.session_id
            logger.info("新会话已创建: %s -> %s", previous_session_id, session_id)
            return {
                "ok": True,
                "session_id": session_id,
                "previous_session_id": previous_session_id,
                "cancelled_tasks": 0,
            }
        except Exception as exc:
            logger.error("清空会话失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def discard_empty_current_session(self) -> Dict[str, Any]:
        """丢弃当前空白会话，并切回最近历史会话。"""
        try:
            current_session_id = self._session.session_id
            if self._session_is_processing(current_session_id):
                return {"ok": True, "discarded": False, "session_id": current_session_id}

            store = self._chat_store()
            stored_session = store.get_session(current_session_id)
            if stored_session is not None and stored_session.conversation_kind == "group":
                return {"ok": True, "discarded": False, "session_id": current_session_id}

            messages = store.load_messages(current_session_id, limit=1)
            if messages:
                return {"ok": True, "discarded": False, "session_id": current_session_id}

            store.delete_session(current_session_id)
            _remove_attachment_session_dir(current_session_id)
            remaining = store.list_sessions(limit=1)
            if remaining:
                next_session_id = remaining[0].session_id
                switch_session = getattr(self._runtime, "switch_session", None)
                if not callable(switch_session):
                    raise RuntimeError("runtime 不支持切换会话")
                switch_session(next_session_id)
            else:
                self._session.clear()
                next_session_id = self._session.session_id

            logger.info("空白会话已丢弃: %s -> %s", current_session_id, next_session_id)
            return {
                "ok": True,
                "discarded": True,
                "deleted_session_id": current_session_id,
                "session_id": next_session_id,
                "empty": not remaining,
            }
        except Exception as exc:
            logger.error("丢弃空白会话失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def cancel_current_tasks(self) -> Dict[str, Any]:
        """取消当前会话中仍在等待/执行的任务，但保留会话历史。"""
        try:
            self._sync_task_status_to_messages()
            cancelled_count = self._cancel_active_session_tasks("用户停止生成")
            messages = self.get_messages()
            return {
                "ok": True,
                "cancelled_tasks": cancelled_count,
                "session_id": self._session.session_id,
                "messages": messages.get("messages", []),
                "is_processing": messages.get("is_processing", False),
            }
        except Exception as exc:
            logger.error("取消当前会话任务失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def _task_progress_label(self, task_id: str | None) -> str:
        if not task_id:
            return ""
        task = self._state.get_task(task_id)
        return str(getattr(task, "progress_label", "") or "") if task is not None else ""

    def _activity_events_by_task(self, task_ids: list[str | None], limit_per_task: int = 5) -> dict[str, list[dict[str, Any]]]:
        ids = [task_id for task_id in task_ids if task_id]
        if not ids:
            return {}
        try:
            store = get_activity_store()
            result: dict[str, list[dict[str, Any]]] = {}
            for task_id, events in store.latest_by_task(ids, limit_per_task=limit_per_task, key_only=True).items():
                visible = [
                    event_dict
                    for event in events
                    if _is_chat_visible_activity(event_dict := event.to_dict())
                ]
                if visible:
                    result[task_id] = visible
            return result
        except Exception:
            logger.debug("读取任务活动事件失败", exc_info=True)
            return {}

    def _latest_activity_for_session(self, session_id: str) -> dict[str, Any]:
        try:
            events = get_activity_store().list_events(session_id=session_id, limit=1, key_only=True)
            return events[0].to_dict() if events else {}
        except Exception:
            logger.debug("读取会话最新活动失败", exc_info=True)
            return {}

    def _session_is_processing(self, session_id: str) -> bool:
        for task in self._state.list_tasks():
            if getattr(task, "chat_session_id", None) != session_id:
                continue
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                return True
        return False

    def _session_updated_at(self, session_id: str, fallback: str = "", messages: list[Any] | None = None) -> str:
        try:
            messages = messages if messages is not None else self._chat_store().load_messages(session_id, limit=240)
        except Exception:
            return fallback
        latest = messages[-1].created_at if messages else fallback
        activity = self._latest_activity_for_session(session_id)
        activity_time = str(activity.get("created_at") or "")
        return max([value for value in (latest, activity_time, fallback) if value] or [""])

    def _session_latest_user_turn(self, messages: list[Any]) -> str:
        for msg in reversed(messages):
            if getattr(msg, "role", "") == MessageRole.USER.value and str(getattr(msg, "content", "") or "").strip():
                return _compact_preview(getattr(msg, "content", ""))
        for msg in reversed(messages):
            if str(getattr(msg, "content", "") or "").strip():
                return _compact_preview(getattr(msg, "content", ""))
        return ""

    def _session_latest_status(self, messages: list[Any]) -> str:
        for msg in reversed(messages):
            status = str(getattr(msg, "status", "") or "")
            if status:
                return status
        return ""

    def delete_current_session(self) -> Dict[str, Any]:
        """删除当前会话，并切换到剩余最近会话或新建空会话。"""
        try:
            self._sync_task_status_to_messages()
            cancelled_count = self._cancel_active_session_tasks("删除会话前取消仍在执行的任务")
            deleted_session_id = self._session.session_id

            store = self._chat_store()
            store.delete_session(deleted_session_id)
            _remove_attachment_session_dir(deleted_session_id)
            remaining = store.list_sessions(limit=1)
            remaining_count = store.count_sessions()

            if remaining:
                next_session_id = remaining[0].session_id
                switch_session = getattr(self._runtime, "switch_session", None)
                if not callable(switch_session):
                    raise RuntimeError("runtime 不支持切换会话")
                switch_session(next_session_id)
            else:
                self._session.clear()
                next_session_id = self._session.session_id

            logger.info(
                "当前会话已删除: %s -> %s，已取消任务数=%d",
                deleted_session_id,
                next_session_id,
                cancelled_count,
            )
            return {
                "ok": True,
                "deleted_session_id": deleted_session_id,
                "session_id": next_session_id,
                "cancelled_tasks": cancelled_count,
                "remaining_sessions": remaining_count,
                "empty": not remaining,
            }
        except Exception as exc:
            logger.error("删除当前会话失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def _cancel_active_session_tasks(self, reason: str) -> int:
        """取消当前会话中仍在等待/执行的任务，并持久化取消提示。"""
        active_task_ids: list[str] = []
        seen: set[str] = set()

        for msg in self._session.get_all_messages():
            if msg.role not in (MessageRole.USER, MessageRole.ASSISTANT):
                continue
            if msg.status not in (MessageStatus.PENDING, MessageStatus.PROCESSING):
                continue
            if not msg.task_id or msg.task_id in seen:
                continue
            task = self._state.get_task(msg.task_id)
            if task is None or task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
                continue
            seen.add(msg.task_id)
            active_task_ids.append(msg.task_id)

        cancelled = 0
        for task_id in active_task_ids:
            task = self._state.get_task(task_id)
            if task is None:
                continue
            did_cancel = False
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                try:
                    self._state.cancel_task(task_id)
                    cancel_runner_task = getattr(
                        self._runtime, "cancel_task_runner_task", None
                    )
                    if callable(cancel_runner_task):
                        cancel_runner_task(task_id)
                    cancelled += 1
                    did_cancel = True
                except (KeyError, ValueError):
                    logger.debug("任务取消跳过: %s", task_id, exc_info=True)

            task = self._state.get_task(task_id)
            if did_cancel and task is not None and task.status == TaskStatus.CANCELLED:
                try:
                    activity_store = get_activity_store()
                    activity_store.finalize_task_events(task_id, status="cancelled")
                    activity_store.record_event(
                        session_id=self._session.session_id,
                        task_id=task_id,
                        tool_name="hermes",
                        phase="task_cancelled",
                        title="Yachiyo 已停止",
                        detail=reason,
                        status="cancelled",
                    )
                except Exception:
                    logger.debug("收尾取消任务活动事件失败: %s", task_id, exc_info=True)
                error = "任务已取消"
                self._session.upsert_assistant_message(
                    task_id=task_id,
                    content=f"⚠️ {error}",
                    status=MessageStatus.FAILED,
                    error=error,
                )

        return cancelled
