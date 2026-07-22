"""Provenance-bound transfer of one tool result into another tool input.

The planner may declare dataflow between two steps, but the model-authored
request is never trusted to provide the value itself.  This module resolves a
small, deliberately constrained binding language against Runtime-owned
terminal events and returns a value-free receipt for audit events.
"""

from __future__ import annotations

import hashlib
import fnmatch
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

_TERMINAL_SUCCESS_EVENT = "agent.tool.call"
_SUPPORTED_VALUE_TYPES = frozenset({"string", "string_list", "number", "bool"})
_TARGET_SEGMENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_MAX_BINDINGS = 16
_MAX_POINTER_SEGMENTS = 16
_MAX_POINTER_LENGTH = 512
_DEFAULT_MAX_BYTES = 4096
_MAX_VALUE_BYTES = 65536
_MISSING = object()
_WORKSPACE_FILE_RESOLUTION_VERSION = 1
_WORKSPACE_FILE_RESOLUTION_KIND = "workspace_file_selection"
_WORKSPACE_FILE_SELECTION_SOURCES = frozenset(
    {"workspace.list", "file.search", "fs.find_files"}
)
_SELECTED_WORKSPACE_FILE_PATH = "<selected file from workspace.list>"
_SELECTED_WORKSPACE_FILES_PATH = "<selected files from workspace.list>"
_SELECTED_WORKSPACE_FILE_PATHS = frozenset(
    {_SELECTED_WORKSPACE_FILE_PATH, _SELECTED_WORKSPACE_FILES_PATH}
)


class InputBindingResolutionError(ValueError):
    """A declared binding could not be proven from the Runtime timeline."""

    def __init__(self, reason: str, *, binding_id: str = "") -> None:
        self.reason = str(reason or "input_binding_invalid").strip()
        self.binding_id = str(binding_id or "").strip()
        super().__init__(self.reason)


@dataclass(frozen=True, slots=True)
class InputBindingReceipt:
    """Value-free correlation receipt safe to persist in public run events."""

    binding_id: str
    run_id: str
    plan_id: str
    target_step_id: str
    target_tool_name: str
    target_input_path: str
    source_step_id: str
    source_tool_name: str
    source_tool_call_id: str
    source_result_path: str
    value_type: str
    value_bytes: int
    value_digest: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "target_step_id": self.target_step_id,
            "target_tool_name": self.target_tool_name,
            "target_input_path": self.target_input_path,
            "source_step_id": self.source_step_id,
            "source_tool_name": self.source_tool_name,
            "source_tool_call_id": self.source_tool_call_id,
            "source_result_path": self.source_result_path,
            "value_type": self.value_type,
            "value_bytes": self.value_bytes,
            "value_digest": self.value_digest,
        }


@dataclass(frozen=True, slots=True)
class InputBindingResolution:
    """Resolved request input plus receipts that never contain resolved values."""

    input: Mapping[str, Any]
    receipts: tuple[InputBindingReceipt, ...]
    bound_top_level_fields: frozenset[str]


@dataclass(frozen=True, slots=True)
class WorkspaceFileResolutionReceipt:
    """Replayable authority receipt for a discovery-selected workspace path."""

    run_id: str
    plan_id: str
    target_step_id: str
    target_tool_name: str
    target_tool_call_id: str
    source_step_id: str
    source_tool_name: str
    source_tool_call_id: str
    requested_path: str
    resolved_path: str
    resolved_paths: tuple[str, ...]
    source_scope: str
    pattern: str
    file_type: str
    selection: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": _WORKSPACE_FILE_RESOLUTION_VERSION,
            "resolution_kind": _WORKSPACE_FILE_RESOLUTION_KIND,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "target_step_id": self.target_step_id,
            "target_tool_name": self.target_tool_name,
            "target_tool_call_id": self.target_tool_call_id,
            "source_step_id": self.source_step_id,
            "source_tool_name": self.source_tool_name,
            "source_tool_call_id": self.source_tool_call_id,
            "requested_path": self.requested_path,
            "resolved_path": self.resolved_path,
            "resolved_paths": list(self.resolved_paths),
            "source_scope": self.source_scope,
            "pattern": self.pattern,
            "file_type": self.file_type,
            "selection": self.selection,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceFileResolution:
    """Resolved workspace paths plus the source-correlated public receipt."""

    resolved_path: str
    resolved_paths: tuple[str, ...]
    receipt: WorkspaceFileResolutionReceipt


