"""Public approval snapshot helpers shared by runtime projections."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.events import tool_input_preview
from apps.shell.agent.tools.policy import (
    HIGH_RISK_AGENT_TOOLS,
    HIGH_RISK_DESKTOP_TOOL_NAMES,
    MEDIUM_RISK_BROWSER_TOOL_NAMES,
    MEDIUM_RISK_DESKTOP_TOOL_NAMES,
)

MEDIUM_RISK_AGENT_TOOLS = {
    *MEDIUM_RISK_DESKTOP_TOOL_NAMES,
    *MEDIUM_RISK_BROWSER_TOOL_NAMES,
}
HIGH_RISK_APPROVAL_TOOLS = {
    *HIGH_RISK_AGENT_TOOLS,
    *HIGH_RISK_DESKTOP_TOOL_NAMES,
}


def approval_input_preview(value: Any, *, limit: int = 1200) -> Any:
    return tool_input_preview(value, limit=limit)


def public_pending_approval(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    if not raw:
        return {}
    input_preview = raw.get("input_preview")
    if input_preview:
        public_input_preview = approval_input_preview(input_preview)
    else:
        public_input_preview = approval_input_preview(raw.get("input") or {})
    snapshot = {
        "approval_id": str(raw.get("approval_id") or ""),
        "tool": str(raw.get("tool") or ""),
        "input_preview": public_input_preview,
        "requested_at": str(raw.get("requested_at") or ""),
    }
    tool_name = str(snapshot["tool"] or "").strip()
    risk_level = _approval_risk_level(raw, tool_name)
    policy_reason = _approval_policy_reason(
        raw,
        tool_name=tool_name,
        risk_level=risk_level,
        public_input_preview=public_input_preview,
    )
    for key in (
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
        "group_id",
        "group_run_id",
        "run_group_id",
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
    ):
        text = str(raw.get(key) or "").strip()
        if text:
            snapshot[key] = text
    if risk_level:
        snapshot["risk_level"] = risk_level
    if policy_reason:
        snapshot["policy_reason"] = policy_reason
    return snapshot


def _approval_risk_level(raw: dict[str, Any], tool_name: str) -> str:
    direct = str(raw.get("risk_level") or "").strip().lower()
    if direct in {"low", "medium", "high"}:
        return direct
    if tool_name in HIGH_RISK_APPROVAL_TOOLS:
        return "high"
    if tool_name in MEDIUM_RISK_AGENT_TOOLS:
        return "medium"
    return ""


def _approval_policy_reason(
    raw: dict[str, Any],
    *,
    tool_name: str,
    risk_level: str,
    public_input_preview: Any,
) -> str:
    direct = str(raw.get("policy_reason") or "").strip()
    if direct and direct != "当前工具策略要求人工确认后再执行。":
        return direct
    criteria = _workflow_approval_criteria(raw, public_input_preview)
    if tool_name == "workflow.approval":
        if criteria:
            return f"Workflow 审批节点要求人工确认：{criteria}"
        return "Workflow 审批节点需要人工确认后才会继续。"
    if tool_name == "terminal.run":
        return "terminal.run 可执行本地命令，按工具策略必须人工确认。"
    if tool_name == "workspace.write_patch":
        return "workspace.write_patch 会修改工作区文件，按工具策略必须人工确认。"
    if risk_level == "medium":
        foreground_reason = _medium_risk_foreground_reason(tool_name, public_input_preview)
        if foreground_reason:
            return foreground_reason
        if tool_name in MEDIUM_RISK_DESKTOP_TOOL_NAMES:
            return "前台输入、点击或快捷键会操作当前桌面窗口，按工具策略需要人工确认。"
        if tool_name in MEDIUM_RISK_BROWSER_TOOL_NAMES:
            return "网页点击或输入会操作当前浏览器页面，按工具策略需要人工确认。"
        return "中风险工具调用按当前工具策略需要人工确认。"
    if risk_level == "high":
        high_risk_foreground_reason = _high_risk_foreground_reason(tool_name, public_input_preview)
        if high_risk_foreground_reason:
            return high_risk_foreground_reason
        return "高风险工具调用按当前工具策略必须人工确认。"
    return ""


def _workflow_approval_criteria(raw: dict[str, Any], public_input_preview: Any) -> str:
    criteria = str(raw.get("workflow_node_approval_criteria") or "").strip()
    if criteria:
        return criteria
    if isinstance(public_input_preview, dict):
        return str(public_input_preview.get("criteria") or "").strip()
    return ""


def _medium_risk_foreground_reason(tool_name: str, public_input_preview: Any) -> str:
    record = public_input_preview if isinstance(public_input_preview, dict) else {}
    if tool_name == "app.quit":
        app_name = _preview_value(record, "app_name")
        if app_name:
            return f"将退出应用 {app_name}，可能导致未保存内容丢失，按工具策略需要人工确认。"
        return "将退出本地应用，可能导致未保存内容丢失，按工具策略需要人工确认。"
    if tool_name == "desktop.close_window":
        return "将关闭当前前台窗口，可能影响未保存内容，按工具策略需要人工确认。"
    if tool_name == "desktop.quit_app":
        return "将退出当前前台应用，可能导致未保存内容丢失，按工具策略需要人工确认。"
    if tool_name == "desktop.hotkey":
        hotkey = _hotkey_preview(record)
        if hotkey:
            return f"将向当前前台窗口发送快捷键 {hotkey}，按工具策略需要人工确认。"
        return "将向当前前台窗口发送快捷键，按工具策略需要人工确认。"
    if tool_name in {"app.open_and_hotkey", "app.focus_and_hotkey"}:
        app_name = _preview_value(record, "app_name")
        hotkey = _hotkey_preview(record)
        if app_name and hotkey:
            return f"将切换到应用 {app_name} 并发送快捷键 {hotkey}，按工具策略需要人工确认。"
        if app_name:
            return f"将切换到应用 {app_name} 并发送快捷键，按工具策略需要人工确认。"
        if hotkey:
            return f"将切换到目标应用并发送快捷键 {hotkey}，按工具策略需要人工确认。"
        return "将切换到目标应用并发送快捷键，按工具策略需要人工确认。"
    if tool_name == "desktop.type_text":
        text = _preview_value(record, "text")
        if text:
            return f"将向当前前台窗口输入文字（{len(text)} 个字符），按工具策略需要人工确认。"
        return "将向当前前台窗口输入文字，按工具策略需要人工确认。"
    if tool_name == "desktop.click":
        click = _click_preview(record)
        if click:
            return f"将{click}当前前台窗口，按工具策略需要人工确认。"
        return "将点击当前前台窗口，按工具策略需要人工确认。"
    if tool_name == "desktop.click_ui_element":
        target = _preview_value(record, "target")
        if target:
            return f"将点击当前前台界面中匹配“{target}”的控件，按工具策略需要人工确认。"
        return "将点击当前前台界面中匹配名称的控件，按工具策略需要人工确认。"
    if tool_name in {"app.open_and_click_ui_element", "app.focus_and_click_ui_element"}:
        app_name = _preview_value(record, "app_name")
        target = _preview_value(record, "target")
        action = "打开" if tool_name.startswith("app.open") else "切到"
        if app_name and target:
            return f"将{action} {app_name} 并点击其中匹配“{target}”的控件，按工具策略需要人工确认。"
        if app_name:
            return f"将{action} {app_name} 并点击其中匹配名称的控件，按工具策略需要人工确认。"
        if target:
            return f"将点击应用中匹配“{target}”的控件，按工具策略需要人工确认。"
        return "将点击应用中匹配名称的控件，按工具策略需要人工确认。"
    if tool_name in {"app.open_and_type_into_ui_element", "app.focus_and_type_into_ui_element"}:
        app_name = _preview_value(record, "app_name")
        target = _preview_value(record, "target")
        text = _preview_value(record, "text")
        action = "打开" if tool_name.startswith("app.open") else "切到"
        count_text = f"并输入文字（{len(text)} 个字符）" if text else "并输入文字"
        if app_name and target:
            return f"将{action} {app_name} 并点击其中匹配“{target}”的输入控件{count_text}，按工具策略需要人工确认。"
        if app_name:
            return f"将{action} {app_name} 并点击其中匹配名称的输入控件{count_text}，按工具策略需要人工确认。"
        if target:
            return f"将点击应用中匹配“{target}”的输入控件{count_text}，按工具策略需要人工确认。"
        return f"将点击应用中匹配名称的输入控件{count_text}，按工具策略需要人工确认。"
    if tool_name == "desktop.type_into_ui_element":
        target = _preview_value(record, "target")
        text = _preview_value(record, "text")
        if target and text:
            return f"将点击当前前台界面中匹配“{target}”的输入控件并输入文字（{len(text)} 个字符），按工具策略需要人工确认。"
        if target:
            return f"将点击当前前台界面中匹配“{target}”的输入控件并输入文字，按工具策略需要人工确认。"
        return "将点击当前前台界面中匹配名称的输入控件并输入文字，按工具策略需要人工确认。"
    if tool_name == "browser.click":
        selector = _preview_value(record, "selector")
        if selector:
            point = _point_selector_preview(selector)
            if point:
                return f"将点击当前浏览器页面位置 {point}，按工具策略需要人工确认。"
            return f"将点击当前浏览器页面中的选择器 {selector}，按工具策略需要人工确认。"
        click = _click_preview(record, x_key="fallback_x", y_key="fallback_y")
        if click:
            return f"将通过桌面回退{click}当前浏览器页面，按工具策略需要人工确认。"
        return "将点击当前浏览器页面，按工具策略需要人工确认。"
    if tool_name == "browser.type_text":
        selector = _preview_value(record, "selector")
        text = _preview_value(record, "text")
        if selector and text:
            point = _point_selector_preview(selector)
            if point:
                return f"将向当前浏览器页面位置 {point} 输入文字（{len(text)} 个字符），按工具策略需要人工确认。"
            return f"将向当前浏览器页面选择器 {selector} 输入文字（{len(text)} 个字符），按工具策略需要人工确认。"
        if selector:
            point = _point_selector_preview(selector)
            if point:
                return f"将向当前浏览器页面位置 {point} 输入文字，按工具策略需要人工确认。"
            return f"将向当前浏览器页面选择器 {selector} 输入文字，按工具策略需要人工确认。"
        return "将向当前浏览器页面输入文字，按工具策略需要人工确认。"
    return ""


def _high_risk_foreground_reason(tool_name: str, public_input_preview: Any) -> str:
    record = public_input_preview if isinstance(public_input_preview, dict) else {}
    if tool_name != "desktop.submit_foreground":
        return ""
    action = _preview_value(record, "action")
    if action == "send":
        return "将发送当前前台输入框中的内容，可能向外部对象发出消息，按工具策略必须人工确认。"
    if action == "submit":
        return "将提交当前前台表单或输入内容，可能触发外部系统操作，按工具策略必须人工确认。"
    if action == "confirm":
        return "将确认当前前台操作，可能触发应用内状态变化，按工具策略必须人工确认。"
    return "将发送、提交或确认当前前台内容，按工具策略必须人工确认。"


def _preview_value(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            return _number_preview(value)
        text = str(value).strip()
        if text:
            return text
    return ""


def _number_preview(value: int | float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(value)


def _point_selector_preview(selector: str) -> str:
    clean = str(selector or "").strip()
    if not clean.startswith("point="):
        return ""
    parts = [part.strip() for part in clean.removeprefix("point=").split(",")]
    if len(parts) != 2 or not all(parts):
        return ""
    try:
        x = _number_preview(float(parts[0]))
        y = _number_preview(float(parts[1]))
    except ValueError:
        return ""
    return f"{x}, {y}"


def _click_preview(
    record: dict[str, Any],
    *,
    x_key: str = "x",
    y_key: str = "y",
) -> str:
    x = _preview_value(record, x_key)
    y = _preview_value(record, y_key)
    if not x or not y:
        return ""
    click_count = _click_count(record.get("click_count"))
    if click_count == 2:
        action = "双击"
    elif click_count > 2:
        action = f"点击 x{click_count}"
    else:
        action = "点击"
    return f"{action}坐标 {x}, {y} 处的"


def _click_count(value: Any) -> int:
    if isinstance(value, bool) or value in (None, ""):
        return 1
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(3, count))


def _hotkey_preview(record: dict[str, Any]) -> str:
    modifiers = record.get("modifiers")
    parts = []
    if isinstance(modifiers, list):
        parts.extend(_hotkey_part_label(item) for item in modifiers)
    parts.append(_hotkey_part_label(record.get("key")))
    return "+".join(part for part in parts if part)


def _hotkey_part_label(value: Any) -> str:
    part = str(value or "").strip()
    if not part:
        return ""
    normalized = part.lower()
    if normalized in {"cmd", "command"}:
        return "Command"
    if normalized in {"ctrl", "control"}:
        return "Control"
    if normalized in {"alt", "option"}:
        return "Option"
    if normalized == "shift":
        return "Shift"
    if normalized == "return":
        return "Return"
    if normalized == "escape":
        return "Escape"
    if normalized == "space":
        return "Space"
    if normalized == "tab":
        return "Tab"
    if len(normalized) == 1:
        return normalized.upper()
    return part


class ApprovalSnapshotBuilder:
    """Builds public ApprovalCard-style snapshots from private pending approvals."""

    def public_pending_approval(self, value: Any) -> dict[str, Any]:
        return public_pending_approval(value)
