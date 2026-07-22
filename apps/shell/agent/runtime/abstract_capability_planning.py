"""Compile narrow model-proposed capability actions into Runtime plans.

The proposal surface is intentionally semantic.  It contains no concrete
tool, generated identifier, policy, approval, fallback, target-authority, or
completion-evidence field.  Every accepted ``(capability_id, action_id)`` pair
has a checked-in compiler that parses its own user-grounded input slots; the
Runtime then chooses adapters and finalizes the ordinary planner snapshots.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, get_args
from urllib.parse import urlparse

from apps.shell.agent.runtime.tool_candidate_selection import (
    ToolCandidateSelection,
    select_trusted_tool_candidate,
)
from apps.shell.agent.runtime.tool_capabilities import (
    action_ids_for_tool,
    registered_tool_names_for_capability,
)
from apps.shell.agent.tools.policy import TOOL_DESCRIPTORS
from apps.shell.yachiyo_agent.capability_registry import capability_definition_map
from apps.shell.yachiyo_agent.contracts import (
    PlannerDecisionSnapshot,
    TaskIntentKind,
    TaskIntentSnapshot,
    ToolPlanStepSnapshot,
)
from apps.shell.yachiyo_agent.planner_primitives import stable_planner_id
from apps.shell.yachiyo_agent.policy import desktop_tool_execution_mode_for_input
from apps.shell.yachiyo_agent.runtime_planner import (
    RuntimePlanner,
    _model_intent_action_evidence_is_grounded,
    _speech_act_action_occurrence_is_authorized,
    clarification_authority_for_goal,
)

ABSTRACT_CAPABILITY_MAX_SUBGOALS = 8
ABSTRACT_CAPABILITY_MAX_INPUT_SLOTS = 8
ABSTRACT_CAPABILITY_TEXT_MAX_CHARS = 2000
ABSTRACT_CAPABILITY_EVIDENCE_MAX_CHARS = 500

_KNOWN_INTENT_KINDS = frozenset(str(value) for value in get_args(TaskIntentKind))


class AbstractCapabilityPlanningError(ValueError):
    """An abstract proposal could not be promoted into Runtime authority."""


@dataclass(frozen=True, slots=True)
class AbstractCapabilityInputSlotProposal:
    slot: str
    value: str
    evidence_quote: str


@dataclass(frozen=True, slots=True)
class AbstractCapabilitySubgoalProposal:
    capability_id: str
    action_id: str
    planning_goal: str
    action_evidence: str
    input_slots: tuple[AbstractCapabilityInputSlotProposal, ...] = ()


@dataclass(frozen=True, slots=True)
class AbstractCapabilityPlanProposal:
    intent_kind: str
    planning_goal: str
    subgoals: tuple[AbstractCapabilitySubgoalProposal, ...]


@dataclass(frozen=True, slots=True)
class _CompiledSupportStep:
    capability_id: str
    title: str
    runtime_action: str
    input_preview: Mapping[str, Any]
    candidate_tools: tuple[str, ...]
    selector_action: str = ""


@dataclass(frozen=True, slots=True)
class _CompiledAction:
    title: str
    runtime_action: str
    input_preview: Mapping[str, Any]
    candidate_tools: tuple[str, ...]
    selector_action: str = ""
    support_steps: tuple[_CompiledSupportStep, ...] = ()


_ActionCompiler = Callable[
    [AbstractCapabilitySubgoalProposal, Mapping[str, str]],
    _CompiledAction,
]


def _compile_browser_search(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    query = _required_slot(slots, "query")
    return _CompiledAction(
        title="Search the web",
        runtime_action="search",
        input_preview={"query": query},
        candidate_tools=("browser.search",),
        selector_action="search",
    )


def _compile_browser_open(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    url = _required_http_url(slots, "url")
    return _CompiledAction(
        title="Open web URL",
        runtime_action="open_url",
        input_preview={"url": url},
        candidate_tools=("browser.open_url", "browser.open"),
        selector_action="open_url",
    )


def _compile_browser_extract(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    url = str(slots.get("url") or "").strip()
    selector = str(slots.get("selector") or "").strip()
    input_preview: dict[str, str] = {}
    if url:
        input_preview["url"] = _validated_http_url(url, "url")
    if selector:
        input_preview["selector"] = selector
    return _CompiledAction(
        title="Extract web page text",
        runtime_action="extract_text",
        input_preview=input_preview,
        candidate_tools=(
            ("browser.open_url_and_extract_text",)
            if url
            else ("browser.extract_text", "browser.extract")
        ),
        selector_action="extract_text",
    )


def _compile_workspace_read(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    path = _required_slot(slots, "path")
    return _CompiledAction(
        title="Read workspace file",
        runtime_action="read_file",
        input_preview={"path": path},
        candidate_tools=("workspace.read", "fs.read_file", "file.read"),
        selector_action="read_file",
    )


def _compile_workspace_list(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    input_preview = {
        key: slots[key]
        for key in ("path", "pattern", "file_type")
        if str(slots.get(key) or "").strip()
    }
    return _CompiledAction(
        title="List workspace files",
        runtime_action="list_files",
        input_preview=input_preview,
        candidate_tools=("workspace.list", "fs.find_files", "file.search"),
        selector_action="list_files",
    )


def _compile_artifact_write(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    payload = {
        "path": _required_slot(slots, "path"),
        "content": _required_preserved_slot(slots, "content"),
    }
    return _compiled_action_for_tool(
        title="Write run artifact",
        runtime_action="write_artifact",
        capability_tool="artifact.write",
        input_preview=payload,
    )


def _compile_workspace_patch(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    payload: dict[str, Any] = {
        "path": _required_slot(slots, "path"),
        "patch": _required_preserved_slot(slots, "patch"),
    }
    expected_sha256 = _canonical_patch_sha256(slots)
    if expected_sha256:
        payload["expected_sha256"] = expected_sha256
    return _compiled_action_for_tool(
        title="Apply workspace patch",
        runtime_action="apply_patch",
        capability_tool="workspace.write_patch",
        input_preview=payload,
    )


def _compile_terminal_command(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    payload: dict[str, Any] = {
        "command": _required_preserved_slot(slots, "command"),
    }
    timeout_seconds = _optional_int_slot(
        slots,
        "timeout_seconds",
        minimum=1,
        maximum=120,
    )
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
    shell = _optional_bool_slot(slots, "shell")
    if shell is not None:
        payload["shell"] = shell
    return _compiled_action_for_tool(
        title="Run grounded terminal command",
        runtime_action="run_command",
        capability_tool="terminal.run",
        input_preview=payload,
    )


def _compile_browser_screenshot(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    payload = _optional_text_payload(slots, ("reason",))
    return _compiled_action_for_tool(
        title="Capture browser screenshot",
        runtime_action="screenshot",
        capability_tool="browser.screenshot",
        input_preview=payload,
    )


def _compile_browser_click(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    target = _required_slot(slots, "target")
    payload: dict[str, Any] = {"selector": f"text={target}"}
    click_count = _optional_int_slot(
        slots,
        "click_count",
        minimum=1,
        maximum=3,
    )
    if click_count is not None:
        payload["click_count"] = click_count
    return _compiled_action_for_tool(
        title="Click browser text target",
        runtime_action="click",
        capability_tool="browser.click",
        input_preview=payload,
    )


def _compile_desktop_list_apps(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    payload: dict[str, Any] = _optional_text_payload(slots, ("query",))
    limit = _optional_int_slot(slots, "limit", minimum=1, maximum=500)
    if limit is not None:
        payload["limit"] = limit
    return _compiled_action_for_tool(
        title="List desktop apps",
        runtime_action="list_apps",
        capability_tool="desktop.list_apps",
        input_preview=payload,
    )


def _compile_desktop_list_windows(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    return _compiled_action_for_tool(
        title="List desktop windows",
        runtime_action="list_windows",
        capability_tool="desktop.list_windows",
        input_preview=_optional_text_payload(slots, ("app_name",)),
    )


def _compile_desktop_inspect_app(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    payload: dict[str, Any] = {
        "app_name": _required_slot(slots, "app_name"),
        **_optional_text_payload(slots, ("role_filter",)),
    }
    for slot in ("open_if_needed", "focus"):
        value = _optional_bool_slot(slots, slot)
        if value is not None:
            payload[slot] = value
    limit = _optional_int_slot(slots, "limit", minimum=1, maximum=200)
    if limit is not None:
        payload["limit"] = limit
    return _compiled_action_for_tool(
        title="Inspect desktop app",
        runtime_action="inspect_app",
        capability_tool="desktop.inspect_app",
        input_preview=payload,
    )


def _compile_desktop_read_ui(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    payload: dict[str, Any] = _optional_text_payload(
        slots,
        ("app_name", "role_filter"),
    )
    limit = _optional_int_slot(slots, "limit", minimum=1, maximum=200)
    if limit is not None:
        payload["limit"] = limit
    return _compiled_action_for_tool(
        title="Read desktop UI",
        runtime_action="read_ui",
        capability_tool="desktop.read_ui",
        input_preview=payload,
    )


def _compile_desktop_capture(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    return _compiled_action_for_tool(
        title="Capture desktop screen",
        runtime_action="capture",
        capability_tool="screen.capture",
        input_preview=_optional_text_payload(slots, ("reason",)),
    )


def _compile_desktop_verify(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    payload: dict[str, Any] = _optional_text_payload(
        slots,
        ("app_name", "role_filter"),
    )
    limit = _optional_int_slot(slots, "limit", minimum=1, maximum=200)
    if limit is not None:
        payload["limit"] = limit
    verification_goal = _optional_enum_slot(
        slots,
        "verification_goal",
        allowed=frozenset({"app_running"}),
    )
    if verification_goal:
        payload["verification_goal"] = verification_goal
    return _compiled_action_for_tool(
        title="Verify desktop state",
        runtime_action="verify",
        capability_tool="desktop.verify",
        input_preview=payload,
    )


def _compile_desktop_ui_click(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    payload: dict[str, Any] = {
        "target": _required_slot(slots, "target"),
        **_optional_text_payload(slots, ("role_filter",)),
    }
    limit = _optional_int_slot(slots, "limit", minimum=1, maximum=200)
    if limit is not None:
        payload["limit"] = limit
    click_count = _optional_int_slot(
        slots,
        "click_count",
        minimum=1,
        maximum=3,
    )
    if click_count is not None:
        payload["click_count"] = click_count
    return _compiled_action_for_tool(
        title="Click desktop UI element",
        runtime_action="click",
        capability_tool="desktop.click_ui_element",
        input_preview=payload,
    )


def _compile_desktop_ui_type(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    payload: dict[str, Any] = {
        "target": _required_slot(slots, "target"),
        "text": _required_preserved_slot(slots, "text"),
        **_optional_text_payload(slots, ("role_filter",)),
    }
    limit = _optional_int_slot(slots, "limit", minimum=1, maximum=200)
    if limit is not None:
        payload["limit"] = limit
    return _compiled_action_for_tool(
        title="Type into desktop UI element",
        runtime_action="type",
        capability_tool="desktop.type_into_ui_element",
        input_preview=payload,
    )


def _compile_desktop_ui_submit(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    action = _required_enum_slot(
        slots,
        "action",
        allowed=frozenset({"send", "submit", "confirm"}),
    )
    return _compiled_action_for_tool(
        title="Submit foreground desktop input",
        runtime_action="submit",
        capability_tool="desktop.submit_foreground",
        input_preview={"action": action},
    )


def _compile_desktop_app_open(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    app_name = _required_slot(slots, "app_name")
    return _CompiledAction(
        title="Open desktop app",
        runtime_action="open_app",
        input_preview={"app_name": app_name},
        candidate_tools=("desktop.open_app", "app.open"),
        selector_action="open_app",
        support_steps=(_desktop_app_verifier(app_name),),
    )


def _compile_desktop_app_focus(
    subgoal: AbstractCapabilitySubgoalProposal,
    slots: Mapping[str, str],
) -> _CompiledAction:
    del subgoal
    app_name = _required_slot(slots, "app_name")
    return _CompiledAction(
        title="Focus desktop app",
        runtime_action="focus_app",
        input_preview={"app_name": app_name},
        candidate_tools=("desktop.focus_app", "app.focus"),
        selector_action="focus_app",
        support_steps=(_desktop_app_verifier(app_name),),
    )


def _desktop_app_verifier(app_name: str) -> _CompiledSupportStep:
    return _CompiledSupportStep(
        capability_id="desktop.visual_verification",
        title="Verify active desktop app",
        runtime_action="verify",
        input_preview={"app_name": app_name},
        candidate_tools=("desktop.verify",),
        selector_action="verify",
    )


_ACTION_COMPILERS: dict[tuple[str, str], _ActionCompiler] = {
    ("browser.research", "search"): _compile_browser_search,
    ("browser.research", "open_url"): _compile_browser_open,
    ("browser.research", "extract_text"): _compile_browser_extract,
    ("browser.research", "screenshot"): _compile_browser_screenshot,
    ("browser.research", "click"): _compile_browser_click,
    ("file.workspace_read", "read_file"): _compile_workspace_read,
    ("file.workspace_read", "list_files"): _compile_workspace_list,
    ("artifact.write", "write_artifact"): _compile_artifact_write,
    ("file.workspace_write", "apply_patch"): _compile_workspace_patch,
    ("terminal.execution", "run_command"): _compile_terminal_command,
    ("desktop.app_control", "open_app"): _compile_desktop_app_open,
    ("desktop.app_control", "focus_app"): _compile_desktop_app_focus,
    ("desktop.app_discovery", "list_apps"): _compile_desktop_list_apps,
    ("desktop.app_discovery", "list_windows"): _compile_desktop_list_windows,
    ("desktop.app_discovery", "inspect_app"): _compile_desktop_inspect_app,
    ("desktop.app_discovery", "read_ui"): _compile_desktop_read_ui,
    ("desktop.app_discovery", "capture"): _compile_desktop_capture,
    ("desktop.app_discovery", "verify"): _compile_desktop_verify,
    ("desktop.ui_operation", "click"): _compile_desktop_ui_click,
    ("desktop.ui_operation", "type"): _compile_desktop_ui_type,
    ("desktop.ui_operation", "submit"): _compile_desktop_ui_submit,
}

_ACTION_SLOT_NAMES: dict[tuple[str, str], frozenset[str]] = {
    ("browser.research", "search"): frozenset({"query"}),
    ("browser.research", "open_url"): frozenset({"url"}),
    ("browser.research", "extract_text"): frozenset({"url", "selector"}),
    ("browser.research", "screenshot"): frozenset({"reason"}),
    ("browser.research", "click"): frozenset({"target", "click_count"}),
    ("file.workspace_read", "read_file"): frozenset({"path"}),
    ("file.workspace_read", "list_files"): frozenset({"path", "pattern", "file_type"}),
    ("artifact.write", "write_artifact"): frozenset({"path", "content"}),
    ("file.workspace_write", "apply_patch"): frozenset(
        {"path", "patch", "expected_sha256", "base_sha256"}
    ),
    ("terminal.execution", "run_command"): frozenset({"command", "timeout_seconds", "shell"}),
    ("desktop.app_control", "open_app"): frozenset({"app_name"}),
    ("desktop.app_control", "focus_app"): frozenset({"app_name"}),
    ("desktop.app_discovery", "list_apps"): frozenset({"query", "limit"}),
    ("desktop.app_discovery", "list_windows"): frozenset({"app_name"}),
    ("desktop.app_discovery", "inspect_app"): frozenset(
        {"app_name", "open_if_needed", "focus", "role_filter", "limit"}
    ),
    ("desktop.app_discovery", "read_ui"): frozenset({"app_name", "role_filter", "limit"}),
    ("desktop.app_discovery", "capture"): frozenset({"reason"}),
    ("desktop.app_discovery", "verify"): frozenset(
        {"app_name", "role_filter", "limit", "verification_goal"}
    ),
    ("desktop.ui_operation", "click"): frozenset({"target", "role_filter", "limit", "click_count"}),
    ("desktop.ui_operation", "type"): frozenset({"target", "text", "role_filter", "limit"}),
    ("desktop.ui_operation", "submit"): frozenset({"action"}),
}

_ACTION_REQUIRED_SLOTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("browser.research", "search"): ("query",),
    ("browser.research", "open_url"): ("url",),
    ("browser.research", "extract_text"): (),
    ("browser.research", "screenshot"): (),
    ("browser.research", "click"): ("target",),
    ("file.workspace_read", "read_file"): ("path",),
    ("file.workspace_read", "list_files"): (),
    ("artifact.write", "write_artifact"): ("path", "content"),
    ("file.workspace_write", "apply_patch"): ("path", "patch"),
    ("terminal.execution", "run_command"): ("command",),
    ("desktop.app_control", "open_app"): ("app_name",),
    ("desktop.app_control", "focus_app"): ("app_name",),
    ("desktop.app_discovery", "list_apps"): (),
    ("desktop.app_discovery", "list_windows"): (),
    ("desktop.app_discovery", "inspect_app"): ("app_name",),
    ("desktop.app_discovery", "read_ui"): (),
    ("desktop.app_discovery", "capture"): (),
    ("desktop.app_discovery", "verify"): (),
    ("desktop.ui_operation", "click"): ("target",),
    ("desktop.ui_operation", "type"): ("target", "text"),
    ("desktop.ui_operation", "submit"): ("action",),
}

_ACTION_SEMANTICS: dict[tuple[str, str], str] = {
    ("browser.research", "search"): "Search the web for a user-provided query.",
    ("browser.research", "open_url"): "Open one user-provided HTTP(S) URL.",
    ("browser.research", "extract_text"): (
        "Extract text from the current page or a user-provided URL."
    ),
    ("browser.research", "screenshot"): (
        "Capture the current browser view without claiming a postcondition."
    ),
    ("browser.research", "click"): (
        "Click one user-provided visible text target in the current page."
    ),
    ("file.workspace_read", "read_file"): "Read one user-provided workspace path.",
    ("file.workspace_read", "list_files"): (
        "List workspace files using optional user-provided filters."
    ),
    ("artifact.write", "write_artifact"): (
        "Write exact user-provided content to a run artifact path with native readback proof."
    ),
    ("file.workspace_write", "apply_patch"): (
        "Apply an exact user-provided patch to a workspace path, optionally "
        "guarded by a canonical SHA-256 digest."
    ),
    ("terminal.execution", "run_command"): (
        "Run one exact user-provided command with optional bounded execution settings."
    ),
    ("desktop.app_control", "open_app"): (
        "Open one user-provided desktop app and verify the active app."
    ),
    ("desktop.app_control", "focus_app"): (
        "Focus one user-provided desktop app and verify the active app."
    ),
    ("desktop.app_discovery", "list_apps"): (
        "List desktop apps using optional user-provided filters."
    ),
    ("desktop.app_discovery", "list_windows"): (
        "List desktop windows, optionally for one user-provided app."
    ),
    ("desktop.app_discovery", "inspect_app"): (
        "Inspect one user-provided desktop app using bounded observation options."
    ),
    ("desktop.app_discovery", "read_ui"): (
        "Read the visible desktop UI using optional user-provided filters."
    ),
    ("desktop.app_discovery", "capture"): "Capture the current desktop screen.",
    ("desktop.app_discovery", "verify"): (
        "Observe desktop state for an explicit supported verification goal."
    ),
    ("desktop.ui_operation", "click"): (
        "Click one user-provided desktop UI target without claiming verification."
    ),
    ("desktop.ui_operation", "type"): (
        "Type exact user-provided text into one user-provided desktop UI target."
    ),
    ("desktop.ui_operation", "submit"): (
        "Perform one explicit supported foreground submit action without claiming verification."
    ),
}

_ACTION_CATALOG_SAMPLE_SLOTS: dict[tuple[str, str], dict[str, str]] = {
    ("browser.research", "search"): {"query": "user-provided query"},
    ("browser.research", "open_url"): {"url": "https://example.invalid"},
    ("browser.research", "extract_text"): {},
    ("browser.research", "screenshot"): {},
    ("browser.research", "click"): {"target": "Continue"},
    ("file.workspace_read", "read_file"): {"path": "README.md"},
    ("file.workspace_read", "list_files"): {},
    ("artifact.write", "write_artifact"): {
        "path": "report.md",
        "content": "User content",
    },
    ("file.workspace_write", "apply_patch"): {
        "path": "README.md",
        "patch": "@@ -1 +1 @@\n-old\n+new\n",
    },
    ("terminal.execution", "run_command"): {"command": "printf catalog"},
    ("desktop.app_control", "open_app"): {"app_name": "User App"},
    ("desktop.app_control", "focus_app"): {"app_name": "User App"},
    ("desktop.app_discovery", "list_apps"): {},
    ("desktop.app_discovery", "list_windows"): {},
    ("desktop.app_discovery", "inspect_app"): {"app_name": "User App"},
    ("desktop.app_discovery", "read_ui"): {},
    ("desktop.app_discovery", "capture"): {},
    ("desktop.app_discovery", "verify"): {},
    ("desktop.ui_operation", "click"): {"target": "Continue"},
    ("desktop.ui_operation", "type"): {
        "target": "Search",
        "text": "User text",
    },
    ("desktop.ui_operation", "submit"): {"action": "confirm"},
}

_CAPABILITY_INTENT_KIND = {
    "browser.research": "web_research",
    "file.workspace_read": "file_access",
    "artifact.write": "report_generation",
    "file.workspace_write": "file_operation",
    "terminal.execution": "code_task",
    "desktop.app_control": "desktop_operation",
    "desktop.app_discovery": "desktop_operation",
    "desktop.ui_operation": "desktop_operation",
}

_RISK_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

_LITERAL_TERMINAL_COMMAND_NAMES = frozenset(
    {
        "awk",
        "bash",
        "brew",
        "bun",
        "cargo",
        "cat",
        "cd",
        "chmod",
        "cp",
        "curl",
        "deno",
        "df",
        "docker",
        "du",
        "echo",
        "env",
        "find",
        "git",
        "go",
        "grep",
        "head",
        "java",
        "javac",
        "make",
        "mkdir",
        "mv",
        "node",
        "npm",
        "npx",
        "pip",
        "pip3",
        "pnpm",
        "printf",
        "ps",
        "pwd",
        "python",
        "python3",
        "pytest",
        "rg",
        "rm",
        "sed",
        "sh",
        "source",
        "swift",
        "tail",
        "touch",
        "uv",
        "wget",
        "xargs",
        "yarn",
        "zsh",
    }
)

_ACTION_EVIDENCE_PATTERNS: dict[tuple[str, str], re.Pattern[str]] = {
    ("browser.research", "search"): re.compile(
        r"(?:搜索|查找|检索|调研|研究|\b(?:search|find|research)\b)",
        flags=re.IGNORECASE,
    ),
    ("browser.research", "open_url"): re.compile(
        r"(?:打开|点开|\bopen\b)",
        flags=re.IGNORECASE,
    ),
    ("browser.research", "extract_text"): re.compile(
        r"(?:提取|读取|\b(?:extract|read)\b)",
        flags=re.IGNORECASE,
    ),
    ("browser.research", "screenshot"): re.compile(
        r"(?:截图|截屏|捕获|\b(?:screenshot|capture)\b)",
        flags=re.IGNORECASE,
    ),
    ("browser.research", "click"): re.compile(
        r"(?:点击|点按|点开|\b(?:click|tap|press)\b)",
        flags=re.IGNORECASE,
    ),
    ("file.workspace_read", "read_file"): re.compile(
        r"(?:读取|查看|检查|\b(?:read|view|inspect)\b)",
        flags=re.IGNORECASE,
    ),
    ("file.workspace_read", "list_files"): re.compile(
        r"(?:列出|列举|\b(?:list|enumerate)\b)",
        flags=re.IGNORECASE,
    ),
    ("artifact.write", "write_artifact"): re.compile(
        r"(?:写入|保存|创建|写|\b(?:write|save|create)\b)",
        flags=re.IGNORECASE,
    ),
    ("file.workspace_write", "apply_patch"): re.compile(
        r"(?:应用补丁|打补丁|修改|更新|写入|"
        r"\b(?:apply\s+(?:a\s+)?patch|patch|modify|update|write)\b)",
        flags=re.IGNORECASE,
    ),
    ("terminal.execution", "run_command"): re.compile(
        r"(?:运行|执行|\b(?:run|execute)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.app_control", "open_app"): re.compile(
        r"(?:打开|启动|开启|拉起|\b(?:open|launch|start)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.app_control", "focus_app"): re.compile(
        r"(?:聚焦|切换到?|切到|置前|激活|\b(?:focus|switch|activate|bring)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.app_discovery", "list_apps"): re.compile(
        r"(?:列出|列举|查看|\b(?:list|enumerate|show)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.app_discovery", "list_windows"): re.compile(
        r"(?:列出|列举|查看|\b(?:list|enumerate|show)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.app_discovery", "inspect_app"): re.compile(
        r"(?:检查|查看|审查|\b(?:inspect|check|examine)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.app_discovery", "read_ui"): re.compile(
        r"(?:读取|查看|检查|\b(?:read|view|inspect)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.app_discovery", "capture"): re.compile(
        r"(?:截图|截屏|捕获|\b(?:screenshot|capture)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.app_discovery", "verify"): re.compile(
        r"(?:验证|确认|核实|\b(?:verify|confirm|check)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.ui_operation", "click"): re.compile(
        r"(?:点击|点按|点开|\b(?:click|tap|press)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.ui_operation", "type"): re.compile(
        r"(?:输入|键入|填写|\b(?:type|enter|fill)\b)",
        flags=re.IGNORECASE,
    ),
    ("desktop.ui_operation", "submit"): re.compile(
        r"(?:提交|发送|确认|\b(?:submit|send|confirm)\b)",
        flags=re.IGNORECASE,
    ),
}


def abstract_capability_action_catalog(
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    """Describe executable semantic actions without exposing adapter authority."""

    allowed = tuple(
        dict.fromkeys(tool for raw_tool in allowed_tools if (tool := str(raw_tool or "").strip()))
    )
    if not allowed:
        return []
    capabilities = capability_definition_map()
    catalog: list[dict[str, Any]] = []
    for key, compiler in _ACTION_COMPILERS.items():
        capability_id, action_id = key
        capability = capabilities.get(capability_id)
        if capability is None or action_id not in {
            *capability.discovery_actions,
            *capability.execution_actions,
        }:
            continue
        sample_slots = _ACTION_CATALOG_SAMPLE_SLOTS[key]
        sample_subgoal = AbstractCapabilitySubgoalProposal(
            capability_id=capability_id,
            action_id=action_id,
            planning_goal="Runtime catalog sample",
            action_evidence="Runtime catalog sample",
        )
        compiled = compiler(sample_subgoal, sample_slots)
        if not _compiled_action_has_trusted_route(compiled, capability_id, allowed):
            continue
        required_slots = _ACTION_REQUIRED_SLOTS[key]
        catalog.append(
            {
                "capability_id": capability_id,
                "action_id": action_id,
                "required_slots": list(required_slots),
                "optional_slots": sorted(_ACTION_SLOT_NAMES[key] - set(required_slots)),
                "semantics": _ACTION_SEMANTICS[key],
            }
        )
    return catalog


def _compiled_action_has_trusted_route(
    compiled: _CompiledAction,
    capability_id: str,
    allowed_tools: Iterable[str],
) -> bool:
    primary = _trusted_selection_for_compiled_step(
        capability_id=capability_id,
        action_id=compiled.selector_action or compiled.runtime_action,
        candidate_tools=compiled.candidate_tools,
        input_preview=compiled.input_preview,
        allowed_tools=allowed_tools,
    )
    if not primary.selected_tool:
        return False
    return all(
        _trusted_selection_for_compiled_step(
            capability_id=support.capability_id,
            action_id=support.selector_action or support.runtime_action,
            candidate_tools=support.candidate_tools,
            input_preview=support.input_preview,
            allowed_tools=allowed_tools,
        ).selected_tool
        for support in compiled.support_steps
    )


def _trusted_selection_for_compiled_step(
    *,
    capability_id: str,
    action_id: str,
    candidate_tools: Iterable[str],
    input_preview: Mapping[str, Any],
    allowed_tools: Iterable[str],
    readiness_by_tool: Mapping[str, Any] | None = None,
) -> ToolCandidateSelection:
    candidates = list(
        dict.fromkeys(tool for raw_tool in candidate_tools if (tool := str(raw_tool or "").strip()))
    )
    for tool_name in registered_tool_names_for_capability(capability_id):
        if tool_name in candidates or action_id not in {
            str(value or "").strip() for value in action_ids_for_tool(tool_name)
        }:
            continue
        descriptor = TOOL_DESCRIPTORS.get(tool_name)
        if descriptor is None:
            continue
        try:
            descriptor.validate_payload(dict(input_preview))
        except Exception:
            continue
        candidates.append(tool_name)
    return select_trusted_tool_candidate(
        candidates,
        allowed_tools,
        required_capability=capability_id,
        required_action=action_id,
        readiness_by_tool=readiness_by_tool,
    )


def _proposal_tool_readiness(
    metadata: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    readiness = metadata.get("tool_readiness_by_tool")
    return readiness if isinstance(readiness, Mapping) else {}


def compile_abstract_capability_plan(
    proposal: AbstractCapabilityPlanProposal,
    original_goal: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
    planner: RuntimePlanner | None = None,
) -> PlannerDecisionSnapshot:
    """Atomically compile and finalize one ordered abstract capability plan."""

    if not isinstance(proposal, AbstractCapabilityPlanProposal):
        raise AbstractCapabilityPlanningError("abstract_capability_proposal_invalid")
    immutable_goal = _required_text(original_goal, "original_goal")
    proposed_intent_kind = _required_text(proposal.intent_kind, "intent_kind")
    planning_goal = _bounded_text(proposal.planning_goal, "planning_goal")
    if proposed_intent_kind not in _KNOWN_INTENT_KINDS or proposed_intent_kind == "general":
        raise AbstractCapabilityPlanningError("abstract_capability_intent_kind_unknown")
    subgoals = tuple(proposal.subgoals)
    if not subgoals or len(subgoals) > ABSTRACT_CAPABILITY_MAX_SUBGOALS:
        raise AbstractCapabilityPlanningError("abstract_capability_subgoal_count_invalid")
    allowed = tuple(
        dict.fromkeys(tool for raw_tool in allowed_tools if (tool := str(raw_tool or "").strip()))
    )
    if not allowed:
        raise AbstractCapabilityPlanningError("abstract_capability_allowed_tools_empty")
    authority_sources = _authority_sources(metadata, immutable_goal)

    # Validate and compile every subgoal before minting a plan.  There is no
    # partial result: one unsupported pair or ungrounded slot rejects all of it.
    compiled_actions: list[tuple[AbstractCapabilitySubgoalProposal, str, _CompiledAction]] = []
    registered_capabilities = capability_definition_map()
    for subgoal in subgoals:
        if not isinstance(subgoal, AbstractCapabilitySubgoalProposal):
            raise AbstractCapabilityPlanningError("abstract_capability_subgoal_invalid")
        capability_id = _required_text(subgoal.capability_id, "capability_id")
        action_id = _required_text(subgoal.action_id, "action_id")
        capability = registered_capabilities.get(capability_id)
        if capability is None:
            raise AbstractCapabilityPlanningError("abstract_capability_capability_unregistered")
        canonical_action_id = action_id
        declared_actions = {
            *capability.discovery_actions,
            *capability.execution_actions,
        }
        if canonical_action_id not in declared_actions:
            raise AbstractCapabilityPlanningError("abstract_capability_action_unregistered")
        key = (capability_id, canonical_action_id)
        compiler = _ACTION_COMPILERS.get(key)
        if compiler is None:
            raise AbstractCapabilityPlanningError("abstract_capability_action_unregistered")
        subgoal_goal = _bounded_text(subgoal.planning_goal, "subgoal_planning_goal")
        action_evidence = _bounded_evidence(
            subgoal.action_evidence,
            "action_evidence",
        )
        if not _quote_is_exactly_grounded(action_evidence, authority_sources):
            raise AbstractCapabilityPlanningError("abstract_capability_action_evidence_ungrounded")
        if action_evidence not in subgoal_goal:
            raise AbstractCapabilityPlanningError(
                "abstract_capability_action_evidence_missing_from_planning_goal"
            )
        if not _ACTION_EVIDENCE_PATTERNS[key].search(action_evidence):
            raise AbstractCapabilityPlanningError("abstract_capability_action_evidence_mismatch")
        if not _abstract_action_evidence_is_grounded(
            immutable_goal,
            subgoal_goal,
            action_evidence,
            _ACTION_EVIDENCE_PATTERNS[key],
        ):
            raise AbstractCapabilityPlanningError("abstract_capability_action_evidence_rejected")
        slots = _validated_input_slots(
            subgoal.input_slots,
            allowed_slots=_ACTION_SLOT_NAMES[key],
            authority_sources=authority_sources,
        )
        if key == ("terminal.execution", "run_command"):
            command = _required_preserved_slot(slots, "command")
            if not _terminal_command_has_authorized_literal_provenance(
                authority_sources,
                command,
            ):
                raise AbstractCapabilityPlanningError("abstract_capability_input_invalid:command")
        normalized_subgoal = AbstractCapabilitySubgoalProposal(
            capability_id=capability_id,
            action_id=action_id,
            planning_goal=subgoal_goal,
            action_evidence=action_evidence,
            input_slots=tuple(subgoal.input_slots),
        )
        compiled_actions.append(
            (
                normalized_subgoal,
                canonical_action_id,
                compiler(normalized_subgoal, slots),
            )
        )

    compiled_intent_families = tuple(
        _CAPABILITY_INTENT_KIND[subgoal.capability_id]
        for subgoal, _action_id, _compiled in compiled_actions
    )
    if proposed_intent_kind not in set(compiled_intent_families):
        raise AbstractCapabilityPlanningError("abstract_capability_intent_kind_mismatch")
    intent_kind = compiled_intent_families[-1]

    required_capabilities = list(
        dict.fromkeys(subgoal.capability_id for subgoal, _action_id, _compiled in compiled_actions)
    )
    proposal_audit = [
        {
            "capability_id": subgoal.capability_id,
            "action_id": subgoal.action_id,
            "planning_goal": subgoal.planning_goal,
            "action_evidence": subgoal.action_evidence,
            "input_slots": [
                {
                    "slot": item.slot,
                    "value": item.value,
                    "evidence_quote": item.evidence_quote,
                }
                for item in subgoal.input_slots
            ],
        }
        for subgoal, _action_id, _compiled in compiled_actions
    ]
    intent_id = stable_planner_id(
        "intent",
        f"abstract-capability:{intent_kind}",
        (f"{immutable_goal}\n{planning_goal}\n{proposed_intent_kind}\n{proposal_audit!r}"),
    )

    steps: list[ToolPlanStepSnapshot] = []
    explicit_goal_subgoals: list[dict[str, str]] = []
    previous_step_id = ""
    readiness_by_tool = _proposal_tool_readiness(metadata)
    for index, (subgoal, canonical_action_id, compiled) in enumerate(
        compiled_actions,
        start=1,
    ):
        selection = _trusted_selection_for_compiled_step(
            capability_id=subgoal.capability_id,
            action_id=compiled.selector_action or canonical_action_id,
            candidate_tools=compiled.candidate_tools,
            input_preview=compiled.input_preview,
            allowed_tools=allowed,
            readiness_by_tool=readiness_by_tool,
        )
        step_id = f"{compiled.runtime_action.replace('_', '-')}-{index}"
        steps.append(
            _tool_plan_step_from_selection(
                step_id=step_id,
                title=compiled.title,
                capability_id=subgoal.capability_id,
                action=compiled.runtime_action,
                input_preview=compiled.input_preview,
                selection=selection,
                depends_on=[previous_step_id] if previous_step_id else [],
                reason=(
                    "Compile the user-grounded abstract action through the registered "
                    "Runtime action compiler."
                ),
            )
        )
        if compiled.runtime_action != "verify":
            explicit_goal_subgoals.append(
                {
                    "step_id": step_id,
                    "capability_id": subgoal.capability_id,
                    "action_id": canonical_action_id,
                }
            )
        previous_step_id = step_id
        for support_index, support in enumerate(compiled.support_steps, start=1):
            support_selection = _trusted_selection_for_compiled_step(
                capability_id=support.capability_id,
                action_id=support.selector_action or support.runtime_action,
                candidate_tools=support.candidate_tools,
                input_preview=support.input_preview,
                allowed_tools=allowed,
                readiness_by_tool=readiness_by_tool,
            )
            support_step_id = (
                f"verify-{compiled.runtime_action.replace('_', '-')}-{index}"
                if support.runtime_action == "verify" and support_index == 1
                else (
                    f"support-{compiled.runtime_action.replace('_', '-')}-{index}-{support_index}"
                )
            )
            steps.append(
                _tool_plan_step_from_selection(
                    step_id=support_step_id,
                    title=support.title,
                    capability_id=support.capability_id,
                    action=support.runtime_action,
                    input_preview=support.input_preview,
                    selection=support_selection,
                    depends_on=[previous_step_id],
                    reason=(
                        "Add Runtime-owned support evidence required by the registered "
                        "abstract action compiler."
                    ),
                )
            )
            previous_step_id = support_step_id

    intent_inputs: dict[str, Any] = {
        "runtime_model_planning_goal": planning_goal,
        "runtime_model_proposed_intent_kind": proposed_intent_kind,
        "runtime_abstract_capability_plan": proposal_audit,
    }
    if explicit_goal_subgoals:
        # Runtime doctrine treats verification as evidence, not as a semantic
        # source step.  Leave a verification-only plan on the legacy contract
        # path instead of minting invalid explicit-source metadata.
        intent_inputs["runtime_explicit_goal_subgoals"] = explicit_goal_subgoals
    intent = TaskIntentSnapshot(
        intent_id=intent_id,
        kind=intent_kind,
        title="Abstract Capability Plan",
        user_goal=immutable_goal,
        confidence=1.0,
        description="Runtime-validated ordered capability actions.",
        inputs=intent_inputs,
        required_capabilities=required_capabilities,
        risk_level=_highest_step_risk(steps),
    )

    runtime_planner = planner or RuntimePlanner()
    plan = runtime_planner.plan_compiled_steps(
        intent,
        steps,
        allowed_tools=allowed,
        metadata=metadata,
        original_goal=immutable_goal,
    )
    finalized_risk = _highest_step_risk(plan.tool_plan.steps)
    if finalized_risk != str(plan.intent.risk_level or "low"):
        intent = intent.model_copy(update={"risk_level": finalized_risk})
        plan = runtime_planner.plan_compiled_steps(
            intent,
            plan.tool_plan.steps,
            allowed_tools=allowed,
            metadata=metadata,
            original_goal=immutable_goal,
        )
    if plan.tool_plan.missing_capabilities or any(
        step.status == "unavailable" or not step.tool_name for step in plan.tool_plan.steps
    ):
        raise AbstractCapabilityPlanningError("abstract_capability_action_compiler_unavailable")
    authoritative_intent = plan.intent
    return PlannerDecisionSnapshot(
        decision_id=stable_planner_id(
            "decision",
            f"abstract-capability:{intent_kind}",
            (f"{immutable_goal}\n{planning_goal}\n{proposed_intent_kind}\n{proposal_audit!r}"),
        ),
        prompt=immutable_goal,
        selected_intent=authoritative_intent,
        candidate_intents=[authoritative_intent],
        plan=plan,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _tool_plan_step_from_selection(
    *,
    step_id: str,
    title: str,
    capability_id: str,
    action: str,
    input_preview: Mapping[str, Any],
    selection: ToolCandidateSelection,
    depends_on: list[str],
    reason: str,
) -> ToolPlanStepSnapshot:
    tool_name = selection.selected_tool
    selected_candidate = next(
        (
            candidate
            for candidate in selection.ranked_candidates
            if candidate.tool_name == tool_name
        ),
        None,
    )
    payload = dict(input_preview)
    return ToolPlanStepSnapshot(
        step_id=step_id,
        title=title,
        capability_id=capability_id,
        action=action,
        tool_name=tool_name,
        input_preview=payload,
        risk_level=(selected_candidate.risk_level if selected_candidate is not None else "medium"),
        execution_mode=(
            desktop_tool_execution_mode_for_input(tool_name, payload) if tool_name else None
        ),
        approval_required=(
            selected_candidate.approval_required if selected_candidate is not None else False
        ),
        depends_on=depends_on,
        reason=reason,
        fallback_tools=list(selection.alternatives),
        status=(
            "planned"
            if selected_candidate is not None and not selected_candidate.blocked
            else "unavailable"
        ),
    )


def _highest_step_risk(steps: Iterable[ToolPlanStepSnapshot]) -> str:
    return max(
        (str(step.risk_level or "low").strip().lower() for step in steps),
        key=lambda value: _RISK_RANK.get(value, _RISK_RANK["medium"]),
        default="low",
    )


def _validated_input_slots(
    input_slots: Iterable[AbstractCapabilityInputSlotProposal],
    *,
    allowed_slots: frozenset[str],
    authority_sources: tuple[str, ...],
) -> dict[str, str]:
    values = tuple(input_slots)
    if len(values) > ABSTRACT_CAPABILITY_MAX_INPUT_SLOTS:
        raise AbstractCapabilityPlanningError("abstract_capability_input_slot_count_invalid")
    result: dict[str, str] = {}
    for item in values:
        if not isinstance(item, AbstractCapabilityInputSlotProposal):
            raise AbstractCapabilityPlanningError("abstract_capability_input_slot_invalid")
        slot = _required_text(item.slot, "input_slot")
        if slot not in allowed_slots:
            raise AbstractCapabilityPlanningError("abstract_capability_input_slot_unregistered")
        if slot in result:
            raise AbstractCapabilityPlanningError("abstract_capability_input_slot_duplicate")
        value = _bounded_preserved_text(item.value, "input_value")
        evidence_quote = _bounded_preserved_text(
            item.evidence_quote,
            "input_evidence_quote",
        )
        if not _quote_is_exactly_grounded(evidence_quote, authority_sources):
            raise AbstractCapabilityPlanningError("abstract_capability_input_evidence_ungrounded")
        if value not in evidence_quote:
            raise AbstractCapabilityPlanningError("abstract_capability_input_value_not_in_evidence")
        result[slot] = value
    return result


def _authority_sources(
    metadata: Mapping[str, Any] | None,
    immutable_goal: str,
) -> tuple[str, ...]:
    try:
        clarification = clarification_authority_for_goal(metadata, immutable_goal)
    except ValueError as exc:
        raise AbstractCapabilityPlanningError(
            "abstract_capability_clarification_authority_invalid"
        ) from exc
    return clarification if clarification is not None else (immutable_goal,)


def _quote_is_exactly_grounded(quote: str, sources: tuple[str, ...]) -> bool:
    return bool(quote and any(quote in source for source in sources))


def _abstract_action_evidence_is_grounded(
    immutable_goal: str,
    planning_goal: str,
    action_evidence: str,
    action_pattern: re.Pattern[str],
) -> bool:
    if _model_intent_action_evidence_is_grounded(
        immutable_goal,
        planning_goal,
        action_evidence,
    ):
        return True
    if action_evidence not in immutable_goal or action_evidence not in planning_goal:
        return False
    action_matches = tuple(action_pattern.finditer(action_evidence))
    if not action_matches:
        return False
    for occurrence in re.finditer(re.escape(action_evidence), immutable_goal):
        for action_match in action_matches:
            if _speech_act_action_occurrence_is_authorized(
                immutable_goal,
                occurrence.start() + action_match.start(),
                occurrence.start() + action_match.end(),
            ):
                return True
    return False


def _terminal_command_has_authorized_literal_provenance(
    authority_sources: tuple[str, ...],
    command: str,
) -> bool:
    if any(
        _terminal_command_is_bound_in_authority_source(source, command)
        for source in authority_sources
    ):
        return True
    if len(authority_sources) != 2:
        return False
    previous_goal, user_reply = authority_sources
    return bool(
        _terminal_authority_source_has_run_request(previous_goal)
        and _terminal_clarification_reply_is_exact_literal(user_reply, command)
        and _terminal_command_has_literal_shape(user_reply, command)
    )


def _terminal_command_is_bound_in_authority_source(
    authority_source: str,
    command: str,
) -> bool:
    if not _terminal_command_has_literal_shape(authority_source, command):
        return False
    action_pattern = _ACTION_EVIDENCE_PATTERNS[("terminal.execution", "run_command")]
    for command_occurrence in re.finditer(re.escape(command), authority_source):
        prefix = authority_source[: command_occurrence.start()]
        hard_boundaries = tuple(re.finditer(r"[.!?。！？;；]", prefix))
        clause_start = hard_boundaries[-1].end() if hard_boundaries else 0
        action_matches = tuple(
            action_pattern.finditer(
                authority_source,
                clause_start,
                command_occurrence.start(),
            )
        )
        if not action_matches:
            continue
        action_match = action_matches[-1]
        between = authority_source[action_match.end() : command_occurrence.start()]
        if len(between) > 200 or re.search(
            r"(?:不要|别|勿|禁止|不应|无需|不需|而不是|例如|比如|也许|可能|"
            r"\b(?:do\s+not|don't|never|not|without|except|instead\s+of|"
            r"rather\s+than|for\s+example|e\.g\.|maybe|perhaps)\b|"
            r"\b(?:he|she|they|someone)\s+(?:said|asked|wrote|suggested)\b)",
            between,
            flags=re.IGNORECASE,
        ):
            continue
        if _speech_act_action_occurrence_is_authorized(
            authority_source,
            action_match.start(),
            action_match.end(),
        ):
            return True
    return False


def _terminal_authority_source_has_run_request(authority_source: str) -> bool:
    action_pattern = _ACTION_EVIDENCE_PATTERNS[("terminal.execution", "run_command")]
    return any(
        _speech_act_action_occurrence_is_authorized(
            authority_source,
            action_match.start(),
            action_match.end(),
        )
        for action_match in action_pattern.finditer(authority_source)
    )


def _terminal_clarification_reply_is_exact_literal(
    user_reply: str,
    command: str,
) -> bool:
    if user_reply == command:
        return True
    escaped = re.escape(command)
    return bool(
        re.fullmatch(
            rf"\s*(?:```(?:[a-z0-9_-]+)?\s*|[`\"'“‘「『])"
            rf"\s*{escaped}\s*(?:```|[`\"'”’」』])\s*",
            user_reply,
            flags=re.IGNORECASE,
        )
        or re.fullmatch(
            rf"\s*(?:\b(?:command|cmd)\b|命令)\s*"
            rf"(?:is\s*)?(?:=|:|：)\s*{escaped}\s*",
            user_reply,
            flags=re.IGNORECASE,
        )
        or re.fullmatch(
            rf"\s*(?:\$|>)\s*{escaped}\s*",
            user_reply,
        )
    )


def _terminal_command_has_literal_shape(
    authority_source: str,
    command: str,
) -> bool:
    value = str(command or "")
    if not value.strip() or value not in authority_source:
        return False
    escaped = re.escape(value)
    if re.search(
        rf"(?:```(?:[a-z0-9_-]+)?\s*|[`\"'“‘「『])\s*{escaped}\s*"
        rf"(?:```|[`\"'”’」』])",
        authority_source,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(
        rf"(?:\b(?:command|cmd)\b|命令)\s*(?:is\s*)?(?:=|:|：)\s*"
        rf"(?:[`\"'“‘「『]\s*)?{escaped}"
        rf"(?=$|[.!?。！？;；\n`\"'”’」』])",
        authority_source,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(
        rf"(?:^|\n)\s*(?:\$|>)\s*{escaped}\s*(?=$|\n)",
        authority_source,
    ):
        return True
    first_token = re.split(r"[\s;&|<>]", value.strip(), maxsplit=1)[0]
    if first_token.startswith(("./", "../", "/", "~/")):
        return True
    return first_token.casefold() in _LITERAL_TERMINAL_COMMAND_NAMES


def _compiled_action_for_tool(
    *,
    title: str,
    runtime_action: str,
    capability_tool: str,
    input_preview: Mapping[str, Any],
) -> _CompiledAction:
    descriptor = TOOL_DESCRIPTORS.get(capability_tool)
    if descriptor is None:
        raise AbstractCapabilityPlanningError("abstract_capability_action_compiler_unavailable")
    payload = dict(input_preview)
    try:
        descriptor.validate_payload(payload)
    except Exception as exc:
        raise AbstractCapabilityPlanningError("abstract_capability_input_invalid:payload") from exc
    return _CompiledAction(
        title=title,
        runtime_action=runtime_action,
        input_preview=payload,
        candidate_tools=(capability_tool,),
        selector_action=runtime_action,
    )


def _required_slot(slots: Mapping[str, str], slot: str) -> str:
    value = str(slots.get(slot) or "").strip()
    if not value:
        raise AbstractCapabilityPlanningError(f"abstract_capability_required_input_missing:{slot}")
    return value


def _required_preserved_slot(slots: Mapping[str, str], slot: str) -> str:
    value = slots.get(slot)
    if not isinstance(value, str) or not value.strip():
        raise AbstractCapabilityPlanningError(f"abstract_capability_required_input_missing:{slot}")
    return value


def _optional_text_payload(
    slots: Mapping[str, str],
    names: Iterable[str],
) -> dict[str, str]:
    payload: dict[str, str] = {}
    for name in names:
        value = str(slots.get(name) or "").strip()
        if value:
            payload[name] = value
    return payload


def _optional_int_slot(
    slots: Mapping[str, str],
    slot: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    raw_value = slots.get(slot)
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not re.fullmatch(r"[0-9]+", value):
        raise AbstractCapabilityPlanningError(f"abstract_capability_input_invalid:{slot}")
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise AbstractCapabilityPlanningError(f"abstract_capability_input_invalid:{slot}")
    return parsed


def _optional_bool_slot(
    slots: Mapping[str, str],
    slot: str,
) -> bool | None:
    raw_value = slots.get(slot)
    if raw_value is None:
        return None
    value = str(raw_value).strip().casefold()
    if value in {"true", "是"}:
        return True
    if value in {"false", "否"}:
        return False
    raise AbstractCapabilityPlanningError(f"abstract_capability_input_invalid:{slot}")


def _optional_enum_slot(
    slots: Mapping[str, str],
    slot: str,
    *,
    allowed: frozenset[str],
) -> str | None:
    raw_value = slots.get(slot)
    if raw_value is None:
        return None
    value = str(raw_value).strip().casefold()
    if value not in allowed:
        raise AbstractCapabilityPlanningError(f"abstract_capability_input_invalid:{slot}")
    return value


def _required_enum_slot(
    slots: Mapping[str, str],
    slot: str,
    *,
    allowed: frozenset[str],
) -> str:
    value = _optional_enum_slot(slots, slot, allowed=allowed)
    if value is None:
        raise AbstractCapabilityPlanningError(f"abstract_capability_required_input_missing:{slot}")
    return value


def _canonical_patch_sha256(slots: Mapping[str, str]) -> str:
    canonical: dict[str, str] = {}
    for slot in ("expected_sha256", "base_sha256"):
        raw_value = slots.get(slot)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise AbstractCapabilityPlanningError(f"abstract_capability_input_invalid:{slot}")
        canonical[slot] = value.casefold()
    expected = canonical.get("expected_sha256", "")
    base = canonical.get("base_sha256", "")
    if expected and base and expected != base:
        raise AbstractCapabilityPlanningError("abstract_capability_input_invalid:base_sha256")
    return expected or base


def _required_http_url(slots: Mapping[str, str], slot: str) -> str:
    value = _required_slot(slots, slot)
    return _validated_http_url(value, slot)


def _validated_http_url(value: str, slot: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AbstractCapabilityPlanningError(f"abstract_capability_input_invalid:{slot}")
    return value


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AbstractCapabilityPlanningError(f"abstract_capability_{field_name}_invalid")
    return value.strip()


def _bounded_text(value: Any, field_name: str) -> str:
    clean = _required_text(value, field_name)
    clean = " ".join(clean.split())
    if len(clean) > ABSTRACT_CAPABILITY_TEXT_MAX_CHARS:
        raise AbstractCapabilityPlanningError(f"abstract_capability_{field_name}_too_long")
    return clean


def _bounded_evidence(value: Any, field_name: str) -> str:
    clean = _required_text(value, field_name)
    if len(clean) > ABSTRACT_CAPABILITY_EVIDENCE_MAX_CHARS:
        raise AbstractCapabilityPlanningError(f"abstract_capability_{field_name}_too_long")
    return clean


def _bounded_preserved_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AbstractCapabilityPlanningError(f"abstract_capability_{field_name}_invalid")
    if len(value) > ABSTRACT_CAPABILITY_EVIDENCE_MAX_CHARS:
        raise AbstractCapabilityPlanningError(f"abstract_capability_{field_name}_too_long")
    return value


__all__ = [
    "ABSTRACT_CAPABILITY_MAX_INPUT_SLOTS",
    "ABSTRACT_CAPABILITY_MAX_SUBGOALS",
    "AbstractCapabilityInputSlotProposal",
    "AbstractCapabilityPlanProposal",
    "AbstractCapabilityPlanningError",
    "AbstractCapabilitySubgoalProposal",
    "abstract_capability_action_catalog",
    "compile_abstract_capability_plan",
]