@dataclass(frozen=True, slots=True)
class _InputBinding:
    binding_id: str
    source_step_id: str
    source_tool_name: str
    source_result_path: str
    target_input_path: str
    value_type: str
    required: bool
    max_bytes: int


def has_explicit_input_bindings(request: Mapping[str, Any]) -> bool:
    """Return whether the request declares the new authoritative dataflow seam."""

    return isinstance(request.get("input_bindings"), list) and bool(
        request.get("input_bindings")
    )


def resolve_tool_request_input_bindings(
    request: Mapping[str, Any],
    timeline: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
) -> InputBindingResolution:
    """Resolve all explicit bindings or fail without returning a partial input.

    A source is eligible only when it is the unique successful terminal event
    for the exact Runtime-owned run, plan, step and tool declared by the
    binding.  A binding may mutate values below ``/input`` only.
    """

    raw_bindings = request.get("input_bindings")
    if not isinstance(raw_bindings, list) or not raw_bindings:
        return InputBindingResolution(
            input=dict(request.get("input") or {})
            if isinstance(request.get("input"), Mapping)
            else {},
            receipts=(),
            bound_top_level_fields=frozenset(),
        )
    if len(raw_bindings) > _MAX_BINDINGS:
        raise InputBindingResolutionError("input_binding_count_exceeded")

    clean_run_id = str(run_id or "").strip()
    plan_id = str(request.get("plan_id") or "").strip()
    target_step_id = str(
        request.get("step_id") or request.get("planner_step_id") or ""
    ).strip()
    target_tool_name = str(
        request.get("tool") or request.get("tool_name") or ""
    ).strip()
    if not clean_run_id:
        raise InputBindingResolutionError("input_binding_run_id_required")
    if not plan_id:
        raise InputBindingResolutionError("input_binding_plan_id_required")
    if not target_step_id:
        raise InputBindingResolutionError("input_binding_target_step_required")
    if not target_tool_name:
        raise InputBindingResolutionError("input_binding_target_tool_required")

    dependencies = frozenset(_string_list(request.get("depends_on")))
    parsed: list[_InputBinding] = []
    seen_ids: set[str] = set()
    seen_targets: set[str] = set()
    for raw_binding in raw_bindings:
        binding = _parse_binding(raw_binding)
        if binding.binding_id in seen_ids:
            raise InputBindingResolutionError(
                "input_binding_id_duplicated",
                binding_id=binding.binding_id,
            )
        if binding.target_input_path in seen_targets:
            raise InputBindingResolutionError(
                "input_binding_target_duplicated",
                binding_id=binding.binding_id,
            )
        if binding.source_step_id not in dependencies:
            raise InputBindingResolutionError(
                "input_binding_source_not_dependency",
                binding_id=binding.binding_id,
            )
        seen_ids.add(binding.binding_id)
        seen_targets.add(binding.target_input_path)
        parsed.append(binding)

    original_input = (
        dict(request.get("input"))
        if isinstance(request.get("input"), Mapping)
        else {}
    )
    resolved_input = _copy_json_mapping(original_input)
    receipts: list[InputBindingReceipt] = []
    bound_fields: set[str] = set()
    for binding in parsed:
        source_event = _unique_source_event(
            timeline,
            run_id=clean_run_id,
            plan_id=plan_id,
            binding=binding,
        )
        if source_event is None:
            if binding.required:
                raise InputBindingResolutionError(
                    "input_binding_source_unresolved",
                    binding_id=binding.binding_id,
                )
            continue
        result = source_event.get("result")
        if not isinstance(result, Mapping):
            raise InputBindingResolutionError(
                "input_binding_source_result_invalid",
                binding_id=binding.binding_id,
            )
        value = _json_pointer_value(result, binding.source_result_path)
        if value is _MISSING:
            if binding.required:
                raise InputBindingResolutionError(
                    "input_binding_source_path_missing",
                    binding_id=binding.binding_id,
                )
            continue
        _validate_value(value, binding)
        encoded = _canonical_value_bytes(value)
        target_segments = _target_pointer_segments(binding.target_input_path)
        existing = _nested_value(resolved_input, target_segments[1:])
        if existing is not _MISSING and existing != value:
            raise InputBindingResolutionError(
                "input_binding_target_conflict",
                binding_id=binding.binding_id,
            )
        if existing is _MISSING:
            _set_nested_value(resolved_input, target_segments[1:], _copy_json_value(value))
        bound_fields.add(target_segments[1])
        receipts.append(
            InputBindingReceipt(
                binding_id=binding.binding_id,
                run_id=clean_run_id,
                plan_id=plan_id,
                target_step_id=target_step_id,
                target_tool_name=target_tool_name,
                target_input_path=binding.target_input_path,
                source_step_id=binding.source_step_id,
                source_tool_name=binding.source_tool_name,
                source_tool_call_id=str(source_event.get("tool_call_id") or "").strip(),
                source_result_path=binding.source_result_path,
                value_type=binding.value_type,
                value_bytes=len(encoded),
                value_digest=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
            )
        )

    return InputBindingResolution(
        input=resolved_input,
        receipts=tuple(receipts),
        bound_top_level_fields=frozenset(bound_fields),
    )


