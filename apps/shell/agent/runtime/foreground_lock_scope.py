"""Foreground-action lock scoping for runtime ToolBrokers."""

from __future__ import annotations

from typing import Any


def foreground_lock_broker_kwargs(
    *,
    run_id: str,
    run_group_id: str = "",
    workflow_run_id: str = "",
) -> dict[str, Any]:
    clean_run_id = str(run_id or "").strip()
    clean_group_id = str(run_group_id or "").strip()
    if clean_group_id:
        return {
            "foreground_lock_key": clean_group_id,
            "foreground_lock_owner": f"{clean_group_id}:{clean_run_id}",
        }
    clean_workflow_id = str(workflow_run_id or "").strip()
    if clean_workflow_id:
        lock_key = f"workflow:{clean_workflow_id}"
        return {
            "foreground_lock_key": lock_key,
            "foreground_lock_owner": f"{lock_key}:{clean_run_id}",
        }
    return {}
