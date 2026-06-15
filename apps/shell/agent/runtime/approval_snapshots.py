"""Public approval snapshot helpers shared by runtime projections."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.events import tool_input_preview


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
    return {
        "approval_id": str(raw.get("approval_id") or ""),
        "tool": str(raw.get("tool") or ""),
        "input_preview": public_input_preview,
        "requested_at": str(raw.get("requested_at") or ""),
    }


class ApprovalSnapshotBuilder:
    """Builds public ApprovalCard-style snapshots from private pending approvals."""

    def public_pending_approval(self, value: Any) -> dict[str, Any]:
        return public_pending_approval(value)
