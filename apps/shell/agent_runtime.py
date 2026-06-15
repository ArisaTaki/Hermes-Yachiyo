"""Agent Studio, Skill Library, and Workflow runtime services."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
from collections.abc import Iterable as IterableABC
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import uuid4

from apps.core.tls import urlopen_with_bundled_ca
from apps.installer.workspace_init import get_workspace_status
from apps.shell.agent.repositories.agents import AgentDefinitionRepository
from apps.shell.agent.repositories.approvals import ApprovalRepository
from apps.shell.agent.repositories.artifacts import RunArtifactRepository
from apps.shell.agent.repositories.events import RunEventRepository
from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.repositories.groups import RunGroupRepository
from apps.shell.agent.repositories.memories import AgentMemoryStore
from apps.shell.agent.repositories.runs import RunRepository
from apps.shell.agent.repositories.skill_folders import SkillFolderRepository
from apps.shell.agent.repositories.skills import SkillRepository
from apps.shell.agent.repositories.studio_deletions import StudioDeletionRepository
from apps.shell.agent.repositories.task_run_links import TaskRunLinkRepository
from apps.shell.agent.repositories.workspaces import TrustedWorkspaceRepository
from apps.shell.agent.repositories.workflows import WorkflowRepository
from apps.shell.agent.runtime.budget import (
    RunBudget as _RunBudget,
)
from apps.shell.agent.runtime.budget import (
    RunBudgetLimits as _RunBudgetLimits,
)
from apps.shell.agent.runtime.budget import (
    WorkflowRunBudget as _WorkflowRunBudget,
)
from apps.shell.agent.runtime.approval_lifecycle import (
    ApprovalCoordinator,
    ApprovalPauseProjectionCoordinator,
)
from apps.shell.agent.runtime.approval_resume import ApprovalResumeCoordinator
from apps.shell.agent.runtime.approval_snapshots import (
    ApprovalSnapshotBuilder,
    public_pending_approval as _runtime_public_pending_approval,
)
from apps.shell.agent.runtime.agent_context import (
    AgentContextBuilder,
    agent_goal_disallows_tool as _runtime_agent_goal_disallows_tool,
    agent_output_contract_rules as _runtime_agent_output_contract_rules,
    user_goal_from_agent_messages as _runtime_user_goal_from_agent_messages,
)
from apps.shell.agent.runtime.cancellation import (
    RunCancellationProjection,
    WorkflowCancellationProjectionCoordinator,
    WorkflowCancellationTarget,
)
from apps.shell.agent.runtime.errors import AgentApprovalRequired, AgentRuntimeError
from apps.shell.agent.runtime.events import (
    RuntimeAgentRunEventRecorder,
    RuntimeRunEventRecorder,
    RuntimeTaskEventRecorder,
    RuntimeTaskModelEventBuilder,
    RuntimeToolCallEventRecorder,
    RuntimeTraceEventBuilder,
    ToolEventPayloadBuilder,
    artifact_created_payload as _runtime_artifact_created_payload,
    canonical_run_event_aliases as _runtime_canonical_run_event_aliases,
    canonical_tool_event_payload as _runtime_canonical_tool_event_payload,
    canonical_tool_input_preview as _runtime_canonical_tool_input_preview,
    memory_retrieved_payload as _runtime_memory_retrieved_payload,
    memory_skill_trace_event as _runtime_memory_skill_trace_event,
    memory_trace_result as _runtime_memory_trace_result,
    model_output_completed_payload as _runtime_model_output_completed_payload,
    redact_json_value as _redact_json_value,
    runtime_trace_input_preview as _runtime_event_trace_input_preview,
    skill_trace_result as _runtime_skill_trace_result,
    task_run_event_payload as _runtime_task_run_event_payload,
    tool_trace_status as _runtime_tool_trace_status,
)
from apps.shell.agent.runtime.future_task_scheduler import FutureTaskTriggerScheduler
from apps.shell.agent.runtime.model_profiles import RuntimeModelProfileResolver
from apps.shell.agent.runtime.run_projections import (
    ApprovalResumeProjectionCoordinator,
    RunProjectionCoordinator,
)
from apps.shell.agent.runtime.skill_content import SkillContentInspector
from apps.shell.agent.runtime.skill_import import SkillImportPreparer, SkillImportSourceResolver
from apps.shell.agent.runtime.skill_install import SkillInstallCommandValidator
from apps.shell.agent.runtime.skill_sources import SkillSourceDiscovery
from apps.shell.agent.runtime.skill_sync import SkillSyncPlanner
from apps.shell.agent.runtime.tool_requests import ToolRequestParser
from apps.shell.agent.runtime.tool_approvals import (
    ToolApprovalClaimProjection,
    ToolApprovalContinuationHandoff,
    ToolApprovalContinuationOutcome,
    ToolApprovalCustomApiContinuationRequest,
    ToolApprovalExecutionFailureProjection,
    ToolApprovalExecutionFollowup,
    ToolApprovalExecutionRequest,
    ToolPendingApprovalBuilder,
    ToolApprovalResumeContext,
    ToolApprovalTransitionContext,
)
from apps.shell.agent.runtime.timeline import RuntimeAgentTimelineBuilder

from apps.shell.agent.runtime.workflow_continuation import WorkflowContinuationCoordinator
from apps.shell.agent.runtime.workflow_approvals import (
    WorkflowApprovalPauseProjection,
    WorkflowApprovalResumeContext,
    WorkflowApprovalResumeCoordinator,
    WorkflowApprovalTransitionContext,
)
from apps.shell.agent.runtime.workflow_outcomes import (
    WorkflowChildOutcomeCoordinator,
    WorkflowChildRunProjection,
    WorkflowChildStatusProjection,
    WorkflowParentResumeFailureProjection,
)
from apps.shell.agent.runtime.workflow_path import WorkflowPathPlanner
from apps.shell.agent.runtime.workflow_nodes import (
    WorkflowAgentNodeExecution,
    WorkflowAgentNodeHandoff,
    WorkflowArtifactNodeWrite,
    WorkflowSubworkflowNodeExecution,
)
from apps.shell.agent.runtime.workflow_parent_resume import WorkflowParentResumeCoordinator
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowConditionNodeProjection,
    WorkflowContinuationFailureProjection,
    WorkflowLoopNodeProjection,
    WorkflowParallelNodeProjection,
    WorkflowRunCompletionProjection,
    WorkflowStartNodeProjection,
)
from apps.shell.agent.runtime.workflow_resume import (
    RunTransitionProjectionCoordinator,
    WorkflowParentRunLocator,
    WorkflowResumePlanner,
)
from apps.shell.agent.runtime.workflow_start import WorkflowRunStartProjector
from apps.shell.agent.tools.broker import (
    _TERMINAL_PROCESS_LOCK,
    _TERMINAL_PROCESSES,
    ToolBroker,
    cancel_terminal_process_groups,
)
from apps.shell.agent.tools.policy import (
    FUTURE_TASK_TOOL_NAMES as _FUTURE_TASK_TOOL_NAMES,
    HIGH_RISK_AGENT_TOOLS as _HIGH_RISK_AGENT_TOOLS,
    KNOWN_AGENT_TOOLS as _KNOWN_AGENT_TOOLS,
    MEMORY_KINDS as _MEMORY_KINDS,
    MEMORY_TOOL_NAMES as _MEMORY_TOOL_NAMES,
    MEMORY_SCOPES as _MEMORY_SCOPES,
    RuntimePolicyCompiler,
    TOOL_DESCRIPTORS,
    PolicyGate,
    ToolDescriptor,
    ToolDescriptorRegistry,
    TOOL_FUNCTION_NAMES as _TOOL_FUNCTION_NAMES,
    TOOL_NAME_ALIASES as _TOOL_NAME_ALIASES,
)
from apps.shell.credential_store import (
    CredentialStore,
    CredentialStoreError,
    create_credential_store,
)
from apps.shell.model_profiles import (
    get_model_profile_service,
    openai_compatible_chat_message,
    read_openai_compatible_chat_timeout,
    supports_openai_compatible_api,
)
from packages.security import (
    contains_sensitive_text,
    redact_api_error_text,
    redact_sensitive_text,
    scrubbed_subprocess_env,
)

logger = logging.getLogger(__name__)


_EXECUTION_BACKENDS = {"native_profile", "yachiyo_profile", "external_cli"}
_MEMORY_CONTEXT_LIMIT = 12
_MEMORY_CONTENT_MAX_CHARS = 4000
_MAX_AGENT_TOOL_ITERATIONS = 50
_FINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
_WORKFLOW_NODE_TYPES = {"start", "agent", "approval", "artifact", "condition", "parallel", "workflow", "loop"}
_NATIVE_LIBRARY_SOURCE_TYPES = {"native_global", "native_project"}
_SKILL_SOURCE_TYPES = {*_NATIVE_LIBRARY_SOURCE_TYPES, "npx_skills", "local_zip", "local_dir"}
_UNSET = object()
_MAIN_CHAT_AGENT_ID = "builtin:yachiyo-main"
_SYSTEM_AGENT_IDS = {_MAIN_CHAT_AGENT_ID}
_DEFAULT_AGENT_IDS = {
    _MAIN_CHAT_AGENT_ID,
    "agent_yachiyo_orchestrator",
    "agent_coding",
    "agent_design",
    "agent_review",
    "agent_research",
    "agent_office",
    "agent_custom",
}
_MARKET_AGENT_OPERATING_DOCTRINE = (
    "Market-grade Agent operating doctrine:\n"
    "- Act as a persistent personal agent, not a one-shot chatbot: preserve user intent, "
    "handoff context, and reusable outputs when the task has follow-up value.\n"
    "- Prefer the smallest reliable action loop: reason from available context, inspect before "
    "acting, use tools only when they materially improve the answer, and do not fabricate tool results.\n"
    "- Treat Skills as task manuals and tools as external actions; use mounted Skills when relevant, "
    "but keep direct answers lightweight when no Skill is needed.\n"
    "- For multi-step work, expose progress through concise summaries, artifacts, or workflow handoffs "
    "instead of hiding important intermediate decisions.\n"
    "- Respect safety boundaries: approval gates, workspace scopes, credential redaction, and user "
    "instructions outrank autonomy."
)


def _is_active_run_status(status: str) -> bool:
    return (status.strip() or "running") not in _FINAL_RUN_STATUSES


def _agent_output_contract_rules(contract: Any) -> str:
    return _runtime_agent_output_contract_rules(contract)


def _user_goal_from_agent_messages(messages: list[dict[str, Any]]) -> str:
    return _runtime_user_goal_from_agent_messages(messages)


def _agent_goal_disallows_tool(user_goal: str, tool_name: str) -> str:
    return _runtime_agent_goal_disallows_tool(user_goal, tool_name)


def _named_row_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        column[0]: row[index]
        for index, column in enumerate(cursor.description or ())
        if index < len(row)
    }


class _LockedCursor:
    def __init__(self, cursor: sqlite3.Cursor, lock: threading.RLock) -> None:
        self._cursor = cursor
        self._lock = lock

    @property
    def description(self) -> Any:
        return self._cursor.description

    def fetchone(self) -> Any:
        with self._lock:
            return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        with self._lock:
            return self._cursor.fetchall()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class _LockedConnection:
    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        self._conn = conn
        self._lock = lock

    @property
    def row_factory(self) -> Any:
        with self._lock:
            return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        with self._lock:
            self._conn.row_factory = value

    def execute(self, *args: Any, **kwargs: Any) -> _LockedCursor:
        with self._lock:
            return _LockedCursor(self._conn.execute(*args, **kwargs), self._lock)

    def executescript(self, *args: Any, **kwargs: Any) -> _LockedCursor:
        with self._lock:
            return _LockedCursor(self._conn.executescript(*args, **kwargs), self._lock)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oha_yachiyo_home() -> Path:
    root = Path(os.getenv("OHA_YACHIYO_HOME", os.path.expanduser("~/.oha-yachiyo"))).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _native_skill_home() -> Path:
    return _oha_yachiyo_home() / "skill-library"


def _slug(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return normalized[:48] or fallback


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _normalize_execution_backend(value: Any, *, model_mode: str = "") -> str:
    """Normalize all Studio execution backends to the native runtime."""
    backend = str(value or "").strip()
    if backend and backend not in _EXECUTION_BACKENDS:
        raise AgentRuntimeError("execution_backend 不再支持 legacy 或未知执行后端；请使用 native_profile")
    return "native_profile"


def _normalize_skill_source_type(value: Any) -> str:
    source_type = str(value or "").strip()
    return source_type


def _is_native_library_source_type(value: Any) -> bool:
    return _normalize_skill_source_type(value) in _NATIVE_LIBRARY_SOURCE_TYPES


def redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


def _iso_epoch(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return time.time()
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return time.time()


def _json_chars(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return len(str(value))


def _truncate_text(value: Any, max_chars: int) -> tuple[str, bool]:
    text = str(value or "")
    limit = max(1, int(max_chars or 1))
    if len(text) <= limit:
        return text, False
    marker = "\n\n[truncated]"
    if limit <= len(marker):
        return text[:limit], True
    return text[: limit - len(marker)] + marker, True


def _limit_json_strings(value: Any, max_chars: int) -> tuple[Any, bool]:
    if isinstance(value, dict):
        changed = False
        limited: dict[str, Any] = {}
        for key, item in value.items():
            next_item, item_changed = _limit_json_strings(item, max_chars)
            limited[str(key)] = next_item
            changed = changed or item_changed
        return limited, changed
    if isinstance(value, list):
        changed = False
        limited_items = []
        for item in value:
            next_item, item_changed = _limit_json_strings(item, max_chars)
            limited_items.append(next_item)
            changed = changed or item_changed
        return limited_items, changed
    if isinstance(value, tuple):
        return _limit_json_strings(list(value), max_chars)
    if isinstance(value, str):
        return _truncate_text(value, max_chars)
    return value, False


def _safe_rel_path(value: str) -> str:
    candidate = str(value or "").replace("\\", "/").strip()
    if not candidate or candidate.startswith("/") or candidate.startswith("../") or "/../" in candidate:
        raise AgentRuntimeError("路径必须是相对路径，且不能越界")
    return candidate


def _is_within(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        base = root.resolve()
    except OSError:
        return False
    return resolved == base or base in resolved.parents


def _read_text(path: Path, limit: int = 200_000) -> str:
    return SkillContentInspector.read_text(path, limit)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _atomic_write_text(target: Path, content: str) -> None:
    tmp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


_UNIFIED_HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


def _normalize_unified_diff_path(value: str) -> str:
    path = str(value or "").strip()
    if "\t" in path:
        path = path.split("\t", 1)[0].strip()
    elif " " in path:
        path = path.split(" ", 1)[0].strip()
    if path in {"", "/dev/null"}:
        raise AgentRuntimeError("workspace.write_patch 不支持删除或创建型 /dev/null patch")
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return _safe_rel_path(path)


def _apply_single_file_unified_diff(original: str, patch: str, *, expected_path: str) -> str:
    if not patch.strip():
        raise AgentRuntimeError("workspace.write_patch patch 不能为空")
    if any(marker in patch for marker in ("GIT binary patch", "Binary files ")):
        raise AgentRuntimeError("workspace.write_patch 不支持二进制 patch")
    if re.search(r"(?m)^(rename from|rename to|deleted file mode|new file mode)\b", patch):
        raise AgentRuntimeError("workspace.write_patch 不支持重命名、删除或新文件 patch")

    lines = patch.splitlines(keepends=True)
    old_headers = [line for line in lines if line.startswith("--- ")]
    new_headers = [line for line in lines if line.startswith("+++ ")]
    if len(old_headers) != 1 or len(new_headers) != 1:
        raise AgentRuntimeError("workspace.write_patch 只支持单文件 unified diff")
    old_path = _normalize_unified_diff_path(old_headers[0][4:].rstrip("\r\n"))
    new_path = _normalize_unified_diff_path(new_headers[0][4:].rstrip("\r\n"))
    clean_expected_path = _safe_rel_path(expected_path)
    if old_path != clean_expected_path or new_path != clean_expected_path:
        raise AgentRuntimeError("workspace.write_patch patch 路径必须与目标 path 一致")

    original_lines = original.splitlines(keepends=True)
    output: list[str] = []
    old_pos = 0
    index = 0
    hunk_count = 0
    while index < len(lines):
        line = lines[index]
        match = _UNIFIED_HUNK_RE.match(line)
        if match is None:
            index += 1
            continue

        hunk_count += 1
        old_start = int(match.group("old_start"))
        old_count = int(match.group("old_count") or "1")
        new_count = int(match.group("new_count") or "1")
        hunk_old_pos = max(0, old_start - 1)
        if hunk_old_pos < old_pos:
            raise AgentRuntimeError("workspace.write_patch hunk 顺序无效")
        output.extend(original_lines[old_pos:hunk_old_pos])
        old_pos = hunk_old_pos
        consumed_old = 0
        produced_new = 0
        index += 1
        while index < len(lines) and not _UNIFIED_HUNK_RE.match(lines[index]):
            hunk_line = lines[index]
            if hunk_line.startswith(("--- ", "+++ ")):
                raise AgentRuntimeError("workspace.write_patch 不支持多文件 patch")
            if hunk_line.startswith("\\"):
                index += 1
                continue
            if not hunk_line:
                raise AgentRuntimeError("workspace.write_patch hunk 格式无效")
            marker = hunk_line[0]
            text = hunk_line[1:]
            if marker in {" ", "-"}:
                if old_pos >= len(original_lines) or original_lines[old_pos] != text:
                    raise AgentRuntimeError("workspace.write_patch hunk context 与当前文件不匹配")
                consumed_old += 1
                old_pos += 1
                if marker == " ":
                    output.append(text)
                    produced_new += 1
            elif marker == "+":
                output.append(text)
                produced_new += 1
            else:
                raise AgentRuntimeError("workspace.write_patch hunk 行格式无效")
            index += 1
        if consumed_old != old_count or produced_new != new_count:
            raise AgentRuntimeError("workspace.write_patch hunk 行数与 header 不一致")

    if hunk_count == 0:
        raise AgentRuntimeError("workspace.write_patch 缺少 unified diff hunk")
    output.extend(original_lines[old_pos:])
    return "".join(output)


def _skill_content_hash(root: Path) -> str:
    return SkillContentInspector.content_hash(root)


def _parse_skill_frontmatter(markdown: str) -> dict[str, Any]:
    return SkillContentInspector.parse_frontmatter(markdown)


def _normalize_tool_name(value: Any) -> str:
    name = str(value or "").strip()
    return _TOOL_NAME_ALIASES.get(name, name)


def _message_field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    if isinstance(value, (str, bytes, bytearray)):
        return None
    return getattr(value, name, None)


_MODEL_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
)


class _ModelOutputText(str):
    def __new__(
        cls,
        value: str,
        *,
        metadata: dict[str, Any] | None = None,
        truncated: bool = False,
    ) -> "_ModelOutputText":
        obj = str.__new__(cls, value)
        obj.model_metadata = metadata or {}
        obj.output_truncated = truncated
        return obj


def _coerce_model_usage(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    usage: dict[str, Any] = {}
    for key in _MODEL_USAGE_KEYS:
        raw = _message_field(value, key)
        if raw is None:
            continue
        try:
            usage[key] = int(raw)
        except (TypeError, ValueError):
            usage[key] = raw
    return usage or None


def _stream_chunk_usage(chunk: Any) -> dict[str, Any] | None:
    usage = _coerce_model_usage(_message_field(chunk, "usage"))
    if usage is not None:
        return usage
    response = _message_field(chunk, "response")
    if response is not None:
        return _coerce_model_usage(_message_field(response, "usage"))
    return None


def _stream_chunk_finish_reason(chunk: Any) -> str | None:
    direct = _first_present(_message_field(chunk, "finish_reason"), _message_field(chunk, "stop_reason"))
    if direct:
        return str(direct)
    choices = _message_field(chunk, "choices")
    if isinstance(choices, list):
        for choice in choices:
            reason = _first_present(_message_field(choice, "finish_reason"), _message_field(choice, "stop_reason"))
            if reason:
                return str(reason)
    response = _message_field(chunk, "response")
    response_reason = (
        _first_present(_message_field(response, "finish_reason"), _message_field(response, "stop_reason"))
        if response is not None
        else None
    )
    if response_reason:
        return str(response_reason)
    output = _message_field(response, "output") if response is not None else None
    if isinstance(output, list):
        for item in output:
            reason = _first_present(_message_field(item, "finish_reason"), _message_field(item, "stop_reason"))
            if reason:
                return str(reason)
    return None


def _model_message_metadata(message: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    finish_reason = _first_present(_message_field(message, "finish_reason"), _message_field(message, "stop_reason"))
    if finish_reason:
        metadata["finish_reason"] = str(finish_reason)
    usage = _coerce_model_usage(_message_field(message, "usage"))
    if usage is not None:
        metadata["usage"] = usage
    return metadata


def _model_output_metadata(value: Any) -> dict[str, Any]:
    metadata = getattr(value, "model_metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def _model_output_completed_payload(
    content: str,
    *,
    truncated: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _runtime_model_output_completed_payload(
        content,
        truncated=truncated,
        metadata=metadata,
    )


def _message_content_part_type(value: Any) -> str:
    return str(_message_field(value, "type") or "").strip().lower()


def _responses_stream_event_type(value: Any) -> str:
    return str(_message_field(value, "type") or _message_field(value, "event") or "").strip().lower()


_RESPONSES_STREAM_REASONING_EVENTS = {
    "response.reasoning.delta",
    "response.reasoning.done",
    "response.reasoning_text.delta",
    "response.reasoning_text.done",
    "response.reasoning_summary_text.delta",
    "response.reasoning_summary_text.done",
    "reasoning.delta",
    "reasoning.done",
    "reasoning_text.delta",
    "reasoning_text.done",
    "reasoning_summary_text.delta",
    "reasoning_summary_text.done",
}


def _responses_stream_is_reasoning_event(value: Any) -> bool:
    return _responses_stream_event_type(value) in _RESPONSES_STREAM_REASONING_EVENTS


def _responses_stream_text_delta(chunk: Any) -> str | None:
    event_type = _responses_stream_event_type(chunk)
    if event_type in {"response.output_text.delta", "output_text.delta"}:
        return _message_text_value(_message_field(chunk, "delta"))
    if event_type in {"response.refusal.delta", "refusal.delta"}:
        return _message_text_value(_message_field(chunk, "delta"))
    if event_type in {
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.added",
        "response.output_item.done",
        "function_call_arguments.delta",
        "function_call_arguments.done",
        "output_item.added",
        "output_item.done",
    }:
        return ""
    return None


def _responses_stream_text_done(chunk: Any) -> str | None:
    event_type = _responses_stream_event_type(chunk)
    if event_type in {
        "response.content_part.added",
        "response.content_part.done",
        "content_part.added",
        "content_part.done",
    }:
        part = _message_field(chunk, "part")
        return _message_visible_content_text(part)
    if event_type in {"response.output_item.added", "response.output_item.done", "output_item.added", "output_item.done"}:
        item = _message_field(chunk, "item")
        item_type = _message_content_part_type(item)
        if item_type == "message":
            return _message_visible_content_text(item)
        return None
    if event_type not in {"response.output_text.done", "output_text.done", "response.refusal.done", "refusal.done"}:
        return None
    for field_name in ("text", "refusal", "content", "delta"):
        value = _message_field(chunk, field_name)
        if value is not None:
            return _message_text_value(value)
    return ""


def _stream_index_value(value: Any, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _responses_stream_text_key(chunk: Any) -> tuple[int, int]:
    return (
        _stream_index_value(_message_field(chunk, "output_index"), 0),
        _stream_index_value(_message_field(chunk, "content_index"), 0),
    )


def _responses_stream_tool_call(chunk: Any) -> dict[str, Any] | None:
    event_type = _responses_stream_event_type(chunk)
    item = _message_field(chunk, "item")
    snapshot = event_type in {"response.output_item.done", "output_item.done"}
    if event_type in {"response.output_item.added", "response.output_item.done", "output_item.added", "output_item.done"}:
        item_type = _message_content_part_type(item)
        if item_type not in {"function_call", "tool_call"}:
            return None
        arguments = _message_field(item, "arguments")
        item_id = _message_field(item, "id")
        call_id = _message_field(item, "call_id")
        return {
            "index": _stream_index_value(_first_present(_message_field(chunk, "output_index"), _message_field(item, "index")), 0),
            "id": str(item_id or call_id or ""),
            "item_id": str(item_id or "") if item_id else "",
            "call_id": str(call_id or "") if call_id else "",
            "type": "function",
            "function": {
                "name": str(_message_field(item, "name") or ""),
                "arguments": arguments if arguments is not None else "",
            },
            "_snapshot": snapshot,
        }
    if event_type in {
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "function_call_arguments.delta",
        "function_call_arguments.done",
    }:
        arguments = _message_field(chunk, "arguments")
        if arguments is None:
            arguments = _message_field(chunk, "delta")
        item_id = _message_field(chunk, "item_id")
        call_id = _message_field(chunk, "call_id")
        return {
            "index": _stream_index_value(_first_present(_message_field(chunk, "output_index"), _message_field(chunk, "index")), 0),
            "id": str(item_id or call_id or ""),
            "item_id": str(item_id or "") if item_id else "",
            "call_id": str(call_id or "") if call_id else "",
            "type": "function",
            "function": {
                "name": str(_message_field(chunk, "name") or ""),
                "arguments": arguments if arguments is not None else "",
            },
            "_snapshot": event_type.endswith(".done"),
        }
    return None


def _is_reasoning_content_part(value: Any) -> bool:
    return _message_content_part_type(value) in {"reasoning", "reasoning_content", "thinking", "thought"}


def _message_text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(text for item in value if (text := _message_text_value(item)))
    if isinstance(value, dict):
        for key in ("value", "content", "text"):
            nested = value.get(key)
            if nested is not None:
                text = _message_text_value(nested)
                if text:
                    return text
        return ""
    nested = _message_field(value, "value")
    if nested is not None:
        text = _message_text_value(nested)
        if text:
            return text
    nested = _message_field(value, "content")
    if nested is not None:
        text = _message_text_value(nested)
        if text:
            return text
    nested = _message_field(value, "text")
    if nested is not None:
        text = _message_text_value(nested)
        if text:
            return text
    return str(value) if value is not None and not isinstance(value, set) else ""


def _tool_arguments_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _message_content_text(content: Any) -> str:
    if isinstance(content, dict):
        if _is_reasoning_content_part(content):
            return ""
        nested = _message_content_text(content.get("content"))
        if nested:
            return nested
        reasoning = content.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning
        text = content.get("text")
        return _message_text_value(text)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if _is_reasoning_content_part(item):
                continue
            text = _message_content_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    nested = _message_field(content, "content")
    if nested is not None:
        text = _message_content_text(nested)
        if text:
            return text
    reasoning = _message_field(content, "reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    text = _message_field(content, "text")
    if text is not None:
        return _message_text_value(text)
    return ""


def _message_visible_content_text(content: Any) -> str:
    if isinstance(content, dict):
        if _is_reasoning_content_part(content):
            return ""
        nested = _message_visible_content_text(content.get("content"))
        if nested:
            return nested
        text = content.get("text")
        if text is not None:
            return _message_text_value(text)
        return _message_text_value(content.get("refusal"))
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if _is_reasoning_content_part(item):
                continue
            text = _message_visible_content_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    nested = _message_field(content, "content")
    if nested is not None:
        text = _message_visible_content_text(nested)
        if text:
            return text
    text = _message_field(content, "text")
    if text is not None:
        return _message_text_value(text)
    refusal = _message_field(content, "refusal")
    if refusal is not None:
        return _message_text_value(refusal)
    return ""


def _stream_chunk_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
    if _responses_stream_is_reasoning_event(chunk):
        return ""
    responses_text = _responses_stream_text_delta(chunk)
    if responses_text is not None:
        return responses_text
    choices = _message_field(chunk, "choices")
    if isinstance(choices, list):
        parts: list[str] = []
        for choice in choices:
            delta = _message_field(choice, "delta")
            if delta is not None:
                parts.append(_message_visible_content_text(delta))
            message = _message_field(choice, "message")
            if message is not None:
                parts.append(_message_visible_content_text(message))
            text = _message_field(choice, "text")
            if text is not None:
                parts.append(str(text))
        if parts:
            return "".join(parts)
    delta = _message_field(chunk, "delta")
    if delta is not None:
        return _message_visible_content_text(delta)
    return _message_visible_content_text(chunk)


def _stream_choice_index(choice: Any, fallback: int) -> int:
    try:
        value = _message_field(choice, "index")
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _stream_chunk_tool_calls(chunk: Any) -> list[tuple[int, int, Any]]:
    responses_call = _responses_stream_tool_call(chunk)
    if responses_call is not None:
        return [(0, _stream_choice_index(responses_call, 0), responses_call)]
    direct = _message_field(chunk, "tool_calls")
    if isinstance(direct, list):
        return [(0, index, call) for index, call in enumerate(direct)]
    direct_single = _message_field(chunk, "tool_call")
    if direct_single is not None:
        return [(0, 0, direct_single)]
    direct_function = _message_field(chunk, "function_call")
    if direct_function is not None:
        return [(0, 0, {"index": 0, "type": "function", "function": direct_function})]
    for field_name in ("delta", "message"):
        value = _message_field(chunk, field_name)
        if value is None:
            continue
        calls = _message_field(value, "tool_calls")
        if isinstance(calls, list):
            return [(0, index, call) for index, call in enumerate(calls)]
        single_call = _message_field(value, "tool_call")
        if single_call is not None:
            return [(0, 0, single_call)]
        function_call = _message_field(value, "function_call")
        if function_call is not None:
            return [(0, 0, {"index": 0, "type": "function", "function": function_call})]
    choices = _message_field(chunk, "choices")
    if not isinstance(choices, list):
        return []
    calls: list[tuple[int, int, Any]] = []
    for choice_position, choice in enumerate(choices):
        choice_index = _stream_choice_index(choice, choice_position)
        delta = _message_field(choice, "delta")
        if delta is not None:
            delta_calls = _message_field(delta, "tool_calls")
            if isinstance(delta_calls, list):
                calls.extend((choice_index, index, call) for index, call in enumerate(delta_calls))
            delta_single_call = _message_field(delta, "tool_call")
            if delta_single_call is not None:
                calls.append((choice_index, 0, delta_single_call))
            delta_function = _message_field(delta, "function_call")
            if delta_function is not None:
                calls.append((choice_index, 0, {"index": 0, "type": "function", "function": delta_function}))
        message = _message_field(choice, "message")
        if message is not None:
            message_calls = _message_field(message, "tool_calls")
            if isinstance(message_calls, list):
                calls.extend((choice_index, index, call) for index, call in enumerate(message_calls))
            message_single_call = _message_field(message, "tool_call")
            if message_single_call is not None:
                calls.append((choice_index, 0, message_single_call))
            message_function = _message_field(message, "function_call")
            if message_function is not None:
                calls.append((choice_index, 0, {"index": 0, "type": "function", "function": message_function}))
    return calls


def _merge_stream_tool_call_delta(
    accumulator: dict[tuple[int, int], dict[str, Any]],
    raw_call: Any,
    choice_index: int,
    fallback_index: int,
) -> None:
    if raw_call is None:
        return
    raw_index = _message_field(raw_call, "index")
    try:
        index = int(raw_index) if raw_index is not None else fallback_index
    except (TypeError, ValueError):
        index = fallback_index
    call_id = _message_field(raw_call, "id")
    item_id = _message_field(raw_call, "item_id")
    response_call_id = _message_field(raw_call, "call_id")
    match_ids = {str(value) for value in (call_id, item_id, response_call_id) if value}
    key = (choice_index, index)
    if match_ids:
        for existing_key, existing in accumulator.items():
            existing_ids = {
                str(value)
                for value in (existing.get("id"), existing.get("item_id"), existing.get("call_id"))
                if value
            }
            if existing_key[0] == choice_index and match_ids.intersection(existing_ids):
                key = existing_key
                break
        else:
            existing = accumulator.get(key)
            has_distinct_id = False
            if raw_index is None and existing:
                existing_ids = {
                    str(value)
                    for value in (existing.get("id"), existing.get("item_id"), existing.get("call_id"))
                    if value
                }
                has_distinct_id = bool(existing_ids and not match_ids.intersection(existing_ids))
            if raw_index is None and existing and has_distinct_id:
                occupied = {tool_index for existing_choice, tool_index in accumulator if existing_choice == choice_index}
                while index in occupied:
                    index += 1
                key = (choice_index, index)
    entry = accumulator.setdefault(key, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    if item_id:
        entry["item_id"] = str(item_id)
    if response_call_id:
        entry["call_id"] = str(response_call_id)
    preferred_id = response_call_id or call_id or item_id
    if preferred_id:
        entry["id"] = str(preferred_id)
    call_type = _message_field(raw_call, "type")
    if call_type:
        entry["type"] = str(call_type)
    raw_function = _message_field(raw_call, "function")
    if raw_function is None:
        return
    function = entry.setdefault("function", {"name": "", "arguments": ""})
    snapshot = bool(_message_field(raw_call, "_snapshot"))
    name = _message_field(raw_function, "name")
    if name:
        function["name"] = str(name) if snapshot else f"{function.get('name') or ''}{name}"
    arguments = _message_field(raw_function, "arguments")
    if arguments or snapshot:
        arguments_text = _tool_arguments_text(arguments)
        function["arguments"] = arguments_text if snapshot else f"{function.get('arguments') or ''}{arguments_text}"


def _coalesced_stream_tool_calls(accumulator: dict[tuple[int, int], dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for choice_index, tool_index in sorted(accumulator):
        call = accumulator[(choice_index, tool_index)]
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        calls.append(
            {
                "id": str(call.get("id") or f"call_{choice_index}_{tool_index}"),
                "type": str(call.get("type") or "function"),
                "function": {
                    "name": str(function.get("name") or ""),
                    "arguments": str(function.get("arguments") or ""),
                },
            }
        )
    return calls


def _coerce_tool_call(value: Any, index: int) -> dict[str, Any] | None:
    if value is None:
        return None
    raw_function = _message_field(value, "function")
    function_name = _message_field(raw_function, "name") if raw_function is not None else ""
    if not function_name:
        return None
    arguments = _message_field(raw_function, "arguments")
    return {
        "id": str(_message_field(value, "id") or f"call_{index}"),
        "type": str(_message_field(value, "type") or "function"),
        "function": {
            "name": str(function_name),
            "arguments": _tool_arguments_text(arguments) if arguments is not None else "{}",
        },
    }


def _coerce_tool_calls(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    calls: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        call = _coerce_tool_call(item, index)
        if call is not None:
            calls.append(call)
    return calls


def _coerce_function_call(value: Any, index: int = 0) -> dict[str, Any] | None:
    if value is None:
        return None
    name = _message_field(value, "name")
    if not name:
        return None
    arguments = _message_field(value, "arguments")
    return {
        "id": f"call_{index}",
        "type": "function",
        "function": {
            "name": str(name),
            "arguments": _tool_arguments_text(arguments) if arguments is not None else "{}",
        },
    }


def _coalesce_model_message(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        tool_calls = _coerce_tool_calls(message.get("tool_calls"))
        if tool_calls is not None:
            return {**message, "tool_calls": tool_calls}
        tool_call = _coerce_tool_call(message.get("tool_call"), 0)
        if tool_call is not None:
            return {**message, "tool_calls": [tool_call]}
        function_call = _coerce_function_call(message.get("function_call"))
        return {**message, "tool_calls": [function_call]} if function_call is not None else message
    if isinstance(message, str):
        return {"role": "assistant", "content": message}
    if not isinstance(message, IterableABC):
        result = {"role": "assistant", "content": _message_visible_content_text(message)}
        tool_calls = _coerce_tool_calls(_message_field(message, "tool_calls"))
        if tool_calls is not None:
            result["tool_calls"] = tool_calls
        else:
            tool_call = _coerce_tool_call(_message_field(message, "tool_call"), 0)
            if tool_call is not None:
                result["tool_calls"] = [tool_call]
            else:
                function_call = _coerce_function_call(_message_field(message, "function_call"))
                if function_call is not None:
                    result["tool_calls"] = [function_call]
        return result

    content_parts: list[str] = []
    responses_text_order: list[tuple[int, int]] = []
    responses_text_deltas: dict[tuple[int, int], list[str]] = {}
    responses_text_done: dict[tuple[int, int], str] = {}
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_deltas: dict[tuple[int, int], dict[str, Any]] = {}
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    for chunk in message:
        if _responses_stream_is_reasoning_event(chunk):
            continue
        chunk_finish_reason = _stream_chunk_finish_reason(chunk)
        if chunk_finish_reason:
            finish_reason = chunk_finish_reason
        chunk_usage = _stream_chunk_usage(chunk)
        if chunk_usage is not None:
            usage = chunk_usage
        responses_delta = _responses_stream_text_delta(chunk)
        responses_done = _responses_stream_text_done(chunk)
        if responses_delta is not None or responses_done is not None:
            key = _responses_stream_text_key(chunk)
            if key not in responses_text_order:
                responses_text_order.append(key)
            if responses_delta:
                responses_text_deltas.setdefault(key, []).append(responses_delta)
            if responses_done is not None:
                responses_text_done[key] = responses_done
        else:
            content = _stream_chunk_text(chunk)
            if content:
                content_parts.append(content)
        chunk_tool_calls = _stream_chunk_tool_calls(chunk)
        if isinstance(chunk_tool_calls, list):
            for choice_index, fallback_index, call in chunk_tool_calls:
                _merge_stream_tool_call_delta(tool_call_deltas, call, choice_index, fallback_index)

    for key in responses_text_order:
        content_parts.append(responses_text_done.get(key) or "".join(responses_text_deltas.get(key, [])))

    result: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
    if tool_call_deltas:
        tool_calls = _coalesced_stream_tool_calls(tool_call_deltas)
    if tool_calls is not None:
        result["tool_calls"] = tool_calls
    if finish_reason:
        result["finish_reason"] = finish_reason
    if usage is not None:
        result["usage"] = usage
    return result


def _call_model_profile_chat_message(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    stream: bool = False,
) -> Any:
    kwargs: dict[str, Any] = {}
    if tools is not None:
        kwargs["tools"] = tools
    if stream and _callable_accepts_keyword(openai_compatible_chat_message, "stream"):
        kwargs["stream"] = True
    return openai_compatible_chat_message(base_url, model, api_key, messages, **kwargs)


def _callable_accepts_keyword(func: Any, name: str) -> bool:
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())


def _tool_input_preview(value: Any, *, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(key): _tool_input_preview(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_tool_input_preview(item, limit=limit) for item in value[:20]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = redact_secrets(value)
    if len(text) > limit:
        return f"{text[:limit]}... [truncated]"
    return text


def _canonical_tool_event_payload(
    tool_name: str,
    input_preview: Any,
    *,
    approved: bool = False,
    pre_validation: bool = False,
    result: dict[str, Any] | None = None,
    error: Any = None,
    status: str = "",
) -> dict[str, Any]:
    return _runtime_canonical_tool_event_payload(
        tool_name,
        input_preview,
        approved=approved,
        pre_validation=pre_validation,
        result=result,
        error=error,
        status=status,
    )


def _canonical_tool_input_preview(
    tool_name: str,
    input_preview: Any,
    *,
    pre_validation: bool = False,
) -> Any:
    return _runtime_canonical_tool_input_preview(
        tool_name,
        input_preview,
        pre_validation=pre_validation,
    )


def _artifact_created_payload(
    tool_result: dict[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    return _runtime_artifact_created_payload(tool_result, run_id=run_id)


def _task_run_event_payload(
    *,
    task_id: str = "",
    run_id: str = "",
    session_id: str = "",
    status: str = "",
    result: Any = None,
    error: Any = None,
) -> dict[str, Any]:
    return _runtime_task_run_event_payload(
        task_id=task_id,
        run_id=run_id,
        session_id=session_id,
        status=status,
        result=result,
        error=error,
    )


def _canonical_run_event_aliases(event_type: str, payload: dict[str, Any] | None = None) -> list[str]:
    return _runtime_canonical_run_event_aliases(event_type, payload)


def _memory_skill_trace_event(
    tool_name: str,
    input_preview: Any,
    tool_result: dict[str, Any],
) -> dict[str, Any] | None:
    return _runtime_memory_skill_trace_event(tool_name, input_preview, tool_result)


def _runtime_trace_input_preview(tool_name: str, input_preview: Any) -> Any:
    return _runtime_event_trace_input_preview(tool_name, input_preview)


def _tool_trace_status(tool_result: dict[str, Any]) -> str:
    return _runtime_tool_trace_status(tool_result)


def _skill_trace_result(tool_result: dict[str, Any]) -> dict[str, Any]:
    return _runtime_skill_trace_result(tool_result)


def _memory_trace_result(tool_result: dict[str, Any]) -> dict[str, Any]:
    return _runtime_memory_trace_result(tool_result)


def _memory_retrieved_payload(memories: list[dict[str, Any]]) -> dict[str, Any]:
    return _runtime_memory_retrieved_payload(memories)


def _normalize_tool_iteration(value: Any) -> int:
    try:
        iteration = int(value or 0)
    except (TypeError, ValueError):
        iteration = 0
    return max(0, min(iteration, _MAX_AGENT_TOOL_ITERATIONS))


def _public_pending_approval(value: Any) -> dict[str, Any]:
    return _runtime_public_pending_approval(value)


class NativeRunEngine:
    """Persistent native agent execution engine shared by product entry points.

    AgentRuntimeService is kept as a compatibility name below because mature
    routes, tests, and UI-facing APIs still use the service label.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        workspace_dir: Path | str | None = None,
        *,
        credential_store: CredentialStore | None = None,
        seed_templates: bool = True,
    ) -> None:
        root = Path(workspace_dir) if workspace_dir is not None else _oha_yachiyo_home()
        root.mkdir(parents=True, exist_ok=True)
        self.workspace_dir = root
        self.db_path = Path(db_path) if db_path is not None else root / "agent-runtime.db"
        self._credential_store = credential_store or create_credential_store(root)
        self.skills_dir = root / "skills"
        self.skill_installs_dir = root / "skill-installs"
        self.skill_installs_native_home = self.skill_installs_dir / "native-home"
        self.agent_artifacts_dir = root / "artifacts" / "agent-runs"
        self.workflow_artifacts_dir = root / "artifacts" / "workflow-runs"
        self.agent_workspaces_dir = root / "workspaces" / "agents"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.skill_installs_dir.mkdir(parents=True, exist_ok=True)
        self.skill_installs_native_home.mkdir(parents=True, exist_ok=True)
        self.agent_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.workflow_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.agent_workspaces_dir.mkdir(parents=True, exist_ok=True)
        self._accepting_runs = True
        self._closed = False
        self.runtime_limits = _RunBudgetLimits()
        self._db_lock = threading.RLock()
        self._approval_execution_lock = threading.RLock()
        self._approval_execution_in_progress: set[str] = set()
        self._run_cancel_locks: dict[str, threading.RLock] = {}
        self._run_cancel_locks_guard = threading.RLock()
        self.tool_request_parser = ToolRequestParser()
        self.runtime_agent_run_events = RuntimeAgentRunEventRecorder(
            append_run_event=self.append_run_event,
        )
        self.tool_event_payloads = ToolEventPayloadBuilder()
        self.runtime_tool_call_events = RuntimeToolCallEventRecorder(
            append_run_event=self.append_run_event,
            payload_builder=self.tool_event_payloads,
        )
        self.runtime_task_model_events = RuntimeTaskModelEventBuilder()
        self.runtime_task_events = RuntimeTaskEventRecorder(
            append_run_event=self.append_run_event,
            payload_builder=self.runtime_task_model_events,
        )
        self.runtime_trace_events = RuntimeTraceEventBuilder()
        self.tool_pending_approvals = ToolPendingApprovalBuilder(
            approval_id_factory=lambda: f"approval_{uuid4().hex[:12]}",
            now=_now,
        )
        raw_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        raw_conn.execute("PRAGMA foreign_keys=ON")
        raw_conn.execute("PRAGMA journal_mode=WAL")
        raw_conn.execute("PRAGMA busy_timeout=5000")
        self._conn = _LockedConnection(raw_conn, self._db_lock)
        self._conn.row_factory = _named_row_factory
        self.task_run_links = TaskRunLinkRepository(
            self._conn,
            ensure_row_factory=self._ensure_row_factory,
            get_run=lambda run_id: self.get_run(run_id),
            now=_now,
            error_type=AgentRuntimeError,
        )
        self.trusted_workspaces = TrustedWorkspaceRepository(
            self._conn,
            now=_now,
            error_type=AgentRuntimeError,
        )
        self.studio_deletions = StudioDeletionRepository(
            self._conn,
            now=_now,
        )
        self.skill_folders = SkillFolderRepository(
            self._conn,
            ensure_row_factory=self._ensure_row_factory,
            row_to_skill_folder=self._row_to_skill_folder,
            now=_now,
            slug=_slug,
            id_suffix_factory=lambda: uuid4().hex[:6],
            delete_skill=lambda skill_id: self.delete_skill(skill_id),
            error_type=AgentRuntimeError,
        )
        self.skill_records = SkillRepository(
            self._conn,
            ensure_row_factory=self._ensure_row_factory,
            row_to_skill=self._row_to_skill,
            now=_now,
            json_dump=_json_dump,
            json_load=_json_load,
            normalize_skill_folder_id=self._normalize_skill_folder_id,
            installed_skill_source_map=self._installed_skill_source_map,
            record_studio_deletion=self._record_studio_deletion,
            skill_deletion_key=self._skill_deletion_key,
            is_native_library_source_type=_is_native_library_source_type,
            skills_dir=self.skills_dir,
            skill_installs_dir=self.skill_installs_dir,
            skill_id_factory=lambda name: f"skill_{_slug(name, 'skill')}_{uuid4().hex[:8]}",
            asset_paths_for=SkillContentInspector.asset_paths,
        )
        self.agent_definitions = AgentDefinitionRepository(
            self._conn,
            ensure_row_factory=self._ensure_row_factory,
            row_to_agent=self._row_to_agent,
            row_to_agent_private=self._row_to_agent_private,
            coerce_named_row=self._coerce_named_row,
            main_chat_virtual_agent=self._main_chat_virtual_agent,
            now=_now,
            json_dump=_json_dump,
            agent_id_factory=lambda name: f"agent_{_slug(name, 'agent')}_{uuid4().hex[:8]}",
            normalize_execution_backend=_normalize_execution_backend,
            ensure_global_name_available=self._ensure_global_name_available,
            validate_agent_profile_refs=self._validate_agent_profile_refs,
            compile_tool_policy=self._compile_tool_policy,
            compile_workspace_policy=self._compile_workspace_policy,
            assign_default_agent_workdir=self._assign_default_agent_workdir,
            trust_workspace_from_policy=self._trust_workspace_from_policy,
            agent_model_credential_ref=self._agent_model_credential_ref,
            store_credential=self._store_credential,
            delete_credential=self._delete_credential,
            record_studio_deletion=self._record_studio_deletion,
            clear_studio_deletion=self._clear_studio_deletion,
            system_agent_ids=_SYSTEM_AGENT_IDS,
            main_chat_agent_id=_MAIN_CHAT_AGENT_ID,
            error_type=AgentRuntimeError,
        )
        self.skill_install_validator = SkillInstallCommandValidator(
            error_type=AgentRuntimeError,
        )
        self.skill_sources = SkillSourceDiscovery(
            native_skill_home=_native_skill_home,
            skill_installs_dir=self.skill_installs_dir,
            skill_installs_native_home=self.skill_installs_native_home,
            json_load=_json_load,
            normalize_source_type=_normalize_skill_source_type,
            native_library_source_types=_NATIVE_LIBRARY_SOURCE_TYPES,
        )
        self.skill_content = SkillContentInspector()
        self.skill_import_sources = SkillImportSourceResolver(
            workspace_dir=self.workspace_dir,
            id_factory=lambda: uuid4().hex,
            error_type=AgentRuntimeError,
        )
        self.skill_import_preparer = SkillImportPreparer(
            content=self.skill_content,
            skill_source_types=_SKILL_SOURCE_TYPES,
            now=_now,
            error_type=AgentRuntimeError,
        )
        self.skill_sync = SkillSyncPlanner(
            skill_source_types=_SKILL_SOURCE_TYPES,
            count_skill_files=SkillSourceDiscovery.count_skill_files,
        )
        self.approval_snapshots = ApprovalSnapshotBuilder()
        self.run_groups = RunGroupRepository(
            self._conn,
            ensure_row_factory=self._ensure_row_factory,
            row_to_run_group=self._row_to_run_group,
            row_to_run=self._row_to_run,
            now=_now,
            json_dump=_json_dump,
            redact_secrets=redact_secrets,
        )
        self.run_approvals = ApprovalRepository(
            self._conn,
            self._db_lock,
            now=_now,
            json_dump=_json_dump,
            public_pending_approval=self.approval_snapshots.public_pending_approval,
        )
        self.run_artifacts = RunArtifactRepository(
            self._conn,
            agent_artifacts_dir=self.agent_artifacts_dir,
            workflow_artifacts_dir=self.workflow_artifacts_dir,
            get_run=self.get_run,
            now=_now,
            json_dump=_json_dump,
            redact_json_value=_redact_json_value,
            redact_secrets=redact_secrets,
            safe_rel_path=_safe_rel_path,
            is_within=_is_within,
            read_text=_read_text,
        )
        self.run_projections = RunProjectionCoordinator(
            run_artifacts=self.run_artifacts,
            run_approvals=self.run_approvals,
            task_run_links=self.task_run_links,
        )
        self.runs = RunRepository(
            self._conn,
            ensure_row_factory=self._ensure_row_factory,
            row_to_run=self._row_to_run,
            accepting_runs=lambda: self._accepting_runs,
            sync_projections=self.run_projections.sync,
            append_run_to_group=self._append_run_to_group,
            now=_now,
            json_dump=_json_dump,
            json_load=_json_load,
            redact_secrets=redact_secrets,
            redact_json_value=_redact_json_value,
            contains_sensitive_text=contains_sensitive_text,
            error_type=AgentRuntimeError,
            unset_sentinel=_UNSET,
        )
        self.run_events = RunEventRepository(
            self._conn,
            self._db_lock,
            now=_now,
            json_dump=_json_dump,
            json_load=_json_load,
            error_type=AgentRuntimeError,
            ensure_run_exists=self.get_run,
            sync_event_cursor=self.run_projections.sync_event_cursor,
        )
        self.runtime_events = RuntimeRunEventRecorder(self.run_events)
        self.runtime_agent_timeline = RuntimeAgentTimelineBuilder(
            timeline_factory=self._timeline,
        )
        self.runtime_policy = RuntimePolicyCompiler()
        self.model_profile_resolver = RuntimeModelProfileResolver(
            profile_service_factory=lambda: get_model_profile_service(),
            supports_openai_compatible_api=supports_openai_compatible_api,
            default_agent_ids=_DEFAULT_AGENT_IDS,
            error_type=AgentRuntimeError,
        )
        self.agent_context_builder = AgentContextBuilder(
            compile_agent_runtime=self._compile_agent_runtime,
            load_agent_skills=self._load_agent_skills,
            long_term_memory_context=self._long_term_memory_context,
            operating_doctrine=_MARKET_AGENT_OPERATING_DOCTRINE,
        )
        self.workflows = WorkflowRepository(
            self._conn,
            ensure_row_factory=self._ensure_row_factory,
            row_to_workflow=self._row_to_workflow,
            now=_now,
            json_dump=_json_dump,
            workflow_id_factory=lambda name: f"workflow_{_slug(name, 'workflow')}_{uuid4().hex[:8]}",
            ensure_global_name_available=self._ensure_global_name_available,
            validate_workflow=self.validate_workflow,
            validate_workflow_agent_nodes=self._validate_workflow_agent_nodes,
            validate_workflow_subworkflow_nodes=self._validate_workflow_subworkflow_nodes,
            record_studio_deletion=self._record_studio_deletion,
            clear_studio_deletion=self._clear_studio_deletion,
        )
        self.approval_pause = ApprovalPauseProjectionCoordinator(
            timeline_factory=self._timeline,
            append_run_event=self.append_run_event,
            update_run=self._update_run,
            snapshots=self.approval_snapshots,
        )
        self.approvals = ApprovalCoordinator(
            timeline_factory=self._timeline,
            append_run_event=self.append_run_event,
            update_run=self._update_run,
        )
        self.approval_resume = ApprovalResumeCoordinator(
            call_agent_tool=self._call_agent_tool,
            fatal_tool_failure_detail=self._fatal_tool_failure_detail,
            append_tool_result_message=self._append_tool_result_message,
            run_tool_requests=self._run_tool_requests,
            timeline_factory=self._timeline,
            claim_pending_approval=self.run_approvals.claim_pending_approval,
            approve_tool_run=self.approvals.approve_tool_run,
            continue_custom_api_agent=self._run_custom_api_agent,
        )
        self.workflow_continuation = WorkflowContinuationCoordinator(
            self,
            iso_epoch=lambda value: _iso_epoch(value),
        )
        self.workflow_approval_resume = WorkflowApprovalResumeCoordinator(
            claim_pending_approval=self.run_approvals.claim_pending_approval,
            get_current_run=self.get_run,
            resume_after_approval_node=self.workflow_continuation.resume_after_approval_node,
        )
        self.workflow_cancellation = WorkflowCancellationProjectionCoordinator(
            pending_approval_private=lambda run_id: self.runs.pending_approval_private(run_id),
            get_run=lambda run_id: self.get_run(run_id),
            merge_workflow_child_run_outcome=lambda timeline, artifacts, child_run, label: (
                self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, label)
            ),
            timeline_factory=lambda event, detail="", **extra: self._timeline(event, detail, **extra),
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
        )
        self.workflow_child_outcomes = WorkflowChildOutcomeCoordinator()
        self.workflow_parent_locator = WorkflowParentRunLocator(
            get_run_group=self.get_run_group,
            get_run=self.get_run,
        )
        self.workflow_path_planner = WorkflowPathPlanner(node_kind=self._node_kind)
        self.workflow_run_start_projector = WorkflowRunStartProjector(
            timeline_factory=self._timeline,
            path_snapshot=self._workflow_path_snapshot,
            runtime_snapshot=self._workflow_runtime_snapshot,
        )
        self.workflow_resume_planner = WorkflowResumePlanner(
            get_workflow=self.get_workflow,
            workflow_path=self._workflow_path,
            node_kind=self._node_kind,
        )
        self.future_task_scheduler = FutureTaskTriggerScheduler(
            self._conn,
            self._db_lock,
            create_run_for_runnable=lambda **kwargs: self.create_run_for_runnable(**kwargs),
            future_task_store=lambda **kwargs: self._future_task_store(**kwargs),
            now=_now,
            redact_secrets=redact_secrets,
            error_type=AgentRuntimeError,
        )
        self.workflow_parent_resume = WorkflowParentResumeCoordinator(
            parent_runs_waiting_for_child=lambda child_run: self._workflow_parent_runs_waiting_for_child(child_run),
            workflow_run_is_group_root=lambda workflow_run: self._workflow_run_is_group_root(workflow_run),
            workflow_child_node_context=lambda timeline, child_run: self._workflow_child_node_context(timeline, child_run),
            merge_workflow_child_run_outcome=lambda timeline, artifacts, child_run, label: (
                self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, label)
            ),
            workflow_for_run_resume=lambda workflow_run: self._workflow_for_run_resume(workflow_run),
            workflow_resume_start_index=lambda workflow, workflow_run, child_run_id: (
                self._workflow_resume_start_index(workflow, workflow_run, child_run_id)
            ),
            workflow_next_node_id=lambda workflow, node_id, context: (
                self._workflow_next_node_id(workflow, node_id, context)
            ),
            continue_workflow_run=lambda run, workflow, **kwargs: self.workflow_continuation.continue_run(run, workflow, **kwargs),
            timeline_factory=lambda event, detail="", **extra: self._timeline(event, detail, **extra),
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            update_run_group=lambda run_group_id, **kwargs: self._update_run_group(run_group_id, **kwargs),
        )
        self.approval_resume_projection = ApprovalResumeProjectionCoordinator(
            timeline_factory=lambda event, detail="", **extra: self._timeline(event, detail, **extra),
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            update_agent_run_group_if_root=lambda run: self._update_agent_run_group_if_root(run),
            mark_parent_workflows_child_running=lambda run: self._mark_parent_workflows_child_running(run),
        )
        self.run_transition_projection = RunTransitionProjectionCoordinator(
            update_agent_run_group_if_root=lambda run: self._update_agent_run_group_if_root(run),
            resume_parent_workflows_after_child_update=lambda run: self._resume_parent_workflows_after_child_update(run),
            workflow_run_is_group_root=lambda run: self._workflow_run_is_group_root(run),
            update_run_group=lambda run_group_id, **kwargs: self._update_run_group(run_group_id, **kwargs),
            get_run=lambda run_id: self.get_run(run_id),
        )
        self._init_db()
        self._migrate_agent_workspace_policies()
        if seed_templates:
            self._seed_templates()

    def close(self) -> None:
        self.shutdown()

    def shutdown(self, *, close_db: bool = True) -> None:
        if self._closed:
            return
        self._accepting_runs = False
        cancel_terminal_process_groups()
        try:
            self._ensure_row_factory()
            rows = self._conn.execute(
                """
                SELECT run_id
                  FROM runs
                 WHERE status NOT IN ('completed', 'failed', 'cancelled')
                 ORDER BY updated_at DESC
                """
            ).fetchall()
            for row in rows:
                try:
                    self.cancel_run(str(row["run_id"]))
                except Exception:
                    continue
            self._conn.commit()
        finally:
            if close_db:
                self._conn.close()
                self._credential_store.close()
                self._closed = True

    def _ensure_row_factory(self) -> None:
        if self._conn.row_factory is not _named_row_factory:
            self._conn.row_factory = _named_row_factory

    def _coerce_named_row(self, row: Any, description: Any = None) -> Any:
        if row is None or isinstance(row, dict):
            return row
        if isinstance(row, sqlite3.Row):
            if description:
                return {
                    column[0]: row[index]
                    for index, column in enumerate(description)
                    if index < len(row)
                }
            return {key: row[key] for key in row.keys()}
        if description:
            return {
                column[0]: row[index]
                for index, column in enumerate(description)
                if index < len(row)
            }
        return row

    def _init_db(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                nickname TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                avatar_url TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'custom',
                instructions TEXT NOT NULL DEFAULT '',
                persona_prompt TEXT NOT NULL DEFAULT '',
                model_mode TEXT NOT NULL DEFAULT 'profile',
                execution_backend TEXT NOT NULL DEFAULT 'native_profile',
                model_profile_id TEXT NOT NULL DEFAULT '',
                vision_model_profile_id TEXT NOT NULL DEFAULT '',
                model_provider TEXT NOT NULL DEFAULT 'openai_compatible',
                model_base_url TEXT NOT NULL DEFAULT '',
                model_name TEXT NOT NULL DEFAULT '',
                model_api_key TEXT NOT NULL DEFAULT '',
                model_credential_ref TEXT NOT NULL DEFAULT '',
                tool_policy_json TEXT NOT NULL DEFAULT '{}',
                workspace_policy_json TEXT NOT NULL DEFAULT '{}',
                skill_ids_json TEXT NOT NULL DEFAULT '[]',
                output_contract TEXT NOT NULL DEFAULT 'chat',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS skills (
                skill_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL DEFAULT '',
                local_path TEXT NOT NULL DEFAULT '',
                folder_id TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'local_dir',
                origin_path TEXT NOT NULL DEFAULT '',
                source_ref TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                last_synced_at TEXT NOT NULL DEFAULT '',
                sync_status TEXT NOT NULL DEFAULT 'imported',
                content_summary TEXT NOT NULL DEFAULT '',
                skill_markdown TEXT NOT NULL,
                asset_paths_json TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS skill_folders (
                folder_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source_scope TEXT NOT NULL DEFAULT 'all',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                nodes_json TEXT NOT NULL DEFAULT '[]',
                edges_json TEXT NOT NULL DEFAULT '[]',
                default_input_schema_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS studio_deletions (
                item_type TEXT NOT NULL,
                item_key TEXT NOT NULL,
                deleted_at TEXT NOT NULL,
                PRIMARY KEY (item_type, item_key)
            );
            CREATE TABLE IF NOT EXISTS run_groups (
                run_group_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                workspace_dir TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'running',
                summary TEXT NOT NULL DEFAULT '',
                child_run_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                run_group_id TEXT NOT NULL DEFAULT '',
                client_request_id TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                runnable_id TEXT NOT NULL,
                status TEXT NOT NULL,
                user_goal TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                timeline_json TEXT NOT NULL DEFAULT '[]',
                artifacts_json TEXT NOT NULL DEFAULT '[]',
                pending_approval_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS task_run_links (
                task_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                session_id TEXT NOT NULL DEFAULT '',
                run_status TEXT NOT NULL DEFAULT '',
                last_event_sequence INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS run_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'native_runtime',
                visibility TEXT NOT NULL DEFAULT 'user',
                sensitivity TEXT NOT NULL DEFAULT 'public',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
                UNIQUE (run_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS run_approvals (
                approval_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                tool TEXT NOT NULL DEFAULT '',
                input_preview_json TEXT NOT NULL DEFAULT '{}',
                payload_json TEXT NOT NULL DEFAULT '{}',
                requested_at TEXT NOT NULL,
                resolved_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS run_artifacts (
                artifact_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT '',
                path TEXT NOT NULL DEFAULT '',
                source_run_id TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
                UNIQUE (run_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS trusted_workspaces (
                path TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT '',
                trusted_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_items (
                memory_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL DEFAULT 'global',
                kind TEXT NOT NULL DEFAULT 'fact',
                content TEXT NOT NULL,
                project_id TEXT NOT NULL DEFAULT '',
                source_session_id TEXT NOT NULL DEFAULT '',
                source_message_id TEXT NOT NULL DEFAULT '',
                source_task_id TEXT NOT NULL DEFAULT '',
                source_run_id TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 1.0,
                pinned INTEGER NOT NULL DEFAULT 0,
                user_confirmed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS memory_projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_project_sessions (
                session_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES memory_projects(project_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS memory_events (
                event_id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'agent_tool',
                payload_json TEXT NOT NULL DEFAULT '{}',
                source_run_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS future_tasks (
                future_task_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                prompt TEXT NOT NULL,
                runnable_id TEXT NOT NULL DEFAULT '',
                runnable_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'scheduled',
                scheduled_at_epoch REAL NOT NULL,
                cron TEXT NOT NULL DEFAULT '',
                source_run_id TEXT NOT NULL DEFAULT '',
                last_run_id TEXT NOT NULL DEFAULT '',
                run_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                cancelled_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS future_task_events (
                event_id TEXT PRIMARY KEY,
                future_task_id TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'agent_runtime',
                payload_json TEXT NOT NULL DEFAULT '{}',
                source_run_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        scrubbed_secrets = self._ensure_runtime_columns()
        self._conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_agents_name ON agents (LOWER(name));
            CREATE INDEX IF NOT EXISTS idx_workflows_name ON workflows (LOWER(name));
            CREATE INDEX IF NOT EXISTS idx_skills_folder ON skills (folder_id);
            CREATE INDEX IF NOT EXISTS idx_skills_origin ON skills (origin_path);
            CREATE INDEX IF NOT EXISTS idx_skills_content_hash ON skills (content_hash);
            CREATE INDEX IF NOT EXISTS idx_skill_folders_sort ON skill_folders (sort_order, LOWER(name));
            CREATE INDEX IF NOT EXISTS idx_run_groups_status_updated ON run_groups (status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_runs_group_updated ON runs (run_group_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_runs_kind_updated ON runs (kind, updated_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_client_request ON runs (client_request_id) WHERE client_request_id != '';
            CREATE INDEX IF NOT EXISTS idx_task_run_links_session ON task_run_links (session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_run_events_run_sequence ON run_events (run_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_run_approvals_run_status ON run_approvals (run_id, status);
            CREATE INDEX IF NOT EXISTS idx_run_artifacts_run_sequence ON run_artifacts (run_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_trusted_workspaces_updated ON trusted_workspaces (updated_at);
            CREATE INDEX IF NOT EXISTS idx_memory_items_scope_kind_updated ON memory_items (scope, kind, deleted_at, updated_at);
            CREATE INDEX IF NOT EXISTS idx_memory_items_source_run ON memory_items (source_run_id);
            CREATE INDEX IF NOT EXISTS idx_memory_project_sessions_project ON memory_project_sessions (project_id);
            CREATE INDEX IF NOT EXISTS idx_memory_events_memory_created ON memory_events (memory_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_future_tasks_status_due ON future_tasks (status, scheduled_at_epoch);
            CREATE INDEX IF NOT EXISTS idx_future_tasks_runnable_updated ON future_tasks (runnable_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_future_task_events_task_created ON future_task_events (future_task_id, created_at);
            """
        )
        self._conn.execute(
            """
            INSERT INTO runtime_schema_metadata (key, value, updated_at)
            VALUES ('schema_version', '1', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (_now(),),
        )
        self._conn.commit()
        if scrubbed_secrets:
            self._vacuum_after_secret_scrub()

    def _ensure_runtime_columns(self) -> bool:
        columns = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(agents)").fetchall()}
        if "nickname" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN nickname TEXT NOT NULL DEFAULT ''")
        if "persona_prompt" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN persona_prompt TEXT NOT NULL DEFAULT ''")
        if "execution_backend" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN execution_backend TEXT NOT NULL DEFAULT 'native_profile'")
        if "model_profile_id" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN model_profile_id TEXT NOT NULL DEFAULT ''")
        if "vision_model_profile_id" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN vision_model_profile_id TEXT NOT NULL DEFAULT ''")
        if "model_credential_ref" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN model_credential_ref TEXT NOT NULL DEFAULT ''")
        skill_columns = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(skills)").fetchall()}
        if "local_path" not in skill_columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN local_path TEXT NOT NULL DEFAULT ''")
        if "folder_id" not in skill_columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN folder_id TEXT NOT NULL DEFAULT ''")
        if "enabled" not in skill_columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        if "source_type" not in skill_columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN source_type TEXT NOT NULL DEFAULT 'local_dir'")
        if "origin_path" not in skill_columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN origin_path TEXT NOT NULL DEFAULT ''")
        if "source_ref" not in skill_columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN source_ref TEXT NOT NULL DEFAULT ''")
        if "content_hash" not in skill_columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''")
        if "last_synced_at" not in skill_columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN last_synced_at TEXT NOT NULL DEFAULT ''")
        if "sync_status" not in skill_columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'imported'")
        run_columns = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "run_group_id" not in run_columns:
            self._conn.execute("ALTER TABLE runs ADD COLUMN run_group_id TEXT NOT NULL DEFAULT ''")
        if "client_request_id" not in run_columns:
            self._conn.execute("ALTER TABLE runs ADD COLUMN client_request_id TEXT NOT NULL DEFAULT ''")
        if "pending_approval_json" not in run_columns:
            self._conn.execute("ALTER TABLE runs ADD COLUMN pending_approval_json TEXT NOT NULL DEFAULT '{}'")
        task_run_link_columns = {
            str(row["name"]) for row in self._conn.execute("PRAGMA table_info(task_run_links)").fetchall()
        }
        if "run_status" not in task_run_link_columns:
            self._conn.execute("ALTER TABLE task_run_links ADD COLUMN run_status TEXT NOT NULL DEFAULT ''")
        if "last_event_sequence" not in task_run_link_columns:
            self._conn.execute(
                "ALTER TABLE task_run_links ADD COLUMN last_event_sequence INTEGER NOT NULL DEFAULT 0"
            )
        if "updated_at" not in task_run_link_columns:
            self._conn.execute("ALTER TABLE task_run_links ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
        self._conn.execute(
            """
            UPDATE task_run_links
               SET run_status=COALESCE((SELECT status FROM runs WHERE runs.run_id=task_run_links.run_id), '')
             WHERE run_status=''
            """
        )
        self._conn.execute(
            """
            UPDATE task_run_links
               SET last_event_sequence=COALESCE(
                    (SELECT MAX(sequence) FROM run_events WHERE run_events.run_id=task_run_links.run_id),
                    0
               )
             WHERE last_event_sequence=0
            """
        )
        self._conn.execute(
            """
            UPDATE task_run_links
               SET updated_at=created_at
             WHERE updated_at=''
            """
        )
        self._migrate_native_execution_and_skill_sources()
        scrubbed_run_groups = self._migrate_run_group_secret_projections()
        scrubbed_agent_credentials = self._migrate_agent_model_credentials()
        return scrubbed_run_groups or scrubbed_agent_credentials

    def _vacuum_after_secret_scrub(self) -> None:
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.execute("VACUUM")
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            logger.debug("NativeRunEngine secret scrub vacuum failed", exc_info=True)

    def _migrate_native_execution_and_skill_sources(self) -> None:
        self._conn.execute(
            """
            UPDATE agents
               SET execution_backend='native_profile'
             WHERE execution_backend IN ('yachiyo_profile', 'external_cli', '')
            """
        )
        self._conn.execute(
            """
            UPDATE skill_folders
               SET source_scope='installed'
             WHERE source_scope='yachiyo'
            """
        )
        self._conn.execute(
            """
            UPDATE studio_deletions
               SET item_key='installed:' || substr(item_key, 9)
             WHERE item_type='skill_source'
               AND item_key LIKE 'yachiyo:%'
            """
        )

    def _migrate_run_group_secret_projections(self) -> bool:
        scrubbed = False
        rows = self._conn.execute(
            "SELECT run_group_id, title, source, workspace_dir, summary FROM run_groups"
        ).fetchall()
        for row in rows:
            clean_title = redact_secrets(row["title"])[:180]
            clean_source = redact_secrets(row["source"])[:80]
            clean_workspace_dir = redact_secrets(row["workspace_dir"])
            clean_summary = redact_secrets(row["summary"])
            if (
                clean_title == row["title"]
                and clean_source == row["source"]
                and clean_workspace_dir == row["workspace_dir"]
                and clean_summary == row["summary"]
            ):
                continue
            self._conn.execute(
                """
                UPDATE run_groups
                   SET title=?, source=?, workspace_dir=?, summary=?, updated_at=?
                 WHERE run_group_id=?
                """,
                (
                    clean_title,
                    clean_source,
                    clean_workspace_dir,
                    clean_summary,
                    _now(),
                    str(row["run_group_id"]),
                ),
            )
            scrubbed = True
        return scrubbed

    def _agent_model_credential_ref(self, agent_id: str) -> str:
        return f"agent:{agent_id}:model_api_key"

    def _store_credential(self, ref: str, secret: str) -> None:
        secret = str(secret or "").strip()
        if not secret:
            return
        try:
            self._credential_store.set(ref, secret)
        except CredentialStoreError as exc:
            raise AgentRuntimeError(redact_api_error_text(exc)) from exc

    def _read_credential(self, ref: str) -> str:
        ref = str(ref or "").strip()
        if not ref:
            return ""
        try:
            return self._credential_store.get(ref)
        except CredentialStoreError as exc:
            raise AgentRuntimeError(redact_api_error_text(exc)) from exc

    def _delete_credential(self, ref: str) -> None:
        ref = str(ref or "").strip()
        if not ref:
            return
        try:
            self._credential_store.delete(ref)
        except CredentialStoreError:
            pass

    def _migrate_agent_model_credentials(self) -> bool:
        scrubbed = False
        rows = self._conn.execute(
            "SELECT agent_id, model_api_key, model_credential_ref FROM agents WHERE model_api_key<>''"
        ).fetchall()
        for row in rows:
            secret = str(row["model_api_key"] or "").strip()
            if not secret:
                continue
            credential_ref = str(row["model_credential_ref"] or "").strip() or self._agent_model_credential_ref(str(row["agent_id"]))
            try:
                self._credential_store.set(credential_ref, secret)
            except CredentialStoreError:
                continue
            self._conn.execute(
                "UPDATE agents SET model_credential_ref=?, model_api_key='' WHERE agent_id=?",
                (credential_ref, str(row["agent_id"])),
            )
            scrubbed = True
        return scrubbed

    def _record_studio_deletion(self, item_type: str, item_key: str) -> None:
        self.studio_deletions.record(item_type, item_key)

    def _clear_studio_deletion(self, item_type: str, item_key: str) -> None:
        self.studio_deletions.clear(item_type, item_key)

    def _has_studio_deletion(self, item_type: str, item_key: str) -> bool:
        return self.studio_deletions.has(item_type, item_key)

    @staticmethod
    def _skill_deletion_key(source_type: str, origin_path: str) -> str:
        clean_origin = str(origin_path or "").strip()
        if not clean_origin:
            return ""
        library = "native" if _is_native_library_source_type(source_type) else "installed"
        try:
            clean_origin = str(Path(clean_origin).expanduser().resolve())
        except OSError:
            pass
        return f"{library}:{clean_origin}"

    def _seed_templates(self) -> None:
        templates = [
            (
                "agent_yachiyo_orchestrator",
                "Yachiyo Orchestrator",
                "负责拆解目标、汇总上下文，并调度其他 Agent。",
                "orchestrator",
                "你是 Yachiyo 主控调度 Agent。你负责把用户目标整理成明确 brief，决定需要哪些 Agent 参与，并汇总最终结果。",
                "report",
            ),
            (
                "agent_coding",
                "Coding Agent",
                "负责实现代码改动、整理 diff 和验证建议。",
                "coding",
                "你是 Coding Agent。你负责根据 brief 输出最小可验证实现方案、变更摘要、测试建议和风险说明。",
                "diff",
            ),
            (
                "agent_design",
                "Design Agent",
                "负责信息架构、界面方案、原型说明和设计交付物。",
                "design",
                "你是 Design Agent。你负责把需求转成设计目标、界面结构、交互状态和可交付原型说明。",
                "artifacts",
            ),
            (
                "agent_review",
                "Review Agent",
                "负责检查实现质量、回归风险和测试缺口。",
                "review",
                "你是 Review Agent。你以代码审查视角输出问题优先级、证据、风险和必要的修复建议。",
                "report",
            ),
            (
                "agent_research",
                "Research Agent",
                "负责资料整理、事实核验和方案比较。",
                "research",
                "你是 Research Agent。你负责整理已知事实、指出不确定点，并输出可执行结论。",
                "markdown",
            ),
            (
                "agent_office",
                "Office Agent",
                "负责日报、表格、文档和工作材料整理。",
                "office",
                "你是 Office Agent。你负责把工作信息整理成清晰、可复用的文档、表格或汇报材料。",
                "report",
            ),
            (
                "agent_custom",
                "Custom Agent",
                "空白模板，用于从 GUI 配置专用 Agent。",
                "custom",
                "你是一个由用户配置的专用 Agent。严格遵循当前 Agent instructions 和挂载 Skills。",
                "chat",
            ),
        ]
        agent_rows = self._conn.execute("SELECT agent_id, name FROM agents").fetchall()
        existing_agent_ids = {str(row["agent_id"]) for row in agent_rows}
        existing_agent_names = {str(row["name"]).strip().lower() for row in agent_rows}
        for agent_id, name, description, category, instructions, output_contract in templates:
            if (
                agent_id in existing_agent_ids
                or name.strip().lower() in existing_agent_names
                or self._has_studio_deletion("agent", agent_id)
            ):
                continue
            self.create_agent(
                {
                    "agent_id": agent_id,
                    "name": name,
                    "description": description,
                    "category": category,
                    "instructions": instructions,
                    "model_mode": "follow_main",
                    "tool_policy": self._default_tool_policy(category),
                    "workspace_policy": self._default_workspace_policy(),
                    "output_contract": output_contract,
                    "enabled": True,
                },
                seed=True,
            )
        self._seed_workflow_templates()

    def _seed_workflow_templates(self) -> None:
        phase4_tasks = {
            "orchestrator": "拆解全局目标，明确后续 Agent 的交付边界、依赖关系、风险和验收口径。",
            "research": "基于全局目标整理事实、约束、参考信息和不确定点，为设计与实现提供依据。",
            "design": "基于研究结果提出信息架构、交互结构、视觉方向和需要交付的设计要点。",
            "coding": "根据上游设计与约束给出实现方案、必要代码或变更计划，并说明验证方式。",
            "review": "审查上游实现或方案，列出问题优先级、风险、缺失测试和可验收结论。",
            "office": "把整条流程的目标、关键决策、产物、风险和后续待办整理成最终汇报。",
        }
        workflow_templates = [
            {
                "workflow_id": "workflow_web_idea_full",
                "name": "网页点子全流程",
                "description": "从点子 brief 到设计、编码、审查和人工确认的线性模板。",
                "nodes": [
                    {"id": "start", "type": "start", "position": {"x": 0, "y": 80}, "data": {"label": "Start"}},
                    {
                        "id": "design",
                        "type": "agent",
                        "position": {"x": 220, "y": 80},
                        "data": {
                            "label": "Design Agent",
                            "agent_id": "agent_design",
                            "task": "把网页点子转成可执行设计 brief，包含目标用户、页面结构、关键交互和视觉方向。",
                        },
                    },
                    {
                        "id": "approval",
                        "type": "approval",
                        "position": {"x": 440, "y": 80},
                        "data": {
                            "label": "人工审批",
                            "criteria": "确认设计 brief 已覆盖目标用户、页面结构、关键交互和验收点，再继续编码。",
                        },
                    },
                    {
                        "id": "coding",
                        "type": "agent",
                        "position": {"x": 660, "y": 80},
                        "data": {
                            "label": "Coding Agent",
                            "agent_id": "agent_coding",
                            "task": "根据已审批设计 brief 规划实现方案，产出代码、patch 或明确的实现步骤与验证方法。",
                        },
                    },
                    {
                        "id": "review",
                        "type": "agent",
                        "position": {"x": 880, "y": 80},
                        "data": {
                            "label": "Review Agent",
                            "agent_id": "agent_review",
                            "task": "审查实现结果，列出阻塞问题、风险、缺失测试和是否可以验收。",
                        },
                    },
                ],
                "edges": [
                    {"id": "e-start-design", "source": "start", "target": "design"},
                    {"id": "e-design-approval", "source": "design", "target": "approval"},
                    {"id": "e-approval-coding", "source": "approval", "target": "coding"},
                    {"id": "e-coding-review", "source": "coding", "target": "review"},
                ],
                "enabled": True,
            },
            {
                "workflow_id": "workflow_phase4_agent_line_smoke",
                "name": "Phase 4 Agent 全线流通测试",
                "description": "依次调用 Orchestrator、Research、Design、Coding、Review、Office，并写出最终 Artifact。",
                "nodes": [
                    {"id": "start", "type": "start", "position": {"x": 0, "y": 80}, "data": {"label": "Start"}},
                    {
                        "id": "orchestrator",
                        "type": "agent",
                        "position": {"x": 220, "y": 80},
                        "data": {
                            "label": "Yachiyo Orchestrator",
                            "agent_id": "agent_yachiyo_orchestrator",
                            "task": phase4_tasks["orchestrator"],
                        },
                    },
                    {
                        "id": "research",
                        "type": "agent",
                        "position": {"x": 440, "y": 80},
                        "data": {
                            "label": "Research Agent",
                            "agent_id": "agent_research",
                            "task": phase4_tasks["research"],
                        },
                    },
                    {
                        "id": "design",
                        "type": "agent",
                        "position": {"x": 660, "y": 80},
                        "data": {
                            "label": "Design Agent",
                            "agent_id": "agent_design",
                            "task": phase4_tasks["design"],
                        },
                    },
                    {
                        "id": "coding",
                        "type": "agent",
                        "position": {"x": 880, "y": 80},
                        "data": {
                            "label": "Coding Agent",
                            "agent_id": "agent_coding",
                            "task": phase4_tasks["coding"],
                        },
                    },
                    {
                        "id": "review",
                        "type": "agent",
                        "position": {"x": 1100, "y": 80},
                        "data": {
                            "label": "Review Agent",
                            "agent_id": "agent_review",
                            "task": phase4_tasks["review"],
                        },
                    },
                    {
                        "id": "office",
                        "type": "agent",
                        "position": {"x": 1320, "y": 80},
                        "data": {
                            "label": "Office Agent",
                            "agent_id": "agent_office",
                            "task": phase4_tasks["office"],
                        },
                    },
                    {
                        "id": "artifact",
                        "type": "artifact",
                        "position": {"x": 1540, "y": 80},
                        "data": {
                            "label": "Flow Summary",
                            "kind": "artifact",
                            "artifact_path": "reports/phase-4-flow-summary.md",
                        },
                    },
                ],
                "edges": [
                    {"id": "e-start-orchestrator", "source": "start", "target": "orchestrator"},
                    {"id": "e-orchestrator-research", "source": "orchestrator", "target": "research"},
                    {"id": "e-research-design", "source": "research", "target": "design"},
                    {"id": "e-design-coding", "source": "design", "target": "coding"},
                    {"id": "e-coding-review", "source": "coding", "target": "review"},
                    {"id": "e-review-office", "source": "review", "target": "office"},
                    {"id": "e-office-artifact", "source": "office", "target": "artifact"},
                ],
                "enabled": True,
            },
        ]
        agent_ids = {
            str(row["agent_id"])
            for row in self._conn.execute("SELECT agent_id FROM agents").fetchall()
        }
        existing_workflows = self._conn.execute("SELECT workflow_id, name FROM workflows").fetchall()
        existing_workflow_ids = {str(row["workflow_id"]) for row in existing_workflows}
        existing_workflow_names = {str(row["name"]).strip().lower() for row in existing_workflows}
        for workflow in workflow_templates:
            workflow_id = str(workflow["workflow_id"])
            name = str(workflow["name"])
            if (
                workflow_id in existing_workflow_ids
                or name.strip().lower() in existing_workflow_names
                or self._has_studio_deletion("workflow", workflow_id)
            ):
                continue
            referenced_agents = [
                str((node.get("data") or {}).get("agent_id") or "")
                for node in workflow["nodes"]
                if str(node.get("type") or (node.get("data") or {}).get("kind") or "") == "agent"
            ]
            if any(agent_id and agent_id not in agent_ids for agent_id in referenced_agents):
                continue
            self.create_workflow(workflow, seed=True)

    @staticmethod
    def _default_tool_policy(category: str = "custom") -> dict[str, Any]:
        return RuntimePolicyCompiler.default_tool_policy(category)

    @staticmethod
    def _default_workspace_policy() -> dict[str, Any]:
        return RuntimePolicyCompiler.default_workspace_policy()

    def _default_agent_workdir(self, agent_id: str) -> Path:
        raw_id = str(agent_id or "")
        clean_id = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_id).strip(".-")[:80]
        if not clean_id:
            clean_id = "agent"
        if clean_id != raw_id:
            clean_id = f"{clean_id}-{hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:8]}"
        workdir = self.agent_workspaces_dir / clean_id
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir

    def _assign_default_agent_workdir(
        self,
        agent_id: str,
        workspace_policy: dict[str, Any],
        tool_policy: dict[str, Any],
    ) -> dict[str, Any]:
        if str(workspace_policy.get("default_workdir") or "").strip():
            return workspace_policy
        assigned = {**workspace_policy, "default_workdir": str(self._default_agent_workdir(agent_id))}
        if "workspace.write_patch" in (tool_policy.get("allowed_tools") or []) and not assigned.get("writable_scopes"):
            assigned["writable_scopes"] = ["."]
        return assigned

    def trust_workspace(self, path: str | Path, *, source: str = "runtime", commit: bool = True) -> dict[str, Any]:
        return self.trusted_workspaces.trust(path, source=source, commit=commit)

    def _trust_workspace_from_policy(
        self,
        workspace_policy: dict[str, Any],
        *,
        source: str,
        commit: bool = True,
    ) -> None:
        workdir = str(workspace_policy.get("default_workdir") or "").strip()
        if not workdir:
            return
        self.trusted_workspaces.trust_from_policy(
            workspace_policy,
            source=source,
            commit=commit,
        )

    def list_trusted_workspaces(self) -> dict[str, Any]:
        return self.trusted_workspaces.list()

    def _migrate_agent_workspace_policies(self) -> None:
        rows = self._conn.execute(
            "SELECT agent_id, category, tool_policy_json, workspace_policy_json FROM agents"
        ).fetchall()
        changed = False
        for row in rows:
            tool_policy = self._compile_tool_policy(
                str(row["category"] or "custom"),
                _json_load(row["tool_policy_json"], {}),
            )
            workspace_policy = self._compile_workspace_policy(
                _json_load(row["workspace_policy_json"], self._default_workspace_policy())
            )
            if str(workspace_policy.get("default_workdir") or "").strip():
                continue
            workspace_policy = self._assign_default_agent_workdir(str(row["agent_id"]), workspace_policy, tool_policy)
            self._conn.execute(
                "UPDATE agents SET workspace_policy_json=?, updated_at=? WHERE agent_id=?",
                (_json_dump(workspace_policy), _now(), row["agent_id"]),
            )
            changed = True
        if changed:
            self._conn.commit()

    @staticmethod
    def _tool_schemas(allowed_tools: list[str]) -> list[dict[str, Any]]:
        return ToolDescriptorRegistry.model_tool_schemas(allowed_tools)

    def _compile_tool_policy(self, category: str, policy: Any = None) -> dict[str, Any]:
        return self.runtime_policy.compile_tool_policy(category, policy)

    def _compile_workspace_policy(self, policy: Any = None) -> dict[str, Any]:
        return self.runtime_policy.compile_workspace_policy(policy)

    def _memory_store(self, *, source_run_id: str = "") -> AgentMemoryStore:
        return AgentMemoryStore(
            self._conn,
            self._db_lock,
            source_run_id=source_run_id,
            now=_now,
            json_dump=_json_dump,
            redact_json_value=_redact_json_value,
            redact_secrets=redact_secrets,
            memory_scopes=_MEMORY_SCOPES,
            memory_kinds=_MEMORY_KINDS,
            context_limit=_MEMORY_CONTEXT_LIMIT,
            content_max_chars=_MEMORY_CONTENT_MAX_CHARS,
            error_type=AgentRuntimeError,
        )

    def _future_task_store(
        self,
        *,
        source_run_id: str = "",
        default_runnable_id: str = "",
    ) -> AgentFutureTaskStore:
        return AgentFutureTaskStore(
            self._conn,
            self._db_lock,
            source_run_id=source_run_id,
            default_runnable_id=default_runnable_id,
            now=_now,
            json_dump=_json_dump,
            redact_json_value=_redact_json_value,
            redact_secrets=redact_secrets,
            error_type=AgentRuntimeError,
        )

    def list_memory_items(self, *, include_deleted: bool = False, limit: int = 100) -> dict[str, Any]:
        memories = self._memory_store().list_items(include_deleted=include_deleted, limit=limit)
        return {"ok": True, "memories": memories}

    def create_memory_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._memory_store(source_run_id="manual").add(
            content=str(payload.get("content") or ""),
            kind=str(payload.get("kind") or ""),
            scope=str(payload.get("scope") or ""),
        )

    def update_memory_item(self, memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._memory_store(source_run_id="manual").replace(
            memory_id=memory_id,
            old_content=str(payload.get("old_content") or ""),
            content=str(payload.get("content") or ""),
            kind=str(payload.get("kind") or ""),
            scope=str(payload.get("scope") or ""),
        )

    def delete_memory_item(self, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._memory_store(source_run_id="manual").remove(memory_id=memory_id, reason=reason)

    def _long_term_memory_context(self) -> str:
        return self._memory_store().context_block(limit=_MEMORY_CONTEXT_LIMIT)

    def schedule_future_task(self, payload: dict[str, Any], *, source_run_id: str = "") -> dict[str, Any]:
        runnable_name = str(payload.get("runnable_name") or payload.get("name") or "").strip()
        runnable_id = str(payload.get("runnable_id") or ("" if runnable_name else _MAIN_CHAT_AGENT_ID)).strip()
        if self.resolve_runnable(runnable_id=runnable_id, name=runnable_name) is None:
            raise AgentRuntimeError("FutureTask 指向的 Agent 或 Workflow 不存在")
        return self._future_task_store(
            source_run_id=source_run_id or "manual",
            default_runnable_id=runnable_id,
        ).schedule(
            title=str(payload.get("title") or ""),
            prompt=str(payload.get("prompt") or payload.get("user_goal") or payload.get("goal") or ""),
            runnable_id=runnable_id,
            runnable_name=runnable_name,
            delay_seconds=payload.get("delay_seconds"),
            scheduled_at_epoch=payload.get("scheduled_at_epoch"),
            cron=str(payload.get("cron") or ""),
        )

    def list_future_tasks(self, *, include_finished: bool = True, limit: int = 100) -> dict[str, Any]:
        return {
            "ok": True,
            "future_tasks": self._future_task_store().list_tasks(
                include_finished=include_finished,
                limit=limit,
            ),
        }

    def cancel_future_task(self, future_task_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._future_task_store(source_run_id="manual").cancel(future_task_id, reason=reason)

    def trigger_due_future_tasks(self, *, now_epoch: float | None = None, limit: int = 20) -> dict[str, Any]:
        return self.future_task_scheduler.trigger_due_future_tasks(
            now_epoch=now_epoch,
            limit=limit,
        )

    def _row_to_agent(self, row: Any) -> dict[str, Any]:
        return {
            "agent_id": row["agent_id"],
            "name": row["name"],
            "nickname": row["nickname"] or row["name"],
            "description": row["description"],
            "avatar_url": row["avatar_url"],
            "category": row["category"],
            "instructions": row["instructions"],
            "persona_prompt": row["persona_prompt"],
            "model_mode": row["model_mode"],
            "execution_backend": _normalize_execution_backend(row["execution_backend"], model_mode=row["model_mode"]),
            "model_profile_id": row["model_profile_id"],
            "vision_model_profile_id": row["vision_model_profile_id"],
            "model_config": {
                "provider": row["model_provider"],
                "base_url": row["model_base_url"],
                "model": row["model_name"],
                "api_key_configured": bool(str(row["model_credential_ref"] or "").strip() or str(row["model_api_key"] or "").strip()),
            },
            "tool_policy": self._compile_tool_policy(
                row["category"],
                _json_load(row["tool_policy_json"], self._default_tool_policy(row["category"])),
            ),
            "workspace_policy": self._compile_workspace_policy(
                _json_load(row["workspace_policy_json"], self._default_workspace_policy()),
            ),
            "skill_ids": _json_load(row["skill_ids_json"], []),
            "output_contract": row["output_contract"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_agent_private(self, row: Any) -> dict[str, Any]:
        agent = self._row_to_agent(row)
        agent["model_config"]["credential_ref"] = row["model_credential_ref"]
        agent["model_config"]["api_key"] = (
            self._read_credential(str(row["model_credential_ref"] or "")) or str(row["model_api_key"] or "")
        )
        return agent

    def _main_chat_virtual_agent(self) -> dict[str, Any]:
        try:
            default_profile_id = str(get_model_profile_service().get_defaults().get("chat") or "").strip()
        except Exception:
            default_profile_id = ""
        return {
            "agent_id": _MAIN_CHAT_AGENT_ID,
            "name": "Yachiyo",
            "nickname": "Yachiyo",
            "description": "Oha-Yachiyo main chat system agent.",
            "avatar_url": "",
            "category": "orchestrator",
            "instructions": "Main chat native agent.",
            "persona_prompt": "",
            "model_mode": "profile",
            "execution_backend": "native_profile",
            "model_profile_id": default_profile_id,
            "vision_model_profile_id": "",
            "model_config": {
                "provider": "model_profile",
                "base_url": "",
                "model": "",
                "api_key_configured": bool(default_profile_id),
            },
            "tool_policy": self._main_chat_tool_policy(),
            "workspace_policy": self._compile_workspace_policy(
                {
                    "default_workdir": str(self.agent_workspaces_dir / "builtin-yachiyo-main"),
                    "readable_scopes": ["."],
                    "writable_scopes": [],
                }
            ),
            "skill_ids": [],
            "output_contract": "chat",
            "enabled": True,
            "virtual": True,
            "system": True,
            "builtin": True,
            "editable": False,
            "deletable": False,
            "created_at": "",
            "updated_at": "",
        }

    def _row_to_skill(self, row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        folder_id = str(row["folder_id"] if "folder_id" in keys else "")
        folder_name = str(row["folder_name"] if "folder_name" in keys and row["folder_name"] else "")
        return {
            "skill_id": row["skill_id"],
            "name": row["name"],
            "description": row["description"],
            "source_path": row["source_path"],
            "local_path": row["local_path"] or str(self.skills_dir / row["skill_id"]),
            "folder_id": folder_id,
            "folder_name": folder_name,
            "source_type": row["source_type"],
            "origin_path": row["origin_path"],
            "source_ref": row["source_ref"],
            "content_hash": row["content_hash"],
            "last_synced_at": row["last_synced_at"],
            "sync_status": row["sync_status"],
            "content_summary": row["content_summary"],
            "skill_markdown": row["skill_markdown"],
            "asset_paths": _json_load(row["asset_paths_json"], []),
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_skill_folder(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "folder_id": row["folder_id"],
            "name": row["name"],
            "description": row["description"],
            "source_scope": row["source_scope"],
            "sort_order": int(row["sort_order"]),
            "skill_count": int(row["skill_count"] or 0),
            "installed_count": int(row["installed_count"] or 0),
            "native_count": int(row["native_count"] or 0),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_workflow(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "workflow_id": row["workflow_id"],
            "name": row["name"],
            "description": row["description"],
            "nodes": _json_load(row["nodes_json"], []),
            "edges": _json_load(row["edges_json"], []),
            "default_input_schema": _json_load(row["default_input_schema_json"], {}),
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_run(self, row: sqlite3.Row) -> dict[str, Any]:
        row_keys = row.keys() if hasattr(row, "keys") else []
        run_group_id = row["run_group_id"]
        run_group_source = (
            str(row["run_group_source"] or "")
            if "run_group_source" in row_keys
            else self._run_group_source(str(run_group_id or ""))
        )
        task_link = self.task_run_links.for_run(str(row["run_id"] or ""))
        run = {
            "run_id": row["run_id"],
            "task_id": str(task_link["task_id"] or "") if task_link is not None else "",
            "session_id": str(task_link["session_id"] or "") if task_link is not None else "",
            "task_run_link_created_at": str(task_link["created_at"] or "") if task_link is not None else "",
            "task_run_link_updated_at": str(task_link["updated_at"] or "") if task_link is not None else "",
            "task_run_link_run_status": str(task_link["run_status"] or "") if task_link is not None else "",
            "task_run_link_last_event_sequence": (
                int(task_link["last_event_sequence"] or 0) if task_link is not None else 0
            ),
            "run_group_id": run_group_id,
            "run_group_source": run_group_source,
            "client_request_id": str(row["client_request_id"] or "") if "client_request_id" in row_keys else "",
            "kind": row["kind"],
            "runnable_id": row["runnable_id"],
            "runnable_name": self._runnable_name(str(row["kind"]), str(row["runnable_id"])),
            "status": row["status"],
            "user_goal": row["user_goal"],
            "result": row["result"],
            "timeline": _json_load(row["timeline_json"], []),
            "artifacts": _json_load(row["artifacts_json"], []),
            "pending_approval": _public_pending_approval(_json_load(row["pending_approval_json"], {})),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        return run

    def _row_to_run_group(self, row: sqlite3.Row) -> dict[str, Any]:
        child_run_ids = _json_load(row["child_run_ids_json"], [])
        return {
            "run_group_id": row["run_group_id"],
            "title": row["title"],
            "source": row["source"],
            "workspace_dir": row["workspace_dir"],
            "status": row["status"],
            "summary": row["summary"],
            "child_run_ids": child_run_ids if isinstance(child_run_ids, list) else [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _runnable_name(self, kind: str, runnable_id: str) -> str:
        self._ensure_row_factory()
        if kind == "main_chat_run" and runnable_id == _MAIN_CHAT_AGENT_ID:
            return "Yachiyo"
        if kind == "agent_run":
            row = self._conn.execute("SELECT name FROM agents WHERE agent_id=?", (runnable_id,)).fetchone()
            return str(row["name"]) if row is not None else ""
        if kind == "workflow_run":
            row = self._conn.execute("SELECT name FROM workflows WHERE workflow_id=?", (runnable_id,)).fetchone()
            return str(row["name"]) if row is not None else ""
        return ""

    def _ensure_global_name_available(self, name: str, *, ignore_agent_id: str = "", ignore_workflow_id: str = "") -> None:
        self._ensure_row_factory()
        clean = (name or "").strip()
        if not clean:
            raise AgentRuntimeError("名称不能为空")
        if clean.lower() == "yachiyo":
            raise AgentRuntimeError("Yachiyo 是系统 Agent 名称，不能作为普通 Agent/Workflow 名称")
        agent = self._conn.execute(
            "SELECT agent_id FROM agents WHERE LOWER(name)=LOWER(?)",
            (clean,),
        ).fetchone()
        if agent and agent["agent_id"] != ignore_agent_id:
            raise AgentRuntimeError("Agent/Workflow 名称必须全局唯一")
        workflow = self._conn.execute(
            "SELECT workflow_id FROM workflows WHERE LOWER(name)=LOWER(?)",
            (clean,),
        ).fetchone()
        if workflow and workflow["workflow_id"] != ignore_workflow_id:
            raise AgentRuntimeError("Agent/Workflow 名称必须全局唯一")

    @staticmethod
    def _validate_available_profile(profile_id: str, capability: str) -> dict[str, Any]:
        try:
            profile = get_model_profile_service().get_profile(profile_id)
        except KeyError as exc:
            raise AgentRuntimeError("Agent 引用的模型 Profile 不存在") from exc
        if str(profile.get("capability") or "") != capability:
            raise AgentRuntimeError(f"Agent 引用的 {capability} 模型 Profile 类型不匹配")
        if str(profile.get("status") or "") != "available":
            raise AgentRuntimeError("Agent 只能引用已通过连接测试的模型 Profile")
        if not profile.get("enabled", True):
            raise AgentRuntimeError("Agent 引用的模型 Profile 已停用")
        return profile

    def _validate_agent_profile_refs(self, payload: dict[str, Any]) -> None:
        model_mode = str(payload.get("model_mode") or "profile")
        if model_mode == "profile":
            profile_id = str(payload.get("model_profile_id") or "").strip()
            if profile_id:
                self._validate_available_profile(profile_id, "chat")
        vision_profile_id = str(payload.get("vision_model_profile_id") or "").strip()
        if vision_profile_id:
            self._validate_available_profile(vision_profile_id, "vision")

    def list_agents(self) -> dict[str, Any]:
        return self.agent_definitions.list()

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self.agent_definitions.get(agent_id)

    def _get_agent_private(self, agent_id: str) -> dict[str, Any]:
        return self.agent_definitions.get_private(agent_id)

    def create_agent(self, payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        return self.agent_definitions.create(payload, seed=seed)

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.agent_definitions.update(agent_id, payload)

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        return self.agent_definitions.delete(agent_id)

    def attach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        agent = self.get_agent(agent_id)
        skill = self.get_skill(skill_id)
        if not skill.get("enabled", True):
            raise AgentRuntimeError("Skill 已停用，不能挂载")
        skill_ids = list(dict.fromkeys([*agent.get("skill_ids", []), skill_id]))
        return self.update_agent(agent_id, {"skill_ids": skill_ids})

    def detach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        agent = self.get_agent(agent_id)
        skill_ids = [item for item in agent.get("skill_ids", []) if item != skill_id]
        return self.update_agent(agent_id, {"skill_ids": skill_ids})

    def list_skill_folders(self) -> dict[str, Any]:
        return self.skill_folders.list()

    def create_skill_folder(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.skill_folders.create(payload)

    def get_skill_folder(self, folder_id: str) -> dict[str, Any]:
        return self.skill_folders.get(folder_id)

    def update_skill_folder(self, folder_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.skill_folders.update(folder_id, payload)

    def delete_skill_folder(self, folder_id: str, *, delete_skills: bool = False) -> dict[str, Any]:
        return self.skill_folders.delete(folder_id, delete_skills=delete_skills)

    def list_skills(self) -> dict[str, Any]:
        return self.skill_records.list()

    def list_native_skill_sources(self) -> dict[str, Any]:
        roots = self._native_skill_root_specs()
        return {
            "ok": True,
            "roots": [
                {
                    "path": str(root["path"]),
                    "source_type": root["source_type"],
                    "library": "native",
                    "exists": root["path"].exists(),
                    "skill_count": self._count_skill_files(root["path"]),
                }
                for root in roots
            ],
        }

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        return self.skill_records.get(skill_id)

    def import_skill(self, source_path: str, folder_id: str | None = None) -> dict[str, Any]:
        source = Path(source_path).expanduser()
        if not source.exists():
            raise AgentRuntimeError("Skill 路径不存在")
        target_folder_id = self._normalize_skill_folder_id(folder_id)
        resolved = self.skill_import_sources.resolve(str(source))
        try:
            imported = self._import_skill_root(
                resolved.source_root,
                source_path=resolved.source_path,
                source_type=resolved.source_type,
                origin_path=resolved.origin_path,
                source_ref=resolved.source_ref,
                sync_status="imported",
                folder_id=target_folder_id,
            )
            self._clear_studio_deletion(
                "skill_source",
                self._skill_deletion_key(resolved.source_type, resolved.origin_path),
            )
            self._conn.commit()
            return imported
        finally:
            self.skill_import_sources.cleanup(resolved)

    def sync_native_skills(self, roots: list[Any] | None = None) -> dict[str, Any]:
        return self._sync_skill_roots(self._native_skill_root_specs(roots), library="native")

    def sync_installed_skills(
        self,
        *,
        record_source_type: str = "npx_skills",
        folder_id: str | None = None,
        source_ref_override: str = "",
        restore_deleted: bool = False,
    ) -> dict[str, Any]:
        source_type = record_source_type if record_source_type == "npx_skills" else "npx_skills"
        roots = self._installed_skill_root_specs(source_type=source_type, source_ref_override=source_ref_override)
        return self._sync_skill_roots(
            roots,
            library="installed",
            folder_id=folder_id,
            restore_deleted=restore_deleted,
        )

    def _sync_skill_roots(
        self,
        root_specs: list[dict[str, Any]],
        *,
        library: str,
        folder_id: str | None = None,
        restore_deleted: bool = False,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        now = _now()
        target_folder_id = self._normalize_skill_folder_id(folder_id) if folder_id is not None else None
        for entry in self.skill_sync.plan_entries(root_specs, library=library):
            if entry.skipped_result is not None:
                results.append(entry.skipped_result)
                continue
            if entry.candidate is None:
                continue
            candidate = entry.candidate
            source_root = candidate.source_root
            source_type = candidate.source_type
            source_ref = candidate.source_ref
            library_name = candidate.library
            deletion_key = self._skill_deletion_key(source_type, str(source_root.resolve()))
            has_deletion = self._has_studio_deletion("skill_source", deletion_key)
            restore_deletion = restore_deleted and has_deletion
            if has_deletion and not restore_deletion:
                results.append({
                    "source": str(source_root),
                    "source_type": source_type,
                    "library": library_name,
                    "source_ref": source_ref,
                    "status": "skipped",
                    "message": "用户已删除，跳过同步；可通过显式导入或重新安装恢复",
                })
                continue
            try:
                result = self._import_skill_root(
                    source_root,
                    source_path=f"{source_type}:{source_ref}",
                    source_type=source_type,
                    origin_path=str(source_root.resolve()),
                    source_ref=source_ref,
                    sync_status="synced",
                    synced_at=now,
                    copy_to_managed=False,
                    folder_id=target_folder_id,
                )
                if restore_deletion:
                    self._clear_studio_deletion("skill_source", deletion_key)
                    self._conn.commit()
                results.append({
                    "source": str(source_root),
                    "source_type": source_type,
                    "library": library_name,
                    "source_ref": source_ref,
                    "status": result["sync_status"],
                    "skill_id": result["skill_id"],
                    "name": result["name"],
                })
            except AgentRuntimeError as exc:
                results.append({
                    "source": str(source_root),
                    "source_type": source_type,
                    "library": library_name,
                    "source_ref": source_ref,
                    "status": "failed",
                    "message": redact_api_error_text(exc),
                })
        summary = self.skill_sync.summarize_results(results)
        roots_info = self.skill_sync.roots_info(root_specs, library=library)
        return {"ok": summary["failed"] == 0, "roots": roots_info, "summary": summary, "results": results}

    def install_skill_command(self, command: str, folder_id: str | None = None) -> dict[str, Any]:
        argv, installer = self._validated_skill_install_argv(command)
        target_folder_id = self._normalize_skill_folder_id(folder_id)
        source_ref = self._skill_install_source_ref(argv, installer)
        started_at = _now()
        env = scrubbed_subprocess_env({"OHA_YACHIYO_HOME": str(self.skill_installs_native_home)})
        try:
            completed = subprocess.run(
                argv,
                cwd=self.skill_installs_dir,
                env=env,
                text=True,
                capture_output=True,
                timeout=600,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AgentRuntimeError(f"找不到安装命令：{argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AgentRuntimeError("Skill 安装命令超时") from exc
        stdout = redact_secrets(completed.stdout)[-12000:]
        stderr = redact_secrets(completed.stderr)[-12000:]
        sync_result = (
            self.sync_installed_skills(
                record_source_type=installer,
                folder_id=target_folder_id,
                source_ref_override=source_ref,
                restore_deleted=True,
            )
            if completed.returncode == 0
            else None
        )
        return {
            "ok": completed.returncode == 0,
            "installer": installer,
            "command": argv,
            "started_at": started_at,
            "finished_at": _now(),
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "sync": sync_result,
        }

    def _import_skill_root(
        self,
        source_root: Path,
        *,
        source_path: str,
        source_type: str,
        origin_path: str,
        source_ref: str,
        sync_status: str,
        synced_at: str = "",
        copy_to_managed: bool = True,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        prepared = self.skill_import_preparer.prepare(
            source_root,
            source_type=source_type,
            source_ref=source_ref,
            synced_at=synced_at,
        )
        source_ref = prepared.source_ref
        name = prepared.name
        description = prepared.description
        content_hash = prepared.content_hash
        existing = self._find_existing_skill(origin_path, content_hash, source_type)
        summary = prepared.summary
        now = prepared.now
        last_synced_at = prepared.last_synced_at
        markdown = prepared.markdown
        target_folder_id = self._normalize_skill_folder_id(folder_id) if folder_id is not None else ""
        saved = self.skill_records.save_import(
            source_root=source_root,
            source_path=source_path,
            source_type=source_type,
            origin_path=origin_path,
            source_ref=source_ref,
            name=name,
            description=description,
            content_hash=content_hash,
            last_synced_at=last_synced_at,
            sync_status=sync_status,
            summary=summary,
            markdown=markdown,
            now=now,
            existing=existing,
            copy_to_managed=copy_to_managed,
            folder_id_was_provided=folder_id is not None,
            target_folder_id=target_folder_id,
        )
        skill = self.get_skill(saved["skill_id"])
        skill["sync_status"] = saved["sync_status"]
        return skill

    def _find_existing_skill(self, origin_path: str, content_hash: str, source_type: str) -> sqlite3.Row | None:
        return self.skill_records.find_existing_import(
            origin_path=origin_path,
            content_hash=content_hash,
            source_type=source_type,
        )

    def _repair_native_skill_references(self) -> None:
        self.skill_records.repair_native_references()

    def _repair_installed_skill_provenance(self) -> None:
        self.skill_records.repair_installed_provenance()

    def _native_skill_root_specs(self, roots: list[Any] | None = None) -> list[dict[str, Any]]:
        return self.skill_sources.native_root_specs(roots)

    def _installed_skill_root_specs(self, *, source_type: str, source_ref_override: str = "") -> list[dict[str, Any]]:
        return self.skill_sources.installed_root_specs(
            source_type=source_type,
            source_ref_override=source_ref_override,
        )

    def _installed_skill_source_map(self) -> dict[str, str]:
        return self.skill_sources.installed_source_map()

    @staticmethod
    def _skill_lock_source_ref(entry: dict[str, Any]) -> str:
        return SkillSourceDiscovery.skill_lock_source_ref(entry)

    @staticmethod
    def _infer_native_source_type(path: Path) -> str:
        return SkillSourceDiscovery.infer_native_source_type(path)

    @staticmethod
    def _count_skill_files(root: Path) -> int:
        return SkillSourceDiscovery.count_skill_files(root)

    def _validated_skill_install_argv(self, command: str) -> tuple[list[str], str]:
        return self.skill_install_validator.validate(command)

    def _skill_install_source_ref(self, argv: list[str], installer: str) -> str:
        return self.skill_install_validator.source_ref(argv, installer)

    @staticmethod
    def _metadata_skill_source_ref(metadata: dict[str, Any], fallback: str) -> str:
        return SkillContentInspector.metadata_source_ref(metadata, fallback)

    def _validated_npx_skills_argv(self, argv: list[str]) -> list[str]:
        return self.skill_install_validator.validate_npx_skills_argv(argv)

    @staticmethod
    def _has_agent_target(args: list[str]) -> bool:
        return SkillInstallCommandValidator.has_agent_target(args)

    def _validate_skill_install_agent_target(self, args: list[str]) -> None:
        self.skill_install_validator.validate_agent_target(args)

    def _normalize_skill_folder_id(self, folder_id: str | None) -> str:
        return self.skill_folders.normalize_id(folder_id)

    def _validate_skill_folder_name(self, name: str, *, current_folder_id: str = "") -> None:
        self.skill_folders.validate_name(name, current_folder_id=current_folder_id)

    def update_skill(self, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.skill_records.update(skill_id, payload)

    @staticmethod
    def _skill_name(markdown: str, fallback: str) -> str:
        return SkillContentInspector.name(markdown, fallback)

    @staticmethod
    def _skill_description(markdown: str) -> str:
        return SkillContentInspector.description(markdown)

    @staticmethod
    def _skill_summary(markdown: str) -> str:
        return SkillContentInspector.summary(markdown)

    @staticmethod
    def _skill_asset_paths(root: Path) -> list[str]:
        return SkillContentInspector.asset_paths(root)

    def delete_skill(self, skill_id: str) -> dict[str, Any]:
        return self.skill_records.delete(skill_id)

    def list_workflows(self) -> dict[str, Any]:
        return self.workflows.list()

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self.workflows.get(workflow_id)

    def create_workflow(self, payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        return self.workflows.create(payload, seed=seed)

    def update_workflow(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.workflows.update(workflow_id, payload)

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self.workflows.delete(workflow_id)

    @staticmethod
    def _node_kind(node: dict[str, Any]) -> str:
        data = node.get("data") or {}
        data_kind = str(data.get("kind") or data.get("node_type") or "").strip()
        node_type = str(node.get("type") or "").strip()
        if data_kind and node_type in {"", "input", "default", "output"}:
            return data_kind
        return node_type or data_kind

    def validate_workflow(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        if not nodes:
            raise AgentRuntimeError("Workflow 至少需要一个 Start 节点")
        node_ids = [str(node.get("id") or "") for node in nodes]
        if len(set(node_ids)) != len(node_ids) or any(not node_id for node_id in node_ids):
            raise AgentRuntimeError("Workflow 节点 ID 必须唯一")
        for node in nodes:
            kind = self._node_kind(node)
            if kind not in _WORKFLOW_NODE_TYPES:
                label = str((node.get("data") or {}).get("label") or node.get("id") or "节点").strip() or "节点"
                raise AgentRuntimeError(f"{label} 使用了未知 Workflow 节点类型：{kind or '空'}")
            if kind == "artifact":
                data = node.get("data") or {}
                artifact_path = str(data.get("artifact_path") or data.get("artifactPath") or "").strip()
                if artifact_path:
                    label = str(data.get("label") or node.get("id") or "Artifact").strip() or "Artifact"
                    try:
                        _safe_rel_path(artifact_path)
                    except AgentRuntimeError as exc:
                        raise AgentRuntimeError(f"Artifact 节点 {label} 的产物路径无效：{exc}") from exc
            if kind == "condition":
                data = node.get("data") or {}
                condition = WorkflowPathPlanner.condition_text(node)
                if not condition:
                    label = str(data.get("label") or node.get("id") or "Condition").strip() or "Condition"
                    raise AgentRuntimeError(f"Condition 节点 {label} 缺少条件文本")
            if kind == "loop":
                data = node.get("data") or {}
                condition = WorkflowPathPlanner.condition_text(node)
                if not condition:
                    label = str(data.get("label") or node.get("id") or "Loop").strip() or "Loop"
                    raise AgentRuntimeError(f"Loop 节点 {label} 缺少条件文本")
        starts = [node for node in nodes if self._node_kind(node) == "start"]
        if len(starts) != 1:
            raise AgentRuntimeError("Workflow 必须且只能有一个 Start 节点")
        start_id = str(starts[0]["id"])
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        incoming: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        for edge in edges:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source not in outgoing or target not in incoming:
                raise AgentRuntimeError("Workflow edge 引用了不存在的节点")
            outgoing[source].append(target)
            incoming[target].append(source)
        if incoming[start_id]:
            raise AgentRuntimeError("Start 节点不能有入边")
        for node_id, targets in outgoing.items():
            node = next(item for item in nodes if str(item.get("id") or "") == node_id)
            kind = self._node_kind(node)
            if kind == "condition":
                if len(targets) != 2:
                    raise AgentRuntimeError("Condition 节点必须有 true/false 两个下一步")
                branch_roles = [
                    WorkflowPathPlanner.edge_branch(edge)
                    for edge in edges
                    if str(edge.get("source") or "") == node_id
                ]
                labelled_roles = [role for role in branch_roles if role]
                if labelled_roles and set(labelled_roles) != {"true", "false"}:
                    raise AgentRuntimeError("Condition 节点分支必须标注 true/false")
                if len(labelled_roles) != len(set(labelled_roles)):
                    raise AgentRuntimeError("Condition 节点分支标注不能重复")
            elif kind == "parallel":
                if len(targets) < 2:
                    raise AgentRuntimeError("Parallel 节点必须至少有两个并行分支")
            elif kind == "loop":
                if len(targets) != 2:
                    raise AgentRuntimeError("Loop 节点必须有 continue/exit 两个下一步")
                branch_roles = [
                    WorkflowPathPlanner.loop_edge_role(edge)
                    for edge in edges
                    if str(edge.get("source") or "") == node_id
                ]
                labelled_roles = [role for role in branch_roles if role]
                if labelled_roles and set(labelled_roles) != {"continue", "exit"}:
                    raise AgentRuntimeError("Loop 节点分支必须标注 continue/exit")
                if len(labelled_roles) != len(set(labelled_roles)):
                    raise AgentRuntimeError("Loop 节点分支标注不能重复")
            elif len(targets) > 1:
                raise AgentRuntimeError("只有 Condition、Parallel 或 Loop 节点允许多个下一步")
        for node_id, sources in incoming.items():
            if node_id != start_id and len(sources) < 1:
                raise AgentRuntimeError("Workflow 不允许断链节点")
        seen: set[str] = set()
        active: set[str] = set()

        def visit(node_id: str, incoming_edge: dict[str, Any] | None = None) -> None:
            if node_id in active:
                source = str((incoming_edge or {}).get("source") or "")
                source_node = next((item for item in nodes if str(item.get("id") or "") == source), {})
                source_kind = self._node_kind(source_node) if source_node else ""
                if source_kind == "loop" and WorkflowPathPlanner.loop_edge_role(incoming_edge or {}) == "continue":
                    return
                raise AgentRuntimeError("Workflow 不能包含非 Loop 控制的环")
            if node_id in seen:
                return
            active.add(node_id)
            for edge in (edge for edge in edges if str(edge.get("source") or "") == node_id):
                target = str(edge.get("target") or "")
                if target:
                    visit(target, edge)
            active.remove(node_id)
            seen.add(node_id)

        visit(start_id)
        if seen != set(node_ids):
            raise AgentRuntimeError("Workflow 必须从 Start 触达所有节点")
        return {"ok": True}

    def _workflow_agent_for_node(self, node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") or {}
        label = str(data.get("label") or node.get("id") or "Agent").strip() or "Agent"
        agent_id = str(data.get("agent_id") or data.get("agentId") or "").strip()
        if not agent_id:
            raise AgentRuntimeError(f"Agent 节点 {label} 没有选择 Agent")
        try:
            agent = self._get_agent_private(agent_id)
        except KeyError as exc:
            raise AgentRuntimeError(f"Agent 节点 {label} 引用了不存在的 Agent") from exc
        if not agent.get("enabled", True):
            raise AgentRuntimeError(f"Agent 节点 {label} 选择的 Agent 已停用")
        return agent

    @staticmethod
    def _workflow_id_for_node(node: dict[str, Any]) -> str:
        return WorkflowPathPlanner.workflow_id(node)

    def _workflow_for_node(self, node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") or {}
        label = str(data.get("label") or node.get("id") or "Workflow").strip() or "Workflow"
        workflow_id = self._workflow_id_for_node(node)
        if not workflow_id:
            raise AgentRuntimeError(f"Workflow 节点 {label} 没有选择子 Workflow")
        try:
            workflow = self.get_workflow(workflow_id)
        except KeyError as exc:
            raise AgentRuntimeError(f"Workflow 节点 {label} 引用了不存在的子 Workflow") from exc
        if not workflow.get("enabled", True):
            raise AgentRuntimeError(f"Workflow 节点 {label} 选择的子 Workflow 已停用")
        return workflow

    def _validate_workflow_agent_nodes(self, nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if self._node_kind(node) == "agent":
                self._workflow_agent_for_node(node)

    def _validate_workflow_subworkflow_nodes(
        self,
        nodes: list[dict[str, Any]],
        *,
        parent_workflow_id: str = "",
    ) -> None:
        for node in nodes:
            if self._node_kind(node) != "workflow":
                continue
            data = node.get("data") or {}
            label = str(data.get("label") or node.get("id") or "Workflow").strip() or "Workflow"
            workflow_id = self._workflow_id_for_node(node)
            if not workflow_id:
                raise AgentRuntimeError(f"Workflow 节点 {label} 没有选择子 Workflow")
            if parent_workflow_id and workflow_id == parent_workflow_id:
                raise AgentRuntimeError(f"Workflow 节点 {label} 不能引用当前 Workflow")
            self._workflow_for_node(node)

    def _validate_agent_run_readiness(
        self,
        agent: dict[str, Any],
        *,
        label: str = "Agent",
        require_model_config: bool = False,
    ) -> None:
        display = str(label or agent.get("name") or "Agent").strip() or "Agent"
        if not agent.get("enabled", True):
            raise AgentRuntimeError(f"{display} 已停用")
        self._load_agent_skills(agent.get("skill_ids") or [])
        model_mode = str(agent.get("model_mode") or "profile")
        model_config = agent.get("model_config") or {}
        if model_mode == "custom_api":
            missing = [
                label
                for key, label in (
                    ("base_url", "Base URL"),
                    ("model", "Model"),
                    ("api_key", "API Key"),
                )
                if not str(model_config.get(key) or "").strip()
            ]
            if missing:
                raise AgentRuntimeError(f"{display} Custom API 配置不完整：缺少 {', '.join(missing)}")
        elif require_model_config and model_mode != "follow_main" and str(agent.get("agent_id") or "") not in _DEFAULT_AGENT_IDS:
            if not str(agent.get("model_profile_id") or "").strip():
                raise AgentRuntimeError(f"{display} 缺少可运行的 Chat Profile")
        if require_model_config:
            try:
                self._agent_model_config_private(agent)
            except AgentRuntimeError as exc:
                raise AgentRuntimeError(f"{display} 无法运行：{exc}") from exc

    def _validate_workflow_agent_run_readiness(self, nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if self._node_kind(node) != "agent":
                continue
            data = node.get("data") or {}
            label = str(data.get("label") or node.get("id") or "Agent").strip() or "Agent"
            agent = self._workflow_agent_for_node(node)
            self._validate_agent_run_readiness(
                agent,
                label=f"Agent 节点 {label}",
                require_model_config=True,
            )

    def _validate_workflow_runnable_steps(self, nodes: list[dict[str, Any]]) -> None:
        if not any(self._node_kind(node) != "start" for node in nodes):
            raise AgentRuntimeError(
                "Workflow 至少需要一个可执行节点（Agent、Approval、Artifact、Condition、Parallel、Workflow 或 Loop）"
            )

    def list_runs(self, limit: int = 50) -> dict[str, Any]:
        return self.runs.list(limit)

    def list_run_groups(self, limit: int = 50) -> dict[str, Any]:
        return self.run_groups.list(limit)

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        return self.run_groups.get(run_group_id)

    def _run_group_source(self, run_group_id: str) -> str:
        return self.run_groups.source(run_group_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.runs.get(run_id)

    def link_task_run(self, *, task_id: str, run_id: str, session_id: str = "") -> dict[str, Any]:
        return self.task_run_links.link(task_id=task_id, run_id=run_id, session_id=session_id)

    def get_task_run_link(self, task_id: str) -> dict[str, Any]:
        return self.task_run_links.get(task_id)

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "native_runtime",
        visibility: str = "user",
        sensitivity: str = "public",
    ) -> dict[str, Any]:
        return self.runtime_events.append(
            run_id,
            event_type,
            payload,
            actor=actor,
            visibility=visibility,
            sensitivity=sensitivity,
        )

    def list_run_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        return self.runtime_events.list(
            run_id,
            after_sequence=after_sequence,
            limit=limit,
            include_internal=include_internal,
        )

    def delete_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if _is_active_run_status(str(run.get("status") or "")):
            raise AgentRuntimeError("Run 仍在进行中或待审批，取消或完成后才能删除")
        run_group_id = str(run.get("run_group_id") or "")
        targets = [run]
        delete_group = False
        if run.get("kind") == "workflow_run" and run_group_id:
            group_runs = self.run_groups.runs(run_group_id)
            if any(_is_active_run_status(str(item.get("status") or "")) for item in group_runs):
                raise AgentRuntimeError("这个 Workflow Run 仍有进行中或待审批的子 Run，取消或完成后才能删除")
            targets = group_runs or [run]
            delete_group = True
        deleted_run_ids = self.runs.delete_rows(targets, delete_artifacts=self.run_artifacts.delete_files)
        deleted_ids = set(deleted_run_ids)
        if delete_group and run_group_id:
            self.run_groups.delete(run_group_id)
        else:
            self.run_groups.remove_run_ids(run_group_id, deleted_ids)
        self._conn.commit()
        return {
            "ok": True,
            "deleted_run_ids": deleted_run_ids,
            "deleted_run_count": len(deleted_run_ids),
        }

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        return self.run_artifacts.read(run_id, artifact_path)

    def _insert_run_group(
        self,
        *,
        title: str,
        source: str,
        workspace_dir: str = "",
    ) -> dict[str, Any]:
        return self.run_groups.insert(title=title, source=source, workspace_dir=workspace_dir)

    def _append_run_to_group(self, run_group_id: str, run_id: str) -> None:
        self.run_groups.append_run(run_group_id, run_id)

    @staticmethod
    def _client_request_id_from_payload(payload: dict[str, Any]) -> str:
        client_request_id = str(
            payload.get("client_run_id")
            or payload.get("client_request_id")
            or payload.get("idempotency_key")
            or ""
        ).strip()[:128]
        if contains_sensitive_text(client_request_id):
            raise AgentRuntimeError("client_run_id/idempotency_key 不能包含 API key、token 或其他敏感值")
        return client_request_id

    def _run_by_client_request_id(self, client_request_id: str) -> dict[str, Any] | None:
        return self.runs.by_client_request_id(client_request_id)

    def _update_run_group(
        self,
        run_group_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
    ) -> None:
        self.run_groups.update(run_group_id, status=status, summary=summary)

    def _insert_run(
        self,
        *,
        kind: str,
        runnable_id: str,
        user_goal: str,
        run_group_id: str = "",
        client_request_id: str = "",
    ) -> dict[str, Any]:
        return self.runs.insert(
            kind=kind,
            runnable_id=runnable_id,
            user_goal=user_goal,
            run_group_id=run_group_id,
            client_request_id=client_request_id,
        )

    def _update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        result: str | None = None,
        timeline: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        pending_approval: dict[str, Any] | None | object = _UNSET,
    ) -> dict[str, Any]:
        run = self.runs.update(
            run_id,
            status=status,
            result=result,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=pending_approval,
        )
        return run

    def _terminal_run_or_none(self, run_id: str) -> dict[str, Any] | None:
        try:
            run = self.get_run(run_id)
        except KeyError:
            return None
        status = str(run.get("status") or "").strip()
        return run if status in _FINAL_RUN_STATUSES else None

    @staticmethod
    def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        return {
            "time": _now(),
            "event": event,
            "detail": redact_secrets(detail),
            **_redact_json_value(extra),
        }

    def _run_budget(self, run_id: str, timeline: list[dict[str, Any]]) -> _RunBudget:
        try:
            run = self.get_run(run_id) if run_id else {}
        except KeyError:
            run = {}
        model_calls = 0
        tool_calls = 0
        terminal_calls = 0
        for event in timeline:
            if not isinstance(event, dict):
                continue
            event_name = str(event.get("event") or "")
            if event_name in {"agent.model.response", "model.output.completed"}:
                model_calls += 1
            if event_name in {"agent.tool.call", "agent.tool.skipped", "agent.tool.denied"}:
                tool_calls += 1
            if event_name == "agent.tool.call" and str(event.get("detail") or "") == "terminal.run":
                result = event.get("result") if isinstance(event.get("result"), dict) else {}
                if not result.get("approval_required"):
                    terminal_calls += 1
        return _RunBudget(
            limits=self.runtime_limits,
            started_at_epoch=_iso_epoch(run.get("created_at")),
            model_calls_used=model_calls,
            tool_calls_used=tool_calls,
            terminal_calls_used=terminal_calls,
        )

    def _check_context_budget(self, budget: _RunBudget, messages: list[dict[str, Any]]) -> None:
        budget.check_context(_json_chars(_redact_json_value(messages)))

    def _limit_model_output(self, value: Any) -> tuple[str, bool]:
        safe = redact_secrets(value)
        return _truncate_text(safe, self.runtime_limits.max_model_output_chars)

    def _limit_tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        limited, truncated = _limit_json_strings(_redact_json_value(result), self.runtime_limits.max_tool_output_chars)
        if isinstance(limited, dict) and truncated:
            return {**limited, "truncated": True}
        return limited if isinstance(limited, dict) else {"ok": False, "error": str(limited)}

    def start_main_chat_run(
        self,
        *,
        task_id: str,
        session_id: str,
        user_goal: str,
    ) -> dict[str, Any]:
        run = self._insert_run(
            kind="main_chat_run",
            runnable_id=_MAIN_CHAT_AGENT_ID,
            user_goal=redact_secrets(user_goal),
        )
        self.link_task_run(task_id=task_id, run_id=run["run_id"], session_id=session_id)
        timeline = [
            self._timeline(
                "run.started",
                "Native main chat run started",
                task_id=str(task_id or ""),
                session_id=str(session_id or ""),
            ),
            self._timeline("task.created", str(task_id or ""), task_id=str(task_id or "")),
            self._timeline("task.started", str(task_id or ""), task_id=str(task_id or "")),
            self._timeline("task.linked", str(task_id or ""), task_id=str(task_id or "")),
        ]
        run = self._update_run(run["run_id"], timeline=timeline)
        self.runtime_task_events.started(
            run["run_id"],
            task_id=str(task_id or ""),
            session_id=str(session_id or ""),
        )
        return run

    def call_main_chat_model(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        *,
        profile_id: str = "",
        capability: str = "chat",
    ) -> str:
        run = self.get_run(run_id)
        if str(run.get("kind") or "") != "main_chat_run":
            raise AgentRuntimeError("Run 不是主聊天 Native Run")
        default_profile_id = str(
            profile_id or get_model_profile_service().get_defaults().get(capability) or ""
        ).strip()
        if not default_profile_id:
            raise AgentRuntimeError(f"native_agent_not_ready:{capability}_model_profile_required")
        model_config = self._model_profile_config_private(default_profile_id, capability=capability)
        timeline = list(run.get("timeline") or [])
        budget = self._run_budget(run_id, timeline)
        self._check_context_budget(budget, messages)
        budget.claim_model_call()
        timeline.append(
            self._timeline(
                "model.request.started",
                str(model_config.get("model") or ""),
                profile_id=default_profile_id,
                capability=capability,
            )
        )
        self._update_run(run_id, timeline=timeline)
        self.append_run_event(
            run_id,
            "model.request.started",
            self.runtime_task_model_events.model_request_started_payload(
                profile_id=default_profile_id,
                model=str(model_config.get("model") or ""),
                capability=capability,
                message_count=len(messages),
            ),
        )
        try:
            message = _coalesce_model_message(
                _call_model_profile_chat_message(
                    str(model_config.get("base_url") or ""),
                    str(model_config.get("model") or ""),
                    str(model_config.get("api_key") or ""),
                    messages,
                    stream=True,
                )
            )
            content, output_truncated = self._limit_model_output(_message_visible_content_text(message))
            content = content.strip()
            if not content:
                raise AgentRuntimeError("Native Agent 模型返回了空回复")
            output_metadata = _model_message_metadata(message)
        except Exception as exc:
            terminal = self._terminal_run_or_none(run_id)
            if terminal is not None:
                return str(terminal.get("result") or "")
            safe_error = redact_secrets(exc)
            timeline.append(self._timeline("model.request.failed", safe_error))
            self._update_run(run_id, timeline=timeline)
            self.append_run_event(
                run_id,
                "model.request.failed",
                self.runtime_task_model_events.model_request_failed_payload(safe_error),
            )
            raise
        terminal = self._terminal_run_or_none(run_id)
        if terminal is not None:
            return str(terminal.get("result") or "")
        timeline.append(
            self._timeline(
                "model.output.completed",
                content[:500],
                output_chars=len(content),
                truncated=output_truncated,
            )
        )
        self._update_run(run_id, timeline=timeline)
        self.append_run_event(
            run_id,
            "model.output.completed",
            self.runtime_task_model_events.model_output_completed_payload(
                content,
                truncated=output_truncated,
                metadata=output_metadata,
            ),
        )
        return content

    def _main_chat_workspace_policy(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        if isinstance(policy, dict):
            compiled = self._compile_workspace_policy(policy)
        else:
            workspace = get_workspace_status()
            dirs = workspace.get("dirs") if isinstance(workspace.get("dirs"), dict) else {}
            if workspace.get("initialized") and dirs.get("projects"):
                workdir = Path(str(dirs["projects"]))
            else:
                workdir = self.agent_workspaces_dir / "builtin-yachiyo-main"
            workdir.mkdir(parents=True, exist_ok=True)
            compiled = self._compile_workspace_policy(
                {
                    "default_workdir": str(workdir),
                    "readable_scopes": ["."],
                    "writable_scopes": [],
                }
            )
        if not str(compiled.get("default_workdir") or "").strip():
            workdir = self.agent_workspaces_dir / "builtin-yachiyo-main"
            workdir.mkdir(parents=True, exist_ok=True)
            compiled = {**compiled, "default_workdir": str(workdir)}
        self._trust_workspace_from_policy(compiled, source="main_chat", commit=True)
        return compiled

    def _main_chat_tool_policy(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = policy if isinstance(policy, dict) else {
            "allowed_tools": [
                "workspace.list",
                "workspace.read",
                *_MEMORY_TOOL_NAMES,
                *_FUTURE_TASK_TOOL_NAMES,
                "artifact.write",
            ]
        }
        return self._compile_tool_policy("custom", raw)

    def _main_chat_agent_config(
        self,
        *,
        model_profile_id: str,
        tool_policy: dict[str, Any] | None = None,
        workspace_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "agent_id": _MAIN_CHAT_AGENT_ID,
            "name": "Yachiyo",
            "nickname": "Yachiyo",
            "category": "orchestrator",
            "instructions": "Main chat native agent.",
            "persona_prompt": "",
            "model_mode": "profile",
            "execution_backend": "native_profile",
            "model_profile_id": str(model_profile_id or "").strip(),
            "vision_model_profile_id": "",
            "model_config": {},
            "tool_policy": self._main_chat_tool_policy(tool_policy),
            "workspace_policy": self._main_chat_workspace_policy(workspace_policy),
            "skill_ids": [],
            "output_contract": "chat",
            "enabled": True,
        }

    @staticmethod
    def _main_chat_pending_approval(
        pending_approval: dict[str, Any],
        *,
        model_profile_id: str,
        tool_policy: dict[str, Any],
        workspace_policy: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **pending_approval,
            "resume_kind": "main_chat",
            "model_profile_id": str(model_profile_id or "").strip(),
            "tool_policy": tool_policy,
            "workspace_policy": workspace_policy,
        }

    def execute_main_chat_model_loop(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        *,
        profile_id: str = "",
        tool_policy: dict[str, Any] | None = None,
        workspace_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self.get_run(run_id)
        if str(run.get("kind") or "") != "main_chat_run":
            raise AgentRuntimeError("Run 不是主聊天 Native Run")
        default_profile_id = str(
            profile_id or get_model_profile_service().get_defaults().get("chat") or ""
        ).strip()
        if not default_profile_id:
            raise AgentRuntimeError("native_agent_not_ready:chat_model_profile_required")
        model_config = self._model_profile_config_private(default_profile_id, capability="chat")
        agent = self._main_chat_agent_config(
            model_profile_id=default_profile_id,
            tool_policy=tool_policy,
            workspace_policy=workspace_policy,
        )
        runtime = self._compile_agent_runtime(agent)
        timeline = [event for event in run.get("timeline") or [] if isinstance(event, dict)]
        budget = self._run_budget(run_id, timeline)
        self._check_context_budget(budget, messages)
        timeline.append(
            self.runtime_agent_timeline.compiled(
                detail="Main chat NativeRunEngine compiled tools and workspace policy",
                allowed_tools=runtime["tool_policy"].get("allowed_tools") or [],
            )
        )
        timeline.append(
            self._timeline(
                "model.request.started",
                str(model_config.get("model") or ""),
                profile_id=default_profile_id,
                capability="chat",
            )
        )
        self._update_run(run_id, status="running", timeline=timeline)
        self.append_run_event(
            run_id,
            "model.request.started",
            self.runtime_task_model_events.model_request_started_payload(
                profile_id=default_profile_id,
                model=str(model_config.get("model") or ""),
                capability="chat",
                message_count=len(messages),
            ),
        )
        broker = ToolBroker(
            runtime["workspace_policy"],
            self.agent_artifacts_dir / run_id,
            memory_store=self._memory_store(source_run_id=run_id),
            future_task_store=self._future_task_store(
                source_run_id=run_id,
                default_runnable_id=_MAIN_CHAT_AGENT_ID,
            ),
        )
        artifacts = [item for item in run.get("artifacts") or [] if isinstance(item, dict)]
        try:
            result_text = self._run_custom_api_agent(
                agent,
                "",
                broker,
                timeline,
                artifacts,
                messages=messages,
                run_id=run_id,
                budget=budget,
            )
        except AgentApprovalRequired as exc:
            pending = self._main_chat_pending_approval(
                exc.pending_approval,
                model_profile_id=default_profile_id,
                tool_policy=runtime["tool_policy"],
                workspace_policy=runtime["workspace_policy"],
            )
            return self.approval_pause.project_tool_required(
                run_id,
                pending_approval=pending,
                timeline=timeline,
                artifacts=artifacts,
            )
        except Exception as exc:
            terminal = self._terminal_run_or_none(run_id)
            if terminal is not None:
                return terminal
            safe_error = redact_secrets(exc)
            timeline.append(self._timeline("model.request.failed", safe_error))
            self._update_run(run_id, status="failed", result=safe_error, timeline=timeline, artifacts=artifacts, pending_approval=None)
            self.append_run_event(
                run_id,
                "model.request.failed",
                self.runtime_task_model_events.model_request_failed_payload(safe_error),
            )
            raise
        terminal = self._terminal_run_or_none(run_id)
        if terminal is not None:
            return terminal

        timeline.append(
            self._timeline(
                "model.output.ready",
                result_text[:500],
                output_chars=len(result_text),
                truncated=bool(getattr(result_text, "output_truncated", False)),
            )
        )
        self.append_run_event(
            run_id,
            "model.output.completed",
            self.runtime_task_model_events.model_output_completed_payload(
                str(result_text),
                truncated=bool(getattr(result_text, "output_truncated", False)),
                metadata=_model_output_metadata(result_text),
            ),
        )
        return self._update_run(
            run_id,
            status="running",
            result=result_text,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )

    def complete_main_chat_run(self, run_id: str, result: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        terminal = run if str(run.get("status") or "").strip() in _FINAL_RUN_STATUSES else None
        if terminal is not None:
            return terminal
        safe_result = redact_secrets(result)
        timeline = [
            *[event for event in run.get("timeline") or [] if isinstance(event, dict)],
            self._timeline("run.completed", "Native main chat run completed"),
        ]
        completed = self._update_run(
            run_id,
            status="completed",
            result=safe_result,
            timeline=timeline,
            pending_approval=None,
        )
        link = self.task_run_links.for_run(run_id)
        self.runtime_task_events.completed(
            run_id,
            task_id=str((link or {}).get("task_id") or ""),
            session_id=str((link or {}).get("session_id") or ""),
            result=safe_result,
        )
        return completed

    def fail_main_chat_run(self, run_id: str, error: Any) -> dict[str, Any]:
        run = self.get_run(run_id)
        terminal = run if str(run.get("status") or "").strip() in _FINAL_RUN_STATUSES else None
        if terminal is not None:
            return terminal
        safe_error = redact_secrets(error)
        timeline = [
            *[event for event in run.get("timeline") or [] if isinstance(event, dict)],
            self._timeline("run.failed", safe_error),
        ]
        failed = self._update_run(
            run_id,
            status="failed",
            result=safe_error,
            timeline=timeline,
            pending_approval=None,
        )
        link = self.task_run_links.for_run(run_id)
        self.runtime_task_events.failed(
            run_id,
            task_id=str((link or {}).get("task_id") or ""),
            session_id=str((link or {}).get("session_id") or ""),
            error=safe_error,
        )
        return failed

    def _load_agent_skills(self, skill_ids: list[str]) -> list[dict[str, Any]]:
        skills = []
        for skill_id in skill_ids:
            try:
                skill = self.get_skill(skill_id)
            except KeyError as exc:
                raise AgentRuntimeError(f"Agent 挂载的 Skill 不存在：{skill_id}") from exc
            if not skill.get("enabled", True):
                raise AgentRuntimeError(f"Agent 挂载的 Skill 已停用：{skill.get('name') or skill_id}")
            skills.append(skill)
        return skills

    def _compile_agent_runtime(self, agent: dict[str, Any]) -> dict[str, Any]:
        return self.runtime_policy.compile_agent_runtime(agent)

    def _agent_context(
        self,
        agent: dict[str, Any],
        user_goal: str,
        upstream: str = "",
        *,
        skills: list[dict[str, Any]] | None = None,
    ) -> str:
        return self.agent_context_builder.build(
            agent,
            user_goal,
            upstream,
            skills=skills,
        )

    @staticmethod
    def _agent_workspace_dir(agent: dict[str, Any]) -> str:
        workspace = agent.get("workspace_policy") or {}
        return str(workspace.get("default_workdir") or "").strip()

    def create_agent_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(payload.get("agent_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not agent_id:
            raise AgentRuntimeError("缺少 agent_id")
        if not user_goal:
            raise AgentRuntimeError("运行目标不能为空")
        agent = self._get_agent_private(agent_id)
        self._validate_agent_run_readiness(agent)
        run_group_id = str(payload.get("run_group_id") or "").strip()
        client_request_id = self._client_request_id_from_payload(payload)
        existing = self._run_by_client_request_id(client_request_id)
        if existing is not None:
            return existing
        root_group = False
        with self._db_lock:
            existing = self._run_by_client_request_id(client_request_id)
            if existing is not None:
                return existing
            if run_group_id:
                self.get_run_group(run_group_id)
            else:
                group = self._insert_run_group(
                    title=f"{agent['name']}: {user_goal[:80]}",
                    source=str(payload.get("source") or "agent"),
                    workspace_dir=self._agent_workspace_dir(agent),
                )
                run_group_id = group["run_group_id"]
                root_group = True
            run = self._insert_run(
                kind="agent_run",
                runnable_id=agent_id,
                user_goal=user_goal,
                run_group_id=run_group_id,
                client_request_id=client_request_id,
            )
        result = self._execute_agent_run(
            run["run_id"],
            agent,
            user_goal,
            upstream=str(payload.get("upstream") or ""),
        )
        if root_group:
            result = self._project_agent_run_group_if_root(result)
        return result

    def create_agent_run_async(
        self,
        payload: dict[str, Any],
        on_complete: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> dict[str, Any]:
        """创建 Agent Run 并立即返回，异步执行实际任务。

        Args:
            payload: Agent Run 配置
            on_complete: 执行完成后的回调函数（在后台线程中调用）

        Returns:
            包含 run_id 和 status="processing" 的 run 信息
        """
        agent_id = str(payload.get("agent_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not agent_id:
            raise AgentRuntimeError("缺少 agent_id")
        if not user_goal:
            raise AgentRuntimeError("运行目标不能为空")
        agent = self._get_agent_private(agent_id)
        self._validate_agent_run_readiness(agent)

        run_group_id = str(payload.get("run_group_id") or "").strip()
        root_group = False
        if run_group_id:
            self.get_run_group(run_group_id)
        else:
            group = self._insert_run_group(
                title=f"{agent['name']}: {user_goal[:80]}",
                source=str(payload.get("source") or "agent"),
                workspace_dir=self._agent_workspace_dir(agent),
            )
            run_group_id = group["run_group_id"]
            root_group = True

        run = self._insert_run(kind="agent_run", runnable_id=agent_id, user_goal=user_goal, run_group_id=run_group_id)

        # 立即返回 processing 状态
        result = {
            **run,
            "status": "processing",
            "runnable": self.resolve_runnable(runnable_id=agent_id),
            "agent_run_id": run["run_id"],
        }

        # 启动后台线程执行
        def _execute_in_background() -> None:
            try:
                exec_result = self._execute_agent_run(
                    run["run_id"],
                    agent,
                    user_goal,
                    upstream=str(payload.get("upstream") or ""),
                )
                if root_group:
                    exec_result = self._project_agent_run_group_if_root(exec_result)
                if on_complete:
                    on_complete(exec_result)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "异步 Agent Run 执行失败: %s", exc, exc_info=True
                )
                safe_error = redact_secrets(exc)
                # 更新 run 状态为 failed
                self.runtime_agent_run_events.failed(run["run_id"], safe_error)
                self._update_run(
                    run["run_id"],
                    status="failed",
                    result=safe_error,
                    timeline=[self.runtime_agent_timeline.failed(safe_error)],
                    artifacts=[],
                    pending_approval=None,
                )
                if on_complete:
                    on_complete({
                        **run,
                        "status": "failed",
                        "result": safe_error,
                    })

        thread = threading.Thread(
            target=_execute_in_background,
            name=f"agent-run-{run['run_id'][:8]}",
            daemon=True,
        )
        thread.start()

        return result

    def _execute_agent_run(self, run_id: str, agent: dict[str, Any], user_goal: str, upstream: str = "") -> dict[str, Any]:
        backend = _normalize_execution_backend(agent.get("execution_backend"), model_mode=str(agent.get("model_mode") or "profile"))
        runtime = self._compile_agent_runtime(agent)
        timeline = [
            self.runtime_agent_timeline.started(
                str(agent["name"]),
                backend=backend,
                runtime=runtime["runtime"],
            )
        ]
        self.runtime_agent_run_events.started(
            run_id,
            agent_id=str(agent.get("agent_id") or ""),
            agent_name=str(agent.get("name") or ""),
            backend=backend,
            runtime=runtime["runtime"],
        )
        timeline.append(
            self.runtime_agent_timeline.compiled(
                allowed_tools=runtime["tool_policy"].get("allowed_tools") or [],
            )
        )
        artifact_root = self.agent_artifacts_dir / run_id
        skills = self._load_agent_skills(agent.get("skill_ids") or [])
        context = self._agent_context(agent, user_goal, upstream, skills=skills)
        broker = ToolBroker(
            runtime["workspace_policy"],
            artifact_root,
            skills=skills,
            memory_store=self._memory_store(source_run_id=run_id),
            future_task_store=self._future_task_store(
                source_run_id=run_id,
                default_runnable_id=str(agent.get("agent_id") or ""),
            ),
        )
        artifacts: list[dict[str, Any]] = []
        try:
            retrieved_memories = self._memory_store().list_items(
                include_deleted=False,
                limit=_MEMORY_CONTEXT_LIMIT,
            )
            self.append_run_event(
                run_id,
                "memory.retrieved",
                self.runtime_trace_events.memory_retrieved_payload(retrieved_memories),
            )
            artifact = broker.artifact_write("agent-context.md", context)
            artifacts.append({"kind": "context", **artifact})
            timeline.append(self._timeline("agent.artifact.write", "agent-context.md", artifact=artifact))
            result = self._run_custom_api_agent(agent, context, broker, timeline, artifacts, run_id=run_id)
            result_text = str(result)
            self.append_run_event(
                run_id,
                "model.output.completed",
                self.runtime_task_model_events.model_output_completed_payload(
                    result_text,
                    truncated=bool(getattr(result, "output_truncated", False)),
                    metadata=_model_output_metadata(result),
                ),
            )
            timeline.append(self.runtime_agent_timeline.completed())
            self.runtime_agent_run_events.completed(run_id, result_text)
            return self._update_run(
                run_id,
                status="completed",
                result=result_text,
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=None,
            )
        except AgentApprovalRequired as exc:
            return self.approval_pause.project_tool_required(
                run_id,
                pending_approval=exc.pending_approval,
                timeline=timeline,
                artifacts=artifacts,
            )
        except Exception as exc:
            safe_error = redact_secrets(exc)
            timeline.append(self.runtime_agent_timeline.failed(safe_error))
            self.runtime_agent_run_events.failed(run_id, safe_error)
            return self._update_run(
                run_id,
                status="failed",
                result=safe_error,
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=None,
            )

    def _run_custom_api_agent(
        self,
        agent: dict[str, Any],
        context: str,
        broker: ToolBroker,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        messages: list[dict[str, Any]] | None = None,
        start_iteration: int = 0,
        run_id: str = "",
        budget: _RunBudget | None = None,
    ) -> str:
        model_config = self._agent_model_config_private(agent)
        base_url = str(model_config.get("base_url") or "").rstrip("/")
        model = str(model_config.get("model") or "").strip()
        api_key = str(model_config.get("api_key") or "").strip()
        if not base_url or not model or not api_key:
            raise AgentRuntimeError("Agent 模型 Profile 缺少 base_url、model 或 API Key")
        runtime = self._compile_agent_runtime(agent)
        allowed_tools = runtime["tool_policy"].get("allowed_tools") or []
        if messages is None:
            allowed_tool_text = ", ".join(allowed_tools) or "none"
            memory_tool_guidance = (
                "Use memory.add, memory.replace, and memory.remove only for stable user preferences, durable facts, "
                "task commitments, reusable summaries, or explicit forget/correction requests; never store secrets. "
                if any(tool in allowed_tools for tool in _MEMORY_TOOL_NAMES)
                else ""
            )
            future_task_guidance = (
                "Use future_task.schedule/list/cancel for explicit reminders, follow-up commitments, standing orders, "
                "or recurring summaries; do not schedule hidden future work without user intent. "
                if any(tool in allowed_tools for tool in _FUTURE_TASK_TOOL_NAMES)
                else ""
            )
            system_prompt = (
                "You are running inside Oha-Yachiyo Agent Runtime. "
                "Follow the Agent functional instructions, persona prompt, user goal, and exact output requests. "
                "If those instructions require an exact phrase or format, return exactly that final output. "
                "Return concise final output unless the Agent instructions require otherwise. "
                f"{_MARKET_AGENT_OPERATING_DOCTRINE}\n"
                "Prefer native tool_calls when available. "
                "If the model endpoint does not support tool_calls and a controlled tool is needed, respond as JSON "
                "{\"action\":\"tool\",\"tool\":\"workspace.list\",\"input\":{}}. "
                "Do not request tools that are not listed as allowed. "
                "If no tools are allowed, do not request tools. "
                "Do not request a tool solely because of the output contract; use tools only when the user goal "
                "or an explicit deliverable requires them. "
                f"{memory_tool_guidance}"
                f"{future_task_guidance}"
                "If the user asks not to create, save, write, or modify files, provide the content inline and do "
                "not request file-writing tools. If the user asks not to run or execute commands, do not request "
                "command-execution tools. "
                "Workspace tools only accept paths relative to the configured Default Workdir. Never pass absolute "
                "paths to workspace tools. If a required target is outside that workspace and terminal.run is "
                "allowed, use terminal.run instead. A failed workspace tool call is recoverable: follow its hint "
                "or switch tools instead of stopping or retrying the same invalid path. "
                f"Request at most one high-risk tool per turn.\n\nAllowed tools: {allowed_tool_text}"
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context},
            ]
        budget = budget or self._run_budget(run_id, timeline)
        self._check_context_budget(budget, messages)
        tools = self._tool_schemas(allowed_tools)
        start_iteration = _normalize_tool_iteration(start_iteration)
        for iteration in range(start_iteration, _MAX_AGENT_TOOL_ITERATIONS):
            self._check_context_budget(budget, messages)
            budget.claim_model_call()
            message = _coalesce_model_message(
                _call_model_profile_chat_message(base_url, model, api_key, messages, tools=tools, stream=True)
            )
            content = _message_visible_content_text(message)
            tool_requests = self._tool_requests_from_message(message, content)
            detail = content[:500] if content else ", ".join(request["tool"] for request in tool_requests)[:500]
            timeline.append(self._timeline("agent.model.response", detail))
            if not tool_requests:
                if not content.strip():
                    raise AgentRuntimeError("Native Agent 模型返回了空回复")
                result_text, truncated = self._limit_model_output(content)
                return _ModelOutputText(
                    result_text,
                    metadata=_model_message_metadata(message),
                    truncated=truncated,
                )

            if tool_requests[0].get("protocol") == "tool_calls":
                messages.append(self._assistant_message_for_history(message))
            else:
                messages.append({"role": "assistant", "content": content})
            self._run_tool_requests(
                tool_requests,
                allowed_tools,
                broker,
                messages,
                timeline,
                artifacts,
                next_iteration=iteration + 1,
                run_id=run_id,
                budget=budget,
            )
        artifact_completion = self._tool_loop_limit_artifact_completion(timeline, artifacts)
        if artifact_completion:
            timeline.append(
                self._timeline(
                    "agent.tool.loop_limit_completed",
                    "artifact.write completed before model final output",
                    artifact_paths=[
                        str(artifact.get("path") or "")
                        for artifact in artifacts
                        if artifact.get("kind") != "context" and str(artifact.get("path") or "").strip()
                    ],
                    loop_limit_detail=self._tool_loop_limit_detail(timeline),
                )
            )
            return artifact_completion
        raise AgentRuntimeError(f"custom_api Agent 工具循环超过上限；{self._tool_loop_limit_detail(timeline)}")

    @staticmethod
    def _tool_loop_limit_detail(timeline: list[dict[str, Any]]) -> str:
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

    @staticmethod
    def _tool_loop_limit_artifact_completion(timeline: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> str | None:
        last_tool_event = next((event for event in reversed(timeline) if event.get("event") == "agent.tool.call"), None)
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
            f"{NativeRunEngine._tool_loop_limit_detail(timeline)}"
        )

    @staticmethod
    def _fatal_tool_failure_detail(tool_name: str, tool_request: dict[str, Any], tool_result: dict[str, Any]) -> str:
        if tool_name != "terminal.run":
            return ""
        if tool_result.get("ok") or tool_result.get("approval_required") or tool_result.get("blocked_by_user_goal"):
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

    @staticmethod
    def _assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
        content = message.get("content")
        history = {"role": "assistant", "content": content if content not in (None, "") else None}
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            history["tool_calls"] = tool_calls
        return history

    @staticmethod
    def _append_tool_result_message(messages: list[dict[str, Any]], tool_request: dict[str, Any], tool_result: dict[str, Any]) -> None:
        content = json.dumps(tool_result, ensure_ascii=False)
        if tool_request.get("protocol") == "tool_calls":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tool_request.get("tool_call_id") or ""),
                    "content": content,
                }
            )
            return
        messages.append({"role": "user", "content": f"Tool result for {tool_request['tool']}: {content}"})

    def _run_tool_requests(
        self,
        tool_requests: list[dict[str, Any]],
        allowed_tools: list[str],
        broker: ToolBroker,
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        next_iteration: int,
        run_id: str = "",
        budget: _RunBudget | None = None,
    ) -> None:
        budget = budget or self._run_budget(run_id, timeline)
        user_goal = _user_goal_from_agent_messages(messages)
        for index, tool_request in enumerate(tool_requests):
            tool_name = _normalize_tool_name(tool_request.get("tool"))
            raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
            input_preview = _tool_input_preview(raw_input)
            goal_block_reason = _agent_goal_disallows_tool(user_goal, tool_name)
            if goal_block_reason:
                budget.claim_tool_call(tool_name)
                tool_result = {
                    "ok": False,
                    "blocked_by_user_goal": True,
                    "tool": tool_name,
                    "error": goal_block_reason,
                    "hint": "Do not ask for approval. Continue with an inline answer that follows the user's stated constraint.",
                }
                timeline.append(self._timeline("agent.tool.skipped", tool_name, input_preview=input_preview, result=tool_result))
                if run_id:
                    self.append_run_event(
                        run_id,
                        "agent.tool.skipped",
                        {"tool": tool_name, "input_preview": input_preview, "result": tool_result},
                    )
                self._append_tool_result_message(messages, {**tool_request, "tool": tool_name}, tool_result)
                continue
            tool_result = self._call_agent_tool(
                tool_request,
                allowed_tools,
                broker,
                timeline,
                artifacts=artifacts,
                run_id=run_id,
                budget=budget,
            )
            if tool_result.get("approval_required"):
                raise AgentApprovalRequired(
                    self.tool_pending_approvals.build(
                        tool_request,
                        messages=messages,
                        next_iteration=next_iteration,
                        remaining_tool_requests=tool_requests[index + 1 :],
                    )
                )
            fatal_failure = self._fatal_tool_failure_detail(tool_name, tool_request, tool_result)
            if fatal_failure:
                timeline.append(
                    self._timeline(
                        "agent.tool.failed",
                        tool_name,
                        input_preview=input_preview,
                        result=tool_result,
                        status="failed",
                    )
                )
                raise AgentRuntimeError(fatal_failure)
            self._append_tool_result_message(messages, tool_request, tool_result)

    def _call_agent_tool(
        self,
        tool_request: dict[str, Any],
        allowed_tools: list[str],
        broker: ToolBroker,
        timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        approved: bool = False,
        run_id: str = "",
        budget: _RunBudget | None = None,
    ) -> dict[str, Any]:
        tool_name = _normalize_tool_name(tool_request.get("tool"))
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        input_preview = _tool_input_preview(payload)
        budget = budget or self._run_budget(run_id, timeline)
        if not PolicyGate.allows_tool(tool_name, allowed_tools):
            budget.claim_tool_call(tool_name)
            timeline.append(self._timeline("agent.tool.denied", tool_name, input_preview=input_preview))
            self.runtime_tool_call_events.denied(run_id, tool_name, input_preview)
            raise AgentRuntimeError(f"Agent 试图调用未授权工具：{tool_name}")
        self.runtime_tool_call_events.requested(
            run_id,
            tool_name,
            input_preview,
            approved=approved,
        )
        try:
            self._validate_tool_payload(tool_name, payload)
        except AgentRuntimeError as exc:
            self.runtime_tool_call_events.failed(
                run_id,
                tool_name,
                input_preview,
                approved=approved,
                pre_validation=True,
                error=exc,
            )
            raise
        budget.claim_tool_call(tool_name, terminal_execution=tool_name == "terminal.run" and approved)
        self.runtime_tool_call_events.started(
            run_id,
            tool_name,
            input_preview,
            approved=approved,
        )
        try:
            tool_result = broker.call(tool_name, payload, approved=approved)
        except AgentRuntimeError as exc:
            if not tool_name.startswith("workspace."):
                self.runtime_tool_call_events.failed(
                    run_id,
                    tool_name,
                    input_preview,
                    approved=approved,
                    error=exc,
                )
                raise
            terminal_hint = (
                " If the required target is outside the configured workspace, use terminal.run and wait for approval."
                if "terminal.run" in allowed_tools
                else ""
            )
            tool_result = {
                "ok": False,
                "tool": tool_name,
                "error": redact_api_error_text(exc),
                "hint": (
                    "Workspace tools only accept relative paths within the configured Default Workdir. "
                    "Use a valid relative path and do not retry the same invalid path."
                    f"{terminal_hint}"
                ),
                **({"suggested_tool": "terminal.run"} if "terminal.run" in allowed_tools else {}),
            }
        tool_result = self._limit_tool_result(tool_result)
        self.runtime_tool_call_events.result(
            run_id,
            tool_name,
            input_preview,
            tool_result,
            approved=approved,
        )
        timeline.append(self._timeline("agent.tool.call", tool_name, input_preview=input_preview, result=tool_result))
        if run_id:
            self.runtime_tool_call_events.agent_tool_call(
                run_id,
                tool_name,
                input_preview,
                tool_result,
                approved=approved,
            )
            trace_event = self.runtime_trace_events.memory_skill_trace_event(
                tool_name,
                input_preview,
                tool_result,
            )
            if trace_event is not None:
                self.append_run_event(run_id, trace_event["event_type"], trace_event["payload"])
        if artifacts is not None and tool_name == "artifact.write" and tool_result.get("ok"):
            artifact = {"kind": "tool_artifact", **tool_result}
            if artifact not in artifacts:
                artifacts.append(artifact)
            if run_id:
                self.append_run_event(
                    run_id,
                    "artifact.created",
                    self.runtime_trace_events.artifact_created_payload(
                        tool_result,
                        run_id=run_id,
                    ),
                )
        return tool_result

    @staticmethod
    def _validate_tool_payload(tool_name: str, payload: dict[str, Any]) -> None:
        ToolDescriptorRegistry.validate_payload(tool_name, payload)

    @staticmethod
    def _make_pending_approval(
        tool_request: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        next_iteration: int,
        remaining_tool_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return ToolPendingApprovalBuilder(
            approval_id_factory=lambda: f"approval_{uuid4().hex[:12]}",
            now=_now,
        ).build(
            tool_request,
            messages=messages,
            next_iteration=next_iteration,
            remaining_tool_requests=remaining_tool_requests,
        )

    def _tool_requests_from_message(self, message: dict[str, Any], content: str) -> list[dict[str, Any]]:
        return self.tool_request_parser.requests_from_message(message, content)

    @staticmethod
    def _parse_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
        return ToolRequestParser().parse_tool_calls(tool_calls)

    @staticmethod
    def _model_profile_config_private(profile_id: str, *, capability: str) -> dict[str, Any]:
        return RuntimeModelProfileResolver(
            profile_service_factory=lambda: get_model_profile_service(),
            supports_openai_compatible_api=supports_openai_compatible_api,
            default_agent_ids=_DEFAULT_AGENT_IDS,
            error_type=AgentRuntimeError,
        ).model_profile_config_private(profile_id, capability=capability)

    @staticmethod
    def _chat_profile_model_config_private(profile_id: str) -> dict[str, Any]:
        return NativeRunEngine._model_profile_config_private(profile_id, capability="chat")

    def _agent_model_config_private(self, agent: dict[str, Any]) -> dict[str, Any]:
        return self.model_profile_resolver.agent_model_config_private(agent)

    @staticmethod
    def _parse_tool_request(content: str) -> dict[str, Any] | None:
        return ToolRequestParser().parse_json_fallback(content)

    @staticmethod
    def _openai_compatible_chat(base_url: str, model: str, api_key: str, messages: list[dict[str, str]]) -> str:
        url = f"{base_url.rstrip('/')}/chat/completions"
        timeout = read_openai_compatible_chat_timeout()
        body = json.dumps({"model": model, "messages": messages, "temperature": 0.2}).encode("utf-8")
        request = urlrequest.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urlopen_with_bundled_ca(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise AgentRuntimeError(f"custom_api 调用超时：等待响应超过 {timeout:g} 秒") from exc
        except (urlerror.URLError, json.JSONDecodeError) as exc:
            raise AgentRuntimeError(f"custom_api 调用失败：{redact_secrets(exc)}") from exc
        return str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")

    def test_agent_model(self, agent_id: str) -> dict[str, Any]:
        agent = self._get_agent_private(agent_id)
        vision_profile_id = str(agent.get("vision_model_profile_id") or "").strip()
        vision_result: dict[str, Any] | None = None
        if vision_profile_id:
            try:
                vision_result = get_model_profile_service().test_profile(vision_profile_id)
            except KeyError as exc:
                raise AgentRuntimeError("Agent 引用的图片识别 Profile 不存在") from exc
            if not vision_result.get("ok"):
                vision_result["mode"] = "vision_profile"
                return vision_result
        profile_id = str(agent.get("model_profile_id") or "").strip()
        if profile_id:
            try:
                result = get_model_profile_service().test_profile(profile_id)
            except KeyError as exc:
                raise AgentRuntimeError("Agent 引用的模型 Profile 不存在") from exc
            result["mode"] = "profile"
            if result.get("ok") and vision_result:
                result["message"] = f"{result.get('message') or '文本模型测试通过'}；图片识别 Profile 测试通过。"
            return result
        if agent.get("model_mode") == "follow_main" or str(agent.get("agent_id") or "") in _DEFAULT_AGENT_IDS:
            default_profile_id = str(get_model_profile_service().get_defaults().get("chat") or "").strip()
            if default_profile_id:
                try:
                    result = get_model_profile_service().test_profile(default_profile_id)
                except KeyError as exc:
                    raise AgentRuntimeError("默认 Chat Profile 不存在") from exc
                result["mode"] = "follow_main"
                if result.get("ok") and vision_result:
                    result["message"] = f"{result.get('message') or '文本模型测试通过'}；图片识别 Profile 测试通过。"
                return result
        if agent.get("model_mode") != "custom_api":
            return {
                "ok": False,
                "mode": "profile",
                "missing": ["model_profile_id"],
                "message": "请选择已通过测试的 Agent 文本模型 Profile。",
            }
        model_config = agent.get("model_config") or {}
        missing = [
            key
            for key in ("base_url", "model", "api_key")
            if not str(model_config.get(key) or "").strip()
        ]
        if missing:
            return {"ok": False, "missing": missing, "message": "custom_api 配置不完整。"}
        started = time.time()
        try:
            result = self._openai_compatible_chat(
                str(model_config["base_url"]).rstrip("/"),
                str(model_config["model"]),
                str(model_config["api_key"]),
                [{"role": "user", "content": "Reply with OK."}],
            )
        except AgentRuntimeError as exc:
            return {"ok": False, "message": redact_api_error_text(exc)}
        return {
            "ok": True,
            "latency_ms": int((time.time() - started) * 1000),
            "message": result[:500] or "OK",
        }

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow_id = str(payload.get("workflow_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not workflow_id:
            raise AgentRuntimeError("缺少 workflow_id")
        if not user_goal:
            raise AgentRuntimeError("运行目标不能为空")
        workflow = self.get_workflow(workflow_id)
        if not workflow.get("enabled", True):
            raise AgentRuntimeError("Workflow 已停用")
        self.validate_workflow(workflow["nodes"], workflow["edges"])
        self._validate_workflow_agent_nodes(workflow["nodes"])
        self._validate_workflow_subworkflow_nodes(workflow["nodes"], parent_workflow_id=workflow_id)
        self._validate_workflow_runnable_steps(workflow["nodes"])
        self._validate_workflow_agent_run_readiness(workflow["nodes"])
        run_group_id = str(payload.get("run_group_id") or "").strip()
        client_request_id = self._client_request_id_from_payload(payload)
        existing = self._run_by_client_request_id(client_request_id)
        if existing is not None:
            return existing
        root_group = False
        with self._db_lock:
            existing = self._run_by_client_request_id(client_request_id)
            if existing is not None:
                return existing
            if run_group_id:
                self.get_run_group(run_group_id)
            else:
                group = self._insert_run_group(
                    title=f"{workflow['name']}: {user_goal[:80]}",
                    source=str(payload.get("source") or "workflow"),
                    workspace_dir="",
                )
                run_group_id = group["run_group_id"]
                root_group = True
            run = self._insert_run(
                kind="workflow_run",
                runnable_id=workflow_id,
                user_goal=user_goal,
                run_group_id=run_group_id,
                client_request_id=client_request_id,
            )
        timeline, started_payload = self.workflow_run_start_projector.started_projection(workflow_id, workflow)
        self.append_run_event(
            run["run_id"],
            "workflow.run.started",
            started_payload,
        )
        artifacts: list[dict[str, Any]] = []
        context = user_goal
        return self._continue_workflow_run(
            run,
            workflow,
            context=context,
            timeline=timeline,
            artifacts=artifacts,
            start_index=0,
            root_group=root_group,
        )

    def create_workflow_run_async(
        self,
        payload: dict[str, Any],
        on_complete: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> dict[str, Any]:
        workflow_id = str(payload.get("workflow_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not workflow_id:
            raise AgentRuntimeError("缺少 workflow_id")
        if not user_goal:
            raise AgentRuntimeError("运行目标不能为空")
        workflow = self.get_workflow(workflow_id)
        if not workflow.get("enabled", True):
            raise AgentRuntimeError("Workflow 已停用")
        self.validate_workflow(workflow["nodes"], workflow["edges"])
        self._validate_workflow_agent_nodes(workflow["nodes"])
        self._validate_workflow_subworkflow_nodes(workflow["nodes"], parent_workflow_id=workflow_id)
        self._validate_workflow_runnable_steps(workflow["nodes"])
        self._validate_workflow_agent_run_readiness(workflow["nodes"])

        run_group_id = str(payload.get("run_group_id") or "").strip()
        root_group = False
        if run_group_id:
            self.get_run_group(run_group_id)
        else:
            group = self._insert_run_group(
                title=f"{workflow['name']}: {user_goal[:80]}",
                source=str(payload.get("source") or "workflow"),
                workspace_dir="",
            )
            run_group_id = group["run_group_id"]
            root_group = True

        run = self._insert_run(kind="workflow_run", runnable_id=workflow_id, user_goal=user_goal, run_group_id=run_group_id)
        timeline, started_payload = self.workflow_run_start_projector.started_projection(workflow_id, workflow)
        self.append_run_event(
            run["run_id"],
            "workflow.run.started",
            started_payload,
        )
        run = self._update_run(
            run["run_id"],
            status="running",
            timeline=timeline,
            artifacts=[],
            pending_approval=None,
        )
        result = {
            **run,
            "status": "processing",
            "workflow_run_id": run["run_id"],
            "runnable": self.resolve_runnable(runnable_id=workflow_id),
        }

        def _execute_in_background() -> None:
            try:
                exec_result = self._continue_workflow_run(
                    run,
                    workflow,
                    context=user_goal,
                    timeline=list(timeline),
                    artifacts=[],
                    start_index=0,
                    root_group=root_group,
                )
                if on_complete:
                    on_complete(exec_result)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "异步 Workflow Run 执行失败: %s", exc, exc_info=True
                )
                failed = self.workflow_continuation.project_background_failure(
                    run,
                    timeline=timeline,
                    error=exc,
                    root_group=root_group,
                )
                if on_complete:
                    on_complete(failed)

        thread = threading.Thread(
            target=_execute_in_background,
            name=f"workflow-run-{run['run_id'][:8]}",
            daemon=True,
        )
        thread.start()

        return result

    def _workflow_parent_runs_waiting_for_child(
        self,
        child_run: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self.workflow_parent_locator.parent_runs_waiting_for_child(child_run)

    def _workflow_resume_start_index(
        self,
        workflow: dict[str, Any],
        workflow_run: dict[str, Any],
        child_run_id: str,
    ) -> int | None:
        return self.workflow_resume_planner.resume_start_index(
            workflow,
            workflow_run,
            child_run_id,
        )

    def _workflow_run_is_group_root(self, workflow_run: dict[str, Any]) -> bool:
        return self.workflow_parent_locator.workflow_run_is_group_root(workflow_run)

    @staticmethod
    def _workflow_child_artifact_refs(child_run: dict[str, Any], label: str) -> list[dict[str, Any]]:
        return WorkflowChildOutcomeCoordinator.child_artifact_refs(child_run, label)

    @staticmethod
    def _workflow_child_node_context(
        timeline: list[dict[str, Any]],
        child_run: dict[str, Any],
    ) -> tuple[str, dict[str, str]]:
        return WorkflowChildOutcomeCoordinator.child_node_context(timeline, child_run)

    def _merge_workflow_child_run_outcome(
        self,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        child_run: dict[str, Any],
        label: str,
    ) -> None:
        self.workflow_child_outcomes.merge_child_run_outcome(
            timeline,
            artifacts,
            child_run,
            label,
        )

    @staticmethod
    def _workflow_artifact_path(label: str, artifacts: list[dict[str, Any]], configured_path: str = "") -> str:
        return WorkflowPathPlanner.artifact_path(label, artifacts, configured_path)

    def _resume_parent_workflows_after_child_update(self, child_run: dict[str, Any]) -> None:
        self.workflow_parent_resume.resume_after_child_update(child_run)

    def _mark_parent_workflows_child_running(self, child_run: dict[str, Any]) -> None:
        self.workflow_parent_resume.mark_child_running(child_run)

    def _resume_parent_workflow_after_child_update(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
    ) -> dict[str, Any]:
        return self.workflow_parent_resume.resume_parent_after_child_update(workflow_run, child_run)

    def _continue_workflow_run(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        *,
        context: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        start_index: int,
        root_group: bool,
        start_node_id: str = "",
    ) -> dict[str, Any]:
        return self.workflow_continuation.continue_run(
            run,
            workflow,
            context=context,
            timeline=timeline,
            artifacts=artifacts,
            start_index=start_index,
            root_group=root_group,
            start_node_id=start_node_id,
        )

    def _workflow_path(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        return self.workflow_path_planner.workflow_path(workflow)

    def _workflow_nodes_by_id(self, workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return self.workflow_path_planner.nodes_by_id(workflow)

    def _workflow_next_node_id(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any] | str,
        context: str,
    ) -> str:
        if isinstance(node, str):
            node = self._workflow_nodes_by_id(workflow).get(node) or {}
        if not node:
            return ""
        return self.workflow_path_planner.next_node_id(workflow, node, context)

    def _workflow_condition_selection(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
    ) -> dict[str, Any]:
        return self.workflow_path_planner.condition_selection(workflow, node, context)

    def _workflow_parallel_plan(self, workflow: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
        return self.workflow_path_planner.parallel_plan(workflow, node)

    def _workflow_loop_selection(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
        *,
        previous_iterations: int = 0,
    ) -> dict[str, Any]:
        return self.workflow_path_planner.loop_selection(
            workflow,
            node,
            context,
            previous_iterations=previous_iterations,
        )

    def _workflow_loop_step_limit(self, workflow: dict[str, Any]) -> int:
        return self.workflow_path_planner.loop_step_limit(workflow)

    def _workflow_loop_iterations_from_timeline(self, timeline: list[dict[str, Any]]) -> dict[str, int]:
        return self.workflow_path_planner.loop_iterations_from_timeline(timeline)

    @staticmethod
    def _workflow_node_task(node: dict[str, Any]) -> str:
        return WorkflowPathPlanner.node_task(node)

    @staticmethod
    def _workflow_approval_criteria(node: dict[str, Any]) -> str:
        return WorkflowPathPlanner.approval_criteria(node)

    @staticmethod
    def _workflow_child_goal(workflow_goal: str, step_task: str) -> str:
        return WorkflowPathPlanner.child_goal(workflow_goal, step_task)

    def _workflow_path_snapshot(self, workflow: dict[str, Any]) -> list[dict[str, str]]:
        return self.workflow_path_planner.path_snapshot(workflow)

    @staticmethod
    def _workflow_runtime_snapshot(workflow: dict[str, Any]) -> dict[str, Any]:
        return WorkflowPathPlanner.runtime_snapshot(workflow)

    def _workflow_for_run_resume(self, workflow_run: dict[str, Any]) -> dict[str, Any]:
        return self.workflow_resume_planner.workflow_for_run_resume(workflow_run)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        clean_run_id = str(run_id or "").strip()
        with self._run_cancel_locks_guard:
            lock = self._run_cancel_locks.setdefault(clean_run_id, threading.RLock())
        try:
            with lock:
                return self._cancel_run_once(clean_run_id)
        finally:
            with self._run_cancel_locks_guard:
                if self._run_cancel_locks.get(clean_run_id) is lock:
                    self._run_cancel_locks.pop(clean_run_id, None)

    def _cancel_workflow_run_projection(
        self,
        run_id: str,
        run: dict[str, Any],
        timeline: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        return self.workflow_cancellation.project_cancelled_workflow_run(run_id, run, timeline)

    def _cancel_run_once(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] in _FINAL_RUN_STATUSES:
            return run
        timeline = [*run["timeline"]]
        if run.get("kind") == "workflow_run":
            workflow_timeline, artifacts, result_text = self._cancel_workflow_run_projection(run_id, run, timeline)
            projection = RunCancellationProjection.workflow(workflow_timeline, artifacts, result_text)
        else:
            projection = RunCancellationProjection.plain(timeline, self._timeline)
        result = self._update_run(
            run_id,
            **projection.update_fields(),
        )
        cancel_event_type = "workflow.run.cancelled" if result.get("kind") == "workflow_run" else "run.cancelled"
        self.append_run_event(
            run_id,
            cancel_event_type,
            {
                "kind": result.get("kind"),
                "result": result.get("result") or "",
                "status": "cancelled",
            },
        )
        if result.get("kind") == "workflow_run" and self._workflow_run_is_group_root(result):
            projected = self._project_cancelled_workflow_group_if_root(run, result)
            self._resume_parent_workflows_after_child_update(projected)
            return projected
        return self._project_child_run_transition(result)

    def _tool_approval_resume_context(
        self,
        run: dict[str, Any],
        pending: dict[str, Any],
        *,
        runtime: dict[str, Any],
        skills: list[dict[str, Any]] | None = None,
    ) -> ToolApprovalResumeContext:
        run_id = str(run["run_id"])
        return ToolApprovalResumeContext.from_run(
            run,
            pending,
            broker=ToolBroker(
                runtime["workspace_policy"],
                self.agent_artifacts_dir / run_id,
                skills=skills,
                memory_store=self._memory_store(source_run_id=run_id),
                future_task_store=self._future_task_store(
                    source_run_id=run_id,
                    default_runnable_id=str((run.get("runnable_id") or _MAIN_CHAT_AGENT_ID)),
                ),
            ),
            allowed_tools=runtime["tool_policy"].get("allowed_tools") or [],
            budget_factory=lambda context_run_id, context_timeline: self._run_budget(
                context_run_id,
                context_timeline,
            ),
        )

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        clean_run_id = str(run_id or "").strip()
        with self._approval_execution_lock:
            run = self.get_run(clean_run_id)
            if run["status"] != "approval_required":
                return run
            if clean_run_id in self._approval_execution_in_progress:
                return run
            self._approval_execution_in_progress.add(clean_run_id)
        try:
            return self._approve_run_approval_once(run)
        finally:
            with self._approval_execution_lock:
                self._approval_execution_in_progress.discard(clean_run_id)

    def _approve_run_approval_once(self, run: dict[str, Any]) -> dict[str, Any]:
        run_id = str(run["run_id"])
        if run["status"] != "approval_required":
            return run
        if run["kind"] == "workflow_run":
            return self._approve_workflow_run_approval(run)
        if run["kind"] == "main_chat_run":
            return self._approve_main_chat_run_approval(run)
        if run["kind"] != "agent_run":
            raise AgentRuntimeError("当前只支持恢复 Agent Run 的工具审批")
        pending = self.runs.pending_approval_private(run_id)
        if not pending:
            raise AgentRuntimeError("Run 缺少待审批工具信息")
        agent = self._get_agent_private(str(run["runnable_id"]))
        runtime = self._compile_agent_runtime(agent)
        skills = self._load_agent_skills(agent.get("skill_ids") or [])
        resume_context = self._tool_approval_resume_context(
            run,
            pending,
            runtime=runtime,
            skills=skills,
        )
        return self._resume_approved_tool_run(
            run_id=run_id,
            pending=pending,
            resume_context=resume_context,
            agent=agent,
            resumed_detail="Agent resumed after approval",
            running_result="已批准，Agent 正在继续执行",
            project_running=self._project_agent_approval_resume_running,
            project_completed=self._project_agent_approval_resume_completed,
            project_result=self._project_child_run_transition,
            redact_error=redact_secrets,
        )

    def _resume_approved_tool_run(
        self,
        *,
        run_id: str,
        pending: dict[str, Any],
        resume_context: ToolApprovalResumeContext,
        agent: dict[str, Any],
        resumed_detail: str,
        running_result: str,
        project_completed: Any,
        project_running: Any | None = None,
        project_required: Any | None = None,
        project_result: Any | None = None,
        redact_error: Any = redact_api_error_text,
    ) -> dict[str, Any]:
        return self.approval_resume.resume_approved_tool_run(
            run_id=run_id,
            pending=pending,
            context=resume_context,
            agent=agent,
            resumed_detail=resumed_detail,
            running_result=running_result,
            project_completed=project_completed,
            project_required=self._project_approval_resume_required,
            project_failed=self._project_approval_resume_failed,
            get_current_run=self.get_run,
            project_running=project_running,
            prepare_required=project_required,
            project_result=project_result,
            redact_error=redact_error,
        )

    def _project_agent_approval_resume_running(self, running: dict[str, Any]) -> dict[str, Any]:
        return self.approval_resume_projection.project_agent_running(running)

    def _project_agent_approval_resume_completed(
        self,
        context: ToolApprovalResumeContext,
        result_text: str,
    ) -> dict[str, Any]:
        return self.approval_resume_projection.project_agent_completed(context, result_text)

    def _project_main_chat_approval_resume_completed(
        self,
        context: ToolApprovalResumeContext,
        result_text: str,
    ) -> dict[str, Any]:
        return self.approval_resume_projection.project_main_chat_completed(context, result_text)

    def _project_approval_resume_required(
        self,
        context: ToolApprovalResumeContext,
        pending_approval: dict[str, Any],
    ) -> dict[str, Any]:
        return self.approval_resume_projection.project_required(context, pending_approval)

    def _project_approval_resume_failed(
        self,
        context: ToolApprovalResumeContext,
        safe_error: str,
    ) -> dict[str, Any]:
        return self.approval_resume_projection.project_failed(context, safe_error)

    def _approve_main_chat_run_approval(self, run: dict[str, Any]) -> dict[str, Any]:
        run_id = str(run["run_id"])
        pending = self.runs.pending_approval_private(run_id)
        if not pending:
            raise AgentRuntimeError("Run 缺少待审批工具信息")
        model_profile_id = str(pending.get("model_profile_id") or "").strip()
        if not model_profile_id:
            model_profile_id = str(get_model_profile_service().get_defaults().get("chat") or "").strip()
        if not model_profile_id:
            raise AgentRuntimeError("native_agent_not_ready:chat_model_profile_required")
        tool_policy = pending.get("tool_policy") if isinstance(pending.get("tool_policy"), dict) else {"allowed_tools": []}
        workspace_policy = pending.get("workspace_policy") if isinstance(pending.get("workspace_policy"), dict) else None
        agent = self._main_chat_agent_config(
            model_profile_id=model_profile_id,
            tool_policy=tool_policy,
            workspace_policy=workspace_policy,
        )
        runtime = self._compile_agent_runtime(agent)
        resume_context = self._tool_approval_resume_context(run, pending, runtime=runtime)
        return self._resume_approved_tool_run(
            run_id=run_id,
            pending=pending,
            resume_context=resume_context,
            agent=agent,
            resumed_detail="Main chat resumed after approval",
            running_result="已批准，Yachiyo 正在继续执行",
            project_completed=self._project_main_chat_approval_resume_completed,
            project_required=lambda pending_approval: self._main_chat_pending_approval(
                pending_approval,
                model_profile_id=model_profile_id,
                tool_policy=runtime["tool_policy"],
                workspace_policy=runtime["workspace_policy"],
            ),
            redact_error=redact_api_error_text,
        )

    def _approve_workflow_run_approval(self, run: dict[str, Any]) -> dict[str, Any]:
        run_id = str(run["run_id"])
        pending = self.runs.pending_approval_private(run_id)
        resume_context = WorkflowApprovalResumeContext.from_run(
            run,
            pending,
            workflow=self._workflow_for_run_resume(run),
            root_group=self._workflow_run_is_group_root(run),
        )
        return self.workflow_approval_resume.resume_after_approval(
            run,
            pending,
            resume_context,
        )

    def _project_cancelled_workflow_group_if_root(
        self,
        run: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return self.run_transition_projection.project_cancelled_workflow_group_if_root(run, result)

    def _project_child_run_transition(self, result: dict[str, Any]) -> dict[str, Any]:
        return self.run_transition_projection.project_child_run_transition(result)

    def _project_agent_run_group_if_root(self, result: dict[str, Any]) -> dict[str, Any]:
        return self.run_transition_projection.project_agent_run_group_if_root(result)

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "approval_required":
            return run
        if run["kind"] == "workflow_run":
            pending = self.runs.pending_approval_private(run_id)
            approval_context = WorkflowApprovalTransitionContext.from_pending(pending)
            result = self.approvals.reject_workflow_node(
                run_id,
                timeline=[*run["timeline"]],
                reason=reason,
                workflow_node_id=approval_context.workflow_node_id,
                label=approval_context.label,
                criteria=approval_context.criteria,
                input_preview=approval_context.input_preview,
            )
            return self._project_cancelled_workflow_group_if_root(run, result)
        pending = self.runs.pending_approval_private(run_id)
        approval_context = ToolApprovalTransitionContext.from_pending(pending)
        result = self.approvals.reject_tool_run(
            run_id,
            timeline=[*run["timeline"]],
            reason=reason,
            tool_name=approval_context.tool_name,
            input_preview=approval_context.input_preview,
        )
        return self._project_child_run_transition(result)

    def timeout_run_approval(self, run_id: str, reason: str = "approval_wait_timeout") -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "approval_required":
            return run
        if run["kind"] == "workflow_run":
            pending = self.runs.pending_approval_private(run_id)
            if not pending or str(pending.get("tool") or "") != "workflow.approval":
                return self.cancel_run(run_id)
            approval_context = WorkflowApprovalTransitionContext.from_pending(pending)
            result = self.approvals.timeout_workflow_node(
                run_id,
                timeline=[*run["timeline"]],
                reason=reason,
                workflow_node_id=approval_context.workflow_node_id,
                label=approval_context.label,
                criteria=approval_context.criteria,
                input_preview=approval_context.input_preview,
            )
            return self._project_cancelled_workflow_group_if_root(run, result)
        pending = self.runs.pending_approval_private(run_id)
        approval_context = ToolApprovalTransitionContext.from_pending(pending)
        result = self.approvals.timeout_tool_run(
            run_id,
            timeline=[*run["timeline"]],
            reason=reason,
            tool_name=approval_context.tool_name,
            input_preview=approval_context.input_preview,
        )
        return self._project_child_run_transition(result)

    def _update_agent_run_group_if_root(self, run: dict[str, Any]) -> None:
        run_group_id = str(run.get("run_group_id") or "")
        if not run_group_id:
            return
        try:
            group = self.get_run_group(run_group_id)
        except KeyError:
            return
        child_run_ids = [str(item) for item in group.get("child_run_ids") or [] if str(item)]
        if group.get("source") in {"agent", "delegation"} or child_run_ids == [run.get("run_id")]:
            self._update_run_group(run_group_id, status=str(run.get("status") or ""), summary=str(run.get("result") or ""))

    def list_runnables(self) -> dict[str, Any]:
        agents = self.list_agents()["agents"]
        workflows = self.list_workflows()["workflows"]
        return {
            "ok": True,
            "runnables": [
                self._agent_runnable_summary(agent)
                for agent in agents
            ]
            + [
                self._workflow_runnable_summary(workflow)
                for workflow in workflows
            ],
        }

    @staticmethod
    def _agent_runnable_summary(agent: dict[str, Any]) -> dict[str, Any]:
        tool_policy = agent.get("tool_policy") if isinstance(agent.get("tool_policy"), dict) else {}
        allowed_tools = tool_policy.get("allowed_tools") if isinstance(tool_policy.get("allowed_tools"), list) else []
        approval_required = (
            tool_policy.get("approval_required")
            if isinstance(tool_policy.get("approval_required"), dict)
            else {}
        )
        return {
            "id": agent["agent_id"],
            "name": agent["name"],
            "nickname": agent.get("nickname") or agent["name"],
            "description": agent.get("description") or "",
            "avatar_url": agent.get("avatar_url") or "",
            "category": agent.get("category") or "custom",
            "output_contract": agent.get("output_contract") or "chat",
            "kind": "agent",
            "enabled": agent["enabled"],
            "tool_policy": {
                "allowed_tools": [str(item) for item in allowed_tools if str(item)],
                "approval_required": {
                    str(tool): bool(required)
                    for tool, required in approval_required.items()
                    if str(tool)
                },
            },
        }

    def _workflow_participants(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        participants: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for node in workflow.get("nodes") or []:
            if self._node_kind(node) != "agent":
                continue
            data = node.get("data") or {}
            agent_id = str(data.get("agent_id") or data.get("agentId") or "").strip()
            if not agent_id or agent_id in seen_ids:
                continue
            try:
                agent = self.get_agent(agent_id)
            except KeyError:
                continue
            seen_ids.add(agent_id)
            participants.append(self._agent_runnable_summary(agent))
        return participants

    def _workflow_runnable_summary(self, workflow: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": workflow["workflow_id"],
            "name": workflow["name"],
            "description": workflow.get("description") or "",
            "kind": "workflow",
            "enabled": workflow["enabled"],
            "participants": self._workflow_participants(workflow),
        }

    def list_delegation_targets(self) -> dict[str, Any]:
        agents = [
            {
                "kind": "agent",
                "id": agent["agent_id"],
                "name": agent["name"],
                "description": agent.get("description") or "",
                "category": agent.get("category") or "custom",
                "output_contract": agent.get("output_contract") or "chat",
            }
            for agent in self.list_agents()["agents"]
            if agent.get("enabled", True) and not agent.get("system")
        ]
        workflows = [
            {
                "kind": "workflow",
                "id": workflow["workflow_id"],
                "name": workflow["name"],
                "description": workflow.get("description") or "",
                "nodes": len(workflow.get("nodes") or []),
                "output_contract": "workflow",
            }
            for workflow in self.list_workflows()["workflows"]
            if workflow.get("enabled", True)
        ]
        return {"ok": True, "agents": agents, "workflows": workflows}

    def resolve_runnable(self, *, runnable_id: str = "", name: str = "") -> dict[str, Any] | None:
        self._ensure_row_factory()
        clean_id = str(runnable_id or "").strip()
        if clean_id == _MAIN_CHAT_AGENT_ID:
            return self._agent_runnable_summary(self._main_chat_virtual_agent())
        if runnable_id:
            agent = self._conn.execute("SELECT * FROM agents WHERE agent_id=?", (runnable_id,)).fetchone()
            if agent:
                return self._agent_runnable_summary(self._row_to_agent(agent))
            workflow = self._conn.execute("SELECT * FROM workflows WHERE workflow_id=?", (runnable_id,)).fetchone()
            if workflow:
                return self._workflow_runnable_summary(self._row_to_workflow(workflow))
        clean_name = (name or "").strip()
        if clean_name:
            if clean_name.lower() == "yachiyo":
                return self._agent_runnable_summary(self._main_chat_virtual_agent())
            agents = self._conn.execute(
                "SELECT * FROM agents WHERE LOWER(name)=LOWER(?) OR LOWER(nickname)=LOWER(?)",
                (clean_name, clean_name),
            ).fetchall()
            workflow = self._conn.execute("SELECT * FROM workflows WHERE LOWER(name)=LOWER(?)", (clean_name,)).fetchone()
            matches = [*agents, *([workflow] if workflow is not None else [])]
            if len(matches) > 1:
                raise AgentRuntimeError("Agent/Workflow 名称不唯一")
            if agents:
                return self._agent_runnable_summary(self._row_to_agent(agents[0]))
            if workflow:
                return self._workflow_runnable_summary(self._row_to_workflow(workflow))
        return None

    def create_run_for_runnable(
        self,
        *,
        runnable_id: str = "",
        name: str = "",
        user_goal: str = "",
        run_group_id: str = "",
        upstream: str = "",
        client_run_id: str = "",
        client_request_id: str = "",
    ) -> dict[str, Any]:
        runnable = self.resolve_runnable(runnable_id=runnable_id, name=name)
        if runnable is None:
            raise AgentRuntimeError("未找到指定 Agent 或 Workflow")
        if not runnable.get("enabled", True):
            raise AgentRuntimeError("指定 Agent 或 Workflow 已停用")
        request_id = client_run_id or client_request_id
        if runnable["kind"] == "agent":
            run = self.create_agent_run({
                "agent_id": runnable["id"],
                "user_goal": user_goal,
                "source": "agent",
                "run_group_id": run_group_id,
                "upstream": upstream,
                "client_run_id": request_id,
            })
            run["agent_run_id"] = run["run_id"]
            run["runnable"] = runnable
            return run
        run = self.create_workflow_run({
            "workflow_id": runnable["id"],
            "user_goal": user_goal,
            "source": "workflow",
            "run_group_id": run_group_id,
            "client_run_id": request_id,
        })
        run["workflow_run_id"] = run["run_id"]
        run["runnable"] = runnable
        return run

    def create_run_for_runnable_async(
        self,
        *,
        runnable_id: str = "",
        name: str = "",
        user_goal: str = "",
        run_group_id: str = "",
        upstream: str = "",
        on_complete: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> dict[str, Any]:
        """创建 Run 并立即返回，异步执行实际任务。"""
        runnable = self.resolve_runnable(runnable_id=runnable_id, name=name)
        if runnable is None:
            raise AgentRuntimeError("未找到指定 Agent 或 Workflow")
        if not runnable.get("enabled", True):
            raise AgentRuntimeError("指定 Agent 或 Workflow 已停用")

        if runnable["kind"] == "agent":
            run = self.create_agent_run_async(
                {
                    "agent_id": runnable["id"],
                    "user_goal": user_goal,
                    "source": "agent",
                    "run_group_id": run_group_id,
                    "upstream": upstream,
                },
                on_complete=on_complete,
            )
            run["agent_run_id"] = run["run_id"]
            run["runnable"] = runnable
            return run

        run = self.create_workflow_run_async(
            {
                "workflow_id": runnable["id"],
                "user_goal": user_goal,
                "source": "workflow",
                "run_group_id": run_group_id,
            },
            on_complete=on_complete,
        )
        run["workflow_run_id"] = run["run_id"]
        run["runnable"] = runnable
        return run

    def rerun_run(self, run_id: str) -> dict[str, Any]:
        original = self.get_run(run_id)
        original_status = str(original.get("status") or "")
        if original_status not in _FINAL_RUN_STATUSES:
            raise AgentRuntimeError("当前 Run 还在进行中，不能重跑")
        user_goal = str(original.get("user_goal") or "").strip()
        if not user_goal:
            raise AgentRuntimeError("原 Run 没有记录任务目标，无法重跑")
        kind = str(original.get("kind") or "")
        runnable_id = str(original.get("runnable_id") or "")
        if kind == "agent_run":
            rerun = self.create_agent_run(
                {
                    "agent_id": runnable_id,
                    "user_goal": user_goal,
                    "source": "rerun",
                }
            )
            rerun_key = "agent_run_id"
        elif kind == "workflow_run":
            rerun = self.create_workflow_run(
                {
                    "workflow_id": runnable_id,
                    "user_goal": user_goal,
                    "source": "rerun",
                }
            )
            rerun_key = "workflow_run_id"
        else:
            raise AgentRuntimeError("不支持重跑这个 Run 类型")

        rerun_event = self._timeline(
            "run.rerun.started",
            f"Rerun of {original.get('runnable_name') or runnable_id}",
            rerun_of_run_id=str(original.get("run_id") or ""),
            rerun_of_kind=kind,
            rerun_of_status=original_status,
            rerun_of_runnable_id=runnable_id,
            rerun_of_runnable_name=str(original.get("runnable_name") or ""),
            original_created_at=str(original.get("created_at") or ""),
            original_updated_at=str(original.get("updated_at") or ""),
            input_preview={
                "original_run_id": str(original.get("run_id") or ""),
                "original_status": original_status,
                "original_target": str(original.get("runnable_name") or runnable_id),
                "original_goal": user_goal,
            },
        )
        self.append_run_event(
            str(rerun["run_id"]),
            "run.rerun.started",
            {
                "rerun_of_run_id": str(original.get("run_id") or ""),
                "rerun_of_kind": kind,
                "rerun_of_status": original_status,
                "rerun_of_runnable_id": runnable_id,
                "rerun_of_runnable_name": str(original.get("runnable_name") or ""),
                "original_created_at": str(original.get("created_at") or ""),
                "original_updated_at": str(original.get("updated_at") or ""),
                "input_preview": {
                    "original_run_id": str(original.get("run_id") or ""),
                    "original_status": original_status,
                    "original_target": str(original.get("runnable_name") or runnable_id),
                    "original_goal": user_goal,
                },
            },
        )
        updated = self._update_run(
            str(rerun["run_id"]),
            timeline=[rerun_event, *[event for event in rerun.get("timeline") or [] if isinstance(event, dict)]],
        )
        updated[rerun_key] = updated["run_id"]
        updated["runnable"] = self.resolve_runnable(runnable_id=runnable_id)
        return updated

    def delegate_runnable(
        self,
        *,
        kind: str = "",
        runnable_id: str = "",
        name: str = "",
        user_goal: str = "",
    ) -> dict[str, Any]:
        goal = str(user_goal or "").strip()
        if not goal:
            raise AgentRuntimeError("委派目标不能为空")
        runnable = self.resolve_runnable(runnable_id=runnable_id, name=name)
        if runnable is None:
            raise AgentRuntimeError("未找到可委派的 Agent 或 Workflow")
        requested_kind = str(kind or "").strip()
        if requested_kind and requested_kind not in {runnable["kind"], f"{runnable['kind']}_run"}:
            raise AgentRuntimeError("委派类型与目标不匹配")
        if not runnable.get("enabled", True):
            raise AgentRuntimeError("指定 Agent 或 Workflow 已停用")
        if runnable["kind"] == "agent":
            run = self.create_agent_run({"agent_id": runnable["id"], "user_goal": goal, "source": "delegation"})
        else:
            run = self.create_workflow_run({"workflow_id": runnable["id"], "user_goal": goal, "source": "delegation"})
        return {
            "ok": run["status"] == "completed",
            "runnable": runnable,
            "run_id": run["run_id"],
            "run_group_id": run.get("run_group_id", ""),
            "status": run["status"],
            "result": run.get("result") or "",
            "pending_approval": run.get("pending_approval") if isinstance(run.get("pending_approval"), dict) else {},
        }

    def parse_known_chat_runnable(self, text: str) -> tuple[str, str] | None:
        value = (text or "").strip()
        mention = self._chat_mention_parts(value)
        if mention is None:
            return None
        prefix, body, remaining_lines = mention
        if not body.strip():
            return None
        if body.startswith('"') or body.startswith("'"):
            return self.parse_chat_runnable(value)
        runnables = sorted(
            self.list_runnables()["runnables"],
            key=lambda item: max(len(str(item.get("name") or "")), len(str(item.get("nickname") or ""))),
            reverse=True,
        )
        body_lower = body.lower()
        for runnable in runnables:
            aliases = [
                str(runnable.get("name") or "").strip(),
                str(runnable.get("nickname") or "").strip(),
            ]
            for name in sorted({alias for alias in aliases if alias}, key=len, reverse=True):
                if not body_lower.startswith(name.lower()):
                    continue
                remainder = body[len(name) :]
                if remainder and not remainder[0].isspace():
                    continue
                return name, self._chat_mention_goal(prefix, remainder, remaining_lines)
        parsed = self.parse_chat_runnable(value)
        if parsed is None:
            return None
        raw_name = str(parsed[0] or "").strip().lower()
        if raw_name in {"agent", "agents", "workflow", "workflows", "runnable", "runnables"}:
            return None
        return parsed

    @staticmethod
    def parse_chat_runnable(text: str) -> tuple[str, str] | None:
        value = (text or "").strip()
        mention = NativeRunEngine._chat_mention_parts(value)
        if mention is None:
            return None
        prefix, body, remaining_lines = mention
        match = re.match(r"^(?P<name>\"[^\"]+\"|'[^']+'|[^\s，。！？、；;,.!?]+)\s*(?P<body>.*)$", body)
        if not match:
            return None
        raw_name = match.group("name").strip("\"'")
        rest = match.group("body")
        return raw_name, NativeRunEngine._chat_mention_goal(prefix, rest, remaining_lines)

    @staticmethod
    def _chat_mention_parts(text: str) -> tuple[str, str, list[str]] | None:
        value = (text or "").strip()
        if not value:
            return None
        lines = value.splitlines()
        first_line = lines[0]
        match = re.search(r"(^|[\s，。！？、；;,.!?])@(?P<body>.+)$", first_line)
        if not match:
            return None
        prefix = first_line[: match.start()].strip()
        body = match.group("body")
        return prefix, body, lines[1:]

    @staticmethod
    def _chat_mention_goal(prefix: str, remainder: str, remaining_lines: list[str]) -> str:
        first_line_parts = [part.strip() for part in (prefix, remainder) if part and part.strip()]
        first_line = " ".join(first_line_parts)
        return "\n".join([first_line, *remaining_lines]).strip()


AgentRuntimeService = NativeRunEngine

_global_agent_runtime_service: NativeRunEngine | None = None


def get_native_agent_readiness() -> dict[str, Any]:
    """Return native main-agent readiness."""
    try:
        profile_service = get_model_profile_service()
        profile_id = str(profile_service.get_defaults().get("chat") or "").strip()
        if not profile_id:
            return {
                "ready": False,
                "code": "native_agent_not_ready",
                "reason": "model_profile_required",
                "message": "请先配置并选择默认对话模型。",
                "capabilities": {
                    "model": False,
                    "image_input": False,
                    "tools": False,
                    "approval": False,
                },
            }
        profile = profile_service.get_profile_private(profile_id)
    except KeyError:
        return {
            "ready": False,
            "code": "native_agent_not_ready",
            "reason": "model_profile_required",
            "message": "默认对话模型不存在，请重新选择。",
            "capabilities": {
                "model": False,
                "image_input": False,
                "tools": False,
                "approval": False,
            },
        }
    except Exception as exc:
        return {
            "ready": False,
            "code": "native_agent_not_ready",
            "reason": "model_profile_unavailable",
            "message": redact_secrets(exc),
            "capabilities": {
                "model": False,
                "image_input": False,
                "tools": False,
                "approval": False,
            },
        }

    reason = ""
    if not profile.get("enabled", True):
        reason = "默认对话模型已停用。"
    elif str(profile.get("status") or "") != "available":
        reason = "默认对话模型尚未通过连接测试。"
    elif str(profile.get("capability") or "") != "chat":
        reason = "默认模型不是对话模型。"
    elif not supports_openai_compatible_api(str(profile.get("provider") or "openai_compatible")):
        reason = "Native Agent 当前仅支持 OpenAI-compatible 对话模型。"
    elif not all(str(profile.get(key) or "").strip() for key in ("base_url", "model", "api_key")):
        reason = "默认对话模型配置不完整。"

    ready = not reason
    return {
        "ready": ready,
        "code": "" if ready else "native_agent_not_ready",
        "reason": "" if ready else "model_profile_unavailable",
        "message": reason,
        "profile_id": profile_id,
        "model": str(profile.get("model") or ""),
        "provider": str(profile.get("provider") or ""),
        "capabilities": {
            "model": ready,
            "image_input": ready,
            "tools": False,
            "approval": False,
        },
    }


def get_native_run_engine() -> NativeRunEngine:
    global _global_agent_runtime_service
    if _global_agent_runtime_service is None:
        _global_agent_runtime_service = NativeRunEngine()
    return _global_agent_runtime_service


def get_agent_runtime_service() -> NativeRunEngine:
    """Compatibility accessor for existing AppState, TaskRunner, and routes."""
    return get_native_run_engine()


def close_agent_runtime_service() -> None:
    global _global_agent_runtime_service
    if _global_agent_runtime_service is not None:
        _global_agent_runtime_service.close()
        _global_agent_runtime_service = None
