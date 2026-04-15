"""AppState 测试 — 任务创建、取消、状态推进"""

import pytest

from packages.protocol.enums import RiskLevel, TaskStatus, TaskType


class TestAppStateCreate:
    def test_create_task(self, app_state):
        task = app_state.create_task("测试任务")
        assert task.description == "测试任务"
        assert task.status == TaskStatus.PENDING
        assert task.task_type == TaskType.GENERAL
        assert task.risk_level == RiskLevel.LOW
        assert len(task.task_id) == 12

    def test_create_task_custom_type(self, app_state):
        task = app_state.create_task(
            "截图", task_type=TaskType.SCREENSHOT, risk_level=RiskLevel.MEDIUM
        )
        assert task.task_type == TaskType.SCREENSHOT
        assert task.risk_level == RiskLevel.MEDIUM

    def test_list_tasks(self, app_state):
        app_state.create_task("A")
        app_state.create_task("B")
        assert len(app_state.list_tasks()) == 2

    def test_get_task(self, app_state):
        task = app_state.create_task("find me")
        found = app_state.get_task(task.task_id)
        assert found is not None
        assert found.description == "find me"

    def test_get_task_not_found(self, app_state):
        assert app_state.get_task("nonexistent") is None

    def test_task_counts(self, app_state):
        app_state.create_task("A")
        app_state.create_task("B")
        counts = app_state.get_task_counts()
        assert counts["pending"] == 2
        assert counts["running"] == 0


class TestAppStateCancel:
    def test_cancel_pending(self, app_state):
        task = app_state.create_task("to cancel")
        result = app_state.cancel_task(task.task_id)
        assert result.status == TaskStatus.CANCELLED

    def test_cancel_running(self, app_state):
        task = app_state.create_task("running one")
        app_state.update_task_status(task.task_id, TaskStatus.RUNNING)
        result = app_state.cancel_task(task.task_id)
        assert result.status == TaskStatus.CANCELLED

    def test_cancel_completed_raises(self, app_state):
        task = app_state.create_task("done")
        app_state.update_task_status(task.task_id, TaskStatus.RUNNING)
        app_state.update_task_status(task.task_id, TaskStatus.COMPLETED, result="ok")
        with pytest.raises(ValueError, match="无法取消"):
            app_state.cancel_task(task.task_id)

    def test_cancel_nonexistent_raises(self, app_state):
        with pytest.raises(KeyError, match="不存在"):
            app_state.cancel_task("no-such-id")


class TestAppStateUpdateStatus:
    def test_pending_to_running(self, app_state):
        task = app_state.create_task("step")
        result = app_state.update_task_status(task.task_id, TaskStatus.RUNNING)
        assert result.status == TaskStatus.RUNNING

    def test_running_to_completed_with_result(self, app_state):
        task = app_state.create_task("step")
        app_state.update_task_status(task.task_id, TaskStatus.RUNNING)
        result = app_state.update_task_status(
            task.task_id, TaskStatus.COMPLETED, result="done"
        )
        assert result.status == TaskStatus.COMPLETED
        assert result.result == "done"

    def test_running_to_failed_with_error(self, app_state):
        task = app_state.create_task("fail")
        app_state.update_task_status(task.task_id, TaskStatus.RUNNING)
        result = app_state.update_task_status(
            task.task_id, TaskStatus.FAILED, error="boom"
        )
        assert result.status == TaskStatus.FAILED
        assert result.error == "boom"

    def test_terminal_state_raises(self, app_state):
        task = app_state.create_task("final")
        app_state.update_task_status(task.task_id, TaskStatus.RUNNING)
        app_state.update_task_status(task.task_id, TaskStatus.COMPLETED, result="x")
        with pytest.raises(ValueError, match="终态"):
            app_state.update_task_status(task.task_id, TaskStatus.RUNNING)

    def test_update_nonexistent_raises(self, app_state):
        with pytest.raises(KeyError, match="不存在"):
            app_state.update_task_status("nope", TaskStatus.RUNNING)

    def test_full_lifecycle(self, app_state):
        """完整生命周期: pending → running → completed"""
        task = app_state.create_task("lifecycle")
        assert task.status == TaskStatus.PENDING
        app_state.update_task_status(task.task_id, TaskStatus.RUNNING)
        assert app_state.get_task(task.task_id).status == TaskStatus.RUNNING
        app_state.update_task_status(
            task.task_id, TaskStatus.COMPLETED, result="结果"
        )
        final = app_state.get_task(task.task_id)
        assert final.status == TaskStatus.COMPLETED
        assert final.result == "结果"
        assert final.updated_at > task.created_at
