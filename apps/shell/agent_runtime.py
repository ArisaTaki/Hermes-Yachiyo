"""Agent Studio, Skill Library, and Workflow runtime services."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import uuid4

from apps.core.tls import urlopen_with_bundled_ca
from apps.shell.model_profiles import (
    get_model_profile_service,
    openai_compatible_chat_message,
    read_openai_compatible_chat_timeout,
    supports_openai_compatible_api,
)


class AgentRuntimeError(RuntimeError):
    """Raised when an Agent Studio operation cannot be completed."""


class AgentApprovalRequired(AgentRuntimeError):
    """Raised internally when a run must pause for user approval."""

    def __init__(self, pending_approval: dict[str, Any]) -> None:
        self.pending_approval = pending_approval
        super().__init__(f"等待审批：{pending_approval.get('tool') or 'tool'}")


_EXECUTION_BACKENDS = {"hermes_profile", "yachiyo_profile", "external_cli"}
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
_SKILL_SOURCE_TYPES = {"hermes_global", "hermes_project", "npx_skills", "hermes_cli", "local_zip", "local_dir"}
_SHELL_METACHARS = {"&&", "||", "&", ";", "|", ">", ">>", "<", "$(", "`", "\n", "\r"}
_SKILL_INSTALL_PATH_CANDIDATES = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
    "~/.local/bin",
    "~/.npm-global/bin",
    "~/.volta/bin",
    "~/.asdf/shims",
    "~/.local/share/mise/shims",
)
_UNSET = object()
_DEFAULT_AGENT_IDS = {
    "agent_yachiyo_orchestrator",
    "agent_coding",
    "agent_design",
    "agent_review",
    "agent_research",
    "agent_office",
    "agent_custom",
}


def _path_entries(value: str | None) -> list[str]:
    return [entry for entry in str(value or "").split(os.pathsep) if entry]


def _dedupe_path_entries(entries: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        clean_entry = str(entry or "").strip()
        if not clean_entry or clean_entry in seen:
            continue
        seen.add(clean_entry)
        deduped.append(clean_entry)
    return deduped


def _existing_dir(path: str | Path) -> str:
    try:
        expanded = Path(path).expanduser()
        if expanded.is_dir():
            return str(expanded)
    except OSError:
        return ""
    return ""


def _version_manager_node_bin_dirs() -> list[str]:
    home = Path.home()
    candidates: list[Path] = []
    for root in (
        home / ".nvm" / "versions" / "node",
        home / ".asdf" / "installs" / "nodejs",
        home / ".local" / "share" / "mise" / "installs" / "node",
    ):
        try:
            candidates.extend(path / "bin" for path in sorted(root.iterdir(), reverse=True) if path.is_dir())
        except OSError:
            continue
    for root in (
        home / ".fnm" / "node-versions",
        home / ".local" / "share" / "fnm" / "node-versions",
    ):
        try:
            candidates.extend(path / "installation" / "bin" for path in sorted(root.iterdir(), reverse=True) if path.is_dir())
        except OSError:
            continue
    return [resolved for candidate in candidates if (resolved := _existing_dir(candidate))]


def _skill_install_subprocess_env(hermes_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_home)
    configured_node_bin = _existing_dir(env.get("HERMES_YACHIYO_NODE_BIN", ""))
    candidate_dirs = [configured_node_bin] if configured_node_bin else []
    candidate_dirs.extend(_existing_dir(path) for path in _SKILL_INSTALL_PATH_CANDIDATES)
    candidate_dirs.extend(_version_manager_node_bin_dirs())
    env["PATH"] = os.pathsep.join(
        _dedupe_path_entries([
            *_path_entries(env.get("PATH")),
            *(path for path in candidate_dirs if path),
        ])
    )
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


def _hermes_yachiyo_home() -> Path:
    hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
    root = Path(hermes_home) / "yachiyo"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))).expanduser()


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
    """Normalize legacy backend values to the persistent Yachiyo runtime.

    Agent Studio used to expose Hermes/external CLI backends. Those values are
    now kept only for database compatibility; custom Studio agents always run
    through Yachiyo Agent Runtime.
    """
    backend = str(value or "").strip()
    if backend and backend not in _EXECUTION_BACKENDS:
        raise AgentRuntimeError("execution_backend 仅支持 yachiyo_profile（旧值将自动迁移）")
    return "yachiyo_profile"


_SECRET_RE = re.compile(
    r"(?i)(sk-[a-z0-9._-]{8,}|api[_-]?key\s*[:=]\s*[^\s,;]+|authorization\s*[:=]\s*bearer\s+[^\s,;]+)"
)


def redact_secrets(value: Any) -> str:
    text = str(value if value is not None else "")
    return _SECRET_RE.sub("[redacted]", text)


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


def _message_content_text(content: Any) -> str:
    if isinstance(content, dict):
        nested = _message_content_text(content.get("content"))
        if nested:
            return nested
        reasoning = content.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning
        text = content.get("text")
        return str(text) if text is not None else ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


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

    def workspace_write_patch(self, path: str, content: str, *, approved: bool = False) -> dict[str, Any]:
        if not approved and not self.approvals.get("workspace.write_patch"):
            return {"ok": False, "approval_required": True, "tool": "workspace.write_patch"}
        target = self._resolve_workspace_path(path, write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": path, "bytes": len(content.encode("utf-8"))}

    def terminal_run(self, command: str, *, approved: bool = False, timeout_seconds: int = 30) -> dict[str, Any]:
        if not approved and not self.approvals.get("terminal.run"):
            return {"ok": False, "approval_required": True, "tool": "terminal.run"}
        result = subprocess.run(
            command,
            cwd=self.workdir,
            shell=True,
            text=True,
            capture_output=True,
            timeout=max(1, min(int(timeout_seconds or 30), 120)),
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": redact_secrets(result.stdout)[-8000:],
            "stderr": redact_secrets(result.stderr)[-8000:],
        }

    def artifact_write(self, path: str, content: str) -> dict[str, Any]:
        rel = _safe_rel_path(path)
        target = (self.artifact_root / rel).resolve()
        if not _is_within(target, self.artifact_root):
            raise AgentRuntimeError("artifact 路径越界")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": rel, "bytes": len(content.encode("utf-8"))}

    def call(self, name: str, payload: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        if name == "workspace.list":
            return self.workspace_list(str(payload.get("path") or "."))
        if name == "workspace.read":
            return self.workspace_read(str(payload.get("path") or ""))
        if name == "workspace.write_patch":
            return self.workspace_write_patch(
                str(payload.get("path") or ""),
                str(payload.get("content") or payload.get("patch") or ""),
                approved=approved,
            )
        if name == "terminal.run":
            return self.terminal_run(
                str(payload.get("command") or ""),
                approved=approved,
                timeout_seconds=int(payload.get("timeout_seconds") or 30),
            )
        if name == "artifact.write":
            return self.artifact_write(str(payload.get("path") or ""), str(payload.get("content") or ""))
        raise AgentRuntimeError(f"未知工具：{name}")


class AgentRuntimeService:
    """Persistent service behind Agent Studio and Workflow Studio."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        workspace_dir: Path | str | None = None,
        *,
        seed_templates: bool = True,
    ) -> None:
        root = Path(workspace_dir) if workspace_dir is not None else _hermes_yachiyo_home()
        root.mkdir(parents=True, exist_ok=True)
        self.workspace_dir = root
        self.db_path = Path(db_path) if db_path is not None else root / "agent-runtime.db"
        self.skills_dir = root / "skills"
        self.skill_installs_dir = root / "skill-installs"
        self.skill_installs_hermes_home = self.skill_installs_dir / "hermes-home"
        self.agent_artifacts_dir = root / "artifacts" / "agent-runs"
        self.workflow_artifacts_dir = root / "artifacts" / "workflow-runs"
        self.agent_workspaces_dir = root / "workspaces" / "agents"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.skill_installs_dir.mkdir(parents=True, exist_ok=True)
        self.skill_installs_hermes_home.mkdir(parents=True, exist_ok=True)
        self.agent_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.workflow_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.agent_workspaces_dir.mkdir(parents=True, exist_ok=True)
        self._db_lock = threading.RLock()
        raw_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn = _LockedConnection(raw_conn, self._db_lock)
        self._conn.row_factory = _named_row_factory
        self._init_db()
        self._migrate_agent_workspace_policies()
        if seed_templates:
            self._seed_templates()

    def close(self) -> None:
        self._conn.close()

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
                execution_backend TEXT NOT NULL DEFAULT 'yachiyo_profile',
                model_profile_id TEXT NOT NULL DEFAULT '',
                vision_model_profile_id TEXT NOT NULL DEFAULT '',
                model_provider TEXT NOT NULL DEFAULT 'openai_compatible',
                model_base_url TEXT NOT NULL DEFAULT '',
                model_name TEXT NOT NULL DEFAULT '',
                model_api_key TEXT NOT NULL DEFAULT '',
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
            """
        )
        self._ensure_runtime_columns()
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
            """
        )
        self._conn.commit()

    def _ensure_runtime_columns(self) -> None:
        columns = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(agents)").fetchall()}
        if "nickname" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN nickname TEXT NOT NULL DEFAULT ''")
        if "persona_prompt" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN persona_prompt TEXT NOT NULL DEFAULT ''")
        if "execution_backend" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN execution_backend TEXT NOT NULL DEFAULT 'yachiyo_profile'")
        if "model_profile_id" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN model_profile_id TEXT NOT NULL DEFAULT ''")
        if "vision_model_profile_id" not in columns:
            self._conn.execute("ALTER TABLE agents ADD COLUMN vision_model_profile_id TEXT NOT NULL DEFAULT ''")
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
        if "pending_approval_json" not in run_columns:
            self._conn.execute("ALTER TABLE runs ADD COLUMN pending_approval_json TEXT NOT NULL DEFAULT '{}'")

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
        library = "hermes" if source_type in {"hermes_global", "hermes_project"} else "yachiyo"
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
        specs: dict[str, dict[str, Any]] = {
            "workspace.list": {
                "description": "List entries in an allowed workspace directory. Use this before workspace.read when you only know a directory path.",
                "properties": {"path": {"type": "string", "description": "Relative directory path."}},
            },
            "workspace.read": {
                "description": "Read a UTF-8 text file from the allowed workspace. This only accepts file paths; use workspace.list for directories.",
                "properties": {"path": {"type": "string", "description": "Relative file path."}},
                "required": ["path"],
            },
            "workspace.write_patch": {
                "description": "Write text content to an allowed workspace path. Requires user approval.",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path inside writable scopes."},
                    "content": {"type": "string", "description": "Full text content to write."},
                },
                "required": ["path", "content"],
            },
            "terminal.run": {
                "description": "Run a shell command in the Agent workdir. Requires user approval.",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run."},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
                },
                "required": ["command"],
            },
            "artifact.write": {
                "description": "Write a markdown/text artifact for the current run.",
                "properties": {
                    "path": {"type": "string", "description": "Relative artifact path."},
                    "content": {"type": "string", "description": "Artifact content."},
                },
                "required": ["path", "content"],
            },
        }
        schemas = []
        for tool in allowed_tools:
            spec = specs.get(tool)
            function_name = _TOOL_FUNCTION_NAMES.get(tool)
            if not spec or not function_name:
                continue
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": function_name,
                        "description": spec["description"],
                        "parameters": {
                            "type": "object",
                            "properties": spec.get("properties") or {},
                            "required": spec.get("required") or [],
                            "additionalProperties": False,
                        },
                    },
                }
            )
        return schemas

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
                "api_key_configured": bool(row["model_api_key"]),
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
        agent["model_config"]["api_key"] = row["model_api_key"]
        return agent

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
            "yachiyo_count": int(row["yachiyo_count"] or 0),
            "hermes_count": int(row["hermes_count"] or 0),
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
        run = {
            "run_id": row["run_id"],
            "run_group_id": run_group_id,
            "run_group_source": run_group_source,
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
                self._row_to_agent(self._coerce_named_row(row, cursor.description))
                for row in rows
            ],
        }

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        cursor = self._conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,))
        row = cursor.fetchone()
        if row is None:
            raise KeyError(agent_id)
        return self._row_to_agent(self._coerce_named_row(row, cursor.description))

    def _get_agent_private(self, agent_id: str) -> dict[str, Any]:
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
        model_config = payload.get("model_config") or {}
        category = str(payload.get("category") or "custom")
        model_mode = str(payload.get("model_mode") or "profile")
        execution_backend = _normalize_execution_backend(payload.get("execution_backend"), model_mode=model_mode)
        tool_policy = self._compile_tool_policy(category, payload.get("tool_policy"))
        workspace_policy = self._compile_workspace_policy(payload.get("workspace_policy"))
        workspace_policy = self._assign_default_agent_workdir(agent_id, workspace_policy, tool_policy)
        self._conn.execute(
            """
            INSERT INTO agents (
                agent_id, name, nickname, description, avatar_url, category, instructions, persona_prompt,
                model_mode, execution_backend, model_profile_id, vision_model_profile_id, model_provider, model_base_url, model_name, model_api_key,
                tool_policy_json, workspace_policy_json, skill_ids_json, output_contract,
                enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                str(model_config.get("api_key") or ""),
                _json_dump(tool_policy),
                _json_dump(workspace_policy),
                _json_dump(payload.get("skill_ids") or []),
                str(payload.get("output_contract") or "chat"),
                1 if payload.get("enabled", True) else 0,
                now,
                now,
            ),
        )
        if not seed:
            self._clear_studio_deletion("agent", agent_id)
        self._conn.commit()
        return self.get_agent(agent_id)

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        now = _now()
        category = str(next_agent.get("category") or "custom")
        model_mode = str(next_agent.get("model_mode") or "profile")
        execution_backend = _normalize_execution_backend(next_agent.get("execution_backend"), model_mode=model_mode)
        tool_policy = self._compile_tool_policy(category, next_agent.get("tool_policy"))
        workspace_policy = self._compile_workspace_policy(next_agent.get("workspace_policy"))
        workspace_policy = self._assign_default_agent_workdir(agent_id, workspace_policy, tool_policy)
        self._conn.execute(
            """
            UPDATE agents
               SET name=?, nickname=?, description=?, avatar_url=?, category=?, instructions=?, persona_prompt=?,
                   model_mode=?, execution_backend=?, model_profile_id=?, vision_model_profile_id=?, model_provider=?, model_base_url=?, model_name=?, model_api_key=?,
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
                api_key,
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
        if self._conn.execute("SELECT 1 FROM agents WHERE agent_id=?", (agent_id,)).fetchone() is not None:
            self._record_studio_deletion("agent", agent_id)
        self._conn.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
        self._conn.commit()
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
                   SUM(CASE WHEN s.source_type IN ('hermes_global', 'hermes_project') THEN 0 ELSE 1 END) AS yachiyo_count,
                   SUM(CASE WHEN s.source_type IN ('hermes_global', 'hermes_project') THEN 1 ELSE 0 END) AS hermes_count
              FROM skill_folders f
              LEFT JOIN skills s ON s.folder_id = f.folder_id
             GROUP BY f.folder_id
             ORDER BY f.sort_order ASC, LOWER(f.name) ASC
            """
        ).fetchall()
        uncategorized = self._conn.execute(
            """
            SELECT COUNT(*) AS skill_count,
                   SUM(CASE WHEN source_type IN ('hermes_global', 'hermes_project') THEN 0 ELSE 1 END) AS yachiyo_count,
                   SUM(CASE WHEN source_type IN ('hermes_global', 'hermes_project') THEN 1 ELSE 0 END) AS hermes_count
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
                "yachiyo_count": int(uncategorized["yachiyo_count"] or 0),
                "hermes_count": int(uncategorized["hermes_count"] or 0),
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
        if source_scope not in {"all", "yachiyo", "hermes"}:
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
                   SUM(CASE WHEN s.source_type IN ('hermes_global', 'hermes_project') THEN 0 ELSE 1 END) AS yachiyo_count,
                   SUM(CASE WHEN s.source_type IN ('hermes_global', 'hermes_project') THEN 1 ELSE 0 END) AS hermes_count
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
        if source_scope not in {"all", "yachiyo", "hermes"}:
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
        self._repair_hermes_skill_references()
        self._repair_yachiyo_installed_skill_provenance()
        rows = self._conn.execute(
            """
            SELECT s.*, f.name AS folder_name
              FROM skills s
              LEFT JOIN skill_folders f ON f.folder_id = s.folder_id
             ORDER BY s.updated_at DESC
            """
        ).fetchall()
        return {"ok": True, "skills": [self._row_to_skill(row) for row in rows]}

    def list_hermes_skill_sources(self) -> dict[str, Any]:
        roots = self._hermes_skill_root_specs()
        return {
            "ok": True,
            "roots": [
                {
                    "path": str(root["path"]),
                    "source_type": root["source_type"],
                    "library": "hermes",
                    "exists": root["path"].exists(),
                    "skill_count": self._count_skill_files(root["path"]),
                }
                for root in roots
            ],
        }

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        self._repair_hermes_skill_references()
        self._repair_yachiyo_installed_skill_provenance()
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

    def sync_hermes_skills(self, roots: list[Any] | None = None) -> dict[str, Any]:
        return self._sync_skill_roots(self._hermes_skill_root_specs(roots), library="hermes")

    def sync_yachiyo_installed_skills(
        self,
        *,
        record_source_type: str = "npx_skills",
        folder_id: str | None = None,
        source_ref_override: str = "",
        restore_deleted: bool = False,
    ) -> dict[str, Any]:
        source_type = record_source_type if record_source_type in {"npx_skills", "hermes_cli"} else "npx_skills"
        roots = self._yachiyo_skill_root_specs(source_type=source_type, source_ref_override=source_ref_override)
        return self._sync_skill_roots(
            roots,
            library="yachiyo",
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
                        "message": str(exc),
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
        env = _skill_install_subprocess_env(self.skill_installs_hermes_home)
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
            if argv[0] == "npx":
                raise AgentRuntimeError(
                    "找不到安装命令：npx。Yachiyo 已尝试补充 Homebrew、nvm、fnm、Volta、asdf 和 mise 的常见 PATH；"
                    "请确认 Node.js/npm 已安装，或将 npx 所在目录写入 HERMES_YACHIYO_NODE_BIN 后重启应用。"
                ) from exc
            raise AgentRuntimeError(f"找不到安装命令：{argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AgentRuntimeError("Skill 安装命令超时") from exc
        stdout = redact_secrets(completed.stdout)[-12000:]
        stderr = redact_secrets(completed.stderr)[-12000:]
        sync_result = (
            self.sync_yachiyo_installed_skills(
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
            "source_type IN ('hermes_global', 'hermes_project')"
            if source_type in {"hermes_global", "hermes_project"}
            else "source_type NOT IN ('hermes_global', 'hermes_project')"
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

    def _skill_path_owned_by_yachiyo(self, path: Path) -> bool:
        return _is_within(path, self.skills_dir) or _is_within(path, self.skill_installs_dir)

    def _repair_hermes_skill_references(self) -> None:
        rows = self._conn.execute(
            """
            SELECT skill_id, local_path, origin_path
              FROM skills
             WHERE source_type IN ('hermes_global', 'hermes_project')
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

    def _repair_yachiyo_installed_skill_provenance(self) -> None:
        source_map = self._installed_skill_source_map()
        if not source_map:
            return
        self._ensure_row_factory()
        rows = self._conn.execute(
            """
            SELECT skill_id, local_path, origin_path, source_ref, source_type
              FROM skills
             WHERE source_type IN ('npx_skills', 'hermes_cli')
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

    def _hermes_skill_root_specs(self, roots: list[Any] | None = None) -> list[dict[str, Any]]:
        if roots is None:
            raw_roots: list[Any] = [
                {"path": _hermes_home() / "skills", "source_type": "hermes_global"},
            ]
        else:
            raw_roots = roots
        specs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_roots:
            if isinstance(item, dict):
                path = Path(str(item.get("path") or "")).expanduser()
                source_type = str(item.get("source_type") or self._infer_hermes_source_type(path))
            else:
                path = Path(str(item)).expanduser()
                source_type = self._infer_hermes_source_type(path)
            if source_type not in {"hermes_global", "hermes_project"}:
                source_type = "hermes_global"
            key = str(path.resolve()) if path.exists() else str(path)
            if not key or key in seen:
                continue
            seen.add(key)
            specs.append({"path": path, "source_type": source_type})
        return specs

    def _yachiyo_skill_root_specs(self, *, source_type: str, source_ref_override: str = "") -> list[dict[str, Any]]:
        roots = [
            self.skill_installs_dir / ".hermes" / "skills",
            self.skill_installs_hermes_home / "skills",
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
    def _infer_hermes_source_type(path: Path) -> str:
        project_root = Path.cwd() / ".hermes" / "skills"
        try:
            if path.resolve() == project_root.resolve():
                return "hermes_project"
        except OSError:
            pass
        return "hermes_global"

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
        if argv[:3] == ["hermes", "skills", "install"]:
            return argv, "hermes_cli"
        if argv[0] in {"npm", "pnpm", "yarn", "bun", "curl", "bash", "sh", "zsh"}:
            raise AgentRuntimeError("只允许 skills 来源、npx skills add 或 hermes skills install")
        return self._validated_npx_skills_argv(["npx", "skills@latest", "add", *argv]), "npx_skills"

    @staticmethod
    def _skill_install_source_ref(argv: list[str], installer: str) -> str:
        if installer == "hermes_cli" and argv[:3] == ["hermes", "skills", "install"]:
            return " ".join(argv[3:])
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
        AgentRuntimeService._validate_skill_install_agent_target(install_args)
        if not AgentRuntimeService._has_agent_target(install_args):
            normalized.extend(["-a", "hermes-agent"])
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
                if value != "hermes-agent":
                    raise AgentRuntimeError("Yachiyo 安装入口固定使用 hermes-agent 目标")
            elif arg.startswith("--agent=") and arg != "--agent=hermes-agent":
                raise AgentRuntimeError("Yachiyo 安装入口固定使用 hermes-agent 目标")

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
        if source_type not in {"hermes_global", "hermes_project"}:
            local_path = Path(str(skill_row["local_path"])) if skill_row is not None and skill_row["local_path"] else self.skills_dir / skill_id
            if self._skill_path_owned_by_yachiyo(local_path):
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

    def list_run_groups(self, limit: int = 50) -> dict[str, Any]:
        self._ensure_row_factory()
        rows = self._conn.execute(
            "SELECT * FROM run_groups ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit or 50), 200)),),
        ).fetchall()
        return {"ok": True, "run_groups": [self._row_to_run_group(row) for row in rows]}

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT * FROM run_groups WHERE run_group_id=?", (run_group_id,)).fetchone()
        if row is None:
            raise KeyError(run_group_id)
        return self._row_to_run_group(row)

    def _run_group_source(self, run_group_id: str) -> str:
        if not run_group_id:
            return ""
        row = self._conn.execute(
            "SELECT source FROM run_groups WHERE run_group_id=?",
            (run_group_id,),
        ).fetchone()
        if row is None:
            return ""
        return str(row["source"] or "")

    def get_run(self, run_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._row_to_run(row)

    def _delete_run_artifacts(self, run: dict[str, Any]) -> None:
        run_id = str(run.get("run_id") or "")
        if not run_id:
            return
        root = self.agent_artifacts_dir if run.get("kind") == "agent_run" else self.workflow_artifacts_dir
        target = (root / run_id).resolve()
        if _is_within(target, root) and target.exists():
            shutil.rmtree(target, ignore_errors=True)

    def _runs_in_group(self, run_group_id: str) -> list[dict[str, Any]]:
        if not run_group_id:
            return []
        self._ensure_row_factory()
        rows = self._conn.execute(
            "SELECT * FROM runs WHERE run_group_id=? ORDER BY created_at ASC",
            (run_group_id,),
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def _delete_run_rows(self, runs: list[dict[str, Any]]) -> list[str]:
        deleted_run_ids: list[str] = []
        for run in runs:
            run_id = str(run.get("run_id") or "")
            if not run_id:
                continue
            self._delete_run_artifacts(run)
            self._conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
            deleted_run_ids.append(run_id)
        return deleted_run_ids

    def _remove_run_ids_from_group(self, run_group_id: str, run_ids: set[str]) -> None:
        if not run_group_id or not run_ids:
            return
        try:
            group = self.get_run_group(run_group_id)
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
            self._conn.execute("DELETE FROM run_groups WHERE run_group_id=?", (run_group_id,))
            return
        self._conn.execute(
            """
            UPDATE run_groups
               SET child_run_ids_json=?, updated_at=?
             WHERE run_group_id=?
            """,
            (_json_dump(child_run_ids), _now(), run_group_id),
        )

    def delete_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if _is_active_run_status(str(run.get("status") or "")):
            raise AgentRuntimeError("Run 仍在进行中或待审批，取消或完成后才能删除")
        run_group_id = str(run.get("run_group_id") or "")
        targets = [run]
        delete_group = False
        if run.get("kind") == "workflow_run" and run_group_id:
            group_runs = self._runs_in_group(run_group_id)
            if any(_is_active_run_status(str(item.get("status") or "")) for item in group_runs):
                raise AgentRuntimeError("这个 Workflow Run 仍有进行中或待审批的子 Run，取消或完成后才能删除")
            targets = group_runs or [run]
            delete_group = True
        deleted_run_ids = self._delete_run_rows(targets)
        deleted_ids = set(deleted_run_ids)
        if delete_group and run_group_id:
            self._conn.execute("DELETE FROM run_groups WHERE run_group_id=?", (run_group_id,))
        else:
            self._remove_run_ids_from_group(run_group_id, deleted_ids)
        self._conn.commit()
        return {
            "ok": True,
            "deleted_run_ids": deleted_run_ids,
            "deleted_run_count": len(deleted_run_ids),
        }

    def _pending_approval_json(self, run_id: str) -> str:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT pending_approval_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return str(row["pending_approval_json"] or "{}")

    def _pending_approval_private(self, run_id: str) -> dict[str, Any]:
        pending = _json_load(self._pending_approval_json(run_id), {})
        return pending if isinstance(pending, dict) else {}

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        rel = _safe_rel_path(artifact_path)
        root = self.agent_artifacts_dir / run_id if run["kind"] == "agent_run" else self.workflow_artifacts_dir / run_id
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

    def _insert_run_group(
        self,
        *,
        title: str,
        source: str,
        workspace_dir: str = "",
    ) -> dict[str, Any]:
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
        return self.get_run_group(run_group_id)

    def _append_run_to_group(self, run_group_id: str, run_id: str) -> None:
        if not run_group_id:
            return
        group = self.get_run_group(run_group_id)
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

    def _update_run_group(
        self,
        run_group_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
    ) -> None:
        if not run_group_id:
            return
        current = self.get_run_group(run_group_id)
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

    def _insert_run(self, *, kind: str, runnable_id: str, user_goal: str, run_group_id: str = "") -> dict[str, Any]:
        run_id = f"{kind}_{uuid4().hex[:12]}"
        now = _now()
        self._conn.execute(
            """
            INSERT INTO runs (
                run_id, run_group_id, kind, runnable_id, status, user_goal, result,
                timeline_json, artifacts_json, pending_approval_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, run_group_id, kind, runnable_id, "running", user_goal, "", "[]", "[]", "{}", now, now),
        )
        self._conn.commit()
        self._append_run_to_group(run_group_id, run_id)
        return self.get_run(run_id)

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
        current = self.get_run(run_id)
        if pending_approval is _UNSET:
            pending_approval_json = self._pending_approval_json(run_id)
        else:
            pending_approval_json = _json_dump(pending_approval or {})
        self._conn.execute(
            """
            UPDATE runs
               SET status=?, result=?, timeline_json=?, artifacts_json=?, pending_approval_json=?, updated_at=?
             WHERE run_id=?
            """,
            (
                status or current["status"],
                result if result is not None else current["result"],
                _json_dump(timeline if timeline is not None else current["timeline"]),
                _json_dump(artifacts if artifacts is not None else current["artifacts"]),
                pending_approval_json,
                _now(),
                run_id,
            ),
        )
        self._conn.commit()
        return self.get_run(run_id)

    @staticmethod
    def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        return {"time": _now(), "event": event, "detail": redact_secrets(detail), **extra}

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
            "runtime": "yachiyo_agent",
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
                "Runtime: Yachiyo Agent Runtime\n"
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
                # 更新 run 状态为 failed
                self._update_run(
                    run["run_id"],
                    status="failed",
                    result=str(exc),
                    timeline=[self._timeline("agent.run.failed", str(exc))],
                    artifacts=[],
                    pending_approval=None,
                )
                if on_complete:
                    on_complete({
                        **run,
                        "status": "failed",
                        "result": str(exc),
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
        timeline.append(
            self._timeline(
                "agent.runtime.compiled",
                "Yachiyo Agent Runtime compiled tools and workspace policy",
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
            result = self._run_custom_api_agent(agent, context, broker, timeline, artifacts)
            timeline.append(self._timeline("agent.run.completed", "Agent run completed"))
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
            return self._update_run(
                run_id,
                status="approval_required",
                result=f"等待审批：{exc.pending_approval.get('tool') or 'tool'}",
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=exc.pending_approval,
            )
        except Exception as exc:
            timeline.append(self._timeline("agent.run.failed", str(exc)))
            return self._update_run(
                run_id,
                status="failed",
                result=str(exc),
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
                "You are running inside Hermes-Yachiyo Agent Runtime. "
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
        tools = self._tool_schemas(allowed_tools)
        for iteration in range(max(0, int(start_iteration or 0)), _MAX_AGENT_TOOL_ITERATIONS):
            message = openai_compatible_chat_message(base_url, model, api_key, messages, tools=tools)
            content = _message_content_text(message)
            tool_requests = self._tool_requests_from_message(message, content)
            detail = content[:500] if content else ", ".join(request["tool"] for request in tool_requests)[:500]
            timeline.append(self._timeline("agent.model.response", detail))
            if not tool_requests:
                return content

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
            f"{AgentRuntimeService._tool_loop_limit_detail(timeline)}"
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
    ) -> None:
        user_goal = _user_goal_from_agent_messages(messages)
        for index, tool_request in enumerate(tool_requests):
            tool_name = _normalize_tool_name(tool_request.get("tool"))
            raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
            input_preview = _tool_input_preview(raw_input)
            goal_block_reason = _agent_goal_disallows_tool(user_goal, tool_name)
            if goal_block_reason:
                tool_result = {
                    "ok": False,
                    "blocked_by_user_goal": True,
                    "tool": tool_name,
                    "error": goal_block_reason,
                    "hint": "Do not ask for approval. Continue with an inline answer that follows the user's stated constraint.",
                }
                timeline.append(self._timeline("agent.tool.skipped", tool_name, input_preview=input_preview, result=tool_result))
                self._append_tool_result_message(messages, {**tool_request, "tool": tool_name}, tool_result)
                continue
            tool_result = self._call_agent_tool(tool_request, allowed_tools, broker, timeline, artifacts=artifacts)
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
    ) -> dict[str, Any]:
        tool_name = _normalize_tool_name(tool_request.get("tool"))
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        input_preview = _tool_input_preview(payload)
        if tool_name not in allowed_tools:
            timeline.append(self._timeline("agent.tool.denied", tool_name, input_preview=input_preview))
            raise AgentRuntimeError(f"Agent 试图调用未授权工具：{tool_name}")
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
                "error": str(exc),
                "hint": (
                    "Workspace tools only accept relative paths within the configured Default Workdir. "
                    "Use a valid relative path and do not retry the same invalid path."
                    f"{terminal_hint}"
                ),
                **({"suggested_tool": "terminal.run"} if "terminal.run" in allowed_tools else {}),
            }
        timeline.append(self._timeline("agent.tool.call", tool_name, input_preview=input_preview, result=tool_result))
        if artifacts is not None and tool_name == "artifact.write" and tool_result.get("ok"):
            artifact = {"kind": "tool_artifact", **tool_result}
            if artifact not in artifacts:
                artifacts.append(artifact)
        return tool_result

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
    def _chat_profile_model_config_private(profile_id: str) -> dict[str, Any]:
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
        if str(profile.get("capability") or "chat") != "chat":
            raise AgentRuntimeError("Agent 文本推理需要 chat 模型 Profile")
        return {
            "provider": profile.get("provider") or "openai_compatible",
            "base_url": profile.get("base_url") or "",
            "model": profile.get("model") or "",
            "api_key": profile.get("api_key") or "",
        }

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
            return {"ok": False, "message": str(exc)}
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
                failed = self._update_run(
                    run["run_id"],
                    status="failed",
                    result=str(exc),
                    timeline=[*timeline, self._timeline("workflow.run.failed", str(exc), status="failed")],
                    artifacts=[],
                    pending_approval=None,
                )
                if root_group:
                    self._update_run_group(run_group_id, status="failed", summary=str(exc))
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
        for workflow_run in self._workflow_parent_runs_waiting_for_child(child_run):
            self._resume_parent_workflow_after_child_update(workflow_run, child_run)

    def _mark_parent_workflows_child_running(self, child_run: dict[str, Any]) -> None:
        for workflow_run in self._workflow_parent_runs_waiting_for_child(child_run):
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
            if not any(
                event.get("event") == "workflow.run.child_resumed"
                and str(event.get("child_run_id") or "") == child_run_id
                for event in timeline
                if isinstance(event, dict)
            ):
                timeline.append(
                    self._timeline(
                        "workflow.run.child_resumed",
                        f"{child_label} approved and resumed",
                        child_run_id=child_run_id,
                        status="running",
                        **child_node_info,
                    )
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

    def _resume_parent_workflow_after_child_update(
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
        child_label, child_node_info = self._workflow_child_node_context(timeline, child_run)
        self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, child_label)
        if child_status == "approval_required":
            timeline.append(
                self._timeline(
                    "workflow.run.approval_required",
                    child_label,
                    child_run_id=child_run_id,
                    status="approval_required",
                    **child_node_info,
                )
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
            status = "cancelled" if child_status == "cancelled" else "failed"
            detail = (
                f"{child_run.get('runnable_name') or child_run.get('runnable_id')}: "
                f"{child_result}"
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
            timeline.append(
                self._timeline(
                    "workflow.run.resumed",
                    "Workflow resumed after child Agent approval",
                    child_run_id=child_run_id,
                )
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
            timeline.append(
                self._timeline(
                    "workflow.run.failed",
                    str(exc),
                    status="failed",
                    **failed_event_extra,
                )
            )
            result = self._update_run(
                str(workflow_run["run_id"]),
                status="failed",
                result=str(exc),
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(run_group_id, status="failed", summary=str(exc))
            return result

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
        run_group_id = str(run.get("run_group_id") or "")
        current_node_info: dict[str, str] = {}
        try:
            workflow_goal = str(run.get("user_goal") or context)
            has_agent_upstream = max(0, start_index) > 0
            path = self._workflow_path(workflow)
            for index, node in enumerate(path[max(0, start_index) :], start=max(0, start_index)):
                kind = self._node_kind(node)
                label = str((node.get("data") or {}).get("label") or node.get("id"))
                current_node_info = {
                    "workflow_node_id": str(node.get("id") or ""),
                    "workflow_node_kind": kind,
                    "workflow_node_label": label,
                }
                if kind == "start":
                    timeline.append(
                        self._timeline(
                            "workflow.node.start",
                            label,
                            workflow_node_id=str(node.get("id") or ""),
                            status="completed",
                        )
                    )
                    continue
                if kind == "agent":
                    data = node.get("data") or {}
                    agent = self._workflow_agent_for_node(node)
                    agent_id = str(agent.get("agent_id") or data.get("agent_id") or data.get("agentId") or "")
                    step_task = self._workflow_node_task(node)
                    child_goal = self._workflow_child_goal(workflow_goal, step_task)
                    agent_upstream = context if has_agent_upstream else ""
                    child = self._insert_run(
                        kind="agent_run",
                        runnable_id=agent_id,
                        user_goal=child_goal,
                        run_group_id=run_group_id,
                    )
                    child = self._execute_agent_run(
                        child["run_id"],
                        agent,
                        child_goal,
                        upstream=agent_upstream,
                    )
                    context = child["result"]
                    has_agent_upstream = True
                    timeline.append(
                        self._timeline(
                            "workflow.node.agent",
                            label,
                            workflow_node_id=str(node.get("id") or ""),
                            workflow_node_kind=kind,
                            workflow_node_label=label,
                            workflow_node_task=step_task,
                            child_run_id=child["run_id"],
                            status=child["status"],
                            result=_tool_input_preview(child.get("result") or "", limit=1800),
                            artifact_count=len(self._workflow_child_artifact_refs(child, label)),
                        )
                    )
                    self._merge_workflow_child_run_outcome(timeline, artifacts, child, label)
                    if child["status"] == "approval_required":
                        timeline.append(
                            self._timeline(
                                "workflow.run.approval_required",
                                label,
                                workflow_node_id=str(node.get("id") or ""),
                                workflow_node_kind=kind,
                                workflow_node_label=label,
                                child_run_id=child["run_id"],
                            )
                        )
                        result = self._update_run(
                            str(run["run_id"]),
                            status="approval_required",
                            result=context,
                            timeline=timeline,
                            artifacts=artifacts,
                        )
                        if root_group:
                            self._update_run_group(
                                run_group_id,
                                status="approval_required",
                                summary=context,
                            )
                            result = self.get_run(result["run_id"])
                        return result
                    if child["status"] != "completed":
                        status = "cancelled" if child["status"] == "cancelled" else "failed"
                        detail = f"{label}: {context or child['status']}"
                        timeline.append(
                            self._timeline(
                                f"workflow.run.{status}",
                                detail,
                                workflow_node_id=str(node.get("id") or ""),
                                workflow_node_kind=kind,
                                workflow_node_label=label,
                                child_run_id=child["run_id"],
                                status=child["status"],
                            )
                        )
                        result = self._update_run(
                            str(run["run_id"]),
                            status=status,
                            result=context,
                            timeline=timeline,
                            artifacts=artifacts,
                        )
                        if root_group:
                            self._update_run_group(run_group_id, status=status, summary=context)
                            result = self.get_run(result["run_id"])
                        return result
                    continue
                if kind == "approval":
                    criteria = self._workflow_approval_criteria(node)
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
                        "workflow_next_index": index + 1,
                        "workflow_node_id": str(node.get("id") or ""),
                        "workflow_node_label": label,
                        "workflow_node_approval_criteria": criteria,
                    }
                    timeline.append(
                            self._timeline(
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
                    result = self._update_run(
                        str(run["run_id"]),
                        status="approval_required",
                        result=f"等待审批：{label}",
                        timeline=timeline,
                        artifacts=artifacts,
                        pending_approval=pending,
                    )
                    if root_group:
                        self._update_run_group(
                            run_group_id,
                            status="approval_required",
                            summary=f"等待审批：{label}",
                        )
                        result = self.get_run(result["run_id"])
                    return result
                if kind == "artifact":
                    data = node.get("data") or {}
                    broker = ToolBroker(
                        self._default_workspace_policy(),
                        self.workflow_artifacts_dir / str(run["run_id"]),
                    )
                    workflow_node_id = str(node.get("id") or "")
                    artifact_path = self._workflow_artifact_path(
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
                    timeline.append(
                        self._timeline(
                            "workflow.node.artifact",
                            label,
                            workflow_node_id=workflow_node_id,
                            workflow_node_kind=kind,
                            workflow_node_label=label,
                            status="completed",
                            artifact=artifact,
                        )
                    )
                    continue
                raise AgentRuntimeError(f"未知 Workflow 节点类型：{kind}")
            timeline.append(self._timeline("workflow.run.completed", "Workflow run completed"))
            result = self._update_run(
                str(run["run_id"]),
                status="completed",
                result=context,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(run_group_id, status="completed", summary=context)
                result = self.get_run(result["run_id"])
            return result
        except Exception as exc:
            timeline.append(self._timeline("workflow.run.failed", str(exc), status="failed", **current_node_info))
            result = self._update_run(
                str(run["run_id"]),
                status="failed",
                result=str(exc),
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(run_group_id, status="failed", summary=str(exc))
                result = self.get_run(result["run_id"])
            return result

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
        run = self.get_run(run_id)
        if run["status"] in _FINAL_RUN_STATUSES:
            return run
        timeline = [*run["timeline"]]
        artifacts: list[dict[str, Any]] | None = None
        result_text: str | None = None
        if run.get("kind") == "workflow_run":
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
                    "workflow_node_approval_criteria": str(pending.get("workflow_node_approval_criteria") or "").strip(),
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
                            label = str(event.get("detail") or event.get("workflow_node_label") or "Agent").strip() or "Agent"
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
            result_text = f"Workflow 已取消：{label}"
        else:
            timeline.append(self._timeline("run.cancelled", "Run cancelled"))
        result = self._update_run(
            run_id,
            status="cancelled",
            result=result_text,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
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

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "approval_required":
            raise AgentRuntimeError("Run 当前不在待审批状态")
        if run["kind"] == "workflow_run":
            return self._approve_workflow_run_approval(run)
        if run["kind"] != "agent_run":
            raise AgentRuntimeError("当前只支持恢复 Agent Run 的工具审批")
        pending = self._pending_approval_private(run_id)
        if not pending:
            raise AgentRuntimeError("Run 缺少待审批工具信息")
        agent = self._get_agent_private(str(run["runnable_id"]))
        runtime = self._compile_agent_runtime(agent)
        broker = ToolBroker(runtime["workspace_policy"], self.agent_artifacts_dir / run_id)
        allowed_tools = runtime["tool_policy"].get("allowed_tools") or []
        timeline = [*run["timeline"]]
        artifacts = [item for item in run.get("artifacts") or [] if isinstance(item, dict)]
        messages = pending.get("messages") if isinstance(pending.get("messages"), list) else []
        tool_request = pending.get("tool_request") if isinstance(pending.get("tool_request"), dict) else {}
        if not messages or not tool_request:
            raise AgentRuntimeError("Run 待审批上下文不完整，无法恢复")
        tool_name = str(tool_request.get("tool") or pending.get("tool") or "").strip()
        tool_input_preview = _tool_input_preview(tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {})
        timeline.append(
            self._timeline(
                "agent.tool.approval_approved",
                tool_name or "tool",
                input_preview=tool_input_preview,
                status="completed",
            )
        )
        timeline.append(
            self._timeline(
                "agent.run.resumed",
                "Agent resumed after approval",
                status="running",
            )
        )
        running = self._update_run(
            run_id,
            status="running",
            result="已批准，Agent 正在继续执行",
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )
        self._update_agent_run_group_if_root(running)
        self._mark_parent_workflows_child_running(running)
        try:
            tool_result = self._call_agent_tool(tool_request, allowed_tools, broker, timeline, artifacts=artifacts, approved=True)
            fatal_failure = self._fatal_tool_failure_detail(tool_name, tool_request, tool_result)
            if fatal_failure:
                timeline.append(
                    self._timeline(
                        "agent.tool.failed",
                        tool_name or "tool",
                        input_preview=tool_input_preview,
                        result=tool_result,
                        status="failed",
                    )
                )
                raise AgentRuntimeError(fatal_failure)
            self._append_tool_result_message(messages, tool_request, tool_result)
            remaining = pending.get("remaining_tool_requests")
            remaining_requests = [item for item in remaining if isinstance(item, dict)] if isinstance(remaining, list) else []
            self._run_tool_requests(
                remaining_requests,
                allowed_tools,
                broker,
                messages,
                timeline,
                artifacts,
                next_iteration=int(pending.get("next_iteration") or 0),
            )
            result_text = self._run_custom_api_agent(
                agent,
                "",
                broker,
                timeline,
                artifacts,
                messages=messages,
                start_iteration=int(pending.get("next_iteration") or 0),
            )
            timeline.append(self._timeline("agent.run.completed", "Agent run completed"))
            result = self._update_run(
                run_id,
                status="completed",
                result=result_text,
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
            result = self._update_run(
                run_id,
                status="approval_required",
                result=f"等待审批：{exc.pending_approval.get('tool') or 'tool'}",
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=exc.pending_approval,
            )
        except Exception as exc:
            timeline.append(self._timeline("agent.run.failed", str(exc)))
            result = self._update_run(
                run_id,
                status="failed",
                result=str(exc),
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=None,
            )
        self._update_agent_run_group_if_root(result)
        self._resume_parent_workflows_after_child_update(result)
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
        timeline.append(
            self._timeline(
                "workflow.node.approval_approved",
                label,
                workflow_node_id=workflow_node_id,
                workflow_node_kind="approval",
                workflow_node_label=label,
                workflow_node_approval_criteria=criteria,
                input_preview=approval_preview,
                status="completed",
            )
        )
        artifacts = [item for item in run.get("artifacts") or [] if isinstance(item, dict)]
        root_group = self._workflow_run_is_group_root(run)
        running = self._update_run(
            run_id,
            status="running",
            result=context,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )
        if root_group:
            self._update_run_group(str(run.get("run_group_id") or ""), status="running", summary=context)
            running = self.get_run(run_id)
        return self._continue_workflow_run(
            running,
            workflow,
            context=context,
            timeline=timeline,
            artifacts=artifacts,
            start_index=start_index,
            root_group=root_group,
        )

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "approval_required":
            raise AgentRuntimeError("Run 当前不在待审批状态")
        if run["kind"] == "workflow_run":
            pending = self._pending_approval_private(run_id)
            if not pending or str(pending.get("tool") or "") != "workflow.approval":
                raise AgentRuntimeError("Workflow Run 缺少待审批节点信息")
            label = str(pending.get("workflow_node_label") or "Approval")
            criteria = str(pending.get("workflow_node_approval_criteria") or "").strip()
            approval_preview = pending.get("input_preview") if isinstance(pending.get("input_preview"), dict) else {}
            detail = redact_secrets(reason).strip() or f"{label} approval rejected"
            timeline = [
                *run["timeline"],
                self._timeline(
                    "workflow.node.approval_rejected",
                    detail,
                    workflow_node_id=str(pending.get("workflow_node_id") or ""),
                    workflow_node_kind="approval",
                    workflow_node_label=label,
                    workflow_node_approval_criteria=criteria,
                    input_preview=approval_preview,
                    status="cancelled",
                ),
                self._timeline(
                    "workflow.run.cancelled",
                    detail,
                    workflow_node_id=str(pending.get("workflow_node_id") or ""),
                    workflow_node_kind="approval",
                    workflow_node_label=label,
                    workflow_node_approval_criteria=criteria,
                    input_preview=approval_preview,
                    status="cancelled",
                ),
            ]
            result = self._update_run(
                run_id,
                status="cancelled",
                result=f"Workflow 审批已拒绝：{detail}",
                timeline=timeline,
                pending_approval=None,
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
        detail = redact_secrets(reason).strip() or "Tool approval rejected"
        timeline = [
            *run["timeline"],
            self._timeline(
                "agent.tool.approval_rejected",
                detail,
                tool=tool_name,
                input_preview=tool_input_preview,
                status="cancelled",
            ),
        ]
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"工具审批已拒绝：{detail}",
            timeline=timeline,
            pending_approval=None,
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
            if agent.get("enabled", True)
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
        if runnable_id:
            agent = self._conn.execute("SELECT * FROM agents WHERE agent_id=?", (runnable_id,)).fetchone()
            if agent:
                return self._agent_runnable_summary(self._row_to_agent(agent))
            workflow = self._conn.execute("SELECT * FROM workflows WHERE workflow_id=?", (runnable_id,)).fetchone()
            if workflow:
                return self._workflow_runnable_summary(self._row_to_workflow(workflow))
        clean_name = (name or "").strip()
        if clean_name:
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
    ) -> dict[str, Any]:
        runnable = self.resolve_runnable(runnable_id=runnable_id, name=name)
        if runnable is None:
            raise AgentRuntimeError("未找到指定 Agent 或 Workflow")
        if not runnable.get("enabled", True):
            raise AgentRuntimeError("指定 Agent 或 Workflow 已停用")
        if runnable["kind"] == "agent":
            run = self.create_agent_run({
                "agent_id": runnable["id"],
                "user_goal": user_goal,
                "source": "agent",
                "run_group_id": run_group_id,
                "upstream": upstream,
            })
            run["agent_run_id"] = run["run_id"]
            run["runnable"] = runnable
            return run
        run = self.create_workflow_run({
            "workflow_id": runnable["id"],
            "user_goal": user_goal,
            "source": "workflow",
            "run_group_id": run_group_id,
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
        mention = AgentRuntimeService._chat_mention_parts(value)
        if mention is None:
            return None
        prefix, body, remaining_lines = mention
        match = re.match(r"^(?P<name>\"[^\"]+\"|'[^']+'|[^\s，。！？、；;,.!?]+)\s*(?P<body>.*)$", body)
        if not match:
            return None
        raw_name = match.group("name").strip("\"'")
        rest = match.group("body")
        return raw_name, AgentRuntimeService._chat_mention_goal(prefix, rest, remaining_lines)

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


_global_agent_runtime_service: AgentRuntimeService | None = None


def get_agent_runtime_service() -> AgentRuntimeService:
    global _global_agent_runtime_service
    if _global_agent_runtime_service is None:
        _global_agent_runtime_service = AgentRuntimeService()
    return _global_agent_runtime_service


def close_agent_runtime_service() -> None:
    global _global_agent_runtime_service
    if _global_agent_runtime_service is not None:
        _global_agent_runtime_service.close()
        _global_agent_runtime_service = None
