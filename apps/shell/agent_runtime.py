"""Agent Studio, Skill Library, and Workflow runtime services."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import zipfile
from collections.abc import Iterable as IterableABC
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import uuid4

from apps.core.tls import urlopen_with_bundled_ca
from apps.installer.workspace_init import get_workspace_status
from apps.shell.credential_store import CredentialStore, CredentialStoreError, create_credential_store
from apps.shell.model_profiles import (
    get_model_profile_service,
    openai_compatible_chat_message,
    read_openai_compatible_chat_timeout,
    supports_openai_compatible_api,
)
from packages.security import redact_api_error_text, redact_sensitive_text, sanitize_sensitive_value


class AgentRuntimeError(RuntimeError):
    """Raised when an Agent Studio operation cannot be completed."""


class AgentApprovalRequired(AgentRuntimeError):
    """Raised internally when a run must pause for user approval."""

    def __init__(self, pending_approval: dict[str, Any]) -> None:
        self.pending_approval = pending_approval
        super().__init__(f"等待审批：{pending_approval.get('tool') or 'tool'}")


_EXECUTION_BACKENDS = {"native_profile", "yachiyo_profile", "external_cli"}
_KNOWN_AGENT_TOOLS = {
    "workspace.list",
    "workspace.read",
    "workspace.write_patch",
    "terminal.run",
    "artifact.write",
}
_HIGH_RISK_AGENT_TOOLS = {"terminal.run", "workspace.write_patch"}
_TOOL_FUNCTION_NAMES = {
    "workspace.list": "workspace_list",
    "workspace.read": "workspace_read",
    "workspace.write_patch": "workspace_write_patch",
    "terminal.run": "terminal_run",
    "artifact.write": "artifact_write",
}
_TOOL_NAME_ALIASES = {value: key for key, value in _TOOL_FUNCTION_NAMES.items()}
_MAX_AGENT_TOOL_ITERATIONS = 50
_FINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
_WORKFLOW_NODE_TYPES = {"start", "agent", "approval", "artifact"}
_NATIVE_LIBRARY_SOURCE_TYPES = {"native_global", "native_project"}
_SKILL_SOURCE_TYPES = {*_NATIVE_LIBRARY_SOURCE_TYPES, "npx_skills", "local_zip", "local_dir"}
_SHELL_METACHARS = {"&&", "||", "&", ";", "|", ">", ">>", "<", "$(", "`", "\n", "\r"}
_UNSET = object()
_SENSITIVE_ENV_RE = re.compile(
    r"(?i)(^SSH_AUTH_SOCK$|^GITHUB_TOKEN$|^(AWS|GOOGLE|AZURE)_|(_API_KEY|_TOKEN|_SECRET|_PASSWORD)$)"
)
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
_TERMINAL_PROCESS_LOCK = threading.RLock()
_TERMINAL_PROCESSES: set[subprocess.Popen[Any]] = set()
_RUNTIME_JSON_REDACTION_MAX_ITEMS = 1000


@dataclass(frozen=True)
class _RunBudgetLimits:
    max_model_calls: int = 50
    max_tool_calls: int = 100
    max_terminal_calls: int = 10
    max_run_duration_seconds: int = 600
    max_model_output_chars: int = 200_000
    max_tool_output_chars: int = 100_000
    max_context_chars: int = 200_000


@dataclass
class _RunBudget:
    limits: _RunBudgetLimits
    started_at_epoch: float
    model_calls_used: int = 0
    tool_calls_used: int = 0
    terminal_calls_used: int = 0

    def check_duration(self) -> None:
        elapsed = max(0.0, time.time() - self.started_at_epoch)
        if elapsed > max(1, int(self.limits.max_run_duration_seconds)):
            raise AgentRuntimeError(
                f"Run 已超过 max_run_duration_seconds={self.limits.max_run_duration_seconds} 的执行预算"
            )

    def check_context(self, context_chars: int) -> None:
        self.check_duration()
        if context_chars > max(1, int(self.limits.max_context_chars)):
            raise AgentRuntimeError(
                f"Run 上下文超过 max_context_chars={self.limits.max_context_chars} 的执行预算"
            )

    def claim_model_call(self) -> None:
        self.check_duration()
        if self.model_calls_used >= max(1, int(self.limits.max_model_calls)):
            raise AgentRuntimeError(f"Run 已超过 max_model_calls={self.limits.max_model_calls} 的执行预算")
        self.model_calls_used += 1

    def claim_tool_call(self, tool_name: str, *, terminal_execution: bool = False) -> None:
        self.check_duration()
        if self.tool_calls_used >= max(1, int(self.limits.max_tool_calls)):
            raise AgentRuntimeError(f"Run 已超过 max_tool_calls={self.limits.max_tool_calls} 的执行预算")
        if terminal_execution and self.terminal_calls_used >= max(0, int(self.limits.max_terminal_calls)):
            raise AgentRuntimeError(
                f"Run 已超过 max_terminal_calls={self.limits.max_terminal_calls} 的执行预算"
            )
        self.tool_calls_used += 1
        if terminal_execution:
            self.terminal_calls_used += 1


def cancel_terminal_process_groups() -> None:
    with _TERMINAL_PROCESS_LOCK:
        processes = list(_TERMINAL_PROCESSES)
    for process in processes:
        if process.poll() is not None:
            with _TERMINAL_PROCESS_LOCK:
                _TERMINAL_PROCESSES.discard(process)
            continue
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                pass


def _scrubbed_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not _SENSITIVE_ENV_RE.search(key)
    }
    for key, value in (extra or {}).items():
        clean_key = str(key)
        if _SENSITIVE_ENV_RE.search(clean_key):
            continue
        env[clean_key] = str(value)
    return env


def _is_active_run_status(status: str) -> bool:
    return (status.strip() or "running") not in _FINAL_RUN_STATUSES


def _agent_output_contract_rules(contract: Any) -> str:
    value = str(contract or "chat").strip().lower() or "chat"
    rules = {
        "chat": (
            "Return a direct chat response. Include enough detail for the user and the main model to understand "
            "what was done, what failed, or what needs approval. Do not create an artifact unless the user goal "
            "explicitly asks for one."
        ),
        "markdown": (
            "Return polished Markdown with clear sections. If the user explicitly asks for a saved document and "
            "artifact.write is allowed, write the Markdown as an artifact and mention the artifact path; otherwise "
            "include the Markdown inline."
        ),
        "report": (
            "Return a concise report with task, result, evidence, risks, and next steps. Use artifacts only when "
            "the user asks for a saved report or the task naturally produces a file."
        ),
        "diff": (
            "Return a change-oriented answer: summarize intended code changes and include a unified diff or patch "
            "text only when the user asked for a patch. Do not call workspace.write_patch merely because the output "
            "contract is diff; call it only when the user goal asks you to modify workspace files and the tool is "
            "allowed. If no file change is requested, provide code inline."
        ),
        "artifacts": (
            "Prefer producing named artifacts for concrete deliverables. If artifact.write is allowed, write each "
            "deliverable artifact and mention its path in the final answer. If artifact.write is not allowed, state "
            "that no artifact could be written and provide the content inline."
        ),
    }
    return f"Contract: {value}\nRules: {rules.get(value, rules['chat'])}"


def _user_goal_from_agent_messages(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        match = re.search(r"^# User Goal\s*\n(.*?)(?:\n# |\Z)", content, re.DOTALL | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return ""


def _agent_goal_disallows_tool(user_goal: str, tool_name: str) -> str:
    text = " ".join(str(user_goal or "").split()).strip().lower()
    if not text:
        return ""

    no_file_patterns = (
        r"不(?:需要|用|必|要).{0,12}(?:创建|保存|写入|写|修改|改动).{0,8}文件",
        r"无需.{0,12}(?:创建|保存|写入|写|修改|改动).{0,8}文件",
        r"不(?:创建|保存|写入|修改|改动).{0,8}文件",
        r"只(?:需要)?(?:展示|给出|贴出).{0,12}(?:代码|内容|方案)",
        r"代码完整展示即可",
        r"do not (?:create|save|write|modify|change).{0,24}file",
        r"don't (?:create|save|write|modify|change).{0,24}file",
        r"without (?:creating|saving|writing|modifying|changing).{0,24}file",
        r"no file (?:changes?|writes?|creation)",
        r"(?:inline|show|display) (?:code|content) only",
    )
    no_command_patterns = (
        r"不(?:需要|用|必|要).{0,12}(?:运行|执行).{0,12}(?:命令|脚本|代码|测试)?",
        r"无需.{0,12}(?:运行|执行).{0,12}(?:命令|脚本|代码|测试)?",
        r"不要.{0,12}(?:运行|执行).{0,12}(?:命令|脚本|代码|测试)?",
        r"do not (?:run|execute)",
        r"don't (?:run|execute)",
        r"without (?:running|executing)",
        r"no command execution",
    )
    explicit_terminal_patterns = (
        r"(?:必须|需要|请求|调用|使用).{0,24}terminal\.run",
        r"只(?:需要|使用|调用).{0,12}terminal\.run",
        r"(?:must|should|please).{0,24}(?:use|call|request).{0,24}terminal\.run",
        r"(?:only|just).{0,12}(?:use|call).{0,12}terminal\.run",
    )

    if tool_name in {"workspace.write_patch", "artifact.write"} and any(re.search(pattern, text) for pattern in no_file_patterns):
        return "用户目标明确要求不要创建、保存或修改文件；请改为 inline 交付内容。"
    if (
        tool_name == "terminal.run"
        and not any(re.search(pattern, text) for pattern in explicit_terminal_patterns)
        and any(re.search(pattern, text) for pattern in no_command_patterns)
    ):
        return "用户目标明确要求不要运行命令或脚本；请改为给出代码、示例或说明。"
    return ""


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


def _redact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_json_value(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def _redact_run_event_payload(value: Any) -> Any:
    return sanitize_sensitive_value(
        value,
        text_limit=0,
        max_items=_RUNTIME_JSON_REDACTION_MAX_ITEMS,
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
    data = path.read_bytes()[:limit]
    return data.decode("utf-8", errors="replace")


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
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            rel = path.relative_to(root).as_posix()
            digest.update(rel.encode("utf-8", errors="replace"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        except OSError:
            continue
    return digest.hexdigest()


def _parse_skill_frontmatter(markdown: str) -> dict[str, Any]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, Any] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip().strip("\"'")
        if key and value:
            data[key] = value
    return data


def _normalize_tool_name(value: Any) -> str:
    name = str(value or "").strip()
    return _TOOL_NAME_ALIASES.get(name, name)


def _message_field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    if isinstance(value, (str, bytes, bytearray)):
        return None
    return getattr(value, name, None)


def _message_content_part_type(value: Any) -> str:
    return str(_message_field(value, "type") or "").strip().lower()


def _is_reasoning_content_part(value: Any) -> bool:
    return _message_content_part_type(value) in {"reasoning", "reasoning_content", "thinking", "thought"}


def _message_text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
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
    return str(value) if value is not None and not isinstance(value, (list, tuple, set)) else ""


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
        return _message_text_value(text)
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
    return ""


def _stream_chunk_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
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
    direct = _message_field(chunk, "tool_calls")
    if isinstance(direct, list):
        return [(0, index, call) for index, call in enumerate(direct)]
    direct_function = _message_field(chunk, "function_call")
    if direct_function is not None:
        return [(0, 0, {"index": 0, "type": "function", "function": direct_function})]
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
            delta_function = _message_field(delta, "function_call")
            if delta_function is not None:
                calls.append((choice_index, 0, {"index": 0, "type": "function", "function": delta_function}))
        message = _message_field(choice, "message")
        if message is not None:
            message_calls = _message_field(message, "tool_calls")
            if isinstance(message_calls, list):
                calls.extend((choice_index, index, call) for index, call in enumerate(message_calls))
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
    key = (choice_index, index)
    if call_id:
        call_id_text = str(call_id)
        for existing_key, existing in accumulator.items():
            if existing_key[0] == choice_index and str(existing.get("id") or "") == call_id_text:
                key = existing_key
                break
        else:
            existing = accumulator.get(key)
            if raw_index is None and existing and str(existing.get("id") or "") not in {"", call_id_text}:
                occupied = {tool_index for existing_choice, tool_index in accumulator if existing_choice == choice_index}
                while index in occupied:
                    index += 1
                key = (choice_index, index)
    entry = accumulator.setdefault(key, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    if call_id:
        entry["id"] = str(call_id)
    call_type = _message_field(raw_call, "type")
    if call_type:
        entry["type"] = str(call_type)
    raw_function = _message_field(raw_call, "function")
    if raw_function is None:
        return
    function = entry.setdefault("function", {"name": "", "arguments": ""})
    name = _message_field(raw_function, "name")
    if name:
        function["name"] = f"{function.get('name') or ''}{name}"
    arguments = _message_field(raw_function, "arguments")
    if arguments:
        function["arguments"] = f"{function.get('arguments') or ''}{_tool_arguments_text(arguments)}"


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
            function_call = _coerce_function_call(_message_field(message, "function_call"))
            if function_call is not None:
                result["tool_calls"] = [function_call]
        return result

    content_parts: list[str] = []
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_deltas: dict[tuple[int, int], dict[str, Any]] = {}
    for chunk in message:
        content = _stream_chunk_text(chunk)
        if content:
            content_parts.append(content)
        chunk_tool_calls = _stream_chunk_tool_calls(chunk)
        if isinstance(chunk_tool_calls, list):
            for choice_index, fallback_index, call in chunk_tool_calls:
                _merge_stream_tool_call_delta(tool_call_deltas, call, choice_index, fallback_index)

    result: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
    if tool_call_deltas:
        tool_calls = _coalesced_stream_tool_calls(tool_call_deltas)
    if tool_calls is not None:
        result["tool_calls"] = tool_calls
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
    text = redact_secrets(value)
    if len(text) > limit:
        return f"{text[:limit]}... [truncated]"
    return text


def _public_pending_approval(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    if not raw:
        return {}
    return {
        "approval_id": str(raw.get("approval_id") or ""),
        "tool": str(raw.get("tool") or ""),
        "input_preview": raw.get("input_preview") or _tool_input_preview(raw.get("input") or {}),
        "requested_at": str(raw.get("requested_at") or ""),
    }


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    properties: dict[str, Any]
    required: tuple[str, ...] = ()

    @property
    def function_name(self) -> str:
        return _TOOL_FUNCTION_NAMES[self.name]

    @property
    def allowed_fields(self) -> set[str]:
        return set(self.properties)

    def to_model_tool_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.function_name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.properties,
                    "required": list(self.required),
                    "additionalProperties": False,
                },
            },
        }

    def validate_payload(self, payload: dict[str, Any]) -> None:
        extra_fields = sorted(set(payload) - self.allowed_fields)
        if extra_fields:
            raise AgentRuntimeError(f"{self.name} 参数包含未声明字段：{', '.join(extra_fields)}")
        for key in self.required:
            if not isinstance(payload.get(key), str) or not str(payload.get(key) or "").strip():
                raise AgentRuntimeError(f"{self.name} 参数 {key} 必须是非空字符串")
        if self.name == "workspace.write_patch":
            patch_supplied = isinstance(payload.get("patch"), str) and str(payload.get("patch") or "").strip()
            if not patch_supplied:
                raise AgentRuntimeError("workspace.write_patch 参数 patch 必须是非空字符串")
            hash_values = {
                key: str(payload.get(key) or "").strip()
                for key in ("expected_sha256", "base_sha256")
                if key in payload
            }
            for key, value in hash_values.items():
                if value and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                    raise AgentRuntimeError(f"workspace.write_patch 参数 {key} 必须是 64 位 SHA-256 hex")
            if hash_values.get("expected_sha256") and hash_values.get("base_sha256"):
                if hash_values["expected_sha256"].lower() != hash_values["base_sha256"].lower():
                    raise AgentRuntimeError("workspace.write_patch 参数 expected_sha256 与 base_sha256 不一致")
        if "path" in payload and not isinstance(payload.get("path"), str):
            raise AgentRuntimeError(f"{self.name} 参数 path 必须是字符串")
        if "timeout_seconds" in payload:
            value = payload.get("timeout_seconds")
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 120:
                raise AgentRuntimeError("terminal.run 参数 timeout_seconds 必须是 1-120 的整数")
        if "shell" in payload and not isinstance(payload.get("shell"), bool):
            raise AgentRuntimeError("terminal.run 参数 shell 必须是布尔值")
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if redact_secrets(serialized) != serialized:
            raise AgentRuntimeError(f"{self.name} 参数包含敏感凭据，已拒绝执行和持久化")


TOOL_DESCRIPTORS: dict[str, ToolDescriptor] = {
    "workspace.list": ToolDescriptor(
        name="workspace.list",
        description="List entries in an allowed workspace directory. Use this before workspace.read when you only know a directory path.",
        properties={"path": {"type": "string", "description": "Relative directory path."}},
    ),
    "workspace.read": ToolDescriptor(
        name="workspace.read",
        description="Read a UTF-8 text file from the allowed workspace. This only accepts file paths; use workspace.list for directories.",
        properties={"path": {"type": "string", "description": "Relative file path."}},
        required=("path",),
    ),
    "workspace.write_patch": ToolDescriptor(
        name="workspace.write_patch",
        description="Apply a single-file UTF-8 unified diff to an allowed workspace path. Requires user approval.",
        properties={
            "path": {"type": "string", "description": "Relative file path inside writable scopes."},
            "patch": {"type": "string", "description": "Single-file unified diff whose file headers match path."},
            "expected_sha256": {"type": "string", "description": "Optional current file SHA-256 precondition checked immediately before writing."},
            "base_sha256": {"type": "string", "description": "Alias for expected_sha256."},
        },
        required=("path",),
    ),
    "terminal.run": ToolDescriptor(
        name="terminal.run",
        description="Run an argv command in the Agent workdir. Requires user approval. Shell mode is disabled unless explicitly requested and approved.",
        properties={
            "command": {"type": "string", "description": "Command parsed into argv by default."},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
            "shell": {"type": "boolean", "description": "Explicitly request shell parsing; the full command is shown for approval."},
        },
        required=("command",),
    ),
    "artifact.write": ToolDescriptor(
        name="artifact.write",
        description="Write a markdown/text artifact for the current run.",
        properties={
            "path": {"type": "string", "description": "Relative artifact path."},
            "content": {"type": "string", "description": "Artifact content."},
        },
        required=("path", "content"),
    ),
}


class ToolDescriptorRegistry:
    @staticmethod
    def model_tool_schemas(allowed_tools: list[str]) -> list[dict[str, Any]]:
        schemas = []
        for tool in allowed_tools:
            descriptor = TOOL_DESCRIPTORS.get(tool)
            if descriptor is not None:
                schemas.append(descriptor.to_model_tool_schema())
        return schemas

    @staticmethod
    def validate_payload(tool_name: str, payload: dict[str, Any]) -> None:
        descriptor = TOOL_DESCRIPTORS.get(tool_name)
        if descriptor is None:
            raise AgentRuntimeError(f"未知工具：{tool_name}")
        descriptor.validate_payload(payload)


class PolicyGate:
    @staticmethod
    def allows_tool(tool_name: str, allowed_tools: list[str]) -> bool:
        return tool_name in set(str(tool or "").strip() for tool in allowed_tools)


@dataclass
class ToolBroker:
    """Controlled tools exposed to custom API agents.

    The broker is intentionally narrow. Frontend callers never submit shell
    commands directly; runtime code passes approved, policy-checked calls here.
    """

    workspace_policy: dict[str, Any]
    artifact_root: Path
    approvals: dict[str, bool] | None = None

    def __post_init__(self) -> None:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.approvals = self.approvals or {}

    @property
    def workdir(self) -> Path:
        configured = str(self.workspace_policy.get("default_workdir") or "").strip()
        return Path(configured).expanduser() if configured else Path.cwd()

    def _scope_roots(self, key: str) -> list[Path]:
        scopes = self.workspace_policy.get(key) or []
        if isinstance(scopes, str):
            scopes = [scopes]
        roots = []
        for scope in scopes:
            rel = str(scope or ".").strip() or "."
            roots.append((self.workdir / rel).resolve())
        return roots or [self.workdir.resolve()]

    def _resolve_workspace_path(self, path: str, *, write: bool = False) -> Path:
        rel = _safe_rel_path(path or ".")
        target = (self.workdir / rel).resolve()
        key = "writable_scopes" if write else "readable_scopes"
        roots = self._scope_roots(key)
        if not any(_is_within(target, root) for root in roots):
            raise AgentRuntimeError("路径不在 Agent 允许的工作区范围内")
        return target

    def workspace_list(self, path: str = ".") -> dict[str, Any]:
        target = self._resolve_workspace_path(path)
        display_path = path or "."
        if not target.exists():
            return {
                "ok": False,
                "path": display_path,
                "error": "路径不存在",
                "hint": "请先用 workspace.list 查看父目录，确认要访问的相对路径。",
            }
        if not target.is_dir():
            return {
                "ok": False,
                "path": display_path,
                "error": "workspace.list 只能列目录",
                "hint": "如果要读取文件内容，请改用 workspace.read。",
                "suggested_tool": "workspace.read",
            }
        entries = []
        for child in sorted(target.iterdir(), key=lambda item: item.name.lower())[:200]:
            entries.append({"name": child.name, "type": "dir" if child.is_dir() else "file"})
        return {"ok": True, "path": display_path, "entries": entries}

    def workspace_read(self, path: str) -> dict[str, Any]:
        target = self._resolve_workspace_path(path)
        display_path = path or "."
        if not target.exists():
            return {
                "ok": False,
                "path": display_path,
                "error": "路径不存在",
                "hint": "请先用 workspace.list 查看父目录，确认要读取的文件相对路径。",
            }
        if target.is_dir():
            return {
                "ok": False,
                "path": display_path,
                "error": "workspace.read 只能读取文件",
                "hint": "这是一个目录；请改用 workspace.list 查看目录内容，或选择目录中的具体文件再读取。",
                "suggested_tool": "workspace.list",
            }
        if not target.is_file():
            return {
                "ok": False,
                "path": display_path,
                "error": "workspace.read 只能读取文件",
                "hint": "请选择普通文本文件路径。",
            }
        return {"ok": True, "path": display_path, "content": _read_text(target)}

    def workspace_write_patch(
        self,
        path: str,
        content: str = "",
        *,
        patch: str = "",
        expected_sha256: str = "",
        approved: bool = False,
    ) -> dict[str, Any]:
        if str(content or "").strip():
            raise AgentRuntimeError("workspace.write_patch 不再支持 content 全量写入；请提供单文件 unified diff patch")
        target = self._resolve_workspace_path(path, write=True)
        if not approved and not self.approvals.get("workspace.write_patch"):
            return {"ok": False, "approval_required": True, "tool": "workspace.write_patch"}
        mode = "patch"
        if target.exists() and not target.is_file():
            return {"ok": False, "path": path, "error": "workspace.write_patch 只能写入普通文件"}
        if not target.exists():
            return {"ok": False, "path": path, "error": "workspace.write_patch patch 模式要求目标文件已存在"}
        before_bytes = target.read_bytes() if target.exists() else b""
        before_sha256 = _sha256_bytes(before_bytes)
        clean_expected_sha256 = str(expected_sha256 or "").strip()
        if clean_expected_sha256 and clean_expected_sha256 != before_sha256:
            return {
                "ok": False,
                "path": path,
                "error": "workspace.write_patch 当前文件 hash 与 expected_sha256 不匹配",
                "sha256_before": before_sha256,
            }
        try:
            before_text = before_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return {"ok": False, "path": path, "error": "workspace.write_patch patch 模式只支持 UTF-8 文本文件"}
        content = _apply_single_file_unified_diff(before_text, str(patch or ""), expected_path=path)
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(target, content)
        after_sha256 = _sha256_file(target)
        return {
            "ok": True,
            "path": path,
            "mode": mode,
            "bytes": len(content.encode("utf-8")),
            "sha256_before": before_sha256,
            "sha256_after": after_sha256,
        }

    def terminal_run(
        self,
        command: str,
        *,
        approved: bool = False,
        timeout_seconds: int = 30,
        shell: bool = False,
    ) -> dict[str, Any]:
        if not approved and not self.approvals.get("terminal.run"):
            return {
                "ok": False,
                "approval_required": True,
                "tool": "terminal.run",
                "input_preview": {"command": command, "shell": bool(shell)},
            }
        clean_command = str(command or "").strip()
        if not clean_command:
            return {"ok": False, "error": "terminal.run 命令不能为空"}
        try:
            argv: str | list[str] = clean_command if shell else shlex.split(clean_command)
        except ValueError as exc:
            return {"ok": False, "error": f"terminal.run 命令解析失败：{exc}"}
        if not shell and not argv:
            return {"ok": False, "error": "terminal.run 命令不能为空"}
        env = _scrubbed_subprocess_env()
        try:
            process = subprocess.Popen(
                argv,
                cwd=self.workdir,
                shell=bool(shell),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            return {
                "ok": False,
                "returncode": None,
                "timed_out": False,
                "shell": bool(shell),
                "stdout": "",
                "stderr": redact_api_error_text(exc),
            }
        with _TERMINAL_PROCESS_LOCK:
            _TERMINAL_PROCESSES.add(process)
        timed_out = False
        try:
            stdout, stderr = process.communicate(
                timeout=max(1, min(int(timeout_seconds or 30), 120))
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            stdout, stderr = process.communicate()
        finally:
            with _TERMINAL_PROCESS_LOCK:
                _TERMINAL_PROCESSES.discard(process)
        return {
            "ok": process.returncode == 0 and not timed_out,
            "returncode": process.returncode,
            "timed_out": timed_out,
            "shell": bool(shell),
            "stdout": redact_secrets(stdout)[-8000:],
            "stderr": redact_secrets(stderr)[-8000:],
        }

    def artifact_write(self, path: str, content: str) -> dict[str, Any]:
        rel = _safe_rel_path(path)
        target = (self.artifact_root / rel).resolve()
        if not _is_within(target, self.artifact_root):
            raise AgentRuntimeError("artifact 路径越界")
        target.parent.mkdir(parents=True, exist_ok=True)
        safe_content = redact_secrets(content)
        target.write_text(safe_content, encoding="utf-8")
        return {"ok": True, "path": rel, "bytes": len(safe_content.encode("utf-8"))}

    def call(self, name: str, payload: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        if name == "workspace.list":
            return self.workspace_list(str(payload.get("path") or "."))
        if name == "workspace.read":
            return self.workspace_read(str(payload.get("path") or ""))
        if name == "workspace.write_patch":
            return self.workspace_write_patch(
                str(payload.get("path") or ""),
                str(payload.get("content") or ""),
                patch=str(payload.get("patch") or ""),
                expected_sha256=str(payload.get("expected_sha256") or payload.get("base_sha256") or ""),
                approved=approved,
            )
        if name == "terminal.run":
            return self.terminal_run(
                str(payload.get("command") or ""),
                approved=approved,
                timeout_seconds=int(payload.get("timeout_seconds") or 30),
                shell=bool(payload.get("shell", False)),
            )
        if name == "artifact.write":
            return self.artifact_write(str(payload.get("path") or ""), str(payload.get("content") or ""))
        raise AgentRuntimeError(f"未知工具：{name}")


class RunEventRepository:
    """Durable, replayable execution fact log for native runs."""

    def __init__(self, conn: _LockedConnection, db_lock: threading.RLock, *, ensure_run_exists: Any | None = None) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._ensure_run_exists = ensure_run_exists

    def append(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "native_runtime",
        visibility: str = "user",
        sensitivity: str = "public",
    ) -> dict[str, Any]:
        clean_run_id = str(run_id or "").strip()
        clean_event_type = str(event_type or "").strip()
        if not clean_run_id or not clean_event_type:
            raise AgentRuntimeError("RunEvent 缺少 run_id 或 event_type")

        event_id = f"event_{uuid4().hex[:16]}"
        created_at = _now()
        safe_payload = _redact_run_event_payload(payload or {})
        normalized_visibility = "internal" if str(visibility or "").strip() == "internal" else "user"
        normalized_sensitivity = "secret" if str(sensitivity or "").strip() == "secret" else "public"

        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM run_events WHERE run_id=?",
                    (clean_run_id,),
                ).fetchone()
                sequence = int(row["next_sequence"] if row is not None else 1)
                self._conn.execute(
                    """
                    INSERT INTO run_events (
                        event_id, run_id, sequence, schema_version, event_type,
                        actor, visibility, sensitivity, payload_json, created_at
                    ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        clean_run_id,
                        sequence,
                        clean_event_type,
                        str(actor or "native_runtime"),
                        normalized_visibility,
                        normalized_sensitivity,
                        _json_dump(safe_payload),
                        created_at,
                    ),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

        return {
            "event_id": event_id,
            "run_id": clean_run_id,
            "sequence": sequence,
            "schema_version": 1,
            "event_type": clean_event_type,
            "actor": str(actor or "native_runtime"),
            "visibility": normalized_visibility,
            "sensitivity": normalized_sensitivity,
            "payload": safe_payload,
            "created_at": created_at,
        }

    def list(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        clean_run_id = str(run_id or "").strip()
        if callable(self._ensure_run_exists):
            self._ensure_run_exists(clean_run_id)
        safe_after_sequence = max(0, int(after_sequence or 0))
        safe_limit = max(1, min(int(limit or 200), 1000))
        params: list[Any] = [clean_run_id, safe_after_sequence]
        visibility_clause = ""
        if not include_internal:
            visibility_clause = " AND visibility='user' AND sensitivity!='secret'"
        params.append(safe_limit)
        rows = self._conn.execute(
            f"""
            SELECT * FROM run_events
             WHERE run_id=? AND sequence>?{visibility_clause}
             ORDER BY sequence ASC
             LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return {
            "ok": True,
            "run_id": clean_run_id,
            "after_sequence": safe_after_sequence,
            "limit": safe_limit,
            "events": [
                {
                    "event_id": str(row["event_id"]),
                    "run_id": str(row["run_id"]),
                    "sequence": int(row["sequence"]),
                    "schema_version": int(row["schema_version"]),
                    "event_type": str(row["event_type"]),
                    "actor": str(row["actor"]),
                    "visibility": str(row["visibility"]),
                    "sensitivity": str(row["sensitivity"]),
                    "payload": _json_load(row["payload_json"], {}),
                    "created_at": str(row["created_at"]),
                }
                for row in rows
            ],
        }


class TaskRunLinkRepository:
    """Persistence boundary for product Task to native Run links."""

    def __init__(
        self,
        conn: _LockedConnection,
        *,
        ensure_row_factory: Any,
        get_run: Any,
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._get_run = get_run

    def link(self, *, task_id: str, run_id: str, session_id: str = "") -> dict[str, Any]:
        clean_task_id = str(task_id or "").strip()
        clean_run_id = str(run_id or "").strip()
        if not clean_task_id or not clean_run_id:
            raise AgentRuntimeError("Task 与 Run 映射缺少 task_id 或 run_id")
        run = self._get_run(clean_run_id)
        latest_sequence = self.latest_event_sequence(clean_run_id)
        now = _now()
        self._conn.execute(
            """
            INSERT INTO task_run_links (
                task_id, run_id, session_id, run_status, last_event_sequence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                run_id=excluded.run_id,
                session_id=excluded.session_id,
                run_status=excluded.run_status,
                last_event_sequence=excluded.last_event_sequence,
                updated_at=excluded.updated_at
            """,
            (
                clean_task_id,
                clean_run_id,
                str(session_id or ""),
                str(run.get("status") or ""),
                latest_sequence,
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get(clean_task_id)

    def get(self, task_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute(
            """
            SELECT task_id, run_id, session_id, run_status, last_event_sequence, created_at, updated_at
              FROM task_run_links
             WHERE task_id=?
            """,
            (str(task_id or "").strip(),),
        ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._row_to_link(row)

    def for_run(self, run_id: str) -> dict[str, Any] | None:
        self._ensure_row_factory()
        row = self._conn.execute(
            """
            SELECT task_id, run_id, session_id, run_status, last_event_sequence, created_at, updated_at
              FROM task_run_links
             WHERE run_id=?
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (str(run_id or "").strip(),),
        ).fetchone()
        return self._row_to_link(row) if row is not None else None

    def latest_event_sequence(self, run_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS last_sequence FROM run_events WHERE run_id=?",
            (str(run_id or "").strip(),),
        ).fetchone()
        return int(row["last_sequence"] if row is not None else 0)

    def sync_projection(
        self,
        run_id: str,
        *,
        status: str | None = None,
        last_event_sequence: int | None = None,
    ) -> None:
        clean_run_id = str(run_id or "").strip()
        if not clean_run_id:
            return
        updates: list[str] = []
        params: list[Any] = []
        if status is not None:
            updates.append("run_status=?")
            params.append(str(status or ""))
        if last_event_sequence is not None:
            updates.append("last_event_sequence=MAX(last_event_sequence, ?)")
            params.append(max(0, int(last_event_sequence or 0)))
        if not updates:
            return
        updates.append("updated_at=?")
        params.append(_now())
        params.append(clean_run_id)
        self._conn.execute(
            f"UPDATE task_run_links SET {', '.join(updates)} WHERE run_id=?",
            tuple(params),
        )
        self._conn.commit()

    @staticmethod
    def _row_to_link(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"]),
            "run_id": str(row["run_id"]),
            "session_id": str(row["session_id"] or ""),
            "run_status": str(row["run_status"] or ""),
            "last_event_sequence": int(row["last_event_sequence"] or 0),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"] or row["created_at"]),
        }


class ApprovalRepository:
    """Projection store for user-visible and idempotent run approvals."""

    def __init__(self, conn: _LockedConnection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock

    def sync(self, run_id: str, *, status: str, pending_approval: dict[str, Any]) -> None:
        if pending_approval:
            self.upsert_pending(run_id, pending_approval)
            return
        self.resolve_pending(run_id, status=status)

    def upsert_pending(self, run_id: str, pending_approval: dict[str, Any]) -> None:
        public = _public_pending_approval(pending_approval)
        approval_id = str(pending_approval.get("approval_id") or f"approval_{run_id}").strip()
        requested_at = str(pending_approval.get("requested_at") or _now())
        self._conn.execute(
            """
            INSERT INTO run_approvals (
                approval_id, run_id, status, tool, input_preview_json, payload_json,
                requested_at, resolved_at, updated_at
            ) VALUES (?, ?, 'pending', ?, ?, ?, ?, '', ?)
            ON CONFLICT(approval_id) DO UPDATE SET
                status='pending',
                tool=excluded.tool,
                input_preview_json=excluded.input_preview_json,
                payload_json=excluded.payload_json,
                requested_at=excluded.requested_at,
                resolved_at='',
                updated_at=excluded.updated_at
            """,
            (
                approval_id,
                run_id,
                str(public.get("tool") or "")[:120],
                _json_dump(public.get("input_preview") or {}),
                _json_dump(public),
                requested_at,
                _now(),
            ),
        )

    def claim_pending_approval(self, run_id: str, pending_approval: dict[str, Any]) -> bool:
        approval_id = str(pending_approval.get("approval_id") or f"approval_{run_id}").strip()
        if not approval_id:
            return False
        public = _public_pending_approval(pending_approval)
        now = _now()
        requested_at = str(pending_approval.get("requested_at") or now)
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT status FROM run_approvals WHERE approval_id=? AND run_id=?",
                    (approval_id, run_id),
                ).fetchone()
                if row is None:
                    self._conn.execute(
                        """
                        INSERT INTO run_approvals (
                            approval_id, run_id, status, tool, input_preview_json, payload_json,
                            requested_at, resolved_at, updated_at
                        ) VALUES (?, ?, 'pending', ?, ?, ?, ?, '', ?)
                        """,
                        (
                            approval_id,
                            run_id,
                            str(public.get("tool") or "")[:120],
                            _json_dump(public.get("input_preview") or {}),
                            _json_dump(public),
                            requested_at,
                            now,
                        ),
                    )
                    current_status = "pending"
                else:
                    current_status = str(row["status"] or "")
                if current_status != "pending":
                    self._conn.commit()
                    return False
                cursor = self._conn.execute(
                    """
                    UPDATE run_approvals
                       SET status='approved',
                           resolved_at=CASE WHEN resolved_at='' THEN ? ELSE resolved_at END,
                           updated_at=?
                     WHERE approval_id=? AND run_id=? AND status='pending'
                    """,
                    (now, now, approval_id, run_id),
                )
                claimed = int(cursor.rowcount or 0) == 1
                self._conn.commit()
                return claimed
            except Exception:
                self._conn.rollback()
                raise

    def resolve_pending(self, run_id: str, *, status: str) -> None:
        resolved_status = "approved" if status in {"running", "completed"} else "cancelled" if status == "cancelled" else "resolved"
        self._conn.execute(
            """
            UPDATE run_approvals
               SET status=?, resolved_at=CASE WHEN resolved_at='' THEN ? ELSE resolved_at END, updated_at=?
             WHERE run_id=? AND status='pending'
            """,
            (resolved_status, _now(), _now(), run_id),
        )


class RunArtifactRepository:
    """Projection store and file access boundary for run artifacts."""

    def __init__(
        self,
        conn: _LockedConnection,
        *,
        agent_artifacts_dir: Path,
        workflow_artifacts_dir: Path,
        get_run: Any,
    ) -> None:
        self._conn = conn
        self._agent_artifacts_dir = agent_artifacts_dir
        self._workflow_artifacts_dir = workflow_artifacts_dir
        self._get_run = get_run

    def sync(self, run_id: str, artifacts: Any) -> None:
        self._conn.execute("DELETE FROM run_artifacts WHERE run_id=?", (run_id,))
        if not isinstance(artifacts, list):
            return
        now = _now()
        for index, artifact in enumerate(item for item in artifacts if isinstance(item, dict)):
            artifact_id = f"{run_id}:artifact:{index}"
            self._conn.execute(
                """
                INSERT INTO run_artifacts (
                    artifact_id, run_id, sequence, kind, path, source_run_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    run_id,
                    index,
                    str(artifact.get("kind") or "")[:80],
                    str(artifact.get("path") or "")[:500],
                    str(artifact.get("source_run_id") or artifact.get("run_id") or "")[:160],
                    _json_dump(_redact_json_value(artifact)),
                    now,
                ),
            )

    def read(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        rel = _safe_rel_path(artifact_path)
        root = self._run_artifact_root(run)
        target = (root / rel).resolve()
        if not _is_within(target, root) or not target.is_file():
            raise KeyError(rel)
        content = _read_text(target, limit=300_000)
        return {
            "ok": True,
            "run_id": run_id,
            "path": rel,
            "content": redact_secrets(content),
            "truncated": target.stat().st_size > 300_000,
        }

    def delete_files(self, run: dict[str, Any]) -> None:
        run_id = str(run.get("run_id") or "")
        if not run_id:
            return
        root = self._artifact_base_dir(run)
        target = (root / run_id).resolve()
        if _is_within(target, root) and target.exists():
            shutil.rmtree(target, ignore_errors=True)

    def _run_artifact_root(self, run: dict[str, Any]) -> Path:
        return self._artifact_base_dir(run) / str(run["run_id"])

    def _artifact_base_dir(self, run: dict[str, Any]) -> Path:
        return self._agent_artifacts_dir if run.get("kind") == "agent_run" else self._workflow_artifacts_dir


class RunGroupRepository:
    """Lifecycle store for run groups and their child run membership."""

    def __init__(
        self,
        conn: _LockedConnection,
        *,
        ensure_row_factory: Any,
        row_to_run_group: Any,
        row_to_run: Any,
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._row_to_run_group = row_to_run_group
        self._row_to_run = row_to_run

    def list(self, limit: int = 50) -> dict[str, Any]:
        self._ensure_row_factory()
        rows = self._conn.execute(
            "SELECT * FROM run_groups ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit or 50), 200)),),
        ).fetchall()
        return {"ok": True, "run_groups": [self._row_to_run_group(row) for row in rows]}

    def get(self, run_group_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT * FROM run_groups WHERE run_group_id=?", (run_group_id,)).fetchone()
        if row is None:
            raise KeyError(run_group_id)
        return self._row_to_run_group(row)

    def source(self, run_group_id: str) -> str:
        if not run_group_id:
            return ""
        row = self._conn.execute(
            "SELECT source FROM run_groups WHERE run_group_id=?",
            (run_group_id,),
        ).fetchone()
        if row is None:
            return ""
        return str(row["source"] or "")

    def insert(self, *, title: str, source: str, workspace_dir: str = "") -> dict[str, Any]:
        run_group_id = f"run_group_{uuid4().hex[:12]}"
        now = _now()
        self._conn.execute(
            """
            INSERT INTO run_groups (
                run_group_id, title, source, workspace_dir, status, summary,
                child_run_ids_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_group_id, title[:180], source[:80], workspace_dir, "running", "", "[]", now, now),
        )
        self._conn.commit()
        return self.get(run_group_id)

    def append_run(self, run_group_id: str, run_id: str) -> None:
        if not run_group_id:
            return
        group = self.get(run_group_id)
        child_run_ids = [str(item) for item in group.get("child_run_ids") or [] if str(item)]
        if run_id not in child_run_ids:
            child_run_ids.append(run_id)
        self._conn.execute(
            """
            UPDATE run_groups
               SET child_run_ids_json=?, updated_at=?
             WHERE run_group_id=?
            """,
            (_json_dump(child_run_ids), _now(), run_group_id),
        )
        self._conn.commit()

    def update(
        self,
        run_group_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
    ) -> None:
        if not run_group_id:
            return
        current = self.get(run_group_id)
        self._conn.execute(
            """
            UPDATE run_groups
               SET status=?, summary=?, updated_at=?
             WHERE run_group_id=?
            """,
            (
                status or current["status"],
                summary if summary is not None else current["summary"],
                _now(),
                run_group_id,
            ),
        )
        self._conn.commit()

    def runs(self, run_group_id: str) -> list[dict[str, Any]]:
        if not run_group_id:
            return []
        self._ensure_row_factory()
        rows = self._conn.execute(
            "SELECT * FROM runs WHERE run_group_id=? ORDER BY created_at ASC",
            (run_group_id,),
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def remove_run_ids(self, run_group_id: str, run_ids: set[str]) -> None:
        if not run_group_id or not run_ids:
            return
        try:
            group = self.get(run_group_id)
        except KeyError:
            return
        child_run_ids = [
            str(item)
            for item in group.get("child_run_ids") or []
            if str(item) and str(item) not in run_ids
        ]
        remaining_count = self._conn.execute(
            "SELECT COUNT(*) AS count FROM runs WHERE run_group_id=?",
            (run_group_id,),
        ).fetchone()
        if not child_run_ids or int(remaining_count["count"] if remaining_count else 0) <= 0:
            self.delete(run_group_id)
            return
        self._conn.execute(
            """
            UPDATE run_groups
               SET child_run_ids_json=?, updated_at=?
             WHERE run_group_id=?
            """,
            (_json_dump(child_run_ids), _now(), run_group_id),
        )

    def delete(self, run_group_id: str) -> None:
        if not run_group_id:
            return
        self._conn.execute("DELETE FROM run_groups WHERE run_group_id=?", (run_group_id,))


class RunRepository:
    """Source of truth for native run lifecycle rows."""

    def __init__(
        self,
        conn: _LockedConnection,
        *,
        ensure_row_factory: Any,
        row_to_run: Any,
        accepting_runs: Any,
        sync_projections: Any,
        append_run_to_group: Any,
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._row_to_run = row_to_run
        self._accepting_runs = accepting_runs
        self._sync_projections = sync_projections
        self._append_run_to_group = append_run_to_group

    def list(self, limit: int = 50) -> dict[str, Any]:
        self._ensure_row_factory()
        rows = self._conn.execute(
            """
            SELECT runs.*, run_groups.source AS run_group_source
             FROM runs
              LEFT JOIN run_groups ON run_groups.run_group_id = runs.run_group_id
             WHERE NOT (
                runs.kind = 'agent_run'
                AND runs.run_group_id != ''
                AND EXISTS (
                    SELECT 1
                      FROM runs workflow_parent
                     WHERE workflow_parent.run_group_id = runs.run_group_id
                       AND workflow_parent.kind = 'workflow_run'
                )
             )
             ORDER BY runs.updated_at DESC
             LIMIT ?
            """,
            (max(1, min(int(limit or 50), 200)),),
        ).fetchall()
        return {"ok": True, "runs": [self._row_to_run(row) for row in rows]}

    def get(self, run_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._row_to_run(row)

    def pending_approval_json(self, run_id: str) -> str:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT pending_approval_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return str(row["pending_approval_json"] or "{}")

    def by_client_request_id(self, client_request_id: str) -> dict[str, Any] | None:
        clean_id = str(client_request_id or "").strip()
        if not clean_id:
            return None
        self._ensure_row_factory()
        row = self._conn.execute(
            "SELECT * FROM runs WHERE client_request_id=? LIMIT 1",
            (clean_id,),
        ).fetchone()
        if row is None:
            return None
        run = self._row_to_run(row)
        run["idempotent"] = True
        return run

    def insert(
        self,
        *,
        kind: str,
        runnable_id: str,
        user_goal: str,
        run_group_id: str = "",
        client_request_id: str = "",
    ) -> dict[str, Any]:
        if not self._accepting_runs():
            raise AgentRuntimeError("Native Runtime 正在关闭，暂不接受新的 Run")
        run_id = f"{kind}_{uuid4().hex[:12]}"
        now = _now()
        clean_client_request_id = str(client_request_id or "").strip()[:128]
        self._conn.execute(
            """
            INSERT INTO runs (
                run_id, run_group_id, client_request_id, kind, runnable_id, status, user_goal, result,
                timeline_json, artifacts_json, pending_approval_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run_group_id,
                clean_client_request_id,
                kind,
                runnable_id,
                "running",
                redact_secrets(user_goal),
                "",
                "[]",
                "[]",
                "{}",
                now,
                now,
            ),
        )
        self._conn.commit()
        self._append_run_to_group(run_group_id, run_id)
        return self.get(run_id)

    def update(
        self,
        run_id: str,
        *,
        status: str | None = None,
        result: str | None = None,
        timeline: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        pending_approval: dict[str, Any] | None | object = _UNSET,
    ) -> dict[str, Any]:
        current = self.get(run_id)
        if pending_approval is _UNSET:
            pending_approval_json = self.pending_approval_json(run_id)
            next_pending_approval = _json_load(pending_approval_json, {})
        else:
            next_pending_approval = _redact_json_value(pending_approval or {})
            pending_approval_json = _json_dump(next_pending_approval)
        safe_result = redact_secrets(result) if result is not None else current["result"]
        safe_timeline = _redact_json_value(timeline if timeline is not None else current["timeline"])
        safe_artifacts = _redact_json_value(artifacts if artifacts is not None else current["artifacts"])
        next_status = status or current["status"]
        self._conn.execute(
            """
            UPDATE runs
               SET status=?, result=?, timeline_json=?, artifacts_json=?, pending_approval_json=?, updated_at=?
             WHERE run_id=?
            """,
            (
                next_status,
                safe_result,
                _json_dump(safe_timeline),
                _json_dump(safe_artifacts),
                pending_approval_json,
                _now(),
                run_id,
            ),
        )
        self._sync_projections(
            run_id,
            status=next_status,
            artifacts=safe_artifacts,
            pending_approval=next_pending_approval if isinstance(next_pending_approval, dict) else {},
        )
        self._conn.commit()
        return self.get(run_id)

    def delete_rows(self, runs: list[dict[str, Any]], *, delete_artifacts: Any) -> list[str]:
        deleted_run_ids: list[str] = []
        for run in runs:
            run_id = str(run.get("run_id") or "")
            if not run_id:
                continue
            if callable(delete_artifacts):
                delete_artifacts(run)
            self._conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
            deleted_run_ids.append(run_id)
        return deleted_run_ids


class ApprovalCoordinator:
    """Coordinates approval lifecycle transitions and replayable facts."""

    def __init__(self, *, timeline_factory: Any, append_run_event: Any, update_run: Any) -> None:
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run

    def approve_tool_run(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        tool_name: str,
        input_preview: dict[str, Any],
        resumed_detail: str,
        running_result: str,
    ) -> dict[str, Any]:
        display_tool = str(tool_name or "tool").strip() or "tool"
        event_payload = {
            "tool": display_tool,
            "input_preview": input_preview,
            "status": "completed",
        }
        timeline.append(
            self._timeline(
                "agent.tool.approval_approved",
                display_tool,
                input_preview=input_preview,
                status="completed",
            )
        )
        self._append_run_event(run_id, "agent.tool.approval_approved", event_payload)
        timeline.append(
            self._timeline(
                "agent.run.resumed",
                resumed_detail,
                status="running",
            )
        )
        return self._update_run(
            run_id,
            status="running",
            result=running_result,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )

    def approve_workflow_node(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        result_context: str,
        workflow_node_id: str,
        label: str,
        criteria: str,
        input_preview: dict[str, Any],
    ) -> dict[str, Any]:
        event_payload = {
            "workflow_node_id": workflow_node_id,
            "workflow_node_kind": "approval",
            "workflow_node_label": label,
            "workflow_node_approval_criteria": criteria,
            "input_preview": input_preview,
            "status": "completed",
        }
        timeline.append(
            self._timeline(
                "workflow.node.approval_approved",
                label,
                **event_payload,
            )
        )
        self._append_run_event(run_id, "workflow.node.approval_approved", event_payload)
        return self._update_run(
            run_id,
            status="running",
            result=result_context,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )

    def reject_workflow_node(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        reason: str,
        workflow_node_id: str,
        label: str,
        criteria: str,
        input_preview: dict[str, Any],
    ) -> dict[str, Any]:
        detail = redact_secrets(reason).strip() or f"{label} approval rejected"
        timeline_payload = {
            "workflow_node_id": workflow_node_id,
            "workflow_node_kind": "approval",
            "workflow_node_label": label,
            "workflow_node_approval_criteria": criteria,
            "input_preview": input_preview,
            "status": "cancelled",
        }
        event_payload = {**timeline_payload, "reason": detail}
        timeline.append(
            self._timeline(
                "workflow.node.approval_rejected",
                detail,
                **timeline_payload,
            )
        )
        timeline.append(
            self._timeline(
                "workflow.run.cancelled",
                detail,
                **timeline_payload,
            )
        )
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"Workflow 审批已拒绝：{detail}",
            timeline=timeline,
            pending_approval=None,
        )
        self._append_run_event(run_id, "workflow.node.approval_rejected", event_payload)
        self._append_run_event(run_id, "workflow.run.cancelled", event_payload)
        return result

    def reject_tool_run(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        reason: str,
        tool_name: str,
        input_preview: dict[str, Any],
    ) -> dict[str, Any]:
        timeline_tool = str(tool_name or "").strip()
        display_tool = timeline_tool or "tool"
        detail = redact_secrets(reason).strip() or "Tool approval rejected"
        timeline.append(
            self._timeline(
                "agent.tool.approval_rejected",
                detail,
                tool=timeline_tool,
                input_preview=input_preview,
                status="cancelled",
            )
        )
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"工具审批已拒绝：{detail}",
            timeline=timeline,
            pending_approval=None,
        )
        self._append_run_event(
            run_id,
            "agent.tool.approval_rejected",
            {
                "tool": display_tool,
                "input_preview": input_preview,
                "reason": detail,
                "status": "cancelled",
            },
        )
        self._append_run_event(
            run_id,
            "agent.run.cancelled",
            {
                "reason": detail,
                "result": str(result.get("result") or ""),
            },
        )
        return result

    def timeout_workflow_node(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        reason: str,
        workflow_node_id: str,
        label: str,
        criteria: str,
        input_preview: dict[str, Any],
    ) -> dict[str, Any]:
        detail = redact_secrets(reason).strip() or "approval_wait_timeout"
        timeline_payload = {
            "workflow_node_id": workflow_node_id,
            "workflow_node_kind": "approval",
            "workflow_node_label": label,
            "workflow_node_approval_criteria": criteria,
            "input_preview": input_preview,
            "status": "cancelled",
        }
        event_payload = {
            **timeline_payload,
            "reason": detail,
            "tool": "workflow.approval",
        }
        timeline.append(
            self._timeline(
                "workflow.node.approval_timeout",
                detail,
                **timeline_payload,
            )
        )
        timeline.append(
            self._timeline(
                "workflow.run.cancelled",
                detail,
                **timeline_payload,
            )
        )
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"Workflow 审批已超时：{detail}",
            timeline=timeline,
            pending_approval=None,
        )
        self._append_run_event(run_id, "approval.timeout", event_payload)
        self._append_run_event(run_id, "workflow.run.cancelled", event_payload)
        return result

    def timeout_tool_run(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        reason: str,
        tool_name: str,
        input_preview: dict[str, Any],
    ) -> dict[str, Any]:
        timeline_tool = str(tool_name or "").strip()
        display_tool = timeline_tool or "tool"
        detail = redact_secrets(reason).strip() or "approval_wait_timeout"
        timeline.append(
            self._timeline(
                "agent.tool.approval_timeout",
                detail,
                tool=timeline_tool,
                input_preview=input_preview,
                status="cancelled",
            )
        )
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"工具审批已超时：{detail}",
            timeline=timeline,
            pending_approval=None,
        )
        self._append_run_event(
            run_id,
            "approval.timeout",
            {
                "tool": display_tool,
                "input_preview": input_preview,
                "reason": detail,
                "status": "cancelled",
            },
        )
        return result


@dataclass
class ToolApprovalResumeContext:
    """Private execution context needed to resume an approved tool call."""

    run_id: str
    timeline: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    broker: ToolBroker
    allowed_tools: list[str]
    budget: _RunBudget
    messages: list[dict[str, Any]]
    tool_request: dict[str, Any]
    tool_name: str
    input_preview: dict[str, Any]
    remaining_requests: list[dict[str, Any]]
    next_iteration: int


class ApprovalResumeCoordinator:
    """Executes the approved tool portion of a paused run resume."""

    def __init__(
        self,
        *,
        call_agent_tool: Any,
        fatal_tool_failure_detail: Any,
        append_tool_result_message: Any,
        run_tool_requests: Any,
        timeline_factory: Any,
        continue_custom_api_agent: Any | None = None,
    ) -> None:
        self._call_agent_tool = call_agent_tool
        self._fatal_tool_failure_detail = fatal_tool_failure_detail
        self._append_tool_result_message = append_tool_result_message
        self._run_tool_requests = run_tool_requests
        self._timeline = timeline_factory
        self._continue_custom_api_agent = continue_custom_api_agent

    def execute_approved_tool(self, context: ToolApprovalResumeContext) -> None:
        tool_result = self._call_agent_tool(
            context.tool_request,
            context.allowed_tools,
            context.broker,
            context.timeline,
            artifacts=context.artifacts,
            approved=True,
            run_id=context.run_id,
            budget=context.budget,
        )
        fatal_failure = self._fatal_tool_failure_detail(
            context.tool_name,
            context.tool_request,
            tool_result,
        )
        if fatal_failure:
            context.timeline.append(
                self._timeline(
                    "agent.tool.failed",
                    context.tool_name or "tool",
                    input_preview=context.input_preview,
                    result=tool_result,
                    status="failed",
                )
            )
            raise AgentRuntimeError(fatal_failure)
        self._append_tool_result_message(context.messages, context.tool_request, tool_result)
        self._run_tool_requests(
            context.remaining_requests,
            context.allowed_tools,
            context.broker,
            context.messages,
            context.timeline,
            context.artifacts,
            next_iteration=context.next_iteration,
            run_id=context.run_id,
            budget=context.budget,
        )

    def continue_custom_api_agent_after_approved_tool(
        self,
        agent: dict[str, Any],
        context: ToolApprovalResumeContext,
    ) -> str:
        if self._continue_custom_api_agent is None:
            raise AgentRuntimeError(
                "Approval resume coordinator is missing custom API continuation"
            )
        self.execute_approved_tool(context)
        return self._continue_custom_api_agent(
            agent,
            "",
            context.broker,
            context.timeline,
            context.artifacts,
            messages=context.messages,
            start_iteration=context.next_iteration,
            run_id=context.run_id,
            budget=context.budget,
        )


class WorkflowParentResumeCoordinator:
    """Coordinates parent Workflow updates after a child Run changes state."""

    def __init__(
        self,
        *,
        parent_runs_waiting_for_child: Any,
        workflow_run_is_group_root: Any,
        workflow_child_node_context: Any,
        merge_workflow_child_run_outcome: Any,
        workflow_for_run_resume: Any,
        workflow_resume_start_index: Any,
        continue_workflow_run: Any,
        timeline_factory: Any,
        append_run_event: Any,
        update_run: Any,
        update_run_group: Any,
    ) -> None:
        self._parent_runs_waiting_for_child = parent_runs_waiting_for_child
        self._workflow_run_is_group_root = workflow_run_is_group_root
        self._workflow_child_node_context = workflow_child_node_context
        self._merge_workflow_child_run_outcome = merge_workflow_child_run_outcome
        self._workflow_for_run_resume = workflow_for_run_resume
        self._workflow_resume_start_index = workflow_resume_start_index
        self._continue_workflow_run = continue_workflow_run
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run
        self._update_run_group = update_run_group

    def mark_child_running(self, child_run: dict[str, Any]) -> None:
        for workflow_run in self._parent_runs_waiting_for_child(child_run):
            self._mark_parent_child_running(workflow_run, child_run)

    def resume_after_child_update(self, child_run: dict[str, Any]) -> None:
        for workflow_run in self._parent_runs_waiting_for_child(child_run):
            self.resume_parent_after_child_update(workflow_run, child_run)

    @staticmethod
    def _child_artifact_count(artifacts: list[dict[str, Any]], child_run_id: str) -> int:
        return sum(
            1
            for artifact in artifacts
            if isinstance(artifact, dict)
            and artifact.get("kind") == "workflow_child_artifact"
            and str(artifact.get("source_run_id") or "") == child_run_id
        )

    @staticmethod
    def _timeline_has_child_event(timeline: list[dict[str, Any]], event_name: str, child_run_id: str) -> bool:
        if not child_run_id:
            return False
        return any(
            event.get("event") == event_name
            and str(event.get("child_run_id") or "") == child_run_id
            for event in timeline
            if isinstance(event, dict)
        )

    def _append_child_agent_state_event(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
        child_node_info: dict[str, str],
        artifacts: list[dict[str, Any]],
    ) -> None:
        child_run_id = str(child_run.get("run_id") or "")
        if not child_run_id:
            return
        status = str(child_run.get("status") or "")
        payload = {
            "child_run_id": child_run_id,
            "status": status,
            "result": _tool_input_preview(child_run.get("result") or status, limit=1800),
            "artifact_count": self._child_artifact_count(artifacts, child_run_id),
            **child_node_info,
        }
        self._append_run_event(
            str(workflow_run["run_id"]),
            "workflow.node.agent",
            payload,
        )

    def _mark_parent_child_running(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
    ) -> None:
        root_group = self._workflow_run_is_group_root(workflow_run)
        timeline = [
            event
            for event in workflow_run.get("timeline") or []
            if isinstance(event, dict)
        ]
        artifacts = [item for item in workflow_run.get("artifacts") or [] if isinstance(item, dict)]
        child_label, child_node_info = self._workflow_child_node_context(timeline, child_run)
        child_run_id = str(child_run.get("run_id") or "")
        self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, child_label)
        child_resumed_payload = {
            "child_run_id": child_run_id,
            "status": "running",
            **child_node_info,
        }
        already_child_resumed = self._timeline_has_child_event(
            timeline,
            "workflow.run.child_resumed",
            child_run_id,
        )
        if not already_child_resumed:
            self._append_child_agent_state_event(
                workflow_run,
                child_run,
                child_node_info,
                artifacts,
            )
            timeline.append(
                self._timeline(
                    "workflow.run.child_resumed",
                    f"{child_label} approved and resumed",
                    **child_resumed_payload,
                )
            )
            self._append_run_event(
                str(workflow_run["run_id"]),
                "workflow.run.child_resumed",
                child_resumed_payload,
            )
        result_text = f"{child_label} 已批准，正在继续执行"
        result = self._update_run(
            str(workflow_run["run_id"]),
            status="running",
            result=result_text,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )
        if root_group:
            self._update_run_group(
                str(result.get("run_group_id") or ""),
                status="running",
                summary=result_text,
            )

    def resume_parent_after_child_update(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
    ) -> dict[str, Any]:
        root_group = self._workflow_run_is_group_root(workflow_run)
        timeline = [
            event
            for event in workflow_run.get("timeline") or []
            if isinstance(event, dict)
        ]
        artifacts = [item for item in workflow_run.get("artifacts") or [] if isinstance(item, dict)]
        child_status = str(child_run.get("status") or "")
        child_result = str(child_run.get("result") or "")
        child_run_id = str(child_run.get("run_id") or "")
        run_group_id = str(workflow_run.get("run_group_id") or "")
        if child_status == "completed" and self._timeline_has_child_event(
            timeline,
            "workflow.run.resumed",
            child_run_id,
        ):
            return workflow_run
        if child_status == "approval_required" and self._timeline_has_child_event(
            timeline,
            "workflow.run.approval_required",
            child_run_id,
        ):
            if (
                str(workflow_run.get("status") or "") == "approval_required"
                and str(workflow_run.get("result") or "") == child_result
            ):
                return workflow_run
        terminal_child_status = "cancelled" if child_status == "cancelled" else "failed"
        if child_status not in {"completed", "approval_required"} and self._timeline_has_child_event(
            timeline,
            f"workflow.run.{terminal_child_status}",
            child_run_id,
        ):
            return workflow_run
        child_label, child_node_info = self._workflow_child_node_context(timeline, child_run)
        self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, child_label)
        if child_status == "approval_required":
            self._append_child_agent_state_event(
                workflow_run,
                child_run,
                child_node_info,
                artifacts,
            )
            event_payload = {
                "child_run_id": child_run_id,
                "status": "approval_required",
                **child_node_info,
            }
            timeline.append(
                self._timeline(
                    "workflow.run.approval_required",
                    child_label,
                    **event_payload,
                )
            )
            self._append_run_event(
                str(workflow_run["run_id"]),
                "workflow.run.approval_required",
                event_payload,
            )
            result = self._update_run(
                str(workflow_run["run_id"]),
                status="approval_required",
                result=child_result,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(
                    run_group_id,
                    status="approval_required",
                    summary=child_result,
                )
            return result
        if child_status != "completed":
            status = terminal_child_status
            detail = (
                f"{child_run.get('runnable_name') or child_run.get('runnable_id')}: "
                f"{child_result}"
            )
            self._append_child_agent_state_event(
                workflow_run,
                child_run,
                child_node_info,
                artifacts,
            )
            timeline.append(
                self._timeline(
                    f"workflow.run.{status}",
                    detail,
                    child_run_id=child_run_id,
                    status=child_status,
                    **child_node_info,
                )
            )
            self._append_run_event(
                str(workflow_run["run_id"]),
                f"workflow.run.{status}",
                {
                    "child_run_id": child_run_id,
                    "status": child_status,
                    "result": _tool_input_preview(child_result or child_status, limit=1800),
                    **child_node_info,
                },
            )
            result = self._update_run(
                str(workflow_run["run_id"]),
                status=status,
                result=child_result,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(run_group_id, status=status, summary=child_result)
            return result
        try:
            workflow = self._workflow_for_run_resume(workflow_run)
            start_index = self._workflow_resume_start_index(workflow, workflow_run, child_run_id)
            if start_index is None:
                return workflow_run
            self._append_child_agent_state_event(
                workflow_run,
                child_run,
                child_node_info,
                artifacts,
            )
            resumed_payload = {"child_run_id": child_run_id, "status": "running", **child_node_info}
            timeline.append(
                self._timeline(
                    "workflow.run.resumed",
                    "Workflow resumed after child Agent approval",
                    **resumed_payload,
                )
            )
            self._append_run_event(
                str(workflow_run["run_id"]),
                "workflow.run.resumed",
                resumed_payload,
            )
            return self._continue_workflow_run(
                workflow_run,
                workflow,
                context=child_result,
                timeline=timeline,
                artifacts=artifacts,
                start_index=start_index,
                root_group=root_group,
            )
        except Exception as exc:
            failed_event_extra = dict(child_node_info)
            if child_run_id:
                failed_event_extra["child_run_id"] = child_run_id
            if child_status:
                failed_event_extra["child_run_status"] = child_status
            safe_error = redact_api_error_text(exc)
            timeline.append(
                self._timeline(
                    "workflow.run.failed",
                    safe_error,
                    status="failed",
                    **failed_event_extra,
                )
            )
            result = self._update_run(
                str(workflow_run["run_id"]),
                status="failed",
                result=safe_error,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(run_group_id, status="failed", summary=safe_error)
            return result


class WorkflowContinuationCoordinator:
    """Executes Workflow nodes for a Workflow Run."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def continue_run(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        *,
        context: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        start_index: int,
        root_group: bool,
    ) -> dict[str, Any]:
        engine = self._engine
        run_group_id = str(run.get("run_group_id") or "")
        current_node_info: dict[str, str] = {}
        try:
            workflow_goal = str(run.get("user_goal") or context)
            has_agent_upstream = max(0, start_index) > 0
            path = engine._workflow_path(workflow)
            for index, node in enumerate(path[max(0, start_index) :], start=max(0, start_index)):
                kind = engine._node_kind(node)
                label = str((node.get("data") or {}).get("label") or node.get("id"))
                current_node_info = {
                    "workflow_node_id": str(node.get("id") or ""),
                    "workflow_node_kind": kind,
                    "workflow_node_label": label,
                }
                if kind == "start":
                    start_payload = {
                        "workflow_node_id": str(node.get("id") or ""),
                        "workflow_node_kind": kind,
                        "workflow_node_label": label,
                        "status": "completed",
                    }
                    timeline.append(
                        engine._timeline(
                            "workflow.node.start",
                            label,
                            workflow_node_id=start_payload["workflow_node_id"],
                            status="completed",
                        )
                    )
                    engine.append_run_event(
                        str(run["run_id"]),
                        "workflow.node.start",
                        start_payload,
                    )
                    continue
                if kind == "agent":
                    result = self._run_agent_node(
                        run,
                        node,
                        label=label,
                        kind=kind,
                        workflow_goal=workflow_goal,
                        context=context,
                        has_agent_upstream=has_agent_upstream,
                        run_group_id=run_group_id,
                        timeline=timeline,
                        artifacts=artifacts,
                        root_group=root_group,
                    )
                    if result.get("done"):
                        return result["run"]
                    context = str(result.get("context") or "")
                    has_agent_upstream = True
                    continue
                if kind == "approval":
                    return self._pause_for_approval_node(
                        run,
                        node,
                        label=label,
                        kind=kind,
                        context=context,
                        run_group_id=run_group_id,
                        timeline=timeline,
                        artifacts=artifacts,
                        root_group=root_group,
                        node_index=index,
                    )
                if kind == "artifact":
                    self._write_artifact_node(
                        run,
                        node,
                        label=label,
                        kind=kind,
                        context=context,
                        artifacts=artifacts,
                        timeline=timeline,
                    )
                    continue
                raise AgentRuntimeError(f"未知 Workflow 节点类型：{kind}")
            timeline.append(engine._timeline("workflow.run.completed", "Workflow run completed"))
            engine.append_run_event(str(run["run_id"]), "workflow.run.completed", {"result": context})
            result = engine._update_run(
                str(run["run_id"]),
                status="completed",
                result=context,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                engine._update_run_group(run_group_id, status="completed", summary=context)
                result = engine.get_run(result["run_id"])
            return result
        except Exception as exc:
            safe_error = redact_secrets(exc)
            safe_node_info = {
                key: redact_secrets(value)
                for key, value in current_node_info.items()
            }
            timeline.append(engine._timeline("workflow.run.failed", safe_error, status="failed", **safe_node_info))
            engine.append_run_event(
                str(run["run_id"]),
                "workflow.run.failed",
                {"error": safe_error, **safe_node_info},
            )
            result = engine._update_run(
                str(run["run_id"]),
                status="failed",
                result=safe_error,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                engine._update_run_group(run_group_id, status="failed", summary=safe_error)
                result = engine.get_run(result["run_id"])
            return result

    def resume_after_approval_node(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        *,
        context: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        start_index: int,
        root_group: bool,
        workflow_node_id: str,
        label: str,
        criteria: str,
        input_preview: dict[str, Any],
    ) -> dict[str, Any]:
        engine = self._engine
        run_id = str(run["run_id"])
        running = engine.approvals.approve_workflow_node(
            run_id,
            timeline=timeline,
            artifacts=artifacts,
            result_context=context,
            workflow_node_id=workflow_node_id,
            label=label,
            criteria=criteria,
            input_preview=input_preview,
        )
        if root_group:
            engine._update_run_group(
                str(run.get("run_group_id") or ""),
                status="running",
                summary=context,
            )
            running = engine.get_run(run_id)
        return self.continue_run(
            running,
            workflow,
            context=context,
            timeline=timeline,
            artifacts=artifacts,
            start_index=start_index,
            root_group=root_group,
        )

    def _run_agent_node(
        self,
        run: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        workflow_goal: str,
        context: str,
        has_agent_upstream: bool,
        run_group_id: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
    ) -> dict[str, Any]:
        engine = self._engine
        data = node.get("data") or {}
        agent = engine._workflow_agent_for_node(node)
        agent_id = str(agent.get("agent_id") or data.get("agent_id") or data.get("agentId") or "")
        step_task = engine._workflow_node_task(node)
        child_goal = engine._workflow_child_goal(workflow_goal, step_task)
        agent_upstream = context if has_agent_upstream else ""
        child = engine._insert_run(
            kind="agent_run",
            runnable_id=agent_id,
            user_goal=child_goal,
            run_group_id=run_group_id,
        )
        child = engine._execute_agent_run(
            child["run_id"],
            agent,
            child_goal,
            upstream=agent_upstream,
        )
        next_context = child["result"]
        agent_payload = {
            "workflow_node_id": str(node.get("id") or ""),
            "workflow_node_kind": kind,
            "workflow_node_label": label,
            "workflow_node_task": step_task,
            "child_run_id": child["run_id"],
            "status": child["status"],
            "result": _tool_input_preview(child.get("result") or "", limit=1800),
            "artifact_count": len(engine._workflow_child_artifact_refs(child, label)),
        }
        timeline.append(
            engine._timeline(
                "workflow.node.agent",
                label,
                **agent_payload,
            )
        )
        engine.append_run_event(str(run["run_id"]), "workflow.node.agent", agent_payload)
        engine._merge_workflow_child_run_outcome(timeline, artifacts, child, label)
        if child["status"] == "approval_required":
            event_payload = {
                "workflow_node_id": str(node.get("id") or ""),
                "workflow_node_kind": kind,
                "workflow_node_label": label,
                "child_run_id": child["run_id"],
                "status": "approval_required",
            }
            timeline.append(
                engine._timeline(
                    "workflow.run.approval_required",
                    label,
                    **event_payload,
                )
            )
            engine.append_run_event(
                str(run["run_id"]),
                "workflow.run.approval_required",
                event_payload,
            )
            result = engine._update_run(
                str(run["run_id"]),
                status="approval_required",
                result=next_context,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                engine._update_run_group(
                    run_group_id,
                    status="approval_required",
                    summary=next_context,
                )
                result = engine.get_run(result["run_id"])
            return {"done": True, "run": result}
        if child["status"] != "completed":
            status = "cancelled" if child["status"] == "cancelled" else "failed"
            detail = f"{label}: {next_context or child['status']}"
            timeline.append(
                engine._timeline(
                    f"workflow.run.{status}",
                    detail,
                    workflow_node_id=str(node.get("id") or ""),
                    workflow_node_kind=kind,
                    workflow_node_label=label,
                    child_run_id=child["run_id"],
                    status=child["status"],
                )
            )
            engine.append_run_event(
                str(run["run_id"]),
                f"workflow.run.{status}",
                {
                    "workflow_node_id": str(node.get("id") or ""),
                    "workflow_node_kind": kind,
                    "workflow_node_label": label,
                    "child_run_id": child["run_id"],
                    "status": child["status"],
                    "result": _tool_input_preview(next_context or child["status"], limit=1800),
                },
            )
            result = engine._update_run(
                str(run["run_id"]),
                status=status,
                result=next_context,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                engine._update_run_group(run_group_id, status=status, summary=next_context)
                result = engine.get_run(result["run_id"])
            return {"done": True, "run": result}
        return {"done": False, "context": next_context}

    def _pause_for_approval_node(
        self,
        run: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        context: str,
        run_group_id: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
        node_index: int,
    ) -> dict[str, Any]:
        engine = self._engine
        criteria = engine._workflow_approval_criteria(node)
        pending = {
            "approval_id": f"approval_{uuid4().hex[:12]}",
            "tool": "workflow.approval",
            "input_preview": {
                "checkpoint": label,
                "context": _tool_input_preview(context),
                **({"criteria": criteria} if criteria else {}),
            },
            "requested_at": _now(),
            "workflow_context": context,
            "workflow_next_index": node_index + 1,
            "workflow_node_id": str(node.get("id") or ""),
            "workflow_node_label": label,
            "workflow_node_approval_criteria": criteria,
        }
        timeline.append(
            engine._timeline(
                "workflow.node.approval_required",
                label,
                workflow_node_id=str(node.get("id") or ""),
                workflow_node_kind=kind,
                workflow_node_label=label,
                workflow_node_approval_criteria=criteria,
                status="approval_required",
                pending_approval=_public_pending_approval(pending),
            )
        )
        engine.append_run_event(
            str(run["run_id"]),
            "workflow.node.approval_required",
            {
                "workflow_node_id": str(node.get("id") or ""),
                "workflow_node_kind": kind,
                "workflow_node_label": label,
                "workflow_node_approval_criteria": criteria,
                "status": "approval_required",
                "pending_approval": _public_pending_approval(pending),
            },
        )
        result = engine._update_run(
            str(run["run_id"]),
            status="approval_required",
            result=f"等待审批：{label}",
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=pending,
        )
        if root_group:
            engine._update_run_group(
                run_group_id,
                status="approval_required",
                summary=f"等待审批：{label}",
            )
            result = engine.get_run(result["run_id"])
        return result

    def _write_artifact_node(
        self,
        run: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        context: str,
        artifacts: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
    ) -> None:
        engine = self._engine
        data = node.get("data") or {}
        broker = ToolBroker(
            engine._default_workspace_policy(),
            engine.workflow_artifacts_dir / str(run["run_id"]),
        )
        workflow_node_id = str(node.get("id") or "")
        artifact_path = engine._workflow_artifact_path(
            label,
            artifacts,
            str(data.get("artifact_path") or data.get("artifactPath") or ""),
        )
        artifact = broker.artifact_write(artifact_path, context)
        artifacts.append(
            {
                "kind": "workflow_artifact",
                "workflow_node_id": workflow_node_id,
                "workflow_node_label": label,
                **artifact,
            }
        )
        artifact_payload = {
            "workflow_node_id": workflow_node_id,
            "workflow_node_kind": kind,
            "workflow_node_label": label,
            "status": "completed",
            "artifact": artifact,
        }
        timeline.append(
            engine._timeline(
                "workflow.node.artifact",
                label,
                **artifact_payload,
            )
        )
        engine.append_run_event(str(run["run_id"]), "workflow.node.artifact", artifact_payload)


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
        )
        self.run_groups = RunGroupRepository(
            self._conn,
            ensure_row_factory=self._ensure_row_factory,
            row_to_run_group=self._row_to_run_group,
            row_to_run=self._row_to_run,
        )
        self.runs = RunRepository(
            self._conn,
            ensure_row_factory=self._ensure_row_factory,
            row_to_run=self._row_to_run,
            accepting_runs=lambda: self._accepting_runs,
            sync_projections=self._sync_run_projections,
            append_run_to_group=self._append_run_to_group,
        )
        self.run_events = RunEventRepository(self._conn, self._db_lock, ensure_run_exists=self.get_run)
        self.run_approvals = ApprovalRepository(self._conn, self._db_lock)
        self.run_artifacts = RunArtifactRepository(
            self._conn,
            agent_artifacts_dir=self.agent_artifacts_dir,
            workflow_artifacts_dir=self.workflow_artifacts_dir,
            get_run=self.get_run,
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
            continue_custom_api_agent=self._run_custom_api_agent,
        )
        self.workflow_continuation = WorkflowContinuationCoordinator(self)
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
            continue_workflow_run=lambda run, workflow, **kwargs: self.workflow_continuation.continue_run(run, workflow, **kwargs),
            timeline_factory=lambda event, detail="", **extra: self._timeline(event, detail, **extra),
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            update_run_group=lambda run_group_id, **kwargs: self._update_run_group(run_group_id, **kwargs),
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
            CREATE TABLE IF NOT EXISTS runtime_schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        scrubbed_agent_credentials = self._ensure_runtime_columns()
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
        if scrubbed_agent_credentials:
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
        return self._migrate_agent_model_credentials()

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
        clean_key = str(item_key or "").strip()
        if not clean_key:
            return
        self._conn.execute(
            """
            INSERT INTO studio_deletions (item_type, item_key, deleted_at)
            VALUES (?, ?, ?)
            ON CONFLICT(item_type, item_key) DO UPDATE SET deleted_at=excluded.deleted_at
            """,
            (item_type, clean_key, _now()),
        )

    def _clear_studio_deletion(self, item_type: str, item_key: str) -> None:
        self._conn.execute(
            "DELETE FROM studio_deletions WHERE item_type=? AND item_key=?",
            (item_type, str(item_key or "").strip()),
        )

    def _has_studio_deletion(self, item_type: str, item_key: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM studio_deletions WHERE item_type=? AND item_key=?",
            (item_type, str(item_key or "").strip()),
        ).fetchone()
        return row is not None

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
        tools = ["artifact.write"]
        if category in {"coding", "review"}:
            tools = ["workspace.list", "workspace.read", "workspace.write_patch", "terminal.run", "artifact.write"]
        elif category in {"research", "design", "office", "orchestrator"}:
            tools = ["workspace.list", "workspace.read", "artifact.write"]
        return {
            "allowed_tools": tools,
            "approval_required": {"terminal.run": True, "workspace.write_patch": True},
        }

    @staticmethod
    def _default_workspace_policy() -> dict[str, Any]:
        return {"default_workdir": "", "readable_scopes": ["."], "writable_scopes": []}

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
        raw_path = str(path or "").strip()
        if not raw_path:
            raise AgentRuntimeError("trusted workspace 路径不能为空")
        try:
            resolved = Path(raw_path).expanduser().resolve()
        except OSError as exc:
            raise AgentRuntimeError(f"trusted workspace 路径无效：{exc}") from exc
        if not resolved.exists() or not resolved.is_dir():
            raise AgentRuntimeError("trusted workspace 必须是已存在目录")
        now = _now()
        self._conn.execute(
            """
            INSERT INTO trusted_workspaces (path, source, trusted_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            (str(resolved), str(source or "runtime")[:120], now, now),
        )
        if commit:
            self._conn.commit()
        return {"path": str(resolved), "source": str(source or "runtime")[:120], "trusted_at": now}

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
        try:
            self.trust_workspace(workdir, source=source, commit=commit)
        except AgentRuntimeError:
            return

    def list_trusted_workspaces(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT path, source, trusted_at, updated_at FROM trusted_workspaces ORDER BY updated_at DESC"
        ).fetchall()
        return {
            "ok": True,
            "workspaces": [
                {
                    "path": str(row["path"]),
                    "source": str(row["source"] or ""),
                    "trusted_at": str(row["trusted_at"] or ""),
                    "updated_at": str(row["updated_at"] or ""),
                }
                for row in rows
            ],
        }

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
        raw = policy if isinstance(policy, dict) else {}
        default_policy = self._default_tool_policy(category)
        allowed = raw.get("allowed_tools")
        if isinstance(allowed, str):
            allowed = [allowed]
        if not isinstance(allowed, list):
            allowed = default_policy["allowed_tools"]
        normalized_allowed = []
        for tool in allowed:
            name = str(tool or "").strip()
            if name in _KNOWN_AGENT_TOOLS and name not in normalized_allowed:
                normalized_allowed.append(name)

        raw_approval = raw.get("approval_required")
        approval_required = dict(raw_approval) if isinstance(raw_approval, dict) else {}
        for tool in _HIGH_RISK_AGENT_TOOLS:
            if tool in normalized_allowed:
                approval_required[tool] = True
            else:
                approval_required.pop(tool, None)
        return {"allowed_tools": normalized_allowed, "approval_required": approval_required}

    def _compile_workspace_policy(self, policy: Any = None) -> dict[str, Any]:
        raw = policy if isinstance(policy, dict) else {}
        default_policy = self._default_workspace_policy()
        readable = raw.get("readable_scopes", default_policy["readable_scopes"])
        writable = raw.get("writable_scopes", default_policy["writable_scopes"])
        if isinstance(readable, str):
            readable = [item.strip() for item in readable.split(",") if item.strip()]
        if isinstance(writable, str):
            writable = [item.strip() for item in writable.split(",") if item.strip()]
        if not isinstance(readable, list):
            readable = default_policy["readable_scopes"]
        if not isinstance(writable, list):
            writable = default_policy["writable_scopes"]
        return {
            "default_workdir": str(raw.get("default_workdir") or "").strip(),
            "readable_scopes": [str(item or ".").strip() or "." for item in readable],
            "writable_scopes": [str(item or "").strip() for item in writable if str(item or "").strip()],
        }

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
        self._ensure_row_factory()
        cursor = self._conn.execute("SELECT * FROM agents ORDER BY category, name")
        rows = cursor.fetchall()
        return {
            "ok": True,
            "agents": [
                self._main_chat_virtual_agent(),
                *[
                    self._row_to_agent(self._coerce_named_row(row, cursor.description))
                    for row in rows
                ],
            ],
        }

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        if str(agent_id or "").strip() == _MAIN_CHAT_AGENT_ID:
            return self._main_chat_virtual_agent()
        self._ensure_row_factory()
        cursor = self._conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,))
        row = cursor.fetchone()
        if row is None:
            raise KeyError(agent_id)
        return self._row_to_agent(self._coerce_named_row(row, cursor.description))

    def _get_agent_private(self, agent_id: str) -> dict[str, Any]:
        if str(agent_id or "").strip() == _MAIN_CHAT_AGENT_ID:
            agent = self._main_chat_virtual_agent()
            return {
                **agent,
                "model_config": {
                    **agent["model_config"],
                    "credential_ref": "",
                    "api_key": "",
                },
            }
        self._ensure_row_factory()
        cursor = self._conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,))
        row = cursor.fetchone()
        if row is None:
            raise KeyError(agent_id)
        return self._row_to_agent_private(self._coerce_named_row(row, cursor.description))

    def create_agent(self, payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        self._ensure_global_name_available(name)
        self._validate_agent_profile_refs(payload)
        now = _now()
        agent_id = str(payload.get("agent_id") or f"agent_{_slug(name, 'agent')}_{uuid4().hex[:8]}")
        if agent_id in _SYSTEM_AGENT_IDS:
            raise AgentRuntimeError("系统 Agent 不能创建或覆盖")
        model_config = payload.get("model_config") or {}
        category = str(payload.get("category") or "custom")
        model_mode = str(payload.get("model_mode") or "profile")
        execution_backend = _normalize_execution_backend(payload.get("execution_backend"), model_mode=model_mode)
        tool_policy = self._compile_tool_policy(category, payload.get("tool_policy"))
        workspace_policy = self._compile_workspace_policy(payload.get("workspace_policy"))
        workspace_policy = self._assign_default_agent_workdir(agent_id, workspace_policy, tool_policy)
        self._trust_workspace_from_policy(workspace_policy, source=f"agent:{agent_id}", commit=False)
        api_key = str(model_config.get("api_key") or "").strip()
        credential_ref = self._agent_model_credential_ref(agent_id) if api_key else ""
        if api_key:
            self._store_credential(credential_ref, api_key)
        try:
            self._conn.execute(
                """
                INSERT INTO agents (
                    agent_id, name, nickname, description, avatar_url, category, instructions, persona_prompt,
                    model_mode, execution_backend, model_profile_id, vision_model_profile_id, model_provider,
                    model_base_url, model_name, model_api_key, model_credential_ref,
                    tool_policy_json, workspace_policy_json, skill_ids_json, output_contract,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    name,
                    str(payload.get("nickname") or name),
                    str(payload.get("description") or ""),
                    str(payload.get("avatar_url") or ""),
                    category,
                    str(payload.get("instructions") or ""),
                    str(payload.get("persona_prompt") or ""),
                    model_mode,
                    execution_backend,
                    str(payload.get("model_profile_id") or ""),
                    str(payload.get("vision_model_profile_id") or ""),
                    str(model_config.get("provider") or "openai_compatible"),
                    str(model_config.get("base_url") or ""),
                    str(model_config.get("model") or ""),
                    "",
                    credential_ref,
                    _json_dump(tool_policy),
                    _json_dump(workspace_policy),
                    _json_dump(payload.get("skill_ids") or []),
                    str(payload.get("output_contract") or "chat"),
                    1 if payload.get("enabled", True) else 0,
                    now,
                    now,
                ),
            )
        except sqlite3.Error:
            self._delete_credential(credential_ref)
            raise
        if not seed:
            self._clear_studio_deletion("agent", agent_id)
        self._conn.commit()
        return self.get_agent(agent_id)

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if str(agent_id or "").strip() in _SYSTEM_AGENT_IDS:
            raise AgentRuntimeError("系统 Agent 不能修改")
        current = self._get_agent_private(agent_id)
        if "name" in payload:
            self._ensure_global_name_available(str(payload.get("name") or ""), ignore_agent_id=agent_id)
        next_agent = {**current, **{key: value for key, value in payload.items() if key not in {"model_config"}}}
        self._validate_agent_profile_refs(next_agent)
        model_config = {**current.get("model_config", {}), **(payload.get("model_config") or {})}
        api_key = str(model_config.get("api_key") or "")
        if "model_config" in payload and "api_key" not in payload.get("model_config", {}):
            api_key = str(current.get("model_config", {}).get("api_key") or "")
        if "model_config" in payload and "api_key" in payload.get("model_config", {}) and not api_key:
            api_key = str(current.get("model_config", {}).get("api_key") or "")
        credential_ref = str(current.get("model_config", {}).get("credential_ref") or "").strip()
        if api_key:
            credential_ref = credential_ref or self._agent_model_credential_ref(agent_id)
            self._store_credential(credential_ref, api_key)
        now = _now()
        category = str(next_agent.get("category") or "custom")
        model_mode = str(next_agent.get("model_mode") or "profile")
        execution_backend = _normalize_execution_backend(next_agent.get("execution_backend"), model_mode=model_mode)
        tool_policy = self._compile_tool_policy(category, next_agent.get("tool_policy"))
        workspace_policy = self._compile_workspace_policy(next_agent.get("workspace_policy"))
        workspace_policy = self._assign_default_agent_workdir(agent_id, workspace_policy, tool_policy)
        self._trust_workspace_from_policy(workspace_policy, source=f"agent:{agent_id}", commit=False)
        self._conn.execute(
            """
            UPDATE agents
               SET name=?, nickname=?, description=?, avatar_url=?, category=?, instructions=?, persona_prompt=?,
                   model_mode=?, execution_backend=?, model_profile_id=?, vision_model_profile_id=?, model_provider=?,
                   model_base_url=?, model_name=?, model_api_key='', model_credential_ref=?,
                   tool_policy_json=?, workspace_policy_json=?, skill_ids_json=?, output_contract=?,
                   enabled=?, updated_at=?
             WHERE agent_id=?
            """,
            (
                str(next_agent.get("name") or ""),
                str(next_agent.get("nickname") or next_agent.get("name") or ""),
                str(next_agent.get("description") or ""),
                str(next_agent.get("avatar_url") or ""),
                category,
                str(next_agent.get("instructions") or ""),
                str(next_agent.get("persona_prompt") or ""),
                model_mode,
                execution_backend,
                str(next_agent.get("model_profile_id") or ""),
                str(next_agent.get("vision_model_profile_id") or ""),
                str(model_config.get("provider") or "openai_compatible"),
                str(model_config.get("base_url") or ""),
                str(model_config.get("model") or ""),
                credential_ref,
                _json_dump(tool_policy),
                _json_dump(workspace_policy),
                _json_dump(next_agent.get("skill_ids") or []),
                str(next_agent.get("output_contract") or "chat"),
                1 if next_agent.get("enabled", True) else 0,
                now,
                agent_id,
            ),
        )
        self._conn.commit()
        return self.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        if str(agent_id or "").strip() in _SYSTEM_AGENT_IDS:
            raise AgentRuntimeError("系统 Agent 不能删除")
        row = self._conn.execute("SELECT model_credential_ref FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if self._conn.execute("SELECT 1 FROM agents WHERE agent_id=?", (agent_id,)).fetchone() is not None:
            self._record_studio_deletion("agent", agent_id)
        self._conn.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
        self._conn.commit()
        if row is not None:
            self._delete_credential(str(row["model_credential_ref"] or ""))
        return {"ok": True}

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
        self._ensure_row_factory()
        rows = self._conn.execute(
            """
            SELECT f.*,
                   COUNT(s.skill_id) AS skill_count,
                   SUM(CASE WHEN s.source_type IN ('native_global', 'native_project') THEN 0 ELSE 1 END) AS installed_count,
                   SUM(CASE WHEN s.source_type IN ('native_global', 'native_project') THEN 1 ELSE 0 END) AS native_count
              FROM skill_folders f
              LEFT JOIN skills s ON s.folder_id = f.folder_id
             GROUP BY f.folder_id
             ORDER BY f.sort_order ASC, LOWER(f.name) ASC
            """
        ).fetchall()
        uncategorized = self._conn.execute(
            """
            SELECT COUNT(*) AS skill_count,
                   SUM(CASE WHEN source_type IN ('native_global', 'native_project') THEN 0 ELSE 1 END) AS installed_count,
                   SUM(CASE WHEN source_type IN ('native_global', 'native_project') THEN 1 ELSE 0 END) AS native_count
              FROM skills
             WHERE folder_id = ''
            """
        ).fetchone()
        return {
            "ok": True,
            "folders": [self._row_to_skill_folder(row) for row in rows],
            "uncategorized": {
                "folder_id": "",
                "name": "Uncategorized",
                "description": "",
                "source_scope": "all",
                "sort_order": -1,
                "skill_count": int(uncategorized["skill_count"] or 0),
                "installed_count": int(uncategorized["installed_count"] or 0),
                "native_count": int(uncategorized["native_count"] or 0),
            },
        }

    def create_skill_folder(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise AgentRuntimeError("文件夹名称不能为空")
        self._validate_skill_folder_name(name)
        folder_id = str(payload.get("folder_id") or f"folder_{_slug(name, 'folder')}_{uuid4().hex[:6]}").strip()
        folder_id = _slug(folder_id, "folder")
        if not folder_id.startswith("folder_"):
            folder_id = f"folder_{folder_id}"
        description = str(payload.get("description") or "").strip()[:1000]
        source_scope = str(payload.get("source_scope") or "all")
        if source_scope not in {"all", "installed", "native"}:
            source_scope = "all"
        sort_order = int(payload.get("sort_order") or 0)
        now = _now()
        try:
            self._conn.execute(
                """
                INSERT INTO skill_folders (
                    folder_id, name, description, source_scope, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (folder_id, name, description, source_scope, sort_order, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise AgentRuntimeError("Skill 文件夹已存在") from exc
        self._conn.commit()
        return self.get_skill_folder(folder_id)

    def get_skill_folder(self, folder_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute(
            """
            SELECT f.*,
                   COUNT(s.skill_id) AS skill_count,
                   SUM(CASE WHEN s.source_type IN ('native_global', 'native_project') THEN 0 ELSE 1 END) AS installed_count,
                   SUM(CASE WHEN s.source_type IN ('native_global', 'native_project') THEN 1 ELSE 0 END) AS native_count
              FROM skill_folders f
              LEFT JOIN skills s ON s.folder_id = f.folder_id
             WHERE f.folder_id=?
             GROUP BY f.folder_id
            """,
            (folder_id,),
        ).fetchone()
        if row is None:
            raise KeyError(folder_id)
        return self._row_to_skill_folder(row)

    def update_skill_folder(self, folder_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_skill_folder(folder_id)
        name = str(payload.get("name") if "name" in payload else current["name"]).strip()
        if not name:
            raise AgentRuntimeError("文件夹名称不能为空")
        self._validate_skill_folder_name(name, current_folder_id=folder_id)
        description = str(payload.get("description") if "description" in payload else current["description"]).strip()[:1000]
        source_scope = str(payload.get("source_scope") if "source_scope" in payload else current["source_scope"])
        if source_scope not in {"all", "installed", "native"}:
            source_scope = "all"
        sort_order = int(payload.get("sort_order") if "sort_order" in payload else current["sort_order"])
        self._conn.execute(
            """
            UPDATE skill_folders
               SET name=?, description=?, source_scope=?, sort_order=?, updated_at=?
             WHERE folder_id=?
            """,
            (name, description, source_scope, sort_order, _now(), folder_id),
        )
        self._conn.commit()
        return self.get_skill_folder(folder_id)

    def delete_skill_folder(self, folder_id: str, *, delete_skills: bool = False) -> dict[str, Any]:
        self.get_skill_folder(folder_id)
        deleted_skill_count = 0
        if delete_skills:
            self._ensure_row_factory()
            rows = self._conn.execute("SELECT skill_id FROM skills WHERE folder_id=?", (folder_id,)).fetchall()
            for row in rows:
                self.delete_skill(str(row["skill_id"]))
                deleted_skill_count += 1
            self._conn.execute("DELETE FROM skill_folders WHERE folder_id=?", (folder_id,))
            self._conn.commit()
            return {"ok": True, "deleted_skill_count": deleted_skill_count}
        now = _now()
        self._conn.execute("UPDATE skills SET folder_id='', updated_at=? WHERE folder_id=?", (now, folder_id))
        self._conn.execute("DELETE FROM skill_folders WHERE folder_id=?", (folder_id,))
        self._conn.commit()
        return {"ok": True, "deleted_skill_count": 0}

    def list_skills(self) -> dict[str, Any]:
        self._ensure_row_factory()
        self._repair_native_skill_references()
        self._repair_installed_skill_provenance()
        rows = self._conn.execute(
            """
            SELECT s.*, f.name AS folder_name
              FROM skills s
              LEFT JOIN skill_folders f ON f.folder_id = s.folder_id
             ORDER BY s.updated_at DESC
            """
        ).fetchall()
        return {"ok": True, "skills": [self._row_to_skill(row) for row in rows]}

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
        self._ensure_row_factory()
        self._repair_native_skill_references()
        self._repair_installed_skill_provenance()
        row = self._conn.execute(
            """
            SELECT s.*, f.name AS folder_name
              FROM skills s
              LEFT JOIN skill_folders f ON f.folder_id = s.folder_id
             WHERE s.skill_id=?
            """,
            (skill_id,),
        ).fetchone()
        if row is None:
            raise KeyError(skill_id)
        return self._row_to_skill(row)

    def import_skill(self, source_path: str, folder_id: str | None = None) -> dict[str, Any]:
        source = Path(source_path).expanduser()
        if not source.exists():
            raise AgentRuntimeError("Skill 路径不存在")
        target_folder_id = self._normalize_skill_folder_id(folder_id)
        temp_dir: Path | None = None
        source_type = "local_dir"
        source_ref = source.name
        origin_path = str(source.resolve())
        if source.is_file():
            if source.suffix.lower() != ".zip":
                raise AgentRuntimeError("Skill 文件只支持 ZIP")
            source_type = "local_zip"
            temp_dir = self.workspace_dir / "skill-import-tmp" / uuid4().hex
            temp_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(source) as archive:
                for member in archive.infolist():
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise AgentRuntimeError("ZIP 包含路径穿越项，已拒绝导入")
                archive.extractall(temp_dir)
            roots = [child for child in temp_dir.iterdir() if child.is_dir()]
            source_root = temp_dir
            if not (source_root / "SKILL.md").exists() and len(roots) == 1:
                source_root = roots[0]
        else:
            source_root = source
        try:
            imported = self._import_skill_root(
                source_root,
                source_path=f"local:{source.name}",
                source_type=source_type,
                origin_path=origin_path,
                source_ref=source_ref,
                sync_status="imported",
                folder_id=target_folder_id,
            )
            self._clear_studio_deletion(
                "skill_source",
                self._skill_deletion_key(source_type, origin_path),
            )
            self._conn.commit()
            return imported
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

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
        for root_spec in root_specs:
            root = root_spec["path"]
            source_type = str(root_spec["source_type"])
            if source_type not in _SKILL_SOURCE_TYPES:
                source_type = "local_dir"
            if not root.exists():
                results.append({
                    "source": str(root),
                    "source_type": source_type,
                    "library": library,
                    "status": "skipped",
                    "message": "Skills root 不存在",
                })
                continue
            skill_files = sorted(root.rglob("SKILL.md"))
            if not skill_files:
                results.append({
                    "source": str(root),
                    "source_type": source_type,
                    "library": library,
                    "status": "skipped",
                    "message": "未发现 SKILL.md",
                })
                continue
            skill_ancestors = {path.parent for path in skill_files}
            for child in sorted(item for item in root.iterdir() if item.is_dir()):
                if not any(child == parent or child in parent.parents for parent in skill_ancestors):
                    results.append({
                        "source": str(child),
                        "source_type": source_type,
                        "library": library,
                        "status": "skipped",
                        "message": "目录中未发现 SKILL.md",
                    })
            for skill_md in skill_files:
                source_root = skill_md.parent
                try:
                    source_ref = source_root.relative_to(root).as_posix()
                except ValueError:
                    source_ref = source_root.name
                source_map = root_spec.get("source_map") if isinstance(root_spec.get("source_map"), dict) else {}
                source_ref = str(
                    source_map.get(source_root.name)
                    or source_map.get(source_ref)
                    or root_spec.get("source_ref_override")
                    or source_ref
                )
                deletion_key = self._skill_deletion_key(source_type, str(source_root.resolve()))
                has_deletion = self._has_studio_deletion("skill_source", deletion_key)
                restore_deletion = restore_deleted and has_deletion
                if has_deletion and not restore_deletion:
                    results.append({
                        "source": str(source_root),
                        "source_type": source_type,
                        "library": library,
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
                        "library": library,
                        "source_ref": source_ref,
                        "status": result["sync_status"],
                        "skill_id": result["skill_id"],
                        "name": result["name"],
                    })
                except AgentRuntimeError as exc:
                    results.append({
                        "source": str(source_root),
                        "source_type": source_type,
                        "library": library,
                        "source_ref": source_ref,
                        "status": "failed",
                        "message": redact_api_error_text(exc),
                    })
        summary = {
            "imported": sum(1 for item in results if item.get("status") == "imported"),
            "updated": sum(1 for item in results if item.get("status") == "updated"),
            "skipped": sum(1 for item in results if item.get("status") == "skipped"),
            "failed": sum(1 for item in results if item.get("status") == "failed"),
        }
        roots_info = [
            {
                "path": str(root["path"]),
                "source_type": root["source_type"],
                "library": library,
                "exists": root["path"].exists(),
                "skill_count": self._count_skill_files(root["path"]),
            }
            for root in root_specs
        ]
        return {"ok": summary["failed"] == 0, "roots": roots_info, "summary": summary, "results": results}

    def install_skill_command(self, command: str, folder_id: str | None = None) -> dict[str, Any]:
        argv, installer = self._validated_skill_install_argv(command)
        target_folder_id = self._normalize_skill_folder_id(folder_id)
        source_ref = self._skill_install_source_ref(argv, installer)
        started_at = _now()
        env = _scrubbed_subprocess_env({"OHA_YACHIYO_HOME": str(self.skill_installs_native_home)})
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
        if source_type not in _SKILL_SOURCE_TYPES:
            raise AgentRuntimeError("未知 Skill 来源类型")
        skill_md = source_root / "SKILL.md"
        if not skill_md.is_file():
            raise AgentRuntimeError("Skill 根目录必须包含 SKILL.md")
        markdown = _read_text(skill_md)
        metadata = _parse_skill_frontmatter(markdown)
        source_ref = self._metadata_skill_source_ref(metadata, source_ref)
        name = self._skill_name(markdown, source_root.name)
        name = str(metadata.get("name") or name)[:120] or source_root.name
        description = self._skill_description(markdown)
        description = str(metadata.get("description") or description)[:240]
        content_hash = _skill_content_hash(source_root)
        existing = self._find_existing_skill(origin_path, content_hash, source_type)
        summary = self._skill_summary(markdown)
        now = _now()
        last_synced_at = synced_at or (now if source_type not in {"local_dir", "local_zip"} else "")
        target_folder_id = self._normalize_skill_folder_id(folder_id) if folder_id is not None else ""
        if existing is None:
            skill_id = f"skill_{_slug(name, 'skill')}_{uuid4().hex[:8]}"
            target = self.skills_dir / skill_id if copy_to_managed else source_root
            if copy_to_managed:
                shutil.copytree(source_root, target)
            asset_paths = self._skill_asset_paths(target)
            self._conn.execute(
                """
                INSERT INTO skills (
                    skill_id, name, description, source_path, local_path, folder_id, source_type, origin_path,
                    source_ref, content_hash, last_synced_at, sync_status, content_summary,
                    skill_markdown, asset_paths_json, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    skill_id,
                    name,
                    description,
                    source_path,
                    str(target.resolve()),
                    target_folder_id,
                    source_type,
                    origin_path,
                    source_ref,
                    content_hash,
                    last_synced_at,
                    sync_status,
                    summary,
                    markdown,
                    _json_dump(asset_paths),
                    1,
                    now,
                    now,
                ),
            )
            final_status = "imported"
        elif existing["content_hash"] == content_hash:
            skill_id = str(existing["skill_id"])
            target = Path(str(existing["local_path"] or self.skills_dir / skill_id))
            next_local_path = str(target.resolve()) if copy_to_managed else origin_path
            if not copy_to_managed:
                self._remove_managed_copy_if_safe(target, origin_path)
            next_folder_id = target_folder_id if folder_id is not None else existing["folder_id"]
            self._conn.execute(
                """
                UPDATE skills
                   SET source_path=?, local_path=?, source_type=?, origin_path=?, source_ref=?,
                       folder_id=?, last_synced_at=?, sync_status=?
                 WHERE skill_id=?
                """,
                (
                    source_path if existing["origin_path"] == origin_path else existing["source_path"],
                    next_local_path if existing["origin_path"] == origin_path else existing["local_path"],
                    source_type if existing["origin_path"] == origin_path else existing["source_type"],
                    origin_path if existing["origin_path"] == origin_path else existing["origin_path"],
                    source_ref if existing["origin_path"] == origin_path else existing["source_ref"],
                    next_folder_id,
                    last_synced_at or existing["last_synced_at"],
                    "skipped",
                    skill_id,
                ),
            )
            final_status = "skipped"
        else:
            skill_id = str(existing["skill_id"])
            target = Path(str(existing["local_path"] or self.skills_dir / skill_id))
            if copy_to_managed and target.exists():
                shutil.rmtree(target, ignore_errors=True)
            elif not copy_to_managed:
                self._remove_managed_copy_if_safe(target, origin_path)
                target = source_root
            if copy_to_managed:
                shutil.copytree(source_root, target)
            asset_paths = self._skill_asset_paths(target)
            next_folder_id = target_folder_id if folder_id is not None else existing["folder_id"]
            self._conn.execute(
                """
                UPDATE skills
                   SET name=?, description=?, source_path=?, local_path=?, folder_id=?, source_type=?, origin_path=?,
                       source_ref=?, content_hash=?, last_synced_at=?, sync_status=?, content_summary=?,
                       skill_markdown=?, asset_paths_json=?, updated_at=?
                 WHERE skill_id=?
                """,
                (
                    name,
                    description,
                    source_path,
                    str(target.resolve()),
                    next_folder_id,
                    source_type,
                    origin_path,
                    source_ref,
                    content_hash,
                    last_synced_at,
                    sync_status,
                    summary,
                    markdown,
                    _json_dump(asset_paths),
                    now,
                    skill_id,
                ),
            )
            final_status = "updated"
        self._conn.commit()
        skill = self.get_skill(skill_id)
        skill["sync_status"] = final_status
        return skill

    def _find_existing_skill(self, origin_path: str, content_hash: str, source_type: str) -> sqlite3.Row | None:
        self._ensure_row_factory()
        library_condition = (
            "source_type IN ('native_global', 'native_project')"
            if _is_native_library_source_type(source_type)
            else "source_type NOT IN ('native_global', 'native_project')"
        )
        if origin_path:
            row = self._conn.execute(
                f"SELECT * FROM skills WHERE origin_path=? AND {library_condition}",
                (origin_path,),
            ).fetchone()
            if row is not None:
                return row
        if content_hash:
            return self._conn.execute(
                f"SELECT * FROM skills WHERE content_hash=? AND {library_condition}",
                (content_hash,),
            ).fetchone()
        return None

    def _remove_managed_copy_if_safe(self, path: Path, origin_path: str) -> None:
        try:
            resolved = path.resolve()
            origin = Path(origin_path).resolve()
        except OSError:
            return
        if resolved == origin:
            return
        if _is_within(resolved, self.skills_dir) and resolved.exists():
            shutil.rmtree(resolved, ignore_errors=True)

    def _skill_path_owned_by_runtime(self, path: Path) -> bool:
        return _is_within(path, self.skills_dir) or _is_within(path, self.skill_installs_dir)

    def _repair_native_skill_references(self) -> None:
        rows = self._conn.execute(
            """
            SELECT skill_id, local_path, origin_path
              FROM skills
             WHERE source_type IN ('native_global', 'native_project')
               AND origin_path != ''
               AND local_path != origin_path
            """
        ).fetchall()
        if not rows:
            return
        for row in rows:
            old_local_path = Path(str(row["local_path"] or ""))
            origin_path = str(row["origin_path"])
            self._remove_managed_copy_if_safe(old_local_path, origin_path)
            self._conn.execute(
                """
                UPDATE skills
                   SET local_path=?, updated_at=?
                 WHERE skill_id=?
                """,
                (origin_path, _now(), row["skill_id"]),
            )
        self._conn.commit()

    def _repair_installed_skill_provenance(self) -> None:
        source_map = self._installed_skill_source_map()
        if not source_map:
            return
        self._ensure_row_factory()
        rows = self._conn.execute(
            """
            SELECT skill_id, local_path, origin_path, source_ref, source_type
             FROM skills
             WHERE source_type='npx_skills'
            """
        ).fetchall()
        changed = False
        for row in rows:
            keys = []
            for raw_path in (row["local_path"], row["origin_path"]):
                if raw_path:
                    keys.append(Path(str(raw_path)).name)
            if row["source_ref"]:
                keys.append(str(row["source_ref"]))
            next_ref = next((source_map[key] for key in keys if key in source_map), "")
            if next_ref and next_ref != row["source_ref"]:
                self._conn.execute(
                    """
                    UPDATE skills
                       SET source_ref=?, source_path=?, updated_at=?
                     WHERE skill_id=?
                    """,
                    (next_ref, f"{row['source_type']}:{next_ref}", _now(), row["skill_id"]),
                )
                changed = True
        if changed:
            self._conn.commit()

    def _native_skill_root_specs(self, roots: list[Any] | None = None) -> list[dict[str, Any]]:
        if roots is None:
            raw_roots: list[Any] = [
                {"path": _native_skill_home() / "skills", "source_type": "native_global"},
            ]
        else:
            raw_roots = roots
        specs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_roots:
            if isinstance(item, dict):
                path = Path(str(item.get("path") or "")).expanduser()
                source_type = _normalize_skill_source_type(item.get("source_type") or self._infer_native_source_type(path))
            else:
                path = Path(str(item)).expanduser()
                source_type = self._infer_native_source_type(path)
            if source_type not in _NATIVE_LIBRARY_SOURCE_TYPES:
                source_type = "native_global"
            key = str(path.resolve()) if path.exists() else str(path)
            if not key or key in seen:
                continue
            seen.add(key)
            specs.append({"path": path, "source_type": source_type})
        return specs

    def _installed_skill_root_specs(self, *, source_type: str, source_ref_override: str = "") -> list[dict[str, Any]]:
        roots = [
            self.skill_installs_dir / ".skills" / "skills",
            self.skill_installs_native_home / "skills",
        ]
        source_map = self._installed_skill_source_map()
        return [
            {
                "path": root,
                "source_type": source_type,
                "source_map": source_map,
                "source_ref_override": source_ref_override,
            }
            for root in roots
        ]

    def _installed_skill_source_map(self) -> dict[str, str]:
        lock_path = self.skill_installs_dir / "skills-lock.json"
        if not lock_path.is_file():
            return {}
        try:
            data = _json_load(lock_path.read_text(encoding="utf-8"), {})
        except OSError:
            return {}
        raw_skills = data.get("skills") if isinstance(data, dict) else {}
        if not isinstance(raw_skills, dict):
            return {}
        source_map: dict[str, str] = {}
        for skill_name, raw_entry in raw_skills.items():
            if not isinstance(raw_entry, dict):
                continue
            source_ref = self._skill_lock_source_ref(raw_entry)
            if not source_ref:
                continue
            source_map[str(skill_name)] = source_ref
            skill_path = str(raw_entry.get("skillPath") or "")
            if skill_path:
                source_map[Path(skill_path).parent.name] = source_ref
        return source_map

    @staticmethod
    def _skill_lock_source_ref(entry: dict[str, Any]) -> str:
        source = str(entry.get("source") or "").strip()
        source_type = str(entry.get("sourceType") or "").strip().lower()
        skill_path = str(entry.get("skillPath") or "").strip()
        if source_type == "github" and re.fullmatch(r"[^/\s]+/[^/\s]+", source):
            if skill_path:
                return f"https://github.com/{source}/blob/main/{skill_path}"
            return f"https://github.com/{source}"
        return " · ".join(part for part in [source, skill_path] if part)

    @staticmethod
    def _infer_native_source_type(path: Path) -> str:
        project_root = Path.cwd() / ".oha-yachiyo" / "skills"
        try:
            if path.resolve() == project_root.resolve():
                return "native_project"
        except OSError:
            pass
        return "native_global"

    @staticmethod
    def _count_skill_files(root: Path) -> int:
        if not root.exists():
            return 0
        return sum(1 for _ in root.rglob("SKILL.md"))

    def _validated_skill_install_argv(self, command: str) -> tuple[list[str], str]:
        if not command.strip():
            raise AgentRuntimeError("请输入 Skill 来源或安装命令")
        if any(token in command for token in _SHELL_METACHARS):
            raise AgentRuntimeError("Skill 安装命令不能包含 shell 管道、重定向或串联操作")
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise AgentRuntimeError("Skill 安装命令格式无效") from exc
        if not argv:
            raise AgentRuntimeError("请输入 Skill 来源或安装命令")
        if re.fullmatch(r"skills(@[A-Za-z0-9._~-]+)?", argv[0]):
            argv = ["npx", *argv]
        if argv[0] == "npx":
            return self._validated_npx_skills_argv(argv), "npx_skills"
        if argv[0] in {"npm", "pnpm", "yarn", "bun", "curl", "bash", "sh", "zsh"}:
            raise AgentRuntimeError("只允许 skills 来源或 npx skills add")
        return self._validated_npx_skills_argv(["npx", "skills@latest", "add", *argv]), "npx_skills"

    @staticmethod
    def _skill_install_source_ref(argv: list[str], installer: str) -> str:
        if installer != "npx_skills":
            return ""
        index = 1
        while index < len(argv) and argv[index] in {"-y", "--yes"}:
            index += 1
        if index + 1 >= len(argv):
            return ""
        install_args = argv[index + 2:]
        clean_args: list[str] = []
        skip_next = False
        for arg in install_args:
            if skip_next:
                skip_next = False
                continue
            if arg in {"-a", "--agent"}:
                skip_next = True
                continue
            if arg.startswith("--agent=") or arg in {"--copy", "-y", "--yes"}:
                continue
            clean_args.append(arg)
        if not clean_args:
            return ""
        if re.fullmatch(r"[^/\s]+/[^/\s]+", clean_args[0]):
            clean_args[0] = f"https://github.com/{clean_args[0]}"
        return " ".join(clean_args)

    @staticmethod
    def _metadata_skill_source_ref(metadata: dict[str, Any], fallback: str) -> str:
        for key in ("source", "repository", "repo", "homepage", "url", "origin"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return fallback

    @staticmethod
    def _validated_npx_skills_argv(argv: list[str]) -> list[str]:
        normalized = list(argv)
        index = 1
        while index < len(normalized) and normalized[index] in {"-y", "--yes"}:
            index += 1
        if index + 1 >= len(normalized) or not re.fullmatch(r"skills(@[A-Za-z0-9._~-]+)?", normalized[index]):
            raise AgentRuntimeError("只允许 Skill 来源、npx skills add 或 npx skills@latest add")
        if normalized[index + 1] not in {"add", "install"}:
            raise AgentRuntimeError("只允许 Skill 来源、npx skills add 或 npx skills@latest add")
        install_args = normalized[index + 2:]
        if not install_args:
            raise AgentRuntimeError("请提供要安装的 Skill 来源")
        NativeRunEngine._validate_skill_install_agent_target(install_args)
        if not NativeRunEngine._has_agent_target(install_args):
            normalized.extend(["-a", "oha-yachiyo"])
        if "--copy" not in install_args:
            normalized.append("--copy")
        if "-y" not in normalized and "--yes" not in normalized:
            normalized.append("-y")
        return normalized

    @staticmethod
    def _has_agent_target(args: list[str]) -> bool:
        return any(arg in {"-a", "--agent"} or arg.startswith("--agent=") for arg in args)

    @staticmethod
    def _validate_skill_install_agent_target(args: list[str]) -> None:
        for index, arg in enumerate(args):
            if arg == "-a" or arg == "--agent":
                value = args[index + 1] if index + 1 < len(args) else ""
                if value != "oha-yachiyo":
                    raise AgentRuntimeError("Yachiyo 安装入口固定使用 oha-yachiyo 目标")
            elif arg.startswith("--agent=") and arg != "--agent=oha-yachiyo":
                raise AgentRuntimeError("Yachiyo 安装入口固定使用 oha-yachiyo 目标")

    def _normalize_skill_folder_id(self, folder_id: str | None) -> str:
        clean = str(folder_id or "").strip()
        if not clean:
            return ""
        row = self._conn.execute("SELECT folder_id FROM skill_folders WHERE folder_id=?", (clean,)).fetchone()
        if row is None:
            raise AgentRuntimeError("Skill 文件夹不存在")
        return clean

    def _validate_skill_folder_name(self, name: str, *, current_folder_id: str = "") -> None:
        if len(name) > 120:
            raise AgentRuntimeError("Skill 文件夹名称不能超过 120 个字符")
        row = self._conn.execute(
            """
            SELECT folder_id
              FROM skill_folders
             WHERE LOWER(name)=LOWER(?)
               AND folder_id != ?
             LIMIT 1
            """,
            (name, current_folder_id),
        ).fetchone()
        if row is not None:
            raise AgentRuntimeError("Skill 文件夹已存在")

    def update_skill(self, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_skill(skill_id)
        if "enabled" not in payload and "folder_id" not in payload:
            return current
        enabled = payload.get("enabled") if "enabled" in payload else current.get("enabled", True)
        folder_id = self._normalize_skill_folder_id(payload.get("folder_id")) if "folder_id" in payload else current.get("folder_id", "")
        self._conn.execute(
            """
            UPDATE skills
               SET enabled=?, folder_id=?, updated_at=?
             WHERE skill_id=?
            """,
            (1 if enabled is not False else 0, folder_id, _now(), skill_id),
        )
        self._conn.commit()
        return self.get_skill(skill_id)

    @staticmethod
    def _skill_name(markdown: str, fallback: str) -> str:
        for line in markdown.splitlines():
            if line.startswith("# "):
                return line[2:].strip()[:120] or fallback
        return fallback or "Imported Skill"

    @staticmethod
    def _skill_description(markdown: str) -> str:
        for line in markdown.splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#"):
                return clean[:240]
        return ""

    @staticmethod
    def _skill_summary(markdown: str) -> str:
        lines = [line.strip() for line in markdown.splitlines() if line.strip() and not line.startswith("#")]
        return " ".join(lines)[:500]

    @staticmethod
    def _skill_asset_paths(root: Path) -> list[str]:
        paths: list[str] = []
        for folder in ("assets", "templates", "examples"):
            base = root / folder
            if not base.exists():
                continue
            for child in base.rglob("*"):
                if child.is_file():
                    paths.append(child.relative_to(root).as_posix())
        return sorted(paths)

    def delete_skill(self, skill_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        skill_row = self._conn.execute(
            "SELECT local_path, source_type, origin_path FROM skills WHERE skill_id=?",
            (skill_id,),
        ).fetchone()
        if skill_row is not None:
            self._record_studio_deletion(
                "skill_source",
                self._skill_deletion_key(str(skill_row["source_type"]), str(skill_row["origin_path"])),
            )
        self._conn.execute("DELETE FROM skills WHERE skill_id=?", (skill_id,))
        rows = self._conn.execute("SELECT agent_id, skill_ids_json FROM agents").fetchall()
        for row in rows:
            skill_ids = [item for item in _json_load(row["skill_ids_json"], []) if item != skill_id]
            self._conn.execute(
                "UPDATE agents SET skill_ids_json=?, updated_at=? WHERE agent_id=?",
                (_json_dump(skill_ids), _now(), row["agent_id"]),
            )
        self._conn.commit()
        source_type = str(skill_row["source_type"] if skill_row is not None else "")
        if not _is_native_library_source_type(source_type):
            local_path = Path(str(skill_row["local_path"])) if skill_row is not None and skill_row["local_path"] else self.skills_dir / skill_id
            if self._skill_path_owned_by_runtime(local_path):
                shutil.rmtree(local_path, ignore_errors=True)
        return {"ok": True}

    def list_workflows(self) -> dict[str, Any]:
        self._ensure_row_factory()
        rows = self._conn.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
        return {"ok": True, "workflows": [self._row_to_workflow(row) for row in rows]}

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT * FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
        if row is None:
            raise KeyError(workflow_id)
        return self._row_to_workflow(row)

    def create_workflow(self, payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        self._ensure_global_name_available(name)
        nodes = payload.get("nodes") or []
        edges = payload.get("edges") or []
        self.validate_workflow(nodes, edges)
        self._validate_workflow_agent_nodes(nodes)
        now = _now()
        workflow_id = str(payload.get("workflow_id") or f"workflow_{_slug(name, 'workflow')}_{uuid4().hex[:8]}")
        self._conn.execute(
            """
            INSERT INTO workflows (
                workflow_id, name, description, nodes_json, edges_json,
                default_input_schema_json, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workflow_id,
                name,
                str(payload.get("description") or ""),
                _json_dump(nodes),
                _json_dump(edges),
                _json_dump(payload.get("default_input_schema") or {}),
                1 if payload.get("enabled", True) else 0,
                now,
                now,
            ),
        )
        if not seed:
            self._clear_studio_deletion("workflow", workflow_id)
        self._conn.commit()
        return self.get_workflow(workflow_id)

    def update_workflow(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_workflow(workflow_id)
        next_payload = dict(payload)
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            self._ensure_global_name_available(name, ignore_workflow_id=workflow_id)
            next_payload["name"] = name
        next_workflow = {**current, **next_payload}
        self.validate_workflow(next_workflow.get("nodes") or [], next_workflow.get("edges") or [])
        self._validate_workflow_agent_nodes(next_workflow.get("nodes") or [])
        self._conn.execute(
            """
            UPDATE workflows
               SET name=?, description=?, nodes_json=?, edges_json=?,
                   default_input_schema_json=?, enabled=?, updated_at=?
             WHERE workflow_id=?
            """,
            (
                str(next_workflow.get("name") or ""),
                str(next_workflow.get("description") or ""),
                _json_dump(next_workflow.get("nodes") or []),
                _json_dump(next_workflow.get("edges") or []),
                _json_dump(next_workflow.get("default_input_schema") or {}),
                1 if next_workflow.get("enabled", True) else 0,
                _now(),
                workflow_id,
            ),
        )
        self._conn.commit()
        return self.get_workflow(workflow_id)

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        if self._conn.execute("SELECT 1 FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone() is not None:
            self._record_studio_deletion("workflow", workflow_id)
        self._conn.execute("DELETE FROM workflows WHERE workflow_id=?", (workflow_id,))
        self._conn.commit()
        return {"ok": True}

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
            if len(targets) > 1:
                raise AgentRuntimeError("Workflow v1 只允许线性流程，每个节点最多一个下一步")
        for node_id, sources in incoming.items():
            if node_id != start_id and len(sources) != 1:
                raise AgentRuntimeError("Workflow v1 不允许断链或多入口节点")
        seen: set[str] = set()
        active: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in active:
                raise AgentRuntimeError("Workflow 不能包含环")
            if node_id in seen:
                return
            active.add(node_id)
            for target in outgoing[node_id]:
                visit(target)
            active.remove(node_id)
            seen.add(node_id)

        visit(start_id)
        if seen != set(node_ids):
            raise AgentRuntimeError("Workflow v1 必须是一条从 Start 出发的单一路径")
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

    def _validate_workflow_agent_nodes(self, nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if self._node_kind(node) == "agent":
                self._workflow_agent_for_node(node)

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
            raise AgentRuntimeError("Workflow 至少需要一个可执行节点（Agent、Approval 或 Artifact）")

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

    def _sync_task_run_link_projection(
        self,
        run_id: str,
        *,
        status: str | None = None,
        last_event_sequence: int | None = None,
    ) -> None:
        self.task_run_links.sync_projection(
            run_id,
            status=status,
            last_event_sequence=last_event_sequence,
        )

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
        event = self.run_events.append(
            run_id,
            event_type,
            payload,
            actor=actor,
            visibility=visibility,
            sensitivity=sensitivity,
        )
        self._sync_task_run_link_projection(run_id, last_event_sequence=int(event.get("sequence") or 0))
        return event

    def list_run_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        return self.run_events.list(
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

    def _pending_approval_json(self, run_id: str) -> str:
        return self.runs.pending_approval_json(run_id)

    def _pending_approval_private(self, run_id: str) -> dict[str, Any]:
        pending = _json_load(self._pending_approval_json(run_id), {})
        return pending if isinstance(pending, dict) else {}

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
        return str(
            payload.get("client_run_id")
            or payload.get("client_request_id")
            or payload.get("idempotency_key")
            or ""
        ).strip()[:128]

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
        self._sync_task_run_link_projection(run_id, status=str(run.get("status") or ""))
        return run

    def _terminal_run_or_none(self, run_id: str) -> dict[str, Any] | None:
        try:
            run = self.get_run(run_id)
        except KeyError:
            return None
        status = str(run.get("status") or "").strip()
        return run if status in _FINAL_RUN_STATUSES else None

    def _sync_run_projections(
        self,
        run_id: str,
        *,
        status: str,
        artifacts: Any,
        pending_approval: dict[str, Any],
    ) -> None:
        self._sync_run_artifacts(run_id, artifacts)
        self._sync_run_approval(run_id, status=status, pending_approval=pending_approval)

    def _sync_run_artifacts(self, run_id: str, artifacts: Any) -> None:
        self.run_artifacts.sync(run_id, artifacts)

    def _sync_run_approval(self, run_id: str, *, status: str, pending_approval: dict[str, Any]) -> None:
        self.run_approvals.sync(run_id, status=status, pending_approval=pending_approval)

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
            self._timeline("task.linked", str(task_id or ""), task_id=str(task_id or "")),
        ]
        run = self._update_run(run["run_id"], timeline=timeline)
        self.append_run_event(
            run["run_id"],
            "run.started",
            {"task_id": str(task_id or ""), "session_id": str(session_id or "")},
        )
        self.append_run_event(
            run["run_id"],
            "task.linked",
            {"task_id": str(task_id or ""), "session_id": str(session_id or "")},
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
            {
                "profile_id": default_profile_id,
                "model": str(model_config.get("model") or ""),
                "capability": capability,
                "message_count": len(messages),
            },
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
        except Exception as exc:
            terminal = self._terminal_run_or_none(run_id)
            if terminal is not None:
                return str(terminal.get("result") or "")
            safe_error = redact_secrets(exc)
            timeline.append(self._timeline("model.request.failed", safe_error))
            self._update_run(run_id, timeline=timeline)
            self.append_run_event(run_id, "model.request.failed", {"error": safe_error})
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
            {"content": content, "output_chars": len(content), "truncated": output_truncated},
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
        raw = policy if isinstance(policy, dict) else {"allowed_tools": ["workspace.list", "workspace.read", "artifact.write"]}
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
            self._timeline(
                "agent.runtime.compiled",
                "Main chat NativeRunEngine compiled tools and workspace policy",
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
            {
                "profile_id": default_profile_id,
                "model": str(model_config.get("model") or ""),
                "capability": "chat",
                "message_count": len(messages),
            },
        )
        broker = ToolBroker(runtime["workspace_policy"], self.agent_artifacts_dir / run_id)
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
            timeline.append(
                self._timeline(
                    "agent.tool.approval_required",
                    str(pending.get("tool") or ""),
                    pending_approval=_public_pending_approval(pending),
                )
            )
            self.append_run_event(
                run_id,
                "agent.tool.approval_required",
                _public_pending_approval(pending),
            )
            return self._update_run(
                run_id,
                status="approval_required",
                result=f"等待审批：{pending.get('tool') or 'tool'}",
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=pending,
            )
        except Exception as exc:
            terminal = self._terminal_run_or_none(run_id)
            if terminal is not None:
                return terminal
            safe_error = redact_secrets(exc)
            timeline.append(self._timeline("model.request.failed", safe_error))
            self._update_run(run_id, status="failed", result=safe_error, timeline=timeline, artifacts=artifacts, pending_approval=None)
            self.append_run_event(run_id, "model.request.failed", {"error": safe_error})
            raise
        terminal = self._terminal_run_or_none(run_id)
        if terminal is not None:
            return terminal

        timeline.append(
            self._timeline(
                "model.output.ready",
                result_text[:500],
                output_chars=len(result_text),
                truncated=len(result_text) >= self.runtime_limits.max_model_output_chars,
            )
        )
        self.append_run_event(
            run_id,
            "model.output.completed",
            {"content": result_text, "output_chars": len(result_text)},
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
        self.append_run_event(run_id, "run.completed", {"result": safe_result})
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
        self.append_run_event(run_id, "run.failed", {"error": safe_error})
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
        category = str(agent.get("category") or "custom")
        tool_policy = self._compile_tool_policy(category, agent.get("tool_policy"))
        workspace_policy = self._compile_workspace_policy(agent.get("workspace_policy"))
        return {
            "runtime": "oha_agent",
            "tool_policy": tool_policy,
            "workspace_policy": workspace_policy,
            "progress_events": [
                "agent.run.started",
                "agent.runtime.compiled",
                "agent.model.response",
                "agent.tool.call",
                "agent.artifact.write",
                "agent.run.completed",
                "agent.run.failed",
            ],
        }

    def _agent_context(self, agent: dict[str, Any], user_goal: str, upstream: str = "") -> str:
        skills = self._load_agent_skills(agent.get("skill_ids") or [])
        runtime = self._compile_agent_runtime(agent)
        tool_policy = runtime["tool_policy"]
        workspace_policy = runtime["workspace_policy"]
        skill_blocks = []
        for skill in skills:
            skill_blocks.append(
                f"## Skill: {skill['name']}\n\n{skill['skill_markdown']}\n\n"
                f"Assets/Templates: {', '.join(skill.get('asset_paths') or []) or 'none'}"
            )
        return "\n\n".join(
            [
                f"# Agent\nName: {agent['name']}\nNickname: {agent.get('nickname') or agent['name']}\nCategory: {agent.get('category') or 'custom'}",
                f"# Functional Instructions\n{agent.get('instructions') or 'No extra functional instructions.'}",
                f"# Persona Prompt\n{agent.get('persona_prompt') or 'No persona override.'}",
                f"# Mounted Skills\n{chr(10).join(skill_blocks) if skill_blocks else 'No mounted skills.'}",
                "# Runtime\n"
                "Runtime: Oha Agent Runtime\n"
                f"Allowed tools: {', '.join(tool_policy.get('allowed_tools') or [])}\n"
                f"Approval required: {json.dumps(tool_policy.get('approval_required') or {}, ensure_ascii=False)}\n"
                f"Workspace: {json.dumps(workspace_policy, ensure_ascii=False)}",
                f"# Upstream Context\n{upstream or 'None'}",
                f"# User Goal\n{user_goal}",
                f"# Output Contract\n{_agent_output_contract_rules(agent.get('output_contract'))}",
            ]
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
            self._update_run_group(run_group_id, status=result["status"], summary=result.get("result") or "")
            result = self.get_run(result["run_id"])
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
                    self._update_run_group(
                        run_group_id,
                        status=exec_result["status"],
                        summary=exec_result.get("result") or "",
                    )
                if on_complete:
                    on_complete(exec_result)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "异步 Agent Run 执行失败: %s", exc, exc_info=True
                )
                safe_error = redact_secrets(exc)
                # 更新 run 状态为 failed
                self.append_run_event(run["run_id"], "agent.run.failed", {"error": safe_error})
                self._update_run(
                    run["run_id"],
                    status="failed",
                    result=safe_error,
                    timeline=[self._timeline("agent.run.failed", safe_error)],
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
        timeline = [self._timeline("agent.run.started", f"{agent['name']} started", backend=backend, runtime=runtime["runtime"])]
        self.append_run_event(
            run_id,
            "agent.run.started",
            {
                "agent_id": str(agent.get("agent_id") or ""),
                "agent_name": str(agent.get("name") or ""),
                "backend": backend,
                "runtime": runtime["runtime"],
            },
        )
        timeline.append(
            self._timeline(
                "agent.runtime.compiled",
                "Oha Agent Runtime compiled tools and workspace policy",
                allowed_tools=runtime["tool_policy"].get("allowed_tools") or [],
            )
        )
        artifact_root = self.agent_artifacts_dir / run_id
        context = self._agent_context(agent, user_goal, upstream)
        broker = ToolBroker(runtime["workspace_policy"], artifact_root)
        artifacts: list[dict[str, Any]] = []
        try:
            artifact = broker.artifact_write("agent-context.md", context)
            artifacts.append({"kind": "context", **artifact})
            timeline.append(self._timeline("agent.artifact.write", "agent-context.md", artifact=artifact))
            result = self._run_custom_api_agent(agent, context, broker, timeline, artifacts, run_id=run_id)
            timeline.append(self._timeline("agent.run.completed", "Agent run completed"))
            self.append_run_event(run_id, "agent.run.completed", {"result": result})
            return self._update_run(
                run_id,
                status="completed",
                result=result,
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=None,
            )
        except AgentApprovalRequired as exc:
            timeline.append(
                self._timeline(
                    "agent.tool.approval_required",
                    str(exc.pending_approval.get("tool") or ""),
                    pending_approval=_public_pending_approval(exc.pending_approval),
                )
            )
            self.append_run_event(
                run_id,
                "agent.tool.approval_required",
                _public_pending_approval(exc.pending_approval),
            )
            return self._update_run(
                run_id,
                status="approval_required",
                result=f"等待审批：{exc.pending_approval.get('tool') or 'tool'}",
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=exc.pending_approval,
            )
        except Exception as exc:
            safe_error = redact_secrets(exc)
            timeline.append(self._timeline("agent.run.failed", safe_error))
            self.append_run_event(run_id, "agent.run.failed", {"error": safe_error})
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
        allowed_tools = (agent.get("tool_policy") or {}).get("allowed_tools") or []
        if messages is None:
            allowed_tool_text = ", ".join(allowed_tools) or "none"
            system_prompt = (
                "You are running inside Oha-Yachiyo Agent Runtime. "
                "Follow the Agent functional instructions, persona prompt, user goal, and exact output requests. "
                "If those instructions require an exact phrase or format, return exactly that final output. "
                "Return concise final output unless the Agent instructions require otherwise. "
                "Prefer native tool_calls when available. "
                "If the model endpoint does not support tool_calls and a controlled tool is needed, respond as JSON "
                "{\"action\":\"tool\",\"tool\":\"workspace.list\",\"input\":{}}. "
                "Do not request tools that are not listed as allowed. "
                "If no tools are allowed, do not request tools. "
                "Do not request a tool solely because of the output contract; use tools only when the user goal "
                "or an explicit deliverable requires them. "
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
        for iteration in range(max(0, int(start_iteration or 0)), _MAX_AGENT_TOOL_ITERATIONS):
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
                result_text, _truncated = self._limit_model_output(content)
                return result_text

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
        history = {"role": "assistant", "content": message.get("content") or ""}
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
                    self._make_pending_approval(
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
            if run_id:
                self.append_run_event(
                    run_id,
                    "agent.tool.denied",
                    {"tool": tool_name, "input_preview": input_preview},
                )
            raise AgentRuntimeError(f"Agent 试图调用未授权工具：{tool_name}")
        self._validate_tool_payload(tool_name, payload)
        budget.claim_tool_call(tool_name, terminal_execution=tool_name == "terminal.run" and approved)
        try:
            tool_result = broker.call(tool_name, payload, approved=approved)
        except AgentRuntimeError as exc:
            if not tool_name.startswith("workspace."):
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
        timeline.append(self._timeline("agent.tool.call", tool_name, input_preview=input_preview, result=tool_result))
        if run_id:
            self.append_run_event(
                run_id,
                "agent.tool.call",
                {
                    "tool": tool_name,
                    "input_preview": input_preview,
                    "result": tool_result,
                    "approved": bool(approved),
                },
            )
        if artifacts is not None and tool_name == "artifact.write" and tool_result.get("ok"):
            artifact = {"kind": "tool_artifact", **tool_result}
            if artifact not in artifacts:
                artifacts.append(artifact)
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
        raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        return {
            "approval_id": f"approval_{uuid4().hex[:12]}",
            "tool": _normalize_tool_name(tool_request.get("tool")),
            "input": raw_input,
            "input_preview": _tool_input_preview(raw_input),
            "requested_at": _now(),
            "messages": messages,
            "tool_request": tool_request,
            "remaining_tool_requests": remaining_tool_requests,
            "next_iteration": max(0, min(int(next_iteration or 0), _MAX_AGENT_TOOL_ITERATIONS)),
        }

    def _tool_requests_from_message(self, message: dict[str, Any], content: str) -> list[dict[str, Any]]:
        native = self._parse_tool_calls(message.get("tool_calls"))
        if native:
            return native
        fallback = self._parse_tool_request(content)
        return [fallback] if fallback else []

    @staticmethod
    def _parse_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
        if not isinstance(tool_calls, list):
            return []
        requests = []
        for index, call in enumerate(tool_calls):
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            function_name = str(function.get("name") or "").strip()
            if not function_name:
                continue
            raw_arguments = function.get("arguments") or "{}"
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments or "{}")
                except json.JSONDecodeError as exc:
                    raise AgentRuntimeError(f"工具参数不是合法 JSON：{function_name}") from exc
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                raise AgentRuntimeError(f"工具参数格式无效：{function_name}")
            if not isinstance(arguments, dict):
                raise AgentRuntimeError(f"工具参数必须是对象：{function_name}")
            requests.append(
                {
                    "protocol": "tool_calls",
                    "tool": _normalize_tool_name(function_name),
                    "input": arguments,
                    "tool_call_id": str(call.get("id") or f"call_{index}"),
                    "function_name": function_name,
                }
            )
        return requests

    @staticmethod
    def _model_profile_config_private(profile_id: str, *, capability: str) -> dict[str, Any]:
        try:
            profile = get_model_profile_service().get_profile_private(profile_id)
        except KeyError as exc:
            raise AgentRuntimeError("Agent 引用的模型 Profile 不存在") from exc
        if not profile.get("enabled", True):
            raise AgentRuntimeError("Agent 引用的模型 Profile 已停用")
        if str(profile.get("status") or "") != "available":
            raise AgentRuntimeError("Agent 引用的模型 Profile 尚未通过连接测试")
        if not supports_openai_compatible_api(str(profile.get("provider") or "openai_compatible")):
            raise AgentRuntimeError("Agent Runtime 首版仅支持 OpenAI-compatible 模型 Profile")
        if str(profile.get("capability") or "chat") != capability:
            raise AgentRuntimeError(f"Agent 推理需要 {capability} 模型 Profile")
        return {
            "provider": profile.get("provider") or "openai_compatible",
            "base_url": profile.get("base_url") or "",
            "model": profile.get("model") or "",
            "api_key": profile.get("api_key") or "",
        }

    @staticmethod
    def _chat_profile_model_config_private(profile_id: str) -> dict[str, Any]:
        return NativeRunEngine._model_profile_config_private(profile_id, capability="chat")

    def _agent_model_config_private(self, agent: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(agent.get("model_profile_id") or "").strip()
        if profile_id:
            return self._chat_profile_model_config_private(profile_id)
        model_mode = str(agent.get("model_mode") or "profile")
        agent_id = str(agent.get("agent_id") or "")
        if model_mode == "follow_main" or agent_id in _DEFAULT_AGENT_IDS:
            default_profile_id = str(get_model_profile_service().get_defaults().get("chat") or "").strip()
            if default_profile_id:
                return self._chat_profile_model_config_private(default_profile_id)
        model_config = agent.get("model_config") or {}
        if any(str(model_config.get(key) or "").strip() for key in ("base_url", "model", "api_key")):
            return model_config
        raise AgentRuntimeError("Agent 缺少可运行的 Chat Profile；请在 Agent Studio 为该岗位选择已测试的文本模型。")

    @staticmethod
    def _parse_tool_request(content: str) -> dict[str, Any] | None:
        clean = content.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.DOTALL).strip()
        try:
            payload = json.loads(clean)
        except json.JSONDecodeError:
            return None
        if payload.get("action") == "tool" and payload.get("tool"):
            payload["protocol"] = "json_fallback"
            payload["tool"] = _normalize_tool_name(payload.get("tool"))
            if not isinstance(payload.get("input"), dict):
                payload["input"] = {}
            return payload
        return None

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
        timeline = [
            self._timeline(
                "workflow.run.started",
                workflow["name"],
                workflow_path=self._workflow_path_snapshot(workflow),
                workflow_snapshot=self._workflow_runtime_snapshot(workflow),
            )
        ]
        self.append_run_event(
            run["run_id"],
            "workflow.run.started",
            {
                "workflow_id": workflow_id,
                "workflow_name": workflow["name"],
                "workflow_path": self._workflow_path_snapshot(workflow),
            },
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
        timeline = [
            self._timeline(
                "workflow.run.started",
                workflow["name"],
                workflow_path=self._workflow_path_snapshot(workflow),
                workflow_snapshot=self._workflow_runtime_snapshot(workflow),
            )
        ]
        self.append_run_event(
            run["run_id"],
            "workflow.run.started",
            {
                "workflow_id": workflow_id,
                "workflow_name": workflow["name"],
                "workflow_path": self._workflow_path_snapshot(workflow),
            },
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
                safe_error = redact_secrets(exc)
                failed = self._update_run(
                    run["run_id"],
                    status="failed",
                    result=safe_error,
                    timeline=[*timeline, self._timeline("workflow.run.failed", safe_error, status="failed")],
                    artifacts=[],
                    pending_approval=None,
                )
                self.append_run_event(
                    run["run_id"],
                    "workflow.run.failed",
                    {"error": safe_error},
                )
                if root_group:
                    self._update_run_group(run_group_id, status="failed", summary=safe_error)
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
        if child_run.get("kind") != "agent_run" or not child_run.get("run_group_id"):
            return []
        try:
            group = self.get_run_group(str(child_run["run_group_id"]))
        except KeyError:
            return []
        parents: list[dict[str, Any]] = []
        child_run_id = str(child_run.get("run_id") or "")
        for run_id in [str(item) for item in group.get("child_run_ids") or [] if str(item)]:
            if run_id == child_run_id:
                continue
            try:
                candidate = self.get_run(run_id)
            except KeyError:
                continue
            candidate_status = str(candidate.get("status") or "")
            if (
                candidate.get("kind") != "workflow_run"
                or candidate_status not in {"approval_required", "running", "processing"}
            ):
                continue
            if any(
                event.get("event") == "workflow.run.approval_required"
                and str(event.get("child_run_id") or "") == child_run_id
                for event in candidate.get("timeline") or []
                if isinstance(event, dict)
            ):
                parents.append(candidate)
        return parents

    def _workflow_resume_start_index(
        self,
        workflow: dict[str, Any],
        workflow_run: dict[str, Any],
        child_run_id: str,
    ) -> int | None:
        target_agent_ordinal = 0
        for event in workflow_run.get("timeline") or []:
            if not isinstance(event, dict) or event.get("event") != "workflow.node.agent":
                continue
            target_agent_ordinal += 1
            if str(event.get("child_run_id") or "") == child_run_id:
                break
        else:
            return None
        seen_agent_nodes = 0
        for index, node in enumerate(self._workflow_path(workflow)):
            if self._node_kind(node) != "agent":
                continue
            seen_agent_nodes += 1
            if seen_agent_nodes == target_agent_ordinal:
                return index + 1
        return None

    def _workflow_run_is_group_root(self, workflow_run: dict[str, Any]) -> bool:
        run_group_id = str(workflow_run.get("run_group_id") or "")
        if not run_group_id:
            return False
        try:
            group = self.get_run_group(run_group_id)
        except KeyError:
            return False
        child_run_ids = [str(item) for item in group.get("child_run_ids") or [] if str(item)]
        return (
            group.get("source") == "workflow"
            or child_run_ids[:1] == [workflow_run.get("run_id")]
        )

    @staticmethod
    def _workflow_child_artifact_refs(child_run: dict[str, Any], label: str) -> list[dict[str, Any]]:
        child_run_id = str(child_run.get("run_id") or "")
        if not child_run_id:
            return []
        refs: list[dict[str, Any]] = []
        for artifact in child_run.get("artifacts") or []:
            if not isinstance(artifact, dict):
                continue
            artifact_kind = str(artifact.get("kind") or "").strip()
            if artifact_kind == "context":
                continue
            path = str(artifact.get("path") or "").strip()
            if not path:
                continue
            refs.append(
                {
                    "kind": "workflow_child_artifact",
                    "path": path,
                    "source_run_id": child_run_id,
                    "source_run_kind": str(child_run.get("kind") or ""),
                    "source_runnable_id": str(child_run.get("runnable_id") or ""),
                    "source_runnable_name": str(child_run.get("runnable_name") or child_run.get("runnable_id") or ""),
                    "workflow_step_label": label,
                    "artifact_kind": artifact_kind,
                }
            )
        return refs

    @staticmethod
    def _workflow_child_node_context(
        timeline: list[dict[str, Any]],
        child_run: dict[str, Any],
    ) -> tuple[str, dict[str, str]]:
        child_run_id = str(child_run.get("run_id") or "")
        child_label = str(child_run.get("runnable_name") or child_run.get("runnable_id") or "Agent")
        child_node_info: dict[str, str] = {}
        for event in timeline:
            if (
                isinstance(event, dict)
                and event.get("event") == "workflow.node.agent"
                and str(event.get("child_run_id") or "") == child_run_id
            ):
                child_label = str(event.get("detail") or child_label).strip() or child_label
                node_id = str(event.get("workflow_node_id") or "").strip()
                if node_id:
                    child_node_info = {
                        "workflow_node_id": node_id,
                        "workflow_node_kind": str(event.get("workflow_node_kind") or "agent"),
                        "workflow_node_label": str(event.get("workflow_node_label") or child_label),
                    }
                break
        return child_label, child_node_info

    def _merge_workflow_child_run_outcome(
        self,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        child_run: dict[str, Any],
        label: str,
    ) -> None:
        child_run_id = str(child_run.get("run_id") or "")
        if not child_run_id:
            return
        child_status = str(child_run.get("status") or "")
        child_result = str(child_run.get("result") or "")
        child_artifacts = self._workflow_child_artifact_refs(child_run, label)
        for event in timeline:
            if not isinstance(event, dict):
                continue
            if event.get("event") != "workflow.node.agent":
                continue
            if str(event.get("child_run_id") or "") != child_run_id:
                continue
            event["status"] = child_status
            event["result"] = _tool_input_preview(child_result, limit=1800)
            event["artifact_count"] = len(child_artifacts)
        existing_refs = {
            (
                str(item.get("kind") or ""),
                str(item.get("source_run_id") or ""),
                str(item.get("path") or ""),
            )
            for item in artifacts
            if isinstance(item, dict)
        }
        for artifact in child_artifacts:
            key = (
                str(artifact.get("kind") or ""),
                str(artifact.get("source_run_id") or ""),
                str(artifact.get("path") or ""),
            )
            if key not in existing_refs:
                artifacts.append(artifact)
                existing_refs.add(key)

    @staticmethod
    def _workflow_artifact_path(label: str, artifacts: list[dict[str, Any]], configured_path: str = "") -> str:
        configured = str(configured_path or "").strip()
        if configured:
            rel = _safe_rel_path(configured)
            rel_path = Path(rel)
            if rel_path.suffix:
                base = rel_path.with_suffix("")
                suffix = rel_path.suffix
            else:
                base = rel_path
                suffix = ".md"
        else:
            base = Path(_slug(label, "artifact"))
            suffix = ".md"
        existing_paths = {
            str(item.get("path") or "")
            for item in artifacts
            if isinstance(item, dict) and item.get("kind") == "workflow_artifact"
        }
        candidate = f"{base}{suffix}"
        index = 2
        while candidate in existing_paths:
            candidate = f"{base}-{index}{suffix}"
            index += 1
        return candidate

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
    ) -> dict[str, Any]:
        return self.workflow_continuation.continue_run(
            run,
            workflow,
            context=context,
            timeline=timeline,
            artifacts=artifacts,
            start_index=start_index,
            root_group=root_group,
        )

    def _workflow_path(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = {str(node["id"]): node for node in workflow["nodes"]}
        outgoing = {str(edge["source"]): str(edge["target"]) for edge in workflow["edges"]}
        start = next(node for node in workflow["nodes"] if self._node_kind(node) == "start")
        result = [start]
        current = str(start["id"])
        while current in outgoing:
            current = outgoing[current]
            result.append(nodes[current])
        return result

    @staticmethod
    def _workflow_node_task(node: dict[str, Any]) -> str:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        for key in ("task", "instructions", "step_task", "prompt"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _workflow_approval_criteria(node: dict[str, Any]) -> str:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        for key in ("criteria", "approval_criteria", "instructions", "task", "prompt"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _workflow_child_goal(workflow_goal: str, step_task: str) -> str:
        clean_workflow_goal = str(workflow_goal or "").strip()
        clean_step_task = str(step_task or "").strip()
        if not clean_step_task:
            return clean_workflow_goal
        if not clean_workflow_goal:
            return clean_step_task
        return f"{clean_step_task}\n\nWorkflow Goal:\n{clean_workflow_goal}"

    def _workflow_path_snapshot(self, workflow: dict[str, Any]) -> list[dict[str, str]]:
        snapshot: list[dict[str, str]] = []
        planned_artifacts: list[dict[str, Any]] = []
        for node in self._workflow_path(workflow):
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            kind = self._node_kind(node)
            node_id = str(node.get("id") or "")
            label = str(data.get("label") or node_id or kind)
            item = {
                "id": node_id,
                "kind": kind,
                "label": label,
            }
            if kind == "artifact":
                artifact_path = self._workflow_artifact_path(
                    label,
                    planned_artifacts,
                    str(data.get("artifact_path") or data.get("artifactPath") or ""),
                )
                item["artifact_path"] = artifact_path
                planned_artifacts.append({"kind": "workflow_artifact", "path": artifact_path})
            if kind == "agent":
                step_task = self._workflow_node_task(node)
                if step_task:
                    item["task"] = step_task
            if kind == "approval":
                criteria = self._workflow_approval_criteria(node)
                if criteria:
                    item["criteria"] = criteria
            snapshot.append(item)
        return snapshot

    @staticmethod
    def _workflow_runtime_snapshot(workflow: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_id": str(workflow.get("workflow_id") or ""),
            "name": str(workflow.get("name") or "Workflow"),
            "nodes": _json_load(_json_dump(workflow.get("nodes") or []), []),
            "edges": _json_load(_json_dump(workflow.get("edges") or []), []),
        }

    def _workflow_for_run_resume(self, workflow_run: dict[str, Any]) -> dict[str, Any]:
        for event in workflow_run.get("timeline") or []:
            if not isinstance(event, dict) or event.get("event") != "workflow.run.started":
                continue
            snapshot = event.get("workflow_snapshot")
            if not isinstance(snapshot, dict):
                continue
            nodes = snapshot.get("nodes")
            edges = snapshot.get("edges")
            if isinstance(nodes, list) and isinstance(edges, list):
                return {
                    "workflow_id": str(snapshot.get("workflow_id") or workflow_run.get("runnable_id") or ""),
                    "name": str(snapshot.get("name") or "Workflow"),
                    "nodes": nodes,
                    "edges": edges,
                    "enabled": True,
                }
        return self.get_workflow(str(workflow_run["runnable_id"]))

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
        artifacts = [item for item in run.get("artifacts") or [] if isinstance(item, dict)]
        pending = self._pending_approval_private(run_id)
        node_info: dict[str, str] = {}
        cancelled_child_run_id = ""
        label = "Workflow"
        if pending and str(pending.get("tool") or "") == "workflow.approval":
            label = str(pending.get("workflow_node_label") or "Approval")
            node_info = {
                "workflow_node_id": str(pending.get("workflow_node_id") or ""),
                "workflow_node_kind": "approval",
                "workflow_node_label": label,
                "workflow_node_approval_criteria": str(
                    pending.get("workflow_node_approval_criteria") or ""
                ).strip(),
            }
        else:
            child_run_id = ""
            for event in reversed(timeline):
                if not isinstance(event, dict):
                    continue
                if event.get("event") != "workflow.run.approval_required":
                    continue
                child_run_id = str(event.get("child_run_id") or "").strip()
                if child_run_id:
                    break
            if child_run_id:
                cancelled_child_run_id = child_run_id
                for event in timeline:
                    if (
                        isinstance(event, dict)
                        and event.get("event") == "workflow.node.agent"
                        and str(event.get("child_run_id") or "") == child_run_id
                    ):
                        label = (
                            str(event.get("detail") or event.get("workflow_node_label") or "Agent").strip()
                            or "Agent"
                        )
                        node_info = {
                            "workflow_node_id": str(event.get("workflow_node_id") or ""),
                            "workflow_node_kind": str(event.get("workflow_node_kind") or "agent"),
                            "workflow_node_label": str(event.get("workflow_node_label") or label),
                        }
                        break
                try:
                    child_run = self.get_run(child_run_id)
                except KeyError:
                    child_run = {}
                if child_run and str(child_run.get("status") or "") not in _FINAL_RUN_STATUSES:
                    child_timeline = [
                        event
                        for event in child_run.get("timeline") or []
                        if isinstance(event, dict)
                    ]
                    child_timeline.append(self._timeline("run.cancelled", "Parent Workflow cancelled"))
                    self.append_run_event(
                        child_run_id,
                        "run.cancelled",
                        {"reason": "Parent Workflow cancelled", "parent_run_id": run_id},
                    )
                    child_run = self._update_run(
                        child_run_id,
                        status="cancelled",
                        result="父 Workflow 已取消",
                        timeline=child_timeline,
                        pending_approval=None,
                    )
                if child_run:
                    self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, label)
        cancel_event_extra: dict[str, Any] = {"status": "cancelled", **node_info}
        if cancelled_child_run_id:
            cancel_event_extra["child_run_id"] = cancelled_child_run_id
        timeline.append(
            self._timeline(
                "workflow.run.cancelled",
                f"{label} cancelled",
                **cancel_event_extra,
            )
        )
        return timeline, artifacts, f"Workflow 已取消：{label}"

    def _cancel_run_once(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] in _FINAL_RUN_STATUSES:
            return run
        timeline = [*run["timeline"]]
        artifacts: list[dict[str, Any]] | None = None
        result_text: str | None = None
        if run.get("kind") == "workflow_run":
            timeline, artifacts, result_text = self._cancel_workflow_run_projection(run_id, run, timeline)
        else:
            timeline.append(self._timeline("run.cancelled", "Run cancelled"))
            result_text = "Run cancelled"
        result = self._update_run(
            run_id,
            status="cancelled",
            result=result_text,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
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
            self._update_run_group(
                str(result.get("run_group_id") or ""),
                status="cancelled",
                summary=str(result.get("result") or "Workflow 已取消"),
            )
            result = self.get_run(run_id)
        else:
            self._update_agent_run_group_if_root(result)
        self._resume_parent_workflows_after_child_update(result)
        return result

    def _tool_approval_resume_context(
        self,
        run: dict[str, Any],
        pending: dict[str, Any],
        *,
        runtime: dict[str, Any],
    ) -> ToolApprovalResumeContext:
        run_id = str(run["run_id"])
        messages = pending.get("messages") if isinstance(pending.get("messages"), list) else []
        tool_request = pending.get("tool_request") if isinstance(pending.get("tool_request"), dict) else {}
        if not messages or not tool_request:
            raise AgentRuntimeError("Run 待审批上下文不完整，无法恢复")
        timeline = [
            event
            for event in run.get("timeline") or []
            if isinstance(event, dict)
        ]
        artifacts = [item for item in run.get("artifacts") or [] if isinstance(item, dict)]
        remaining = pending.get("remaining_tool_requests")
        remaining_requests = [item for item in remaining if isinstance(item, dict)] if isinstance(remaining, list) else []
        try:
            next_iteration = int(pending.get("next_iteration") or 0)
        except (TypeError, ValueError):
            next_iteration = 0
        tool_name = str(tool_request.get("tool") or pending.get("tool") or "").strip()
        return ToolApprovalResumeContext(
            run_id=run_id,
            timeline=timeline,
            artifacts=artifacts,
            broker=ToolBroker(runtime["workspace_policy"], self.agent_artifacts_dir / run_id),
            allowed_tools=runtime["tool_policy"].get("allowed_tools") or [],
            budget=self._run_budget(run_id, timeline),
            messages=messages,
            tool_request=tool_request,
            tool_name=tool_name,
            input_preview=_tool_input_preview(tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}),
            remaining_requests=remaining_requests,
            next_iteration=next_iteration,
        )

    def _claim_and_project_approved_tool(
        self,
        run_id: str,
        pending: dict[str, Any],
        resume_context: ToolApprovalResumeContext,
        *,
        resumed_detail: str,
        running_result: str,
    ) -> dict[str, Any] | None:
        if not self.run_approvals.claim_pending_approval(run_id, pending):
            return None
        return self.approvals.approve_tool_run(
            run_id,
            timeline=resume_context.timeline,
            artifacts=resume_context.artifacts,
            tool_name=resume_context.tool_name,
            input_preview=resume_context.input_preview,
            resumed_detail=resumed_detail,
            running_result=running_result,
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
        pending = self._pending_approval_private(run_id)
        if not pending:
            raise AgentRuntimeError("Run 缺少待审批工具信息")
        agent = self._get_agent_private(str(run["runnable_id"]))
        runtime = self._compile_agent_runtime(agent)
        resume_context = self._tool_approval_resume_context(run, pending, runtime=runtime)
        running = self._claim_and_project_approved_tool(
            run_id,
            pending,
            resume_context,
            resumed_detail="Agent resumed after approval",
            running_result="已批准，Agent 正在继续执行",
        )
        if running is None:
            return self.get_run(run_id)
        self._update_agent_run_group_if_root(running)
        self._mark_parent_workflows_child_running(running)
        try:
            result_text = self.approval_resume.continue_custom_api_agent_after_approved_tool(
                agent,
                resume_context,
            )
            resume_context.timeline.append(self._timeline("agent.run.completed", "Agent run completed"))
            self.append_run_event(run_id, "agent.run.completed", {"result": result_text})
            result = self._update_run(
                run_id,
                status="completed",
                result=result_text,
                timeline=resume_context.timeline,
                artifacts=resume_context.artifacts,
                pending_approval=None,
            )
        except AgentApprovalRequired as exc:
            resume_context.timeline.append(
                self._timeline(
                    "agent.tool.approval_required",
                    str(exc.pending_approval.get("tool") or ""),
                    pending_approval=_public_pending_approval(exc.pending_approval),
                )
            )
            self.append_run_event(
                run_id,
                "agent.tool.approval_required",
                _public_pending_approval(exc.pending_approval),
            )
            result = self._update_run(
                run_id,
                status="approval_required",
                result=f"等待审批：{exc.pending_approval.get('tool') or 'tool'}",
                timeline=resume_context.timeline,
                artifacts=resume_context.artifacts,
                pending_approval=exc.pending_approval,
            )
        except Exception as exc:
            safe_error = redact_secrets(exc)
            resume_context.timeline.append(self._timeline("agent.run.failed", safe_error))
            self.append_run_event(run_id, "agent.run.failed", {"error": safe_error})
            result = self._update_run(
                run_id,
                status="failed",
                result=safe_error,
                timeline=resume_context.timeline,
                artifacts=resume_context.artifacts,
                pending_approval=None,
            )
        self._update_agent_run_group_if_root(result)
        self._resume_parent_workflows_after_child_update(result)
        return result

    def _approve_main_chat_run_approval(self, run: dict[str, Any]) -> dict[str, Any]:
        run_id = str(run["run_id"])
        pending = self._pending_approval_private(run_id)
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
        running = self._claim_and_project_approved_tool(
            run_id,
            pending,
            resume_context,
            resumed_detail="Main chat resumed after approval",
            running_result="已批准，Yachiyo 正在继续执行",
        )
        if running is None:
            return self.get_run(run_id)
        try:
            result_text = self.approval_resume.continue_custom_api_agent_after_approved_tool(
                agent,
                resume_context,
            )
            resume_context.timeline.append(
                self._timeline(
                    "model.output.ready",
                    result_text[:500],
                    output_chars=len(result_text),
                )
            )
            self.append_run_event(
                run_id,
                "model.output.completed",
                {"content": result_text, "output_chars": len(result_text)},
            )
            result = self._update_run(
                run_id,
                status="running",
                result=result_text,
                timeline=resume_context.timeline,
                artifacts=resume_context.artifacts,
                pending_approval=None,
            )
        except AgentApprovalRequired as exc:
            pending_next = self._main_chat_pending_approval(
                exc.pending_approval,
                model_profile_id=model_profile_id,
                tool_policy=runtime["tool_policy"],
                workspace_policy=runtime["workspace_policy"],
            )
            resume_context.timeline.append(
                self._timeline(
                    "agent.tool.approval_required",
                    str(pending_next.get("tool") or ""),
                    pending_approval=_public_pending_approval(pending_next),
                )
            )
            self.append_run_event(
                run_id,
                "agent.tool.approval_required",
                _public_pending_approval(pending_next),
            )
            result = self._update_run(
                run_id,
                status="approval_required",
                result=f"等待审批：{pending_next.get('tool') or 'tool'}",
                timeline=resume_context.timeline,
                artifacts=resume_context.artifacts,
                pending_approval=pending_next,
            )
        except Exception as exc:
            safe_error = redact_api_error_text(exc)
            resume_context.timeline.append(self._timeline("agent.run.failed", safe_error))
            self.append_run_event(run_id, "agent.run.failed", {"error": safe_error})
            result = self._update_run(
                run_id,
                status="failed",
                result=safe_error,
                timeline=resume_context.timeline,
                artifacts=resume_context.artifacts,
                pending_approval=None,
            )
        return result

    def _approve_workflow_run_approval(self, run: dict[str, Any]) -> dict[str, Any]:
        run_id = str(run["run_id"])
        pending = self._pending_approval_private(run_id)
        if not pending or str(pending.get("tool") or "") != "workflow.approval":
            raise AgentRuntimeError("Workflow Run 缺少待审批节点信息")
        workflow = self._workflow_for_run_resume(run)
        label = str(pending.get("workflow_node_label") or "Approval")
        context = str(pending.get("workflow_context") or run.get("result") or run.get("user_goal") or "")
        try:
            start_index = int(pending.get("workflow_next_index") or 0)
        except (TypeError, ValueError):
            raise AgentRuntimeError("Workflow Run 待审批恢复位置无效")
        timeline = [
            event
            for event in run.get("timeline") or []
            if isinstance(event, dict)
        ]
        workflow_node_id = str(pending.get("workflow_node_id") or "")
        criteria = str(pending.get("workflow_node_approval_criteria") or "").strip()
        approval_preview = pending.get("input_preview") if isinstance(pending.get("input_preview"), dict) else {}
        artifacts = [item for item in run.get("artifacts") or [] if isinstance(item, dict)]
        root_group = self._workflow_run_is_group_root(run)
        if not self.run_approvals.claim_pending_approval(run_id, pending):
            return self.get_run(run_id)
        return self.workflow_continuation.resume_after_approval_node(
            run,
            workflow,
            context=context,
            timeline=timeline,
            artifacts=artifacts,
            start_index=start_index,
            root_group=root_group,
            workflow_node_id=workflow_node_id,
            label=label,
            criteria=criteria,
            input_preview=approval_preview,
        )

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "approval_required":
            return run
        if run["kind"] == "workflow_run":
            pending = self._pending_approval_private(run_id)
            if not pending or str(pending.get("tool") or "") != "workflow.approval":
                raise AgentRuntimeError("Workflow Run 缺少待审批节点信息")
            label = str(pending.get("workflow_node_label") or "Approval")
            criteria = str(pending.get("workflow_node_approval_criteria") or "").strip()
            approval_preview = pending.get("input_preview") if isinstance(pending.get("input_preview"), dict) else {}
            result = self.approvals.reject_workflow_node(
                run_id,
                timeline=[*run["timeline"]],
                reason=reason,
                workflow_node_id=str(pending.get("workflow_node_id") or ""),
                label=label,
                criteria=criteria,
                input_preview=approval_preview,
            )
            if self._workflow_run_is_group_root(run):
                self._update_run_group(
                    str(run.get("run_group_id") or ""),
                    status="cancelled",
                    summary=str(result.get("result") or ""),
                )
                result = self.get_run(run_id)
            return result
        pending = self._pending_approval_private(run_id)
        tool_request = pending.get("tool_request") if isinstance(pending.get("tool_request"), dict) else {}
        tool_name = str(tool_request.get("tool") or pending.get("tool") or "").strip()
        tool_input_preview = _tool_input_preview(tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {})
        result = self.approvals.reject_tool_run(
            run_id,
            timeline=[*run["timeline"]],
            reason=reason,
            tool_name=tool_name,
            input_preview=tool_input_preview,
        )
        self._update_agent_run_group_if_root(result)
        self._resume_parent_workflows_after_child_update(result)
        return result

    def timeout_run_approval(self, run_id: str, reason: str = "approval_wait_timeout") -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "approval_required":
            return run
        if run["kind"] == "workflow_run":
            pending = self._pending_approval_private(run_id)
            if not pending or str(pending.get("tool") or "") != "workflow.approval":
                return self.cancel_run(run_id)
            label = str(pending.get("workflow_node_label") or "Approval")
            criteria = str(pending.get("workflow_node_approval_criteria") or "").strip()
            approval_preview = pending.get("input_preview") if isinstance(pending.get("input_preview"), dict) else {}
            result = self.approvals.timeout_workflow_node(
                run_id,
                timeline=[*run["timeline"]],
                reason=reason,
                workflow_node_id=str(pending.get("workflow_node_id") or ""),
                label=label,
                criteria=criteria,
                input_preview=approval_preview,
            )
            if self._workflow_run_is_group_root(run):
                self._update_run_group(
                    str(run.get("run_group_id") or ""),
                    status="cancelled",
                    summary=str(result.get("result") or ""),
                )
                result = self.get_run(run_id)
            return result
        pending = self._pending_approval_private(run_id)
        tool_request = pending.get("tool_request") if isinstance(pending.get("tool_request"), dict) else {}
        tool_name = str(tool_request.get("tool") or pending.get("tool") or "").strip()
        tool_input_preview = _tool_input_preview(tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {})
        result = self.approvals.timeout_tool_run(
            run_id,
            timeline=[*run["timeline"]],
            reason=reason,
            tool_name=tool_name,
            input_preview=tool_input_preview,
        )
        self._update_agent_run_group_if_root(result)
        self._resume_parent_workflows_after_child_update(result)
        return result

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
