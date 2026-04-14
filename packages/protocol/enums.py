"""协议枚举定义"""

from enum import StrEnum


class TaskStatus(StrEnum):
    """任务状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    """任务类型"""

    STATUS_QUERY = "status_query"
    SCREENSHOT = "screenshot"
    ACTIVE_WINDOW = "active_window"
    GENERAL = "general"


class RiskLevel(StrEnum):
    """风险等级"""

    LOW = "low"  # status, task lists, screenshots, summaries
    MEDIUM = "medium"  # bounded reads, workspace scans, safe local queries
    HIGH = "high"  # arbitrary shell, destructive ops, git push, keyboard/mouse


class ErrorCode(StrEnum):
    """错误码"""

    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    TASK_NOT_CANCELLABLE = "task_not_cancellable"
    RISK_DENIED = "risk_denied"
    INTERNAL_ERROR = "internal_error"
    ADAPTER_ERROR = "adapter_error"


class AuditAction(StrEnum):
    """审计动作类型"""

    TASK_CREATED = "task_created"
    TASK_CANCELLED = "task_cancelled"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    SCREEN_CAPTURED = "screen_captured"
    WINDOW_QUERIED = "window_queried"
    RISK_DENIED = "risk_denied"
