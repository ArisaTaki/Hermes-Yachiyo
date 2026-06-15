"""Tool descriptors, schema generation, and policy gates."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from packages.security import redact_sensitive_text

MEMORY_SCOPES = {"global", "project", "session"}
MEMORY_KINDS = {"preference", "fact", "task", "summary"}
TOOL_FUNCTION_NAMES = {
    "skill.read": "skill_read",
    "memory.add": "memory_add",
    "memory.replace": "memory_replace",
    "memory.remove": "memory_remove",
    "future_task.schedule": "future_task_schedule",
    "future_task.list": "future_task_list",
    "future_task.cancel": "future_task_cancel",
    "workspace.list": "workspace_list",
    "workspace.read": "workspace_read",
    "workspace.write_patch": "workspace_write_patch",
    "terminal.run": "terminal_run",
    "artifact.write": "artifact_write",
}
TOOL_NAME_ALIASES = {value: key for key, value in TOOL_FUNCTION_NAMES.items()}


def _redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    properties: dict[str, Any]
    required: tuple[str, ...] = ()

    @property
    def function_name(self) -> str:
        return TOOL_FUNCTION_NAMES[self.name]

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
                    "properties": deepcopy(self.properties),
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
            patch_supplied = (
                isinstance(payload.get("patch"), str)
                and str(payload.get("patch") or "").strip()
            )
            if not patch_supplied:
                raise AgentRuntimeError("workspace.write_patch 参数 patch 必须是非空字符串")
            hash_values = {
                key: str(payload.get(key) or "").strip()
                for key in ("expected_sha256", "base_sha256")
                if key in payload
            }
            for key, value in hash_values.items():
                if value and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                    raise AgentRuntimeError(
                        f"workspace.write_patch 参数 {key} 必须是 64 位 SHA-256 hex"
                    )
            if hash_values.get("expected_sha256") and hash_values.get("base_sha256"):
                if hash_values["expected_sha256"].lower() != hash_values["base_sha256"].lower():
                    raise AgentRuntimeError(
                        "workspace.write_patch 参数 expected_sha256 与 base_sha256 不一致"
                    )
        if self.name == "skill.read":
            value = str(payload.get("skill_id") or payload.get("name") or "").strip()
            if not value:
                raise AgentRuntimeError("skill.read 参数 skill_id 或 name 必须是非空字符串")
        if self.name.startswith("memory."):
            for key in ("memory_id", "content", "old_content", "kind", "scope", "reason"):
                if key in payload and not isinstance(payload.get(key), str):
                    raise AgentRuntimeError(f"{self.name} 参数 {key} 必须是字符串")
            scope = str(payload.get("scope") or "").strip().lower()
            if scope and scope not in MEMORY_SCOPES:
                raise AgentRuntimeError(f"{self.name} 参数 scope 必须是 global、project 或 session")
            kind = str(payload.get("kind") or "").strip().lower()
            if kind and kind not in MEMORY_KINDS:
                raise AgentRuntimeError(
                    f"{self.name} 参数 kind 必须是 preference、fact、task 或 summary"
                )
            if self.name == "memory.replace":
                if not str(payload.get("content") or "").strip():
                    raise AgentRuntimeError("memory.replace 参数 content 必须是非空字符串")
                if not str(payload.get("memory_id") or payload.get("old_content") or "").strip():
                    raise AgentRuntimeError(
                        "memory.replace 参数 memory_id 或 old_content 必须是非空字符串"
                    )
            if (
                self.name == "memory.remove"
                and not str(payload.get("memory_id") or payload.get("content") or "").strip()
            ):
                raise AgentRuntimeError("memory.remove 参数 memory_id 或 content 必须是非空字符串")
        if self.name.startswith("future_task."):
            for key in (
                "future_task_id",
                "title",
                "prompt",
                "runnable_id",
                "runnable_name",
                "cron",
                "reason",
            ):
                if key in payload and not isinstance(payload.get(key), str):
                    raise AgentRuntimeError(f"{self.name} 参数 {key} 必须是字符串")
            for key in ("delay_seconds", "scheduled_at_epoch"):
                if key in payload and payload.get(key) not in (None, ""):
                    value = payload.get(key)
                    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                        raise AgentRuntimeError(f"{self.name} 参数 {key} 必须是数字")
                    try:
                        float(value)
                    except (TypeError, ValueError) as exc:
                        raise AgentRuntimeError(f"{self.name} 参数 {key} 必须是数字") from exc
            if self.name == "future_task.schedule" and not str(payload.get("prompt") or "").strip():
                raise AgentRuntimeError("future_task.schedule 参数 prompt 必须是非空字符串")
            if (
                self.name == "future_task.cancel"
                and not str(payload.get("future_task_id") or "").strip()
            ):
                raise AgentRuntimeError("future_task.cancel 参数 future_task_id 必须是非空字符串")
        if "path" in payload and not isinstance(payload.get("path"), str):
            raise AgentRuntimeError(f"{self.name} 参数 path 必须是字符串")
        if "timeout_seconds" in payload:
            value = payload.get("timeout_seconds")
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 120:
                raise AgentRuntimeError("terminal.run 参数 timeout_seconds 必须是 1-120 的整数")
        if "shell" in payload and not isinstance(payload.get("shell"), bool):
            raise AgentRuntimeError("terminal.run 参数 shell 必须是布尔值")
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if _redact_secrets(serialized) != serialized:
            raise AgentRuntimeError(f"{self.name} 参数包含敏感凭据，已拒绝执行和持久化")


TOOL_DESCRIPTORS: dict[str, ToolDescriptor] = {
    "skill.read": ToolDescriptor(
        name="skill.read",
        description=(
            "Read the full SKILL.md instructions for a mounted Agent Skill. "
            "Use this only after the skill summary index looks relevant to the task."
        ),
        properties={
            "skill_id": {
                "type": "string",
                "description": "Mounted skill id from the Skill summary index.",
            },
            "name": {
                "type": "string",
                "description": "Optional mounted skill name if skill_id is unavailable.",
            },
        },
    ),
    "memory.add": ToolDescriptor(
        name="memory.add",
        description=(
            "Persist a stable user preference, durable fact, task commitment, or reusable summary "
            "for future Agent sessions. Never store secrets or one-off transient details."
        ),
        properties={
            "content": {"type": "string", "description": "Concise memory content to preserve."},
            "kind": {
                "type": "string",
                "enum": ["preference", "fact", "task", "summary"],
                "description": "Memory category. Defaults to fact.",
            },
            "scope": {
                "type": "string",
                "enum": ["global", "project", "session"],
                "description": "Recall scope. Defaults to global.",
            },
        },
        required=("content",),
    ),
    "memory.replace": ToolDescriptor(
        name="memory.replace",
        description=(
            "Replace an existing durable memory by memory_id or exact old_content when the user "
            "corrects it."
        ),
        properties={
            "memory_id": {
                "type": "string",
                "description": "Existing memory id from Long-term Memory context.",
            },
            "old_content": {
                "type": "string",
                "description": "Exact old memory content if memory_id is unavailable.",
            },
            "content": {"type": "string", "description": "Replacement memory content."},
            "kind": {
                "type": "string",
                "enum": ["preference", "fact", "task", "summary"],
                "description": "Optional replacement category.",
            },
            "scope": {
                "type": "string",
                "enum": ["global", "project", "session"],
                "description": "Optional replacement recall scope.",
            },
        },
        required=("content",),
    ),
    "memory.remove": ToolDescriptor(
        name="memory.remove",
        description=(
            "Soft-delete an existing durable memory by memory_id or exact content when the user "
            "asks to forget it."
        ),
        properties={
            "memory_id": {
                "type": "string",
                "description": "Existing memory id from Long-term Memory context.",
            },
            "content": {
                "type": "string",
                "description": "Exact memory content if memory_id is unavailable.",
            },
            "reason": {"type": "string", "description": "Optional short reason for the audit log."},
        },
    ),
    "future_task.schedule": ToolDescriptor(
        name="future_task.schedule",
        description=(
            "Schedule a durable FutureTask self-wakeup for this Agent or another runnable. "
            "Use for reminders, standing orders, periodic summaries, and follow-up commitments."
        ),
        properties={
            "title": {"type": "string", "description": "Short user-facing FutureTask title."},
            "prompt": {
                "type": "string",
                "description": "Goal to execute when the FutureTask wakes up.",
            },
            "delay_seconds": {
                "type": "number",
                "description": "Optional delay from now in seconds.",
            },
            "scheduled_at_epoch": {
                "type": "number",
                "description": "Optional Unix epoch seconds for the wakeup.",
            },
            "cron": {
                "type": "string",
                "description": (
                    "Optional repeat schedule: @hourly, @daily, @weekly, "
                    "or every N minutes/hours/days."
                ),
            },
            "runnable_id": {
                "type": "string",
                "description": "Optional target Agent/Workflow id. Defaults to current Agent.",
            },
            "runnable_name": {
                "type": "string",
                "description": "Optional target Agent/Workflow name.",
            },
        },
        required=("prompt",),
    ),
    "future_task.list": ToolDescriptor(
        name="future_task.list",
        description=(
            "List durable FutureTasks visible to the Agent, including scheduled "
            "and recently finished entries."
        ),
        properties={
            "include_finished": {
                "type": "boolean",
                "description": "Include triggered/cancelled/failed tasks. Defaults true.",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    ),
    "future_task.cancel": ToolDescriptor(
        name="future_task.cancel",
        description="Cancel a scheduled FutureTask by id.",
        properties={
            "future_task_id": {"type": "string", "description": "FutureTask id to cancel."},
            "reason": {"type": "string", "description": "Optional short reason for the audit log."},
        },
        required=("future_task_id",),
    ),
    "workspace.list": ToolDescriptor(
        name="workspace.list",
        description=(
            "List entries in an allowed workspace directory. Use this before workspace.read "
            "when you only know a directory path."
        ),
        properties={"path": {"type": "string", "description": "Relative directory path."}},
    ),
    "workspace.read": ToolDescriptor(
        name="workspace.read",
        description=(
            "Read a UTF-8 text file from the allowed workspace. This only accepts file paths; "
            "use workspace.list for directories."
        ),
        properties={"path": {"type": "string", "description": "Relative file path."}},
        required=("path",),
    ),
    "workspace.write_patch": ToolDescriptor(
        name="workspace.write_patch",
        description=(
            "Apply a single-file UTF-8 unified diff to an allowed workspace path. "
            "Requires user approval."
        ),
        properties={
            "path": {"type": "string", "description": "Relative file path inside writable scopes."},
            "patch": {
                "type": "string",
                "description": "Single-file unified diff whose file headers match path.",
            },
            "expected_sha256": {
                "type": "string",
                "description": (
                    "Optional current file SHA-256 precondition checked immediately before writing."
                ),
            },
            "base_sha256": {"type": "string", "description": "Alias for expected_sha256."},
        },
        required=("path",),
    ),
    "terminal.run": ToolDescriptor(
        name="terminal.run",
        description=(
            "Run an argv command in the Agent workdir. Requires user approval. "
            "Shell mode is disabled unless explicitly requested and approved."
        ),
        properties={
            "command": {"type": "string", "description": "Command parsed into argv by default."},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
            "shell": {
                "type": "boolean",
                "description": (
                    "Explicitly request shell parsing; the full command is shown for approval."
                ),
            },
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
