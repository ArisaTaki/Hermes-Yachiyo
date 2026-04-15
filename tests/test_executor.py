"""Executor 测试 — SimulatedExecutor、HermesCallError、HermesInvokeResult"""

import asyncio

import pytest

from apps.core.executor import (
    HermesCallError,
    HermesInvokeResult,
    SimulatedExecutor,
)
from packages.protocol.enums import RiskLevel, TaskStatus, TaskType
from packages.protocol.schemas import TaskInfo
from datetime import datetime, timezone


def _make_task(desc: str = "test") -> TaskInfo:
    now = datetime.now(timezone.utc)
    return TaskInfo(
        task_id="test001",
        description=desc,
        task_type=TaskType.GENERAL,
        status=TaskStatus.PENDING,
        risk_level=RiskLevel.LOW,
        created_at=now,
        updated_at=now,
    )


class TestHermesCallError:
    def test_basic_error(self):
        exc = HermesCallError("命令失败")
        assert str(exc) == "命令失败"
        assert exc.returncode == -1
        assert exc.stderr == ""

    def test_with_returncode_and_stderr(self):
        exc = HermesCallError("失败", returncode=1, stderr="error output")
        s = exc.to_error_string()
        assert "失败" in s
        assert "exit=1" in s
        assert "error output" in s

    def test_long_stderr_truncated(self):
        long_stderr = "x" * 200
        exc = HermesCallError("err", stderr=long_stderr)
        s = exc.to_error_string()
        # stderr 截断到 120 字符
        assert len(s) < len(long_stderr) + 50


class TestHermesInvokeResult:
    def test_success_result(self):
        r = HermesInvokeResult(success=True, stdout="ok output", returncode=0)
        assert r.output == "ok output"

    def test_failure_result(self):
        r = HermesInvokeResult(
            success=False,
            stdout="",
            stderr="error",
            returncode=1,
            error_message="执行失败",
        )
        assert r.output == ""
        err = r.to_task_error()
        assert "执行失败" in err
        assert "exit=1" in err

    def test_empty_failure(self):
        r = HermesInvokeResult(success=False)
        assert r.to_task_error() == "未知错误"


class TestSimulatedExecutor:
    @pytest.mark.asyncio
    async def test_run_returns_result(self):
        """SimulatedExecutor 应返回模拟结果字符串"""
        executor = SimulatedExecutor()
        task = _make_task("测试模拟任务")
        # 为加速测试，monkey-patch 延迟
        import apps.core.executor as mod
        original_run = mod._SIM_RUN_DELAY
        original_complete = mod._SIM_COMPLETE_DELAY
        mod._SIM_RUN_DELAY = 0.01
        mod._SIM_COMPLETE_DELAY = 0.01
        try:
            result = await executor.run(task)
            assert "[模拟结果]" in result
            assert "测试模拟任务" in result
        finally:
            mod._SIM_RUN_DELAY = original_run
            mod._SIM_COMPLETE_DELAY = original_complete
