"""请求/响应 Schema 定义"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import RiskLevel, TaskStatus, TaskType


# ── 通用 ──────────────────────────────────────────────


class StatusResponse(BaseModel):
    """GET /status 响应"""

    service: str = "hermes-yachiyo"
    version: str = "0.1.0"
    uptime_seconds: float
    task_counts: dict[TaskStatus, int] = Field(default_factory=dict)
    hermes_ready: bool = False


# ── 任务 ──────────────────────────────────────────────


class TaskCreateRequest(BaseModel):
    """POST /tasks 请求"""

    description: str = Field(..., min_length=1, max_length=500)
    task_type: TaskType = TaskType.GENERAL
    risk_level: RiskLevel = RiskLevel.LOW


class TaskInfo(BaseModel):
    """单个任务的信息"""

    task_id: str
    description: str
    task_type: TaskType
    status: TaskStatus
    risk_level: RiskLevel
    created_at: datetime
    updated_at: datetime
    result: str | None = None
    error: str | None = None


class TaskGetResponse(BaseModel):
    """GET /tasks/{task_id} 响应"""

    task: TaskInfo


class TaskCreateResponse(BaseModel):
    """POST /tasks 响应"""

    task: TaskInfo


class TaskListResponse(BaseModel):
    """GET /tasks 响应"""

    tasks: list[TaskInfo]
    total: int


class TaskCancelResponse(BaseModel):
    """POST /tasks/{task_id}/cancel 响应"""

    task: TaskInfo


# ── 本地能力 ──────────────────────────────────────────


class ScreenshotResponse(BaseModel):
    """GET /screen/current 响应"""

    image_base64: str
    format: str = "png"
    width: int
    height: int
    captured_at: datetime


class ActiveWindowResponse(BaseModel):
    """GET /system/active-window 响应"""

    title: str
    app_name: str
    pid: int | None = None
    queried_at: datetime


# ── Assistant intent ───────────────────────────────────


class AssistantIntentRequest(BaseModel):
    """POST /assistant/intent 请求。"""

    text: str = Field(..., min_length=1, max_length=1000)
    source: str = "astrbot"
    sender_id: str = ""
    dry_run: bool = False


class AssistantIntentResponse(BaseModel):
    """POST /assistant/intent 响应。"""

    ok: bool
    action: str
    task_id: str | None = None
    message: str
