"""Controlled tool broker for custom API agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.terminal import (
    _TERMINAL_PROCESS_LOCK,
    _TERMINAL_PROCESSES,
    cancel_terminal_process_groups,
    run_terminal_command,
)
from apps.shell.agent.tools.workspace import (
    _apply_single_file_unified_diff,
    _atomic_write_text,
    _is_within,
    _read_text,
    _safe_rel_path,
    _sha256_bytes,
    _sha256_file,
)
from packages.security import redact_sensitive_text

__all__ = [
    "ToolBroker",
    "_TERMINAL_PROCESSES",
    "_TERMINAL_PROCESS_LOCK",
    "cancel_terminal_process_groups",
]


def _redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


@dataclass
class ToolBroker:
    """Controlled tools exposed to custom API agents."""

    workspace_policy: dict[str, Any]
    artifact_root: Path
    approvals: dict[str, bool] | None = None
    skills: list[dict[str, Any]] | None = None
    memory_store: Any | None = None
    future_task_store: Any | None = None

    def __post_init__(self) -> None:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.approvals = self.approvals or {}
        self.skills = self.skills or []

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

    def skill_read(self, skill_id: str = "", name: str = "") -> dict[str, Any]:
        wanted = str(skill_id or name or "").strip()
        if not wanted:
            return {
                "ok": False,
                "error": "skill.read 需要 skill_id 或 name",
                "available_skills": self._available_skill_refs(),
            }
        wanted_key = wanted.lower()
        for skill in self.skills or []:
            refs = {
                str(skill.get("skill_id") or "").strip().lower(),
                str(skill.get("name") or "").strip().lower(),
                str(skill.get("source_ref") or "").strip().lower(),
            }
            if wanted_key not in refs:
                continue
            markdown = _redact_secrets(str(skill.get("skill_markdown") or ""))
            return {
                "ok": True,
                "skill_id": str(skill.get("skill_id") or ""),
                "name": str(skill.get("name") or ""),
                "description": str(skill.get("description") or ""),
                "skill_markdown": markdown,
                "asset_paths": skill.get("asset_paths") or [],
            }
        return {
            "ok": False,
            "error": "Skill 未挂载到当前 Agent，不能读取完整手册",
            "requested": wanted,
            "available_skills": self._available_skill_refs(),
        }

    def memory_add(self, content: str, kind: str = "", scope: str = "") -> dict[str, Any]:
        if self.memory_store is None:
            return {"ok": False, "error": "当前运行未启用长期记忆存储"}
        return self.memory_store.add(content=content, kind=kind, scope=scope)

    def memory_replace(
        self,
        content: str,
        *,
        memory_id: str = "",
        old_content: str = "",
        kind: str = "",
        scope: str = "",
    ) -> dict[str, Any]:
        if self.memory_store is None:
            return {"ok": False, "error": "当前运行未启用长期记忆存储"}
        return self.memory_store.replace(
            memory_id=memory_id,
            old_content=old_content,
            content=content,
            kind=kind,
            scope=scope,
        )

    def memory_remove(
        self,
        *,
        memory_id: str = "",
        content: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        if self.memory_store is None:
            return {"ok": False, "error": "当前运行未启用长期记忆存储"}
        return self.memory_store.remove(memory_id=memory_id, content=content, reason=reason)

    def future_task_schedule(
        self,
        *,
        title: str = "",
        prompt: str,
        delay_seconds: Any = None,
        scheduled_at_epoch: Any = None,
        cron: str = "",
        runnable_id: str = "",
        runnable_name: str = "",
    ) -> dict[str, Any]:
        if self.future_task_store is None:
            return {"ok": False, "error": "当前运行未启用 FutureTask 存储"}
        return self.future_task_store.schedule(
            title=title,
            prompt=prompt,
            runnable_id=runnable_id,
            runnable_name=runnable_name,
            delay_seconds=delay_seconds,
            scheduled_at_epoch=scheduled_at_epoch,
            cron=cron,
        )

    def future_task_list(
        self,
        *,
        include_finished: bool = True,
        limit: int = 100,
    ) -> dict[str, Any]:
        if self.future_task_store is None:
            return {"ok": False, "error": "当前运行未启用 FutureTask 存储"}
        return {
            "ok": True,
            "future_tasks": self.future_task_store.list_tasks(
                include_finished=include_finished,
                limit=limit,
            ),
        }

    def future_task_cancel(self, future_task_id: str, *, reason: str = "") -> dict[str, Any]:
        if self.future_task_store is None:
            return {"ok": False, "error": "当前运行未启用 FutureTask 存储"}
        try:
            return self.future_task_store.cancel(future_task_id, reason=reason)
        except KeyError:
            return {"ok": False, "error": "FutureTask 不存在", "future_task_id": future_task_id}

    def _available_skill_refs(self) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        for skill in self.skills or []:
            refs.append(
                {
                    "skill_id": str(skill.get("skill_id") or ""),
                    "name": str(skill.get("name") or ""),
                    "description": str(skill.get("description") or ""),
                }
            )
        return refs

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
                "hint": (
                    "这是一个目录；请改用 workspace.list 查看目录内容，"
                    "或选择目录中的具体文件再读取。"
                ),
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
            raise AgentRuntimeError(
                "workspace.write_patch 不再支持 content 全量写入；"
                "请提供单文件 unified diff patch"
            )
        target = self._resolve_workspace_path(path, write=True)
        if not approved and not self.approvals.get("workspace.write_patch"):
            return {"ok": False, "approval_required": True, "tool": "workspace.write_patch"}
        mode = "patch"
        if target.exists() and not target.is_file():
            return {"ok": False, "path": path, "error": "workspace.write_patch 只能写入普通文件"}
        if not target.exists():
            return {
                "ok": False,
                "path": path,
                "error": "workspace.write_patch patch 模式要求目标文件已存在",
            }
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
            return {
                "ok": False,
                "path": path,
                "error": "workspace.write_patch patch 模式只支持 UTF-8 文本文件",
            }
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
        return run_terminal_command(
            command,
            workdir=self.workdir,
            timeout_seconds=timeout_seconds,
            shell=shell,
        )

    def artifact_write(self, path: str, content: str) -> dict[str, Any]:
        rel = _safe_rel_path(path)
        target = (self.artifact_root / rel).resolve()
        if not _is_within(target, self.artifact_root):
            raise AgentRuntimeError("artifact 路径越界")
        target.parent.mkdir(parents=True, exist_ok=True)
        safe_content = _redact_secrets(content)
        target.write_text(safe_content, encoding="utf-8")
        return {"ok": True, "path": rel, "bytes": len(safe_content.encode("utf-8"))}

    def call(self, name: str, payload: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        if name == "skill.read":
            return self.skill_read(
                str(payload.get("skill_id") or ""),
                str(payload.get("name") or ""),
            )
        if name == "memory.add":
            return self.memory_add(
                str(payload.get("content") or ""),
                kind=str(payload.get("kind") or ""),
                scope=str(payload.get("scope") or ""),
            )
        if name == "memory.replace":
            return self.memory_replace(
                str(payload.get("content") or ""),
                memory_id=str(payload.get("memory_id") or ""),
                old_content=str(payload.get("old_content") or ""),
                kind=str(payload.get("kind") or ""),
                scope=str(payload.get("scope") or ""),
            )
        if name == "memory.remove":
            return self.memory_remove(
                memory_id=str(payload.get("memory_id") or ""),
                content=str(payload.get("content") or ""),
                reason=str(payload.get("reason") or ""),
            )
        if name == "future_task.schedule":
            return self.future_task_schedule(
                title=str(payload.get("title") or ""),
                prompt=str(payload.get("prompt") or ""),
                delay_seconds=payload.get("delay_seconds"),
                scheduled_at_epoch=payload.get("scheduled_at_epoch"),
                cron=str(payload.get("cron") or ""),
                runnable_id=str(payload.get("runnable_id") or ""),
                runnable_name=str(payload.get("runnable_name") or ""),
            )
        if name == "future_task.list":
            return self.future_task_list(
                include_finished=bool(payload.get("include_finished", True)),
                limit=int(payload.get("limit") or 100),
            )
        if name == "future_task.cancel":
            return self.future_task_cancel(
                str(payload.get("future_task_id") or ""),
                reason=str(payload.get("reason") or ""),
            )
        if name == "workspace.list":
            return self.workspace_list(str(payload.get("path") or "."))
        if name == "workspace.read":
            return self.workspace_read(str(payload.get("path") or ""))
        if name == "workspace.write_patch":
            return self.workspace_write_patch(
                str(payload.get("path") or ""),
                str(payload.get("content") or ""),
                patch=str(payload.get("patch") or ""),
                expected_sha256=str(
                    payload.get("expected_sha256") or payload.get("base_sha256") or ""
                ),
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
            return self.artifact_write(
                str(payload.get("path") or ""),
                str(payload.get("content") or ""),
            )
        raise AgentRuntimeError(f"未知工具：{name}")
