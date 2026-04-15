"""Protocol schema 测试 — 枚举、请求/响应模型"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.protocol.enums import (
    ErrorCode,
    HermesInstallStatus,
    RiskLevel,
    TaskStatus,
    TaskType,
)
from packages.protocol.errors import ErrorResponse
from packages.protocol.schemas import (
    ActiveWindowResponse,
    ScreenshotResponse,
    StatusResponse,
    TaskCancelResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskGetResponse,
    TaskInfo,
    TaskListResponse,
)


# ── 枚举值覆盖 ─────────────────────────────────────────────

class TestEnums:
    def test_task_status_values(self):
        assert set(TaskStatus) == {"pending", "running", "completed", "failed", "cancelled"}

    def test_task_type_values(self):
        assert "general" in set(TaskType)

    def test_risk_level_values(self):
        assert set(RiskLevel) == {"low", "medium", "high"}

    def test_error_code_includes_key_codes(self):
        assert "not_found" in set(ErrorCode)
        assert "task_not_cancellable" in set(ErrorCode)

    def test_install_status_has_ready(self):
        assert HermesInstallStatus.READY == "ready"
        assert HermesInstallStatus.NOT_INSTALLED == "not_installed"


# ── TaskInfo ───────────────────────────────────────────────

class TestTaskInfo:
    def test_create_minimal(self):
        now = datetime.now(timezone.utc)
        t = TaskInfo(
            task_id="abc123",
            description="测试任务",
            task_type=TaskType.GENERAL,
            status=TaskStatus.PENDING,
            risk_level=RiskLevel.LOW,
            created_at=now,
            updated_at=now,
        )
        assert t.task_id == "abc123"
        assert t.result is None
        assert t.error is None

    def test_with_result_and_error(self):
        now = datetime.now(timezone.utc)
        t = TaskInfo(
            task_id="x",
            description="d",
            task_type=TaskType.GENERAL,
            status=TaskStatus.FAILED,
            risk_level=RiskLevel.LOW,
            created_at=now,
            updated_at=now,
            result="partial",
            error="超时",
        )
        assert t.result == "partial"
        assert t.error == "超时"


# ── Request/Response 模型 ──────────────────────────────────

class TestTaskCreateRequest:
    def test_valid_request(self):
        req = TaskCreateRequest(description="测试")
        assert req.task_type == TaskType.GENERAL
        assert req.risk_level == RiskLevel.LOW

    def test_empty_description_rejected(self):
        with pytest.raises(ValidationError):
            TaskCreateRequest(description="")

    def test_long_description_rejected(self):
        with pytest.raises(ValidationError):
            TaskCreateRequest(description="x" * 501)


class TestStatusResponse:
    def test_defaults(self):
        resp = StatusResponse(uptime_seconds=10.5)
        assert resp.service == "hermes-yachiyo"
        assert resp.version == "0.1.0"
        assert resp.hermes_ready is False

    def test_with_task_counts(self):
        resp = StatusResponse(
            uptime_seconds=60,
            task_counts={TaskStatus.PENDING: 3, TaskStatus.RUNNING: 1},
            hermes_ready=True,
        )
        assert resp.hermes_ready is True
        assert resp.task_counts[TaskStatus.PENDING] == 3


class TestErrorResponse:
    def test_create(self):
        err = ErrorResponse(error=ErrorCode.NOT_FOUND, message="任务不存在")
        assert err.error == "not_found"
        assert err.detail is None


class TestListResponse:
    def test_empty_list(self):
        resp = TaskListResponse(tasks=[], total=0)
        assert resp.total == 0

    def test_with_tasks(self):
        now = datetime.now(timezone.utc)
        t = TaskInfo(
            task_id="t1",
            description="x",
            task_type=TaskType.GENERAL,
            status=TaskStatus.PENDING,
            risk_level=RiskLevel.LOW,
            created_at=now,
            updated_at=now,
        )
        resp = TaskListResponse(tasks=[t], total=1)
        assert resp.total == 1
        assert resp.tasks[0].task_id == "t1"


class TestScreenshotResponse:
    def test_create(self):
        now = datetime.now(timezone.utc)
        resp = ScreenshotResponse(
            image_base64="abc",
            width=1920,
            height=1080,
            captured_at=now,
        )
        assert resp.format == "png"
        assert resp.width == 1920


class TestActiveWindowResponse:
    def test_create(self):
        now = datetime.now(timezone.utc)
        resp = ActiveWindowResponse(
            title="终端",
            app_name="Terminal",
            pid=1234,
            queried_at=now,
        )
        assert resp.pid == 1234

    def test_no_pid(self):
        now = datetime.now(timezone.utc)
        resp = ActiveWindowResponse(
            title="x", app_name="y", queried_at=now
        )
        assert resp.pid is None
