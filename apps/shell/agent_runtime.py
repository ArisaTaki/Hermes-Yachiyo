"""Agent Studio, Skill Library, and Workflow runtime services."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import uuid4

from apps.shell.model_profiles import (
    get_model_profile_service,
    openai_compatible_chat_message,
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
_FINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
_UNSET = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hermes_yachiyo_home() -> Path:
    hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
    root = Path(hermes_home) / "yachiyo"
    root.mkdir(parents=True, exist_ok=True)
    return root


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
        if not target.exists():
            raise AgentRuntimeError("路径不存在")
        if not target.is_dir():
            raise AgentRuntimeError("workspace.list 只能列目录")
        entries = []
        for child in sorted(target.iterdir(), key=lambda item: item.name.lower())[:200]:
            entries.append({"name": child.name, "type": "dir" if child.is_dir() else "file"})
        return {"ok": True, "path": path or ".", "entries": entries}

    def workspace_read(self, path: str) -> dict[str, Any]:
        target = self._resolve_workspace_path(path)
        if not target.is_file():
            raise AgentRuntimeError("workspace.read 只能读取文件")
        return {"ok": True, "path": path, "content": _read_text(target)}

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
        self.agent_artifacts_dir = root / "artifacts" / "agent-runs"
        self.workflow_artifacts_dir = root / "artifacts" / "workflow-runs"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.agent_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.workflow_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        if seed_templates:
            self._seed_templates()

    def close(self) -> None:
        self._conn.close()

    def _ensure_row_factory(self) -> None:
        if self._conn.row_factory is not sqlite3.Row:
            self._conn.row_factory = sqlite3.Row

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
                content_summary TEXT NOT NULL DEFAULT '',
                skill_markdown TEXT NOT NULL,
                asset_paths_json TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
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
        if "enabled" not in skill_columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        run_columns = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "run_group_id" not in run_columns:
            self._conn.execute("ALTER TABLE runs ADD COLUMN run_group_id TEXT NOT NULL DEFAULT ''")
        if "pending_approval_json" not in run_columns:
            self._conn.execute("ALTER TABLE runs ADD COLUMN pending_approval_json TEXT NOT NULL DEFAULT '{}'")

    def _seed_templates(self) -> None:
        count = self._conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        if count:
            return
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
        for agent_id, name, description, category, instructions, output_contract in templates:
            self.create_agent(
                {
                    "agent_id": agent_id,
                    "name": name,
                    "description": description,
                    "category": category,
                    "instructions": instructions,
                    "model_mode": "profile",
                    "tool_policy": self._default_tool_policy(category),
                    "workspace_policy": self._default_workspace_policy(),
                    "output_contract": output_contract,
                    "enabled": True,
                },
                seed=True,
            )
        self.create_workflow(
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
                        "data": {"label": "Design Agent", "agent_id": "agent_design"},
                    },
                    {
                        "id": "approval",
                        "type": "approval",
                        "position": {"x": 440, "y": 80},
                        "data": {"label": "人工审批"},
                    },
                    {
                        "id": "coding",
                        "type": "agent",
                        "position": {"x": 660, "y": 80},
                        "data": {"label": "Coding Agent", "agent_id": "agent_coding"},
                    },
                    {
                        "id": "review",
                        "type": "agent",
                        "position": {"x": 880, "y": 80},
                        "data": {"label": "Review Agent", "agent_id": "agent_review"},
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
            seed=True,
        )

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

    @staticmethod
    def _tool_schemas(allowed_tools: list[str]) -> list[dict[str, Any]]:
        specs: dict[str, dict[str, Any]] = {
            "workspace.list": {
                "description": "List entries in an allowed workspace directory.",
                "properties": {"path": {"type": "string", "description": "Relative directory path."}},
            },
            "workspace.read": {
                "description": "Read a UTF-8 text file from the allowed workspace.",
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
        if "artifact.write" not in normalized_allowed:
            normalized_allowed.append("artifact.write")

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

    def _row_to_agent(self, row: sqlite3.Row) -> dict[str, Any]:
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

    def _row_to_agent_private(self, row: sqlite3.Row) -> dict[str, Any]:
        agent = self._row_to_agent(row)
        agent["model_config"]["api_key"] = row["model_api_key"]
        return agent

    def _row_to_skill(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "skill_id": row["skill_id"],
            "name": row["name"],
            "description": row["description"],
            "source_path": row["source_path"],
            "local_path": row["local_path"] or str(self.skills_dir / row["skill_id"]),
            "content_summary": row["content_summary"],
            "skill_markdown": row["skill_markdown"],
            "asset_paths": _json_load(row["asset_paths_json"], []),
            "enabled": bool(row["enabled"]),
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
        run = {
            "run_id": row["run_id"],
            "run_group_id": row["run_group_id"],
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
        rows = self._conn.execute("SELECT * FROM agents ORDER BY category, name").fetchall()
        return {"ok": True, "agents": [self._row_to_agent(row) for row in rows]}

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if row is None:
            raise KeyError(agent_id)
        return self._row_to_agent(row)

    def _get_agent_private(self, agent_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if row is None:
            raise KeyError(agent_id)
        return self._row_to_agent_private(row)

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

    def list_skills(self) -> dict[str, Any]:
        self._ensure_row_factory()
        rows = self._conn.execute("SELECT * FROM skills ORDER BY updated_at DESC").fetchall()
        return {"ok": True, "skills": [self._row_to_skill(row) for row in rows]}

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT * FROM skills WHERE skill_id=?", (skill_id,)).fetchone()
        if row is None:
            raise KeyError(skill_id)
        return self._row_to_skill(row)

    def import_skill(self, source_path: str) -> dict[str, Any]:
        source = Path(source_path).expanduser()
        if not source.exists():
            raise AgentRuntimeError("Skill 路径不存在")
        temp_dir: Path | None = None
        if source.is_file():
            if source.suffix.lower() != ".zip":
                raise AgentRuntimeError("Skill 文件只支持 ZIP")
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
        skill_md = source_root / "SKILL.md"
        if not skill_md.is_file():
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise AgentRuntimeError("Skill 根目录必须包含 SKILL.md")
        markdown = _read_text(skill_md)
        name = self._skill_name(markdown, source_root.name)
        description = self._skill_description(markdown)
        skill_id = f"skill_{_slug(name, 'skill')}_{uuid4().hex[:8]}"
        target = self.skills_dir / skill_id
        shutil.copytree(source_root, target)
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
        asset_paths = self._skill_asset_paths(target)
        summary = self._skill_summary(markdown)
        now = _now()
        self._conn.execute(
            """
            INSERT INTO skills (
                skill_id, name, description, source_path, local_path, content_summary,
                skill_markdown, asset_paths_json, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                skill_id,
                name,
                description,
                f"local:{source.name}",
                str(target),
                summary,
                markdown,
                _json_dump(asset_paths),
                1,
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get_skill(skill_id)

    def update_skill(self, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_skill(skill_id)
        if "enabled" not in payload:
            return current
        enabled = payload.get("enabled")
        self._conn.execute(
            """
            UPDATE skills
               SET enabled=?, updated_at=?
             WHERE skill_id=?
            """,
            (1 if enabled is not False else 0, _now(), skill_id),
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
        self._conn.execute("DELETE FROM skills WHERE skill_id=?", (skill_id,))
        rows = self._conn.execute("SELECT agent_id, skill_ids_json FROM agents").fetchall()
        for row in rows:
            skill_ids = [item for item in _json_load(row["skill_ids_json"], []) if item != skill_id]
            self._conn.execute(
                "UPDATE agents SET skill_ids_json=?, updated_at=? WHERE agent_id=?",
                (_json_dump(skill_ids), _now(), row["agent_id"]),
            )
        self._conn.commit()
        shutil.rmtree(self.skills_dir / skill_id, ignore_errors=True)
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
        self._conn.commit()
        return self.get_workflow(workflow_id)

    def update_workflow(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_workflow(workflow_id)
        if "name" in payload:
            self._ensure_global_name_available(str(payload.get("name") or ""), ignore_workflow_id=workflow_id)
        next_workflow = {**current, **payload}
        self.validate_workflow(next_workflow.get("nodes") or [], next_workflow.get("edges") or [])
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
        self._conn.execute("DELETE FROM workflows WHERE workflow_id=?", (workflow_id,))
        self._conn.commit()
        return {"ok": True}

    @staticmethod
    def _node_kind(node: dict[str, Any]) -> str:
        data = node.get("data") or {}
        return str(node.get("type") or data.get("kind") or data.get("node_type") or "").strip()

    def validate_workflow(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        if not nodes:
            raise AgentRuntimeError("Workflow 至少需要一个 Start 节点")
        node_ids = [str(node.get("id") or "") for node in nodes]
        if len(set(node_ids)) != len(node_ids) or any(not node_id for node_id in node_ids):
            raise AgentRuntimeError("Workflow 节点 ID 必须唯一")
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

    def list_runs(self, limit: int = 50) -> dict[str, Any]:
        self._ensure_row_factory()
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY updated_at DESC LIMIT ?",
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

    def get_run(self, run_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._row_to_run(row)

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
                f"# Output Contract\n{agent.get('output_contract') or 'chat'}",
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
        if not agent.get("enabled", True):
            raise AgentRuntimeError("Agent 已停用")
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
        result = self._execute_agent_run(run["run_id"], agent, user_goal)
        if root_group:
            self._update_run_group(run_group_id, status=result["status"], summary=result.get("result") or "")
            result = self.get_run(result["run_id"])
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
            prompt = (
                "You are running inside Hermes-Yachiyo Agent Runtime. "
                "Return concise final output. Prefer native tool_calls when available. "
                "If the model endpoint does not support tool_calls and a controlled tool is needed, respond as JSON "
                "{\"action\":\"tool\",\"tool\":\"workspace.list\",\"input\":{}}; otherwise respond normally. "
                "Request at most one high-risk tool per turn.\n\n"
                f"Allowed tools: {', '.join(allowed_tools)}\n\n{context}"
            )
            messages = [{"role": "user", "content": prompt}]
        tools = self._tool_schemas(allowed_tools)
        for iteration in range(max(0, int(start_iteration or 0)), 6):
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
        raise AgentRuntimeError("custom_api Agent 工具循环超过上限")

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
        for index, tool_request in enumerate(tool_requests):
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
        if tool_name not in allowed_tools:
            timeline.append(self._timeline("agent.tool.denied", tool_name))
            raise AgentRuntimeError(f"Agent 试图调用未授权工具：{tool_name}")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        tool_result = broker.call(tool_name, payload, approved=approved)
        timeline.append(self._timeline("agent.tool.call", tool_name, result=tool_result))
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
            "next_iteration": max(0, min(int(next_iteration or 0), 6)),
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

    def _agent_model_config_private(self, agent: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(agent.get("model_profile_id") or "").strip()
        if profile_id:
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
            with urlrequest.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError) as exc:
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
        timeline = [self._timeline("workflow.run.started", workflow["name"])]
        artifacts: list[dict[str, Any]] = []
        context = user_goal
        try:
            for node in self._workflow_path(workflow):
                kind = self._node_kind(node)
                label = str((node.get("data") or {}).get("label") or node.get("id"))
                if kind == "start":
                    timeline.append(self._timeline("workflow.node.start", label))
                    continue
                if kind == "agent":
                    agent_id = str((node.get("data") or {}).get("agent_id") or (node.get("data") or {}).get("agentId") or "")
                    if not agent_id:
                        raise AgentRuntimeError(f"Agent 节点 {label} 缺少 agent_id")
                    agent = self._get_agent_private(agent_id)
                    child = self._insert_run(kind="agent_run", runnable_id=agent_id, user_goal=context, run_group_id=run_group_id)
                    child = self._execute_agent_run(child["run_id"], agent, context, upstream=context)
                    context = child["result"]
                    timeline.append(self._timeline("workflow.node.agent", label, child_run_id=child["run_id"], status=child["status"]))
                    if child["status"] == "approval_required":
                        timeline.append(self._timeline("workflow.run.approval_required", label, child_run_id=child["run_id"]))
                        result = self._update_run(run["run_id"], status="approval_required", result=context, timeline=timeline, artifacts=artifacts)
                        if root_group:
                            self._update_run_group(run_group_id, status="approval_required", summary=context)
                            result = self.get_run(result["run_id"])
                        return result
                    continue
                if kind == "approval":
                    timeline.append(self._timeline("workflow.node.approval", f"{label} checkpoint recorded"))
                    continue
                if kind == "artifact":
                    broker = ToolBroker(self._default_workspace_policy(), self.workflow_artifacts_dir / run["run_id"])
                    artifact = broker.artifact_write(f"{_slug(label, 'artifact')}.md", context)
                    artifacts.append({"kind": "workflow_artifact", **artifact})
                    timeline.append(self._timeline("workflow.node.artifact", label))
                    continue
                raise AgentRuntimeError(f"未知 Workflow 节点类型：{kind}")
            timeline.append(self._timeline("workflow.run.completed", "Workflow run completed"))
            result = self._update_run(run["run_id"], status="completed", result=context, timeline=timeline, artifacts=artifacts)
            if root_group:
                self._update_run_group(run_group_id, status="completed", summary=context)
                result = self.get_run(result["run_id"])
            return result
        except Exception as exc:
            timeline.append(self._timeline("workflow.run.failed", str(exc)))
            result = self._update_run(run["run_id"], status="failed", result=str(exc), timeline=timeline, artifacts=artifacts)
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

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] in _FINAL_RUN_STATUSES:
            return run
        timeline = [*run["timeline"], self._timeline("run.cancelled", "Run cancelled")]
        result = self._update_run(run_id, status="cancelled", timeline=timeline, pending_approval=None)
        self._update_agent_run_group_if_root(result)
        return result

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "approval_required":
            raise AgentRuntimeError("Run 当前不在待审批状态")
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
        try:
            tool_result = self._call_agent_tool(tool_request, allowed_tools, broker, timeline, artifacts=artifacts, approved=True)
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
        return result

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "approval_required":
            raise AgentRuntimeError("Run 当前不在待审批状态")
        detail = redact_secrets(reason).strip() or "Tool approval rejected"
        timeline = [*run["timeline"], self._timeline("agent.tool.approval_rejected", detail)]
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"工具审批已拒绝：{detail}",
            timeline=timeline,
            pending_approval=None,
        )
        self._update_agent_run_group_if_root(result)
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
                {"id": agent["agent_id"], "name": agent["name"], "kind": "agent", "enabled": agent["enabled"]}
                for agent in agents
            ]
            + [
                {"id": workflow["workflow_id"], "name": workflow["name"], "kind": "workflow", "enabled": workflow["enabled"]}
                for workflow in workflows
            ],
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
            agent = self._conn.execute("SELECT agent_id, name, enabled FROM agents WHERE agent_id=?", (runnable_id,)).fetchone()
            if agent:
                return {"kind": "agent", "id": agent["agent_id"], "name": agent["name"], "enabled": bool(agent["enabled"])}
            workflow = self._conn.execute("SELECT workflow_id, name, enabled FROM workflows WHERE workflow_id=?", (runnable_id,)).fetchone()
            if workflow:
                return {"kind": "workflow", "id": workflow["workflow_id"], "name": workflow["name"], "enabled": bool(workflow["enabled"])}
        clean_name = (name or "").strip()
        if clean_name:
            agent = self._conn.execute("SELECT agent_id, name, enabled FROM agents WHERE LOWER(name)=LOWER(?)", (clean_name,)).fetchone()
            workflow = self._conn.execute("SELECT workflow_id, name, enabled FROM workflows WHERE LOWER(name)=LOWER(?)", (clean_name,)).fetchone()
            matches = [item for item in (agent, workflow) if item is not None]
            if len(matches) > 1:
                raise AgentRuntimeError("Agent/Workflow 名称不唯一")
            if agent:
                return {"kind": "agent", "id": agent["agent_id"], "name": agent["name"], "enabled": bool(agent["enabled"])}
            if workflow:
                return {"kind": "workflow", "id": workflow["workflow_id"], "name": workflow["name"], "enabled": bool(workflow["enabled"])}
        return None

    def create_run_for_runnable(self, *, runnable_id: str = "", name: str = "", user_goal: str = "") -> dict[str, Any]:
        runnable = self.resolve_runnable(runnable_id=runnable_id, name=name)
        if runnable is None:
            raise AgentRuntimeError("未找到指定 Agent 或 Workflow")
        if not runnable.get("enabled", True):
            raise AgentRuntimeError("指定 Agent 或 Workflow 已停用")
        if runnable["kind"] == "agent":
            run = self.create_agent_run({"agent_id": runnable["id"], "user_goal": user_goal, "source": "chat"})
            run["agent_run_id"] = run["run_id"]
            run["runnable"] = runnable
            return run
        run = self.create_workflow_run({"workflow_id": runnable["id"], "user_goal": user_goal, "source": "chat"})
        run["workflow_run_id"] = run["run_id"]
        run["runnable"] = runnable
        return run

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
        }

    def parse_known_chat_runnable(self, text: str) -> tuple[str, str] | None:
        value = (text or "").strip()
        if not value.startswith("@"):
            return None
        body = value[1:]
        if not body.strip():
            return None
        if body.startswith('"') or body.startswith("'"):
            return self.parse_chat_runnable(value)
        runnables = sorted(
            self.list_runnables()["runnables"],
            key=lambda item: len(str(item.get("name") or "")),
            reverse=True,
        )
        body_lower = body.lower()
        for runnable in runnables:
            name = str(runnable.get("name") or "").strip()
            if not name:
                continue
            if not body_lower.startswith(name.lower()):
                continue
            remainder = body[len(name) :]
            if remainder and not remainder[0].isspace():
                continue
            return name, remainder.strip()
        return self.parse_chat_runnable(value)

    @staticmethod
    def parse_chat_runnable(text: str) -> tuple[str, str] | None:
        first_line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
        if not first_line.startswith("@"):
            return None
        match = re.match(r"^@(?P<name>\"[^\"]+\"|'[^']+'|[^\s]+)\s*(?P<body>.*)$", first_line)
        if not match:
            return None
        raw_name = match.group("name").strip("\"'")
        rest = match.group("body")
        remaining_lines = (text or "").strip().splitlines()[1:]
        body = "\n".join([rest, *remaining_lines]).strip()
        return raw_name, body


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
