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
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List
from uuid import uuid4

from apps.core.chat_session import (
    ChatMessage,
    ChatSession,
    MessageRole,
    MessageStatus,
)
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

    def send_message(self, text: str, attachments: list[dict] | None = None) -> Dict[str, Any]:
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

            # 1. 添加用户消息
            message_id = self._session.add_user_message(text, saved_attachments)

            # 2. 创建任务
            task = self._state.create_task(
                task_type=TaskType.GENERAL,
                description=text,
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
                len(text),
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

    def _should_enforce_image_capability(self) -> bool:
        runner = getattr(self._runtime, "task_runner", None)
        if runner is None:
            return False
        executor = getattr(runner, "executor", None)
        return getattr(executor, "name", "") == "HermesExecutor"

    def get_messages(self, limit: int = 50) -> Dict[str, Any]:
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

            messages = self._session.get_messages(limit)
            sorted_msgs = self._sort_messages_by_task(messages)
            return {
                "ok": True,
                "session_id": self._session.session_id,
                "is_processing": self._session.is_processing(),
                "messages": [
                    {
                        "id": m.message_id,
                        "role": m.role.value,
                        "content": m.content,
                        "status": m.status.value,
                        "task_id": m.task_id,
                        "error": m.error,
                        "created_at": m.created_at.isoformat(),
                        "attachments": self._serialize_attachments(m.attachments),
                    }
                    for m in sorted_msgs
                ],
            }

        except Exception as exc:
            logger.error("获取消息列表失败: %s", exc)
            return {"ok": False, "error": str(exc), "messages": []}

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
        # 消息保持原本时间线位置。
        assistant_by_task: dict[str, ChatMessage] = {}
        for msg in messages:
            if msg.role == MessageRole.ASSISTANT and msg.task_id in user_task_ids:
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

        # 兜底：分页/limit 截断时 user 可能不在当前列表，不能丢弃这些 assistant。
        for msg in messages:
            if (
                msg.role == MessageRole.ASSISTANT
                and msg.task_id in user_task_ids
                and msg.message_id not in inserted_assistant_ids
            ):
                result.append(msg)

        return result

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
                elif assistant.status != MessageStatus.PROCESSING:
                    self._session.upsert_assistant_message(
                        task_id=msg.task_id,
                        content=assistant.content,
                        status=MessageStatus.PROCESSING,
                        error=assistant.error,
                    )

    def get_session_info(self) -> Dict[str, Any]:
        """获取会话元信息"""
        return {
            "session_id": self._session.session_id,
            "message_count": self._session.message_count(),
            "is_processing": self._session.is_processing(),
            "pending_message_id": self._session.get_pending_message_id(),
        }

    def get_executor_info(self) -> Dict[str, Any]:
        image_input = get_current_hermes_image_input_capability()
        runner = self._runtime.task_runner
        if runner is None:
            return {"executor": "none", "available": False, "image_input": image_input}
        return {"executor": runner.executor.name, "available": True, "image_input": image_input}

    def list_sessions(self, limit: int = 20) -> Dict[str, Any]:
        """列出最近会话，包含当前空白会话。"""
        from apps.core.chat_store import get_chat_store

        store = get_chat_store()
        current_session = self._runtime.chat_session
        current_session_id = current_session.session_id
        sessions = store.list_sessions(limit=limit)
        session_items = [
            {
                "session_id": session.session_id,
                "title": session.title,
                "created_at": session.created_at,
                "message_count": session.message_count,
            }
            for session in sessions
        ]
        if not any(item["session_id"] == current_session_id for item in session_items):
            stored_current = store.get_session(current_session_id)
            session_items.insert(
                0,
                {
                    "session_id": current_session_id,
                    "title": (stored_current.title if stored_current else "") or "新对话",
                    "created_at": stored_current.created_at if stored_current else "",
                    "message_count": stored_current.message_count if stored_current else 0,
                },
            )
        return {
            "ok": True,
            "current_session_id": current_session_id,
            "sessions": session_items,
        }

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
        """清空会话"""
        try:
            self._sync_task_status_to_messages()
            cancelled_count = self._cancel_active_session_tasks()
            self._session.clear()
            logger.info("会话已清空，已取消旧会话任务数=%d", cancelled_count)
            return {
                "ok": True,
                "session_id": self._session.session_id,
                "cancelled_tasks": cancelled_count,
            }
        except Exception as exc:
            logger.error("清空会话失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def cancel_current_tasks(self) -> Dict[str, Any]:
        """取消当前会话中仍在等待/执行的任务，但保留会话历史。"""
        try:
            self._sync_task_status_to_messages()
            cancelled_count = self._cancel_active_session_tasks()
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

    def delete_current_session(self) -> Dict[str, Any]:
        """删除当前会话，并切换到剩余最近会话或新建空会话。"""
        try:
            self._sync_task_status_to_messages()
            cancelled_count = self._cancel_active_session_tasks()
            deleted_session_id = self._session.session_id

            from apps.core.chat_store import get_chat_store

            store = get_chat_store()
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

    def _cancel_active_session_tasks(self) -> int:
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
            seen.add(msg.task_id)
            active_task_ids.append(msg.task_id)

        cancelled = 0
        for task_id in active_task_ids:
            task = self._state.get_task(task_id)
            if task is None:
                continue
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                try:
                    self._state.cancel_task(task_id)
                    cancel_runner_task = getattr(
                        self._runtime, "cancel_task_runner_task", None
                    )
                    if callable(cancel_runner_task):
                        cancel_runner_task(task_id)
                    cancelled += 1
                except (KeyError, ValueError):
                    logger.debug("任务取消跳过: %s", task_id, exc_info=True)

            task = self._state.get_task(task_id)
            if task is not None and task.status == TaskStatus.CANCELLED:
                error = "任务已取消"
                self._session.upsert_assistant_message(
                    task_id=task_id,
                    content=f"⚠️ {error}",
                    status=MessageStatus.FAILED,
                    error=error,
                )

        return cancelled
