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
    "screen.capture": "screen_capture",
    "desktop.permissions": "desktop_permissions",
    "desktop.active_window": "desktop_active_window",
    "desktop.running_apps": "desktop_running_apps",
    "desktop.windows": "desktop_windows",
    "app.status": "app_status",
    "app.open": "app_open",
    "app.focus": "app_focus",
    "app.focus_window": "app_focus_window",
    "app.open_and_safe_type_text": "app_open_and_safe_type_text",
    "app.focus_and_safe_type_text": "app_focus_and_safe_type_text",
    "app.open_and_safe_shortcut": "app_open_and_safe_shortcut",
    "app.focus_and_safe_shortcut": "app_focus_and_safe_shortcut",
    "app.show": "app_show",
    "app.hide": "app_hide",
    "app.minimize": "app_minimize",
    "app.quit": "app_quit",
    "desktop.reveal_path": "desktop_reveal_path",
    "desktop.open_path": "desktop_open_path",
    "media.apple_music_play": "media_apple_music_play",
    "media.apple_music_open_and_play": "media_apple_music_open_and_play",
    "media.apple_music_control": "media_apple_music_control",
    "system.volume": "system_volume",
    "clipboard.write": "clipboard_write",
    "desktop.safe_shortcut": "desktop_safe_shortcut",
    "desktop.safe_type_text": "desktop_safe_type_text",
    "desktop.safe_click": "desktop_safe_click",
    "desktop.hide_app": "desktop_hide_app",
    "desktop.minimize_window": "desktop_minimize_window",
    "desktop.close_window": "desktop_close_window",
    "desktop.hotkey": "desktop_hotkey",
    "desktop.type_text": "desktop_type_text",
    "desktop.click": "desktop_click",
    "browser.open_url": "browser_open_url",
    "browser.open_url_and_extract_text": "browser_open_url_and_extract_text",
    "browser.open_url_and_screenshot": "browser_open_url_and_screenshot",
    "browser.current_page": "browser_current_page",
    "browser.click": "browser_click",
    "browser.type_text": "browser_type_text",
    "browser.extract_text": "browser_extract_text",
    "browser.screenshot": "browser_screenshot",
}
TOOL_NAME_ALIASES = {value: key for key, value in TOOL_FUNCTION_NAMES.items()}
KNOWN_AGENT_TOOLS = set(TOOL_FUNCTION_NAMES)
HIGH_RISK_AGENT_TOOLS = {"terminal.run", "workspace.write_patch"}
MEMORY_TOOL_NAMES = ("memory.add", "memory.replace", "memory.remove")
FUTURE_TASK_TOOL_NAMES = ("future_task.schedule", "future_task.list", "future_task.cancel")
SAFE_SHORTCUT_ACTIONS = (
    "copy",
    "paste",
    "select_all",
    "undo",
    "redo",
    "find",
    "new_tab",
    "new_window",
    "refresh",
    "browser_back",
    "browser_forward",
)
LOW_RISK_DESKTOP_TOOL_NAMES = (
    "screen.capture",
    "desktop.permissions",
    "desktop.active_window",
    "desktop.running_apps",
    "desktop.windows",
    "app.status",
    "app.open",
    "app.focus",
    "app.focus_window",
    "app.open_and_safe_type_text",
    "app.focus_and_safe_type_text",
    "app.open_and_safe_shortcut",
    "app.focus_and_safe_shortcut",
    "app.show",
    "app.hide",
    "app.minimize",
    "desktop.reveal_path",
    "desktop.open_path",
    "media.apple_music_play",
    "media.apple_music_open_and_play",
    "media.apple_music_control",
    "system.volume",
    "clipboard.write",
    "desktop.safe_shortcut",
    "desktop.safe_type_text",
    "desktop.safe_click",
    "desktop.hide_app",
    "desktop.minimize_window",
)
MEDIUM_RISK_DESKTOP_TOOL_NAMES = (
    "app.quit",
    "desktop.close_window",
    "desktop.hotkey",
    "desktop.type_text",
    "desktop.click",
)
LOW_RISK_BROWSER_TOOL_NAMES = (
    "browser.open_url",
    "browser.open_url_and_extract_text",
    "browser.open_url_and_screenshot",
    "browser.current_page",
    "browser.extract_text",
    "browser.screenshot",
)
MEDIUM_RISK_BROWSER_TOOL_NAMES = ("browser.click", "browser.type_text")
DAILY_BROWSER_TOOL_NAMES = (*LOW_RISK_BROWSER_TOOL_NAMES, *MEDIUM_RISK_BROWSER_TOOL_NAMES)
DAILY_DESKTOP_TOOL_NAMES = (
    *LOW_RISK_DESKTOP_TOOL_NAMES,
    *MEDIUM_RISK_DESKTOP_TOOL_NAMES,
    *DAILY_BROWSER_TOOL_NAMES,
)


