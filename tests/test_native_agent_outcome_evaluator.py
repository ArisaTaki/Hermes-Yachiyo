"""Deterministic terminal-outcome regression tests for the Native Agent path."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from apps.core.executor import NativeAgentError, NativeAgentExecutor
from apps.shell.agent.runtime.events import (
    RUNTIME_EXECUTION_PROVENANCE_KEY,
    RUNTIME_EXECUTION_PROVENANCE_VERSION,
    RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
)
from apps.shell.agent.runtime.goal_contract import GoalContract, GoalCriterion
from apps.shell.agent.runtime.goal_runtime import goal_contract_event_payload
from apps.shell.agent.runtime.outcome_evaluator import (
    MainChatOutcomeEvaluation,
    evaluate_main_chat_outcome,
)
from apps.shell.yachiyo_agent.legacy_tasks import LegacyRuntimePort
from packages.protocol.enums import RiskLevel, TaskStatus, TaskType
from packages.protocol.schemas import TaskInfo


def _task(description: str) -> TaskInfo:
    now = datetime.now(timezone.utc)
    return TaskInfo(
        task_id="outcome-task-1",
        description=description,
        task_type=TaskType.GENERAL,
        status=TaskStatus.PENDING,
        risk_level=RiskLevel.LOW,
        created_at=now,
        updated_at=now,
    )


class _ExecutorRuntime:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.calls: list[str] = []
        self.status = "running"
        self.result = ""

    def list_delegation_targets(self) -> dict[str, list[Any]]:
        return {"agents": [], "workflows": []}

    def start_main_chat_run(self, **_payload: Any) -> dict[str, Any]:
        self.calls.append("start")
        return {"run_id": "main-chat-outcome-1", "status": "running"}

    def execute_main_chat_model_loop(
        self,
        _run_id: str,
        _messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append("execute")
        self.result = "模型说任务已完成。"
        return {
            "run_id": "main-chat-outcome-1",
            "status": "running",
            "result": self.result,
        }

    def get_run(self, _run_id: str) -> dict[str, Any]:
        self.calls.append("get_run")
        return {
            "run_id": "main-chat-outcome-1",
            "kind": "main_chat_run",
            "status": self.status,
            "result": self.result,
            "pending_approval": {},
            "timeline": [],
        }

    def list_run_events(self, _run_id: str, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("list_events")
        return {"events": list(self.events)}

    def complete_main_chat_run(self, _run_id: str, result: str) -> dict[str, Any]:
        self.calls.append("complete")
        self.status = "completed"
        self.result = result
        return {"status": self.status, "result": result}

    def fail_main_chat_run(self, _run_id: str, error: Any) -> dict[str, Any]:
        self.calls.append("fail")
        self.status = "failed"
        self.result = str(error)
        return {"status": self.status, "result": self.result}


def _desktop_event(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": "agent.desktop.intent_completed",
        "payload": {
            "tool": "app.open",
            "source": "runtime_planner",
            "summary": "已处理应用打开请求。",
            "result": result,
        },
    }


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (
            {
                "ok": False,
                "permission_error": True,
                "permission_targets": ["accessibility"],
            },
            "desktop_permission_required",
        ),
        (
            {"ok": False, "error_code": "app_not_found"},
            "desktop_tool_failed",
        ),
        (
            {"ok": True, "verification_failed": True},
            "desktop_verification_failed",
        ),
    ],
)
@pytest.mark.asyncio
async def test_executor_does_not_complete_failed_desktop_outcome_from_model_text(
    result: dict[str, Any],
    reason: str,
) -> None:
    runtime = _ExecutorRuntime([_desktop_event(result)])
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("打开计算器"))

    assert exc_info.value.reason == reason
    assert runtime.status == "failed"
    assert "complete" not in runtime.calls
    assert runtime.calls.count("fail") == 1


@pytest.mark.asyncio
async def test_executor_completes_app_open_with_postcondition_evidence() -> None:
    runtime = _ExecutorRuntime(
        [
            _desktop_event(
                {
                    "ok": True,
                    "data": {
                        "app_name": "Calculator",
                        "launch_verified": True,
                    },
                }
            )
        ]
    )
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    output = await executor.run(_task("打开计算器"))

    assert output == "模型说任务已完成。"
    assert runtime.status == "completed"
    assert runtime.calls.count("complete") == 1
    assert "fail" not in runtime.calls


@pytest.mark.asyncio
async def test_executor_rejects_app_open_without_postcondition_evidence() -> None:
    runtime = _ExecutorRuntime(
        [
            _desktop_event(
                {
                    "ok": True,
                    "data": {"app_name": "Calculator"},
                }
            )
        ]
    )
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("打开计算器"))

    assert exc_info.value.reason == "desktop_verification_missing"
    assert runtime.status == "failed"
    assert "complete" not in runtime.calls
    assert runtime.calls.count("fail") == 1


@pytest.mark.asyncio
async def test_executor_keeps_pure_text_completion_compatible() -> None:
    runtime = _ExecutorRuntime([])
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    output = await executor.run(_task("解释一下什么是结构化并发"))

    assert output == "模型说任务已完成。"
    assert runtime.status == "completed"
    assert runtime.calls.count("complete") == 1
    assert "fail" not in runtime.calls


class _AwaitingUserRuntime(_ExecutorRuntime):
    def execute_main_chat_model_loop(
        self,
        _run_id: str,
        _messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append("execute")
        self.status = "awaiting_user"
        self.result = "请问要整理哪个目录？"
        return {
            "run_id": "main-chat-outcome-1",
            "status": self.status,
            "result": self.result,
        }


@pytest.mark.asyncio
async def test_executor_returns_clarification_without_complete_or_fail() -> None:
    runtime = _AwaitingUserRuntime([])
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    output = await executor.run(_task("帮我整理一下文件"))

    assert output == "请问要整理哪个目录？"
    assert runtime.status == "awaiting_user"
    assert "complete" not in runtime.calls
    assert "fail" not in runtime.calls


def test_evaluator_projects_awaiting_user_as_non_terminal_turn_exit() -> None:
    question = "请问要整理哪个目录？"

    outcome = evaluate_main_chat_outcome(
        {
            "run_id": "run-awaiting-user",
            "status": "awaiting_user",
            "result": question,
        }
    )

    assert outcome == MainChatOutcomeEvaluation(
        kind="awaiting_user",
        reason="clarification_required",
        message=question,
    )
    assert outcome.allows_completion is False


def test_evaluator_completed_status_does_not_hide_failed_desktop_fact() -> None:
    outcome = evaluate_main_chat_outcome(
        {
            "run_id": "completed-with-failed-desktop-fact",
            "status": "completed",
            "result": "模型说已完成。",
        },
        [
            {
                **_desktop_event({"ok": False, "error_code": "app_not_found"}),
                "run_id": "completed-with-failed-desktop-fact",
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_tool_failed"


def test_evaluator_preserves_structured_runtime_provider_handoff() -> None:
    summary = (
        "后台桌面控制尚未就绪，因此没有打开或操作 Google Chrome，"
        "也没有接管你正在使用的鼠标和键盘。"
        "请先安装或授权后台控制组件后重试。"
    )
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.intent_unavailable",
                "payload": {
                    "tool": "desktop.inspect_app",
                    "status": "blocked",
                    "source": "runtime_execution_envelope",
                    "reason": "runtime_execution_not_ready",
                    "blocked_by": "provider_required",
                    "blocked_summary": summary,
                    "input_preview": {"app_name": "Google Chrome"},
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "runtime_execution_not_ready"
    assert outcome.message == summary
    assert outcome.desktop_observed is True


def test_evaluator_does_not_claim_blocked_desktop_intent_was_executed() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.intent_unavailable",
                "payload": {
                    "tool": "app.open",
                    "status": "blocked",
                    "reason": "runtime_execution_not_ready",
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "runtime_execution_not_ready"
    assert "桌面操作未完成" in outcome.message
    assert "已执行" not in outcome.message


def test_evaluator_completed_status_does_not_hide_unverified_desktop_fact() -> None:
    outcome = evaluate_main_chat_outcome(
        {"status": "completed", "result": "模型说已完成。"},
        [
            _desktop_event(
                {
                    "ok": True,
                    "data": {"app_name": "Calculator"},
                }
            )
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


@pytest.mark.parametrize(
    "events",
    [
        [],
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "workspace.read",
                    "result": {"ok": False, "error": "file_not_found"},
                },
            }
        ],
    ],
)
def test_evaluator_completed_status_without_desktop_facts_stays_completed(
    events: list[dict[str, Any]],
) -> None:
    outcome = evaluate_main_chat_outcome(
        {"status": "completed", "result": "已完成。"},
        events,
    )

    assert outcome.kind == "completed"
    assert outcome.desktop_observed is False


class _CompletionResultRuntime(_ExecutorRuntime):
    def __init__(self, completion_status: str) -> None:
        super().__init__([])
        self.completion_status = completion_status
        self.pending_approval: dict[str, Any] = {}

    def get_run(self, _run_id: str) -> dict[str, Any]:
        self.calls.append("get_run")
        return {
            "run_id": "main-chat-outcome-1",
            "kind": "main_chat_run",
            "status": self.status,
            "result": self.result,
            "pending_approval": dict(self.pending_approval),
            "timeline": [],
        }

    def complete_main_chat_run(self, _run_id: str, result: str) -> dict[str, Any]:
        self.calls.append("complete")
        self.status = self.completion_status
        self.result = result if self.status == "completed" else f"run became {self.status}"
        if self.status == "approval_required":
            self.pending_approval = {
                "approval_id": "approval-during-complete",
                "tool": "desktop.verify",
            }
        return {
            "run_id": "main-chat-outcome-1",
            "status": self.status,
            "result": self.result,
            "pending_approval": dict(self.pending_approval),
        }


@pytest.mark.parametrize(
    ("completion_status", "reason"),
    [
        ("approval_required", "approval_required"),
        ("failed", "failed"),
        ("cancelled", "cancelled"),
    ],
)
@pytest.mark.asyncio
async def test_executor_requires_complete_call_to_return_completed_status(
    completion_status: str,
    reason: str,
) -> None:
    runtime = _CompletionResultRuntime(completion_status)
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("解释结构化并发"))

    assert exc_info.value.reason == reason
    assert runtime.calls.count("complete") == 1
    assert "fail" not in runtime.calls


class _FreshApprovalRaceRuntime(_ExecutorRuntime):
    def __init__(self) -> None:
        super().__init__([])
        self.get_count = 0

    def execute_main_chat_model_loop(
        self,
        _run_id: str,
        _messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append("execute")
        return {
            "run_id": "main-chat-outcome-1",
            "status": "approval_required",
            "result": "等待审批：app.open",
            "pending_approval": {"approval_id": "approval-old", "tool": "app.open"},
        }

    def get_run(self, _run_id: str) -> dict[str, Any]:
        self.calls.append("get_run")
        self.get_count += 1
        if self.get_count == 1:
            return {
                "run_id": "main-chat-outcome-1",
                "kind": "main_chat_run",
                "status": "running",
                "result": "模型说任务已完成。",
                "pending_approval": {},
                "timeline": [],
            }
        return {
            "run_id": "main-chat-outcome-1",
            "kind": "main_chat_run",
            "status": "approval_required",
            "result": "等待审批：desktop.verify",
            "pending_approval": {
                "approval_id": "approval-new",
                "tool": "desktop.verify",
            },
            "timeline": [],
        }


@pytest.mark.asyncio
async def test_executor_refreshes_run_before_completion_and_preserves_new_approval() -> None:
    runtime = _FreshApprovalRaceRuntime()
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("打开计算器并验证前台窗口"))

    assert exc_info.value.reason == "approval_required"
    assert runtime.get_count >= 2
    assert "complete" not in runtime.calls
    assert "fail" not in runtime.calls


@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
@pytest.mark.asyncio
async def test_executor_does_not_complete_or_reproject_failed_terminal_run(
    terminal_status: str,
) -> None:
    runtime = _ExecutorRuntime([])
    runtime.status = terminal_status
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("解释结构化并发"))

    assert exc_info.value.reason == terminal_status
    assert "complete" not in runtime.calls
    assert "fail" not in runtime.calls


class _PagedOutcomeRuntime(_ExecutorRuntime):
    def __init__(self) -> None:
        events = [
            {
                "sequence": sequence,
                "event_type": "agent.model.output",
                "payload": {"text": f"chunk-{sequence}"},
            }
            for sequence in range(1, 1001)
        ]
        events.append(
            {
                "sequence": 1001,
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    "tool": "app.open",
                    "result": {"ok": False, "error_code": "app_not_found"},
                },
            }
        )
        super().__init__(events)
        self.after_sequences: list[int] = []

    def list_run_events(
        self,
        _run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append("list_events")
        self.after_sequences.append(after_sequence)
        page = [
            event
            for event in self.events
            if int(event["sequence"]) > after_sequence
        ][:limit]
        next_after_sequence = max(
            [int(event["sequence"]) for event in page] or [after_sequence]
        )
        return {
            "events": page,
            "next_after_sequence": next_after_sequence,
            "has_more": next_after_sequence < int(self.events[-1]["sequence"]),
        }


@pytest.mark.asyncio
async def test_executor_pages_to_latest_outcome_event_before_completion() -> None:
    runtime = _PagedOutcomeRuntime()
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("打开不存在的应用"))

    assert exc_info.value.reason == "desktop_tool_failed"
    assert runtime.after_sequences == [0, 1000]
    assert "complete" not in runtime.calls


class _UnboundedOutcomePagesRuntime(_ExecutorRuntime):
    def __init__(self) -> None:
        super().__init__([])
        self.page_calls = 0

    def list_run_events(
        self,
        _run_id: str,
        *,
        after_sequence: int = 0,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append("list_events")
        self.page_calls += 1
        return {
            "events": [],
            "next_after_sequence": after_sequence + 1,
            "has_more": True,
        }


@pytest.mark.asyncio
async def test_executor_fails_closed_when_outcome_event_pages_never_finish() -> None:
    runtime = _UnboundedOutcomePagesRuntime()
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("执行一个事件很多的桌面任务"))

    assert exc_info.value.reason == "outcome_event_history_incomplete"
    assert runtime.page_calls == 10
    assert "complete" not in runtime.calls


class _UnavailableOutcomeEventsRuntime(_ExecutorRuntime):
    def list_run_events(self, _run_id: str, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("list_events")
        raise OSError("event store temporarily unavailable")


class _MalformedOutcomeEventsRuntime(_ExecutorRuntime):
    def __init__(self, payload: Any) -> None:
        super().__init__([])
        self.payload = payload

    def list_run_events(self, _run_id: str, **_kwargs: Any) -> Any:
        self.calls.append("list_events")
        return self.payload


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"events": None}, id="events-none"),
        pytest.param(
            {"has_more": False, "next_after_sequence": 0},
            id="events-missing-with-metadata",
        ),
        pytest.param({"events": ["corrupt-event"]}, id="non-dict-event"),
        pytest.param("corrupt-envelope", id="non-list-envelope"),
    ],
)
@pytest.mark.asyncio
async def test_executor_fails_closed_when_outcome_event_payload_is_malformed(
    payload: Any,
) -> None:
    runtime = _MalformedOutcomeEventsRuntime(payload)
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("打开计算器"))

    assert exc_info.value.reason == "outcome_event_history_incomplete"
    assert runtime.calls.count("list_events") == 1
    assert "complete" not in runtime.calls
    assert runtime.calls.count("fail") == 1


@pytest.mark.asyncio
async def test_executor_accepts_valid_empty_outcome_event_page() -> None:
    runtime = _MalformedOutcomeEventsRuntime({"events": []})
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    output = await executor.run(_task("解释一下什么是结构化并发"))

    assert output == "模型说任务已完成。"
    assert runtime.calls.count("list_events") == 1
    assert runtime.calls.count("complete") == 1
    assert "fail" not in runtime.calls


@pytest.mark.asyncio
async def test_executor_fails_closed_when_durable_outcome_events_are_unavailable() -> None:
    runtime = _UnavailableOutcomeEventsRuntime([])
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("打开计算器"))

    assert exc_info.value.reason == "outcome_event_history_incomplete"
    assert runtime.calls.count("list_events") == 1
    assert "complete" not in runtime.calls


class _LegacyUnavailableOutcomeEventsRuntime(_UnavailableOutcomeEventsRuntime):
    def list_run_events(self, _run_id: str) -> dict[str, Any]:
        self.calls.append("list_events")
        raise OSError("legacy event store temporarily unavailable")


@pytest.mark.asyncio
async def test_executor_fails_closed_when_legacy_event_reader_is_unavailable() -> None:
    runtime = _LegacyUnavailableOutcomeEventsRuntime([])
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("打开计算器"))

    assert exc_info.value.reason == "outcome_event_history_incomplete"
    assert runtime.calls.count("list_events") == 1
    assert "complete" not in runtime.calls


def test_evaluator_honors_explicit_post_action_verification_contract() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "desktop.click_ui_element",
                    "requires_post_action_verification": True,
                    "verification_targets": [{"step_id": "verify-export"}],
                    "result": {"ok": True},
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_does_not_treat_task_progress_projection_as_another_action() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "manage-foreground",
                    "tool": "desktop.quit_app",
                    "requires_post_action_verification": True,
                    "result": {"ok": True},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-desktop-result",
                    "tool": "desktop.active_window",
                    "verification_target_step_ids": ["manage-foreground"],
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "result": {
                        "ok": True,
                        "data": {"app_name": "Finder", "title": ""},
                    },
                },
            },
            {
                "event_type": "agent.task.checkpoint.updated",
                "payload": {
                    "step_id": "verify-desktop-result",
                    "tool": "desktop.active_window",
                    "status": "completed",
                    "requires_post_action_verification": True,
                    "verification_target_step_ids": ["manage-foreground"],
                },
            },
            {
                "event_type": "desktop.provider_execution.routed",
                "payload": {
                    "step_id": "verify-desktop-result",
                    "tool": "desktop.active_window",
                    "requires_post_action_verification": True,
                    "verification_target_step_ids": ["manage-foreground"],
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_does_not_treat_tool_outcome_sidecar_as_another_action() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-open-sidecar"},
        [
            {
                "run_id": "run-open-sidecar",
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-open-sidecar",
                    "step_id": "open-app",
                    "tool": "app.open",
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Google Chrome",
                            "launch_verified": True,
                        },
                    },
                },
            },
            {
                "run_id": "run-open-sidecar",
                "event_type": "agent.tool.outcome",
                "payload": {
                    "plan_id": "plan-open-sidecar",
                    "step_id": "open-app",
                    "tool": "app.open",
                    "status": "completed",
                },
            },
        ],
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize(
    ("status", "reason", "expected_reason"),
    [
        ("failed", "tool_error", "tool_error"),
        ("partial", "result_incomplete", "result_incomplete"),
        ("action_required", "permission_required", "permission_required"),
        ("skipped", "operation_skipped", "operation_skipped"),
    ],
)
def test_evaluator_blocks_canonical_non_desktop_outcomes(
    status: str,
    reason: str,
    expected_reason: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-workspace-outcome", "status": "processing"},
        [
            {
                "run_id": "run-workspace-outcome",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "workspace.read",
                    "tool_call_id": "workspace-read-1",
                    "status": status,
                    "reason": reason,
                    "retryable": status in {"failed", "partial", "skipped"},
                    "verification": "unverified",
                    "visibility": "internal",
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == expected_reason


def test_evaluator_does_not_let_unrelated_success_hide_non_desktop_failure() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-unrelated-success", "status": "processing"},
        [
            {
                "run_id": "run-unrelated-success",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "workspace.read",
                    "tool_call_id": "workspace-read-failed",
                    "step_id": "read-source",
                    "status": "failed",
                    "reason": "path_not_found",
                    "retryable": True,
                    "verification": "not_required",
                    "visibility": "internal",
                },
            },
            {
                "run_id": "run-unrelated-success",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "artifact.write",
                    "tool_call_id": "artifact-write-success",
                    "step_id": "write-other-output",
                    "status": "success",
                    "reason": "completed",
                    "retryable": False,
                    "verification": "not_required",
                    "visibility": "internal",
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "path_not_found"


def test_evaluator_accepts_identity_linked_non_desktop_recovery_success() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-linked-recovery", "status": "processing"},
        [
            {
                "run_id": "run-linked-recovery",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "workspace.read",
                    "tool_call_id": "workspace-read-failed",
                    "step_id": "read-source",
                    "status": "failed",
                    "reason": "path_not_found",
                    "retryable": True,
                    "verification": "not_required",
                    "visibility": "internal",
                },
            },
            {
                "run_id": "run-linked-recovery",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "workspace.read",
                    "tool_call_id": "workspace-read-retry",
                    "source_tool_call_id": "workspace-read-failed",
                    "status": "success",
                    "reason": "completed",
                    "retryable": False,
                    "verification": "not_required",
                    "visibility": "internal",
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_allows_explicit_model_continuation_without_blocked_tool() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-goal-constraint", "status": "processing"},
        [
            {
                "run_id": "run-goal-constraint",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "terminal.run",
                    "tool_call_id": "terminal-blocked-by-goal",
                    "status": "failed",
                    "reason": "blocked_by_user_goal",
                    "retryable": False,
                    "verification": "not_required",
                    "completion_impact": "continue_without_tool",
                    "visibility": "internal",
                },
            }
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_ignores_canonical_outcome_from_another_run() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "current-run", "status": "processing"},
        [
            {
                "run_id": "different-run",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "terminal.run",
                    "tool_call_id": "different-run-failure",
                    "status": "failed",
                    "reason": "command_failed",
                    "visibility": "internal",
                },
            }
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_ignores_public_event_spoofing_internal_outcome_payload() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-public-sidecar", "status": "processing"},
        [
            {
                "run_id": "run-public-sidecar",
                "event_type": "agent.tool.outcome",
                "visibility": "user",
                "payload": {
                    "tool": "terminal.run",
                    "tool_call_id": "public-spoofed-failure",
                    "status": "failed",
                    "reason": "command_failed",
                    "visibility": "internal",
                },
            }
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_does_not_treat_discovery_success_as_original_tool_recovery() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-discovery-only", "status": "processing"},
        [
            {
                "run_id": "run-discovery-only",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "workspace.read",
                    "tool_call_id": "workspace-read-failed",
                    "status": "failed",
                    "reason": "path_not_found",
                    "visibility": "internal",
                },
            },
            {
                "run_id": "run-discovery-only",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "workspace.list",
                    "tool_call_id": "workspace-list-recovery",
                    "source_tool_call_id": "workspace-read-failed",
                    "status": "success",
                    "reason": "completed",
                    "visibility": "internal",
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "path_not_found"


def test_evaluator_accepts_runtime_linked_suggested_tool_recovery() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-suggested-recovery", "status": "processing"},
        [
            {
                "run_id": "run-suggested-recovery",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "workspace.read",
                    "tool_call_id": "workspace-read-failed",
                    "status": "failed",
                    "reason": "tool_shape_mismatch",
                    "suggested_tools": ["workspace.list"],
                    "visibility": "internal",
                },
            },
            {
                "run_id": "run-suggested-recovery",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "workspace.list",
                    "tool_call_id": "workspace-list-recovery",
                    "source_tool_call_id": "workspace-read-failed",
                    "recovery_link_kind": "suggested_tool",
                    "recovery_source_tool": "workspace.read",
                    "recovery_suggested_tool": "workspace.list",
                    "status": "success",
                    "reason": "completed",
                    "visibility": "internal",
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_accepts_completed_coordinator_recovery_for_exact_source() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-coordinator-recovery", "status": "processing"},
        [
            {
                "run_id": "run-coordinator-recovery",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "workspace.read",
                    "tool_call_id": "workspace-read-failed",
                    "status": "failed",
                    "reason": "tool_shape_mismatch",
                    "visibility": "internal",
                },
            },
            {
                "run_id": "run-coordinator-recovery",
                "event_type": "agent.recovery.completed",
                "visibility": "internal",
                "payload": {
                    "source_tool_call_id": "workspace-read-failed",
                    "result_disposition": "continue_plan",
                    "status": "completed",
                    "visibility": "internal",
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_allows_model_to_report_structured_policy_refusal() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-policy-refusal", "status": "processing"},
        [
            {
                "run_id": "run-policy-refusal",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "workspace.write_patch",
                    "tool_call_id": "workspace-boundary-refusal",
                    "status": "failed",
                    "reason": "workspace_boundary_refusal",
                    "completion_impact": "report_refusal",
                    "visibility": "internal",
                },
            }
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_keeps_non_desktop_failure_after_verified_desktop_success() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-mixed-outcomes", "status": "processing"},
        [
            {
                **_desktop_event(
                    {
                        "ok": True,
                        "data": {
                            "app_name": "Calculator",
                            "launch_verified": True,
                        },
                    }
                ),
                "run_id": "run-mixed-outcomes",
            },
            {
                "run_id": "run-mixed-outcomes",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "terminal.run",
                    "tool_call_id": "terminal-failed-after-open",
                    "status": "failed",
                    "reason": "command_failed",
                    "visibility": "internal",
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "command_failed"


def test_evaluator_ignores_blocked_task_projection_after_selected_tool_succeeds() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-selected-browser-tool", "status": "processing"},
        [
            {
                "run_id": "run-selected-browser-tool",
                "event_type": "agent.task.todo.updated",
                "payload": {
                    "tool": "desktop.list_apps",
                    "status": "blocked",
                    "reason": "not_selected_for_execution",
                },
            },
            {
                "run_id": "run-selected-browser-tool",
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "browser.open_url",
                    "requires_post_action_verification": False,
                    "result": {
                        "ok": True,
                        "data": {
                            "url": "https://example.test",
                            "target_id": "owned-target",
                            "target_owned_by_run": True,
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


@pytest.mark.asyncio
async def test_executor_does_not_complete_canonical_non_desktop_failure_from_model_text() -> None:
    runtime = _ExecutorRuntime(
        [
            {
                "run_id": "main-chat-outcome-1",
                "event_type": "agent.tool.outcome",
                "visibility": "internal",
                "payload": {
                    "tool": "terminal.run",
                    "tool_call_id": "terminal-failed",
                    "status": "failed",
                    "reason": "command_failed",
                    "visibility": "internal",
                },
            }
        ]
    )
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("运行一个需要终端的任务"))

    assert exc_info.value.reason == "command_failed"
    assert runtime.status == "failed"
    assert "complete" not in runtime.calls
    assert runtime.calls.count("fail") == 1


@pytest.mark.asyncio
async def test_executor_requests_internal_events_for_canonical_outcome_gate() -> None:
    sidecar = {
        "run_id": "main-chat-outcome-1",
        "event_type": "agent.tool.outcome",
        "visibility": "internal",
        "payload": {
            "tool": "terminal.run",
            "tool_call_id": "terminal-internal-failure",
            "status": "failed",
            "reason": "command_failed",
            "visibility": "internal",
        },
    }

    class _InternalOnlyRuntime(_ExecutorRuntime):
        def __init__(self) -> None:
            super().__init__([sidecar])
            self.event_queries: list[dict[str, Any]] = []

        def list_run_events(
            self,
            _run_id: str,
            **kwargs: Any,
        ) -> dict[str, Any]:
            self.calls.append("list_events")
            self.event_queries.append(dict(kwargs))
            return {
                "events": [sidecar] if kwargs.get("include_internal") is True else []
            }

    runtime = _InternalOnlyRuntime()
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("运行一个需要终端的任务"))

    assert exc_info.value.reason == "command_failed"
    assert runtime.event_queries
    assert all(query.get("include_internal") is True for query in runtime.event_queries)
    assert "complete" not in runtime.calls


@pytest.mark.parametrize(
    "event_type",
    [
        "agent.task.todo.updated",
        "desktop.provider_execution.routed",
    ],
)
def test_evaluator_fails_closed_for_projection_only_desktop_history(
    event_type: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": event_type,
                "payload": {
                    "step_id": "open-app",
                    "tool": "app.open",
                    "status": "completed",
                    "requires_post_action_verification": True,
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "outcome_event_history_incomplete"


def test_evaluator_does_not_use_one_generic_ui_observation_for_an_entire_chain() -> None:
    action_steps = [
        ("focus-recipient-search", "app.focus_and_safe_shortcut"),
        ("type-recipient", "desktop.safe_type_text"),
        ("submit-recipient-search", "desktop.search_submit"),
        ("draft-message", "desktop.safe_type_text"),
        ("send-message", "desktop.submit_foreground"),
    ]
    events = [
        {
            "event_type": "agent.tool.call",
            "payload": {
                "step_id": step_id,
                "tool": tool,
                "input_preview": {"app_name": "Slack"},
                "requires_post_action_verification": True,
                "result": {"ok": True},
            },
        }
        for step_id, tool in action_steps
    ]
    events.append(
        {
            "event_type": "agent.tool.call",
            "payload": {
                "step_id": "verify-message",
                "tool": "desktop.ui_elements",
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "verification_target_step_ids": ["send-message"],
                "result": {
                    "ok": True,
                    "data": {
                        "app_name": "Slack",
                        "count": 1,
                        "elements": [{"role": "AXWindow", "name": "Slack"}],
                    },
                },
            },
        }
    )

    outcome = evaluate_main_chat_outcome({}, events)

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


@pytest.mark.parametrize("legacy_requires_verification", [False, True])
def test_evaluator_rejects_semantic_shortcut_when_generic_probe_fails(
    legacy_requires_verification: bool,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-dispatch",
                    "plan_id": "plan-dispatch",
                    "request_id": "request-open-spotlight",
                    "step_id": "open-spotlight",
                    "tool": "desktop.safe_shortcut",
                    "input_preview": {"action": "spotlight_search"},
                    "requires_post_action_verification": legacy_requires_verification,
                    "result": {
                        "ok": True,
                        "action": "desktop.safe_shortcut",
                        "summary": "Executed safe shortcut: spotlight_search",
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-dispatch",
                    "plan_id": "plan-dispatch",
                    "source_request_id": "request-open-spotlight",
                    "source_step_id": "open-spotlight",
                    "step_id": "open-spotlight:runtime-verify",
                    "tool": "desktop.ui_elements",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "verification_target_step_ids": ["open-spotlight"],
                    "result": {
                        "ok": False,
                        "error": "generic UI observation timed out",
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_tool_failed"


def test_evaluator_completes_successful_dispatch_followed_by_clipboard_read() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-copy-read",
                    "plan_id": "plan-copy-read",
                    "request_id": "request-copy",
                    "step_id": "copy-selection",
                    "tool": "desktop.safe_shortcut",
                    "input_preview": {"action": "copy"},
                    "requires_post_action_verification": True,
                    "result": {"ok": True, "action": "desktop.safe_shortcut"},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-copy-read",
                    "plan_id": "plan-copy-read",
                    "request_id": "request-read-clipboard",
                    "step_id": "read-clipboard",
                    "source_step_id": "copy-selection",
                    "depends_on": ["copy-selection"],
                    "tool": "clipboard.read",
                    "result": {
                        "ok": True,
                        "data": {"text": "selected text"},
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize(
    "tool_name",
    [
        "desktop.hide_app",
        "desktop.minimize_window",
        "desktop.close_window",
        "desktop.quit_app",
    ],
)
def test_evaluator_completes_successful_foreground_management_dispatch(
    tool_name: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-management-dispatch",
                    "plan_id": "plan-management-dispatch",
                    "request_id": "request-management-dispatch",
                    "step_id": "manage-foreground",
                    "tool": tool_name,
                    # Legacy rows may still carry this stale planner contract.
                    "requires_post_action_verification": True,
                    "result": {"ok": True, "action": tool_name},
                },
            }
        ],
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize(
    "tool_name",
    [
        "desktop.hide_app",
        "desktop.minimize_window",
        "desktop.close_window",
        "desktop.quit_app",
    ],
)
def test_evaluator_ignores_legacy_generic_probe_failure_after_management_dispatch(
    tool_name: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-management-probe",
                    "plan_id": "plan-management-probe",
                    "request_id": "request-management-probe",
                    "step_id": "manage-foreground",
                    "tool": tool_name,
                    "requires_post_action_verification": True,
                    "result": {"ok": True, "action": tool_name},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-management-probe",
                    "plan_id": "plan-management-probe",
                    "source_request_id": "request-management-probe",
                    "source_step_id": "manage-foreground",
                    "step_id": "manage-foreground:runtime-verify",
                    "tool": "desktop.active_window",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "verification_target_step_ids": ["manage-foreground"],
                    "result": {"ok": False, "error": "generic probe timed out"},
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_does_not_hide_unrelated_failure_after_management_dispatch() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-management-mixed",
                    "plan_id": "plan-management-mixed",
                    "step_id": "manage-foreground",
                    "tool": "desktop.hide_app",
                    "requires_post_action_verification": False,
                    "result": {"ok": True, "action": "desktop.hide_app"},
                },
            },
            {
                "event_type": "agent.tool.failed",
                "payload": {
                    "decision_id": "decision-management-mixed",
                    "plan_id": "plan-management-mixed",
                    "step_id": "open-notes",
                    "tool": "app.open",
                    "result": {"ok": False, "error": "launch failed"},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_tool_failed"


def test_evaluator_does_not_hide_unrelated_failure_after_dispatch_receipt() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-mixed",
                    "plan_id": "plan-mixed",
                    "request_id": "request-copy",
                    "step_id": "copy-selection",
                    "tool": "desktop.safe_shortcut",
                    "input_preview": {"action": "copy"},
                    "requires_post_action_verification": False,
                    "result": {"ok": True, "action": "desktop.safe_shortcut"},
                },
            },
            {
                "event_type": "agent.tool.failed",
                "payload": {
                    "decision_id": "decision-mixed",
                    "plan_id": "plan-mixed",
                    "request_id": "request-open",
                    "step_id": "open-notes",
                    "tool": "app.open",
                    "result": {"ok": False, "error": "launch failed"},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_tool_failed"


def test_evaluator_does_not_shield_dispatch_verifier_from_another_plan() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-dispatch-a",
                    "request_id": "request-copy",
                    "step_id": "copy-selection",
                    "tool": "desktop.safe_shortcut",
                    "input_preview": {"action": "copy"},
                    "result": {"ok": True, "action": "desktop.safe_shortcut"},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-dispatch-b",
                    "source_request_id": "request-copy",
                    "source_step_id": "copy-selection",
                    "step_id": "copy-selection:runtime-verify",
                    "tool": "desktop.ui_elements",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "result": {"ok": False, "error": "probe failed"},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_tool_failed"


def test_evaluator_scopes_unverified_semantic_shortcut_to_requested_run() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-current"},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "run_id": "run-old",
                    "decision_id": "decision-old",
                    "plan_id": "plan-old",
                    "source_step_id": "copy-selection",
                    "step_id": "copy-selection:runtime-verify",
                    "tool": "desktop.ui_elements",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "result": {"ok": False, "error": "old probe failed"},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "run_id": "run-current",
                    "decision_id": "decision-repeat",
                    "plan_id": "plan-repeat",
                    "request_id": "request-copy-current",
                    "step_id": "copy-selection",
                    "tool": "desktop.safe_shortcut",
                    "input_preview": {"action": "copy"},
                    "requires_post_action_verification": False,
                    "result": {"ok": True, "action": "desktop.safe_shortcut"},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_still_requires_effect_evidence_for_creation_shortcut() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-new-note",
                    "step_id": "create-note",
                    "tool": "desktop.safe_shortcut",
                    "input_preview": {"action": "new_note"},
                    "requires_post_action_verification": True,
                    "result": {"ok": True, "action": "desktop.safe_shortcut"},
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def _note_content_verification_events(
    *,
    observed_elements: list[dict[str, object]],
    content_input: dict[str, object] | None = None,
    verification_data: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    prepare_step_id = "prepare-report-target-app"
    content_step_id = "insert-report-into-target-app"
    return [
        {
            "event_type": "agent.tool.call",
            "payload": {
                "attempt_id": "attempt-note-content",
                "step_id": prepare_step_id,
                "tool": "app.open_and_safe_shortcut",
                "runtime_role": "prepare_target_app",
                "input_preview": {"app_name": "Notes", "action": "new_note"},
                "requires_post_action_verification": True,
                "result": {"ok": True},
            },
        },
        {
            "event_type": "agent.tool.call",
            "payload": {
                "attempt_id": "attempt-note-content",
                "step_id": content_step_id,
                "tool": "desktop.safe_type_text",
                "runtime_role": "type_ui",
                "depends_on": [prepare_step_id],
                "input_preview": {
                    "app_name": "Notes",
                    "container_action": "new_note",
                    **(
                        content_input
                        or {
                            "text": (
                                "Atlas launch review: confirm the desktop Agent "
                                "release checklist."
                            )
                        }
                    ),
                },
                "requires_post_action_verification": True,
                "result": {"ok": True, "data": {"character_count": 65}},
            },
        },
        {
            "event_type": "agent.tool.call",
            "payload": {
                "attempt_id": "attempt-note-content",
                "step_id": "verify-report-target-app",
                "tool": "desktop.ui_elements",
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "verification_target_step_ids": [prepare_step_id, content_step_id],
                "input_preview": {"app_name": "Notes"},
                "result": {
                    "ok": True,
                    "postcondition_verified": True,
                    "data": {
                        "app_name": "Notes",
                        "count": len(observed_elements),
                        "elements": observed_elements,
                        **(verification_data or {}),
                    },
                },
            },
        },
    ]


def test_evaluator_rejects_generic_same_app_window_for_typed_note_content() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        _note_content_verification_events(
            observed_elements=[{"role": "AXWindow", "name": "Notes"}],
        ),
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_binds_inferred_container_verification_to_dependent_content() -> None:
    events = _note_content_verification_events(
        observed_elements=[{"role": "AXWindow", "name": "Notes"}],
    )
    content_payload = events[1]["payload"]
    assert isinstance(content_payload, dict)
    content_payload.pop("requires_post_action_verification")

    outcome = evaluate_main_chat_outcome({}, events)

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_accepts_same_app_ui_containing_substantive_typed_content() -> None:
    intended = "Atlas launch review: confirm the desktop Agent release checklist."
    outcome = evaluate_main_chat_outcome(
        {},
        _note_content_verification_events(
            observed_elements=[
                {"role": "AXWindow", "name": "Notes"},
                {"role": "AXTextArea", "value": intended},
            ],
            content_input={"text": intended},
        ),
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize("intended", ["hello", "OK", "你好"])
def test_evaluator_accepts_exact_short_content_in_editable_ui(intended: str) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        _note_content_verification_events(
            observed_elements=[
                {"role": "AXWindow", "name": "Notes"},
                {"role": "AXTextField", "value": intended},
            ],
            content_input={"text": intended},
        ),
    )

    assert outcome.kind == "completed"


def test_evaluator_rejects_short_content_only_present_in_unrelated_button_label() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        _note_content_verification_events(
            observed_elements=[
                {"role": "AXWindow", "name": "Notes"},
                {"role": "AXButton", "name": "OK"},
            ],
            content_input={"text": "OK"},
        ),
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_accepts_explicit_semantic_content_verification_without_raw_text() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        _note_content_verification_events(
            observed_elements=[{"role": "AXWindow", "name": "Notes"}],
            content_input={
                "body_source": "report_artifact",
                "artifact_path": "summary.md",
            },
            verification_data={"content_verified": True},
        ),
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize(
    ("action", "player_state", "expected_kind"),
    [
        ("play", "playing", "completed"),
        ("play", "paused", "failed"),
        ("pause", "paused", "completed"),
        ("pause", "stopped", "completed"),
        ("pause", "playing", "failed"),
    ],
)
def test_evaluator_requires_media_state_to_match_requested_control(
    action: str,
    player_state: str,
    expected_kind: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "control-media-playback",
                    "tool": "media.apple_music_control",
                    "input_preview": {"action": action},
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "control": action,
                            "player_state": player_state,
                            # A track identifies content, not whether pause/play
                            # reached the requested state.
                            "track": "超时空辉夜姬",
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == expected_kind
    if expected_kind == "failed":
        assert outcome.reason == "desktop_verification_missing"


def test_evaluator_treats_approval_approved_as_lifecycle_not_media_action() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "control-media-playback",
                    "tool": "media.apple_music_control",
                    "input_preview": {"action": "play"},
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "control": "play",
                            "player_state": "playing",
                            "track": "超时空辉夜姬",
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.approval_approved",
                "payload": {
                    "tool": "media.apple_music_control",
                    "input_preview": {"action": "play"},
                    "approval_id": "approval-media-play",
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_ignores_unrelated_foreground_ui_for_verified_background_media() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "control-media-playback",
                    "tool": "media.music_app_open_and_play",
                    "input_preview": {"app_name": "Music"},
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Music",
                            "control": "play",
                            "playback_ok": True,
                            "player_state": "playing",
                            "track": "超时空辉夜姬",
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-media-playback",
                    "tool": "desktop.ui_elements",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "verification_target_step_ids": ["control-media-playback"],
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "ChatGPT",
                            "elements": [],
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_accepts_verified_apple_music_open_and_play_receipt() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "open-and-play-apple-music",
                    "tool": "media.apple_music_open_and_play",
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Music",
                            "control": "play",
                            "playback_ok": True,
                            "track": "超时空辉夜姬",
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_keeps_unverified_apple_music_open_and_play_fail_closed() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "open-and-play-apple-music",
                    "tool": "media.apple_music_open_and_play",
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Music",
                            "control": "play",
                            "playback_ok": True,
                            "track": "超时空辉夜姬",
                            "playback_state_unverified": True,
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_rejects_negative_apple_music_open_and_play_receipt() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "open-and-play-apple-music",
                    "tool": "media.apple_music_open_and_play",
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Music",
                            "control": "play",
                            "playback_ok": False,
                            "track": "超时空辉夜姬",
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_ignores_unrelated_permission_preflight_after_verified_focus() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.permission_preflight",
                "payload": {
                    "tool": "app.focus",
                    "tools": ["app.focus"],
                    "status": "permission_preflight_available",
                    "permission_targets": ["chrome_cdp"],
                    # A legacy preflight without capability information can
                    # over-attribute the flattened target to the planned tool.
                    "affected_tools": ["app.focus"],
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "focus-finder",
                    "tool": "app.focus",
                    "input_preview": {"app_name": "Finder"},
                    "result": {
                        "ok": True,
                        "focus_verified": True,
                        "data": {"app_name": "Finder"},
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_does_not_attribute_unrelated_preflight_to_missing_focus_evidence() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.permission_preflight",
                "payload": {
                    "tool": "app.focus",
                    "status": "permission_preflight_available",
                    "permission_targets": ["chrome_cdp"],
                    "affected_tools": ["app.focus"],
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "focus-finder",
                    "tool": "app.focus",
                    "input_preview": {"app_name": "Finder"},
                    "result": {"ok": True, "data": {"app_name": "Finder"}},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_attributes_relevant_permission_preflight_to_focus_action() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.permission_preflight",
                "payload": {
                    "tool": "app.focus",
                    "status": "permission_preflight_available",
                    "permission_targets": ["accessibility"],
                    "affected_tools": ["app.focus"],
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "focus-finder",
                    "tool": "app.focus",
                    "input_preview": {"app_name": "Finder"},
                    "result": {"ok": True, "data": {"app_name": "Finder"}},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_permission_required"


@pytest.mark.parametrize(
    ("tool", "status_key", "status"),
    [
        ("app.show", "show_status", "shown"),
        ("app.show", "show_status", "launched"),
        ("app.hide", "hide_status", "hidden"),
        ("app.minimize", "minimize_status", "minimized"),
    ],
)
def test_evaluator_accepts_native_app_management_status_receipt(
    tool: str,
    status_key: str,
    status: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "manage-app",
                    "tool": tool,
                    "input_preview": {"app_name": "Slack"},
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {"app_name": "Slack", status_key: status},
                    },
                },
            }
        ],
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize(
    ("tool", "status_key", "status"),
    [
        ("app.show", "show_status", "shown"),
        ("app.hide", "hide_status", "hidden"),
        ("app.minimize", "minimize_status", "minimized"),
    ],
)
def test_evaluator_keeps_native_app_management_receipt_authoritative_over_running_apps(
    tool: str,
    status_key: str,
    status: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "manage-app",
                    "tool": tool,
                    "input_preview": {"app_name": "Slack"},
                    "result": {
                        "ok": True,
                        "data": {"app_name": "Slack", status_key: status},
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-desktop-result",
                    "tool": "desktop.running_apps",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "verification_target_step_ids": ["manage-app"],
                    "result": {
                        "ok": True,
                        "data": {
                            "apps": [{"name": "Slack", "frontmost": False}],
                            "count": 1,
                            "frontmost": "Finder",
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_ignores_app_management_planning_and_started_projections() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.intent_planned",
                "payload": {
                    "tool": "app.show",
                    "requires_post_action_verification": True,
                    "status": "planned",
                },
            },
            {
                "event_type": "agent.tool.started",
                "payload": {
                    "tool": "app.show",
                    "requires_post_action_verification": True,
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "manage-app",
                    "tool": "app.show",
                    "input_preview": {"app_name": "Slack"},
                    "result": {
                        "ok": True,
                        "data": {"app_name": "Slack", "show_status": "shown"},
                    },
                },
            },
            {
                "event_type": "agent.tool.started",
                "payload": {
                    "tool": "desktop.running_apps",
                    "verification_target_step_ids": ["manage-app"],
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-desktop-result",
                    "tool": "desktop.running_apps",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "verification_target_step_ids": ["manage-app"],
                    "result": {
                        "ok": True,
                        "data": {
                            "apps": [{"name": "Slack", "frontmost": False}],
                            "count": 1,
                            "frontmost": "Finder",
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_ignores_resolved_input_projection_before_verified_focus() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.input_resolved",
                "payload": {
                    "step_id": "focus-app",
                    "tool": "app.focus",
                    "input_preview": {"app_name": "Slack"},
                    "requires_post_action_verification": True,
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "focus-app",
                    "tool": "app.focus",
                    "input_preview": {"app_name": "Slack"},
                    "result": {"ok": True, "data": {"app_name": "Slack"}},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-focus",
                    "tool": "desktop.verify",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "verification_target_step_ids": ["focus-app"],
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Slack",
                            "focus_verified": True,
                            "foreground_ready": True,
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_does_not_treat_aggregate_completion_as_second_focus_action() -> None:
    focus_step = {
        "step_id": "focus-app",
        "tool": "app.focus",
        "input_preview": {"app_name": "Slack"},
        "result": {"ok": True, "data": {"app_name": "Slack"}},
    }
    verify_step = {
        "step_id": "verify-focus",
        "tool": "desktop.verify",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "verification_target_step_ids": ["focus-app"],
        "result": {
            "ok": True,
            "data": {
                "app_name": "Slack",
                "focus_verified": True,
                "foreground_ready": True,
            },
        },
    }
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {"event_type": "agent.tool.call", "payload": focus_step},
            {"event_type": "agent.tool.call", "payload": verify_step},
            {
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    **focus_step,
                    "requires_post_action_verification": False,
                    "steps": [focus_step, verify_step],
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_preserves_scoped_content_verifier_over_aggregate_step_projection() -> None:
    action_step = {
        "decision_id": "decision-type",
        "plan_id": "plan-type",
        "step_id": "type-message",
        "tool": "desktop.safe_type_text",
        "runtime_stage": "operate",
        "runtime_role": "type_ui",
        "input_preview": {"text": "你好八千代"},
        "requires_post_action_verification": True,
        "result": {"ok": True, "data": {"character_count": 5}},
    }
    verify_step = {
        "decision_id": "decision-type",
        "plan_id": "plan-type",
        "step_id": "verify-message",
        "tool": "desktop.ui_elements",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "verification_target_step_ids": ["type-message"],
        "result": {
            "ok": True,
            "data": {
                "elements": [
                    {"role": "AXTextField", "value": "你好八千代"},
                ],
            },
        },
    }
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-type"},
        [
            {
                "run_id": "run-type",
                "event_type": "agent.tool.call",
                "payload": action_step,
            },
            {
                "run_id": "run-type",
                "event_type": "agent.tool.call",
                "payload": verify_step,
            },
            {
                "run_id": "run-type",
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    **action_step,
                    "requires_post_action_verification": False,
                    "steps": [action_step, verify_step],
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_preserves_scoped_search_verifier_over_aggregate_step_projection() -> None:
    action_step = {
        "decision_id": "decision-search",
        "plan_id": "plan-search",
        "step_id": "submit-search",
        "tool": "desktop.search_submit",
        "runtime_stage": "operate",
        "runtime_role": "submit_ui",
        "requires_post_action_verification": True,
        "result": {"ok": True, "data": {"submitted": True}},
    }
    verify_step = {
        "decision_id": "decision-search",
        "plan_id": "plan-search",
        "step_id": "verify-search",
        "tool": "desktop.ui_elements",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "verification_target_step_ids": ["submit-search"],
        "result": {
            "ok": True,
            "data": {
                "app_name": "Notes",
                "elements": [
                    {"role": "AXSearchField", "value": "hello"},
                ],
            },
        },
    }
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-search"},
        [
            {
                "run_id": "run-search",
                "event_type": "agent.tool.call",
                "payload": action_step,
            },
            {
                "run_id": "run-search",
                "event_type": "agent.tool.call",
                "payload": verify_step,
            },
            {
                "run_id": "run-search",
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    **action_step,
                    "requires_post_action_verification": False,
                    "steps": [action_step, verify_step],
                },
            },
        ],
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize(
    "action_tool",
    [
        "app.open_and_safe_key",
        "app.open_and_safe_scroll",
        "app.open_and_safe_click",
    ],
)
def test_evaluator_preserves_scoped_compound_verifier_over_aggregate_step_projection(
    action_tool: str,
) -> None:
    action_step = {
        "decision_id": "decision-compound",
        "plan_id": "plan-compound",
        "step_id": "operate-foreground",
        "tool": action_tool,
        "input_preview": {"app_name": "Google Chrome"},
        "requires_post_action_verification": True,
        "result": {"ok": True, "data": {"app_name": "Google Chrome"}},
    }
    verify_step = {
        "decision_id": "decision-compound",
        "plan_id": "plan-compound",
        "step_id": "verify-foreground",
        "tool": "desktop.ui_elements",
        "source": "runtime_verification",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "verification_target_step_ids": ["operate-foreground"],
        "result": {
            "ok": True,
            "data": {
                "app_name": "Google Chrome",
                "elements": [{"role": "AXWindow", "name": "Google Chrome"}],
            },
        },
    }
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-compound"},
        [
            {
                "run_id": "run-compound",
                "event_type": "agent.tool.call",
                "payload": action_step,
            },
            {
                "run_id": "run-compound",
                "event_type": "agent.tool.call",
                "payload": verify_step,
            },
            {
                "run_id": "run-compound",
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    **action_step,
                    "requires_post_action_verification": False,
                    "steps": [action_step, verify_step],
                },
            },
        ],
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize("action_tool", ["desktop.open_path", "desktop.reveal_path"])
def test_evaluator_preserves_scoped_native_receipt_over_aggregate_step_projection(
    action_tool: str,
) -> None:
    action_step = {
        "decision_id": "decision-path",
        "plan_id": "plan-path",
        "request_id": f"request:{action_tool}",
        "tool_call_id": f"call:{action_tool}",
        "step_id": "operate-path",
        "tool": action_tool,
        "input_preview": {"path": "~/Downloads/report.pdf"},
        "requires_post_action_verification": True,
        "result": {"ok": True, "data": {"exists": True}},
    }
    canonical_verifier = {
        "decision_id": "decision-path",
        "plan_id": "plan-path",
        "source_request_id": f"request:{action_tool}",
        "source_tool_call_id": f"call:{action_tool}",
        "step_id": "operate-path:runtime-verify",
        "source_step_id": "operate-path",
        "tool": "desktop.ui_elements",
        "source": "runtime_native_postcondition_receipt",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "result": {
            "ok": True,
            "postcondition_verified": True,
            "verification_satisfied_by_native_receipt": True,
            "source_tool": action_tool,
            "source_step_id": "operate-path",
        },
    }
    aggregate_verifier = {
        key: value
        for key, value in canonical_verifier.items()
        if key not in {"source_request_id", "source_tool_call_id"}
    }
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-path"},
        [
            {
                "run_id": "run-path",
                "event_type": "agent.tool.call",
                "payload": action_step,
            },
            {
                "run_id": "run-path",
                "event_type": "agent.tool.call",
                "payload": canonical_verifier,
            },
            {
                "run_id": "run-path",
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    **action_step,
                    "requires_post_action_verification": False,
                    "steps": [action_step, aggregate_verifier],
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def _aggregate_failed_open_path_retry_outcome(
    *,
    request_id: str,
    tool_call_id: str,
) -> MainChatOutcomeEvaluation:
    action_step = {
        "run_id": "run-path-failed-copy",
        "decision_id": "decision-path-failed-copy",
        "plan_id": "plan-path-failed-copy",
        "attempt_id": "attempt-path-failed-copy",
        "request_id": "request-old",
        "tool_call_id": "call-old",
        "step_id": "open-path",
        "tool": "desktop.open_path",
        "requires_post_action_verification": True,
        "result": {"ok": True, "data": {"exists": True}},
    }
    canonical_verifier = {
        "run_id": "run-path-failed-copy",
        "decision_id": "decision-path-failed-copy",
        "plan_id": "plan-path-failed-copy",
        "attempt_id": "attempt-path-failed-copy",
        "source_request_id": "request-old",
        "source_tool_call_id": "call-old",
        "step_id": "verify-path",
        "source_step_id": "open-path",
        "tool": "desktop.ui_elements",
        "source": "runtime_native_postcondition_receipt",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "result": {
            "ok": True,
            "postcondition_verified": True,
            "verification_satisfied_by_native_receipt": True,
            "source_tool": "desktop.open_path",
            "source_step_id": "open-path",
        },
    }
    failed_child = {
        **action_step,
        "request_id": request_id,
        "tool_call_id": tool_call_id,
        "result": {
            "ok": False,
            "verification_failed": True,
            "error": "open path retry failed",
        },
    }
    return evaluate_main_chat_outcome(
        {"run_id": "run-path-failed-copy"},
        [
            {
                "run_id": "run-path-failed-copy",
                "event_type": "agent.tool.call",
                "payload": action_step,
            },
            {
                "run_id": "run-path-failed-copy",
                "event_type": "agent.tool.call",
                "payload": canonical_verifier,
            },
            {
                "run_id": "run-path-failed-copy",
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    **action_step,
                    "requires_post_action_verification": False,
                    "steps": [failed_child],
                },
            },
        ],
    )


def test_evaluator_does_not_hide_failed_aggregate_child_as_action_copy() -> None:
    outcome = _aggregate_failed_open_path_retry_outcome(
        request_id="request-old",
        tool_call_id="call-old",
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_failed"


def test_evaluator_does_not_hide_new_identity_failed_aggregate_retry() -> None:
    outcome = _aggregate_failed_open_path_retry_outcome(
        request_id="request-new",
        tool_call_id="call-new",
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_failed"


@pytest.mark.parametrize(
    ("scope_key", "outer_value", "conflicting_value"),
    [
        ("run_id", "run-path", "run-forged"),
        ("decision_id", "decision-path", "decision-forged"),
        ("plan_id", "plan-path", "plan-forged"),
        ("attempt_id", "attempt-path", "attempt-forged"),
    ],
)
def test_evaluator_does_not_overwrite_conflicting_aggregate_receipt_scope(
    scope_key: str,
    outer_value: str,
    conflicting_value: str,
) -> None:
    scope = {
        "decision_id": "decision-path",
        "plan_id": "plan-path",
        "attempt_id": "attempt-path",
    }
    action_step = {
        **scope,
        "step_id": "open-path",
        "tool": "desktop.open_path",
        "requires_post_action_verification": True,
        "result": {"ok": True, "data": {"exists": True}},
    }
    verifier_step = {
        **scope,
        scope_key: conflicting_value,
        "step_id": "verify-path",
        "source_step_id": "open-path",
        "tool": "desktop.ui_elements",
        "source": "runtime_native_postcondition_receipt",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "result": {
            "ok": True,
            "postcondition_verified": True,
            "verification_satisfied_by_native_receipt": True,
            "source_tool": "desktop.open_path",
            "source_step_id": "open-path",
        },
    }
    aggregate_scope = {**scope, scope_key: outer_value}
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-path"},
        [
            {
                "run_id": "run-path",
                "event_type": "agent.tool.call",
                "payload": action_step,
            },
            {
                "run_id": "run-path",
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    **action_step,
                    **aggregate_scope,
                    "requires_post_action_verification": False,
                    "steps": [action_step, verifier_step],
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


@pytest.mark.parametrize(
    ("scope_key", "outer_value", "forged_value"),
    [
        ("run_id", "run-path-nested", "run-forged"),
        ("attempt_id", "attempt-path-nested", "attempt-forged"),
    ],
)
def test_evaluator_rejects_nested_aggregate_receipt_scope_forgery(
    scope_key: str,
    outer_value: str,
    forged_value: str,
) -> None:
    scope = {
        "decision_id": "decision-path-nested",
        "plan_id": "plan-path-nested",
        "attempt_id": "attempt-path-nested",
    }
    action_step = {
        **scope,
        "step_id": "open-path",
        "tool": "desktop.open_path",
        "requires_post_action_verification": True,
        "result": {"ok": True, "data": {"exists": True}},
    }
    verifier_step = {
        **scope,
        "step_id": "verify-path",
        "source_step_id": "open-path",
        "tool": "desktop.ui_elements",
        "source": "runtime_native_postcondition_receipt",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "result": {
            "ok": True,
            "postcondition_verified": True,
            "verification_satisfied_by_native_receipt": True,
            "source_tool": "desktop.open_path",
            "source_step_id": "open-path",
            "data": {scope_key: forged_value},
        },
    }
    verifier_step.pop(scope_key, None)
    aggregate_scope = {**scope, scope_key: outer_value}
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-path-nested"},
        [
            {
                "run_id": "run-path-nested",
                "event_type": "agent.tool.call",
                "payload": action_step,
            },
            {
                "run_id": "run-path-nested",
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    **action_step,
                    **aggregate_scope,
                    "requires_post_action_verification": False,
                    "steps": [action_step, verifier_step],
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def _aggregate_path_action_copy_events(
    *,
    copy_request_id: str,
    copy_tool_call_id: str,
    copy_result: dict[str, Any],
) -> list[dict[str, Any]]:
    action = {
        "decision_id": "decision-aggregate-copy",
        "plan_id": "plan-aggregate-copy",
        "request_id": "request-original",
        "tool_call_id": "call-original",
        "step_id": "open-path",
        "tool": "desktop.open_path",
        "input_preview": {"path": "~/Downloads/report.pdf"},
        "requires_post_action_verification": True,
        "result": {"ok": True, "data": {"exists": True}},
    }
    receipt = {
        "decision_id": "decision-aggregate-copy",
        "plan_id": "plan-aggregate-copy",
        "source_request_id": "request-original",
        "source_tool_call_id": "call-original",
        "step_id": "verify-path",
        "source_step_id": "open-path",
        "tool": "desktop.ui_elements",
        "source": "runtime_native_postcondition_receipt",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "result": {
            "ok": True,
            "postcondition_verified": True,
            "verification_satisfied_by_native_receipt": True,
            "source_tool": "desktop.open_path",
            "source_step_id": "open-path",
        },
    }
    aggregate_copy = {
        **action,
        "request_id": copy_request_id,
        "tool_call_id": copy_tool_call_id,
        "result": copy_result,
    }
    return [
        {
            "run_id": "run-aggregate-copy",
            "event_type": "agent.tool.call",
            "payload": action,
        },
        {
            "run_id": "run-aggregate-copy",
            "event_type": "agent.tool.call",
            "payload": receipt,
        },
        {
            "run_id": "run-aggregate-copy",
            "event_type": "agent.desktop.intent_completed",
            "payload": {
                **action,
                "requires_post_action_verification": False,
                "steps": [aggregate_copy],
            },
        },
    ]


def test_evaluator_does_not_hide_failed_aggregate_action_copy() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-aggregate-copy"},
        _aggregate_path_action_copy_events(
            copy_request_id="request-original",
            copy_tool_call_id="call-original",
            copy_result={
                "ok": False,
                "verification_failed": True,
                "error": "late aggregate failure",
            },
        ),
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_failed"


def test_evaluator_does_not_deduplicate_new_retry_as_aggregate_action_copy() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-aggregate-copy"},
        _aggregate_path_action_copy_events(
            copy_request_id="request-retry",
            copy_tool_call_id="call-retry",
            copy_result={"ok": False, "error": "new retry failed"},
        ),
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_tool_failed"


def test_evaluator_keeps_aggregate_content_verification_semantic_and_fail_closed() -> None:
    action_step = {
        "decision_id": "decision-content-negative",
        "plan_id": "plan-content-negative",
        "step_id": "type-content",
        "tool": "desktop.safe_type_text",
        "runtime_role": "type_ui",
        "input_preview": {"app_name": "Notes", "text": "hello yachiyo"},
        "requires_post_action_verification": True,
        "result": {"ok": True, "data": {"character_count": 13}},
    }
    verify_step = {
        "decision_id": "decision-content-negative",
        "plan_id": "plan-content-negative",
        "step_id": "verify-content",
        "tool": "desktop.ui_elements",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "verification_target_step_ids": ["type-content"],
        "result": {
            "ok": True,
            "data": {
                "app_name": "Notes",
                "elements": [{"role": "AXWindow", "name": "Notes"}],
            },
        },
    }
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-content-negative"},
        [
            {
                "run_id": "run-content-negative",
                "event_type": "agent.tool.call",
                "payload": action_step,
            },
            {
                "run_id": "run-content-negative",
                "event_type": "agent.tool.call",
                "payload": verify_step,
            },
            {
                "run_id": "run-content-negative",
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    **action_step,
                    "requires_post_action_verification": False,
                    "steps": [action_step, verify_step],
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_does_not_let_aggregate_completion_hide_prior_plan_failure() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.failed",
                "payload": {
                    "decision_id": "decision-sequence",
                    "plan_id": "plan-sequence",
                    "step_id": "type-message",
                    "tool": "desktop.safe_type_text",
                    "result": {"ok": False, "error": "typing failed"},
                },
            },
            {
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    "decision_id": "decision-sequence",
                    "plan_id": "plan-sequence",
                    "tool": "app.open",
                    "result": {
                        "ok": True,
                        "launch_verified": True,
                        "data": {"app_name": "Notes"},
                    },
                    "steps": [
                        {
                            "decision_id": "decision-sequence",
                            "plan_id": "plan-sequence",
                            "step_id": "open-notes",
                            "tool": "app.open",
                            "input_preview": {"app_name": "Notes"},
                            "result": {
                                "ok": True,
                                "launch_verified": True,
                                "data": {"app_name": "Notes"},
                            },
                        }
                    ],
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_tool_failed"


def test_evaluator_allows_correlated_retry_to_supersede_prior_plan_failure() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.failed",
                "payload": {
                    "decision_id": "decision-retry",
                    "plan_id": "plan-retry",
                    "request_id": "request-open-notes",
                    "step_id": "open-notes",
                    "tool": "app.open",
                    "result": {"ok": False, "error": "launch failed"},
                },
            },
            {
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    "decision_id": "decision-retry",
                    "plan_id": "plan-retry",
                    "request_id": "request-open-notes",
                    "step_id": "open-notes",
                    "tool": "app.open",
                    "result": {
                        "ok": True,
                        "launch_verified": True,
                        "data": {"app_name": "Notes"},
                    },
                    "steps": [
                        {
                            "decision_id": "decision-retry",
                            "plan_id": "plan-retry",
                            "request_id": "request-open-notes",
                            "step_id": "open-notes",
                            "tool": "app.open",
                            "result": {
                                "ok": True,
                                "launch_verified": True,
                                "data": {"app_name": "Notes"},
                            },
                        }
                    ],
                },
            },
        ],
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize(
    ("tool", "status_key", "status"),
    [
        ("app.show", "show_status", "unknown"),
        ("app.show", "show_status", "unverified"),
        ("app.hide", "hide_status", "unknown"),
        ("app.minimize", "minimize_status", "unknown"),
    ],
)
def test_evaluator_does_not_use_running_app_as_management_postcondition(
    tool: str,
    status_key: str,
    status: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "manage-app",
                    "tool": tool,
                    "input_preview": {"app_name": "Slack"},
                    "result": {
                        "ok": True,
                        "data": {"app_name": "Slack", status_key: status},
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-desktop-result",
                    "tool": "desktop.running_apps",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "verification_target_step_ids": ["manage-app"],
                    "result": {
                        "ok": True,
                        "data": {
                            "apps": [{"name": "Slack", "frontmost": False}],
                            "count": 1,
                            "frontmost": "Finder",
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


@pytest.mark.parametrize(
    ("tool", "verified_key"),
    [
        ("app.show", "show_verified"),
        ("app.hide", "hide_verified"),
        ("app.minimize", "minimize_verified"),
    ],
)
def test_evaluator_accepts_explicit_app_management_verified_receipt(
    tool: str,
    verified_key: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "manage-app",
                    "tool": tool,
                    "input_preview": {"app_name": "Slack"},
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {"app_name": "Slack", verified_key: True},
                    },
                },
            }
        ],
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize(
    ("tool", "status_key", "status", "verified_key"),
    [
        ("app.show", "show_status", "shown", "show_verified"),
        ("app.hide", "hide_status", "hidden", "hide_verified"),
        ("app.minimize", "minimize_status", "minimized", "minimize_verified"),
    ],
)
def test_evaluator_rejects_conflicting_app_management_receipt(
    tool: str,
    status_key: str,
    status: str,
    verified_key: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "manage-app",
                    "tool": tool,
                    "input_preview": {"app_name": "Slack"},
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Slack",
                            status_key: status,
                            verified_key: False,
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "failed"


def test_evaluator_accepts_native_focus_window_receipt_with_matching_title() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "focus-window",
                    "tool": "app.focus_window",
                    "input_preview": {
                        "app_name": "Slack",
                        "title_contains": "general",
                    },
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Slack",
                            "focus_status": "focused",
                            "window_title": "Slack — general",
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-desktop-result",
                    "tool": "desktop.running_apps",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "verification_target_step_ids": ["focus-window"],
                    "result": {
                        "ok": True,
                        "data": {"apps": [{"name": "Slack"}], "frontmost": "Slack"},
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_accepts_correlated_native_receipt_verifier_projection() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-window-focus",
                    "step_id": "focus-window",
                    "tool": "app.focus_window",
                    "input_preview": {
                        "app_name": "Slack",
                        "title_contains": "general",
                    },
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Slack",
                            "matched_window_title": "general - Slack",
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-window-focus",
                    "step_id": "verify-window-focus",
                    "tool": "desktop.verify",
                    "source": "runtime_native_postcondition_receipt",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "result": {
                        "ok": True,
                        "postcondition_verified": True,
                        "verification_satisfied_by_native_receipt": True,
                        "source_tool": "app.focus_window",
                        "source_step_id": "focus-window",
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_accepts_exact_native_receipt_after_dynamic_target_resolution() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-dynamic-path"},
        [
            {
                "run_id": "run-dynamic-path",
                "event_type": "agent.tool.call",
                "payload": {
                    "run_id": "run-dynamic-path",
                    "decision_id": "decision-dynamic-path",
                    "plan_id": "plan-dynamic-path",
                    "request_id": "plan-dynamic-path:request:2:desktop.open_path_with_app",
                    "tool_call_id": "call-dynamic-path",
                    "step_id": "open-selected-discovered-app",
                    "tool": "desktop.open_path_with_app",
                    "input_preview": {
                        "app_name": "PixelForge",
                        "path": "Downloads/report.pdf",
                    },
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "PixelForge",
                            "exists": True,
                            "open_target": "app_open",
                            "path": "Downloads/report.pdf",
                        },
                    },
                },
            },
            {
                "run_id": "run-dynamic-path",
                "event_type": "agent.tool.call",
                "payload": {
                    "run_id": "run-dynamic-path",
                    "decision_id": "decision-dynamic-path",
                    "plan_id": "plan-dynamic-path",
                    "request_id": "plan-dynamic-path:request:3:desktop.ui_elements",
                    "source_request_id": (
                        "plan-dynamic-path:request:2:desktop.open_path_with_app"
                    ),
                    "source_tool_call_id": "call-dynamic-path",
                    "source_step_id": "open-selected-discovered-app",
                    "step_id": "verify-desktop-result",
                    "tool": "desktop.ui_elements",
                    "source": "runtime_native_postcondition_receipt",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "input_preview": {
                        "app_name": "<selected app from desktop.list_apps>",
                        "limit": 80,
                    },
                    "action_target": {
                        "app_name": "<selected app from desktop.list_apps>",
                        "verified_step_ids": ["open-selected-discovered-app"],
                    },
                    "result": {
                        "ok": True,
                        "postcondition_verified": True,
                        "verification_satisfied_by_native_receipt": True,
                        "source_tool": "desktop.open_path_with_app",
                        "source_step_id": "open-selected-discovered-app",
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


@pytest.mark.parametrize(
    ("action_tool", "result"),
    [
        (
            "system.volume",
            {
                "ok": True,
                "action": "system.volume",
                "data": {
                    "requested_action": "set",
                    "level": 30,
                    "muted": False,
                },
            },
        ),
        (
            "desktop.show_all_apps",
            {
                "ok": True,
                "action": "desktop.show_all_apps",
                "data": {"shown_app_count": 2},
            },
        ),
    ],
)
def test_evaluator_accepts_correlated_intrinsic_system_receipt_projection(
    action_tool: str,
    result: dict[str, object],
) -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-system"},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "run_id": "run-system",
                    "plan_id": "plan-system",
                    "step_id": "operate-system",
                    "tool": action_tool,
                    "requires_post_action_verification": True,
                    "result": result,
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "run_id": "run-system",
                    "plan_id": "plan-system",
                    "step_id": "verify-system",
                    "source_step_id": "operate-system",
                    "depends_on": ["operate-system"],
                    "tool": (
                        "system.volume"
                        if action_tool == "system.volume"
                        else "desktop.active_window"
                    ),
                    "source": "runtime_native_postcondition_receipt",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "result": {
                        "ok": True,
                        "postcondition_verified": True,
                        "verification_satisfied_by_native_receipt": True,
                        "source_tool": action_tool,
                        "source_step_id": "operate-system",
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_rejects_generic_native_receipt_for_a_different_source_tool() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-path-receipt"},
        [
            {
                "run_id": "run-path-receipt",
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-path-receipt",
                    "step_id": "open-path",
                    "tool": "desktop.open_path",
                    "requires_post_action_verification": True,
                    "result": {"ok": True, "data": {"exists": True}},
                },
            },
            {
                "run_id": "run-path-receipt",
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-path-receipt",
                    "step_id": "verify-path",
                    "source_step_id": "open-path",
                    "tool": "desktop.ui_elements",
                    "source": "runtime_native_postcondition_receipt",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "result": {
                        "ok": True,
                        "postcondition_verified": True,
                        "verification_satisfied_by_native_receipt": True,
                        "source_tool": "desktop.reveal_path",
                        "source_step_id": "open-path",
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_rejects_native_receipt_bound_to_an_old_call_identity() -> None:
    outcome = evaluate_main_chat_outcome(
        {"run_id": "run-path-identity"},
        [
            {
                "run_id": "run-path-identity",
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-path-identity",
                    "plan_id": "plan-path-identity",
                    "request_id": "request-new",
                    "tool_call_id": "call-new",
                    "step_id": "open-path",
                    "tool": "desktop.open_path",
                    "requires_post_action_verification": True,
                    "result": {"ok": True, "data": {"exists": True}},
                },
            },
            {
                "run_id": "run-path-identity",
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-path-identity",
                    "plan_id": "plan-path-identity",
                    "source_request_id": "request-old",
                    "source_tool_call_id": "call-old",
                    "step_id": "verify-path",
                    "source_step_id": "open-path",
                    "tool": "desktop.ui_elements",
                    "source": "runtime_native_postcondition_receipt",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "result": {
                        "ok": True,
                        "postcondition_verified": True,
                        "verification_satisfied_by_native_receipt": True,
                        "source_tool": "desktop.open_path",
                        "source_step_id": "open-path",
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_ignores_foreground_session_notice_as_an_action() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.foreground_session_notice",
                "payload": {
                    "plan_id": "plan-window-focus",
                    "step_id": "focus-window",
                    "tool": "app.focus_window",
                    "requires_post_action_verification": True,
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-window-focus",
                    "step_id": "focus-window",
                    "tool": "app.focus_window",
                    "input_preview": {
                        "app_name": "Slack",
                        "title_contains": "general",
                    },
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Slack",
                            "matched_window_title": "general - Slack",
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-window-focus",
                    "step_id": "verify-window-focus",
                    "tool": "desktop.verify",
                    "source": "runtime_native_postcondition_receipt",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "result": {
                        "ok": True,
                        "postcondition_verified": True,
                        "verification_satisfied_by_native_receipt": True,
                        "source_tool": "app.focus_window",
                        "source_step_id": "focus-window",
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_rejects_native_receipt_verifier_from_another_plan() -> None:
    events = [
        {
            "event_type": "agent.tool.call",
            "payload": {
                "plan_id": "plan-window-focus",
                "step_id": "focus-window",
                "tool": "app.focus_window",
                "input_preview": {
                    "app_name": "Slack",
                    "title_contains": "general",
                },
                "requires_post_action_verification": True,
                "result": {
                    "ok": True,
                    "data": {
                        "app_name": "Slack",
                        "matched_window_title": "general - Slack",
                    },
                },
            },
        },
        {
            "event_type": "agent.tool.call",
            "payload": {
                "plan_id": "different-plan",
                "step_id": "verify-window-focus",
                "tool": "desktop.verify",
                "source": "runtime_native_postcondition_receipt",
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "result": {
                    "ok": True,
                    "postcondition_verified": True,
                    "verification_satisfied_by_native_receipt": True,
                    "source_tool": "app.focus_window",
                    "source_step_id": "focus-window",
                },
            },
        },
    ]

    outcome = evaluate_main_chat_outcome({}, events)

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_rejects_generic_verifier_from_another_plan() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-type-a",
                    "step_id": "type-message",
                    "tool": "desktop.safe_type_text",
                    "input_preview": {
                        "app_name": "Notes",
                        "text": "hello world",
                    },
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {"app_name": "Notes"},
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-type-b",
                    "source_step_id": "type-message",
                    "step_id": "type-message:runtime-verify",
                    "tool": "desktop.ui_elements",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Notes",
                            "elements": [
                                {
                                    "role": "AXTextArea",
                                    "editable": True,
                                    "value": "hello world",
                                }
                            ],
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_accepts_legacy_verifier_with_explicit_request_correlation() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "plan_id": "plan-type",
                    "request_id": "request-type-message",
                    "step_id": "type-message",
                    "tool": "desktop.safe_type_text",
                    "input_preview": {
                        "app_name": "Notes",
                        "text": "hello world",
                    },
                    "requires_post_action_verification": True,
                    "result": {"ok": True, "data": {"app_name": "Notes"}},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "source_request_id": "request-type-message",
                    "source_step_id": "type-message",
                    "step_id": "type-message:runtime-verify",
                    "tool": "desktop.ui_elements",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Notes",
                            "elements": [
                                {
                                    "role": "AXTextArea",
                                    "editable": True,
                                    "value": "hello world",
                                }
                            ],
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_rejects_focus_window_receipt_for_wrong_title() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "focus-window",
                    "tool": "app.focus_window",
                    "input_preview": {
                        "app_name": "Slack",
                        "title_contains": "general",
                    },
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Slack",
                            "focus_status": "focused",
                            "window_title": "Slack — random",
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_ignores_wrong_app_ui_failure_for_verified_background_media() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "control-media-playback",
                    "tool": "media.music_app_open_and_play",
                    "input_preview": {"app_name": "Music"},
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Music",
                            "control": "play",
                            "playback_ok": True,
                            "player_state": "playing",
                            "track": "超时空辉夜姬",
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-media-playback",
                    "tool": "desktop.ui_elements",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "verification_target_step_ids": ["control-media-playback"],
                    "result": {
                        "ok": True,
                        "verification_failed": True,
                        "data": {
                            "app_name": "ChatGPT",
                            "elements": [],
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_keeps_unverified_system_media_control_fail_closed() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "control-media-playback",
                    "tool": "media.system_control",
                    "input_preview": {"action": "next"},
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "data": {
                            "control": "next",
                            "player_state": "unknown",
                            "playback_state_unverified": True,
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-media-playback",
                    "tool": "desktop.ui_elements",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "verification_target_step_ids": ["control-media-playback"],
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Music",
                            "elements": [
                                {"role": "AXWindow", "name": "Music"},
                            ],
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_does_not_treat_later_track_status_as_next_track_proof() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "control-media-playback",
                    "tool": "media.system_control",
                    "input_preview": {"action": "next"},
                    "result": {
                        "ok": True,
                        "data": {
                            "control": "next",
                            "player_state": "unknown",
                            "playback_state_unverified": True,
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-media-playback",
                    "verification_target_step_ids": ["control-media-playback"],
                    "tool": "media.apple_music_status",
                    "result": {
                        "ok": True,
                        "data": {
                            "player_state": "playing",
                            "track": "Any currently visible track",
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_rejects_apple_status_as_spotify_playback_proof() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "control-media-playback",
                    "tool": "media.music_app_control",
                    "input_preview": {"app_name": "Spotify", "action": "play"},
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Spotify",
                            "control": "play",
                            "player_state": "unknown",
                            "playback_state_unverified": True,
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-media-playback",
                    "verification_target_step_ids": ["control-media-playback"],
                    "tool": "media.apple_music_status",
                    "result": {
                        "ok": True,
                        "data": {
                            "player_state": "playing",
                            "track": "Different player",
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_accepts_explicit_linked_track_change_proof() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "control-media-playback",
                    "tool": "media.apple_music_control",
                    "input_preview": {"action": "next"},
                    "result": {
                        "ok": True,
                        "data": {
                            "control": "next",
                            "player_state": "unknown",
                            "playback_state_unverified": True,
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "verify-media-playback",
                    "verification_target_step_ids": ["control-media-playback"],
                    "tool": "media.apple_music_status",
                    "result": {
                        "ok": True,
                        "data": {
                            "player_state": "playing",
                            "track": "New track",
                            "track_changed": True,
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_preserves_unverified_desktop_event_reason_and_copy() -> None:
    message = "已发送媒体控制请求，但无法确认播放状态。"
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.intent_unverified",
                "payload": {
                    "tool": "media.system_control",
                    "status": "failed",
                    "reason": "desktop_verification_missing",
                    "error": message,
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"
    assert outcome.message == message


def test_evaluator_does_not_reuse_postcondition_from_other_attempt_or_target() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "sequence": 10,
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    "attempt_id": "attempt-2",
                    "tool": "app.open",
                    "input_preview": {"app_name": "Calculator"},
                    "result": {
                        "ok": True,
                        "data": {"app_name": "Calculator"},
                    },
                },
            },
            {
                "sequence": 11,
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-1",
                    "tool": "desktop.active_window",
                    "verification_target": {"app_name": "Finder"},
                    "result": {"ok": True, "data": {"app_name": "Finder"}},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_does_not_reuse_postcondition_that_precedes_the_action() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "sequence": 10,
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-foreground-return",
                    "step_id": "operate-foreground-ui-followup-return",
                    "tool": "desktop.ui_elements",
                    "verification_target": {
                        "target": "github.com",
                        "step_id": "operate-foreground-ui-followup-return",
                    },
                    "result": {
                        "ok": True,
                        "data": {"target": "github.com", "elements": []},
                    },
                },
            },
            {
                "sequence": 11,
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-foreground-return",
                    "step_id": "operate-foreground-ui-followup-return",
                    "tool": "desktop.hotkey",
                    "requires_post_action_verification": True,
                    "action_target": {
                        "target": "github.com",
                        "step_id": "operate-foreground-ui-followup-return",
                    },
                    "result": {"ok": True},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_accepts_fresh_postcondition_for_the_same_action_identity() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "sequence": 10,
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-foreground-return",
                    "step_id": "operate-foreground-ui-followup-return",
                    "tool": "desktop.hotkey",
                    "requires_post_action_verification": True,
                    "action_target": {
                        "target": "github.com",
                        "step_id": "operate-foreground-ui-followup-return",
                    },
                    "result": {"ok": True},
                },
            },
            {
                "sequence": 11,
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-foreground-return",
                    "source_step_id": "operate-foreground-ui-followup-return",
                    "step_id": "operate-foreground-ui-followup-return:runtime-verify",
                    "tool": "desktop.ui_elements",
                    "verification_target": {
                        "target": "github.com",
                        "step_id": "operate-foreground-ui-followup-return",
                    },
                    "result": {
                        "ok": True,
                        "data": {
                            "target": "github.com",
                            "elements": [{"role": "AXTextField", "name": "github.com"}],
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_rejects_empty_ui_elements_as_postcondition_evidence() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-empty-ui",
                    "step_id": "open-calculator",
                    "tool": "app.open",
                    "input_preview": {"app_name": "Calculator"},
                    "result": {"ok": True, "data": {"app_name": "Calculator"}},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-empty-ui",
                    "source_step_id": "open-calculator",
                    "step_id": "open-calculator:runtime-verify",
                    "tool": "desktop.ui_elements",
                    "input_preview": {"app_name": "Calculator"},
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "Calculator",
                            "elements": [],
                            "count": 0,
                            "text": "   ",
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_rejects_postcondition_observed_in_wrong_app() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-wrong-app",
                    "step_id": "open-calculator",
                    "tool": "app.open",
                    "input_preview": {"app_name": "Calculator"},
                    "result": {"ok": True, "data": {"app_name": "Calculator"}},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-wrong-app",
                    "source_step_id": "open-calculator",
                    "step_id": "open-calculator:runtime-verify",
                    "tool": "desktop.active_window",
                    "verification_target": {"app_name": "Calculator"},
                    "result": {
                        "ok": True,
                        "data": {"app_name": "Finder", "title": "Downloads"},
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_uses_latest_correlated_observation_even_when_it_is_empty() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-latest-empty",
                    "step_id": "click-login",
                    "tool": "desktop.click_ui_element",
                    "requires_post_action_verification": True,
                    "input_preview": {"app_name": "PixelForge", "target": "Login"},
                    "result": {"ok": True},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-latest-empty",
                    "source_step_id": "click-login",
                    "step_id": "click-login:runtime-verify",
                    "tool": "desktop.ui_elements",
                    "input_preview": {"app_name": "PixelForge", "target": "Login"},
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "PixelForge",
                            "elements": [{"role": "AXButton", "name": "Login"}],
                        },
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-latest-empty",
                    "source_step_id": "click-login",
                    "step_id": "click-login:runtime-verify",
                    "tool": "desktop.ui_elements",
                    "input_preview": {"app_name": "PixelForge", "target": "Login"},
                    "result": {
                        "ok": True,
                        "data": {"app_name": "PixelForge", "elements": [], "count": 0},
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_accepts_nonempty_ui_evidence_for_the_same_app_and_target() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-valid-ui",
                    "step_id": "click-login",
                    "tool": "desktop.click_ui_element",
                    "requires_post_action_verification": True,
                    "input_preview": {"app_name": "PixelForge", "target": "Login"},
                    "result": {"ok": True},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-valid-ui",
                    "source_step_id": "click-login",
                    "step_id": "click-login:runtime-verify",
                    "tool": "desktop.ui_elements",
                    "input_preview": {"app_name": "PixelForge", "target": "Login"},
                    "result": {
                        "ok": True,
                        "data": {
                            "app_name": "PixelForge",
                            "elements": [
                                {"role": "AXButton", "name": "Login", "enabled": True}
                            ],
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_requires_label_target_to_match_observed_ui_element() -> None:
    action = {
        "event_type": "agent.tool.call",
        "payload": {
            "attempt_id": "attempt-save-label",
            "step_id": "click-save",
            "tool": "desktop.click_ui_element",
            "requires_post_action_verification": True,
            "input_preview": {"app_name": "PixelForge", "label": "Save"},
            "result": {"ok": True},
        },
    }
    unrelated = {
        "event_type": "agent.tool.call",
        "payload": {
            "attempt_id": "attempt-save-label",
            "source_step_id": "click-save",
            "step_id": "click-save:runtime-verify",
            "tool": "desktop.ui_elements",
            "input_preview": {"app_name": "PixelForge", "label": "Save"},
            "result": {
                "ok": True,
                "data": {
                    "app_name": "PixelForge",
                    "elements": [{"role": "AXButton", "name": "Cancel"}],
                },
            },
        },
    }

    outcome = evaluate_main_chat_outcome({}, [action, unrelated])

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_rejects_fresh_postcondition_from_another_attempt() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "sequence": 10,
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-return-2",
                    "step_id": "operate-foreground-ui-followup-return",
                    "target": "github.com",
                    "tool": "desktop.hotkey",
                    "requires_post_action_verification": True,
                    "result": {"ok": True, "data": {"target": "github.com"}},
                },
            },
            {
                "sequence": 11,
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-return-1",
                    "source_step_id": "operate-foreground-ui-followup-return",
                    "step_id": "operate-foreground-ui-followup-return:runtime-verify",
                    "target": "github.com",
                    "tool": "desktop.ui_elements",
                    "result": {"ok": True, "data": {"target": "github.com"}},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_rejects_fresh_postcondition_from_another_step() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "sequence": 10,
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-foreground-sequence",
                    "step_id": "operate-foreground-ui-followup-return",
                    "target": "github.com",
                    "tool": "desktop.hotkey",
                    "requires_post_action_verification": True,
                    "result": {"ok": True, "data": {"target": "github.com"}},
                },
            },
            {
                "sequence": 11,
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-foreground-sequence",
                    "source_step_id": "operate-foreground-ui-followup-type",
                    "step_id": "operate-foreground-ui-followup-type:runtime-verify",
                    "target": "github.com",
                    "tool": "desktop.ui_elements",
                    "result": {"ok": True, "data": {"target": "github.com"}},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_uses_parent_attempt_when_nested_steps_omit_attempt_id() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    "attempt_id": "attempt-2",
                    "tool": "app.open",
                    "input_preview": {"app_name": "Calculator"},
                    "result": {"ok": True, "data": {"app_name": "Calculator"}},
                    "steps": [
                        {
                            "tool": "app.open",
                            "input_preview": {"app_name": "Calculator"},
                            "result": {"ok": True},
                        }
                    ],
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-1",
                    "tool": "desktop.active_window",
                    "verification_target": {"app_name": "Calculator"},
                    "result": {
                        "ok": True,
                        "data": {"app_name": "Calculator"},
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_requires_postcondition_target_to_match_action_target() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    "attempt_id": "attempt-2",
                    "request_id": "open-calculator",
                    "step_id": "open-app",
                    "tool": "app.open",
                    "input_preview": {"app_name": "Calculator"},
                    "result": {"ok": True},
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "attempt_id": "attempt-2",
                    "request_id": "verify-finder",
                    "step_id": "verify-app",
                    "tool": "desktop.active_window",
                    "verification_target": {"app_name": "Finder"},
                    "result": {"ok": True, "data": {"app_name": "Finder"}},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_uses_latest_successful_recovery_fact_over_older_false() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    "attempt_id": "attempt-recovery",
                    "tool": "desktop.active_window",
                    "verification_target": {"app_name": "Calculator"},
                    "focus_verified": True,
                    "result": {
                        "ok": True,
                        "focus_verified": True,
                        "data": {"app_name": "Calculator"},
                    },
                    "steps": [
                        {
                            "tool": "app.open",
                            "input_preview": {"app_name": "Calculator"},
                            "result": {"ok": True, "focus_verified": False},
                        },
                        {
                            "tool": "desktop.active_window",
                            "verification_target": {"app_name": "Calculator"},
                            "result": {
                                "ok": True,
                                "focus_verified": True,
                                "data": {"app_name": "Calculator"},
                            },
                        },
                    ],
                },
            }
        ],
    )

    assert outcome.kind == "completed"


def test_evaluator_rejects_success_payload_with_blocking_conditions() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            _desktop_event(
                {
                    "ok": True,
                    "blocking_conditions": ["desktop_session_locked"],
                    "data": {"launch_verified": True},
                }
            )
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_tool_failed"


def test_evaluator_rejects_requested_screen_capture_permission_failure() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.intent_completed",
                "payload": {
                    "tool": "screen.capture",
                    "input_preview": {"reason": "user asked to capture the screen"},
                    "result": {
                        "ok": False,
                        "permission_error": True,
                        "permission_targets": ["screen_recording"],
                        "error": "screen recording permission denied",
                    },
                },
            },
            {
                "event_type": "agent.desktop.permission_recovery",
                "payload": {
                    "tool": "screen.capture",
                    "status": "permission_recovery_available",
                    "permission_targets": ["screen_recording"],
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_permission_required"
    assert outcome.desktop_observed is True


def test_evaluator_accepts_successful_permission_diagnostic_with_reported_blockers() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "diagnose-desktop-permissions",
                    "tool": "desktop.permissions",
                    "result": {
                        "ok": True,
                        "permission_error": True,
                        "permission_targets": ["music_app", "automation"],
                        "blocking_conditions": ["desktop_session_locked"],
                        "data": {"ready": False},
                    },
                },
            },
            {
                "event_type": "agent.desktop.permission_recovery",
                "payload": {
                    "step_id": "diagnose-desktop-permissions",
                    "tool": "desktop.permissions",
                    "status": "permission_recovery_available",
                    "permission_targets": ["music_app", "automation"],
                },
            },
        ],
    )

    assert outcome.kind == "completed"
    assert outcome.desktop_observed is True


def test_evaluator_accepts_successful_interactive_permission_diagnostic() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "desktop.permissions.verify",
                    "result": {
                        "ok": True,
                        "action": "desktop.permissions.verify",
                        "data": {
                            "checked": True,
                            "diagnostic_status": "verified",
                            "ready": False,
                        },
                        "permission_error": True,
                        "missing_permissions": ["automation"],
                        "permission_targets": ["automation"],
                        "recovery_actions": [
                            {
                                "label": "Open Automation settings",
                                "tool": "system.settings_open",
                            }
                        ],
                    },
                },
            },
            {
                "event_type": "agent.desktop.permission_recovery",
                "payload": {
                    "tool": "desktop.permissions.verify",
                    "status": "permission_recovery_available",
                    "permission_targets": ["automation"],
                },
            },
        ],
    )

    assert outcome.kind == "completed"
    assert outcome.desktop_observed is True


@pytest.mark.parametrize(
    "failure_evidence",
    (
        {"error": "probe_failed"},
        {"error_code": "probe_failed"},
        {"status": "failed"},
        {"approval_required": True},
    ),
)
def test_evaluator_rejects_permission_diagnostic_with_explicit_failure(
    failure_evidence: dict[str, object],
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "desktop.permissions",
                    "result": {
                        "ok": True,
                        "permission_error": True,
                        "permission_targets": ["automation"],
                        **failure_evidence,
                    },
                },
            }
        ],
    )

    assert outcome.kind == "failed"


def test_evaluator_completes_permission_diagnostic_goal_with_advisory_actions() -> None:
    run_id = "permission-diagnostic-goal"
    contract = GoalContract(
        contract_id="permission-diagnostic-contract",
        run_id=run_id,
        original_goal="检查桌面权限",
        intent_kind="desktop_operation",
        criteria=(
            GoalCriterion(
                criterion_id="permission-readiness-reported",
                description="Report desktop permission readiness",
                required_capabilities=("desktop.app_discovery",),
                source_step_ids=("diagnose-permissions",),
            ),
        ),
    )
    diagnostic_result = {
        "ok": True,
        "action": "desktop.permissions",
        "data": {
            "checked": True,
            "diagnostic_status": "verified",
            "ready": False,
            "missing_permissions": {
                "media.playback": ["music_app", "automation"],
            },
        },
        "permission_error": True,
        "missing_permissions": ["music_app", "automation"],
        "permission_targets": ["music_app", "automation"],
        "recovery_actions": [
            {
                "label": "Open Automation settings",
                "tool": "system.settings_open",
            }
        ],
    }

    outcome = evaluate_main_chat_outcome(
        {"run_id": run_id},
        [
            {
                "event_type": "agent.goal.contract",
                "run_id": run_id,
                "payload": goal_contract_event_payload(contract),
            },
            {
                "event_type": "agent.tool.call",
                "run_id": run_id,
                "payload": {
                    "tool": "desktop.permissions",
                    "tool_call_id": "permission-call",
                    "step_id": "diagnose-permissions",
                    "capability_id": "desktop.app_discovery",
                    "result": diagnostic_result,
                },
            },
        ],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "goal_contract_completed"
    assert outcome.desktop_observed is True


def test_evaluator_accepts_apple_music_search_fallback_without_claiming_playback() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "media.apple_music_play",
                    "input_preview": {"query": "超时空辉夜姬"},
                    "result": {
                        "ok": True,
                        "action": "media.apple_music_play",
                        "data": {
                            "query": "超时空辉夜姬",
                            "status": "not_found",
                            "search_opened": True,
                            "target_app": "Music",
                            "dispatch_verified": True,
                            "foreground_verified": True,
                            "search_query_verified": True,
                            "search_query_identity_verified": True,
                            "playback_started": False,
                            "outcome": "partial",
                            "user_action_required": True,
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_user_action_required"
    assert outcome.desktop_observed is True


def test_evaluator_keeps_verified_partial_handoff_after_progress_projection() -> None:
    partial_result = {
        "ok": True,
        "action": "media.apple_music_play",
        "data": {
            "query": "超时空辉夜姬",
            "status": "not_found",
            "search_opened": True,
            "target_app": "Music",
            "dispatch_verified": True,
            "foreground_verified": True,
            "search_query_verified": True,
            "search_query_identity_verified": True,
            "playback_started": False,
            "outcome": "partial",
            "user_action_required": True,
        },
    }
    events = [
        {
            "event_type": "agent.tool.call",
            "payload": {
                "tool": "media.apple_music_play",
                "tool_call_id": "call-partial-search",
                "input_preview": {"query": "超时空辉夜姬"},
                "result": partial_result,
            },
        },
        {
            "event_type": "tool.completed",
            "payload": {
                "tool": "media.apple_music_play",
                "tool_call_id": "call-partial-search",
                "status": "completed",
                "input_preview": {"query": "超时空辉夜姬"},
                "result": partial_result,
            },
        },
        {
            "event_type": "agent.task.checkpoint.updated",
            "payload": {
                "tool": "media.apple_music_play",
                "status": "completed",
            },
        },
    ]

    outcome = evaluate_main_chat_outcome({}, events)

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_user_action_required"


@pytest.mark.parametrize(
    ("override", "expected_kind"),
    [
        ({}, "completed"),
        ({"track_identity_verified": False}, "failed"),
        ({"catalog_match_verified": False}, "failed"),
        ({"player_state": "paused"}, "failed"),
        ({"playback_started": False}, "failed"),
        ({"foreground_action_taken": True}, "failed"),
    ],
)
def test_evaluator_requires_verified_background_apple_music_playback(
    override: dict[str, Any],
    expected_kind: str,
) -> None:
    data = {
        "query": "Cho Kaguya Hime",
        "status": "played",
        "track": "Cho Kaguya Hime",
        "artist": "KAF",
        "catalog_match_verified": True,
        "track_identity_verified": True,
        "player_state": "playing",
        "playback_started": True,
        "foreground_action_taken": False,
        **override,
    }
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "media.apple_music_play",
                    "input_preview": {"query": "Cho Kaguya Hime"},
                    "result": {
                        "ok": True,
                        "action": "media.apple_music_play",
                        "data": data,
                    },
                },
            }
        ],
    )

    assert outcome.kind == expected_kind
    if expected_kind == "failed":
        assert outcome.reason == "desktop_verification_missing"


def test_evaluator_accepts_trusted_catalog_playback_unverified_as_honest_partial() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "media.apple_music_play",
                    "result": {
                        "ok": True,
                        "action": "media.apple_music_play",
                        RUNTIME_EXECUTION_PROVENANCE_KEY: {
                            "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
                            "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
                        },
                        "data": {
                            "query": "Cho Kaguya Hime",
                            "status": "catalog_playback_unverified",
                            "background_safe": True,
                            "library_search_completed": True,
                            "catalog_match_verified": True,
                            "catalog_dispatch_verified": True,
                            "track_identity_verified": False,
                            "foreground_action_taken": False,
                            "target_app": "Music",
                            "search_opened": False,
                            "playback_started": False,
                            "playback_state_unverified": True,
                            "outcome": "partial",
                            "user_action_required": False,
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_background_library_not_found"


def _trusted_background_apple_music_miss_event() -> dict[str, Any]:
    return {
        "event_type": "agent.tool.call",
        "payload": {
            "tool": "media.apple_music_play",
            "tool_call_id": "initial-music",
            "input_preview": {"query": "超时空辉夜姬"},
            "result": {
                "ok": True,
                "action": "media.apple_music_play",
                RUNTIME_EXECUTION_PROVENANCE_KEY: {
                    "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
                    "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
                },
                "data": {
                    "query": "超时空辉夜姬",
                    "status": "not_found",
                    "background_safe": True,
                    "library_search_completed": True,
                    "foreground_action_taken": False,
                    "target_app": "Music",
                    "search_opened": False,
                    "playback_started": False,
                    "outcome": "partial",
                    "user_action_required": False,
                },
            },
        },
    }


@pytest.mark.parametrize(
    "recovery_events",
    [
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "browser.search",
                    "tool_call_id": "apple-music-alias-search-1",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_search",
                    "input_preview": {
                        "query": "超时空辉夜姬 Apple Music English title"
                    },
                    "result": {
                        "ok": False,
                        "action": "browser.search",
                        "error": "cdp_unavailable",
                    },
                },
            }
        ],
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "browser.search",
                    "tool_call_id": "apple-music-alias-search-1",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_search",
                    "input_preview": {
                        "query": "超时空辉夜姬 Apple Music English title"
                    },
                    "result": {
                        "ok": True,
                        "action": "browser.search",
                        "data": {"target_owned_by_run": True},
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "browser.extract_text",
                    "tool_call_id": "apple-music-alias-extract-1",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_extract",
                    "input_preview": {},
                    "result": {
                        "ok": False,
                        "action": "browser.extract_text",
                        "error": "page_unavailable",
                    },
                },
            },
        ],
    ],
    ids=("search-failed", "extract-failed"),
)
def test_evaluator_preserves_background_apple_music_partial_when_optional_alias_evidence_fails(
    recovery_events: list[dict[str, Any]],
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [_trusted_background_apple_music_miss_event(), *recovery_events],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_background_library_not_found"
    assert outcome.desktop_observed is True


def test_evaluator_preserves_background_apple_music_partial_for_iteration_zero_alias_recovery() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            _trusted_background_apple_music_miss_event(),
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "browser.search",
                    "tool_call_id": "apple-music-alias-search-0",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_search",
                    "input_preview": {
                        "query": "超时空辉夜姬 Apple Music English title"
                    },
                    "result": {"ok": True, "action": "browser.search"},
                },
            },
            {
                "event_type": "agent.tool.failed",
                "payload": {
                    "tool": "browser.extract_text",
                    "tool_call_id": "apple-music-alias-extract-0",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_extract",
                    "status": "failed",
                    "input_preview": {},
                    "result": {
                        "ok": False,
                        "action": "browser.extract_text",
                        "error": "page_unavailable",
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_background_library_not_found"


def test_evaluator_binds_scoped_alias_search_and_extract_ids() -> None:
    scope = "0123456789ab"
    outcome = evaluate_main_chat_outcome(
        {},
        [
            _trusted_background_apple_music_miss_event(),
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "browser.search",
                    "tool_call_id": f"apple-music-alias-search-1-{scope}",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_search",
                    "input_preview": {
                        "query": "超时空辉夜姬 Apple Music English title"
                    },
                    "result": {"ok": True, "action": "browser.search"},
                },
            },
            {
                "event_type": "agent.tool.failed",
                "payload": {
                    "tool": "browser.extract_text",
                    "tool_call_id": f"apple-music-alias-extract-1-{scope}",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_extract",
                    "status": "failed",
                    "input_preview": {},
                    "result": {
                        "ok": False,
                        "action": "browser.extract_text",
                        "error": "page_unavailable",
                    },
                },
            },
        ],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_background_library_not_found"


def test_evaluator_rejects_alias_extract_bound_to_different_scope() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            _trusted_background_apple_music_miss_event(),
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "browser.search",
                    "tool_call_id": "apple-music-alias-search-1-0123456789ab",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_search",
                    "input_preview": {
                        "query": "超时空辉夜姬 Apple Music English title"
                    },
                    "result": {"ok": True, "action": "browser.search"},
                },
            },
            {
                "event_type": "agent.tool.failed",
                "payload": {
                    "tool": "browser.extract_text",
                    "tool_call_id": "apple-music-alias-extract-1-bbbbbbbbbbbb",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_extract",
                    "status": "failed",
                    "input_preview": {},
                    "result": {"ok": False, "error": "page_unavailable"},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_tool_failed"


@pytest.mark.parametrize(
    "tool_call_id",
    ["apple-music-alias-search-00", "apple-music-alias-search--1"],
    ids=("leading-zero", "negative"),
)
def test_evaluator_rejects_noncanonical_apple_music_alias_iteration_ids(
    tool_call_id: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            _trusted_background_apple_music_miss_event(),
            {
                "event_type": "agent.tool.failed",
                "payload": {
                    "tool": "browser.search",
                    "tool_call_id": tool_call_id,
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_search",
                    "input_preview": {
                        "query": "超时空辉夜姬 Apple Music English title"
                    },
                    "result": {"ok": False, "error": "cdp_unavailable"},
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_tool_failed"


@pytest.mark.parametrize(
    ("failure_event", "expected_reason"),
    [
        (
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "browser.search",
                    "tool_call_id": "ordinary-browser-search",
                    "input_preview": {"query": "超时空辉夜姬"},
                    "result": {"ok": False, "error": "cdp_unavailable"},
                },
            },
            "desktop_tool_failed",
        ),
        (
            {
                "event_type": "agent.tool.failed",
                "payload": {
                    "tool": "browser.search",
                    "tool_call_id": "apple-music-alias-search-1",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_search",
                    "input_preview": {
                        "query": "unrelated Apple Music English title"
                    },
                    "result": {"ok": False, "error": "cdp_unavailable"},
                },
            },
            "desktop_tool_failed",
        ),
        (
            {
                "event_type": "agent.tool.failed",
                "payload": {
                    "tool": "browser.extract_text",
                    "tool_call_id": "apple-music-alias-extract-1",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_evidence_extract",
                    "input_preview": {},
                    "result": {"ok": False, "error": "page_unavailable"},
                },
            },
            "desktop_tool_failed",
        ),
        (
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "browser.search",
                    "tool_call_id": "apple-music-alias-search-1",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "some_other_internal_recovery",
                    "input_preview": {
                        "query": "超时空辉夜姬 Apple Music English title"
                    },
                    "result": {"ok": False, "error": "cdp_unavailable"},
                },
            },
            "desktop_tool_failed",
        ),
        (
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "media.apple_music_play",
                    "tool_call_id": "apple-music-alias-play-1",
                    "source": "runtime_internal_recovery",
                    "planning_reason": "apple_music_alias_retry",
                    "input_preview": {"query": "Cho Kaguya Hime"},
                    "result": {
                        "ok": False,
                        "permission_error": True,
                        "permission_targets": ["automation"],
                        "error": "Music Automation denied",
                    },
                },
            },
            "desktop_permission_required",
        ),
    ],
    ids=(
        "ordinary-browser",
        "wrong-alias-search-query",
        "unbound-alias-extract",
        "other-internal-recovery",
        "final-media-retry",
    ),
)
def test_evaluator_keeps_nonoptional_failures_after_background_apple_music_partial_fail_closed(
    failure_event: dict[str, Any],
    expected_reason: str,
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [_trusted_background_apple_music_miss_event(), failure_event],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == expected_reason


def test_evaluator_rejects_unprovenanced_background_apple_music_library_miss() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "media.apple_music_play",
                    "result": {
                        "ok": True,
                        "action": "media.apple_music_play",
                        "data": {
                            "status": "not_found",
                            "background_safe": True,
                            "library_search_completed": True,
                            "foreground_action_taken": False,
                            "target_app": "Music",
                            "search_opened": False,
                            "playback_started": False,
                            "outcome": "partial",
                            "user_action_required": False,
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_accepts_verified_music_search_after_user_moves_focus() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "media.apple_music_play",
                    "result": {
                        "ok": True,
                        "action": "media.apple_music_play",
                        "data": {
                            "status": "not_found",
                            "search_opened": True,
                            "target_app": "Music",
                            "dispatch_verified": True,
                            "foreground_verified": False,
                            "focus_changed_after_search": True,
                            "search_query_verified": True,
                            "search_result_changed_from_nonmatching_baseline": True,
                            "playback_started": False,
                            "outcome": "partial",
                            "user_action_required": True,
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_user_action_required"


def test_evaluator_rejects_legacy_apple_music_partial_without_causal_query_evidence() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "media.apple_music_play",
                    "result": {
                        "ok": True,
                        "action": "media.apple_music_play",
                        "data": {
                            "status": "not_found",
                            "search_opened": True,
                            "target_app": "Music",
                            "dispatch_verified": True,
                            "foreground_verified": True,
                            "search_query_verified": True,
                            "playback_started": False,
                            "outcome": "partial",
                            "user_action_required": True,
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


@pytest.mark.parametrize(
    ("result_override", "expected_reason"),
    [
        ({"ok": False}, "desktop_tool_failed"),
        ({"data": {"status": "error"}}, "desktop_verification_missing"),
        ({"data": {"search_opened": False}}, "desktop_verification_missing"),
        ({"data": {"dispatch_verified": False}}, "desktop_verification_missing"),
        ({"data": {"foreground_verified": False}}, "desktop_verification_missing"),
        ({"data": {"search_query_verified": False}}, "desktop_verification_missing"),
        ({"data": {"target_app": "Finder"}}, "desktop_verification_missing"),
        ({"error": "Music returned stale search state"}, "desktop_verification_missing"),
        ({"permission_error": True}, "desktop_permission_required"),
        ({"permission_targets": ["automation"]}, "desktop_permission_required"),
        ({"missing_permissions": ["automation"]}, "desktop_permission_required"),
        ({"blocking_conditions": ["search_ui_unverified"]}, "desktop_verification_failed"),
    ],
)
def test_evaluator_does_not_overgeneralize_apple_music_partial_completion(
    result_override: dict[str, Any],
    expected_reason: str,
) -> None:
    data = {
        "status": "not_found",
        "search_opened": True,
        "target_app": "Music",
        "dispatch_verified": True,
        "foreground_verified": True,
        "search_query_verified": True,
        "search_query_identity_verified": True,
        "playback_started": False,
        "outcome": "partial",
        "user_action_required": True,
    }
    override_data = result_override.get("data")
    if isinstance(override_data, dict):
        data.update(override_data)
    result = {
        "ok": True,
        "action": "media.apple_music_play",
        "data": data,
        **{key: value for key, value in result_override.items() if key != "data"},
    }

    outcome = evaluate_main_chat_outcome(
        {},
        [{"event_type": "agent.tool.call", "payload": {"tool": "media.apple_music_play", "result": result}}],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == expected_reason


def test_evaluator_does_not_let_apple_music_partial_hide_other_unverified_action() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "open-notes",
                    "tool": "app.open",
                    "input_preview": {"app_name": "Notes"},
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "action": "app.open",
                        "data": {"app_name": "Notes"},
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "search-apple-music",
                    "tool": "media.apple_music_play",
                    "input_preview": {"query": "超时空辉夜姬"},
                    "result": {
                        "ok": True,
                        "action": "media.apple_music_play",
                        "data": {
                            "query": "超时空辉夜姬",
                            "status": "not_found",
                            "search_opened": True,
                            "target_app": "Music",
                            "dispatch_verified": True,
                            "foreground_verified": True,
                            "search_query_verified": True,
                            "search_query_identity_verified": True,
                            "playback_started": False,
                            "outcome": "partial",
                            "user_action_required": True,
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_evaluator_does_not_let_apple_music_partial_hide_permission_warning() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "desktop.permissions",
                    "result": {
                        "ok": True,
                        "permission_targets": ["automation"],
                        "affected_tools": ["media.apple_music_play"],
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "media.apple_music_play",
                    "result": {
                        "ok": True,
                        "action": "media.apple_music_play",
                        "data": {
                            "query": "超时空辉夜姬",
                            "status": "not_found",
                            "search_opened": True,
                            "target_app": "Music",
                            "dispatch_verified": True,
                            "foreground_verified": True,
                            "search_query_verified": True,
                            "search_query_identity_verified": True,
                            "playback_started": False,
                            "outcome": "partial",
                            "user_action_required": True,
                        },
                    },
                },
            },
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_permission_required"


@pytest.mark.parametrize(
    "events",
    [
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "desktop.permissions",
                    "result": {
                        "ok": False,
                        "permission_error": True,
                        "permission_targets": ["automation"],
                    },
                },
            }
        ],
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "desktop.permissions.verify",
                    "result": {
                        "ok": False,
                        "permission_error": True,
                        "permission_targets": ["automation"],
                    },
                },
            }
        ],
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "desktop.permissions",
                    "result": {
                        "ok": True,
                        "permission_error": True,
                        "permission_targets": ["automation"],
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "media.apple_music_play",
                    "result": {
                        "ok": False,
                        "permission_error": True,
                        "permission_targets": ["automation"],
                    },
                },
            },
        ],
    ],
    ids=(
        "passive-diagnostic-call-failed",
        "interactive-diagnostic-call-failed",
        "desktop-action-failed",
    ),
)
def test_evaluator_does_not_let_permission_diagnostic_hide_failure(
    events: list[dict[str, Any]],
) -> None:
    outcome = evaluate_main_chat_outcome({}, events)

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_permission_required"


def test_evaluator_ignores_non_desktop_tool_in_broad_desktop_event_namespace() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.desktop.intent_planned",
                "payload": {
                    "tool": "workspace.write_patch",
                    "requires_post_action_verification": True,
                },
            }
        ],
    )

    assert outcome.kind == "completed"
    assert outcome.desktop_observed is False


class _TimelineFallbackRuntime(_ExecutorRuntime):
    def __init__(self, timeline: list[dict[str, Any]]) -> None:
        super().__init__([])
        self.timeline = timeline

    def get_run(self, _run_id: str) -> dict[str, Any]:
        self.calls.append("get_run")
        return {
            "run_id": "main-chat-outcome-1",
            "kind": "main_chat_run",
            "status": self.status,
            "result": self.result,
            "pending_approval": {},
            "timeline": list(self.timeline),
        }

    def list_run_events(self, _run_id: str, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("list_events")
        raise RuntimeError("event store temporarily unavailable")


@pytest.mark.asyncio
async def test_executor_does_not_fall_back_to_stale_timeline_when_event_listing_fails() -> None:
    runtime = _TimelineFallbackRuntime(
        [_desktop_event({"ok": False, "error_code": "app_not_found"})]
    )
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("打开不存在的应用"))

    assert exc_info.value.reason == "outcome_event_history_incomplete"
    assert "complete" not in runtime.calls
    assert runtime.calls.count("fail") == 1


@pytest.mark.asyncio
async def test_executor_uses_run_timeline_when_event_listing_is_unavailable() -> None:
    runtime = _TimelineFallbackRuntime(
        [_desktop_event({"ok": False, "error_code": "app_not_found"})]
    )
    runtime.list_run_events = None  # type: ignore[method-assign]
    executor = NativeAgentExecutor(runtime_service_getter=lambda: runtime)

    with pytest.raises(NativeAgentError) as exc_info:
        await executor.run(_task("打开不存在的应用"))

    assert exc_info.value.reason == "desktop_tool_failed"
    assert "list_events" not in runtime.calls
    assert "complete" not in runtime.calls
    assert runtime.calls.count("fail") == 1


class _LegacyRuntime:
    def __init__(self) -> None:
        self.complete_calls: list[tuple[str, str]] = []
        self.fail_calls: list[tuple[str, str]] = []
        self.status = "running"

    def complete_main_chat_run(self, run_id: str, result: str) -> dict[str, Any]:
        self.complete_calls.append((run_id, result))
        return {
            "run_id": run_id,
            "kind": "main_chat_run",
            "status": "completed",
            "result": result,
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "kind": "main_chat_run", "status": self.status}

    def fail_main_chat_run(self, run_id: str, error: Any) -> dict[str, Any]:
        self.status = "failed"
        self.fail_calls.append((run_id, str(error)))
        return {
            "run_id": run_id,
            "kind": "main_chat_run",
            "status": "failed",
            "result": str(error),
        }


def _legacy_payload(*, pending_approval: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "run_id": "legacy-main-outcome-1",
        "kind": "main_chat_run",
        "status": "approval_required" if pending_approval else "running",
        "result": "已继续执行。",
        "pending_approval": pending_approval or {},
        "timeline": [
            {
                "event": "agent.desktop.intent_completed",
                "source": "runtime_planner",
                "tool": "app.open",
                "result": {
                    "ok": False,
                    "permission_error": True,
                    "permission_targets": ["accessibility"],
                },
                "summary": "需要权限才能继续。",
            }
        ],
    }


def test_legacy_approval_resume_does_not_trust_failed_intent_completed_event() -> None:
    runtime = _LegacyRuntime()
    port = LegacyRuntimePort(runtime)
    payload = _legacy_payload()

    projected = port._complete_main_chat_daily_desktop_approval_if_ready(
        payload["run_id"],
        payload,
    )

    assert projected["status"] == "failed"
    assert runtime.complete_calls == []
    assert len(runtime.fail_calls) == 1
    assert "系统权限" in runtime.fail_calls[0][1]


def test_legacy_approval_required_remains_pending() -> None:
    runtime = _LegacyRuntime()
    port = LegacyRuntimePort(runtime)
    payload = _legacy_payload(
        pending_approval={"approval_id": "approval-1", "tool": "app.open"}
    )

    projected = port._complete_main_chat_daily_desktop_approval_if_ready(
        payload["run_id"],
        payload,
    )

    assert projected["status"] == "approval_required"
    assert projected["pending_approval"]["approval_id"] == "approval-1"
    assert runtime.complete_calls == []
    assert runtime.fail_calls == []


def test_legacy_approval_resume_does_not_fail_while_desktop_action_is_only_planned() -> None:
    runtime = _LegacyRuntime()
    port = LegacyRuntimePort(runtime)
    payload = {
        "run_id": "legacy-main-outcome-planned",
        "kind": "main_chat_run",
        "status": "running",
        "result": "已批准，正在继续执行。",
        "pending_approval": {},
        "timeline": [
            {
                "event": "agent.desktop.intent_planned",
                "source": "runtime_planner",
                "tool": "app.open",
                "requires_post_action_verification": True,
                "status": "planned",
            }
        ],
    }

    projected = port._complete_main_chat_daily_desktop_approval_if_ready(
        payload["run_id"],
        payload,
    )

    assert projected == payload
    assert runtime.complete_calls == []
    assert runtime.fail_calls == []


class _LegacyFreshApprovalRuntime(_LegacyRuntime):
    def get_run(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "kind": "main_chat_run",
            "status": "approval_required",
            "result": "等待新的验证审批。",
            "pending_approval": {
                "approval_id": "approval-new",
                "tool": "desktop.verify",
            },
        }


def test_legacy_gate_refreshes_run_and_preserves_new_approval_before_action() -> None:
    runtime = _LegacyFreshApprovalRuntime()
    port = LegacyRuntimePort(runtime)
    stale_payload = _legacy_payload()

    projected = port._complete_main_chat_daily_desktop_approval_if_ready(
        stale_payload["run_id"],
        stale_payload,
    )

    assert projected["status"] == "approval_required"
    assert projected["pending_approval"]["approval_id"] == "approval-new"
    assert runtime.complete_calls == []
    assert runtime.fail_calls == []
