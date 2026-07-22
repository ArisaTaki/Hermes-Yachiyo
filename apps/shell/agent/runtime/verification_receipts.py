"""Private authority markers for Runtime-owned verification receipts.

The marker is intentionally an in-process object rather than a serializable
string.  Model-authored JSON, persisted public events, and provider payloads
cannot manufacture a context that passes the identity check.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any


RUNTIME_PRIVATE_VERIFICATION_CONTEXT_KEY = "_runtime_verification_context"
RUNTIME_PRIVATE_VERIFICATION_CONTEXT_VERSION = 1
RUNTIME_PRIVATE_VERIFICATION_AUTHORITY = object()

APP_WINDOW_PRESENT_PREDICATE = "app_window_present"
EXACT_TYPED_CONTENT_PRESENT_PREDICATE = "exact_typed_content_present"
EXACT_CLIPBOARD_CONTENT_PRESENT_PREDICATE = "exact_clipboard_content_present"
EXACT_PASTED_CONTENT_PRESENT_PREDICATE = "exact_pasted_content_present"
EXACT_SUBMIT_DISPATCH_PREDICATE = "exact_submit_dispatch_receipt"
EXACT_FILE_CONTENT_PRESENT_PREDICATE = "exact_file_content_present"
SEMANTIC_ARTIFACT_ADEQUACY_PREDICATE = "semantic_artifact_adequacy"
SEMANTIC_ARTIFACT_ASSESSED_EVENT = "agent.goal.semantic_artifact.assessed"
RUNTIME_SEMANTIC_ARTIFACT_VERIFIER_AUTHORITY = (
    "runtime_semantic_artifact_verifier"
)
EXACT_FILE_READBACK_VERIFIER_TOOL_PREFERENCE = (
    "workspace.read",
    "fs.read_file",
    "file.read",
)
EXACT_FILE_READBACK_VERIFIER_TOOLS = frozenset(
    EXACT_FILE_READBACK_VERIFIER_TOOL_PREFERENCE
)

_EXPLICIT_OUTPUT_PRODUCER_ACTIONS = frozenset(
    {
        "analyze",
        "analyze_data",
        "analyze_data_file",
        "create",
        "create_file",
        "data_analysis",
        "export",
        "export_file",
        "generate",
        "generate_file",
        "produce",
        "produce_file",
        "render",
        "render_file",
        "run_analysis",
        "save",
        "save_file",
        "write",
        "write_artifact",
        "write_file",
    }
)
_EXPLICIT_PATH_PRODUCER_ACTIONS = _EXPLICIT_OUTPUT_PRODUCER_ACTIONS.difference(
    {"analyze", "analyze_data", "analyze_data_file", "data_analysis", "run_analysis"}
)


def normalized_workspace_relative_path(value: Any) -> str:
    """Return one unambiguous workspace-relative POSIX path or ``""``.

    Receipt correlation must not inherit the broker's more permissive path
    conveniences.  In particular, absolute, home-relative, Windows-shaped,
    and parent-traversal paths are never eligible completion evidence.
    """

    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if (
        not raw
        or "\x00" in raw
        or "\\" in raw
        or raw.startswith("~")
        or (len(raw) >= 2 and raw[0].isalpha() and raw[1] == ":")
    ):
        return ""
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        return ""
    normalized = path.as_posix()
    return "" if normalized in {"", "."} else normalized


def declared_workspace_output_path(action_target: Mapping[str, Any] | None) -> str:
    """Extract the exact declared output path from a producer action target."""

    if not isinstance(action_target, Mapping) or not action_target:
        return ""
    action = (
        str(action_target.get("action") or "")
        .strip()
        .casefold()
        .replace("-", "_")
    )
    if action not in _EXPLICIT_OUTPUT_PRODUCER_ACTIONS:
        return ""
    declared: list[str] = []
    for key in ("artifact_path", "output_path"):
        if key not in action_target:
            continue
        normalized = normalized_workspace_relative_path(action_target.get(key))
        if not normalized:
            return ""
        declared.append(normalized)
    if not declared and "path" in action_target:
        if action not in _EXPLICIT_PATH_PRODUCER_ACTIONS:
            return ""
        normalized = normalized_workspace_relative_path(action_target.get("path"))
        if not normalized:
            return ""
        declared.append(normalized)
    unique = tuple(dict.fromkeys(declared))
    return unique[0] if len(unique) == 1 else ""


__all__ = [
    "APP_WINDOW_PRESENT_PREDICATE",
    "EXACT_TYPED_CONTENT_PRESENT_PREDICATE",
    "EXACT_CLIPBOARD_CONTENT_PRESENT_PREDICATE",
    "EXACT_PASTED_CONTENT_PRESENT_PREDICATE",
    "EXACT_SUBMIT_DISPATCH_PREDICATE",
    "EXACT_FILE_CONTENT_PRESENT_PREDICATE",
    "SEMANTIC_ARTIFACT_ADEQUACY_PREDICATE",
    "SEMANTIC_ARTIFACT_ASSESSED_EVENT",
    "RUNTIME_SEMANTIC_ARTIFACT_VERIFIER_AUTHORITY",
    "EXACT_FILE_READBACK_VERIFIER_TOOL_PREFERENCE",
    "EXACT_FILE_READBACK_VERIFIER_TOOLS",
    "RUNTIME_PRIVATE_VERIFICATION_AUTHORITY",
    "RUNTIME_PRIVATE_VERIFICATION_CONTEXT_KEY",
    "RUNTIME_PRIVATE_VERIFICATION_CONTEXT_VERSION",
    "declared_workspace_output_path",
    "normalized_workspace_relative_path",
]
