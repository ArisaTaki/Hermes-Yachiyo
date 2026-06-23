"""Public approval snapshot helpers shared by runtime projections."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.events import tool_input_preview
from apps.shell.agent.tools.policy import (
    HIGH_RISK_AGENT_TOOLS,
    MEDIUM_RISK_BROWSER_TOOL_NAMES,
    MEDIUM_RISK_DESKTOP_TOOL_NAMES,
)

MEDIUM_RISK_AGENT_TOOLS = {
    *MEDIUM_RISK_DESKTOP_TOOL_NAMES,
    *MEDIUM_RISK_BROWSER_TOOL_NAMES,
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
    if tool_name in HIGH_RISK_AGENT_TOOLS:
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
    if direct:
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
        if tool_name in MEDIUM_RISK_DESKTOP_TOOL_NAMES:
            return "前台输入、点击或快捷键会操作当前桌面窗口，按工具策略需要人工确认。"
        if tool_name in MEDIUM_RISK_BROWSER_TOOL_NAMES:
            return "网页点击或输入会操作当前浏览器页面，按工具策略需要人工确认。"
        return "中风险工具调用按当前工具策略需要人工确认。"
    if risk_level == "high":
        return "高风险工具调用按当前工具策略必须人工确认。"
    return ""


def _workflow_approval_criteria(raw: dict[str, Any], public_input_preview: Any) -> str:
    criteria = str(raw.get("workflow_node_approval_criteria") or "").strip()
    if criteria:
        return criteria
    if isinstance(public_input_preview, dict):
        return str(public_input_preview.get("criteria") or "").strip()
    return ""


class ApprovalSnapshotBuilder:
    """Builds public ApprovalCard-style snapshots from private pending approvals."""

    def public_pending_approval(self, value: Any) -> dict[str, Any]:
        return public_pending_approval(value)
