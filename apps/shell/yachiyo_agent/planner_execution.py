"""Convert runtime planner decisions into existing tool request payloads."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .runtime_planner import RuntimePlanner


def planner_desktop_tool_requests(
    prompt: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=allowed,
        metadata=metadata,
    )
    if decision.selected_intent.kind != "desktop_operation":
        return []

    requests: list[dict[str, Any]] = []
    app_name = str(decision.selected_intent.inputs.get("app_name_hint") or "").strip()
    if app_name and "app.open" in allowed:
        requests.append(_request("app.open", {"app_name": app_name}))

    click_target = _click_target_hint(prompt)
    if click_target and "desktop.click_ui_element" in allowed:
        requests.append(
            _request(
                "desktop.click_ui_element",
                {
                    "target": click_target["target"],
                    "role_filter": click_target["role_filter"],
                    "limit": 80,
                    "click_count": click_target["click_count"],
                },
            )
        )

    return requests


def _request(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol": "json_fallback",
        "tool": tool,
        "input": payload,
        "source": "runtime_planner",
        "planning_reason": "planner_fallback_desktop_operation",
    }


def _click_target_hint(prompt: str) -> dict[str, Any] | None:
    text = _clean(prompt)
    patterns = (
        r"(?:双击|点击|点一下|点按|单击|按一下|按)\s*(?P<target>[^。！？!?，,]+)",
        r"(?:double\s+click|click|press|tap)\s+(?:the\s+)?(?P<target_en>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_target = match.groupdict().get("target") or match.groupdict().get("target_en") or ""
        target = _clean_target(raw_target)
        if not target:
            continue
        return {
            "target": target,
            "role_filter": _role_filter(raw_target),
            "click_count": 2 if _contains_any(match.group(0), ("双击", "double click")) else 1,
        }
    return None


def _clean_target(value: str) -> str:
    target = _clean(value)
    target = re.split(
        r"(?:然后|并且|并|再|接着|之后|后|and\s+then|then|and)",
        target,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    target = re.sub(
        r"\s*(?:按钮|控件|元素|菜单项|菜单|复选框|button|control|element|menu item|menu|checkbox)$",
        "",
        target,
        flags=re.IGNORECASE,
    )
    return target.strip(" .，,。")


def _role_filter(value: str) -> str:
    lowered = value.lower()
    if _contains_any(lowered, ("按钮", "button")):
        return "button"
    if _contains_any(lowered, ("菜单", "menu")):
        return "menu"
    if _contains_any(lowered, ("复选框", "checkbox")):
        return "checkbox"
    return ""


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    lowered = str(text or "").lower()
    return any(str(needle).lower() in lowered for needle in needles)
