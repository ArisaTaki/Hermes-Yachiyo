"""应用状态管理

管理任务列表与状态，供 Core Runtime 和 Bridge 使用。
不直接处理 HTTP 请求。
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from packages.protocol.enums import RiskLevel, TaskStatus, TaskType
from packages.protocol.schemas import TaskInfo

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AppState:
    """应用状态容器"""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskInfo] = {}

    def get_task_counts(self) -> dict[str, int]:
        counts = Counter(t.status for t in self._tasks.values())
        return {s.value: counts.get(s, 0) for s in TaskStatus}

    def list_tasks(self) -> list[TaskInfo]:
        return list(self._tasks.values())

    def get_task(self, task_id: str) -> TaskInfo | None:
        return self._tasks.get(task_id)

    def create_task(
        self,
        description: str,
        task_type: TaskType = TaskType.GENERAL,
        risk_level: RiskLevel = RiskLevel.LOW,
    ) -> TaskInfo:
        now = _now()
        task = TaskInfo(
            task_id=uuid4().hex[:12],
            description=description,
            task_type=task_type,
            status=TaskStatus.PENDING,
            risk_level=risk_level,
            created_at=now,
            updated_at=now,
        )
        self._tasks[task.task_id] = task
        logger.info("任务已创建: %s", task.task_id)
        return task

    def cancel_task(self, task_id: str) -> TaskInfo:
        """取消任务，返回更新后的任务信息

        Raises:
            KeyError: 任务不存在
            ValueError: 任务状态不可取消
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"任务 {task_id} 不存在")
        if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            raise ValueError(f"任务 {task_id} 状态为 {task.status}，无法取消")
        task.status = TaskStatus.CANCELLED
        task.updated_at = _now()
        logger.info("任务已取消: %s", task_id)
        return task