def resolve_workspace_file_selection(
    request: Mapping[str, Any],
    timeline: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
) -> WorkspaceFileResolution:
    """Resolve a placeholder path only from its exact planned discovery step.

    Unlike the legacy convenience resolver, this seam requires the immutable
    run/plan/step/call tuple and replays the discovery query before selecting a
    bounded path.  The returned receipt contains no file contents, but carries
    enough provenance for Goal evaluation to recompute the selection later.
    """

    clean_run_id = str(run_id or "").strip()
    plan_id = str(request.get("plan_id") or "").strip()
    target_step_id = str(
        request.get("step_id") or request.get("planner_step_id") or ""
    ).strip()
    target_tool_name = str(
        request.get("tool") or request.get("tool_name") or ""
    ).strip()
    target_tool_call_id = str(request.get("tool_call_id") or "").strip()
    raw_input = request.get("input")
    raw_input = dict(raw_input) if isinstance(raw_input, Mapping) else {}
    requested_path = _workspace_selection_requested_path(raw_input)
    source_tool_name = str(raw_input.get("selection_source") or "").strip()
    dependencies = frozenset(_string_list(request.get("depends_on")))
    if not clean_run_id:
        raise InputBindingResolutionError("workspace_file_resolution_run_id_required")
    if not plan_id:
        raise InputBindingResolutionError("workspace_file_resolution_plan_id_required")
    if not target_step_id:
        raise InputBindingResolutionError("workspace_file_resolution_target_step_required")
    if not target_tool_name:
        raise InputBindingResolutionError("workspace_file_resolution_target_tool_required")
    if not target_tool_call_id:
        raise InputBindingResolutionError("workspace_file_resolution_target_call_required")
    if requested_path not in _SELECTED_WORKSPACE_FILE_PATHS:
        raise InputBindingResolutionError("workspace_file_resolution_placeholder_required")
    if source_tool_name not in _WORKSPACE_FILE_SELECTION_SOURCES:
        raise InputBindingResolutionError("workspace_file_resolution_source_tool_invalid")
    if not dependencies:
        raise InputBindingResolutionError("workspace_file_resolution_dependency_required")

    query = _workspace_selection_query(raw_input)
    matches: list[dict[str, Any]] = []
    for raw_event in timeline:
        if not isinstance(raw_event, Mapping):
            continue
        event = _flatten_event(raw_event)
        if str(event.get("event") or event.get("event_type") or "").strip() != (
            _TERMINAL_SUCCESS_EVENT
        ):
            continue
        if str(event.get("run_id") or "").strip() != clean_run_id:
            continue
        if str(event.get("plan_id") or "").strip() != plan_id:
            continue
        source_step_id = str(
            event.get("step_id") or event.get("planner_step_id") or ""
        ).strip()
        if source_step_id not in dependencies:
            continue
        event_tool = str(
            event.get("tool") or event.get("detail") or event.get("tool_name") or ""
        ).strip()
        if event_tool != source_tool_name:
            continue
        if not str(event.get("tool_call_id") or "").strip():
            continue
        if not _successful_result(event.get("result")):
            continue
        if not _workspace_selection_source_query_matches(event, query):
            continue
        matches.append(event)
    if not matches:
        raise InputBindingResolutionError("workspace_file_resolution_source_unresolved")
    if len(matches) != 1:
        raise InputBindingResolutionError("workspace_file_resolution_source_ambiguous")

    source_event = matches[0]
    result = source_event.get("result")
    if not isinstance(result, Mapping):
        raise InputBindingResolutionError("workspace_file_resolution_source_result_invalid")
    paths = _workspace_selected_paths(
        result,
        source_scope=query["source_scope"],
        pattern=query["pattern"],
        selection=query["selection"],
        multiple=requested_path == _SELECTED_WORKSPACE_FILES_PATH,
    )
    if not paths:
        raise InputBindingResolutionError("workspace_file_resolution_selection_unresolved")
    receipt = WorkspaceFileResolutionReceipt(
        run_id=clean_run_id,
        plan_id=plan_id,
        target_step_id=target_step_id,
        target_tool_name=target_tool_name,
        target_tool_call_id=target_tool_call_id,
        source_step_id=str(
            source_event.get("step_id") or source_event.get("planner_step_id") or ""
        ).strip(),
        source_tool_name=source_tool_name,
        source_tool_call_id=str(source_event.get("tool_call_id") or "").strip(),
        requested_path=requested_path,
        resolved_path=paths[0],
        resolved_paths=tuple(paths),
        source_scope=query["source_scope"],
        pattern=query["pattern"],
        file_type=query["file_type"],
        selection=query["selection"],
    )
    return WorkspaceFileResolution(
        resolved_path=paths[0],
        resolved_paths=tuple(paths),
        receipt=receipt,
    )


