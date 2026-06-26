"""Planner-first direct tool selection for lightweight Chat entrypoints."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .planner_execution import planner_direct_decision_and_tool_requests

LegacyToolRequestProvider = Callable[[str, list[str]], list[dict[str, Any]]]
LegacyToolRequestPostprocess = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


def planner_first_direct_decision_and_tool_requests(
    prompt: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
    legacy_tool_requests: LegacyToolRequestProvider | None = None,
    legacy_postprocess: LegacyToolRequestPostprocess | None = None,
) -> tuple[Any | None, list[dict[str, Any]]]:
    allowed = [str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()]
    decision, planner_requests = planner_direct_decision_and_tool_requests(
        prompt,
        allowed,
        metadata=metadata,
    )
    if _should_consult_legacy(planner_requests):
        legacy_requests = _legacy_requests(
            prompt,
            allowed,
            legacy_tool_requests=legacy_tool_requests,
            legacy_postprocess=legacy_postprocess,
        )
        if legacy_requests and not _same_tool_requests(planner_requests, legacy_requests):
            return None, legacy_requests
    if planner_requests:
        return decision, planner_requests
    return None, _legacy_requests(
        prompt,
        allowed,
        legacy_tool_requests=legacy_tool_requests,
        legacy_postprocess=legacy_postprocess,
    )


def _should_consult_legacy(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return True
    tools = [str(request.get("tool") or "").strip() for request in requests]
    if any(bool(request.get("continue_to_model")) for request in requests):
        return True
    if any(tool == "desktop.submit_foreground" for tool in tools):
        return True
    if any(tool in {"desktop.ui_elements", "screen.capture"} for tool in tools):
        return True
    if any(tool.startswith("system.") for tool in tools):
        return True
    if any(tool.startswith("clipboard.") for tool in tools):
        return True
    if any(tool in {"media.apple_music_play", "media.system_control"} for tool in tools):
        return True
    if len(requests) != 1:
        return False
    tool_name = tools[0]
    return tool_name.startswith(("app.", "desktop.", "browser."))


def _legacy_requests(
    prompt: str,
    allowed_tools: list[str],
    *,
    legacy_tool_requests: LegacyToolRequestProvider | None,
    legacy_postprocess: LegacyToolRequestPostprocess | None,
) -> list[dict[str, Any]]:
    if legacy_tool_requests is None:
        return []
    try:
        requests = legacy_tool_requests(str(prompt or ""), allowed_tools)
    except Exception:
        return []
    cleaned = [request for request in requests if isinstance(request, dict)]
    if legacy_postprocess is not None:
        try:
            cleaned = legacy_postprocess(cleaned)
        except Exception:
            return cleaned
    return cleaned


def _same_tool_requests(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> bool:
    return _request_signature(left) == _request_signature(right)


def _request_signature(requests: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    signature: list[tuple[str, dict[str, Any]]] = []
    for request in requests:
        tool_name = str(request.get("tool") or "").strip()
        if not tool_name:
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        signature.append((tool_name, dict(payload)))
    return signature
