"""Native GroupRun facade exposed by the shared runtime engine."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .group_runs import start_agent_group_run as _start_agent_group_run


class RuntimeGroupFacadeMixin:
    """Starts GroupRun orchestration inside NativeRunEngine."""

    _native_group_run_orchestration = True

    def start_agent_group_run(self, request: dict[str, Any]) -> dict[str, Any]:
        payload = dict(request)
        if not str(payload.get("group_id") or "").strip():
            raise ValueError("缺少 group_id")
        if not str(payload.get("objective") or payload.get("goal") or "").strip():
            raise ValueError("群组运行目标不能为空")
        group = payload.pop("group", None)
        if not isinstance(group, Mapping):
            raise ValueError("缺少已解析的群组定义")
        return _start_agent_group_run(
            self,
            payload,
            group=dict(group),
        )