def validate_workspace_file_resolution_receipt(
    receipt_payload: Mapping[str, Any],
    target_event: Mapping[str, Any],
    timeline: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
) -> bool:
    """Recompute a workspace selection receipt against source and sink facts."""

    try:
        receipt = _workspace_file_resolution_receipt_from_payload(receipt_payload)
        event = _flatten_event(target_event)
        if str(event.get("event") or event.get("event_type") or "").strip() != (
            _TERMINAL_SUCCESS_EVENT
        ):
            return False
        event_identity = {
            "run_id": str(event.get("run_id") or "").strip(),
            "plan_id": str(event.get("plan_id") or "").strip(),
            "target_step_id": str(
                event.get("step_id") or event.get("planner_step_id") or ""
            ).strip(),
            "target_tool_name": str(
                event.get("tool") or event.get("detail") or event.get("tool_name") or ""
            ).strip(),
            "target_tool_call_id": str(event.get("tool_call_id") or "").strip(),
        }
        if event_identity != {
            "run_id": receipt.run_id,
            "plan_id": receipt.plan_id,
            "target_step_id": receipt.target_step_id,
            "target_tool_name": receipt.target_tool_name,
            "target_tool_call_id": receipt.target_tool_call_id,
        }:
            return False
        if receipt.run_id != str(run_id or "").strip():
            return False
        action_target = event.get("action_target")
        if not isinstance(action_target, Mapping):
            return False
        nested_receipt = action_target.get("workspace_file_resolution")
        if not isinstance(nested_receipt, Mapping):
            return False
        if dict(nested_receipt) != receipt.to_payload():
            return False
        if action_target.get("resolution_required") is not True:
            return False
        if str(action_target.get("expected_path") or "").strip() != receipt.requested_path:
            return False
        if not _workspace_resolution_paths_match_mapping(action_target, receipt):
            return False
        input_preview = event.get("input_preview")
        if not isinstance(input_preview, Mapping):
            return False
        if not _workspace_resolution_paths_match_mapping(input_preview, receipt):
            return False
        result = event.get("result")
        if not isinstance(result, Mapping):
            return False
        if receipt.target_tool_name == "data.analyze" and not (
            _workspace_resolution_paths_match_mapping(result, receipt)
        ):
            return False
        replay_request = {
            "tool": receipt.target_tool_name,
            "tool_call_id": receipt.target_tool_call_id,
            "plan_id": receipt.plan_id,
            "step_id": receipt.target_step_id,
            "depends_on": [receipt.source_step_id],
            "input": {
                "path": receipt.requested_path,
                "selection_source": receipt.source_tool_name,
                "source_scope": receipt.source_scope,
                "pattern": receipt.pattern,
                "source_kind": receipt.file_type,
                "selection": receipt.selection,
            },
        }
        replayed = resolve_workspace_file_selection(
            replay_request,
            timeline,
            run_id=receipt.run_id,
        )
        return replayed.receipt.to_payload() == receipt.to_payload()
    except (InputBindingResolutionError, TypeError, ValueError):
        return False


def context_binding_unresolved_result(
    error: InputBindingResolutionError,
) -> dict[str, Any]:
    """Return a bounded failure that enters the normal Runtime replan path."""

    payload: dict[str, Any] = {
        "ok": False,
        "status": "blocked",
        "error": "context_binding_unresolved",
        "reason": error.reason,
        "retryable": True,
        "needs_replan": True,
        "recovery_hints": ["context_binding_unresolved"],
        "summary": "A required context value could not be correlated to its source step.",
    }
    if error.binding_id:
        payload["binding_id"] = error.binding_id
    return payload