def _approval_required_agent_tools() -> tuple[str, ...]:
    return (
        *sorted(HIGH_RISK_AGENT_TOOLS),
        *MEDIUM_RISK_DESKTOP_TOOL_NAMES,
        *MEDIUM_RISK_BROWSER_TOOL_NAMES,
    )


def _redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


def _validate_percentage_number(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise AgentRuntimeError(f"{label} 必须是 0-100 的数字")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AgentRuntimeError(f"{label} 必须是 0-100 的数字") from exc
    if number < 0 or number > 100:
        raise AgentRuntimeError(f"{label} 必须是 0-100 的数字")


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
            if self.name in {"desktop.click", "desktop.safe_click"} and key in {"x", "y"}:
                if payload.get(key) in (None, ""):
                    raise AgentRuntimeError(f"{self.name} 参数 {key} 必须是非负坐标数字")
                continue
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
        if self.name == "desktop.reveal_path" and not str(payload.get("path") or "").strip():
            raise AgentRuntimeError("desktop.reveal_path 参数 path 必须是非空字符串")
        if self.name == "desktop.open_path" and not str(payload.get("path") or "").strip():
            raise AgentRuntimeError("desktop.open_path 参数 path 必须是非空字符串")
        if "timeout_seconds" in payload:
            value = payload.get("timeout_seconds")
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 120:
                raise AgentRuntimeError("terminal.run 参数 timeout_seconds 必须是 1-120 的整数")
        if "shell" in payload and not isinstance(payload.get("shell"), bool):
            raise AgentRuntimeError("terminal.run 参数 shell 必须是布尔值")
        if self.name == "desktop.windows" and "app_name" in payload:
            if not isinstance(payload.get("app_name"), str):
                raise AgentRuntimeError("desktop.windows 参数 app_name 必须是字符串")
        if self.name in {
            "app.open",
            "app.focus",
            "app.focus_window",
            "app.open_and_safe_type_text",
            "app.focus_and_safe_type_text",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "app.show",
            "app.hide",
            "app.minimize",
            "app.quit",
            "app.status",
        } and not str(payload.get("app_name") or "").strip():
            raise AgentRuntimeError(f"{self.name} 参数 app_name 必须是非空字符串")
        if self.name == "app.focus_window" and not str(payload.get("title_contains") or "").strip():
            raise AgentRuntimeError("app.focus_window 参数 title_contains 必须是非空字符串")
        if self.name == "media.apple_music_play" and not str(
            payload.get("query") or ""
        ).strip():
            raise AgentRuntimeError("media.apple_music_play 参数 query 必须是非空字符串")
        if self.name == "media.apple_music_control":
            action = str(payload.get("action") or "").strip()
            if action not in {"toggle", "play", "pause", "next", "previous"}:
                raise AgentRuntimeError(
                    "media.apple_music_control 参数 action 必须是 toggle、play、pause、next 或 previous"
                )
        if self.name == "system.volume":
            action = str(payload.get("action") or "").strip()
            if action not in {"status", "set", "up", "down", "mute", "unmute"}:
                raise AgentRuntimeError(
                    "system.volume 参数 action 必须是 status、set、up、down、mute 或 unmute"
                )
            level = payload.get("level")
            if action == "set":
                if level in (None, ""):
                    raise AgentRuntimeError("system.volume 参数 level 必须是 0-100 的数字")
                _validate_percentage_number(level, "system.volume 参数 level")
            elif level not in (None, ""):
                _validate_percentage_number(level, "system.volume 参数 level")
            step = payload.get("step")
            if step not in (None, ""):
                _validate_percentage_number(step, "system.volume 参数 step")
        if self.name == "clipboard.write" and not str(payload.get("text") or "").strip():
            raise AgentRuntimeError("clipboard.write 参数 text 必须是非空字符串")
        if self.name == "desktop.safe_shortcut":
            action = str(payload.get("action") or "").strip().lower()
            if action not in SAFE_SHORTCUT_ACTIONS:
                raise AgentRuntimeError(
                    "desktop.safe_shortcut 参数 action 必须是 "
                    + "、".join(SAFE_SHORTCUT_ACTIONS)
                )
        if self.name == "desktop.safe_type_text" and not str(
            payload.get("text") or ""
        ).strip():
            raise AgentRuntimeError("desktop.safe_type_text 参数 text 必须是非空字符串")
        if self.name in {"app.open_and_safe_type_text", "app.focus_and_safe_type_text"} and not str(
            payload.get("text") or ""
        ).strip():
            raise AgentRuntimeError(f"{self.name} 参数 text 必须是非空字符串")
        if self.name in {"app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"}:
            action = str(payload.get("action") or "").strip().lower()
            if action not in SAFE_SHORTCUT_ACTIONS:
                raise AgentRuntimeError(
                    f"{self.name} 参数 action 必须是 " + "、".join(SAFE_SHORTCUT_ACTIONS)
                )
        if self.name == "desktop.type_text" and not str(payload.get("text") or "").strip():
            raise AgentRuntimeError("desktop.type_text 参数 text 必须是非空字符串")
        if self.name == "desktop.safe_click":
            for key in ("x", "y"):
                value = payload.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                    raise AgentRuntimeError(f"desktop.safe_click 参数 {key} 必须是非负坐标数字")
                try:
                    coordinate = float(value)
                except (TypeError, ValueError) as exc:
                    raise AgentRuntimeError(
                        f"desktop.safe_click 参数 {key} 必须是非负坐标数字"
                    ) from exc
                if coordinate < 0 or coordinate > 100000:
                    raise AgentRuntimeError(f"desktop.safe_click 参数 {key} 必须是非负坐标数字")
        if self.name == "desktop.click":
            for key in ("x", "y"):
                value = payload.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                    raise AgentRuntimeError(f"desktop.click 参数 {key} 必须是非负坐标数字")
                try:
                    coordinate = float(value)
                except (TypeError, ValueError) as exc:
                    raise AgentRuntimeError(
                        f"desktop.click 参数 {key} 必须是非负坐标数字"
                    ) from exc
                if coordinate < 0 or coordinate > 100000:
                    raise AgentRuntimeError(f"desktop.click 参数 {key} 必须是非负坐标数字")
            click_count = payload.get("click_count", 1)
            if click_count not in (None, ""):
                if isinstance(click_count, bool) or not isinstance(click_count, int):
                    raise AgentRuntimeError("desktop.click 参数 click_count 必须是 1-3 的整数")
                if click_count < 1 or click_count > 3:
                    raise AgentRuntimeError("desktop.click 参数 click_count 必须是 1-3 的整数")
        if self.name == "desktop.hotkey":
            if not str(payload.get("key") or "").strip():
                raise AgentRuntimeError("desktop.hotkey 参数 key 必须是非空字符串")
            modifiers = payload.get("modifiers", [])
            if modifiers not in (None, "") and not isinstance(modifiers, list):
                raise AgentRuntimeError("desktop.hotkey 参数 modifiers 必须是字符串数组")
            allowed_modifiers = {"command", "cmd", "shift", "option", "alt", "control", "ctrl"}
            for modifier in modifiers or []:
                if str(modifier or "").strip().lower() not in allowed_modifiers:
                    raise AgentRuntimeError(
                        "desktop.hotkey 参数 modifiers 只能包含 command/cmd、shift、"
                        "option/alt、control/ctrl"
                    )
        if self.name in {
            "browser.open_url",
            "browser.open_url_and_extract_text",
            "browser.open_url_and_screenshot",
        }:
            value = str(payload.get("url") or "").strip()
            if not value:
                raise AgentRuntimeError(f"{self.name} 参数 url 必须是非空字符串")
            if not re.match(r"^https?://[^\s]+$", value):
                raise AgentRuntimeError(f"{self.name} 参数 url 必须是绝对 http(s) URL")
        if self.name in {"browser.click", "browser.type_text"} and not str(
            payload.get("selector") or ""
        ).strip():
            raise AgentRuntimeError(f"{self.name} 参数 selector 必须是非空字符串")
        if self.name == "browser.click":
            for key in ("fallback_x", "fallback_y"):
                if key not in payload or payload.get(key) in (None, ""):
                    continue
                value = payload.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                    raise AgentRuntimeError(f"browser.click 参数 {key} 必须是非负坐标数字")
                try:
                    coordinate = float(value)
                except (TypeError, ValueError) as exc:
                    raise AgentRuntimeError(
                        f"browser.click 参数 {key} 必须是非负坐标数字"
                    ) from exc
                if coordinate < 0 or coordinate > 100000:
                    raise AgentRuntimeError(f"browser.click 参数 {key} 必须是非负坐标数字")
            click_count = payload.get("click_count", 1)
            if click_count not in (None, ""):
                if isinstance(click_count, bool) or not isinstance(click_count, int):
                    raise AgentRuntimeError("browser.click 参数 click_count 必须是 1-3 的整数")
                if click_count < 1 or click_count > 3:
                    raise AgentRuntimeError("browser.click 参数 click_count 必须是 1-3 的整数")
        if self.name == "browser.type_text" and not str(payload.get("text") or "").strip():
            raise AgentRuntimeError("browser.type_text 参数 text 必须是非空字符串")
        if self.name in {
            "browser.extract_text",
            "browser.screenshot",
            "browser.open_url_and_extract_text",
            "browser.open_url_and_screenshot",
        }:
            for key in ("selector", "reason"):
                if key in payload and not isinstance(payload.get(key), str):
                    raise AgentRuntimeError(f"{self.name} 参数 {key} 必须是字符串")
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
    "screen.capture": ToolDescriptor(
        name="screen.capture",
        description=(
            "Capture the current desktop screen and save it as a run artifact. "
            "Low-risk, observable desktop read action."
        ),
        properties={
            "reason": {
                "type": "string",
                "description": "Optional short reason shown in the Run Timeline.",
            }
        },
    ),
    "desktop.permissions": ToolDescriptor(
        name="desktop.permissions",
        description=(
            "Read desktop execution permission readiness, missing permission targets, "
            "and affected tools. Low-risk diagnostic state."
        ),
        properties={},
    ),
    "desktop.active_window": ToolDescriptor(
        name="desktop.active_window",
        description="Read the current foreground app and window title.",
        properties={},
    ),
    "desktop.running_apps": ToolDescriptor(
        name="desktop.running_apps",
        description=(
            "Read the list of currently running foreground desktop applications. "
            "Low-risk, observable desktop state."
        ),
        properties={},
    ),
    "desktop.windows": ToolDescriptor(
        name="desktop.windows",
        description=(
            "Read open desktop window titles, optionally filtered to one app. "
            "Low-risk, observable desktop state."
        ),
        properties={
            "app_name": {
                "type": "string",
                "description": "Optional application name to filter windows.",
            }
        },
    ),
    "app.status": ToolDescriptor(
        name="app.status",
        description="Check whether a local desktop application is currently running.",
        properties={"app_name": {"type": "string", "description": "Application name."}},
        required=("app_name",),
    ),
    "app.open": ToolDescriptor(
        name="app.open",
        description="Open a local desktop application by display name.",
        properties={"app_name": {"type": "string", "description": "Application name."}},
        required=("app_name",),
    ),
    "app.focus": ToolDescriptor(
        name="app.focus",
        description="Bring a local desktop application to the foreground.",
        properties={"app_name": {"type": "string", "description": "Application name."}},
        required=("app_name",),
    ),
    "app.focus_window": ToolDescriptor(
        name="app.focus_window",
        description="Bring a matching window of a local desktop application to the foreground.",
        properties={
            "app_name": {"type": "string", "description": "Application name."},
            "title_contains": {
                "type": "string",
                "description": "Case-insensitive window title substring to focus.",
            },
        },
        required=("app_name", "title_contains"),
    ),
    "app.open_and_safe_type_text": ToolDescriptor(
        name="app.open_and_safe_type_text",
        description=(
            "Open and focus a local desktop application, then type text explicitly provided "
            "by the user into the foreground app while holding the foreground action lock."
        ),
        properties={
            "app_name": {"type": "string", "description": "Application name."},
            "text": {"type": "string", "description": "User-provided text to type."},
        },
        required=("app_name", "text"),
    ),
    "app.focus_and_safe_type_text": ToolDescriptor(
        name="app.focus_and_safe_type_text",
        description=(
            "Focus a local desktop application, then type text explicitly provided by the user "
            "into the foreground app while holding the foreground action lock."
        ),
        properties={
            "app_name": {"type": "string", "description": "Application name."},
            "text": {"type": "string", "description": "User-provided text to type."},
        },
        required=("app_name", "text"),
    ),
    "app.open_and_safe_shortcut": ToolDescriptor(
        name="app.open_and_safe_shortcut",
        description=(
            "Open and focus a local desktop application, then execute a whitelisted safe "
            "foreground shortcut while holding the foreground action lock."
        ),
        properties={
            "app_name": {"type": "string", "description": "Application name."},
            "action": {
                "type": "string",
                "enum": list(SAFE_SHORTCUT_ACTIONS),
                "description": "Whitelisted shortcut action to execute.",
            },
        },
        required=("app_name", "action"),
    ),
    "app.focus_and_safe_shortcut": ToolDescriptor(
        name="app.focus_and_safe_shortcut",
        description=(
            "Focus a local desktop application, then execute a whitelisted safe foreground "
            "shortcut while holding the foreground action lock."
        ),
        properties={
            "app_name": {"type": "string", "description": "Application name."},
            "action": {
                "type": "string",
                "enum": list(SAFE_SHORTCUT_ACTIONS),
                "description": "Whitelisted shortcut action to execute.",
            },
        },
        required=("app_name", "action"),
    ),
    "app.show": ToolDescriptor(
        name="app.show",
        description=(
            "Show, unhide, restore minimized windows, and activate a local desktop application."
        ),
        properties={"app_name": {"type": "string", "description": "Application name."}},
        required=("app_name",),
    ),
    "app.hide": ToolDescriptor(
        name="app.hide",
        description="Hide a running local desktop application by display name without quitting it.",
        properties={"app_name": {"type": "string", "description": "Application name."}},
        required=("app_name",),
    ),
    "app.minimize": ToolDescriptor(
        name="app.minimize",
        description="Minimize windows for a running local desktop application without quitting it.",
        properties={"app_name": {"type": "string", "description": "Application name."}},
        required=("app_name",),
    ),
    "app.quit": ToolDescriptor(
        name="app.quit",
        description=(
            "Quit a local desktop application by display name. Requires approval because "
            "unsaved work in that application may be lost."
        ),
        properties={"app_name": {"type": "string", "description": "Application name."}},
        required=("app_name",),
    ),
    "desktop.reveal_path": ToolDescriptor(
        name="desktop.reveal_path",
        description=(
            "Reveal a local file or folder in Finder without opening or executing it. "
            "Use this for low-risk 'show in Finder' requests."
        ),
        properties={
            "path": {
                "type": "string",
                "description": "Absolute, relative, or ~/ local filesystem path to reveal in Finder.",
            }
        },
        required=("path",),
    ),
    "desktop.open_path": ToolDescriptor(
        name="desktop.open_path",
        description=(
            "Open a local folder or a safe document/media file with the system default app. "
            "Reject executable, app bundle, script, or unknown file types instead of opening them."
        ),
        properties={
            "path": {
                "type": "string",
                "description": "Absolute, relative, or ~/ local filesystem path to open.",
            }
        },
        required=("path",),
    ),
    "media.apple_music_play": ToolDescriptor(
        name="media.apple_music_play",
        description=(
            "Search the local Apple Music library and start playback. "
            "If direct playback fails, open Music as a fallback."
        ),
        properties={"query": {"type": "string", "description": "Song, album, or artist query."}},
        required=("query",),
    ),
    "media.apple_music_open_and_play": ToolDescriptor(
        name="media.apple_music_open_and_play",
        description=(
            "Open Apple Music and start or resume playback for explicit low-risk daily commands."
        ),
        properties={},
        required=(),
    ),
    "media.apple_music_control": ToolDescriptor(
        name="media.apple_music_control",
        description=(
            "Control Apple Music playback for low-risk daily commands: play, pause, "
            "toggle play/pause, next track, or previous track."
        ),
        properties={
            "action": {
                "type": "string",
                "enum": ["toggle", "play", "pause", "next", "previous"],
                "description": "Playback control action.",
            }
        },
        required=("action",),
    ),
    "system.volume": ToolDescriptor(
        name="system.volume",
        description=(
            "Read or adjust the macOS output volume for low-risk daily desktop commands. "
            "Use status for read-only volume questions, set for an exact 0-100 level, "
            "up/down for small relative changes, and mute/unmute for output mute state."
        ),
        properties={
            "action": {
                "type": "string",
                "enum": ["status", "set", "up", "down", "mute", "unmute"],
                "description": "Volume action.",
            },
            "level": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "description": "Exact output volume level for action=set.",
            },
            "step": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "description": "Optional relative step for up/down. Defaults to 10.",
            },
        },
        required=("action",),
    ),
    "clipboard.write": ToolDescriptor(
        name="clipboard.write",
        description=(
            "Write explicit user-provided text to the system clipboard. "
            "Do not use this to read clipboard contents."
        ),
        properties={
            "text": {
                "type": "string",
                "description": "Text to write to the system clipboard.",
            }
        },
        required=("text",),
    ),
    "desktop.hide_app": ToolDescriptor(
        name="desktop.hide_app",
        description=(
            "Hide the current foreground app using the standard system shortcut. "
            "Low-risk and reversible, but still recorded in the Run Timeline."
        ),
        properties={},
    ),
    "desktop.safe_shortcut": ToolDescriptor(
        name="desktop.safe_shortcut",
        description=(
            "Execute a whitelisted common foreground shortcut such as copy, paste, "
            "select all, undo, redo, find, new tab, new window, refresh, browser back, or "
            "browser forward. Unlike desktop.hotkey, this tool does not accept arbitrary keys."
        ),
        properties={
            "action": {
                "type": "string",
                "enum": list(SAFE_SHORTCUT_ACTIONS),
                "description": "Whitelisted shortcut action to execute.",
            }
        },
        required=("action",),
    ),
    "desktop.safe_type_text": ToolDescriptor(
        name="desktop.safe_type_text",
        description=(
            "Type text that the user explicitly provided in the current daily desktop request "
            "into the foreground app. This is a low-risk direct-action path for Chat/Bubble/Live2D; "
            "use desktop.type_text for model-selected or multi-step typing."
        ),
        properties={"text": {"type": "string", "description": "User-provided text to type."}},
        required=("text",),
    ),
    "desktop.minimize_window": ToolDescriptor(
        name="desktop.minimize_window",
        description=(
            "Minimize the current foreground window using the standard system shortcut. "
            "Low-risk and reversible, but still recorded in the Run Timeline."
        ),
        properties={},
    ),
    "desktop.close_window": ToolDescriptor(
        name="desktop.close_window",
        description=(
            "Close the current foreground window using the standard system shortcut. "
            "Requires approval because unsaved work in that window may be affected."
        ),
        properties={},
    ),
    "desktop.hotkey": ToolDescriptor(
        name="desktop.hotkey",
        description="Send a keyboard shortcut to the current foreground app.",
        properties={
            "key": {"type": "string", "description": "Key to press."},
            "modifiers": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["command", "cmd", "shift", "option", "alt", "control", "ctrl"],
                },
                "description": "Optional modifier keys.",
            },
        },
        required=("key",),
    ),
    "desktop.type_text": ToolDescriptor(
        name="desktop.type_text",
        description="Type text into the current foreground app.",
        properties={"text": {"type": "string", "description": "Text to type."}},
        required=("text",),
    ),
    "desktop.safe_click": ToolDescriptor(
        name="desktop.safe_click",
        description=(
            "Single-click an explicit screen coordinate that the user provided in the current "
            "daily desktop request. Use desktop.click for double-clicks, repeated clicks, "
            "or coordinates selected by the model after screen observation."
        ),
        properties={
            "x": {
                "type": "number",
                "minimum": 0,
                "description": "User-provided screen x coordinate in pixels.",
            },
            "y": {
                "type": "number",
                "minimum": 0,
                "description": "User-provided screen y coordinate in pixels.",
            },
        },
        required=("x", "y"),
    ),
    "desktop.click": ToolDescriptor(
        name="desktop.click",
        description=(
            "Click a screen coordinate in the current foreground desktop session. "
            "Use after observing the screen; this is a medium-risk foreground input action."
        ),
        properties={
            "x": {
                "type": "number",
                "minimum": 0,
                "description": "Screen x coordinate in pixels.",
            },
            "y": {
                "type": "number",
                "minimum": 0,
                "description": "Screen y coordinate in pixels.",
            },
            "click_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
                "description": "Optional click count. Defaults to 1.",
            },
        },
        required=("x", "y"),
    ),
    "browser.open_url": ToolDescriptor(
        name="browser.open_url",
        description=(
            "Open an absolute http(s) URL in a CDP-controlled browser tab. "
            "Falls back to the system browser when Chrome CDP is unavailable."
        ),
        properties={"url": {"type": "string", "description": "Absolute http(s) URL."}},
        required=("url",),
    ),
    "browser.open_url_and_extract_text": ToolDescriptor(
        name="browser.open_url_and_extract_text",
        description=(
            "Open an absolute http(s) URL, then extract visible text from that browser page. "
            "Opening may fall back to the system browser; text extraction requires Chrome CDP."
        ),
        properties={
            "url": {"type": "string", "description": "Absolute http(s) URL."},
            "selector": {
                "type": "string",
                "description": "Optional CSS selector. Defaults to document.body.",
            },
        },
        required=("url",),
    ),
    "browser.open_url_and_screenshot": ToolDescriptor(
        name="browser.open_url_and_screenshot",
        description=(
            "Open an absolute http(s) URL, then capture the resulting browser page as a run artifact."
        ),
        properties={
            "url": {"type": "string", "description": "Absolute http(s) URL."},
            "reason": {
                "type": "string",
                "description": "Optional short reason shown in the Run Timeline.",
            },
        },
        required=("url",),
    ),
    "browser.current_page": ToolDescriptor(
        name="browser.current_page",
        description="Read the current CDP browser page title and URL.",
        properties={},
    ),
    "browser.click": ToolDescriptor(
        name="browser.click",
        description=(
            "Click an element in the current browser page by CSS selector or text=<label>. "
            "If Chrome CDP is unavailable, provide fallback_x and fallback_y after observing "
            "the screen so the tool can safely fall back to foreground desktop clicking."
        ),
        properties={
            "selector": {"type": "string", "description": "CSS selector or text=<label> target to click."},
            "fallback_x": {
                "type": "number",
                "minimum": 0,
                "description": "Optional screen x coordinate for no-CDP foreground fallback.",
            },
            "fallback_y": {
                "type": "number",
                "minimum": 0,
                "description": "Optional screen y coordinate for no-CDP foreground fallback.",
            },
            "click_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
                "description": "Optional foreground fallback click count. Defaults to 1.",
            },
        },
        required=("selector",),
    ),
    "browser.type_text": ToolDescriptor(
        name="browser.type_text",
        description="Set text into an input-like element in the current browser page.",
        properties={
            "selector": {"type": "string", "description": "CSS selector to focus and edit."},
            "text": {"type": "string", "description": "Text to enter."},
        },
        required=("selector", "text"),
    ),
    "browser.extract_text": ToolDescriptor(
        name="browser.extract_text",
        description="Extract visible text from the current browser page or a CSS selector.",
        properties={
            "selector": {
                "type": "string",
                "description": "Optional CSS selector. Defaults to document.body.",
            }
        },
    ),
    "browser.screenshot": ToolDescriptor(
        name="browser.screenshot",
        description="Capture the current browser page as a run artifact.",
        properties={
            "reason": {
                "type": "string",
                "description": "Optional short reason shown in the Run Timeline.",
            }
        },
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


class RuntimePolicyCompiler:
    """Compiles persisted Agent policies into runtime-safe execution policy snapshots."""

    @staticmethod
    def default_tool_policy(category: str = "custom") -> dict[str, Any]:
        memory_tools = list(MEMORY_TOOL_NAMES)
        future_task_tools = list(FUTURE_TASK_TOOL_NAMES)
        daily_tools = list(DAILY_DESKTOP_TOOL_NAMES)
        tools = [*daily_tools, *memory_tools, *future_task_tools, "artifact.write"]
        if category in {"coding", "review"}:
            tools = [
                "workspace.list",
                "workspace.read",
                "workspace.write_patch",
                "terminal.run",
                *memory_tools,
                *future_task_tools,
                "artifact.write",
            ]
        elif category in {"research", "design", "office", "orchestrator"}:
            tools = [
                "workspace.list",
                "workspace.read",
                *daily_tools,
                *memory_tools,
                *future_task_tools,
                "artifact.write",
            ]
        return {
            "allowed_tools": tools,
            "approval_required": {
                tool: True for tool in _approval_required_agent_tools()
            },
        }

    @staticmethod
    def default_workspace_policy() -> dict[str, Any]:
        return {"default_workdir": "", "readable_scopes": ["."], "writable_scopes": []}

    def compile_tool_policy(self, category: str, policy: Any = None) -> dict[str, Any]:
        raw = policy if isinstance(policy, dict) else {}
        default_policy = self.default_tool_policy(category)
        allowed = raw.get("allowed_tools")
        if isinstance(allowed, str):
            allowed = [allowed]
        if not isinstance(allowed, list):
            allowed = default_policy["allowed_tools"]
        normalized_allowed = []
        for tool in allowed:
            name = str(tool or "").strip()
            if name in KNOWN_AGENT_TOOLS and name not in normalized_allowed:
                normalized_allowed.append(name)

        raw_approval = raw.get("approval_required")
        approval_required = dict(raw_approval) if isinstance(raw_approval, dict) else {}
        for tool in _approval_required_agent_tools():
            if tool in normalized_allowed:
                approval_required[tool] = True
            else:
                approval_required.pop(tool, None)
        return {"allowed_tools": normalized_allowed, "approval_required": approval_required}

    def compile_workspace_policy(self, policy: Any = None) -> dict[str, Any]:
        raw = policy if isinstance(policy, dict) else {}
        default_policy = self.default_workspace_policy()
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
            "writable_scopes": [
                str(item or "").strip()
                for item in writable
                if str(item or "").strip()
            ],
        }

    def compile_agent_runtime(self, agent: dict[str, Any]) -> dict[str, Any]:
        category = str(agent.get("category") or "custom")
        tool_policy = self.compile_tool_policy(category, agent.get("tool_policy"))
        if agent.get("skill_ids") and "skill.read" not in tool_policy["allowed_tools"]:
            tool_policy = {
                **tool_policy,
                "allowed_tools": ["skill.read", *tool_policy["allowed_tools"]],
            }
        workspace_policy = self.compile_workspace_policy(agent.get("workspace_policy"))
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
