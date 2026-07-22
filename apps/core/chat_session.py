"""统一聊天/会话层

ChatSession 是 Bubble / Live2D / Chat Window / 主控台摘要共享的消息状态容器。

职责：
  - 管理当前会话的消息列表（user / assistant / system）
  - 追踪发送中状态（pending message）
  - 追踪最近任务 ID（关联 task 结果）
  - 不直接执行任务，只维护消息状态

消息流：
  1. UI 调用 add_user_message(text) → 返回 message_id
  2. UI 创建 task（通过 AppState.create_task）
  3. UI 调用 link_message_to_task(message_id, task_id) → 关联消息与任务
  4. TaskRunner 执行完毕后，调用 add_assistant_message(text, task_id)
  5. UI 轮询 get_messages() 获取最新消息列表

消息会通过 ChatStore 持久化到 SQLite。进程重启时默认恢复最近会话。
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
from uuid import uuid4

from packages.security import redact_sensitive_text, sanitize_sensitive_value

if TYPE_CHECKING:
    from apps.core.chat_store import ChatStore

logger = logging.getLogger(__name__)
_CHAT_TEXT_REDACTION_LIMIT = 0
_CHAT_JSON_MAX_ITEMS = 200
_ASSISTANT_PROJECTION_KEY = "assistant_projection_key"


class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageStatus(str, Enum):
    """消息状态"""
    PENDING = "pending"      # 用户消息已发送，等待 agent 回复
    PROCESSING = "processing"  # 任务正在执行
    COMPLETED = "completed"  # 已收到回复
    FAILED = "failed"        # 处理失败


@dataclass
class ChatMessage:
    """单条聊天消息"""
    message_id: str
    role: MessageRole
    content: str
    status: MessageStatus
    created_at: datetime
    task_id: Optional[str] = None  # 关联的任务 ID（仅 user 消息）
    error: Optional[str] = None    # 失败原因
    attachments: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ChatSession:
    """聊天会话状态容器
    
    线程安全性：多窗口 WebView API 和 TaskRunner 可能并发读写同一会话，
    所有公开读写方法都通过内部 RLock 保护。
    """
    session_id: str = field(default_factory=lambda: uuid4().hex[:8])
    messages: List[ChatMessage] = field(default_factory=list)
    execution_session_id: Optional[str] = field(default=None)
    _pending_message_id: Optional[str] = field(default=None, repr=False)
    _store: Optional["ChatStore"] = field(default=None, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def attach_store(
        self,
        store: "ChatStore",
        load_existing: bool = True,
        fail_active_messages: bool = True,
        create_if_missing: bool = True,
    ) -> None:
        """绑定持久化层，并创建/加载会话。"""
        with self._lock:
            self._store = store
            if create_if_missing:
                store.create_session(self.session_id)
            if load_existing:
                self._load_messages_from_store(fail_active_messages=fail_active_messages)
                # 恢复 execution_session_id
                stored_session = store.get_session(self.session_id)
                if stored_session and stored_session.execution_session_id:
                    self.execution_session_id = stored_session.execution_session_id

    def _load_messages_from_store(self, *, fail_active_messages: bool = True) -> None:
        """从持久化层恢复当前会话消息。"""
        if self._store is None:
            return

        restored: list[ChatMessage] = []
        for stored in self._store.load_messages(self.session_id, limit=0):
            try:
                role = MessageRole(stored.role)
                status = MessageStatus(stored.status)
                created_at = datetime.fromisoformat(stored.created_at)
            except ValueError:
                logger.warning("跳过无法恢复的聊天消息: %s", stored.message_id)
                continue

            error = stored.error
            attachments = _parse_attachments_json(stored.attachments_json)
            metadata = _parse_metadata_json(getattr(stored, "metadata_json", "{}"))
            if fail_active_messages and status in (MessageStatus.PENDING, MessageStatus.PROCESSING):
                status = MessageStatus.FAILED
                error = error or "应用已重启，原任务状态不可恢复"
                self._store.update_message_status(stored.message_id, status.value, error)

            restored.append(ChatMessage(
                message_id=stored.message_id,
                role=role,
                content=_redact_chat_text(stored.content),
                status=status,
                created_at=created_at,
                task_id=stored.task_id,
                error=_redact_optional_chat_text(error),
                attachments=_redact_chat_attachments(attachments),
                metadata=_redact_chat_metadata(metadata),
            ))

        self.messages = restored
        self._dedupe_assistant_messages_locked()
        self._pending_message_id = None

    def reload_from_store(self, *, fail_active_messages: bool = False) -> None:
        """刷新当前会话的持久化消息快照。"""
        with self._lock:
            self._load_messages_from_store(fail_active_messages=fail_active_messages)

    def _persist_message(self, msg: ChatMessage) -> None:
        """将消息写入持久化层（若已绑定）"""
        if self._store is None:
            return
        from apps.core.chat_store import StoredMessage
        self._store.save_message(StoredMessage(
            message_id=msg.message_id,
            session_id=self.session_id,
            role=msg.role.value,
            content=_redact_chat_text(msg.content),
            status=msg.status.value,
            task_id=msg.task_id,
            error=_redact_optional_chat_text(msg.error),
            created_at=msg.created_at.isoformat(),
            attachments_json=json.dumps(_redact_chat_attachments(msg.attachments), ensure_ascii=False),
            metadata_json=json.dumps(_redact_chat_metadata(msg.metadata), ensure_ascii=False),
        ))

    def _ensure_summary_title_locked(self, content: str, attachments: list[dict] | None = None) -> None:
        """为无标题会话写入首条用户消息摘要。调用方需持有 _lock。"""
        if self._store is None:
            return
        from apps.core.chat_store import make_session_title

        title = make_session_title(content)
        if not title and attachments:
            title = f"图片分析 ({len(attachments)})"
        if title:
            self._store.set_session_title_if_empty(self.session_id, title)
    
    def add_user_message(
        self,
        content: str,
        attachments: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> str:
        """添加用户消息，返回 message_id"""
        safe_content = _redact_chat_text(content)
        normalized_attachments = _redact_chat_attachments(attachments or [])
        safe_metadata = _redact_chat_metadata(metadata or {})
        with self._lock:
            msg_id = uuid4().hex[:12]
            msg = ChatMessage(
                message_id=msg_id,
                role=MessageRole.USER,
                content=safe_content,
                status=MessageStatus.PENDING,
                created_at=datetime.now(timezone.utc),
                attachments=normalized_attachments,
                metadata=safe_metadata,
            )
            self.messages.append(msg)
            self._pending_message_id = msg_id
            self._persist_message(msg)
            self._ensure_summary_title_locked(safe_content, normalized_attachments)
        logger.info("用户消息已添加: %s (len=%d, attachments=%d)", msg_id, len(safe_content), len(normalized_attachments))
        return msg_id

    def upsert_user_message_by_client_id(
        self,
        content: str,
        *,
        client_message_id: str,
        task_id: str = "",
        status: MessageStatus = MessageStatus.PROCESSING,
        attachments: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Persist one canonical user message for an idempotent client send."""
        normalized_client_id = str(client_message_id or "").strip()
        if not normalized_client_id:
            raise ValueError("client_message_id must not be empty")

        safe_content = _redact_chat_text(content)
        safe_attachments = _redact_chat_attachments(attachments or [])
        safe_metadata = _redact_chat_metadata(metadata or {})
        safe_metadata["client_message_id"] = normalized_client_id
        deterministic_id = self._client_user_message_id(normalized_client_id)
        clean_task_id = str(task_id or "").strip()

        with self._lock:
            existing = self._user_message_by_client_id_locked(
                normalized_client_id,
                deterministic_id,
            )
            if existing is not None:
                next_status = (
                    status
                    if existing.status in (MessageStatus.PENDING, MessageStatus.PROCESSING)
                    else existing.status
                )
                updated = replace(
                    existing,
                    task_id=existing.task_id or clean_task_id or None,
                    status=next_status,
                    attachments=(
                        existing.attachments
                        if existing.attachments or not safe_attachments
                        else safe_attachments
                    ),
                    metadata={**dict(existing.metadata or {}), **safe_metadata},
                )
                self._persist_message(updated)
                self.messages = [
                    updated if message.message_id == existing.message_id else message
                    for message in self.messages
                ]
                self._pending_message_id = self._find_active_message_id_locked()
                return updated.message_id

            message = ChatMessage(
                message_id=deterministic_id,
                role=MessageRole.USER,
                content=safe_content,
                status=status,
                created_at=datetime.now(timezone.utc),
                task_id=clean_task_id or None,
                attachments=safe_attachments,
                metadata=safe_metadata,
            )
            self._persist_message(message)
            self.messages.append(message)
            self._ensure_summary_title_locked(safe_content, safe_attachments)
            self._pending_message_id = self._find_active_message_id_locked()
            return message.message_id

    def _client_user_message_id(self, client_message_id: str) -> str:
        identity = "\x1f".join((self.session_id, MessageRole.USER.value, client_message_id))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return f"user_{digest[:24]}"

    def _user_message_by_client_id_locked(
        self,
        client_message_id: str,
        deterministic_id: str,
    ) -> Optional[ChatMessage]:
        loader = getattr(self._store, "load_messages", None)
        if callable(loader):
            for stored in loader(self.session_id, limit=0):
                if stored.role != MessageRole.USER.value:
                    continue
                stored_metadata = _parse_metadata_json(
                    getattr(stored, "metadata_json", "{}")
                )
                if (
                    stored.message_id != deterministic_id
                    and str(stored_metadata.get("client_message_id") or "")
                    != client_message_id
                ):
                    continue
                try:
                    persisted = _chat_message_from_stored(
                        stored,
                        fail_active_message=False,
                    )
                except ValueError:
                    continue
                self.messages = [
                    message
                    for message in self.messages
                    if not (
                        message.role == MessageRole.USER
                        and (
                            message.message_id == deterministic_id
                            or str((message.metadata or {}).get("client_message_id") or "")
                            == client_message_id
                        )
                    )
                ]
                self.messages.append(persisted)
                self.messages.sort(key=lambda item: item.created_at)
                return persisted

        for message in self.messages:
            metadata = message.metadata if isinstance(message.metadata, dict) else {}
            if message.role == MessageRole.USER and (
                message.message_id == deterministic_id
                or str(metadata.get("client_message_id") or "") == client_message_id
            ):
                return message
        return None
    
    def link_message_to_task(self, message_id: str, task_id: str) -> bool:
        """将消息与任务关联。

        这里只建立关联，不代表任务已经开始运行。用户消息保持 PENDING，
        直到 TaskStatus.RUNNING 同步过来后再切换为 PROCESSING。
        """
        with self._lock:
            for msg in self.messages:
                if msg.message_id == message_id:
                    msg.task_id = task_id
                    self._persist_message(msg)
                    logger.debug("消息 %s 关联任务 %s", message_id, task_id)
                    return True
        return False

    def update_message_metadata_for_task(
        self,
        task_id: str,
        metadata: dict | None,
        *,
        role: MessageRole | str | None = None,
    ) -> bool:
        """Merge metadata into the first message for a task, preserving existing fields."""
        if not task_id or not metadata:
            return False
        safe_metadata = _redact_chat_metadata(metadata)
        role_value = role.value if isinstance(role, MessageRole) else str(role or "")
        with self._lock:
            for msg in self.messages:
                if msg.task_id != task_id:
                    continue
                if role_value and msg.role.value != role_value:
                    continue
                for key, value in safe_metadata.items():
                    if value is None:
                        msg.metadata.pop(key, None)
                    else:
                        msg.metadata[key] = value
                self._persist_message(msg)
                return True
        return False
    
    def add_assistant_message(
        self,
        content: str,
        task_id: Optional[str] = None,
        error: Optional[str] = None,
        metadata: dict | None = None,
    ) -> str:
        """添加 assistant 回复消息（向后兼容）

        注意：对于 task 关联的 assistant 消息，应优先使用
        upsert_assistant_message() 以保证幂等性。
        """
        safe_content = _redact_chat_text(content)
        safe_error = _redact_optional_chat_text(error)
        safe_metadata = _redact_chat_metadata(metadata or {})
        with self._lock:
            msg_id = uuid4().hex[:12]
            status = MessageStatus.FAILED if safe_error else MessageStatus.COMPLETED
            msg = ChatMessage(
                message_id=msg_id,
                role=MessageRole.ASSISTANT,
                content=safe_content,
                status=status,
                created_at=datetime.now(timezone.utc),
                task_id=task_id,
                error=safe_error,
                metadata=safe_metadata,
            )
            self.messages.append(msg)

            # 更新对应 user 消息状态
            if task_id:
                for m in self.messages:
                    if m.task_id == task_id and m.role == MessageRole.USER:
                        m.status = status
                        if safe_error:
                            m.error = safe_error
                        self._persist_message(m)
                        break

            self._pending_message_id = self._find_active_message_id_locked()
            self._persist_message(msg)
        logger.info("Assistant 回复已添加: %s (task=%s)", msg_id, task_id)
        return msg_id

    def upsert_assistant_projection_message(
        self,
        projection_key: str,
        content: str,
        status: MessageStatus = MessageStatus.COMPLETED,
        error: Optional[str] = None,
        metadata: dict | None = None,
        *,
        message_id: str = "",
    ) -> str:
        """Atomically create or update one derived assistant projection.

        ``projection_key`` is scoped to this chat session and the assistant
        role.  The deterministic message id also makes concurrent projections
        from separate ``ChatSession`` instances converge on one persisted row.
        Callers must include every source identity component in the key; for a
        Workflow child that is the parent Workflow Run and child Agent Run.
        """
        normalized_key = str(projection_key or "").strip()
        if not normalized_key:
            raise ValueError("projection_key must not be empty")

        safe_content = _redact_chat_text(content)
        safe_error = _redact_optional_chat_text(error)
        safe_metadata = _redact_chat_metadata(metadata or {})
        safe_metadata[_ASSISTANT_PROJECTION_KEY] = normalized_key
        message_id = (
            str(message_id or "").strip()
            or self._assistant_projection_message_id(normalized_key)
        )

        with self._lock:
            projection_upserter = getattr(
                self._store,
                "upsert_projection_message",
                None,
            )
            if callable(projection_upserter):
                from apps.core.chat_store import StoredMessage

                stored = projection_upserter(StoredMessage(
                    message_id=message_id,
                    session_id=self.session_id,
                    role=MessageRole.ASSISTANT.value,
                    content=safe_content,
                    status=status.value,
                    task_id=None,
                    error=safe_error,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    attachments_json="[]",
                    metadata_json=json.dumps(safe_metadata, ensure_ascii=False),
                ))
                projected = _chat_message_from_stored(
                    stored,
                    fail_active_message=False,
                )
                next_messages: list[ChatMessage] = []
                inserted = False
                for item in self.messages:
                    item_metadata = (
                        item.metadata if isinstance(item.metadata, dict) else {}
                    )
                    is_same_projection = (
                        item.role == MessageRole.ASSISTANT
                        and (
                            item.message_id == message_id
                            or str(
                                item_metadata.get(_ASSISTANT_PROJECTION_KEY) or ""
                            )
                            == normalized_key
                        )
                    )
                    if not is_same_projection:
                        next_messages.append(item)
                        continue
                    if not inserted:
                        next_messages.append(projected)
                        inserted = True
                if not inserted:
                    next_messages.append(projected)
                self.messages = next_messages
                self._pending_message_id = self._find_active_message_id_locked()
                return projected.message_id

            existing = self._assistant_projection_candidate_locked(
                normalized_key,
                message_id,
            )
            if existing is not None:
                # A stale poll must not regress a terminal callback projection.
                if (
                    existing.status in (MessageStatus.COMPLETED, MessageStatus.FAILED)
                    and status == MessageStatus.PROCESSING
                ):
                    self._pending_message_id = self._find_active_message_id_locked()
                    return existing.message_id
                existing.content = safe_content
                existing.status = status
                existing.error = safe_error
                existing.metadata.update(safe_metadata)
                self._persist_message(existing)
                self._pending_message_id = self._find_active_message_id_locked()
                return existing.message_id

            message = ChatMessage(
                message_id=message_id,
                role=MessageRole.ASSISTANT,
                content=safe_content,
                status=status,
                created_at=datetime.now(timezone.utc),
                error=safe_error,
                metadata=safe_metadata,
            )
            self.messages.append(message)
            self._persist_message(message)
            self._pending_message_id = self._find_active_message_id_locked()
            return message_id

    def _assistant_projection_message_id(self, projection_key: str) -> str:
        identity = "\x1f".join(
            (self.session_id, MessageRole.ASSISTANT.value, projection_key)
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return f"projection_{digest[:24]}"

    def _assistant_projection_candidate_locked(
        self,
        projection_key: str,
        message_id: str,
    ) -> Optional[ChatMessage]:
        memory_candidate: Optional[ChatMessage] = None
        memory_index = -1
        for index, message in enumerate(self.messages):
            if message.role != MessageRole.ASSISTANT:
                continue
            metadata = message.metadata if isinstance(message.metadata, dict) else {}
            if (
                message.message_id == message_id
                or str(metadata.get(_ASSISTANT_PROJECTION_KEY) or "") == projection_key
            ):
                memory_candidate = message
                memory_index = index
                break

        loader = getattr(self._store, "load_messages", None)
        if not callable(loader):
            return memory_candidate
        try:
            stored_messages = loader(self.session_id, limit=0)
        except Exception:
            logger.debug(
                "加载持久化 assistant 投影失败: key=%s",
                projection_key,
                exc_info=True,
            )
            return memory_candidate
        persisted_candidate: Optional[ChatMessage] = None
        for stored in stored_messages:
            if stored.role != MessageRole.ASSISTANT.value:
                continue
            stored_metadata = _parse_metadata_json(
                getattr(stored, "metadata_json", "{}")
            )
            if (
                stored.message_id != message_id
                and str(stored_metadata.get(_ASSISTANT_PROJECTION_KEY) or "")
                != projection_key
            ):
                continue
            try:
                message = _chat_message_from_stored(
                    stored,
                    fail_active_message=False,
                )
            except ValueError:
                logger.warning("跳过无法恢复的 assistant 投影: %s", stored.message_id)
                continue
            if (
                persisted_candidate is None
                or (
                    persisted_candidate.status
                    not in (MessageStatus.COMPLETED, MessageStatus.FAILED)
                    and message.status
                    in (MessageStatus.COMPLETED, MessageStatus.FAILED)
                )
            ):
                persisted_candidate = message

        if persisted_candidate is None:
            return memory_candidate
        if memory_candidate is None:
            self.messages.append(persisted_candidate)
            return persisted_candidate
        if (
            memory_candidate.status in (MessageStatus.COMPLETED, MessageStatus.FAILED)
            and persisted_candidate.status
            not in (MessageStatus.COMPLETED, MessageStatus.FAILED)
        ):
            return memory_candidate

        # The store is the shared concurrency boundary between ChatSession
        # instances.  Refresh a stale in-memory projection before deciding
        # whether the incoming write may change its status.
        self.messages[memory_index] = persisted_candidate
        return persisted_candidate

    def upsert_assistant_message(
        self,
        task_id: str,
        content: str,
        status: MessageStatus = MessageStatus.COMPLETED,
        error: Optional[str] = None,
        attachments: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> str:
        """原子性地创建或更新 task_id 对应的 assistant 消息。

        同一个 task_id 至多只有一条 assistant 消息。
        已存在则更新 content/status/error，否则创建。
        同时同步更新关联 user 消息的状态。

        幂等：多次调用相同参数不会产生重复消息。
        线程安全：check + create/update 在同一把锁内完成。
        """
        safe_content = _redact_chat_text(content)
        safe_error = _redact_optional_chat_text(error)
        safe_attachments = _redact_chat_attachments(attachments or []) if attachments is not None else None
        safe_metadata = _redact_chat_metadata(metadata or {}) if metadata is not None else None
        with self._lock:
            candidates = self._assistant_candidates_for_task_locked(task_id)
            existing = self._select_assistant_candidate(candidates, status)

            if existing is not None:
                self._drop_duplicate_assistant_messages_locked(task_id, existing.message_id)
                # 不允许从终态回退到 PROCESSING。跨实例写回时，旧会话对象
                # 可能在最终消息已落库后继续收到 activity/streaming 回调。
                if (
                    existing.status in (MessageStatus.COMPLETED, MessageStatus.FAILED)
                    and status == MessageStatus.PROCESSING
                ):
                    self._sync_user_status_for_task_locked(task_id, existing.status, existing.error)
                    self._pending_message_id = self._find_active_message_id_locked()
                    return existing.message_id
                existing.content = safe_content
                existing.status = status
                existing.error = safe_error
                if safe_attachments is not None:
                    existing.attachments = safe_attachments
                if safe_metadata is not None:
                    existing.metadata = safe_metadata
                self._persist_message(existing)
                msg_id = existing.message_id
                logger.debug(
                    "Assistant 消息已更新: %s (task=%s, status=%s)",
                    msg_id, task_id, status.value,
                )
            else:
                msg_id = uuid4().hex[:12]
                new_msg = ChatMessage(
                    message_id=msg_id,
                    role=MessageRole.ASSISTANT,
                    content=safe_content,
                    status=status,
                    created_at=datetime.now(timezone.utc),
                    task_id=task_id,
                    error=safe_error,
                    attachments=safe_attachments or [],
                    metadata=safe_metadata or {},
                )
                self.messages.append(new_msg)
                self._persist_message(new_msg)
                logger.info(
                    "Assistant 消息已创建: %s (task=%s, status=%s)",
                    msg_id, task_id, status.value,
                )

            self._sync_user_status_for_task_locked(task_id, status, safe_error)
            self._pending_message_id = self._find_active_message_id_locked()
            return msg_id

    def _assistant_candidates_for_task_locked(self, task_id: str) -> list[ChatMessage]:
        """Return in-memory + persisted assistant candidates for one task.

        `upsert_assistant_message()` may run concurrently from multiple
        ChatSession instances. The store lookup makes the idempotency boundary
        the persisted session/task pair instead of the current Python object.
        """
        candidates = [
            msg
            for msg in self.messages
            if msg.role == MessageRole.ASSISTANT and msg.task_id == task_id
        ]
        seen_ids = {msg.message_id for msg in candidates}
        loader = getattr(self._store, "load_assistant_messages_by_task", None)
        if not callable(loader):
            return candidates
        try:
            stored_messages = loader(self.session_id, task_id)
        except Exception:
            logger.debug("加载持久化 assistant 消息失败: task=%s", task_id, exc_info=True)
            return candidates

        added = False
        for stored in stored_messages:
            if stored.message_id in seen_ids:
                continue
            try:
                msg = _chat_message_from_stored(stored, fail_active_message=False)
            except ValueError:
                logger.warning("跳过无法恢复的 assistant 消息: %s", stored.message_id)
                continue
            candidates.append(msg)
            self.messages.append(msg)
            seen_ids.add(msg.message_id)
            added = True
        if added:
            self.messages.sort(key=lambda msg: msg.created_at)
        return candidates

    @staticmethod
    def _select_assistant_candidate(
        candidates: list[ChatMessage],
        incoming_status: MessageStatus,
    ) -> Optional[ChatMessage]:
        if not candidates:
            return None
        terminal = [
            msg
            for msg in candidates
            if msg.status in (MessageStatus.COMPLETED, MessageStatus.FAILED)
        ]
        if terminal:
            return sorted(terminal, key=lambda msg: msg.created_at, reverse=True)[0]
        if incoming_status in (MessageStatus.COMPLETED, MessageStatus.FAILED):
            return sorted(candidates, key=lambda msg: msg.created_at)[0]
        return sorted(candidates, key=lambda msg: msg.created_at)[0]

    def _drop_duplicate_assistant_messages_locked(self, task_id: str, keep_message_id: str) -> None:
        duplicate_ids: list[str] = []
        next_messages: list[ChatMessage] = []
        for msg in self.messages:
            if (
                msg.role == MessageRole.ASSISTANT
                and msg.task_id == task_id
                and msg.message_id != keep_message_id
            ):
                duplicate_ids.append(msg.message_id)
                continue
            next_messages.append(msg)
        if duplicate_ids:
            self.messages = next_messages
            deleter = getattr(self._store, "delete_messages", None)
            if callable(deleter):
                try:
                    deleter(sorted(set(duplicate_ids)))
                except Exception:
                    logger.debug(
                        "删除重复 assistant 消息失败: %s",
                        duplicate_ids,
                        exc_info=True,
                    )

    def _dedupe_assistant_messages_locked(self) -> None:
        by_task: dict[str, list[ChatMessage]] = {}
        for msg in self.messages:
            if msg.role == MessageRole.ASSISTANT and msg.task_id:
                by_task.setdefault(msg.task_id, []).append(msg)

        for task_id, candidates in by_task.items():
            if len(candidates) <= 1:
                continue
            keep = self._select_assistant_candidate(candidates, MessageStatus.COMPLETED)
            if keep is None:
                continue
            self._drop_duplicate_assistant_messages_locked(task_id, keep.message_id)
            self._sync_user_status_for_task_locked(task_id, keep.status, keep.error)

    def _sync_user_status_for_task_locked(
        self,
        task_id: str,
        status: MessageStatus,
        error: Optional[str],
    ) -> None:
        for msg in self.messages:
            if msg.task_id == task_id and msg.role == MessageRole.USER:
                msg.status = status
                if status == MessageStatus.FAILED and error:
                    msg.error = _redact_chat_text(error)
                elif status != MessageStatus.FAILED:
                    msg.error = None
                self._persist_message(msg)
                break
    
    def add_system_message(self, content: str, metadata: dict | None = None) -> str:
        """添加系统消息（提示、状态更新等）"""
        safe_content = _redact_chat_text(content)
        safe_metadata = _redact_chat_metadata(metadata or {})
        with self._lock:
            msg_id = uuid4().hex[:12]
            msg = ChatMessage(
                message_id=msg_id,
                role=MessageRole.SYSTEM,
                content=safe_content,
                status=MessageStatus.COMPLETED,
                created_at=datetime.now(timezone.utc),
                metadata=safe_metadata,
            )
            self.messages.append(msg)
            self._persist_message(msg)
            return msg_id
    
    def mark_message_failed(self, message_id: str, error: str) -> bool:
        """标记消息处理失败"""
        safe_error = _redact_chat_text(error)
        with self._lock:
            for msg in self.messages:
                if msg.message_id == message_id:
                    msg.status = MessageStatus.FAILED
                    msg.error = safe_error
                    self._pending_message_id = self._find_active_message_id_locked()
                    self._persist_message(msg)
                    return True
        return False

    def mark_message_completed(self, message_id: str) -> bool:
        """Mark a synthetic Agent/Workflow command as completed."""
        with self._lock:
            for msg in self.messages:
                if msg.message_id == message_id:
                    msg.status = MessageStatus.COMPLETED
                    msg.error = None
                    self._pending_message_id = self._find_active_message_id_locked()
                    self._persist_message(msg)
                    return True
        return False

    def mark_message_processing(self, message_id: str) -> bool:
        """标记用户消息进入执行中状态。"""
        with self._lock:
            for msg in self.messages:
                if msg.message_id == message_id:
                    msg.status = MessageStatus.PROCESSING
                    self._pending_message_id = message_id
                    self._persist_message(msg)
                    return True
        return False

    def update_assistant_message(
        self,
        message_id: str,
        content: str,
        *,
        status: MessageStatus = MessageStatus.COMPLETED,
        error: str | None = None,
        metadata: dict | None = None,
    ) -> bool:
        """更新 assistant 消息的内容和状态。

        用于异步 Agent Run 完成后更新消息。
        """
        safe_content = _redact_chat_text(content)
        safe_error = _redact_optional_chat_text(error)
        safe_metadata = _redact_chat_metadata(metadata or {}) if metadata else None
        with self._lock:
            for msg in self.messages:
                if msg.message_id == message_id:
                    msg.content = safe_content
                    msg.status = status
                    msg.error = safe_error
                    if safe_metadata:
                        for key, value in safe_metadata.items():
                            if value is None:
                                msg.metadata.pop(key, None)
                            else:
                                msg.metadata[key] = value
                    self._pending_message_id = self._find_active_message_id_locked()
                    self._persist_message(msg)
                    return True
        return False
    
    def get_messages(self, limit: int = 50) -> List[ChatMessage]:
        """获取消息快照；limit <= 0 时返回全部消息。"""
        try:
            normalized_limit = int(limit)
        except (TypeError, ValueError):
            normalized_limit = 50
        with self._lock:
            if normalized_limit <= 0:
                return list(self.messages)
            return list(self.messages[-normalized_limit:])

    def get_all_messages(self) -> List[ChatMessage]:
        """获取当前会话全部消息的快照。"""
        with self._lock:
            return list(self.messages)

    def has_assistant_reply(self, task_id: str) -> bool:
        """是否已经存在某个任务对应的 assistant 回复。"""
        with self._lock:
            return any(
                m.role == MessageRole.ASSISTANT and m.task_id == task_id
                for m in self.messages
            )

    def get_assistant_message_for_task(self, task_id: str) -> Optional[ChatMessage]:
        """获取某个任务对应的 assistant 消息。"""
        with self._lock:
            for msg in self.messages:
                if msg.role == MessageRole.ASSISTANT and msg.task_id == task_id:
                    return msg
        return None

    def message_count(self) -> int:
        """当前会话消息数量。"""
        with self._lock:
            return len(self.messages)
    
    def get_last_assistant_message(self) -> Optional[ChatMessage]:
        """获取最新一条 assistant 消息"""
        with self._lock:
            for msg in reversed(self.messages):
                if msg.role == MessageRole.ASSISTANT:
                    return msg
        return None
    
    def is_processing(self) -> bool:
        """是否有消息正在处理中"""
        with self._lock:
            return self._find_active_message_id_locked() is not None
    
    def get_pending_message_id(self) -> Optional[str]:
        """获取当前等待回复的消息 ID"""
        with self._lock:
            self._pending_message_id = self._find_active_message_id_locked()
            return self._pending_message_id
    
    def clear(self) -> None:
        """清空会话"""
        with self._lock:
            self.messages.clear()
            self._pending_message_id = None
            self.execution_session_id = None
            self.session_id = uuid4().hex[:8]
            if self._store is not None:
                self._store.create_session(self.session_id)
        logger.info("会话已清空，新 session_id=%s", self.session_id)

    def set_execution_session_id(self, execution_id: str) -> None:
        """记录外部执行会话 ID；Native Run 使用 TaskRunLink 关联。"""
        with self._lock:
            self.execution_session_id = execution_id
            if self._store is not None:
                self._store.update_execution_session_id(self.session_id, execution_id)
        logger.info("Execution session ID 已设置: %s", execution_id)

    def set_session_title(self, title: str) -> None:
        """更新当前会话标题。"""
        title = _redact_chat_text(title).strip()
        if not title:
            return
        from apps.core.title_generator import looks_like_title_prompt_echo

        if looks_like_title_prompt_echo(title):
            logger.warning("忽略疑似标题生成提示词回显的会话标题: %s", title[:80])
            return
        with self._lock:
            if self._store is not None:
                self._store.update_session_title(self.session_id, title)
        logger.info("会话标题已更新: %s", title)
    
    def to_dict(self) -> dict:
        """序列化为字典（供 API 返回）"""
        with self._lock:
            return {
                "session_id": self.session_id,
                "message_count": len(self.messages),
                "is_processing": self._find_active_message_id_locked() is not None,
                "messages": [
                    {
                        "id": m.message_id,
                        "role": m.role.value,
                        "content": _redact_chat_text(m.content),
                        "status": m.status.value,
                        "task_id": m.task_id,
                        "error": _redact_optional_chat_text(m.error),
                        "created_at": m.created_at.isoformat(),
                        "attachments": _redact_chat_attachments(m.attachments),
                        "metadata": _redact_chat_metadata(m.metadata),
                    }
                    for m in self.messages
                ],
            }

    def _find_active_message_id_locked(self) -> Optional[str]:
        """查找仍在等待或执行中的用户消息。调用方需持有 _lock。"""
        for msg in self.messages:
            if (
                msg.role in (MessageRole.USER, MessageRole.ASSISTANT)
                and msg.status in (MessageStatus.PENDING, MessageStatus.PROCESSING)
            ):
                return msg.message_id
        return None


def load_existing_chat_session(
    store: "ChatStore",
    session_id: str,
    *,
    current: ChatSession | None = None,
    fail_active_messages: bool = False,
) -> ChatSession | None:
    """Load an explicit projection target without creating or falling back.

    Background completions must never turn a stale session identifier into a
    new conversation, and must never redirect that completion to whichever
    conversation happens to be current.
    """
    clean_session_id = str(session_id or "").strip()
    if not clean_session_id:
        return None
    try:
        if store.get_session(clean_session_id) is None:
            return None
        if current is not None and current.session_id == clean_session_id:
            return current
        session = ChatSession(session_id=clean_session_id)
        session.attach_store(
            store,
            load_existing=True,
            fail_active_messages=fail_active_messages,
            create_if_missing=False,
        )
        # A concurrent delete between the first lookup and load must still
        # suppress the late projection. Subsequent writes also remain guarded
        # by the store's foreign-key boundary because no session is recreated.
        if store.get_session(clean_session_id) is None:
            return None
        return session
    except Exception:
        logger.debug(
            "Unable to load existing ChatSession: %s",
            clean_session_id,
            exc_info=True,
        )
        return None


# 全局会话实例（单会话 MVP）
# 后续可扩展为多会话管理器
_global_session: Optional[ChatSession] = None
_global_session_lock = threading.RLock()


def get_chat_session() -> ChatSession:
    """获取全局聊天会话（单例），自动绑定持久化层"""
    global _global_session
    session = _global_session
    if session is not None:
        return session

    with _global_session_lock:
        if _global_session is not None:
            return _global_session

        from apps.core.chat_store import get_chat_store
        store = get_chat_store()
        sessions = store.list_sessions(limit=1)
        if sessions:
            session = ChatSession(session_id=sessions[0].session_id)
        else:
            session = ChatSession()
        session.attach_store(store, fail_active_messages=False)
        _global_session = session
        logger.info("初始化全局 ChatSession: %s", session.session_id)
        return session


def switch_chat_session(session_id: str) -> ChatSession:
    """切换到指定历史会话，返回新的 ChatSession 实例。

    会从数据库加载该会话的消息和 execution_session_id。
    若 session_id 不存在则创建空会话。
    """
    global _global_session
    from apps.core.chat_store import get_chat_store
    with _global_session_lock:
        session = ChatSession(session_id=session_id)
        session.attach_store(
            get_chat_store(),
            load_existing=True,
            fail_active_messages=False,
        )
        _global_session = session
    logger.info("切换到会话: %s (messages=%d)", session_id, session.message_count())
    return session


def _chat_message_from_stored(stored, *, fail_active_message: bool = True) -> ChatMessage:
    role = MessageRole(stored.role)
    status = MessageStatus(stored.status)
    error = stored.error
    if fail_active_message and status in (MessageStatus.PENDING, MessageStatus.PROCESSING):
        status = MessageStatus.FAILED
        error = error or "应用已重启，原任务状态不可恢复"
    return ChatMessage(
        message_id=stored.message_id,
        role=role,
        content=_redact_chat_text(stored.content),
        status=status,
        created_at=datetime.fromisoformat(stored.created_at),
        task_id=stored.task_id,
        error=_redact_optional_chat_text(error),
        attachments=_redact_chat_attachments(_parse_attachments_json(stored.attachments_json)),
        metadata=_redact_chat_metadata(_parse_metadata_json(getattr(stored, "metadata_json", "{}"))),
    )


def _parse_attachments_json(value: str | None) -> list[dict]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _parse_metadata_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _redact_chat_text(value: object) -> str:
    return redact_sensitive_text(
        value,
        limit=_CHAT_TEXT_REDACTION_LIMIT,
        collapse_whitespace=False,
        trim=False,
    )


def _redact_optional_chat_text(value: object | None) -> str | None:
    if value is None:
        return None
    return _redact_chat_text(value)


def _redact_chat_attachments(value: list[dict] | object) -> list[dict]:
    sanitized = sanitize_sensitive_value(
        list(value or []) if isinstance(value, list) else [],
        text_limit=_CHAT_TEXT_REDACTION_LIMIT,
        max_items=_CHAT_JSON_MAX_ITEMS,
        collapse_whitespace=False,
        trim=False,
    )
    if not isinstance(sanitized, list):
        return []
    return [item for item in sanitized if isinstance(item, dict)]


def _redact_chat_metadata(value: dict | object) -> dict:
    sanitized = sanitize_sensitive_value(
        dict(value or {}) if isinstance(value, dict) else {},
        text_limit=_CHAT_TEXT_REDACTION_LIMIT,
        max_items=_CHAT_JSON_MAX_ITEMS,
        collapse_whitespace=False,
        trim=False,
    )
    return sanitized if isinstance(sanitized, dict) else {}


def reset_chat_session() -> ChatSession:
    """重置全局会话（测试/清空用）"""
    global _global_session
    from apps.core.chat_store import get_chat_store
    with _global_session_lock:
        session = ChatSession()
        session.attach_store(get_chat_store(), load_existing=False)
        _global_session = session
    logger.info("重置全局 ChatSession: %s", session.session_id)
    return session