def _workspace_selection_requested_path(raw_input: Mapping[str, Any]) -> str:
    for key in ("path", "target_path", "file_path"):
        value = str(raw_input.get(key) or "").strip()
        if value in _SELECTED_WORKSPACE_FILE_PATHS:
            return value
    return ""


def _workspace_selection_query(raw_input: Mapping[str, Any]) -> dict[str, str]:
    source_scope = _safe_workspace_path(
        raw_input.get("source_scope")
        or raw_input.get("source_path")
        or raw_input.get("directory")
        or "."
    )
    file_type = str(
        raw_input.get("file_type") or raw_input.get("source_kind") or ""
    ).strip().casefold()
    if file_type == "unknown":
        file_type = ""
    return {
        "source_scope": source_scope,
        "pattern": str(raw_input.get("pattern") or "").strip(),
        "file_type": file_type,
        "selection": str(
            raw_input.get("selection") or raw_input.get("selection_hint") or ""
        ).strip().casefold(),
    }


def _workspace_selection_source_query_matches(
    event: Mapping[str, Any],
    query: Mapping[str, str],
) -> bool:
    input_preview = event.get("input_preview")
    input_preview = input_preview if isinstance(input_preview, Mapping) else {}
    result = event.get("result")
    result = result if isinstance(result, Mapping) else {}
    try:
        input_scope = _safe_workspace_path(input_preview.get("path") or ".")
        result_scope = _safe_workspace_path(result.get("path") or input_scope)
    except InputBindingResolutionError:
        return False
    source_file_type = str(input_preview.get("file_type") or "").strip().casefold()
    source_selection = str(input_preview.get("selection") or "").strip().casefold()
    return bool(
        input_scope == query["source_scope"]
        and result_scope == query["source_scope"]
        and str(input_preview.get("pattern") or "").strip() == query["pattern"]
        and source_file_type == query["file_type"]
        and source_selection == query["selection"]
    )


def _workspace_selected_paths(
    result: Mapping[str, Any],
    *,
    source_scope: str,
    pattern: str,
    selection: str,
    multiple: bool,
) -> list[str]:
    entries: list[Mapping[str, Any]] = []
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    for container in (result, data):
        for key in ("entries", "files", "matches", "results"):
            values = container.get(key)
            if isinstance(values, list):
                entries.extend(item for item in values if isinstance(item, Mapping))
    files: list[tuple[Mapping[str, Any], str]] = []
    unsafe_entry_seen = False
    for entry in entries:
        if str(entry.get("type") or entry.get("kind") or "file").strip().casefold() in {
            "dir",
            "directory",
        }:
            continue
        try:
            path = _workspace_entry_path(entry, source_scope=source_scope)
        except InputBindingResolutionError:
            unsafe_entry_seen = True
            continue
        if pattern and not _workspace_pattern_matches(path, pattern):
            continue
        files.append((entry, path))
    if unsafe_entry_seen and not files:
        raise InputBindingResolutionError("workspace_file_resolution_path_unsafe")
    if not files:
        return []
    if multiple:
        if not _selection_requests_multiple(selection):
            return []
        return list(dict.fromkeys(path for _entry, path in files))
    if _selection_requests_latest(selection):
        ranked: list[tuple[float, str]] = []
        for entry, path in files:
            modified = _workspace_entry_mtime(entry)
            if modified is not None:
                ranked.append((modified, path))
        if not ranked:
            return []
        latest = max(value for value, _path in ranked)
        winners = [path for value, path in ranked if value == latest]
        return winners if len(winners) == 1 else []
    if any(token in selection for token in ("最后", "last")):
        return [files[-1][1]]
    if any(token in selection for token in ("第一个", "第1个", "first", "top")):
        return [files[0][1]]
    return [files[0][1]] if len(files) == 1 else []


def _workspace_entry_path(
    entry: Mapping[str, Any],
    *,
    source_scope: str,
) -> str:
    explicit = ""
    for key in ("path", "relative_path", "relpath", "display_path"):
        explicit = str(entry.get(key) or "").strip()
        if explicit:
            break
    if explicit:
        path = _safe_workspace_path(explicit)
        if source_scope != "." and not _workspace_path_within(path, source_scope):
            if "/" not in path:
                path = _safe_workspace_path(f"{source_scope}/{path}")
            else:
                raise InputBindingResolutionError("workspace_file_resolution_path_unsafe")
    else:
        name = str(entry.get("name") or "").strip()
        if not name or "/" in name or "\\" in name:
            raise InputBindingResolutionError("workspace_file_resolution_path_unsafe")
        path = _safe_workspace_path(
            name if source_scope == "." else f"{source_scope}/{name}"
        )
    if not _workspace_path_within(path, source_scope):
        raise InputBindingResolutionError("workspace_file_resolution_path_unsafe")
    return path


