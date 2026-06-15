"""Chat-facing task card mapping compatibility exports."""

from __future__ import annotations

from .run_snapshots import agent_task_snapshot_from_payload, agent_task_snapshots_from_payloads

__all__ = [
    "agent_task_snapshot_from_payload",
    "agent_task_snapshots_from_payloads",
]