def _safe_workspace_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    raw = raw.rstrip("/") or "."
    path = PurePosixPath(raw)
    if (
        not raw
        or raw.startswith(("/", "~"))
        or re.search(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw)
        or any(part in {"", ".", ".."} for part in path.parts if raw != ".")
    ):
        raise InputBindingResolutionError("workspace_file_resolution_path_unsafe")
    return path.as_posix()


def _workspace_path_within(path: str, scope: str) -> bool:
    if scope == ".":
        return path != "."
    return bool(path == scope or path.startswith(f"{scope.rstrip('/')}/"))


def _workspace_pattern_matches(path: str, pattern: str) -> bool:
    name = PurePosixPath(path).name.casefold()
    patterns = _expand_workspace_patterns(pattern)
    return any(fnmatch.fnmatchcase(name, candidate.casefold()) for candidate in patterns)


def _expand_workspace_patterns(pattern: str) -> list[str]:
    value = str(pattern or "").strip()
    if not value:
        return ["*"]
    brace = re.fullmatch(r"(?P<prefix>.*)\{(?P<items>[^{}]+)\}(?P<suffix>.*)", value)
    if brace is None:
        return [value]
    return [
        f"{brace.group('prefix')}{item.strip()}{brace.group('suffix')}"
        for item in brace.group("items").split(",")
        if item.strip()
    ]


def _workspace_entry_mtime(entry: Mapping[str, Any]) -> float | None:
    for key in ("mtime", "modified_at", "last_modified", "mtime_ns"):
        value = entry.get(key)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed
    return None


def _selection_requests_latest(selection: str) -> bool:
    return any(
        token in selection
        for token in ("最近", "最新", "latest", "newest", "recent")
    )


def _selection_requests_multiple(selection: str) -> bool:
    return any(
        token in selection
        for token in (
            "所有",
            "全部",
            "多个",
            "多份",
            "all",
            "every",
            "each",
            "multiple",
            "several",
            "比较",
            "对比",
            "compare",
        )
    )


def _workspace_file_resolution_receipt_from_payload(
    payload: Mapping[str, Any],
) -> WorkspaceFileResolutionReceipt:
    if payload.get("version") != _WORKSPACE_FILE_RESOLUTION_VERSION:
        raise ValueError("workspace resolution receipt version mismatch")
    if str(payload.get("resolution_kind") or "").strip() != (
        _WORKSPACE_FILE_RESOLUTION_KIND
    ):
        raise ValueError("workspace resolution receipt kind mismatch")
    text_fields = {
        key: str(payload.get(key) or "").strip()
        for key in (
            "run_id",
            "plan_id",
            "target_step_id",
            "target_tool_name",
            "target_tool_call_id",
            "source_step_id",
            "source_tool_name",
            "source_tool_call_id",
            "requested_path",
            "resolved_path",
            "source_scope",
            "pattern",
            "file_type",
            "selection",
        )
    }
    required = (
        "run_id",
        "plan_id",
        "target_step_id",
        "target_tool_name",
        "target_tool_call_id",
        "source_step_id",
        "source_tool_name",
        "source_tool_call_id",
        "requested_path",
        "resolved_path",
        "source_scope",
    )
    if any(not text_fields[key] for key in required):
        raise ValueError("workspace resolution receipt identity missing")
    raw_paths = payload.get("resolved_paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ValueError("workspace resolution receipt paths missing")
    resolved_paths = tuple(_safe_workspace_path(item) for item in raw_paths)
    if text_fields["resolved_path"] != resolved_paths[0]:
        raise ValueError("workspace resolution receipt primary path mismatch")
    return WorkspaceFileResolutionReceipt(
        run_id=text_fields["run_id"],
        plan_id=text_fields["plan_id"],
        target_step_id=text_fields["target_step_id"],
        target_tool_name=text_fields["target_tool_name"],
        target_tool_call_id=text_fields["target_tool_call_id"],
        source_step_id=text_fields["source_step_id"],
        source_tool_name=text_fields["source_tool_name"],
        source_tool_call_id=text_fields["source_tool_call_id"],
        requested_path=text_fields["requested_path"],
        resolved_path=text_fields["resolved_path"],
        resolved_paths=resolved_paths,
        source_scope=_safe_workspace_path(text_fields["source_scope"]),
        pattern=text_fields["pattern"],
        file_type=text_fields["file_type"],
        selection=text_fields["selection"],
    )


def _workspace_resolution_paths_match_mapping(
    mapping: Mapping[str, Any],
    receipt: WorkspaceFileResolutionReceipt,
) -> bool:
    if len(receipt.resolved_paths) > 1:
        values = mapping.get("paths")
        return bool(
            isinstance(values, list)
            and tuple(str(value or "").strip() for value in values)
            == receipt.resolved_paths
        )
    return str(mapping.get("path") or "").strip() == receipt.resolved_path


def _parse_binding(value: Any) -> _InputBinding:
    if not isinstance(value, Mapping):
        raise InputBindingResolutionError("input_binding_must_be_mapping")
    binding_id = str(value.get("binding_id") or "").strip()
    if not binding_id or len(binding_id) > 160:
        raise InputBindingResolutionError("input_binding_id_invalid")
    source_step_id = str(value.get("source_step_id") or "").strip()
    source_tool_name = str(value.get("source_tool_name") or "").strip()
    source_result_path = str(value.get("source_result_path") or "").strip()
    target_input_path = str(value.get("target_input_path") or "").strip()
    value_type = str(value.get("value_type") or "string").strip()
    if not source_step_id:
        raise InputBindingResolutionError(
            "input_binding_source_step_required", binding_id=binding_id
        )
    if not source_tool_name:
        raise InputBindingResolutionError(
            "input_binding_source_tool_required", binding_id=binding_id
        )
    _source_pointer_segments(source_result_path, binding_id=binding_id)
    _target_pointer_segments(target_input_path, binding_id=binding_id)
    if value_type not in _SUPPORTED_VALUE_TYPES:
        raise InputBindingResolutionError(
            "input_binding_value_type_invalid", binding_id=binding_id
        )
    raw_max_bytes = value.get("max_bytes", _DEFAULT_MAX_BYTES)
    if isinstance(raw_max_bytes, bool):
        max_bytes = 0
    else:
        try:
            max_bytes = int(raw_max_bytes)
        except (TypeError, ValueError):
            max_bytes = 0
    if not 1 <= max_bytes <= _MAX_VALUE_BYTES:
        raise InputBindingResolutionError(
            "input_binding_max_bytes_invalid", binding_id=binding_id
        )
    return _InputBinding(
        binding_id=binding_id,
        source_step_id=source_step_id,
        source_tool_name=source_tool_name,
        source_result_path=source_result_path,
        target_input_path=target_input_path,
        value_type=value_type,
        required=value.get("required") is not False,
        max_bytes=max_bytes,
    )


def _unique_source_event(
    timeline: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    plan_id: str,
    binding: _InputBinding,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for raw_event in timeline:
        if not isinstance(raw_event, Mapping):
            continue
        event = _flatten_event(raw_event)
        event_type = str(event.get("event") or event.get("event_type") or "").strip()
        if event_type != _TERMINAL_SUCCESS_EVENT:
            continue
        if str(event.get("run_id") or "").strip() != run_id:
            continue
        if str(event.get("plan_id") or "").strip() != plan_id:
            continue
        step_id = str(
            event.get("step_id") or event.get("planner_step_id") or ""
        ).strip()
        if step_id != binding.source_step_id:
            continue
        tool_name = str(
            event.get("tool") or event.get("detail") or event.get("tool_name") or ""
        ).strip()
        if tool_name != binding.source_tool_name:
            continue
        tool_call_id = str(event.get("tool_call_id") or "").strip()
        result = event.get("result")
        if not tool_call_id or not _successful_result(result):
            continue
        matches.append(event)
    if not matches:
        return None
    if len(matches) != 1:
        raise InputBindingResolutionError(
            "input_binding_source_ambiguous",
            binding_id=binding.binding_id,
        )
    return matches[0]


def _successful_result(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("ok") is True
        and value.get("approval_required") is not True
        and value.get("verification_failed") is not True
        and str(value.get("status") or "").strip().casefold()
        not in {"blocked", "failed", "partial", "skipped"}
    )


def _flatten_event(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    # Persisted Runtime events keep correlated tool identity in ``payload``.
    # The public wrapper may carry projection fields, but it must never
    # override the authoritative run/plan/step/tool/result tuple.
    return {**dict(event), **dict(payload)} if isinstance(payload, Mapping) else dict(event)


def _source_pointer_segments(pointer: str, *, binding_id: str = "") -> tuple[str, ...]:
    segments = _pointer_segments(pointer, binding_id=binding_id)
    if not segments:
        raise InputBindingResolutionError(
            "input_binding_source_path_invalid", binding_id=binding_id
        )
    return segments


def _target_pointer_segments(pointer: str, *, binding_id: str = "") -> tuple[str, ...]:
    segments = _pointer_segments(pointer, binding_id=binding_id)
    if len(segments) < 2 or segments[0] != "input":
        raise InputBindingResolutionError(
            "input_binding_target_path_invalid", binding_id=binding_id
        )
    if any(not _TARGET_SEGMENT.fullmatch(segment) for segment in segments[1:]):
        raise InputBindingResolutionError(
            "input_binding_target_path_invalid", binding_id=binding_id
        )
    return segments


def _pointer_segments(pointer: str, *, binding_id: str) -> tuple[str, ...]:
    if (
        not pointer
        or len(pointer) > _MAX_POINTER_LENGTH
        or not pointer.startswith("/")
        or pointer == "/"
    ):
        raise InputBindingResolutionError(
            "input_binding_json_pointer_invalid", binding_id=binding_id
        )
    raw_segments = pointer[1:].split("/")
    if not raw_segments or len(raw_segments) > _MAX_POINTER_SEGMENTS:
        raise InputBindingResolutionError(
            "input_binding_json_pointer_invalid", binding_id=binding_id
        )
    segments: list[str] = []
    for raw_segment in raw_segments:
        if not raw_segment or re.search(r"~(?:[^01]|$)", raw_segment):
            raise InputBindingResolutionError(
                "input_binding_json_pointer_invalid", binding_id=binding_id
            )
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if not segment or segment.startswith("_") or "\x00" in segment:
            raise InputBindingResolutionError(
                "input_binding_json_pointer_invalid", binding_id=binding_id
            )
        segments.append(segment)
    return tuple(segments)


def _json_pointer_value(root: Any, pointer: str) -> Any:
    current = root
    for segment in _source_pointer_segments(pointer):
        if isinstance(current, Mapping):
            if segment not in current:
                return _MISSING
            current = current[segment]
            continue
        if isinstance(current, list):
            if not segment.isdigit():
                return _MISSING
            index = int(segment)
            if index < 0 or index >= len(current):
                return _MISSING
            current = current[index]
            continue
        return _MISSING
    return current


def _validate_value(value: Any, binding: _InputBinding) -> None:
    valid = False
    if binding.value_type == "string":
        valid = isinstance(value, str)
    elif binding.value_type == "string_list":
        valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
    elif binding.value_type == "number":
        valid = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        )
    elif binding.value_type == "bool":
        valid = isinstance(value, bool)
    if not valid:
        raise InputBindingResolutionError(
            "input_binding_value_type_mismatch", binding_id=binding.binding_id
        )
    encoded = _canonical_value_bytes(value)
    if len(encoded) > binding.max_bytes:
        raise InputBindingResolutionError(
            "input_binding_value_too_large", binding_id=binding.binding_id
        )


def _canonical_value_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _nested_value(root: Mapping[str, Any], segments: Sequence[str]) -> Any:
    current: Any = root
    for segment in segments:
        if not isinstance(current, Mapping) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _set_nested_value(root: dict[str, Any], segments: Sequence[str], value: Any) -> None:
    current = root
    for segment in segments[:-1]:
        existing = current.get(segment, _MISSING)
        if existing is _MISSING:
            nested: dict[str, Any] = {}
            current[segment] = nested
            current = nested
            continue
        if not isinstance(existing, dict):
            raise InputBindingResolutionError("input_binding_target_conflict")
        current = existing
    current[segments[-1]] = value


def _copy_json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _copy_json_value(item) for key, item in value.items()}


def _copy_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _copy_json_mapping(value)
    if isinstance(value, list):
        return [_copy_json_value(item) for item in value]
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return [
        clean
        for item in value
        if (clean := str(item or "").strip())
    ]


__all__ = [
    "InputBindingReceipt",
    "InputBindingResolution",
    "InputBindingResolutionError",
    "WorkspaceFileResolution",
    "WorkspaceFileResolutionReceipt",
    "context_binding_unresolved_result",
    "has_explicit_input_bindings",
    "resolve_tool_request_input_bindings",
    "resolve_workspace_file_selection",
    "validate_workspace_file_resolution_receipt",
]
